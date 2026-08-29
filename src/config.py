import os
import json
import shutil

MAX_ITERATIONS = 10
LLM_REQUESTS_PER_MINUTE = 40
LLM_MAX_RETRIES = 3
LLM_RATE_LIMIT_COOLDOWN = 60

PROVIDERS = {
    "nvidia": {"name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1/chat/completions", "model": "moonshotai/kimi-k3", "key_placeholder": "nvapi-…"},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o-mini", "key_placeholder": "sk-…"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1/chat/completions", "model": "openai/gpt-4o-mini", "key_placeholder": "sk-or-v1-…"},
    "groq": {"name": "Groq", "base_url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile", "key_placeholder": "gsk_…"},
    "together": {"name": "Together AI", "base_url": "https://api.together.xyz/v1/chat/completions", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "key_placeholder": "…"},
    "mistral": {"name": "Mistral AI", "base_url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest", "key_placeholder": "…"},
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/chat/completions", "model": "deepseek-chat", "key_placeholder": "sk-…"},
    "xai": {"name": "xAI", "base_url": "https://api.x.ai/v1/chat/completions", "model": "grok-3-mini", "key_placeholder": "xai-…"},
    "cerebras": {"name": "Cerebras", "base_url": "https://api.cerebras.ai/v1/chat/completions", "model": "llama3.1-8b", "key_placeholder": "csk-…"},
    "fireworks": {"name": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1/chat/completions", "model": "accounts/fireworks/models/llama-v3p3-70b-instruct", "key_placeholder": "fw_…"},
    "custom": {"name": "Personalizado (compatível com OpenAI)", "base_url": "", "model": "", "key_placeholder": "API key"},
}
DEFAULT_PROVIDER = "nvidia"

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

def default_config() -> dict:
    provider = PROVIDERS[DEFAULT_PROVIDER]
    return {
        "provider": DEFAULT_PROVIDER,
        "base_url": provider["base_url"],
        "api_key": "",
        "model": provider["model"],
    }

def read_config() -> dict:
    cfg = default_config()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg

def write_config(data: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
