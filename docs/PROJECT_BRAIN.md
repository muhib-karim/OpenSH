# OpenSH project brain

Handoff note for whoever (human or agent) picks this repo up next. Keep it short.

## What this is
OpenSH (`opsh`): natural-language shell. Plain English -> one PowerShell/Bash/Zsh command via an LLM
provider, regex safety guard before anything destructive runs. Single file `opsh.py`, stdlib only
(the installers copy only that file, so keep it single-file).

## Invariants
- `opsh.py` stays one file, standard library only. Tests are stdlib `unittest`.
- Settings live next to the program: `config.json` (provider/model/endpoint) and `.env` (keys). Do not change
  their format or location without asking the owner.
- API keys come only from the environment or `.env`; never print or log them (`redact()`).
- Never push to main; push only through the owner's gated push script. No local heavy builds.

## Status
v0.4.0 complete on branch `upgrade/v0.4.0`: guard (63 rules, 155 test pairs), providers, UX, 130 unittest
tests at 99% coverage, CI/CodeQL/release, docs. Code review findings fixed. Not merged or tagged.

## Next step
Coordinator: open PR, merge, tag v0.4.0. Optional: render the archify diagram (TASKS.md).

## Session log
2026-10-22 07:20Z Claude Code/claude-opus-5-5: v0.4.0 guard/providers/UX/tests/CI/docs, review fixes; next: PR + tag by coordinator.
