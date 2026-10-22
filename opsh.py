#!/usr/bin/env python3
"""
OpenSH - Open Natural Language Shell
Talk to your terminal in plain English.

Based on nlsh (https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood

Support: https://ko-fi.com/ai_dev_2024
"""

from __future__ import annotations

__version__ = "0.4.0"

import argparse
import getpass
import importlib
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

USER_AGENT = f"OpenSH/{__version__}"
REPO_URL = "https://github.com/muhib-karim/OpenSH"

# Session stats
session_start = datetime.now()
commands_run = 0


def _load_readline() -> Any:
    """Arrow-key history: readline on macOS/Linux, pyreadline3 (optional) on Windows."""
    name = "pyreadline3" if sys.platform == "win32" else "readline"
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


readline = _load_readline()


# --- Platform and shell detection ---------------------------------------------

SHELL_DISPLAY = {"bash": "bash", "zsh": "zsh", "powershell": "PowerShell"}
_SHELL_ALIASES = {
    "bash": "bash", "sh": "bash", "dash": "bash", "ksh": "bash", "fish": "bash",
    "zsh": "zsh",
    "powershell": "powershell", "pwsh": "powershell", "ps": "powershell",
}


def normalize_shell(name: str) -> str:
    """Map a shell name or path ("/bin/zsh", "pwsh", "PowerShell") to bash, zsh or powershell."""
    key = Path(name.strip()).name.lower()
    if key.endswith(".exe"):
        key = key[:-4]
    if key not in _SHELL_ALIASES:
        raise ValueError(f"unsupported shell '{name}' (use bash, zsh or powershell)")
    return _SHELL_ALIASES[key]


def detect_shell(system: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> str:
    """Pick the shell to generate commands for: OPENSH_SHELL, then $SHELL, then the OS default."""
    env = os.environ if env is None else env
    system = system or platform.system()
    override = env.get("OPENSH_SHELL", "").strip()
    if override:
        try:
            return normalize_shell(override)
        except ValueError:
            pass
    if system == "Windows":
        return "powershell"
    login_shell = env.get("SHELL", "").strip()
    if login_shell:
        try:
            return normalize_shell(login_shell)
        except ValueError:
            pass
    return "zsh" if system == "Darwin" else "bash"


def get_platform_info(system: Optional[str] = None, shell: Optional[str] = None) -> Dict[str, Any]:
    """Current platform details plus the shell commands are generated for and run in."""
    system = system or platform.system()
    shell = shell or detect_shell(system)
    name = {"Windows": "Windows", "Darwin": "macOS"}.get(system, "Linux")
    return {
        "name": name,
        "shell": SHELL_DISPLAY[shell],
        "shell_key": shell,
        "home": Path.home(),
        "path_sep": "\\" if name == "Windows" else "/",
    }


PLATFORM = get_platform_info()


def _is_powershell() -> bool:
    default = "powershell" if PLATFORM["name"] == "Windows" else "bash"
    return bool(PLATFORM.get("shell_key", default) == "powershell")


# --- Update check -------------------------------------------------------------

def _version_tuple(version: str) -> Tuple[int, ...]:
    """Turn "v1.2.3" into (1, 2, 3); non-numeric parts count as 0."""
    parts = []
    for part in version.strip().lstrip("v").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer_version(latest: str, current: str = __version__) -> bool:
    """True only when latest is strictly newer than current."""
    if not latest:
        return False
    return _version_tuple(latest) > _version_tuple(current)


def check_for_updates() -> None:
    """Check GitHub for a newer release (silent, 3 s timeout). Off with OPENSH_NO_UPDATE_CHECK=1."""
    if os.environ.get("OPENSH_NO_UPDATE_CHECK"):
        return
    try:
        url = "https://api.github.com/repos/muhib-karim/OpenSH/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        latest = str(data.get("tag_name", "")).lstrip("v")
        if is_newer_version(latest):
            print(f"\033[33m📦 New version available: v{latest} (you have v{__version__})\033[0m")
            print(f"\033[90m   Update: {REPO_URL}/releases/tag/v{latest}\033[0m\n")
    except Exception:  # noqa: S110 - an update check must never block startup
        pass


def exit_handler(sig: int, frame: Any) -> None:
    print()
    raise InterruptedError()


# --- Settings: config.json and .env next to the program -----------------------

def _program_dir() -> Path:
    """Settings live next to opsh.py, or next to the executable for a PyInstaller build
    (whose __file__ is a temporary folder that disappears after each run)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).parent.absolute()


script_dir = _program_dir()
env_path = script_dir / ".env"
config_path = script_dir / "config.json"

# --provider / --model for this run only; never written to config.json.
SESSION_OVERRIDES: Dict[str, Any] = {}


def load_config() -> Dict[str, Any]:
    """Load configuration from JSON file (an unreadable file counts as empty)."""
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
    return {}


def config_problem() -> Optional[str]:
    """Why config.json can't be used, or None. A broken file is reported, never overwritten."""
    if not config_path.exists():
        return None
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return f"{config_path} is not valid JSON ({e}). Fix or delete it."
    if not isinstance(data, dict):
        return f"{config_path} must contain a JSON object. Fix or delete it."
    return None


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to JSON file."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def current_config() -> Dict[str, Any]:
    return {**load_config(), **SESSION_OVERRIDES}


def _read_env_file() -> Dict[str, str]:
    values: Dict[str, str] = {}
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env() -> None:
    """Load .env into the environment. Variables already set in the real environment win."""
    for key, value in _read_env_file().items():
        os.environ.setdefault(key, value)


KEY_ENV = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}


def save_api_key(provider: str, api_key: str) -> None:
    """Save an API key to .env (readable by the owner only on macOS/Linux)."""
    env_vars = _read_env_file()
    env_vars[KEY_ENV.get(provider, "GROQ_API_KEY")] = api_key
    with open(env_path, "w", encoding="utf-8") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass


# --- Providers ----------------------------------------------------------------

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF = 30.0

PROVIDER_DEFAULTS: Dict[str, Dict[str, Optional[str]]] = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
             "key_env": "GROQ_API_KEY"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash",
               "key_env": "GEMINI_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3.2", "key_env": None},
    "mock": {"base_url": None, "model": "mock", "key_env": None},
}
_PROVIDER_ALIASES = {"openai-compatible": "openai", "openai_compatible": "openai", "custom": "openai",
                     "local": "ollama", "offline": "mock"}


class ProviderError(Exception):
    """A provider call failed. The message is safe to show: it never contains the API key."""


def redact(text: str, secrets: Sequence[Optional[str]]) -> str:
    """Replace every secret (4+ chars) in text with ***."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def _retry_after(error: urllib.error.HTTPError) -> Optional[float]:
    value = error.headers.get("Retry-After") if error.headers else None
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return None
    return min(seconds, MAX_BACKOFF)


def http_post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    secrets: Sequence[Optional[str]] = (),
    sleep: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    """POST JSON with a timeout; retry 429/5xx and network errors with backoff (honours Retry-After)."""
    sleep = sleep or time.sleep
    data = json.dumps(payload).encode("utf-8")
    attempts = 1 + max(0, retries)
    for attempt in range(attempts):
        last = attempt == attempts - 1
        wait = min(2.0 * (2 ** attempt), MAX_BACKOFF)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise ProviderError("Unexpected response from provider")
            return result
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUS and not last:
                wait = _retry_after(e) or wait
                label = "Rate limit" if e.code == 429 else f"Server error {e.code}"
                print(f"\033[90m{label} - retrying in {wait:g}s...\033[0m")
                sleep(wait)
                continue
            if e.code == 429:
                raise ProviderError("Rate limit - please wait a moment") from None
            if e.code in (401, 403):
                raise ProviderError(f"Authentication failed ({e.code}) - check your API key or run !auth") from None
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            raise ProviderError(redact(f"API error {e.code}: {body[:200]}", secrets)) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, InterruptedError):  # Ctrl+C while connecting: cancel, don't retry
                raise reason from None
            if not last:
                sleep(wait)
                continue
            raise ProviderError(redact(f"Network error: {reason}", secrets)) from None
        except json.JSONDecodeError:
            raise ProviderError("Invalid JSON from provider") from None
        except ValueError as e:  # bad header or URL, e.g. a key with non-ASCII characters
            raise ProviderError(redact(f"Request failed: {e}", secrets)) from None
    raise ProviderError("No response from provider")  # pragma: no cover - loop always returns or raises


class Provider:
    """Turns a prompt into text. Subclasses talk to one kind of API."""

    name = "provider"

    def __init__(self, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def __repr__(self) -> str:  # never show the key
        return f"{type(self).__name__}(model={self.model!r}, base_url={self.base_url!r})"

    def complete(self, prompt: str) -> str:
        raise NotImplementedError

    def _post(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers}
        return http_post_json(url, payload, headers, timeout=self.timeout, retries=self.retries,
                              secrets=[self.api_key])


class OpenAICompatibleProvider(Provider):
    """Any /chat/completions API: Groq, OpenAI, OpenRouter, LM Studio, vLLM, Ollama..."""

    name = "openai"

    def complete(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 500,
        }
        result = self._post(f"{self.base_url}/chat/completions", payload, headers)
        try:
            return str(result["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Unexpected response from {self.name}") from None


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"


class OllamaProvider(OpenAICompatibleProvider):
    name = "ollama"


class GeminiProvider(Provider):
    """Google Gemini generateContent. The key goes in a header, never in the URL."""

    name = "gemini"

    def complete(self, prompt: str) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        result = self._post(url, payload, {"x-goog-api-key": self.api_key or ""})
        try:
            return str(result["candidates"][0]["content"]["parts"][0]["text"]).strip()
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Unexpected response from gemini") from None


class MockProvider(Provider):
    """Offline provider for tests and demos: no network, no key, deterministic output.

    OPENSH_MOCK_RESPONSE, if set, is returned for every command request.
    """

    name = "mock"

    def complete(self, prompt: str) -> str:
        if prompt.startswith(EXPLAIN_PREFIX):
            command = prompt.rsplit("Command:", 1)[-1].strip()
            return f"Mock explanation: runs `{command}` in your shell."
        canned = os.environ.get("OPENSH_MOCK_RESPONSE")
        if canned:
            return canned
        request = prompt.rsplit("User request:", 1)[-1].strip().replace('"', "'")
        if "for PowerShell" in prompt:
            return f'Write-Output "mock: {request}"'
        return f'echo "mock: {request}"'


_PROVIDER_CLASSES = {"groq": GroqProvider, "gemini": GeminiProvider, "openai": OpenAICompatibleProvider,
                     "ollama": OllamaProvider, "mock": MockProvider}


def provider_name(config: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    raw = str(env.get("OPENSH_PROVIDER") or config.get("provider") or "groq").strip().lower()
    return _PROVIDER_ALIASES.get(raw, raw)


def _ollama_url(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host if host.endswith("/v1") else f"{host}/v1"


def build_provider(config: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> Provider:
    """Create the provider from config.json plus environment overrides (OPENSH_PROVIDER, OPENSH_MODEL, ...)."""
    env = os.environ if env is None else env
    name = provider_name(config, env)
    if name not in PROVIDER_DEFAULTS:
        choices = ", ".join(sorted(PROVIDER_DEFAULTS))
        raise ProviderError(f"Unknown provider '{name}' - choose one of: {choices}")
    defaults = PROVIDER_DEFAULTS[name]
    model = str(env.get("OPENSH_MODEL") or config.get("model") or defaults["model"])
    base_url = env.get("OPENSH_BASE_URL") or config.get("base_url")
    if not base_url and name == "ollama" and env.get("OLLAMA_HOST"):
        base_url = _ollama_url(env["OLLAMA_HOST"])
    base_url = str(base_url or defaults["base_url"] or "")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ProviderError(f"base_url must start with http:// or https:// (got '{base_url}')")
    try:
        timeout = float(env.get("OPENSH_TIMEOUT") or config.get("timeout") or DEFAULT_TIMEOUT)
        retries = int(config.get("retries", DEFAULT_RETRIES))
    except (TypeError, ValueError):
        raise ProviderError("timeout and retries in config.json must be numbers") from None
    key_env = config.get("api_key_env") or defaults["key_env"]
    api_key = env.get(key_env) if key_env else None
    if name in ("groq", "gemini") and not api_key:
        raise ProviderError(f"No {name.title()} API key - set {key_env} or run !auth")
    cls = _PROVIDER_CLASSES[name]
    return cls(model=model, api_key=api_key, base_url=base_url, timeout=timeout, retries=retries)


def get_ai_response(prompt: str) -> str:
    """Send a prompt to the configured provider."""
    return build_provider(current_config()).complete(prompt)


# --- First-run setup ------------------------------------------------------------

def setup_authentication(ask: Optional[Callable[[str], str]] = None,
                         ask_secret: Optional[Callable[[str], str]] = None,
                         open_url: Optional[Callable[[str], Any]] = None) -> Optional[Dict[str, Any]]:
    """Interactive provider setup. Keys go to .env; everything else to config.json."""
    # Defaults are looked up at call time so tests can patch input()
    ask = ask or input
    ask_secret = ask_secret or getpass.getpass
    open_url = open_url or webbrowser.open
    print("\n\033[1m🔐 OpenSH Setup\033[0m\n")
    print("Choose your AI provider:\n")
    print("  \033[36m1. Groq\033[0m (Recommended - fast, free tier)")
    print("  \033[90m2. Gemini\033[0m (Google AI - free tier)")
    print("  \033[90m3. OpenAI-compatible\033[0m (OpenAI, OpenRouter, LM Studio, vLLM, ...)")
    print("  \033[90m4. Ollama\033[0m (local models, no key, nothing leaves your machine)")
    print()

    choice = ask("\033[33mSelect provider [1-4]:\033[0m ").strip()
    config = load_config()
    for stale in ("model", "base_url", "api_key_env"):
        config.pop(stale, None)

    if choice == "4":
        model = ask("\033[33mModel [llama3.2]:\033[0m ").strip() or "llama3.2"
        config.update({"provider": "ollama", "model": model, "auth_method": "none"})
        save_config(config)
        print(f"\033[32m✓ Using Ollama ({model}). Start it with: ollama serve\033[0m\n")
        return {"provider": "ollama", "api_key": None}

    if choice == "3":
        provider = "openai"
        base_url = ask("\033[33mBase URL [https://api.openai.com/v1]:\033[0m ").strip() or "https://api.openai.com/v1"
        if not base_url.startswith(("http://", "https://")):
            print("\033[31mThe base URL must start with http:// or https://\033[0m")
            return None
        model = ask("\033[33mModel [gpt-4o-mini]:\033[0m ").strip() or "gpt-4o-mini"
        config.update({"base_url": base_url, "model": model})
    elif choice == "2":
        provider = "gemini"
        key_url = "https://aistudio.google.com/apikey"
        print(f"\n\033[36m→ Get your free key at: {key_url}\033[0m")
    else:
        provider = "groq"
        key_url = "https://console.groq.com/keys"
        print(f"\n\033[36m→ Get your free key at: {key_url}\033[0m")
    if provider != "openai" and ask("\033[33mOpen in browser? [Y/n]:\033[0m ").strip().lower() != "n":
        open_url(key_url)
        print("\n\033[90mBrowser opened. Copy your API key and paste it below.\033[0m\n")

    api_key = ask_secret(f"\033[33mPaste your {provider.title()} API key (input is hidden):\033[0m ").strip()
    if not api_key and provider != "openai":
        print("No API key provided.")
        return None
    if api_key:
        save_api_key(provider, api_key)
        os.environ[KEY_ENV[provider]] = api_key

    config["provider"] = provider
    config["auth_method"] = "api_key"
    save_config(config)
    print(f"\033[32m✓ {provider.title()} settings saved!\033[0m\n")
    return {"provider": provider, "api_key": api_key}


# --- Info screens -----------------------------------------------------------------

def show_help() -> None:
    print("\033[36m!explain\033[0m   - Toggle explain-before-run (show what a command does, then ask)")
    print("\033[36m!dry-run\033[0m   - Toggle dry run (show commands, never run them)")
    print("\033[36m!copy\033[0m      - Copy the last generated command to the clipboard")
    print("\033[36m!history\033[0m   - Show recent input")
    print("\033[36m!auth\033[0m      - Change AI provider/key")
    print("\033[36m!version\033[0m   - Show version info")
    print("\033[36m!credits\033[0m   - Show credits")
    print("\033[36m!uninstall\033[0m - Remove OpenSH")
    print("\033[36m!help\033[0m      - Show this help")
    print("\033[36m!<cmd>\033[0m     - Run command directly (bypass AI)")
    print("\033[36mexit\033[0m       - Exit OpenSH")
    if PLATFORM["name"] == "Windows":
        print("\033[36mCtrl+C\033[0m     - Exit OpenSH")
    else:
        print("\033[36mCtrl+C\033[0m     - Cancel the current line")
        print("\033[36mCtrl+D\033[0m     - Exit OpenSH")
    print()


def show_version() -> None:
    config = current_config()
    name = provider_name(config) if (config.get("provider") or os.environ.get("OPENSH_PROVIDER")) else None
    print(f"\n\033[1mOpenSH\033[0m v{__version__}")
    print(f"Platform: {PLATFORM['name']} ({PLATFORM['shell']})")
    if name:
        model = os.environ.get("OPENSH_MODEL") or config.get("model") or PROVIDER_DEFAULTS.get(name, {}).get("model")
        print(f"Provider: {name} ({model})")
    else:
        print("Provider: not configured")
    print(f"Python: {platform.python_version()}")
    print(f"GitHub: {REPO_URL}")
    print()


def show_credits() -> None:
    print("\n\033[36m─────────────────────────────────────────\033[0m")
    print(f"\033[1mOpenSH\033[0m v{__version__} - Open Natural Language Shell")
    print("Based on \033[36mnlsh\033[0m by Junaid Mahmood")
    print("https://github.com/junaid-mahmood/nlsh")
    print("\n☕ Support: \033[33mhttps://ko-fi.com/ai_dev_2024\033[0m")
    print("\033[36m─────────────────────────────────────────\033[0m\n")


def show_goodbye() -> None:
    duration = datetime.now() - session_start
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)
    print("\n\033[36m─────────────────────────────────────────\033[0m")
    print(f"Session: {minutes}m {seconds}s | Commands: {commands_run}")
    print("\033[36mGoodbye! Thanks for using OpenSH ☕\033[0m")
    print("\033[36m─────────────────────────────────────────\033[0m\n")


# --- Context for the model: recent commands and nearby files ------------------------

command_history: List[Dict[str, str]] = []
MAX_HISTORY = 10
MAX_CONTEXT_CHARS = 4000


def get_context_size() -> int:
    return sum(len(e["command"]) + len(e["output"]) for e in command_history)


def add_to_history(command: str, output: str = "") -> None:
    global commands_run
    commands_run += 1
    command_history.append({
        "command": command,
        "output": output[:500] if output else "",
    })
    while len(command_history) > MAX_HISTORY:
        command_history.pop(0)
    while get_context_size() > MAX_CONTEXT_CHARS and len(command_history) > 1:
        command_history.pop(0)


def format_history() -> str:
    if not command_history:
        return "No previous commands."

    lines = []
    for i, entry in enumerate(command_history[-5:], 1):
        lines.append(f"{i}. $ {entry['command']}")
        if entry["output"]:
            output_lines = entry["output"].strip().split("\n")[:2]
            for line in output_lines:
                lines.append(f"   {line}")
    return "\n".join(lines)


def get_file_context(cwd: str) -> str:
    """Get current directory and desktop file listings for AI context."""
    context_parts = []

    # Current directory listing (top 20 items)
    try:
        items = os.listdir(cwd)[:20]
        if items:
            context_parts.append(f"Files in current directory ({cwd}):\n" + "\n".join(f"  {item}" for item in items))
    except OSError:
        pass

    # Desktop listing if not already in desktop
    desktop_path = Path.home() / "Desktop"
    if desktop_path.exists() and str(desktop_path) != cwd:
        try:
            items = os.listdir(desktop_path)[:20]
            if items:
                context_parts.append("Files on Desktop:\n" + "\n".join(f"  {item}" for item in items))
        except OSError:
            pass

    return "\n\n".join(context_parts) if context_parts else ""


# --- Persistent input history (~/.opsh/history) ------------------------------------

HISTORY_LIMIT = 1000
_SECRET_RE = re.compile(
    r"(api[_-]?key|token|secret|passw(or)?d|bearer|authorization)\s*[=:]"
    r"|\b(?:sk-|gsk_|gh[op]_|github_[p]at_|xox[abp]-|AIza)[-_A-Za-z0-9]{8,}",
    re.IGNORECASE,
)


def history_path() -> Path:
    return Path(os.environ.get("OPENSH_HISTORY") or script_dir / "history")


def looks_secret(line: str) -> bool:
    """True for input that seems to contain a key or password; such lines are never saved."""
    return bool(_SECRET_RE.search(line))


def read_history_file(path: Optional[Path] = None) -> List[str]:
    path = path or history_path()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [line.rstrip("\n") for line in f if line.strip()]
    except OSError:
        return []
    return lines[-HISTORY_LIMIT:]


def load_history_into_readline(path: Optional[Path] = None) -> int:
    """Make arrow-key history survive restarts. Returns how many lines were loaded."""
    lines = read_history_file(path)
    if readline is not None and hasattr(readline, "add_history"):
        for line in lines:
            readline.add_history(line)
    return len(lines)


def append_history(line: str, path: Optional[Path] = None) -> bool:
    """Append one input line to the history file, trimming it to HISTORY_LIMIT lines."""
    line = line.strip()
    if not line or looks_secret(line):
        return False
    path = path or history_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.replace("\n", " ") + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        lines = read_history_file(path)
        if path.stat().st_size > 200 * HISTORY_LIMIT:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except OSError:
        return False
    return True


def show_history(count: int = 20, path: Optional[Path] = None) -> None:
    lines = read_history_file(path)[-count:]
    if not lines:
        print("\033[90mNo history yet.\033[0m")
    for i, line in enumerate(lines, 1):
        print(f"\033[90m{i:>3}\033[0m  {line}")


# --- Prompt building ----------------------------------------------------------------

EXPLAIN_PREFIX = "Explain this shell command"


def get_command(user_input: str, cwd: str) -> str:
    history_context = format_history()
    file_context = get_file_context(cwd)

    # Shell-specific instructions
    intro = "You are a shell command translator. Convert the user's request into a command for"
    if _is_powershell():
        shell_instructions = f"""{intro} PowerShell on {PLATFORM['name']}.
Use PowerShell cmdlets and syntax. Examples:
- List files: Get-ChildItem or dir
- Find files: Get-ChildItem -Recurse -Filter "*.py"
- Current directory: Get-Location or pwd
- Remove file: Remove-Item
- Copy file: Copy-Item
- Move file: Move-Item
- Create directory: New-Item -ItemType Directory
- View file: Get-Content or type
- Clear screen: Clear-Host or cls
- Process list: Get-Process
- Kill process: Stop-Process -Name "name"
- Network info: ipconfig, Test-NetConnection"""
    else:
        shell_instructions = f"{intro} {PLATFORM['shell']} on {PLATFORM['name']}."

    prompt = f"""{shell_instructions}
Current directory: {cwd}

AVAILABLE FILES/FOLDERS (use EXACT names with correct spelling and spacing):
{file_context}

Recent command history:
{history_context}

CRITICAL RULES:
- Output ONLY the command, nothing else
- No explanations, no markdown, no backticks
- IMPORTANT: Match user's description to the EXACT file/folder name from the listing above
- For example, if user says "resume folder" and listing shows "Current Resume", use "Current Resume"
- Paths with spaces must be quoted: "C:\\Users\\Name\\Desktop\\Folder Name"
- If unclear, make a reasonable assumption
- Use the command history for context

User request: {user_input}"""

    return clean_command(get_ai_response(prompt))


def explain_command(command: str) -> str:
    """Ask the model for a short plain-English explanation of a command."""
    prompt = (f"{EXPLAIN_PREFIX} for a {PLATFORM['shell']} user on {PLATFORM['name']} in at most two short "
              "sentences: what it does and what it changes. Plain text, no markdown.\n\n"
              f"Command: {command}")
    return " ".join(get_ai_response(prompt).split())


def clean_command(text: str) -> str:
    """Strip the markdown fences, backticks and "$ " prompts models sometimes add."""
    text = text.strip()
    fence = re.match(r"^```[\w-]*\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if len(text) > 1 and text.startswith("`") and text.endswith("`"):
        text = text.strip("`").strip()
    if text.startswith(("$ ", "> ", "PS> ")):
        text = text.split(" ", 1)[1].strip()
    return text


def is_natural_language(text: str) -> bool:
    if text.startswith("!"):
        return False

    # Exit commands
    if text.lower() in ["exit", "quit", "bye", "goodbye"]:
        return False

    # Common shell commands that should run directly
    if _is_powershell():
        shell_commands = [
            "dir", "cls", "type", "copy", "move", "del", "md", "rd",
            "pwd", "ls", "cat", "clear", "whoami", "date", "time",
            "ipconfig", "ping", "netstat", "nslookup", "tracert", "arp",
            "tasklist", "taskkill", "systeminfo", "hostname", "ver",
            "diskpart", "chkdsk", "format",
            "tree", "fc", "comp", "more", "sort", "find", "findstr",
            "attrib", "xcopy", "robocopy", "where", "set", "path",
        ]
        shell_starters = [
            "cd ", "cd\\", "cd/", "dir ", "echo ",
            "type ", "copy ", "move ", "del ", "ren ", "rename ", "md ", "mkdir ",
            "rd ", "rmdir ", "attrib ", "xcopy ", "robocopy ",
            "Get-", "Set-", "New-", "Remove-", "Copy-", "Move-", "Out-",
            "Write-", "Read-", "Start-", "Stop-", "Invoke-", "Test-",
            "Select-", "Where-", "ForEach-", "Sort-", "Group-",
            "git ", "npm ", "node ", "npx ", "yarn ", "pnpm ",
            "python ", "python3 ", "py ", "pip ", "pip3 ",
            "cargo ", "rustc ", "go ", "java ", "javac ",
            "dotnet ", "nuget ",
            "curl ", "wget ", "ssh ", "scp ", "docker ", "kubectl ",
            "code ", "notepad ", "explorer ",
            "./", ".\\", "/", "\\", "~", "$", ">", ">>", "|", "&&", ";",
        ]
    else:
        shell_commands = [
            "ls", "pwd", "clear", "whoami", "date", "cal", "uptime",
            "top", "htop", "ps", "kill", "killall", "jobs", "bg", "fg",
            "cat", "head", "tail", "less", "more", "touch", "stat",
            "find", "grep", "awk", "sed", "wc", "sort", "uniq", "diff",
            "tar", "zip", "unzip", "gzip", "gunzip", "bzip2",
            "chmod", "chown", "chgrp", "id", "groups", "passwd",
            "df", "du", "free", "mount", "umount",
            "ping", "curl", "wget", "ssh", "scp", "netstat", "ifconfig", "ip",
            "apt", "yum", "dnf", "pacman", "brew", "snap", "flatpak",
            "man", "which", "whereis", "history", "alias", "source", "export",
        ]
        shell_starters = [
            "cd ", "ls ", "ll ",
            "cat ", "head ", "tail ", "touch ", "rm ", "cp ", "mv ",
            "mkdir ", "rmdir ", "chmod ", "chown ", "ln ",
            "echo ", "grep ", "sed ", "awk ", "cut ", "tr ", "xargs ",
            "git ", "npm ", "node ", "npx ", "yarn ", "pnpm ",
            "python ", "python3 ", "pip ", "pip3 ",
            "cargo ", "rustc ", "go ", "java ", "javac ",
            "make ", "cmake ", "gcc ", "g++ ", "clang ",
            "brew ", "apt ", "apt-get ", "yum ", "dnf ", "pacman ", "snap ",
            "sudo ", "su ", "ssh ", "scp ", "curl ", "wget ",
            "docker ", "kubectl ", "aws ", "gcloud ", "az ",
            "vi ", "vim ", "nano ", "emacs ", "code ",
            "open ", "xdg-open ",
            "export ", "source ", "alias ",
            "./", "/", "~", "$", ">", ">>", "|", "&&", ";",
        ]

    text_lower = text.lower()
    if text_lower in [c.lower() for c in shell_commands]:
        return False
    return not any(text_lower.startswith(s.lower()) for s in shell_starters)


# --- Safety guard -----------------------------------------------------------------
# AI-generated commands run automatically, except ones that can destroy data, take the
# machine down or run code from the internet. Those are shown with the reason and need
# an explicit "y" first. Rules match at command position (start of line, after ; && || |
# ( { or `, behind sudo/xargs/-exec and friends), so `cat shutdown.log` is not a shutdown.

_OPT = r"-\S+(?:\s+[^\s;&|-][^\s;&|]*)?"  # an option, maybe with a value (-u root, -n 10)
_START = (r"(?:^|[;&|({`\n'\"]|\$\(|-exec(?:dir)?\s|\b(?:then|do|else)\s"
          r"|\s(?:-c|/c|/k|-command)\s"                                   # bash -c, cmd /c, powershell -Command
          r"|\b(?:ssh|mosh)\s+(?:" + _OPT + r"\s+)*[^\s;&|-]\S*\s"          # ssh [opts] host CMD
          r"|\b(?:docker|podman|kubectl|oc)\s+exec\s+(?:" + _OPT + r"\s+)*[^\s;&|-]\S*\s+(?:--\s)?"
          r")\s*")
_WRAP = (r"(?:(?:[A-Za-z_]\w*=\S*"                                           # FOO=1 cmd
         r"|(?:sudo|doas|command|exec|nohup|nice|time|timeout|env|noglob|builtin|xargs|watch|stdbuf|ionice)\b"
         r"(?:\s+" + _OPT + r")*(?:\s+\d[\w.]*)?"                              # timeout 5, nice -n 10
         r")\s+)*")
_GIT = r"git\s+(?:" + _OPT + r"\s+)*"  # git -C repo ...
_CMD = _START + _WRAP + r"(?:[\w./~-]*/|\\)?"
_ARGS = r"[^;&|\n]*"  # rest of the same simple command
_END = r"(?=\s|$|[;&|)]|['\"]\s*(?:$|[;&|)]))"  # word ends here (a closing quote counts)
_ROOTISH = (r"(?:/|~|\$HOME|/(?:etc|usr|bin|sbin|boot|var|lib|lib64|home|root|opt|dev|proc|sys|"
            r"system|library|applications|users)|[a-z]:\\(?:windows)?)/?" + _END)
_SHELLS = r"(?:ba|z|da|k|fi|c|tc)?sh"

GUARD_RULES: List[Tuple[str, str]] = [
    # Deleting files
    ("Deletes files recursively or without asking",
     _CMD + r"rm\s+(?:" + _ARGS + r"\s)?(?:-[a-z]*[rf][a-z]*|--recursive|--force)" + _END),
    ("Deletes files recursively or without asking",
     _CMD + r"(?:remove-item|ri|rm|rmdir|rd|del|erase)\b" + _ARGS + r"\s-(?:r|rec\w*|fo\w*)" + _END),
    ("Deletes folders and their contents (cmd /s /q /f)",
     _CMD + r"(?:rmdir|rd|del|erase)\b" + _ARGS + r"\s/[sfq]\b"),
    ("Deletes every file find matches", _CMD + r"find\b" + _ARGS + r"\s-delete\b"),
    ("Deletes every file piped or passed into it",
     r"\bxargs\b(?:\s+" + _OPT + r")*\s+rm\b|-exec(?:dir)?\s+rm\b"
     r"|\|\s*(?:remove-item|ri|del|erase|rm)\b(?!\s+-whatif)"),
    ("Empties the Recycle Bin", _CMD + r"clear-recyclebin\b"),
    ("Overwrites files so they cannot be recovered", _CMD + r"(?:shred|srm)\b"),
    ("Moves data into /dev/null (deletes it)", _CMD + r"mv\b" + _ARGS + r"\s/dev/null\b"),
    ("Empties a file", _CMD + r"truncate\s+(?:-\S+\s+)*-s\s*0\b"),
    # Disks and filesystems
    ("Formats a disk or partition",
     _CMD + r"(?:mkfs(?:\.\w+)?|mke2fs|mkswap|mkntfs|newfs(?:_\w+)?|wipefs)\b"),
    ("Writes raw data to a disk device", _CMD + r"dd\b" + _ARGS + r"\bof=/dev/(?!null\b|zero\b|stdout\b|stderr\b)"),
    ("Writes raw data to a disk device", r">\s*/dev/(?:sd|hd|vd|xvd|nvme|disk|rdisk|mmcblk)"),
    ("Edits the partition table", _CMD + r"(?:fdisk|sfdisk|gdisk|cfdisk|parted)\b(?!" + _ARGS + r"\s-l\b)"
     + _ARGS + r"\s/dev/"),
    ("Erases or repartitions a disk",
     _CMD + r"diskutil\s+(?:erase\w*|partitiondisk|zerodisk|randomdisk|secureerase|reformat|apfs\s+delete\w*)"),
    ("Formats or wipes a disk", _CMD + r"(?:format-volume|clear-disk|initialize-disk|remove-partition)\b"),
    ("Formats a drive", _CMD + r"format(?:\.com)?\s+[a-z]:"),
    ("Opens the disk partitioning tool", _CMD + r"diskpart\b"),
    ("Wipes free disk space", _CMD + r"cipher\b" + _ARGS + r"\s/w\b"),
    ("Deletes restore points / shadow copies", _CMD + r"(?:vssadmin\s+delete|wmic\s+shadowcopy\s+delete)\b"),
    ("Changes the boot configuration", _CMD + r"bcdedit\b" + _ARGS + r"\s/(?:delete|deletevalue|set)\b"),
    # Permissions
    ("Changes permissions or owner of system folders recursively",
     _CMD + r"(?:chmod|chown|chgrp)\b(?=" + _ARGS + r"\s(?:-[a-z]*r[a-z]*|--recursive)(?:\s|$))"
     + _ARGS + r"\s" + _ROOTISH),
    ("Makes system folders writable by everyone",
     _CMD + r"chmod\s+(?:-\S+\s+)*(?:0?777|a\+rwx|ugo\+rwx)\s+" + _ROOTISH),
    ("Grants everyone full control", _CMD + r"icacls\b" + _ARGS + r"/grant\b" + _ARGS + r"\b(?:everyone|users)\b"),
    ("Takes ownership of files recursively", _CMD + r"takeown\b" + _ARGS + r"\s/r\b"),
    # Fork bombs and runaway processes
    ("Fork bomb: spawns processes until the machine freezes", r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}"),
    ("Fork bomb: spawns processes until the machine freezes", r"\b(\w+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}"),
    ("Fork bomb: spawns processes until the machine freezes",
     r"while\s*\(\s*\$?(?:true|1)\s*\)\s*\{\s*(?:start-process|start)\b"),
    ("Fork bomb: spawns processes until the machine freezes", r"%0\s*\|\s*%0"),
    ("Kills every process you own", _CMD + r"kill\s+-(?:9|kill|sigkill)\s+-1\b"),
    ("Force-kills processes by name", _CMD + r"killall\b"),
    ("Force-kills processes by name", _CMD + r"pkill\s+(?:-\S+\s+)*-(?:9|kill)\b"),
    ("Force-kills processes", _CMD + r"stop-process\b" + _ARGS + r"\s-f(?:o|or|orc|orce)?\b"),
    ("Force-kills processes", _CMD + r"taskkill\b" + _ARGS + r"\s/f\b"),
    # Power
    ("Shuts down or restarts the machine", _CMD + r"(?:shutdown|reboot|halt|poweroff)(?:\.exe)?" + _END),
    ("Shuts down or restarts the machine", _CMD + r"init\s+[06]\b"),
    ("Shuts down or restarts the machine", _CMD + r"systemctl\s+(?:poweroff|reboot|halt|kexec)\b"),
    ("Shuts down or restarts the machine", _CMD + r"(?:stop|restart)-computer\b"),
    # Git history
    ("Overwrites remote git history (force push)",
     _CMD + _GIT + r"push\b" + _ARGS
     + r"\s(?:--force(?:-with-lease)?(?:=\S*)?|-[a-z]*f[a-z]*|\+\S+)" + _END),
    ("Discards uncommitted git changes", _CMD + _GIT + r"reset\b" + _ARGS + r"\s--hard\b"),
    ("Deletes untracked files", _CMD + _GIT + r"clean\b" + _ARGS + r"\s(?:-[a-z]*f|--force)"),
    ("Deletes an unmerged git branch", _CMD + _GIT + r"branch\b" + _ARGS + r"\s(?-i:-D)\b"),
    ("Rewrites or erases git history",
     _CMD + _GIT + r"(?:filter-branch|filter-repo|reflog\s+expire|stash\s+clear|update-ref\s+-d)\b"),
    ("Discards uncommitted git changes",
     _CMD + _GIT + r"(?:checkout\s+(?:(?:\S+\s+)?--\s+)?\.|restore\s+(?:--?\S+\s+)*\.)" + _END),
    # Running code straight from the internet
    ("Runs a script downloaded from the internet",
     r"\b(?:curl|wget|fetch|iwr|irm|invoke-webrequest|invoke-restmethod)\b" + _ARGS + r"\|\s*"
     + r"(?:sudo\s+(?:-\S+\s+)*)?(?:" + _SHELLS + r"|python[\d.]*|perl|ruby|node|php)\b"),
    ("Runs a script downloaded from the internet",
     r"\b(?:iwr|irm|invoke-webrequest|invoke-restmethod|curl|wget)\b[^;\n]*\|\s*(?:iex|invoke-expression)\b"),
    ("Runs a script downloaded from the internet",
     r"\b(?:iex|invoke-expression)\b[^;\n]*(?:downloadstring|iwr|irm|invoke-webrequest|invoke-restmethod)"),
    ("Runs a script downloaded from the internet",
     r"(?:\b" + _SHELLS + r"|\bsource|(?:^|\s)\.)\s+(?:-\S+\s+)*(?:<\(|[\"']?\$\()\s*(?:curl|wget)\b"),
    # System files, registry, security settings
    ("Overwrites a system configuration file", r"(?<![>&\d])>(?!>)\s*/etc/"),
    ("Overwrites a system configuration file", _CMD + r"tee\s+(?:-(?!a\b)\S+\s+)*/etc/"),
    ("Deletes your crontab", _CMD + r"crontab\s+(?:-\S+\s+)*-r\b"),
    ("Erases shell history", _CMD + r"history\s+-c\b"),
    ("Deletes registry keys", _CMD + r"reg(?:\.exe)?\s+delete\b"),
    ("Deletes registry keys", _CMD + r"remove-item\b" + _ARGS + r"\bhk(?:lm|cu|cr|u|cc):"),
    ("Weakens PowerShell script security",
     _CMD + r"set-executionpolicy\s+(?:-\S+\s+)*(?:unrestricted|bypass)\b"),
    ("Turns off antivirus protection", _CMD + r"set-mppreference\b" + _ARGS + r"-disable\w+\s+\$?(?:true|1)\b"),
    # Databases and infrastructure
    ("Deletes a database table or database", r"\bdrop\s+(?:table|database|schema)\b"),
    ("Deletes every row in a table", r"\btruncate\s+table\b"),
    ("Deletes every key in Redis", r"\bflush(?:all|db)\b"),
    ("Deletes a MongoDB database", r"\bdropdatabase\s*\("),
    ("Deletes Docker data", _CMD + r"docker\s+(?:system|volume|image|container|network|builder)\s+prune\b"),
    ("Force-removes Docker containers or images", _CMD + r"docker\s+(?:rm|rmi)\s+(?:\S+\s+)*?-[a-z]*f"),
    ("Deletes Kubernetes resources", _CMD + r"kubectl\s+(?:-\S+\s+)*delete\b"),
    ("Destroys cloud infrastructure", _CMD + r"terraform\s+(?:-\S+\s+)*destroy\b"),
]
_GUARD_RE = [(reason, re.compile(pattern, re.IGNORECASE | re.MULTILINE)) for reason, pattern in GUARD_RULES]


def explain_risk(cmd: str) -> List[str]:
    """Why a command is dangerous: one reason per matching rule, no duplicates. [] means not flagged."""
    reasons: List[str] = []
    if not cmd or not cmd.strip():
        return reasons
    for reason, rx in _GUARD_RE:
        if reason not in reasons and rx.search(cmd):
            reasons.append(reason)
    return reasons


def is_destructive(cmd: str) -> bool:
    """True when a command could delete data, wipe a disk, rewrite history, stop the machine or run downloaded code."""
    return bool(explain_risk(cmd))


def confirm_if_destructive(cmd: str, assume_yes: bool = False, ask: Optional[Callable[[str], str]] = None) -> bool:
    """Return True if the command may run. Destructive commands need an explicit yes."""
    ask = ask or input
    reasons = explain_risk(cmd)
    if not reasons or assume_yes:
        return True
    try:
        answer = ask(f"\033[31m⚠ {'; '.join(reasons)}. Run it? [y/N]\033[0m ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("y", "yes")


def confirm_run(ask: Optional[Callable[[str], str]] = None) -> bool:
    """Explain mode: ask before running a command the guard did not flag (Enter means yes)."""
    ask = ask or input
    try:
        answer = ask("\033[33mRun it? [Y/n]\033[0m ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("", "y", "yes")


# --- Clipboard ------------------------------------------------------------------------

def clipboard_commands(system: Optional[str] = None) -> List[List[str]]:
    system = system or platform.system()
    if system == "Windows":
        return [["clip"]]
    if system == "Darwin":
        return [["pbcopy"]]
    return [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]


def copy_to_clipboard(text: str, system: Optional[str] = None) -> bool:
    """Copy text with the first clipboard tool that is installed. False if none worked."""
    for argv in clipboard_commands(system):
        exe = shutil.which(argv[0])
        if not exe:
            continue
        try:
            subprocess.run([exe, *argv[1:]], input=text, text=True, check=True, capture_output=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


# --- Running commands ------------------------------------------------------------------

def shell_argv(cmd: str) -> List[str]:
    """argv that runs cmd in the detected shell."""
    if _is_powershell():
        exe = "powershell" if PLATFORM["name"] == "Windows" else (shutil.which("pwsh") or "pwsh")
        return [exe, "-NoProfile", "-Command", cmd]
    shell = PLATFORM.get("shell_key", "bash")
    return [shutil.which(shell) or "/bin/sh", "-c", cmd]


def run_command_status(cmd: str) -> Tuple[str, str, int]:
    """Run a command and return (stdout, stderr, exit code). 60 s timeout on Windows, none elsewhere."""
    timeout = 60 if PLATFORM["name"] == "Windows" else None
    try:
        result = subprocess.run(shell_argv(cmd), capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout)
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 124
    except OSError as e:
        return "", str(e), 127


def run_command(cmd: str) -> Tuple[str, str]:
    """Run a command and return (stdout, stderr)."""
    stdout, stderr, _ = run_command_status(cmd)
    return stdout, stderr


_CD_PREFIXES = ("cd ", "set-location ", "chdir ", "sl ")


def cd_target(command: str) -> Optional[str]:
    """The folder a plain cd/Set-Location/chdir command goes to, or None for anything else.

    Chained commands ("cd build && make") are left to the shell.
    """
    stripped = command.strip()
    if stripped.lower() == "cd":
        return "~"
    if any(op in stripped for op in ("&&", "||", ";", "|", "\n")):
        return None
    for prefix in _CD_PREFIXES:
        if stripped.lower().startswith(prefix):
            return stripped[len(prefix):].strip()
    return None


def change_directory(raw: str) -> bool:
    """chdir in this process (a subprocess cd would be lost). Handles quotes, ~ and $env:VAR."""
    path = raw.strip().strip('"').strip("'") or "~"
    if path.lower().startswith("-path "):
        path = path[6:].strip().strip('"').strip("'")
    path = os.path.expanduser(path)
    if PLATFORM["name"] == "Windows":
        path = re.sub(r"\$env:(\w+)", lambda m: os.environ.get(m.group(1), m.group(0)),
                      path.replace("/", "\\"), flags=re.IGNORECASE)
    path = os.path.expandvars(path)
    try:
        os.chdir(path)
        return True
    except OSError as e:
        print(f"cd: {e}")
        return False


@dataclass
class RunOptions:
    """How generated commands are handled (set by flags, toggled with !explain / !dry-run)."""

    yes: bool = False
    dry_run: bool = False
    explain: bool = False
    copy: bool = False


def handle_generated(command: str, opts: RunOptions, ask: Optional[Callable[[str], str]] = None) -> Optional[int]:
    """Show a generated command, then explain / copy / guard / run it.

    Returns the command's exit code, or None when it was not run (dry run or skipped).
    """
    ask = ask or input
    print(f"\033[33m→ {command}\033[0m")
    reasons = explain_risk(command)
    if opts.copy:
        if copy_to_clipboard(command):
            print("\033[90m📋 Copied to clipboard\033[0m")
        else:
            print("\033[90mNo clipboard tool found (install wl-copy, xclip or xsel)\033[0m")
    if opts.explain:
        try:
            print(f"\033[36mℹ {explain_command(command)}\033[0m")
        except ProviderError as e:
            print(f"\033[90m(no explanation: {e})\033[0m")
        if opts.dry_run or opts.yes:  # otherwise the confirmation prompt shows the reasons
            for reason in reasons:
                print(f"\033[31m⚠ {reason}\033[0m")
    if opts.dry_run:
        print("\033[90m(dry run - not executed)\033[0m")
        return None
    target = cd_target(command)
    if target is not None:
        return 0 if change_directory(target) else 1
    if reasons:
        if not confirm_if_destructive(command, opts.yes, ask):
            print("\033[90mSkipped.\033[0m")
            return None
    elif opts.explain and not opts.yes and not confirm_run(ask):
        print("\033[90mSkipped.\033[0m")
        return None
    stdout, stderr, code = run_command_status(command)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    add_to_history(command, stdout + stderr)
    return code


def run_direct(cmd: str) -> None:
    """Run input the user typed as a shell command (no model, no guard)."""
    stdout, stderr = run_command(cmd)
    print(stdout, end="")
    if stderr:
        print(stderr, end="")
    add_to_history(cmd, stdout + stderr)


def uninstall(ask: Optional[Callable[[str], str]] = None) -> bool:
    ask = ask or input
    confirm = ask("\033[33mRemove OpenSH? [y/N]\033[0m ")
    if confirm.strip().lower() != "y":
        return False
    install_dir = Path.home() / ".opsh"
    if PLATFORM["name"] == "Windows":
        bin_path = install_dir / "opsh.cmd"
    else:
        bin_path = Path.home() / ".local" / "bin" / "opsh"
    if install_dir.exists():
        shutil.rmtree(install_dir)
    if bin_path.exists():
        os.remove(bin_path)
    print("\033[32m✓ OpenSH uninstalled\033[0m")
    return True


# --- CLI ---------------------------------------------------------------------------------

EXAMPLES = """\
examples:
  opsh                                      interactive shell
  opsh -c "show my public ip address"       one request, then exit
  opsh -n -c "delete all .tmp files"        dry run: print the command, run nothing
  opsh -e -c "free up disk space"           explain the command and ask before running it
  opsh --copy -n -c "find big files"        copy the command to the clipboard
  opsh --provider ollama --model llama3.2   use a local model for this session
  OPENSH_PROVIDER=mock opsh -n -c "list files"   offline demo, no API key

providers: groq (default), gemini, openai (any OpenAI-compatible URL), ollama, mock
settings:  config.json and .env next to opsh.py (~/.opsh after install); see `man opsh`
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opsh",
        description="OpenSH - talk to your terminal in plain English",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--command", nargs="*", help="run a single natural-language request and exit")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="run destructive AI-generated commands without asking (use with care)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="show generated commands but never run them")
    parser.add_argument("-e", "--explain", action="store_true",
                        help="explain each generated command and ask before running it")
    parser.add_argument("--copy", action="store_true", help="copy each generated command to the clipboard")
    parser.add_argument("--shell", choices=["bash", "zsh", "powershell"],
                        help="shell to generate commands for (default: auto-detect)")
    parser.add_argument("--provider", choices=sorted(PROVIDER_DEFAULTS), help="AI provider for this session")
    parser.add_argument("--model", help="model name for this session")
    parser.add_argument("--no-history", action="store_true", help="do not read or write the history file")
    parser.add_argument("-v", "--version", action="version", version=f"OpenSH v{__version__}")
    return parser


def _thinking(on: bool) -> None:
    if on:
        print("\033[90m⏳ thinking...\033[0m", end="\r", flush=True)
    else:
        print(" " * 20, end="\r")


def run_once(query: str, opts: RunOptions) -> int:
    """-c mode: one request, one command. Exit code: the command's, 0 for a dry run, 1 if skipped or failed."""
    try:
        _thinking(True)
        command = get_command(query, os.getcwd())
        _thinking(False)
        if not command:
            print("\033[31mError: the model returned an empty command\033[0m")
            return 1
        code = handle_generated(command, opts)
        if code is None:
            return 0 if opts.dry_run else 1
        return code
    except ProviderError as e:
        _thinking(False)
        print(f"\033[31mError: {e}\033[0m")
        return 1


def repl(opts: RunOptions, history_enabled: bool = True) -> int:
    """The interactive shell."""
    if platform.system() != "Windows":
        signal.signal(signal.SIGINT, exit_handler)
    if history_enabled:
        load_history_into_readline()
    check_for_updates()
    print("\033[1mOpenSH\033[0m ready! Type naturally or use !help\n")
    last_command = ""

    while True:
        try:
            cwd = os.getcwd()
            user_input = input(f"\033[32m{cwd}\033[0m > ").strip()
            if not user_input:
                continue
            if history_enabled:
                append_history(user_input)

            lowered = user_input.lower()
            if lowered in ["exit", "quit", "bye", "goodbye"]:
                show_goodbye()
                return 0

            # cd has to run in this process, not a subprocess
            target = cd_target(user_input)
            if target is not None and not user_input.startswith("!"):
                change_directory(target)
                continue

            if user_input == "!auth":
                if setup_authentication():
                    print("\033[32m✓ Authentication updated!\033[0m\n")
                continue
            if user_input == "!version":
                show_version()
                continue
            if user_input == "!uninstall":
                if uninstall():
                    return 0
                continue
            if user_input == "!help":
                show_help()
                continue
            if user_input == "!credits":
                show_credits()
                continue
            if user_input == "!history":
                show_history()
                continue
            if user_input == "!explain":
                opts.explain = not opts.explain
                print(f"\033[90mExplain-before-run {'on' if opts.explain else 'off'}\033[0m")
                continue
            if user_input == "!dry-run":
                opts.dry_run = not opts.dry_run
                print(f"\033[90mDry run {'on' if opts.dry_run else 'off'}\033[0m")
                continue
            if user_input == "!copy":
                if not last_command:
                    print("\033[90mNothing to copy yet.\033[0m")
                elif copy_to_clipboard(last_command):
                    print("\033[90m📋 Copied to clipboard\033[0m")
                else:
                    print("\033[90mNo clipboard tool found (install wl-copy, xclip or xsel)\033[0m")
                continue

            if user_input.startswith("!"):
                if user_input[1:]:
                    run_direct(user_input[1:])
                continue

            if not is_natural_language(user_input):
                run_direct(user_input)
                continue

            _thinking(True)
            command = get_command(user_input, cwd)
            _thinking(False)
            if not command:
                print("\033[31mError: the model returned an empty command\033[0m")
                continue
            last_command = command
            handle_generated(command, opts)

        except (EOFError, KeyboardInterrupt):
            show_goodbye()
            return 0
        except InterruptedError:
            continue
        except ProviderError as e:
            _thinking(False)
            print(f"\033[31mError: {e}\033[0m")
        except Exception as e:
            print(f"\033[31mError: {str(e)[:200]}\033[0m")


def _safe_output() -> None:
    """Never crash on emoji when output goes to a pipe or a legacy (cp1252) console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    global PLATFORM
    _safe_output()
    args = build_parser().parse_args(argv)
    load_env()
    PLATFORM = get_platform_info(shell=args.shell)  # after load_env, so OPENSH_SHELL in .env counts
    problem = config_problem()
    if problem:
        print(f"\033[31m{problem}\033[0m")
        return 1
    SESSION_OVERRIDES.clear()
    if args.provider:
        SESSION_OVERRIDES["provider"] = args.provider
    if args.model:
        SESSION_OVERRIDES["model"] = args.model

    config = current_config()
    if not (config.get("provider") or os.environ.get("OPENSH_PROVIDER")):
        # First run - show welcome and auth setup
        print("\n\033[1m🚀 Welcome to OpenSH!\033[0m")
        print("Talk to your terminal in plain English.\n")
        try:
            auth_result = setup_authentication()
        except (EOFError, KeyboardInterrupt):
            auth_result = None
        if not auth_result:
            print("\033[31mAuthentication required to use OpenSH.\033[0m")
            return 1

    opts = RunOptions(yes=args.yes, dry_run=args.dry_run, explain=args.explain, copy=args.copy)
    history_enabled = not args.no_history and current_config().get("history", True) is not False
    if args.command:
        return run_once(" ".join(args.command), opts)
    return repl(opts, history_enabled)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
