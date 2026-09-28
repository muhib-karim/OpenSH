# Changelog

All notable changes to OpenSH will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Confirmation prompt before running AI-generated commands that delete or change data, or that pipe downloads into a shell
- `groq_model` / `gemini_model` settings in `config.json`
- `GROQ_API_KEY` / `GEMINI_API_KEY` environment variables skip the first-run setup
- Test suite (`python -m pytest`) with mocked Groq/Gemini calls; CI runs it on Linux, Windows and macOS

### Changed
- Default models are now `openai/gpt-oss-120b` (Groq) and `gemini-3.6-flash` (Gemini); the previous defaults were retired by the providers
- Gemini API key is sent in the `x-goog-api-key` header instead of the URL
- `.env` is created readable only by the current user, and API keys from it are no longer passed to the commands OpenSH runs
- `sudo` commands, editors, pagers, bare REPLs and `git commit` without `-m` get the terminal instead of having their output captured
- Standalone binaries keep their settings in `~/.config/opsh/`

### Fixed
- Crash on first run when there is no interactive terminal or the console can't print emoji
- Update check compared versions as strings
- Markdown code fences in AI replies were run as part of the command
- Editors, pagers and other interactive commands (`vim`, `less`, `ssh`, ...) now get the terminal
- Commands on Linux/macOS now run in bash/zsh as intended instead of `/bin/sh`
- `install.sh` reinstall from a checkout did not update the installed copy, and it created shell rc files that did not exist
- `install.ps1` failed under `irm | iex` and did not stop on venv/pip errors
- `uninstall.ps1` could not be parsed by Windows PowerShell 5.1 (non-ASCII character in a BOM-less file)
- Standalone binaries saved settings to a temporary folder that was deleted on exit
- Crash on a malformed `config.json`, and an endless error loop when the current directory was deleted
- Command output that is not valid UTF-8 was replaced by a decode error
- AI replies with prose around a code block, and `cd dir && cmd` replies, now run correctly
- Requests such as "make a folder called test" or "open the readme" were run as shell commands instead of going to the AI
- Ctrl+C during the rate-limit wait crashed with a traceback; `!help` now describes Ctrl+C correctly
- Quoted values in `.env` kept their quotes; Gemini auth errors now show the provider's message and the `!auth` hint
- Re-running `install.sh`/`install.ps1` from a checkout replaced the installed `.env`; `install.sh` skipped the PATH setup when `.local/bin` appeared in a comment
- `uninstall.sh` replaced symlinked shell rc files with copies and left the PATH lines it had added
- The Windows `opsh` launcher broke when the user profile path had non-ASCII characters; the PowerShell auto-start line now only runs in interactive console sessions
- The website's Copy button could stay stuck on "Copied!" and failed silently without clipboard access

### Planned
- Command aliases

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
| 0.2.0 | 2026-01-31 | Groq support, auto-execute, cross-platform releases |
| 0.1.1 | 2026-01-30 | Quick query mode, simplified auth |
| 0.1.0 | 2026-01-30 | Auth menu, config storage |
| 0.0.1 | 2026-01-30 | Initial multi-platform release |

---

[Unreleased]: https://github.com/ai-dev-2024/OpenSH/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ai-dev-2024/OpenSH/releases/tag/v0.2.0
[0.1.1]: https://github.com/ai-dev-2024/OpenSH/releases/tag/v0.1.1
[0.1.0]: https://github.com/ai-dev-2024/OpenSH/releases/tag/v0.1.0
[0.0.1]: https://github.com/ai-dev-2024/OpenSH/releases/tag/v0.0.1
