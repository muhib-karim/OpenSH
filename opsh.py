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
import contextlib
import getpass
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

# Importing readline switches on line editing and in-session history for input().
# On Windows the module comes from the optional pyreadline3 package, which can
# raise more than ImportError when there is no console, hence the broad except.
try:
    import readline  # noqa: F401

    _HAVE_READLINE = True
except Exception:
    _HAVE_READLINE = False

# Session stats
session_start = datetime.now()
commands_run = 0

# Set by main(): False when output is not a terminal or NO_COLOR is set.
_color_enabled = True

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x01\x02]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

EXIT_WORDS = ("exit", "quit", "bye", "goodbye")


def get_platform_info() -> dict[str, Any]:
    """Get current platform details."""
    system = platform.system()
    if system == "Windows":
        return {
            "name": "Windows",
            "shell": "PowerShell",
            "home": Path.home(),
            "path_sep": "\\",
        }
    elif system == "Darwin":
        return {
            "name": "macOS",
            "shell": "zsh",
            "home": Path.home(),
            "path_sep": "/",
        }
    else:
        return {
            "name": "Linux",
            "shell": "bash",
            "home": Path.home(),
            "path_sep": "/",
        }


PLATFORM = get_platform_info()


def detect_shell() -> str | None:
    """Path of the shell commands run in. None on Windows, where PowerShell is used."""
    name = PLATFORM["name"]
    if name == "Windows":
        return None
    preferred = ["zsh", "bash"] if name == "macOS" else ["bash"]
    for candidate in preferred:
        path = shutil.which(candidate)
        if path:
            return path
    return "/bin/sh"


def shell_name() -> str:
    """Name of the shell the model is asked to write for (the one commands really run in)."""
    path = detect_shell()
    if path is None or os.name == "nt":
        return str(PLATFORM["shell"])
    return Path(path).name


def printable(text: str) -> str:
    """Escape control characters so what is shown is what will run."""
    return _CONTROL_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", text)


def _version_tuple(version: str) -> tuple[int, ...]:
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


UPDATE_CHECK_INTERVAL = 24 * 60 * 60


def check_for_updates() -> None:
    """Look for a newer release at most once a day. Never raises; OPSH_NO_UPDATE_CHECK turns it off."""
    if os.environ.get("OPSH_NO_UPDATE_CHECK"):
        return
    config = load_config()
    last = config.get("last_update_check", 0)
    now = time.time()
    if isinstance(last, (int, float)) and 0 <= now - last < UPDATE_CHECK_INTERVAL:
        return
    config["last_update_check"] = int(now)
    try:
        save_config(config)
        url = "https://api.github.com/repos/muhib-karim/OpenSH/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenSH"})
        with urllib.request.urlopen(req, timeout=3) as response:  # noqa: S310 - fixed https URL
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return  # offline or rate-limited: not worth bothering the user
    latest = str(data.get("tag_name", "")).lstrip("v") if isinstance(data, dict) else ""
    if is_newer_version(latest):
        print(f"\033[33m📦 New version available: v{latest} (you have v{__version__})\033[0m")
        print(f"\033[90m   Update: https://github.com/muhib-karim/OpenSH/releases/tag/v{latest}\033[0m\n")


def exit_handler(sig: int, frame: Any) -> None:
    print()
    raise InterruptedError()


def get_config_dir() -> Path:
    """Where config.json and .env live.

    OPSH_HOME wins. A PyInstaller binary uses ~/.opsh, because the folder its code
    runs from is a temporary one that is deleted on exit. Otherwise the files sit
    next to the program (~/.opsh after a normal install).
    """
    override = os.environ.get("OPSH_HOME")
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return Path.home() / ".opsh"
    return Path(__file__).parent.absolute()


config_dir = get_config_dir()
env_path = config_dir / ".env"
config_path = config_dir / "config.json"


def _write_private(path: Path, text: str) -> None:
    """Write a file that only the current user can read. API keys live here."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    if os.name != "nt":
        os.chmod(path, 0o600)  # tighten files created by older versions


def load_config() -> dict[str, Any]:
    """Load configuration from JSON file. A missing, unreadable or corrupt file counts as empty."""
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to JSON file."""
    _write_private(config_path, json.dumps(config, indent=2))


def _read_env_file() -> dict[str, str]:
    """Parse .env into a dict. Accepts `export KEY=value`, quotes and stray spaces."""
    values: dict[str, str] = {}
    try:
        with open(env_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def load_env() -> None:
    """Load .env into the environment. Variables that are already exported win."""
    for key, value in _read_env_file().items():
        os.environ.setdefault(key, value)


def save_api_key(provider: str, api_key: str) -> None:
    """Save API key to .env file."""
    env_vars = _read_env_file()
    if provider == "groq":
        env_vars["GROQ_API_KEY"] = api_key
    else:
        env_vars["GEMINI_API_KEY"] = api_key
    _write_private(env_path, "".join(f"{key}={value}\n" for key, value in env_vars.items()))


def _read_secret(prompt: str) -> str:
    """Read an API key without echoing it or leaving it in the line-editor history."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return input(prompt)


def setup_authentication() -> dict[str, str] | None:
    """Interactive authentication setup."""
    print("\n\033[1m🔐 OpenSH Setup\033[0m\n")
    print("Choose your AI provider:\n")
    print("  \033[36m1. Groq\033[0m (Recommended - fast, free tier)")
    print("  \033[90m2. Gemini\033[0m (Google AI - free tier)")
    print()

    choice = input("\033[33mSelect provider [1/2]:\033[0m ").strip()

    if choice == "2":
        provider = "gemini"
        key_url = "https://aistudio.google.com/apikey"
        print(f"\n\033[36m→ Get your free key at: {key_url}\033[0m")
        print("\033[90m  (Takes ~30 seconds - just click 'Create API Key')\033[0m\n")
    else:
        provider = "groq"
        key_url = "https://console.groq.com/keys"
        print(f"\n\033[36m→ Get your free key at: {key_url}\033[0m")
        print("\033[90m  (Sign up with Google/GitHub, create API key)\033[0m\n")

    open_browser = input("\033[33mOpen in browser? [Y/n]:\033[0m ").strip().lower()
    if open_browser != "n":
        webbrowser.open(key_url)
        print("\n\033[90mBrowser opened. Copy your API key and paste it below.\033[0m\n")

    api_key = _read_secret(f"\033[33mPaste your {provider.title()} API key (hidden):\033[0m ").strip()
    if not api_key:
        print("No API key provided.")
        return None

    save_api_key(provider, api_key)
    os.environ[f"{provider.upper()}_API_KEY"] = api_key

    # Save config. A model chosen for the previous provider would not exist on the new one.
    config = load_config()
    if config.get("provider") != provider:
        config.pop("model", None)
    config["provider"] = provider
    config["auth_method"] = "api_key"
    save_config(config)

    print(f"\033[32m✓ {provider.title()} API key saved!\033[0m\n")
    return {"provider": provider, "api_key": api_key}


# --- Providers --------------------------------------------------------------
# Hosted models are retired every few months. These defaults are the providers'
# documented replacements; OPSH_MODEL or "model" in config.json overrides them.
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "gemini": "gemini-3.6-flash"}
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
_MODEL_HINT = 'Set OPSH_MODEL or "model" in config.json to a current model.'


class ProviderError(Exception):
    """A provider call failed. kind is auth, rate_limit, model, network, response or api."""

    def __init__(self, message: str, kind: str = "api") -> None:
        super().__init__(message)
        self.kind = kind


def get_provider() -> str:
    """Configured provider, or the one whose key is exported, or "" when nothing is set up."""
    provider = load_config().get("provider")
    if provider in DEFAULT_MODELS:
        return str(provider)
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return ""


def get_model(provider: str) -> str:
    """Model to use: OPSH_MODEL, then "model" in config.json, then the built-in default."""
    configured = os.environ.get("OPSH_MODEL") or load_config().get("model")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return DEFAULT_MODELS[provider]


def _error_detail(error: urllib.error.HTTPError) -> str:
    """The provider's own error message, falling back to the raw body or the HTTP reason."""
    raw = ""
    if error.fp is not None:
        with contextlib.suppress(OSError, ValueError):
            raw = error.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        message = parsed["error"]["message"] if isinstance(parsed["error"], dict) else parsed["error"]
        return " ".join(str(message).split())[:300]
    except (ValueError, KeyError, TypeError, IndexError):
        text = " ".join(raw.split())[:300]
        return text or str(error.reason)


def _http_error(error: urllib.error.HTTPError, provider: str) -> ProviderError:
    """Turn an HTTP failure into an error the user can act on."""
    detail = _error_detail(error)
    low = detail.lower()
    if error.code == 429:
        return ProviderError("Rate limit - please wait a moment", "rate_limit")
    if "decommissioned" in low or ("model" in low and ("not found" in low or "not supported" in low
                                                         or "does not exist" in low)):
        return ProviderError(f"{provider} model unavailable: {detail} {_MODEL_HINT}", "model")
    if error.code in (401, 403) or "api key" in low or "api_key" in low:
        return ProviderError(f"{provider} rejected the API key - run !auth ({detail})", "auth")
    if error.code == 404:
        return ProviderError(f"{provider} model unavailable: {detail} {_MODEL_HINT}", "model")
    return ProviderError(f"API error {error.code}: {detail}", "api")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], provider: str) -> Any:
    """POST JSON and return the decoded reply. Retries rate limits, 5xx and network failures."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")  # noqa: S310 - fixed https URL
    failure = ProviderError("Request failed", "network")
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 - fixed https URL
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            failure = _http_error(e, provider)
            if e.code != 429 and not 500 <= e.code < 600:
                raise failure from None
            label = "Rate limit" if e.code == 429 else f"Server error {e.code}"
        except OSError as e:  # URLError, timeouts, connection resets
            failure = ProviderError(f"Network error: {getattr(e, 'reason', None) or e}", "network")
            label = "Network error"
        else:
            try:
                return json.loads(body)
            except ValueError:
                raise ProviderError(f"{provider} sent a reply that is not JSON", "response") from None
        if attempt < MAX_RETRIES - 1:
            wait_time = (attempt + 1) * 2
            print(f"\033[90m{label} - waiting {wait_time}s...\033[0m", file=sys.stderr)
            time.sleep(wait_time)
    raise failure


def call_groq(prompt: str, api_key: str, model: str | None = None) -> str:
    """Call Groq API directly using urllib (no external dependencies)."""
    model = model or DEFAULT_MODELS["groq"]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_completion_tokens": 1024,
    }
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"  # a one-line command does not need long reasoning
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": f"OpenSH/{__version__}",
    }
    result = _post_json("https://api.groq.com/openai/v1/chat/completions", payload, headers, "Groq")
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("Groq sent a reply with no command in it", "response") from None
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("Groq returned an empty reply - try rephrasing", "response")
    return content.strip()


def call_gemini(prompt: str, api_key: str, model: str | None = None) -> str:
    """Call Gemini API directly using urllib."""
    model = (model or DEFAULT_MODELS["gemini"]).removeprefix("models/")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.parse.quote(model, safe='')}:generateContent")
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"OpenSH/{__version__}",
        "x-goog-api-key": api_key,  # in a header, not the URL, so it stays out of proxy logs
    }
    result = _post_json(url, payload, headers, "Gemini")
    try:
        candidates = result.get("candidates") or []
        if not candidates:
            reason = (result.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError("Gemini returned no reply" + (f" (blocked: {reason})" if reason else ""), "response")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    except AttributeError:
        raise ProviderError("Gemini sent a reply with no command in it", "response") from None
    if not text.strip():
        reason = candidates[0].get("finishReason")
        raise ProviderError("Gemini returned an empty reply" + (f" ({reason})" if reason else ""), "response")
    return text.strip()


def get_ai_response(prompt: str) -> str:
    """Get AI response using configured provider."""
    provider = get_provider() or "groq"
    model = get_model(provider)

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ProviderError("No Gemini API key - run !auth", "auth")
        return call_gemini(prompt, api_key, model)
    else:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("No Groq API key - run !auth", "auth")
        return call_groq(prompt, api_key, model)


_FENCE_RE = re.compile(r"```(?:[\w+-]*[ \t]*\r?\n)?(.*?)```", re.DOTALL)


def clean_model_output(text: str) -> str:
    """Reduce a model reply to the bare command.

    Models sometimes wrap the command in a markdown fence or backticks, or put a
    "$ " prompt in front of it. Run as-is, a fence makes the shell start a nested
    shell waiting on the terminal, so those wrappers are removed here.
    """
    command = (text or "").strip()
    fenced = _FENCE_RE.search(command)
    if fenced:
        command = fenced.group(1).strip()
    if len(command) >= 2 and command[0] == command[-1] == "`" and "`" not in command[1:-1]:
        command = command[1:-1].strip()
    if command.startswith("$ "):
        command = command[2:].lstrip()
    if not command:
        raise ProviderError("The model returned no command - try rephrasing", "response")
    return command


def show_help() -> None:
    print("\033[36m!auth\033[0m      - Change API provider/key")
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
    provider = get_provider()
    print(f"\n\033[1mOpenSH\033[0m v{__version__}")
    print(f"Platform: {PLATFORM['name']} ({shell_name()})")
    print(f"Provider: {provider or 'not configured'}")
    if provider:
        print(f"Model: {get_model(provider)}")
    print(f"Config: {config_path.parent}")
    print(f"Python: {platform.python_version()}")
    print("GitHub: https://github.com/muhib-karim/OpenSH")
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


command_history: list[dict[str, str]] = []
MAX_HISTORY = 10
MAX_CONTEXT_CHARS = 4000

# Output of earlier commands is sent to the model as context. Anything shaped like
# a credential is replaced first, so `cat .env` does not forward the key.
_SECRET_RE = re.compile(
    r"gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}"
    r"|(\b[A-Za-z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*\s*[=:]\s*)\S+",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Replace API keys and KEY=value style credentials with [redacted]."""
    return _SECRET_RE.sub(lambda m: (m.group(1) or "") + "[redacted]", text)


def get_context_size() -> int:
    return sum(len(e["command"]) + len(e["output"]) for e in command_history)


def add_to_history(command: str, output: str = "") -> None:
    global commands_run
    commands_run += 1
    command_history.append({
        "command": redact_secrets(command),
        "output": redact_secrets(output)[:500] if output else ""
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
        if entry['output']:
            output_lines = entry['output'].strip().split('\n')[:2]
            for line in output_lines:
                lines.append(f"   {line}")
    return "\n".join(lines)


def _listing(folder: str | Path) -> list[str]:
    """First 20 names in a folder, sorted, with control characters escaped."""
    try:
        return [printable(item)[:120] for item in sorted(os.listdir(folder))[:20]]
    except OSError:
        return []


def get_file_context(cwd: str) -> str:
    """Get current directory and desktop file listings for AI context."""
    context_parts = []

    # Current directory listing (top 20 items)
    items = _listing(cwd)
    if items:
        context_parts.append(f"Files in current directory ({cwd}):\n" + "\n".join(f"  {item}" for item in items))

    # Desktop listing if not already in desktop
    desktop_path = Path.home() / "Desktop"
    if desktop_path.exists() and str(desktop_path) != cwd:
        items = _listing(desktop_path)
        if items:
            context_parts.append("Files on Desktop:\n" + "\n".join(f"  {item}" for item in items))

    return "\n\n".join(context_parts) if context_parts else ""


def get_command(user_input: str, cwd: str) -> str:
    history_context = format_history()
    file_context = get_file_context(cwd)

    # Platform-specific shell instructions
    if PLATFORM["name"] == "Windows":
        shell_instructions = """You are a shell command translator. Convert the user's request into a PowerShell command for Windows.
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
        quoting_example = '"C:\\Users\\Name\\Desktop\\Folder Name"'
    else:
        shell_instructions = f"""You are a shell command translator. Convert the user's request into a shell command for {shell_name()} on {PLATFORM['name']}."""
        quoting_example = '"~/Desktop/Folder Name"'

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
- Paths with spaces must be quoted: {quoting_example}
- If unclear, make a reasonable assumption
- Use the command history for context

User request: {user_input}"""

    return clean_model_output(get_ai_response(prompt))


# Words that are both a command and an everyday verb. "open report.pdf" is a
# command; "open the resume folder" is a request for the model.
_AMBIGUOUS_VERBS = {"open", "make", "copy", "move", "go", "cut", "type", "touch", "export", "source"}
_FUNCTION_WORDS = {"the", "my", "this", "that", "these", "those", "to", "into", "from", "in", "of",
                   "for", "with", "me", "please", "called", "named"}
_SHELLISH_RE = re.compile(r"^-|[/\\*?|<>$=~\"'`;&(){}]")


def _reads_like_prose(text: str) -> bool:
    """True for a sentence that merely starts with a command word."""
    words = text.split()
    if len(words) < 3 or words[0].lower() not in _AMBIGUOUS_VERBS:
        return False
    if any(_SHELLISH_RE.search(word) for word in words[1:]):
        return False  # flags, paths, globs or quoting: a real command line
    rest = [word.lower() for word in words[1:]]
    if len(words) == 3:
        return rest[0] in ("the", "my", "this", "that", "to")
    if any(word in _FUNCTION_WORDS for word in rest):
        return True
    return rest[0] in ("a", "an") and len(rest[1]) > 1


def is_natural_language(text: str) -> bool:
    if text.startswith("!"):
        return False

    # Exit commands
    if text.lower() in EXIT_WORDS:
        return False

    if _reads_like_prose(text):
        return True

    # Common shell commands that should run directly
    if PLATFORM["name"] == "Windows":
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
            "cd ", "cd\\", "cd/", "dir ", "echo ", "type ",
            "copy ", "move ", "del ", "ren ", "rename ", "md ", "mkdir ",
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
    return not any(text.lower().startswith(s.lower()) for s in shell_starters)


# --- Directory changes -------------------------------------------------------
# A directory change has to happen in this process, not in a subprocess.
_COMPOUND_RE = re.compile(r"[;&|\n<>`]|\$\(")
_previous_dir: str | None = None


def parse_cd(command: str) -> str | None:
    """Return the target if command is only a directory change, else None.

    "" means the home folder and "-" the previous one. Compound commands such as
    `cd build && make` return None so the whole line goes to the shell.
    """
    text = command.strip()
    if _COMPOUND_RE.search(text):
        return None
    names = "cd|chdir|set-location" + ("|sl" if PLATFORM["name"] == "Windows" else "")
    match = re.match(rf"(?i)^(?:{names})(?=$|\s)\s*(.*)$", text, re.DOTALL)
    if match:
        target = match.group(1).strip()
    else:
        match = re.match(r"(?i)^cd(\.\.[\\/.\w-]*|[\\/].*)$", text)  # cd.. cd\ cd/tmp
        if not match:
            return None
        target = match.group(1)
    target = re.sub(r"(?i)^(-path|-literalpath|/d)\s+", "", target)
    if len(target) >= 2 and target[0] == target[-1] and target[0] in "\"'":
        target = target[1:-1]
    return target


def change_directory(target: str) -> str | None:
    """Change directory. Returns an error message, or None when it worked."""
    global _previous_dir
    if target == "":
        path = str(Path.home())
    elif target == "-":
        if _previous_dir is None:
            return "cd: no previous directory"
        path = _previous_dir
    else:
        path = re.sub(r"(?i)\$env:(\w+)", lambda m: os.environ.get(m.group(1), m.group(0)), target)
        path = os.path.expandvars(os.path.expanduser(path))
        if PLATFORM["name"] == "Windows":
            path = path.replace("/", "\\")
    try:
        before = os.getcwd()
    except OSError:
        before = None
    try:
        os.chdir(path)
    except OSError as e:
        return f"cd: {e}"
    _previous_dir = before
    return None


# --- Safety guard -----------------------------------------------------------
# AI-generated commands run automatically, except ones that can destroy data or
# take the machine down. Those are shown and need an explicit "y" first.
#
# A command is checked in two forms: as written (with Unicode dashes and smart
# quotes mapped to ASCII and line continuations joined), and with quoting and
# escaping stripped, so `r\m`, "rm" and rm${IFS}-rf are all seen as rm. Anything
# the rules cannot see through (eval, a download piped into an interpreter,
# encoded PowerShell, a variable used as the command) is flagged too.
_S = r"[^;&|\n]*"  # stays inside one simple command
_I = re.IGNORECASE
_GUARD_RULES: list[tuple[str, str, int]] = [
    # deletes
    ("recursive or forced delete", rf"\brm\b(?={_S}\s-[a-z]*[rf])", _I),
    ("recursive or forced delete", rf"\brm\b(?={_S}\s--(recursive|force|no-preserve-root|dir)\b)", _I),
    ("recursive or forced delete", rf"\b(remove-item|ri|rmdir|rd|del|erase)\b(?={_S}\s(-r\w*|-fo\w*|/s|/q|/f)\b)", _I),
    ("wildcard delete", rf"\b(rm|remove-item|ri|del|erase)\b(?={_S}\*)", _I),
    ("mass delete", rf"\bxargs\b{_S}\b(rm|shred|unlink)\b", _I),
    ("mass delete", rf"\bfind\b{_S}\s-(delete\b|exec(dir)?\s+(sudo\s+)?(rm|shred|unlink)\b)", _I),
    ("mass delete", r"\|\s*(remove-item|ri|rm|del|erase|rd|rmdir)\b", _I),
    ("mass delete", rf"\bforfiles\b{_S}\b(del|erase|rd|rmdir|remove-item)\b", _I),
    ("delete through an API", r"\.delete\(|\]::delete\(|\b(rmtree|rm_rf|rmsync|removedirs)\b", _I),
    # wipes and overwrites
    ("data wipe", r"\b(shred|wipefs|blkdiscard|srm)\b", _I),
    ("data wipe", rf"\btruncate\b{_S}(-s\s*0\b|--size[= ]0\b)", _I),
    ("data wipe", rf"\bmv\b{_S}/dev/null\b|\brsync\b{_S}--delete|\bcrontab\b{_S}\s-[a-z]*r\b|\btar\b{_S}--remove-files", _I),
    ("data wipe", r"\bclear-(content|recyclebin|disk)\b|\breg\s+delete\b|\bvssadmin\s+delete\b|\bwevtutil\s+cl\b", _I),
    ("data wipe", rf"\bbcdedit\b{_S}/delete|\brobocopy\b{_S}/(mir|purge)\b", _I),
    ("system file overwrite", rf"(>\s*|\btee\b{_S}\s)(/etc/|/boot/|/proc/sysrq)", _I),
    # disks and filesystems
    ("disk or filesystem", r"\bmkfs(\.\w+)?\b|\bmke2fs\b|\bmkswap\b|\bnewfs\w*\b|\bdiskpart\b|\bcipher\s+/w", _I),
    ("disk or filesystem", rf"\b(fdisk|sfdisk|sgdisk|parted)\b(?!{_S}(\s-l\b|--list\b|\sprint\b))", _I),
    ("disk or filesystem", r"\bcryptsetup\s+(luksformat|erase)\b|\b(lv|vg|pv)remove\b|\bz(pool|fs)\s+destroy\b", _I),
    ("disk or filesystem", rf"\bhdparm\b{_S}--security-erase", _I),
    ("disk or filesystem", r"\bdiskutil\s+(erase\w*|zerodisk|secureerase|partitiondisk|reformat)\b", _I),
    ("disk or filesystem", r"\bformat(-volume)?\s+[a-z]:|\b(format-volume|initialize-disk|remove-partition)\b", _I),
    ("disk or filesystem", rf"\bdd\b{_S}\bof=", _I),
    ("raw device write", rf"(>\s*|\b(tee|cp|cat|dd)\b{_S}\s)/dev/(sd|hd|vd|xvd|nvme|mmcblk|r?disk|dm-|md\d|mapper/)", _I),
    # permissions (case-sensitive: chmod -R is recursive, chmod -r removes read access)
    ("recursive permission change", rf"\b(chmod|chown|chgrp|chattr|setfacl)\b(?={_S}\s(-[a-zA-Z]*R|--recursive\b))", 0),
    ("recursive permission change", rf"\b(icacls|cacls|takeown)\b{_S}\s/[tr]\b|\battrib\b{_S}\s/s\b", _I),
    ("permission change on /", rf"\bch(mod|own|grp)\b{_S}\s/(\s|$)", _I),
    # power and processes
    ("shutdown or reboot", r"\b(shutdown|reboot|halt|poweroff)\b|\b(stop|restart)-computer\b", _I),
    ("shutdown or reboot", r"\b(tel)?init\s+[06]\b|\bshut\s+down\b|\blogoff\b", _I),
    ("shutdown or reboot", rf"\bosascript\b{_S}\b(restart|shut\s*down)\b", _I),
    ("mass process kill", rf"\bkillall5?\b|\bpkill\b|\bkill\b{_S}\s-1\b|\btaskkill\b{_S}/f\b", _I),
    ("mass process kill", rf"\b(stop-process|spps)\b{_S}\s-fo|\|\s*(stop-process|spps|kill)\b", _I),
    ("fork bomb", r"([\w:]+)\s*\(\)\s*\{\s*\1\s*\|\s*\1\s*&|%0\s*\|\s*%0", _I),
    ("fork bomb", r"\bfork\s+while\b|\bwhile\b.*\bfork\b", _I | re.DOTALL),
    ("endless spawn loop", r"\bwhile\s*(\(\s*\$?true\s*\)|true\b|:|1\b).*(&\s*;?\s*done\b|start-process)", _I | re.DOTALL),
    ("endless spawn loop", r"\bfor\s*\(\s*;\s*;\s*\).*(&|start-process)", _I | re.DOTALL),
    # git
    ("git history rewrite", rf"\bgit\b(?={_S}\bpush\b)(?={_S}(\s--force|\s-f\b|\s--mirror|\s--delete|\s-d\b|\s\+\w|\s:\w))", _I),
    ("git history rewrite", rf"\bgit\b(?={_S}\breset\b)(?={_S}--hard\b)", _I),
    ("git data loss", rf"\bgit\b(?={_S}\bclean\b)(?={_S}(\s-[a-z]*f|--force))", _I),
    ("git data loss", rf"\bgit\b{_S}\b(checkout|restore)\b{_S}\s(--\s+)?\.(\s|$)|\bgit\b{_S}\bstash\s+(clear|drop)\b", _I),
    ("git data loss", rf"\bgit\b{_S}\b(filter-branch|filter-repo|reflog\s+expire|update-ref\s+-d)\b|--prune=now", _I),
    ("git data loss", rf"\bgit\b{_S}\bbranch\b{_S}\s-D\b", 0),
    # databases and infrastructure
    ("database", r"\bdrop\s+(table|database|schema|index|view|user|role)\b|\bdelete\s+from\b", _I),
    ("database", r"\btruncate\s+(table\s+)?[a-z_]\w*", _I),
    ("database", rf"\bdropdb\b|\bmysqladmin\b{_S}\bdrop\b|dropdatabase\(|\bflush(all|db)\b", _I),
    ("infrastructure", rf"\bdocker\b{_S}\bprune\b|\bdocker\b{_S}\bvolume\s+rm\b|\bdocker\b{_S}\bdown\b{_S}(\s-v\b|--volumes)", _I),
    ("infrastructure", rf"\bkubectl\b{_S}\bdelete\b|\bhelm\s+(uninstall|delete)\b|\bterraform\b{_S}\bdestroy\b", _I),
    ("infrastructure", rf"\baws\b{_S}(\srb\s|terminate-instances|\sdelete-)|\b(gcloud|az|gsutil)\b{_S}\s(delete|rm)\b", _I),
    ("system accounts", r"\buserdel\b|\bpasswd\s+-d\b|\biptables\s+(-f|--flush)\b", _I),
    # running code the guard cannot read
    ("pipe into a shell", r"\|&?\s*(sudo\s+(-\S+\s+)*)?(env\s+)?(\S*/)?((ba|z|da|k|fi|c|tc)?sh|pwsh|powershell)\b", _I),
    ("pipe into an interpreter", r"\|&?\s*(sudo\s+(-\S+\s+)*)?(env\s+)?(\S*/)?(python[\d.]*|perl|ruby|node|php)(\s+-)?\s*($|[;&|\n])", _I),
    ("pipe into a shell", rf"\|\s*xargs\b{_S}\b(ba|z|da|k)?sh\b", _I),
    ("download and run", r"(^|[\s;&|])(\.|source|(ba|z|da|k)?sh)\s+<\(|\$\([^)]*\b(curl|wget|fetch|iwr|irm)\b", _I),
    ("download and run", r"\b(curl|wget|fetch|iwr|irm|invoke-webrequest|invoke-restmethod|certutil|bitsadmin|start-bitstransfer)\b"
                         r".*(&&|;|\|\||\n).*(\b(ba|z|da|k)?sh\s|\bchmod\s+\+x|(^|\s)\.[/\\]|\.exe\b|\bpython[\d.]*\s|\bstart-process\b)",
     _I | re.DOTALL),
    ("download and run", rf"\b(iex|invoke-expression)\b|downloadstring\(|frombase64string|\bmshta\b|\bregsvr32\b{_S}/i:", _I),
    ("download and run", rf"\bcertutil\b{_S}-urlcache|\bbitsadmin\b{_S}/transfer", _I),
    ("hidden command", rf"\beval\b|\b(powershell|pwsh)(\.exe)?\b{_S}\s-e\w*\s+[a-z0-9+/=]{{12,}}", _I),
    ("hidden command", r"\$'[^']*\\(x[0-9a-f]{2}|[0-7]{3})|\b(ba|z|da|k)?sh\s+-c\s+[\"']?\$\(", _I),
    ("hidden command", r"(^|[;&|\n]\s*)(\$\{?\w+(:-[^}]*)?\}?\s+-\w|\$\(|`)", _I),
    ("hidden command", rf"\b(python[\d.]*|perl|ruby|node|php)\b{_S}\s-(c|e)\b"
                       r".*(os\.(system|remove|unlink|fork)|subprocess|shutil|system\(|exec\(|unlink|child_process|urlopen)",
     _I | re.DOTALL),
    ("control characters", r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", 0),
]
_GUARD = [(reason, re.compile(pattern, flags)) for reason, pattern, flags in _GUARD_RULES]
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = {**dict.fromkeys(map(ord, "\u201c\u201d\u201e"), '"'), **dict.fromkeys(map(ord, "\u2018\u2019\u201a"), "'")}


def _guard_views(cmd: str) -> Iterator[str]:
    """The two forms of a command the rules are matched against."""
    raw = cmd.translate(_DASHES).translate(_QUOTES)
    raw = re.sub(r"\\\r?\n", "", raw)  # shell line continuations
    yield raw
    text = re.sub(r"/\*.*?\*/", " ", raw, flags=re.DOTALL)  # SQL comments
    text = re.sub(r"\$\{?IFS\}?", " ", text)  # $IFS used as a space
    text = re.sub(r"\$\{\w*\}", "", text)  # empty-variable padding such as r${x}m
    text = re.sub(r"[\"'`^]", "", text)  # quotes, PowerShell backticks, cmd carets
    text = re.sub(r"\\(?=[A-Za-z-])", "", text)  # r\m, -\rf
    yield re.sub(r"[ \t]+", " ", text)


def destructive_reason(cmd: str) -> str | None:
    """Why a command needs confirmation, or None when it may run straight away."""
    if not cmd:
        return None
    for view in _guard_views(cmd):
        for reason, pattern in _GUARD:
            if pattern.search(view):
                return reason
    return None


def is_destructive(cmd: str) -> bool:
    """True when a command could delete data, wipe a disk, rewrite history or stop the machine."""
    return destructive_reason(cmd) is not None


def confirm_if_destructive(cmd: str, assume_yes: bool = False, ask: Callable[[str], str] = input) -> bool:
    """Return True if the command may run. Destructive commands need an explicit yes."""
    reason = destructive_reason(cmd)
    if reason is None or assume_yes:
        return True
    try:
        answer = ask(f"\033[31m⚠ Flagged: {reason}. This command can delete data or stop your machine. "
                     "Run it? [y/N]\033[0m ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("y", "yes")


# --- Running commands --------------------------------------------------------
class CommandResult(NamedTuple):
    stdout: str
    stderr: str
    returncode: int


# Full-screen programs need the real terminal, so their output is not captured.
INTERACTIVE_COMMANDS = {"vim", "vi", "nvim", "nano", "emacs", "top", "htop", "less", "more", "man",
                        "ssh", "watch", "tmux", "screen"}


def _is_interactive(cmd: str) -> bool:
    if re.search(r"[|;&<>\n]", cmd):
        return False
    words = cmd.split()
    if words and words[0] == "sudo":
        words = words[1:]
    return bool(words) and os.path.basename(words[0]).lower() in INTERACTIVE_COMMANDS


def _command_timeout() -> float | None:
    """Seconds a command may run. OPSH_TIMEOUT overrides it; 0 means no limit."""
    raw = os.environ.get("OPSH_TIMEOUT")
    if raw is not None:
        try:
            value = float(raw)
        except ValueError:
            value = -1.0
        if value == 0:
            return None
        if value > 0:
            return value
    return 60.0 if PLATFORM["name"] == "Windows" else None


def _kill_tree(process: subprocess.Popen[str]) -> None:
    """Stop a command and whatever it started, then collect it without waiting forever."""
    if os.name == "nt":
        # Killing only the shell would leave its children running and holding the pipes.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],  # noqa: S603, S607 - fixed system tool
                       capture_output=True, check=False)
    process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
        process.communicate(timeout=5)


def execute(cmd: str) -> CommandResult:
    """Run a command in the user's shell and return its output and exit code."""
    args: Any
    kwargs: dict[str, Any] = {}
    if PLATFORM["name"] == "Windows":
        args = ["powershell", "-NoProfile", "-Command", cmd]
    else:
        args = cmd
        kwargs["shell"] = True
        shell = detect_shell() if os.name != "nt" else None
        if shell:
            kwargs["executable"] = shell
    timeout = _command_timeout()
    try:
        if _is_interactive(cmd) and sys.stdin.isatty() and sys.stdout.isatty():
            # No time limit here: an editor or ssh session lasts as long as the user wants.
            done = subprocess.run(args, check=False, **kwargs)  # noqa: S603 - running commands is the point
            return CommandResult("", "", done.returncode)
        process = subprocess.Popen(  # noqa: S603 - running commands is the point
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **kwargs,
        )
    except OSError as e:
        return CommandResult("", str(e), 127)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        return CommandResult("", "Command timed out", 124)
    except BaseException:  # Ctrl+C: stop the child, then let the caller handle it
        _kill_tree(process)
        raise
    return CommandResult(stdout, stderr, process.returncode)


def run_command(cmd: str) -> tuple[str, str]:
    """Run a command and return (stdout, stderr)."""
    result = execute(cmd)
    return result.stdout, result.stderr


def _show(result: CommandResult) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)


def run_raw(cmd: str) -> int:
    """Run a command the user typed themselves. These are not checked by the guard."""
    result = execute(cmd)
    _show(result)
    add_to_history(cmd, result.stdout + result.stderr)
    return result.returncode


def handle_generated(command: str, assume_yes: bool, single: bool = False) -> int:
    """Show, vet and run one model-generated command. Returns its exit code."""
    print(f"\033[33m→ {printable(command)}\033[0m")
    target = parse_cd(command)
    if target is not None:
        if single:
            print("\033[90m(a directory change only lasts inside OpenSH; run it in your own shell)\033[0m")
            return 0
        error = change_directory(target)
        if error:
            print(error)
            return 1
        add_to_history(command)
        return 0
    if not confirm_if_destructive(command, assume_yes):
        print("\033[90mSkipped.\033[0m")
        return 1
    result = execute(command)
    _show(result)
    add_to_history(command, result.stdout + result.stderr)
    return result.returncode


# --- Terminal handling -------------------------------------------------------
class _PlainStream:
    """Passes writes through with colour codes removed (output is a pipe, a file, or NO_COLOR is set)."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        return int(self._stream.write(_ANSI_RE.sub("", text)) or 0)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _isatty(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _configure_stdio() -> None:
    """Never crash on a character the console cannot encode, and keep colour codes out of pipes."""
    global _color_enabled
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="replace")
    no_color = "NO_COLOR" in os.environ
    _color_enabled = _isatty(sys.stdout) and not no_color
    if not _color_enabled and not isinstance(sys.stdout, _PlainStream):
        sys.stdout = _PlainStream(sys.stdout)
    if (no_color or not _isatty(sys.stderr)) and not isinstance(sys.stderr, _PlainStream):
        sys.stderr = _PlainStream(sys.stderr)


def build_prompt(cwd: str) -> str:
    """The input prompt. Colour codes are marked as zero-width so readline counts columns correctly."""
    if not _color_enabled:
        return f"{cwd} > "
    if _HAVE_READLINE and os.name != "nt" and _isatty(sys.stdin):
        return f"\001\033[32m\002{cwd}\001\033[0m\002 > "
    return f"\033[32m{cwd}\033[0m > "


def _thinking(on: bool) -> None:
    if not _color_enabled:
        return
    if on:
        print("\033[90m⏳ thinking...\033[0m", end="\r", flush=True)
    else:
        print(" " * 20, end="\r", flush=True)


def _safe_cwd() -> str:
    """Current folder; falls back to home if the folder was deleted underneath us."""
    try:
        return os.getcwd()
    except OSError:
        os.chdir(Path.home())
        print("\033[90m(the current folder no longer exists; moved to your home folder)\033[0m")
        return os.getcwd()


def report_provider_error(error: ProviderError) -> None:
    if error.kind == "auth":
        print(f"\033[31mAuth error: {error}\033[0m", file=sys.stderr)
    elif error.kind == "rate_limit":
        print("\033[31mRate limit hit - wait a moment and try again\033[0m", file=sys.stderr)
    else:
        print(f"\033[31mError: {error}\033[0m", file=sys.stderr)


def uninstall() -> bool:
    """Remove ~/.opsh and the launcher. Returns False when something could not be removed."""
    install_dir = Path.home() / ".opsh"
    if PLATFORM["name"] == "Windows":
        bin_path = install_dir / "opsh.cmd"
    else:
        bin_path = Path.home() / ".local" / "bin" / "opsh"
    try:
        if install_dir.exists():
            shutil.rmtree(install_dir)
        if bin_path.exists():
            os.remove(bin_path)
    except OSError as e:
        print(f"\033[31mCould not remove everything: {e}\033[0m")
        script = "uninstall.ps1" if PLATFORM["name"] == "Windows" else "uninstall.sh"
        print(f"Close OpenSH, then delete {install_dir} yourself or run {script}.")
        return False
    print("\033[32m✓ OpenSH uninstalled\033[0m")
    return True


def run_single(query: str, assume_yes: bool) -> int:
    """`opsh -c`: one request, then exit with the command's status."""
    try:
        _thinking(True)
        try:
            command = get_command(query, _safe_cwd())
        finally:
            _thinking(False)
        return handle_generated(command, assume_yes, single=True)
    except (KeyboardInterrupt, InterruptedError):
        return 130
    except ProviderError as e:
        report_provider_error(e)
        return 1
    except Exception as e:
        print(f"\033[31mError: {e}\033[0m", file=sys.stderr)
        return 1


def repl(assume_yes: bool) -> int:
    """The interactive shell."""
    check_for_updates()

    print("\033[1mOpenSH\033[0m ready! Type naturally or use !help\n")

    while True:
        try:
            cwd = _safe_cwd()
            # Show full path like default Windows terminal
            user_input = input(build_prompt(cwd)).strip()

            if not user_input:
                continue

            # Exit commands
            if user_input.lower() in EXIT_WORDS:
                show_goodbye()
                return 0

            # Directory changes have to happen in this process
            target = parse_cd(user_input)
            if target is not None:
                error = change_directory(target)
                if error:
                    print(error)
                continue

            if user_input == "!auth":
                auth_result = setup_authentication()
                if auth_result:
                    print("\033[32m✓ Authentication updated!\033[0m\n")
                continue

            if user_input == "!version":
                show_version()
                continue

            if user_input == "!uninstall":
                confirm = input("\033[33mRemove OpenSH? [y/N]\033[0m ").strip().lower()
                if confirm in ("y", "yes") and uninstall():
                    return 0
                continue

            if user_input == "!help":
                show_help()
                continue

            if user_input == "!credits":
                show_credits()
                continue

            if user_input.startswith("!"):
                cmd = user_input[1:].strip()
                if cmd:
                    run_raw(cmd)
                continue

            if not is_natural_language(user_input):
                run_raw(user_input)
                continue

            _thinking(True)
            try:
                command = get_command(user_input, cwd)
            finally:
                _thinking(False)
            handle_generated(command, assume_yes)

        except (EOFError, KeyboardInterrupt):
            show_goodbye()
            return 0
        except InterruptedError:
            continue
        except ProviderError as e:
            report_provider_error(e)
        except Exception as e:  # keep the shell alive whatever a single request does
            print(f"\033[31mError: {e}\033[0m", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opsh",
        description="OpenSH - Talk to your terminal in plain English",
        epilog="Example: opsh -c 'show me large files'"
    )
    parser.add_argument(
        '-c', '--command',
        nargs='*',
        help='Run a single natural language query and exit'
    )
    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='Run destructive AI-generated commands without asking (use with care)'
    )
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'OpenSH v{__version__}'
    )
    args = parser.parse_args(argv)
    if args.command is not None and not " ".join(args.command).strip():
        parser.error('-c needs a request, for example: opsh -c "show me large files"')

    original_stdout, original_stderr = sys.stdout, sys.stderr
    _configure_stdio()
    load_env()

    # Ctrl+C cancels the current line instead of killing the shell (not on Windows)
    previous_handler: Any = None
    install_handler = platform.system() != "Windows" and threading.current_thread() is threading.main_thread()
    if install_handler:
        previous_handler = signal.signal(signal.SIGINT, exit_handler)
    try:
        # First run: no provider configured and no key in the environment
        if not get_provider():
            if not _isatty(sys.stdin):
                print("OpenSH is not set up yet. Run `opsh` once in a terminal, "
                      "or export GROQ_API_KEY or GEMINI_API_KEY.", file=sys.stderr)
                return 1
            print("\n\033[1m🚀 Welcome to OpenSH!\033[0m")
            print("Talk to your terminal in plain English.\n")
            try:
                auth_result = setup_authentication()
            except (EOFError, KeyboardInterrupt, InterruptedError):
                print()
                return 130
            if not auth_result:
                print("\033[31mAuthentication required to use OpenSH.\033[0m")
                return 1

        if args.command:
            return run_single(" ".join(args.command), args.yes)
        return repl(args.yes)
    finally:
        if install_handler:
            signal.signal(signal.SIGINT, previous_handler if previous_handler is not None else signal.SIG_DFL)
        sys.stdout, sys.stderr = original_stdout, original_stderr


if __name__ == "__main__":
    sys.exit(main())
