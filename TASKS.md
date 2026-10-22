# TASKS: OpenSH v0.4.0

Checklist for the v0.4.0 upgrade (branch `upgrade/v0.4.0`). Ticked items are done and verified.

- [ ] Safety guard: rule table + reasons, 100+ table-driven pairs (bash/zsh/PowerShell/cmd), explain-before-run
- [ ] Provider layer: Groq, Gemini, OpenAI-compatible, Ollama, mock; timeout/retry; key redaction
- [ ] UX: shell auto-detect, history file, --dry-run, --explain, --copy, --help examples, man page
- [ ] Tests on stdlib unittest, coverage >= 85%
- [ ] CI: ruff, mypy, coverage matrix, gitleaks, CodeQL, Dependabot; release workflow on tag
- [ ] README + landing page refresh, CHANGELOG [0.4.0], version bump, SKILLS_USED.md, HANDOFF.md
- [ ] Pushed via push script, CI green on branch head

## Blocked / notes
(none yet)
