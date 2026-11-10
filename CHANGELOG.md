# Changelog

All notable changes to OpenSH will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Command aliases
- Live output for long-running commands

---

## [0.4.0] - 2026-11-10

### Security
- **Safety guard rebuilt.** Commands are now normalised before matching (quotes, backslashes, backticks, `$IFS`, line continuations, Unicode dashes and smart quotes), rules match flags in any position, and anything the guard cannot see through is flagged: `eval`, a download piped into any shell or interpreter, `bash <(curl ...)`, `iex`, encoded PowerShell, a variable used as the command, interpreter one-liners that delete. This closes 263 tested ways around the 0.3.0 patterns (`rm dir -rf`, `r\m -rf /`, `ls | xargs rm -rf`, `wget ... | sh`, `irm ... | iex`, `git reset HEAD~3 --hard`, `rd /q /s`, `Format-Volume`, ...) and adds families that had no rule: `find -delete`, `shred`, disk tools, recursive `chmod`/`chown` anywhere, `kubectl delete`, `terraform destroy`, `docker ... prune` and more. Each one has a test in `tests/test_guard_bypasses.py`.
- The confirmation prompt says why a command was flagged, and control characters in a generated command are shown escaped so they cannot hide what will run.
- `.env` (the API key) and `config.json` are written with mode 0600.
- The Gemini key is sent in a header instead of the URL.
- API keys and `KEY=value` credentials in command output are redacted before that output is sent to the model as context.
- The API key prompt no longer echoes the key.
- `install.sh` no longer installs an `opsh.py` (or copies a `.env`) that happens to sit in the current directory when run as `curl ... | bash`, and no longer creates `~/.bash_profile`, which stopped bash from reading `~/.profile`.
- `install.ps1`: auto-start is now opt-in and only fires in an interactive console.

### Fixed
- **Both built-in models had been retired by their providers**, so every request failed. Defaults are now `openai/gpt-oss-120b` (Groq) and `gemini-3.6-flash` (Gemini), and a "model retired" reply says how to choose another.
- **Standalone binaries forgot the API key on every launch**: config was stored in PyInstaller's temporary folder. Binaries now use `~/.opsh`.
- Commands run in bash (Linux) or zsh (macOS), the shell the model is asked to write for, instead of `/bin/sh`.
- A markdown-fenced or backticked model reply is reduced to the command instead of being run as-is (which could leave a hidden nested shell waiting on the terminal). An empty reply is an error.
- `cd build && make` and other compound commands starting with `cd` run in the shell instead of failing as a path. Typed `cd "My Dir"`, `CD ..`, `cd..`, `cd -`, `Set-Location X` and `$env:VAR` paths now work.
- Sentences that start with a command word ("open the resume folder", "make a new folder called test", "copy all pdf files to the backup folder") go to the model instead of being run as commands.
- `opsh -c` exits with the command's status, 1 on an OpenSH error or a declined command, and 130 on Ctrl+C. It used to exit 0 always.
- First run without a terminal prints one line instead of a traceback, and an exported `GROQ_API_KEY` or `GEMINI_API_KEY` is enough to run without setup.
- An empty or corrupt `config.json` no longer crashes startup.
- `.env` values no longer override variables that are already exported; quotes, `export` and spaces are handled.
- Provider errors: unexpected reply shapes, HTML error pages and safety blocks give a plain message; server errors and timeouts are retried; errors are classified by status instead of by substring (any error containing "rate" was reported as a rate limit); the provider's own message is shown instead of half a JSON blob.
- Windows: line editing and history now actually load (`import pyreadline3 as readline` never activated them).
- Redirecting output on Windows no longer crashes with `UnicodeEncodeError`, and colour codes are left out of pipes and files (and whenever `NO_COLOR` is set).
- Command output that is not valid UTF-8 is shown instead of being replaced by a codec error.
- `vim`, `nano`, `top`, `htop`, `less`, `more`, `man`, `ssh`, `watch`, `tmux` and `screen` get the real terminal instead of appearing to hang.
- A timed-out command is stopped together with its child processes.
- The shell no longer loops on an error when its current folder is deleted.
- `!uninstall` explains what it could not remove instead of failing with a raw error.
- `install.ps1` works when piped into `iex` (it aborted on a null script path), no longer installs the unused `google-genai` package, no longer closes the window on failure, and writes a launcher that works for user names outside ASCII. `uninstall.ps1` is ASCII-only so Windows PowerShell 5.1 can parse it.
- `install.sh` updates an existing install that is not a git checkout, checks for Python 3.9+ and git, and no longer builds a virtualenv for a program with no dependencies.
- CI: the Python 3.9 job runs on Ubuntu 24.04, because `setup-python` has no 3.9 build for the newest Ubuntu image.

### Added
- Model selection: `OPSH_MODEL` or `"model"` in `config.json`.
- `OPSH_HOME` (config folder), `OPSH_TIMEOUT` (command time limit), `OPSH_NO_UPDATE_CHECK`, `NO_COLOR`.
- The update check runs at most once a day.
- CI gates: ruff lint, mypy (Linux and Windows code paths), tests on Ubuntu, Windows and macOS with Python 3.9 to 3.13, and a gitleaks scan of the full history.
- Release workflow: least-privilege token, the tag must match `__version__`, tests run before building, PyInstaller is pinned, and a `SHA256SUMS` file is published.
- `tests/test_core.py`: unit tests for the classifier, history, config/.env, prompt building, provider parsing and 429 retry (mocked), `run_command`, `!help` and a `--help`/`--version` smoke test.
- `tests/test_regressions.py` (one test per fix above), `tests/test_guard_bypasses.py`, `tests/test_repo_hygiene.py`.
- New README banner (`docs/banner.svg`) and a demo image (`docs/demo.svg`).

### Changed
- `requirements.txt` no longer lists the unused `google-genai` and `google-auth-oauthlib` packages; OpenSH only uses the standard library.
- Update check only reports a release that is actually newer; provider requests send the current version in `User-Agent`; `!help` shows the correct exit key per platform; bare `except:` clauses narrowed.
- `CREDITS.md` filled in.

---

## [0.3.0] - 2026-10-05

### Added
- **Safety guard**: AI-generated commands that delete data, wipe disks, rewrite git history, pipe downloads into a shell or shut the machine down now need an explicit `y` before they run (interactive and `-c` mode).
- `-y/--yes` flag to skip the prompt for scripted use.
- Unit tests (`tests/test_safety.py`), run in CI on Windows, macOS and Linux.
- Local SVG banner and logo; full README with usage, safety, configuration, architecture, development and troubleshooting.

### Changed
- Repository links, installer URLs and the update check now point at `muhib-karim/OpenSH`.

---

## [0.2.0] - 2026-01-31

### Added
- **Groq API support** - Faster free alternative to Gemini (30 req/min)
- **Auto-execute mode** - Commands run automatically, no Enter needed
- **Thinking indicator** - Shows `⏳ thinking...` while AI processes
- **Full path prompt** - Shows complete directory path like default terminal
- **File context** - AI sees your files for more accurate commands
- **Cross-platform release workflow** - GitHub Actions for Windows/Linux/macOS

### Fixed
- `Set-Location` and `chdir` commands now properly change directory
- Output display issues on Windows
- Rate limit handling with auto-retry

### Changed
- Switched from confirmation prompt to auto-execute
- Improved natural language understanding with larger model
- Simplified CI tests to avoid Windows encoding issues

---

## [0.1.1] - 2026-01-30

### Added
- **Quick query mode** (`-c` flag) - Execute single commands from any terminal
- **`ask` function** in PowerShell - Quick natural language queries
- **Auto-launch message** - OpenSH ready notification on new terminals
- **Browser auto-open** - Opens Google AI Studio during setup

### Fixed
- Removed Google OAuth (was blocked by Google's unverified app policy)
- Simplified to API key only - more reliable

---

## [0.1.0] - 2026-01-30

### Added
- Interactive authentication menu on first launch
- `!auth` command to change API key anytime
- JSON-based config storage for auth preferences

---

## [0.0.1] - 2026-01-30

### Added
- **Multi-platform support** - Works on Windows, macOS, and Linux
- **AI-powered command translation** using Google Gemini API
- **Smart command detection** - Shell commands bypass AI for direct execution
- **Command history context** - AI uses recent commands for better suggestions
- **GitHub Actions CI** - Automated testing on Windows, macOS, Linux

### Credits
- Based on [nlsh](https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 0.4.0 | 2026-11-10 | Current models, hardened safety guard, binary config fix, CI gates |
| 0.3.0 | 2026-10-05 | Safety guard for destructive commands |
| 0.2.0 | 2026-01-31 | Groq support, auto-execute, cross-platform releases |
| 0.1.1 | 2026-01-30 | Quick query mode, simplified auth |
| 0.1.0 | 2026-01-30 | Auth menu, config storage |
| 0.0.1 | 2026-01-30 | Initial multi-platform release |

---

[Unreleased]: https://github.com/muhib-karim/OpenSH/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/muhib-karim/OpenSH/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.3.0
[0.2.0]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.2.0
[0.1.1]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.1.1
[0.1.0]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.1.0
[0.0.1]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.0.1
