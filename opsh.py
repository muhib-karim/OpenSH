#!/usr/bin/env python3
"""
OpenSH - Open Natural Language Shell
Talk to your terminal in plain English.

Based on nlsh (https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood

Support: https://ko-fi.com/ai_dev_2024
"""

__version__ = "0.3.0"

import signal
import os
import sys
import subprocess
import platform
import json
import webbrowser
import argparse
import time
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
        url = "https://api.github.com/repos/muhib-karim/OpenSH/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenSH"})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != __version__:
                print(f"\033[33m📦 New version available: v{latest} (you have v{__version__})\033[0m")
                print(f"\033[90m   Update: https://github.com/muhib-karim/OpenSH/releases/tag/v{latest}\033[0m\n")
    except:
        pass  # Silently fail - don't block startup

def exit_handler(sig, frame):
    print()
    raise InterruptedError()

# Signal handling differs on Windows
if platform.system() != "Windows":
    signal.signal(signal.SIGINT, exit_handler)

script_dir = Path(__file__).parent.absolute()
env_path = script_dir / ".env"
config_path = script_dir / "config.json"

def load_config():
    """Load configuration from JSON file."""
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}

def save_config(config: dict):
    """Save configuration to JSON file."""
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

def load_env():
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

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
    
    with open(env_path, "w") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")

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

def call_groq(prompt: str, api_key: str) -> str:
    """Call Groq API directly using urllib (no external dependencies)."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    data = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 500
    }).encode('utf-8')
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "OpenSH/0.2.0"
    }
    
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result["choices"][0]["message"]["content"].strip()
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
                raise Exception(f"API error {e.code}: {error_body[:100]}")
        except urllib.error.URLError as e:
            raise Exception(f"Network error: {e.reason}")

def call_gemini(prompt: str, api_key: str) -> str:
    """Call Gemini API directly using urllib."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    data = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode('utf-8')
    
    headers = {"Content-Type": "application/json", "User-Agent": "OpenSH/0.2.0"}
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result["candidates"][0]["content"]["parts"][0]["text"].strip()
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
                raise Exception(f"API error {e.code}: {error_body[:100]}")
        except urllib.error.URLError as e:
            raise Exception(f"Network error: {e.reason}")

def get_ai_response(prompt: str) -> str:
    """Get AI response using configured provider."""
    config = load_config()
    provider = config.get("provider", "groq")
    
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
    print("\033[36mCtrl+C\033[0m     - Exit OpenSH")
    print()

def show_version():
    config = load_config()
    provider = config.get("provider", "not configured")
    print(f"\n\033[1mOpenSH\033[0m v{__version__}")
    print(f"Platform: {PLATFORM['name']} ({PLATFORM['shell']})")
    print(f"Provider: {provider}")
    print(f"Python: {platform.python_version()}")
    print(f"GitHub: https://github.com/muhib-karim/OpenSH")
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

# Initialize
load_env()

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

    return get_ai_response(prompt)

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
    return not any(text.lower().startswith(s.lower()) for s in shell_starters)


# --- Safety guard -----------------------------------------------------------
# AI-generated commands run automatically, except ones that can destroy data or
# take the machine down. Those are shown and need an explicit "y" first.
import re as _re

_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+",          # rm -r / rm -f / rm -rf
    r"\brm\s+.*--(recursive|force)\b",
    r"\brmdir\s+/s\b", r"\brd\s+/s\b", r"\bdel\s+.*/[sq]\b",
    r"\bremove-item\b.*-(recurse|force)\b",
    r"\bmkfs(\.\w+)?\b", r"\bformat(-volume)?\s+[a-z]:", r"\bdiskpart\b",
    r"\bdd\s+.*\bof=", r">\s*/dev/(sd|nvme|disk|hd)",
    r"\b(shutdown|reboot|halt|poweroff)\b", r"\b(stop|restart)-computer\b",
    r"\bgit\s+push\s+.*(--force|-f)\b", r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\s+-[a-z]*f",
    r"\bchmod\s+(-r\s+)?[0-7]*777\s+/(\s|$)", r"\bchown\s+-r\b.*\s/(\s|$)",
    r":\(\)\s*\{\s*:\|:&\s*\};:",            # fork bomb
    r"\b(drop\s+(table|database))\b", r"\btruncate\s+table\b",
    r"\bkillall\b", r"\bkill\s+-9\s+-1\b", r"\bstop-process\b.*-force",
    r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b", r"\biwr\b[^|]*\|\s*iex\b",
]
_DESTRUCTIVE_RE = [_re.compile(p, _re.IGNORECASE) for p in _DESTRUCTIVE_PATTERNS]


def is_destructive(cmd: str) -> bool:
    """True when a command could delete data, wipe a disk, rewrite history or stop the machine."""
    if not cmd:
        return False
    return any(r.search(cmd) for r in _DESTRUCTIVE_RE)


def confirm_if_destructive(cmd: str, assume_yes: bool = False, ask=input) -> bool:
    """Return True if the command may run. Destructive commands need an explicit yes."""
    if not is_destructive(cmd) or assume_yes:
        return True
    try:
        answer = ask("\033[31m⚠ This command can delete data or stop your machine. Run it? [y/N]\033[0m ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("y", "yes")


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
                errors='replace'
            )
            stdout, stderr = process.communicate(timeout=60)
            return stdout, stderr
        else:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
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
        '-y', '--yes',
        action='store_true',
        help='Run destructive AI-generated commands without asking (use with care)'
    )
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'OpenSH v{__version__}'
    )
    args = parser.parse_args()
    
    # Check if first run (no auth configured)
    config = load_config()
    
    if not config.get("provider"):
        # First run - show welcome and auth setup
        print("\n\033[1m🚀 Welcome to OpenSH!\033[0m")
        print("Talk to your terminal in plain English.\n")
        
        auth_result = setup_authentication()
        if not auth_result:
            print("\033[31mAuthentication required to use OpenSH.\033[0m")
            sys.exit(1)
    
    # Handle single command mode (-c flag)
    if args.command:
        query = ' '.join(args.command)
        cwd = os.getcwd()
        try:
            print("\033[90m⏳ thinking...\033[0m", end="\r", flush=True)
            command = get_command(query, cwd)
            print(" " * 20, end="\r")
            print(f"\033[33m→ {command}\033[0m")
            # Auto-execute
            if command.startswith("cd "):
                path = os.path.expanduser(command[3:].strip())
                if PLATFORM["name"] == "Windows":
                    path = path.replace("/", "\\")
                try:
                    os.chdir(path)
                    print(f"Changed to: {path}")
                except Exception as e:
                    print(f"cd: {e}")
            elif not confirm_if_destructive(command, args.yes):
                print("\033[90mSkipped.\033[0m")
            else:
                stdout, stderr = run_command(command)
                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr)
        except Exception as e:
            print(f"\033[31mError: {e}\033[0m")
        return
    
    # Check for updates (silent, non-blocking)
    check_for_updates()
    
    print("\033[1mOpenSH\033[0m ready! Type naturally or use !help\n")
    
    while True:
        try:
            cwd = os.getcwd()
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
            if user_input.startswith("cd "):
                path = os.path.expanduser(user_input[3:].strip())
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
                    import shutil
                    install_dir = Path.home() / ".opsh"
                    if PLATFORM["name"] == "Windows":
                        bin_path = Path.home() / ".opsh" / "opsh.cmd"
                    else:
                        bin_path = Path.home() / ".local" / "bin" / "opsh"
                    if install_dir.exists():
                        shutil.rmtree(install_dir)
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
            
            # Auto-execute the command
            # Handle directory change commands specially (they need to be run in Python, not subprocess)
            cd_path = None
            if command.lower().startswith("cd "):
                cd_path = command[3:].strip()
            elif command.lower().startswith("set-location "):
                cd_path = command[13:].strip()
            elif command.lower().startswith("chdir "):
                cd_path = command[6:].strip()
            
            if cd_path:
                # Remove quotes if present
                cd_path = cd_path.strip('"').strip("'")
                path = os.path.expanduser(cd_path)
                # Expand environment variables like $env:USERPROFILE
                if PLATFORM["name"] == "Windows":
                    path = path.replace("/", "\\")
                    path = os.path.expandvars(path.replace("$env:", "%").replace("%USERPROFILE", "%USERPROFILE%"))
                try:
                    os.chdir(path)
                except Exception as e:
                    print(f"cd: {e}")
            elif not confirm_if_destructive(command, args.yes):
                print("\033[90mSkipped.\033[0m")
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
                time.sleep(5)
            elif "API_KEY" in err or "api_key" in err or "authentication" in err.lower():
                print("\033[31mAuth error - run !auth to update your credentials\033[0m")
            elif "InterruptedError" not in err and "KeyboardInterrupt" not in err:
                print(f"\033[31mError: {err[:100]}\033[0m")

if __name__ == "__main__":
    main()
