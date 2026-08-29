# srAgentCloud

A self-hostable AI coding agent with a web UI. Chat with an LLM that can read, edit, and run code in sandboxed project directories - powered by NVIDIA NIM using Kimi K3, and runnable on a Raspberry Pi Zero.

See blog post [here](https://lucasalvo.com/post/building-a-simple-coding-agent-on-a-raspberry-pi-zero) for the motivation behind this project.

This builds off of [srAgent](https://github.com/Midnight-Owl-1/srAgent), which is a very simple Coding Agent that runs in your CLI at only 220 lines of easy-to-read python code.

![Image of the app running](http://lucasalvo.com/images/21Mar2026/front-shot.png)

## Features

- **Multi-project / multi-thread** — organize conversations by project and topic
- **Tool-use agent** — the LLM can read files, edit files, list directories, run Python, install packages, search code, and run/stop project processes
- **One-click Run** — add a `run.sh` to your project and a ▶ Run Project button appears in the UI
- **Real-time SSE streaming** — see thoughts, tool calls, and results as they happen
- **Tool approval** — every tool call requires your explicit approve / deny before executing
- **File browser** — upload, download, and delete project files from the UI
- **Admin panel** — manage projects, threads, and messages; configure API settings
- **First-run setup** — automatically prompts for your API key on first launch

## Quick Start

On a fresh raspbery pi zero (or any other linux device):

```bash
# Ensure that you're in the home directory
cd ~/

# Clone the repo
git clone https://github.com/Midnight-Owl-1/srAgentCloud.git && cd srAgentCloud

# Create a new venv for the project
python -m venv venv

# Activate it
. venv/bin/activate

# Install dependencies into the venv
pip install -r requirements.txt

# Start the server
bash run.sh
```

On first launch, if no API key is configured you will be redirected to the Admin settings page to enter your **NVIDIA API key**.
- Create one in the [NVIDIA API Catalog](https://build.nvidia.com/settings/api-keys), then copy the generated key.

The app runs at **http://{IP_ADDRESS_OF_DEVICE}**.

This is a progresive web app, so if you know how to give it an SSL certificate (for https), you can 'install' it like any app on your phone.

## Configuration

Settings are stored in `src/config.json` (auto-created from `config.example.json` on first run).

| Key | Description |
|---|---|
| `provider` | Selected provider (default: `nvidia`). |
| `base_url` | Provider chat-completions endpoint. It is automatically set for supported providers; enter it manually for a custom provider. |
| `api_key` | API key for the selected provider. |
| `model` | Model identifier for the selected provider (default: `moonshotai/kimi-k3`). |

The **Admin → ⚙ Settings** modal includes NVIDIA NIM, OpenAI, OpenRouter, Groq, Together AI, Mistral AI, DeepSeek, xAI, Cerebras, and Fireworks AI. Select **Personalizado** to use any OpenAI-compatible provider by entering its chat-completions base URL, API key, and model.

You can change these at any time from the **Admin → ⚙ Settings** modal, or by editing `src/config.json` directly.

## Tools Available to the Agent

| Tool | Description |
|---|---|
| `read_file` | Read the contents of a file (supports line ranges) |
| `edit_file` | Write or replace content in a file |
| `list_dir` | List files and directories at a given path |
| `python_tool` | Run Python code in the project's virtual environment |
| `code_search` | Search for code patterns using ripgrep-style regex |
| `pip_install` | Install packages into the project's venv |
| `run_project` | Run a script inside the project with the venv activated |
| `stop_process` | Stop a running process by PID |

## Creating a New Project

- Click **+** in the sidebar to create a project
- Each project gets its own directory under `projects/` with an isolated Python venv
- The agent can install packages, run scripts, and manage files within that sandbox
- You can open multiple "threads" for a project (to get a fresh agent to work on the project) - helps prevent context window bloat

## Project Structure

```
srAgentCloud/
├── src/
│   ├── app.py                 # Flask entry point — creates and starts the server
│   ├── config.py              # Configuration paths, read/write config.json helpers
│   ├── database.py            # SQLite database setup, connection helper, save_message()
│   ├── state.py               # Shared runtime state — SSE broadcaster, process tracking
│   ├── tools.py               # Agent tool definitions and execution logic
│   ├── agent.py               # Agentic loop — LLM calls, response parsing, SSE push
│   ├── routes.py              # All Flask API endpoints and SSE streaming
│   ├── agent.md               # System prompt / instructions for the LLM agent
│   ├── config.example.json    # Template config (copy to config.json on first run)
│   ├── templates/
│   │   ├── index.html         # Main chat UI layout and markup
│   │   └── admin.html         # Admin panel for DB management and settings
│   └── static/
│       ├── index.js           # Chat UI logic — SSE, tool approval, processes, rendering
│       ├── index.css           # Styles for the main chat interface
│       ├── admin.css           # Styles for the admin panel
│       └── favicon.png        # App icon
├── projects/                  # Sandboxed project directories (created at runtime)
├── requirements.txt           # Python dependencies
├── run.sh                     # Start script (cd src && python app.py)
└── README.md
```
