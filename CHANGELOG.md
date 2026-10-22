# Changelog

All notable changes to OpenSH will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Command aliases
- Per-folder context hints

---

## [0.4.0] - 2026-10-22

### Added
- **Safety guard rebuilt as a rule table**: 61 rules, each with a plain-English reason that is shown in the prompt (`⚠ Deletes files recursively or without asking. Run it? [y/N]`). Rules match at command position (start of line, after `;` `&&` `||` `|`, inside `$(…)`, behind `sudo`/`xargs`/`find -exec`/`nohup`…), so `cat shutdown.log` no longer counts as a shutdown. New coverage: `find -delete`, `shred`, `wipefs`, partition tools, `diskutil erase*`, `Format-Volume`/`Clear-Disk`, `cipher /w`, `vssadmin delete shadows`, `bcdedit`, recursive `chmod`/`chown` on system folders, `icacls … Everyone`, `takeown /r`, named and PowerShell/batch fork bombs, `pkill -9`, `taskkill /f`, `systemctl poweroff`, `init 0`, `git push origin +branch`, `git branch -D`, `git filter-branch`, `git checkout -- .`, `wget | sh`, `curl | python`, `bash <(curl …)`, `sh -c "$(curl …)"`, `irm | iex`, `iex (…).DownloadString`, writes to `/etc`, `crontab -r`, `reg delete`, `Set-ExecutionPolicy Unrestricted`, Defender switches, `FLUSHALL`, `docker … prune`, `kubectl delete`, `terraform destroy`.
- **Explain-before-run**: `-e/--explain` and the `!explain` toggle show a short model explanation of each command, then ask before running it.
- **`-n/--dry-run`** and the `!dry-run` toggle: show commands, never run them.
- **`--copy`** and `!copy`: copy the generated command with `clip`, `pbcopy`, `wl-copy`, `xclip` or `xsel`.
- **Pluggable providers**: Groq, Gemini, any OpenAI-compatible endpoint (`base_url`, `model`, `api_key_env` in `config.json`), local Ollama (`OLLAMA_HOST`), and an offline `mock` provider (`OPENSH_MOCK_RESPONSE`). `!auth` sets up all of them. `--provider`/`--model` and `OPENSH_PROVIDER`/`OPENSH_MODEL`/`OPENSH_BASE_URL`/`OPENSH_TIMEOUT` override per run.
- Shared HTTP layer with a configurable timeout, retries with exponential backoff on HTTP 429/5xx and network errors, and `Retry-After` support.
- **Shell auto-detection** from `OPENSH_SHELL` or `$SHELL` (bash, zsh, PowerShell/pwsh), with `--shell` to override. Commands now run in the detected shell instead of `/bin/sh`.
- **History file** (`~/.opsh/history`, 1000 lines) loaded into arrow-key history on start; `!history` shows it; lines that look like keys or passwords are never saved; `--no-history` or `"history": false` turns it off.
- `--help` examples, `docs/opsh.1` man page.
- CI: ruff, mypy, unittest under coverage with an 85% gate on Ubuntu/macOS/Windows × Python 3.10/3.12/3.13, gitleaks, CodeQL and Dependabot.
- Release workflow runs the tests first, smoke-tests each PyInstaller binary with the offline provider, ships the man page and `SHA256SUMS.txt`, and builds (without publishing) on `upgrade/**` branches.
- Test suite: 118 stdlib `unittest` tests (99% line coverage), including 135 table-driven destructive/benign guard pairs across bash, zsh, PowerShell and cmd, and end-to-end runs of the real script.
- Landing page redesign, new README with guard table, provider configuration and architecture diagram, refreshed demo image.

### Changed
- **Gemini key moved from the request URL to the `x-goog-api-key` header**, so it can no longer end up in URLs or proxy logs.
- API keys are scrubbed from every error message; `!auth` reads keys with hidden input; `.env` is written with mode 600 on macOS/Linux.
- Variables already set in the environment now take precedence over `.env`.
- Default Gemini model is now `gemini-2.5-flash`; every model is configurable.
- Plain `cd` commands are handled in-process, but chained ones (`cd build && make`) now run in the shell instead of being mangled.
- Markdown fences, backticks and `$ ` prompts are stripped from model output.
- Minimum Python is 3.10 (3.9 is end-of-life).
- Tests moved from pytest to the standard library's `unittest`.

### Fixed
- Output no longer crashes with `UnicodeEncodeError` when piped or on a legacy (cp1252) Windows console.
- An unreadable or non-object `config.json` is treated as empty instead of crashing.
- Update check only reports a release that is actually newer; provider requests send the current version in `User-Agent`; `!help` shows the right exit key per OS; bare `except:` clauses narrowed (all since 0.3.0).

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
| 0.4.0 | 2026-10-22 | Rule-table safety guard, pluggable providers, explain/dry-run/copy, CI gates |
| 0.3.0 | 2026-10-05 | Safety guard for destructive commands, tests, docs |
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
