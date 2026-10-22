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
v0.4.0 work on branch `upgrade/v0.4.0` (see TASKS.md for the checklist).

## Next step
See TASKS.md.

## Session log
