import json
import requests

from config import MAX_ITERATIONS, AGENT_MD, read_config
from database import save_message
from state import get_state
from tools import TOOLS, execute_tool

# ─── LLM helpers ──────────────────────────────────────────────────────────────

def build_system_prompt(project_path: str) -> str:
    with open(AGENT_MD, "r", encoding="utf-8") as f:
        base = f.read()

    tools_docs = ""
    for name, info in TOOLS.items():
        tools_docs += f"- {name}({', '.join(info['parameters'])})\n"
        tools_docs += f"    Description: {info['description']}\n"
        tools_docs += f"    Example: {info['example']}\n"

    prompt = base.replace("{{{INSERT_TOOL_DESCRIPTION_HERE}}}", tools_docs)

    prompt += f"""

## Project Context

Your current working directory is: `{project_path}`

All tool calls automatically run with this as the working directory, so you can use **relative paths** (e.g. `app.py`, `src/main.py`) or absolute paths — both work.

- Use `edit_file("app.py", "...", "")` to create or overwrite a file in the project
- Use `read_file("app.py", "", "")` to read a file
- Use `list_dir(".")` to list the project folder
- Use `run_project("app.py")` to run a script using the project venv
- Use `pip_install("flask requests")` to install packages into the project venv

If the project has a `run.sh` script, the user can also run it directly from the UI button (it sources the venv and executes the script).
"""
    return prompt

def call_llm(messages: list) -> str:
    cfg = read_config()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":           cfg["model"],
        "messages":        messages,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"]
    return json.dumps({"actions": [{"type": "complete", "content": f"LLM error {resp.status_code}: {resp.text}"}]})

def parse_response(response: str) -> list:
    try:
        response = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(response)
        return data.get("actions", [])
    except Exception as e:
        return [{"type": "thought", "content": f"Failed to parse response: {e}"}]

# ─── SSE push helpers ─────────────────────────────────────────────────────────

def push_sse(thread_id: int, msg_type: str, content: str):
    state = get_state(thread_id)
    state["broadcaster"].push({"type": msg_type, "content": content})

def clear_pending_tool_state(state: dict):
    state["pending_tool"] = None
    state["tool_decision"] = None
    state["tool_event"].clear()

def complete_agent_run(thread_id: int, content: str):
    state = get_state(thread_id)
    clear_pending_tool_state(state)
    save_message(thread_id, "assistant", "complete", content)
    push_sse(thread_id, "complete", content)
    push_sse(thread_id, "done", "")
    state["broadcaster"].clear_buffer()

# ─── Agent loop (runs in background thread) ───────────────────────────────────

def run_agent(thread_id: int, project_path: str, messages: list):
    state = get_state(thread_id)
    state["agent_running"] = True
    state["stop_requested"] = False

    try:
        iters = 0
        while iters < MAX_ITERATIONS:
            if state["stop_requested"]:
                complete_agent_run(thread_id, "Agent stopped by user.")
                return

            raw = call_llm(messages)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            messages.append({"role": "assistant", "content": raw})

            actions = parse_response(raw)
            tool_results = []

            for item in actions:
                if state["stop_requested"]:
                    complete_agent_run(thread_id, "Agent stopped by user.")
                    return

                atype   = item.get("type", "thought")
                content = item.get("content", "")

                if atype == "thought":
                    save_message(thread_id, "assistant", "thought", content)
                    push_sse(thread_id, "thought", content)

                elif atype == "tool":
                    state["pending_tool"] = content
                    state["tool_decision"] = None
                    state["tool_event"].clear()

                    save_message(thread_id, "assistant", "tool", content)
                    push_sse(thread_id, "tool", content)

                    got_decision = state["tool_event"].wait(timeout=300)
                    decision = state["tool_decision"] if got_decision else "deny"

                    if decision == "stop":
                        result = "Tool call canceled. Agent stopped by user."
                        save_message(thread_id, "assistant", "tool_result", result)
                        push_sse(thread_id, "tool_result", result)
                        complete_agent_run(thread_id, "Agent stopped by user.")
                        return

                    if decision != "approve":
                        result = "Tool call denied by user."
                    else:
                        result = execute_tool(content, project_path)

                    save_message(thread_id, "assistant", "tool_result", result)
                    push_sse(thread_id, "tool_result", result)

                    clear_pending_tool_state(state)
                    tool_results.append(f"RESULT OF {content}:\n{result}")

                elif atype == "complete":
                    complete_agent_run(thread_id, content)
                    return

                else:
                    # Agent used an unrecognised action type — correct it
                    with open(AGENT_MD, "r", encoding="utf-8") as f:
                        agent_md = f.read()
                    correction = (
                        f'Your last response contained an invalid action type: "{atype}". '
                        f'You must only use "thought", "tool", or "complete". '
                        f'Here is your instruction reference:\n\n{agent_md}'
                    )
                    save_message(thread_id, "assistant", "thought",
                                 f'⚠️ Invalid action type used: "{atype}". Correcting…')
                    push_sse(thread_id, "thought",
                             f'⚠️ Invalid action type used: "{atype}". Correcting…')
                    tool_results.append(correction)

            if tool_results:
                messages.append({"role": "user", "content": "\n\n".join(tool_results)})

            iters += 1

        complete_agent_run(thread_id, "Max iterations reached.")
    finally:
        state["agent_running"] = False
        state["stop_requested"] = False
        clear_pending_tool_state(state)
