# 🚀 OpenSH

<div align="center">

![OpenSH Banner](https://capsule-render.vercel.app/api?type=waving&color=0:000000,100:eab308&height=280&section=header&text=OpenSH&fontSize=80&animation=fadeIn&fontAlignY=35&desc=Your%20Terminal,%20Caffeinated.&descSize=25&descAlignY=55&fontColor=ffffff&stroke=eab308&strokeWidth=2)

[![Website](https://img.shields.io/badge/🌐_Website-opensh.vercel.app-eab308?style=for-the-badge&logo=vercel&logoColor=black&labelColor=white)](https://opensh.vercel.app)
[![Version](https://img.shields.io/github/v/release/ai-dev-2024/OpenSH?style=for-the-badge&color=eab308&labelColor=black)](https://github.com/ai-dev-2024/OpenSH/releases)
[![License](https://img.shields.io/github/license/ai-dev-2024/OpenSH?style=for-the-badge&color=white&labelColor=black)](LICENSE)
[![ZAI Community](https://img.shields.io/badge/Part%20of-ZAI%20Start--up%20Community-8b5cf6?style=for-the-badge)](https://startup.z.ai/)
[![Ko-fi](https://img.shields.io/badge/☕_Support_on_Ko--fi-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white&labelColor=black)](https://ko-fi.com/ai_dev_2024)

**[Installation](#-installation)** • **[Features](#-features)** • **[Configuration](#-configuration)** • **[Development](#-development)**

<br>
<br>

</div>

## 🔮 Wake Up Your Terminal

**OpenSH** is the caffeine hit your command line needs. It transforms your terminal into a natural language interface that understands you.

> "Find all large video files over 1GB in my downloads folder"  
> "Convert this video to mp4 and lower the bitrate"  
> "Commit everything with the message 'update styles' and push"

OpenSH translates your intent into the correct command for your OS (Windows, macOS, or Linux), shows it to you, and executes it.

## ✨ Features

| Feature | Description |
| :--- | :--- |
| 🗣️ **Conversational** | Speaks your language. No more `tar -xvf`. |
| ⚡ **Auto-Run** | Generates, shows, and runs commands instantly. |
| 🧠 **Smart Context** | Sees your current project structure for accurate suggestions. |
| 🔁 **Cross-Platform** | Native PowerShell for Windows, Bash/Zsh for Unix. |
| 🛡️ **Safety First** | AI-generated commands that delete or change data (`rm`, `git reset --hard`, `Remove-Item`, `curl ... \| sh`, ...) ask for confirmation first. |
| 🚀 **Zero Config** | Python standard library only, plus a free Groq or Gemini API key. No forced subscriptions. |

## 📦 Installation

Requirements: Python 3.9+ and `git`. On Debian/Ubuntu you also need `python3-venv` (`sudo apt install python3-venv`).

### Windows (PowerShell)
Paste this into your terminal (not verified on Linux CI; the script is parse-checked only):
```powershell
irm https://raw.githubusercontent.com/ai-dev-2024/OpenSH/main/install.ps1 | iex
```

### macOS / Linux
One-line install:
```bash
curl -fsSL https://raw.githubusercontent.com/ai-dev-2024/OpenSH/main/install.sh | bash
```

The installer puts OpenSH in `~/.opsh` (with its own virtualenv), creates the `opsh` command in `~/.local/bin`, and adds `~/.local/bin` to your `PATH` in your existing shell rc files. Running it again updates the install (`git pull` for the one-line install; for a checkout install, run `./install.sh` from the checkout again). To remove OpenSH, run `~/.opsh/uninstall.sh` (or `!uninstall` inside OpenSH).

### From a local checkout
```bash
git clone https://github.com/ai-dev-2024/OpenSH.git
cd OpenSH
./install.sh          # installs this checkout into ~/.opsh
# or run it without installing:
python3 opsh.py
```

## 🎮 Usage

Type `opsh` to start (on Windows the installer can also start it with every new terminal). On first run it asks you to pick Groq or Gemini and paste a free API key.

```text
/home/me/projects/app > create a new react app called dashboard
→ npx create-react-app dashboard
```

Input that already looks like a command (`ls`, `git status`, `npm install`, `./script.sh`, ...) runs directly without asking the AI. Prefix anything with `!` to force it to run as-is, e.g. `!make build`.

Built-in commands: `!help`, `!auth` (change provider/key), `!version`, `!credits`, `!uninstall`, and `exit`.

For a single query without the interactive prompt:
```bash
opsh -c "show my ip address"
```

> **Privacy:** each query sends your request, the file names in the current directory and on your Desktop, and your last few commands with the first lines of their output to the provider you chose (Groq or Gemini). API keys from `.env` are not passed on to the commands OpenSH runs.

## ⚙️ Configuration

Run `!auth` inside OpenSH to switch provider or replace your key. Settings live next to `opsh.py` (`~/.opsh/` for an installed copy):

- `config.json` holds the provider and, optionally, the model to use:

  ```json
  {
    "provider": "groq",
    "groq_model": "openai/gpt-oss-120b",
    "gemini_model": "gemini-3.6-flash"
  }
  ```

- `.env` holds the API key (`GROQ_API_KEY=...` or `GEMINI_API_KEY=...`) and is created readable only by you.

You can also export `GROQ_API_KEY` or `GEMINI_API_KEY` in your environment instead. If either is set, OpenSH skips the first-run setup.

Standalone binaries from the Releases page keep these files in `~/.config/opsh/` instead.

## 🛠️ Development

OpenSH is a single Python file (`opsh.py`) with no runtime dependencies beyond the standard library (`pyreadline3` on Windows only). The tests mock all Groq/Gemini calls, so they need no API key or network.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # CLI, installer paths and landing-page checks
python3 opsh.py --version           # quick smoke check
```

On Windows use `.venv\Scripts\python -m pytest` (run by CI, not verified locally on Linux).

Other checks that CI runs:

```bash
shellcheck -S warning install.sh uninstall.sh
pwsh -NoProfile -Command '$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("install.ps1",[ref]$null,[ref]$e); $e'
```

The landing page at [opensh.vercel.app](https://opensh.vercel.app) is the static file `docs/index.html` (no build step). Vercel serves it through the root `vercel.json`; open the file in a browser to preview it.

Release binaries are built by `.github/workflows/release.yml` with PyInstaller when a `v*` tag is pushed. To build one locally:

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --onefile --name opsh opsh.py   # output: dist/opsh
```

## 🤝 Contributing

We welcome contributions! Please check out the issues or submit a PR.

1. Fork the repo
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<div align="center">
  <p>Made with ☕ by the AI Dev Team • © 2026</p>
</div>
