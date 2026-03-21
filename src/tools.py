import os
import sys
import re
import ast
import subprocess
import threading
import time
from datetime import datetime

from config import PROJECTS_DIR
from state import _running_processes, _proc_lock

# ─── Tool registry ────────────────────────────────────────────────────────────

TOOLS: dict = {}

def tool(name, params, description, example):
    def decorator(func):
        TOOLS[name] = {"function": func, "parameters": params, "description": description, "example": example}
        return func
    return decorator

def resolve_path(path: str, project_path: str) -> str:
    """If path is relative, make it absolute under project_path."""
    if os.path.isabs(path):
        return path
    return os.path.join(project_path, path)

def execute_tool(tool_content: str, project_path: str) -> str:
    match = re.match(r"(\w+)\((.*)\)", tool_content, re.DOTALL)
    if not match:
        return "Error: Invalid tool format."
    tool_name, params_str = match.group(1), match.group(2)
    if tool_name not in TOOLS:
        return f"Error: Tool '{tool_name}' not found."
    try:
        params = ast.literal_eval(f"({params_str},)")
    except Exception as e:
        return f"Error parsing parameters: {e}"
    try:
        return TOOLS[tool_name]["function"](*params, _project_path=project_path)
    except TypeError:
        return TOOLS[tool_name]["function"](*params)

def _get_project_name(project_path: str) -> str:
    """Derive a project name from its path by matching against the projects directory."""
    return os.path.basename(project_path) if project_path else "unknown"

# ─── Tool implementations ─────────────────────────────────────────────────────

class Tools:
    @staticmethod
    @tool("read_file", ["path", "start_line", "end_line"],
          "Read a file's contents. Accepts relative paths (resolved from the project directory) or absolute paths. Pass empty strings for start_line/end_line to read the whole file.",
          'read_file("app.py", "", "") or read_file("app.py", "10", "20")')
    def read_file(path, start_line="", end_line="", _project_path=None, **_):
        try:
            full = resolve_path(path, _project_path) if _project_path else path
            with open(full, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if start_line or end_line:
                s = int(start_line) - 1 if start_line else 0
                e = int(end_line) if end_line else len(lines)
                lines = lines[s:e]
            return "".join(lines)
        except Exception as e:
            return f"Error [{type(e).__name__}]: {e}"

    @staticmethod
    @tool("list_dir", ["path"],
          "List files and directories. Use '.' to list the project root. Accepts relative or absolute paths.",
          'list_dir(".") or list_dir("src")')
    def list_dir(path, _project_path=None, **_):
        try:
            full = resolve_path(path, _project_path) if _project_path else path
            entries = []
            for name in os.listdir(full):
                entries.append(name + "/" if os.path.isdir(os.path.join(full, name)) else name)
            return "\n".join(entries)
        except Exception as e:
            return f"Error [{type(e).__name__}]: {e}"

    @staticmethod
    @tool("python_tool", ["code", "filepath"],
          "Execute a Python snippet or script using the project's venv Python. Runs with the project directory as CWD. Pass code as string and leave filepath empty, or pass empty code and a relative/absolute filepath.",
          'python_tool("print(1+1)", "") or python_tool("", "script.py")')
    def python_tool(code, filepath="", _project_path=None, **_):
        try:
            cwd = _project_path or None
            python_exe = sys.executable
            if _project_path:
                if sys.platform == "win32":
                    venv_python = os.path.join(_project_path, "venv", "Scripts", "python.exe")
                else:
                    venv_python = os.path.join(_project_path, "venv", "bin", "python")
                if os.path.exists(venv_python):
                    python_exe = venv_python
            if filepath:
                full = resolve_path(filepath, _project_path) if _project_path else filepath
                cmd = [python_exe, full]
            else:
                cmd = [python_exe, "-c", code]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
            out = result.stdout
            if result.stderr:
                out += "\nSTDERR:\n" + result.stderr
            return out.strip() or "(no output)"
        except Exception as e:
            return f"Error [{type(e).__name__}]: {e}"

    @staticmethod
    @tool("edit_file", ["path", "new_content", "old_string"],
          "Edit a file. Accepts relative paths (from project root) or absolute. If old_string is provided, replaces its first occurrence with new_content. If old_string is empty, overwrites the entire file.",
          'edit_file("app.py", "full file content", "") or edit_file("app.py", "new line", "old line")')
    def edit_file(path, new_content, old_string="", _project_path=None, **_):
        try:
            full = resolve_path(path, _project_path) if _project_path else path
            if old_string:
                with open(full, "r", encoding="utf-8") as f:
                    content = f.read()
                if old_string not in content:
                    return "Error: old_string not found in file."
                content = content.replace(old_string, new_content, 1)
            else:
                content = new_content
            os.makedirs(os.path.dirname(os.path.abspath(full)), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            return f"File updated successfully: {full}"
        except Exception as e:
            return f"Error [{type(e).__name__}]: {e}"

    @staticmethod
    @tool("code_search", ["pattern", "path"],
          "Search for a regex pattern across files. Use '.' to search the whole project. Accepts relative or absolute paths.",
          'code_search("def main", ".") or code_search("import flask", "src")')
    def code_search(pattern, path, _project_path=None, **_):
        full = resolve_path(path, _project_path) if _project_path else path
        matches = []
        for root, _, files in os.walk(full):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if re.search(pattern, line):
                                matches.append(f"{fpath}:{i}: {line.rstrip()}")
                except Exception:
                    continue
        return "\n".join(matches) or "No matches found."

    @staticmethod
    @tool("run_project", ["script_path"],
          "Run a script using the project's venv Python. If it's a long-running process (like a web server), it will continue in the background and return a PID. Use '.' or relative paths.",
          'run_project("app.py") or run_project("src/main.py")')
    def run_project(script_path, _project_path=None, **_):
        try:
            project_path = _project_path or os.path.dirname(os.path.abspath(script_path))
            full_script  = resolve_path(script_path, project_path)
            if sys.platform == "win32":
                venv_python = os.path.join(project_path, "venv", "Scripts", "python.exe")
            else:
                venv_python = os.path.join(project_path, "venv", "bin", "python")
            if not os.path.exists(venv_python):
                return f"Error: venv not found at {venv_python}."

            proc = subprocess.Popen(
                [venv_python, full_script],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=project_path,
                bufsize=1, universal_newlines=True
            )

            output_log = []
            def drain(stream, label):
                for line in stream:
                    output_log.append(f"[{label}] {line.strip()}")
                    if len(output_log) > 500: output_log.pop(0)

            threading.Thread(target=drain, args=(proc.stdout, "STDOUT"), daemon=True).start()
            threading.Thread(target=drain, args=(proc.stderr, "STDERR"), daemon=True).start()

            time.sleep(2)
            if proc.poll() is not None:
                return f"Process finished early.\nLOG:\n" + "\n".join(output_log)

            with _proc_lock:
                _running_processes[proc.pid] = {
                    "popen": proc,
                    "project": _get_project_name(project_path),
                    "script": script_path,
                    "started_at": datetime.now().strftime("%d-%b-%Y at %H:%M:%S")
                }
            return f"Process started in background (PID: {proc.pid}).\nInitial Output:\n" + "\n".join(output_log)
        except Exception as e:
            return f"Error [{type(e).__name__}]: {e}"

    @staticmethod
    @tool("stop_process", ["pid"],
          "Stop a background process by its PID.",
          'stop_process(12345)')
    def stop_process(pid, **_):
        try:
            pid = int(pid)
            with _proc_lock:
                if pid not in _running_processes:
                    return f"Error: Process with PID {pid} not found in tracked registry."
                proc_info = _running_processes.pop(pid)
                proc = proc_info["popen"]
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return f"Process {pid} stopped."
        except Exception as e:
            return f"Error stopping process: {e}"

    @staticmethod
    @tool("pip_install", ["packages"],
          "Install one or more Python packages into the project's venv using pip. Pass package names as a space-separated string.",
          'pip_install("flask") or pip_install("requests pandas numpy")')
    def pip_install(packages, _project_path=None, **_):
        try:
            if not _project_path:
                return "Error: no project path available."
            if sys.platform == "win32":
                venv_pip = os.path.join(_project_path, "venv", "Scripts", "pip.exe")
            else:
                venv_pip = os.path.join(_project_path, "venv", "bin", "pip")
            if not os.path.exists(venv_pip):
                return f"Error: venv pip not found at {venv_pip}."
            pkg_list = packages.split()
            result = subprocess.run(
                [venv_pip, "install"] + pkg_list,
                capture_output=True, text=True, timeout=120,
                cwd=_project_path
            )
            out = result.stdout
            if result.stderr:
                out += "\nSTDERR:\n" + result.stderr
            return out.strip() or "(no output)"
        except Exception as e:
            return f"Error [{type(e).__name__}]: {e}"

# Instantiate to register all tools
_tools_instance = Tools()
