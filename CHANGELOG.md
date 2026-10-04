# Changelog

All notable changes to OpenSH will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Customizable AI model selection
- Command aliases

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
| 0.2.0 | 2026-01-31 | Groq support, auto-execute, cross-platform releases |
| 0.1.1 | 2026-01-30 | Quick query mode, simplified auth |
| 0.1.0 | 2026-01-30 | Auth menu, config storage |
| 0.0.1 | 2026-01-30 | Initial multi-platform release |

---

[Unreleased]: https://github.com/muhib-karim/OpenSH/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.3.0
[0.2.0]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.2.0
[0.1.1]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.1.1
[0.1.0]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.1.0
[0.0.1]: https://github.com/muhib-karim/OpenSH/releases/tag/v0.0.1
