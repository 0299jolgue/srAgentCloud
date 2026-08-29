import os
import json
import shutil

MAX_ITERATIONS = 10
LLM_REQUESTS_PER_MINUTE = 40
LLM_MAX_RETRIES = 3

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "projects"))
AGENT_MD     = os.path.join(BASE_DIR, "agent.md")
DB_PATH      = os.path.join(BASE_DIR, "sragent.db")
CONFIG_PATH  = os.path.join(BASE_DIR, "config.json")
CONFIG_EXAMPLE = os.path.join(BASE_DIR, "config.example.json")

os.makedirs(PROJECTS_DIR, exist_ok=True)

# Auto-create config.json from example on first run
if not os.path.exists(CONFIG_PATH) and os.path.exists(CONFIG_EXAMPLE):
    shutil.copy2(CONFIG_EXAMPLE, CONFIG_PATH)

def read_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"api_key": "", "model": ""}

def write_config(data: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
