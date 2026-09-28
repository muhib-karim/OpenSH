#!/usr/bin/env python3
"""
OpenSH - Open Natural Language Shell
Talk to your terminal in plain English.

Based on nlsh (https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood

Support: https://ko-fi.com/ai_dev_2024
"""

__version__ = "0.2.0"

import signal
import os
import re
import sys
import subprocess
import platform
import json
import webbrowser
import argparse
import time
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# Session stats
session_start = datetime.now()
commands_run = 0

# Cross-platform readline support
if platform.system() == "Windows":
    try:
        import pyreadline3 as readline
    except ImportError:
        readline = None
else:
    import readline

def get_platform_info():
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

def check_for_updates():
    """Check GitHub for new version (silent, non-blocking)."""
    try:
        url = "https://api.github.com/repos/ai-dev-2024/OpenSH/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenSH"})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest = data.get("tag_name", "").lstrip("v")
            if latest and version_tuple(latest) > version_tuple(__version__):
                print(f"\033[33m📦 New version available: v{latest} (you have v{__version__})\033[0m")
                print(f"\033[90m   Update: https://github.com/ai-dev-2024/OpenSH/releases/tag/v{latest}\033[0m\n")
    except Exception:
        pass  # Silently fail - don't block startup

def version_tuple(version: str) -> tuple:
    """Turn '0.2.0' / 'v0.10.1' into (0, 2, 0) / (0, 10, 1) for comparison."""
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])

def exit_handler(sig, frame):
    os.write(sys.stdout.fileno(), b"\n")  # print() is not safe inside a signal handler
    raise InterruptedError()

if getattr(sys, "frozen", False):
    # Standalone (PyInstaller) builds unpack to a temp dir that is deleted on exit,
    # so keep their settings in a fixed folder (not ~/.opsh, which the installers manage)
    script_dir = Path.home() / ".config" / "opsh"
else:
    script_dir = Path(__file__).parent.absolute()
env_path = script_dir / ".env"
config_path = script_dir / "config.json"

_config_warning_shown = False

def load_config():
    """Load configuration from JSON file."""
    global _config_warning_shown
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            if isinstance(config, dict):
                return config
        except (OSError, ValueError):
            pass
        if not _config_warning_shown:
            _config_warning_shown = True
            print(f"\033[33mIgnoring invalid config file: {config_path}\033[0m")
    return {}

def save_config(config: dict):
    """Save configuration to JSON file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

API_KEY_VARS = ("GROQ_API_KEY", "GEMINI_API_KEY")
# Keys the user exported in their own shell (as opposed to ones OpenSH read from .env)
_keys_from_shell = set()

def load_env():
    _keys_from_shell.update(key for key in API_KEY_VARS if os.getenv(key))
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key.startswith("export "):
                        key = key[len("export "):].strip()
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    os.environ[key] = value

def command_env() -> dict:
    """Environment for the commands OpenSH runs, without the API keys it loaded itself."""
    env = os.environ.copy()
    for key in API_KEY_VARS:
        if key not in _keys_from_shell:
            env.pop(key, None)
    return env

def save_api_key(provider: str, api_key: str):
    """Save API key to .env file."""
    env_vars = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value
    
    if provider == "groq":
        env_vars["GROQ_API_KEY"] = api_key
    else:
        env_vars["GEMINI_API_KEY"] = api_key
    
    # The file holds API keys, so create it readable by the current user only
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
    try:
        os.chmod(env_path, 0o600)  # also tighten files created by older versions
    except OSError:
        pass

def get_provider():
    """Configured provider, else whichever API key is set in the environment."""
    provider = load_config().get("provider")
    if provider:
        return provider
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return None

def setup_authentication():
    """Interactive authentication setup."""
    print("\n\033[1m🔐 OpenSH Setup\033[0m\n")
    print("Choose your AI provider:\n")
    print("  \033[36m1. Groq\033[0m (Recommended - Fast, reliable, 30 req/min)")
    print("  \033[90m2. Gemini\033[0m (Google AI - 15 req/min)")
    print()
    
    choice = input("\033[33mSelect provider [1/2]:\033[0m ").strip()
    
    if choice == "2":
        provider = "gemini"
        print("\n\033[36m→ Get your free key at: https://aistudio.google.com/apikey\033[0m")
        print("\033[90m  (Takes ~30 seconds - just click 'Create API Key')\033[0m\n")
        open_browser = input("\033[33mOpen in browser? [Y/n]:\033[0m ").strip().lower()
        if open_browser != 'n':
            webbrowser.open("https://aistudio.google.com/apikey")
            print("\n\033[90mBrowser opened. Copy your API key and paste it below.\033[0m\n")
    else:
        provider = "groq"
        print("\n\033[36m→ Get your free key at: https://console.groq.com/keys\033[0m")
        print("\033[90m  (Sign up with Google/GitHub, create API key)\033[0m\n")
        open_browser = input("\033[33mOpen in browser? [Y/n]:\033[0m ").strip().lower()
        if open_browser != 'n':
            webbrowser.open("https://console.groq.com/keys")
            print("\n\033[90mBrowser opened. Copy your API key and paste it below.\033[0m\n")
    
    api_key = input(f"\033[33mPaste your {provider.title()} API key:\033[0m ").strip()
    if not api_key:
        print("No API key provided.")
        return None
    
    save_api_key(provider, api_key)
    os.environ[f"{provider.upper()}_API_KEY"] = api_key
    
    # Save config
    config = load_config()
    config["provider"] = provider
    config["auth_method"] = "api_key"
    save_config(config)
    
    print(f"\033[32m✓ {provider.title()} API key saved!\033[0m\n")
    return {"provider": provider, "api_key": api_key}

# Default models; override with "groq_model" / "gemini_model" in config.json.
# llama-3.3-70b-versatile and gemini-2.0-flash were retired by the providers in 2026.
GROQ_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-3.6-flash"

def api_error_message(code: int, body: str) -> str:
    """Short error text: the provider's error.message if the body is JSON."""
    try:
        message = json.loads(body)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = body
    return f"API error {code}: {str(message)[:200]}"

def call_groq(prompt: str, api_key: str) -> str:
    """Call Groq API directly using urllib (no external dependencies)."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    model = load_config().get("groq_model") or GROQ_MODEL
    
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1024
    }
    if model.startswith("openai/gpt-oss"):
        # Reasoning model: keep the thinking short and out of the reply
        body["reasoning_effort"] = "low"
        body["include_reasoning"] = False
    data = json.dumps(body).encode('utf-8')
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": f"OpenSH/{__version__}"
    }
    
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                try:
                    return result["choices"][0]["message"]["content"].strip()
                except (KeyError, IndexError, TypeError, AttributeError):
                    raise Exception("Unexpected response from Groq API")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"\033[90mRate limit - waiting {wait_time}s...\033[0m")
                    time.sleep(wait_time)
                    continue
                raise Exception("Rate limit - please wait a moment")
            else:
                error_body = e.read().decode('utf-8') if e.fp else str(e)
                raise Exception(api_error_message(e.code, error_body))
        except urllib.error.URLError as e:
            raise Exception(f"Network error: {e.reason}")

def call_gemini(prompt: str, api_key: str) -> str:
    """Call Gemini API directly using urllib."""
    model = load_config().get("gemini_model") or GEMINI_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
    data = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
        "User-Agent": f"OpenSH/{__version__}"
    }
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                try:
                    parts = result["candidates"][0]["content"]["parts"]
                    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                except (KeyError, IndexError, TypeError, AttributeError):
                    raise Exception("Unexpected response from Gemini API (the request may have been blocked)")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"\033[90mRate limit - waiting {wait_time}s...\033[0m")
                    time.sleep(wait_time)
                    continue
                raise Exception("Rate limit - please wait a moment")
            else:
                error_body = e.read().decode('utf-8') if e.fp else str(e)
                raise Exception(api_error_message(e.code, error_body))
        except urllib.error.URLError as e:
            raise Exception(f"Network error: {e.reason}")

def get_ai_response(prompt: str) -> str:
    """Get AI response using configured provider."""
    provider = get_provider() or "groq"
    
    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise Exception("No Gemini API key - run !auth")
        return call_gemini(prompt, api_key)
    else:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise Exception("No Groq API key - run !auth")
        return call_groq(prompt, api_key)

def show_help():
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
        print("\033[36mCtrl+C\033[0m     - Cancel the current line or command")
        print("\033[36mCtrl+D\033[0m     - Exit OpenSH")
    print()

def show_version():
    provider = get_provider() or "not configured"
    print(f"\n\033[1mOpenSH\033[0m v{__version__}")
    print(f"Platform: {PLATFORM['name']} ({PLATFORM['shell']})")
    print(f"Provider: {provider}")
    print(f"Python: {platform.python_version()}")
    print(f"GitHub: https://github.com/ai-dev-2024/OpenSH")
    print()

def show_credits():
    print("\n\033[36m─────────────────────────────────────────\033[0m")
    print(f"\033[1mOpenSH\033[0m v{__version__} - Open Natural Language Shell")
    print("Based on \033[36mnlsh\033[0m by Junaid Mahmood")
    print("https://github.com/junaid-mahmood/nlsh")
    print("\n☕ Support: \033[33mhttps://ko-fi.com/ai_dev_2024\033[0m")
    print("\033[36m─────────────────────────────────────────\033[0m\n")

def show_goodbye():
    global commands_run, session_start
    duration = datetime.now() - session_start
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)
    print(f"\n\033[36m─────────────────────────────────────────\033[0m")
    print(f"Session: {minutes}m {seconds}s | Commands: {commands_run}")
    print("\033[36mGoodbye! Thanks for using OpenSH ☕\033[0m")
    print("\033[36m─────────────────────────────────────────\033[0m\n")

command_history = []
MAX_HISTORY = 10
MAX_CONTEXT_CHARS = 4000

def get_context_size() -> int:
    return sum(len(e["command"]) + len(e["output"]) for e in command_history)

def add_to_history(command: str, output: str = ""):
    global commands_run
    commands_run += 1
    command_history.append({
        "command": command,
        "output": output[:500] if output else ""
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

def get_file_context(cwd: str) -> str:
    """Get current directory and desktop file listings for AI context."""
    context_parts = []
    
    # Current directory listing (top 20 items)
    try:
        items = os.listdir(cwd)[:20]
        if items:
            context_parts.append(f"Files in current directory ({cwd}):\n" + "\n".join(f"  {item}" for item in items))
    except:
        pass
    
    # Desktop listing if not already in desktop
    desktop_path = Path.home() / "Desktop"
    if desktop_path.exists() and str(desktop_path) != cwd:
        try:
            items = os.listdir(desktop_path)[:20]
            if items:
                context_parts.append(f"Files on Desktop:\n" + "\n".join(f"  {item}" for item in items))
        except:
            pass
    
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
    else:
        shell_instructions = f"""You are a shell command translator. Convert the user's request into a shell command for {PLATFORM['shell']} on {PLATFORM['name']}."""
    
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

    command = clean_command(get_ai_response(prompt))
    if not command:
        raise Exception("AI returned an empty command")
    return command

def clean_command(text: str) -> str:
    """Strip markdown code fences/backticks that models sometimes add despite the prompt."""
    text = text.strip()
    block = re.search(r"```[^\n`]*\n(.*?)```", text, re.DOTALL)
    if block:
        # Keep only the fenced command when the model wraps it in prose
        text = block.group(1).strip()
    elif text.startswith("```"):
        lines = text.split("\n")
        if len(lines) == 1:
            return lines[0].strip("`").strip()
        body = lines[1:]  # drop the opening fence and its language tag
        if body and body[-1].strip().startswith("```"):
            body = body[:-1]
        text = "\n".join(body).strip()
    elif len(text) > 1 and text[0] == "`" and text[-1] == "`":
        text = text[1:-1].strip()
    if text.startswith("$ "):
        text = text[2:]  # a copied shell prompt
    return text

# Commands that delete data, kill processes, power off the machine or run downloaded code.
# Matched at a command position: start of line, after ; & | ( ` $( , behind wrappers such
# as sudo/xargs/env (with their options), a backslash, or a path like /bin/.
_CMD_START = (
    r"(?:^|[;&|(`]|\$\()\s*"
    r"(?:(?:sudo|doas|xargs|env|command|nohup|nice|time)(?:\s+-\S+)*\s+)*"
    r"\\?(?:\S*/)?"
)
DESTRUCTIVE_PATTERNS = [
    _CMD_START + r"(?:rm|rmdir|unlink|shred|dd|truncate|mkfs(?:\.\w+)?|fdisk|wipefs|diskpart|format)\b",
    _CMD_START + r"(?:del|erase|rd)\b",
    _CMD_START + r"(?:kill|killall|pkill|taskkill|shutdown|reboot|poweroff|halt)\b",
    _CMD_START + r"(?:chmod|chown)\s+(?:[^\s;&|]+\s+)*-\w*R",
    _CMD_START + r"systemctl\s+(?:reboot|poweroff|halt|suspend|hibernate)\b",
    _CMD_START + r"crontab\s+(?:-\w+\s+)*-r\b",
    r"(?:^|;|&&|\|\|)\s*>(?!>)\s*\S",  # "> file" empties the file
    r"\b(?:Remove-Item|Clear-Content|Clear-RecycleBin|Format-Volume|Clear-Disk|Stop-Process|Stop-Computer|Restart-Computer)\b",
    r"\bgit\s+(?:reset\s+--hard|clean\b|restore\b|checkout\s+(?:--|\.)(?:\s|$)|branch\s+-D\b|stash\s+(?:drop|clear)\b|push\b.*(?:--force|\s-f\b))",
    r"\bfind\b.*\s-(?:delete\b|exec(?:dir)?\s+(?:\S*/)?rm\b)",
    r"\brsync\b.*\s--delete",
    r"\bdocker\s+(?:(?:system|volume|image|container|network|builder)\s+)?(?:prune|rm|rmi)\b",
    r"\|\s*(?:sudo\s+)?(?:\S*/)?(?:ba|z|da|k)?sh\b",  # piping downloaded text into a shell
    _CMD_START + r"eval\b",
]

def is_destructive(command: str) -> bool:
    """Heuristic check for AI-generated commands that should not run without asking."""
    return any(re.search(p, command, re.IGNORECASE | re.MULTILINE) for p in DESTRUCTIVE_PATTERNS)

def confirm_command(command: str) -> bool:
    """Ask before running a risky AI-generated command. Defaults to No."""
    if not is_destructive(command):
        return True
    try:
        answer = input("\033[31m⚠️  This command can delete or change data. Run it? [y/N]\033[0m ")
    except EOFError:
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        return True
    print("\033[90mSkipped.\033[0m")
    return False

# Words that follow the first word of an English request ("make a folder") but
# rarely the name of a command
ENGLISH_WORDS = {
    "a", "an", "the", "my", "me", "to", "up", "into", "some", "this", "that",
    "these", "those", "every", "it", "for", "and", "what", "which", "how",
}

def is_natural_language(text: str) -> bool:
    if text.startswith("!"):
        return False
    
    # Exit commands
    if text.lower() in ["exit", "quit", "bye", "goodbye"]:
        return False
    
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
    words = text_lower.split()
    if len(words) > 1 and words[1] in ENGLISH_WORDS:
        return True  # "make a folder...", "open the readme", "go to downloads"
    return not any(text.lower().startswith(s.lower()) for s in shell_starters)

# Full-screen or interactive programs (editors, pagers, monitors, remote shells)
INTERACTIVE_COMMANDS = {
    "vi", "vim", "nvim", "nano", "emacs", "less", "more", "man",
    "top", "htop", "watch", "ssh", "tmux", "screen",
}
# Interpreters and database clients start a REPL when run without arguments
REPL_COMMANDS = {
    "python", "python3", "ipython", "node", "irb", "psql", "mysql", "sqlite3",
    "bash", "zsh", "sh", "fish",
}

def is_interactive(cmd: str) -> bool:
    """Commands that need the terminal: they would appear to hang if their output were captured."""
    words = cmd.split()
    if not words:
        return False
    if words[0] == "sudo":
        return True  # password and [Y/n] prompts must be visible
    name = os.path.basename(words[0])
    if name in INTERACTIVE_COMMANDS or (len(words) == 1 and name in REPL_COMMANDS):
        return True
    if re.match(r"git\s+commit\b", cmd) and not re.search(r"\s(?:-\w*[mF]|--message|--file|--no-edit)\b", cmd):
        return True  # opens an editor for the commit message
    return re.search(r"\|\s*(?:less|more)\s*$", cmd) is not None

def current_dir() -> str:
    """os.getcwd(), moving to the home directory if the current one was deleted."""
    try:
        return os.getcwd()
    except FileNotFoundError:
        os.chdir(Path.home())
        return os.getcwd()

def is_compound(cmd: str) -> bool:
    """True for commands chained with && || ; | or newlines."""
    return re.search(r"&&|\|\||[;|\n]", cmd) is not None

def run_command(cmd: str) -> tuple:
    """Run a command and return (stdout, stderr)."""
    try:
        if PLATFORM["name"] == "Windows":
            # Use Popen for better output handling on Windows
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=command_env()
            )
            stdout, stderr = process.communicate(timeout=60)
            return stdout, stderr
        else:
            # Run in the shell the AI was asked to target (bash/zsh), not /bin/sh
            shell = shutil.which(PLATFORM["shell"])
            if is_interactive(cmd):
                # Let the program use the terminal directly; capturing its output would hang it
                subprocess.run(cmd, shell=True, executable=shell, env=command_env())
                return "", ""
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, errors="replace",
                executable=shell, env=command_env(),
            )
            return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        process.kill()
        return "", "Command timed out"
    except Exception as e:
        return "", str(e)

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="OpenSH - Talk to your terminal in plain English",
        epilog="Example: opsh -c 'show me large files'"
    )
    parser.add_argument(
        '-c', '--command',
        nargs='*',
        help='Run a single natural language query and exit'
    )
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'OpenSH v{__version__}'
    )
    args = parser.parse_args()
    
    # Don't crash on consoles/pipes that can't encode emoji (e.g. cp1252 on Windows)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    
    # Signal handling differs on Windows
    if platform.system() != "Windows":
        signal.signal(signal.SIGINT, exit_handler)
    
    load_env()
    
    # Check if first run (no provider configured and no API key in the environment)
    if not get_provider():
        # First run - show welcome and auth setup
        print("\n\033[1m🚀 Welcome to OpenSH!\033[0m")
        print("Talk to your terminal in plain English.\n")
        
        try:
            auth_result = setup_authentication()
        except (EOFError, KeyboardInterrupt, InterruptedError):
            print()
            auth_result = None
        if not auth_result:
            print("\033[31mAuthentication required to use OpenSH.\033[0m")
            print("Run opsh in an interactive terminal, or set GROQ_API_KEY or GEMINI_API_KEY.")
            sys.exit(1)
    
    # Handle single command mode (-c flag)
    if args.command:
        query = ' '.join(args.command)
        cwd = current_dir()
        try:
            print("\033[90m⏳ thinking...\033[0m", end="\r", flush=True)
            command = get_command(query, cwd)
            print(" " * 20, end="\r")
            print(f"\033[33m→ {command}\033[0m")
            if not confirm_command(command):
                return
            # Auto-execute
            if command.startswith("cd ") and not is_compound(command):
                path = os.path.expanduser(command[3:].strip())
                if PLATFORM["name"] == "Windows":
                    path = path.replace("/", "\\")
                try:
                    os.chdir(path)
                    print(f"Changed to: {path}")
                except Exception as e:
                    print(f"cd: {e}")
            else:
                stdout, stderr = run_command(command)
                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr)
        except Exception as e:
            print(f"\033[31mError: {e}\033[0m")
            sys.exit(1)
        return
    
    # Check for updates (silent, non-blocking)
    check_for_updates()
    
    print("\033[1mOpenSH\033[0m ready! Type naturally or use !help\n")
    
    while True:
        try:
            cwd = current_dir()
            # Show full path like default Windows terminal
            prompt = f"\033[32m{cwd}\033[0m > "
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            
            # Exit commands
            if user_input.lower() in ["exit", "quit", "bye", "goodbye"]:
                show_goodbye()
                break
            
            # Handle cd command specially
            if user_input.startswith("cd ") and not is_compound(user_input) and not is_natural_language(user_input):
                path = os.path.expanduser(user_input[3:].strip().strip('"').strip("'"))
                if PLATFORM["name"] == "Windows":
                    path = path.replace("/", "\\")
                try:
                    os.chdir(path)
                except Exception as e:
                    print(f"cd: {e}")
                continue
            elif user_input == "cd":
                os.chdir(Path.home())
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
                confirm = input("\033[33mRemove OpenSH? [y/N]\033[0m ")
                if confirm.lower() == "y":
                    install_dir = Path.home() / ".opsh"
                    if PLATFORM["name"] == "Windows":
                        bin_path = Path.home() / ".opsh" / "opsh.cmd"
                    else:
                        bin_path = Path.home() / ".local" / "bin" / "opsh"
                    if install_dir.exists():
                        shutil.rmtree(install_dir)
                    if getattr(sys, "frozen", False) and script_dir.exists():
                        shutil.rmtree(script_dir)  # settings of a standalone binary
                    if bin_path.exists():
                        os.remove(bin_path)
                    print("\033[32m✓ OpenSH uninstalled\033[0m")
                    sys.exit(0)
                continue
            
            if user_input == "!help":
                show_help()
                continue
            
            if user_input == "!credits":
                show_credits()
                continue
            
            if user_input.startswith("!"):
                cmd = user_input[1:]
                if not cmd:
                    continue
                stdout, stderr = run_command(cmd)
                print(stdout, end="")
                if stderr:
                    print(stderr, end="")
                add_to_history(cmd, stdout + stderr)
                continue
            
            if not is_natural_language(user_input):
                stdout, stderr = run_command(user_input)
                print(stdout, end="")
                if stderr:
                    print(stderr, end="")
                add_to_history(user_input, stdout + stderr)
                continue
            # Show thinking indicator
            print("\033[90m⏳ thinking...\033[0m", end="\r", flush=True)
            command = get_command(user_input, cwd)
            print(" " * 20, end="\r")  # Clear the thinking message
            print(f"\033[33m→ {command}\033[0m")
            if not confirm_command(command):
                continue
            
            # Auto-execute the command
            # Handle directory change commands specially (they need to be run in Python, not subprocess)
            cd_path = None
            if is_compound(command):
                pass  # e.g. "cd src && ls": run it in the shell
            elif command.lower().startswith("cd "):
                cd_path = command[3:].strip()
            elif command.lower().startswith("set-location "):
                cd_path = command[13:].strip()
            elif command.lower().startswith("chdir "):
                cd_path = command[6:].strip()
            
            if cd_path:
                # Remove quotes if present
                cd_path = cd_path.strip('"').strip("'")
                path = os.path.expanduser(cd_path)
                # Expand environment variables like $HOME or $env:USERPROFILE
                if PLATFORM["name"] != "Windows":
                    path = os.path.expandvars(path)
                else:
                    path = path.replace("/", "\\")
                    path = os.path.expandvars(path.replace("$env:", "%").replace("%USERPROFILE", "%USERPROFILE%"))
                try:
                    os.chdir(path)
                except Exception as e:
                    print(f"cd: {e}")
            else:
                stdout, stderr = run_command(command)
                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr)
                add_to_history(command, stdout + stderr)
            
        except (EOFError, KeyboardInterrupt):
            show_goodbye()
            break
        except InterruptedError:
            continue
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                print("\033[31mRate limit hit - waiting 5 seconds...\033[0m")
                try:
                    time.sleep(5)
                except (InterruptedError, KeyboardInterrupt):
                    pass
            elif any(s in err.lower() for s in ("api_key", "api key", "authentication", "error 401", "error 403")):
                print("\033[31mAuth error - run !auth to update your credentials\033[0m")
            elif "InterruptedError" not in err and "KeyboardInterrupt" not in err:
                print(f"\033[31mError: {err[:100]}\033[0m")

if __name__ == "__main__":
    main()
