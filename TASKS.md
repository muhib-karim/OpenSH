# TASKS: OpenSH v0.4.0

Checklist for the v0.4.0 upgrade (branch `upgrade/v0.4.0`). Ticked items are done and verified.

- [x] Safety guard: rule table + reasons, 155 table-driven pairs (bash/zsh/PowerShell/cmd), explain-before-run
- [x] Provider layer: Groq, Gemini, OpenAI-compatible, Ollama, mock; timeout/retry; key redaction
- [x] UX: shell auto-detect, history file, --dry-run, --explain, --copy, --help examples, man page
- [x] Tests on stdlib unittest, coverage >= 85% (99%)
- [x] CI: ruff, mypy, coverage matrix, gitleaks, CodeQL, Dependabot; release workflow on tag
- [x] README + landing page refresh, CHANGELOG [0.4.0], version bump, SKILLS_USED.md, HANDOFF.md
- [x] Independent code review; critical/important/minor findings fixed (see HANDOFF.md)
- [ ] Pushed via push script, CI green on branch head (final push of this branch)

## Blocked / notes
- **Archify HTML render**: `docs/architecture/opsh-flow.archify.json` passes archify validate, deliver and strict
  check, but its browser check (and a plain headless-Chromium screenshot) could not run on the build machine
  because of memory pressure. The HTML is not committed until someone has looked at it. Render with
  `archify finalize workflow docs/architecture/opsh-flow.archify.json <out>.html --quality showcase`.
  Its source line citations are pinned to revision 311e3d9.
- Not flagged by the guard (outside its categories): package removals, `systemctl stop`, `iptables -F`,
  `userdel -r`, `rsync --delete`.
