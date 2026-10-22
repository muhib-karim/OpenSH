# HANDOFF: OpenSH v0.4.0

Branch `upgrade/v0.4.0` (from `main` at 87db7f5). Not merged, no PR opened, nothing tagged.

## What changed
- **Safety guard** (`GUARD_RULES`, `explain_risk`): 63 rules with reasons, matched at command position,
  including behind `sudo -u x`, `VAR=value`, `timeout N`, inside `bash -c '…'`, `cmd /c`, `powershell -Command "…"`,
  after `ssh host` and `docker`/`kubectl exec`. 155 destructive/benign pairs in `tests/test_safety.py`.
- **Explain before run** (`-e`, `!explain`), **dry run** (`-n`, `!dry-run`), **clipboard** (`--copy`, `!copy`),
  **shell auto-detect** (`--shell`, `OPENSH_SHELL`, `$SHELL`), **history file** (`!history`, `--no-history`),
  man page `docs/opsh.1`, `--help` examples. `opsh -c` now returns the command's exit code.
- **Providers**: Groq, Gemini, OpenAI-compatible, Ollama, mock; `http_post_json` with timeout, retries,
  backoff and Retry-After; keys only from env/`.env`, redacted from errors, Gemini key in a header.
- **Tests**: stdlib `unittest`, 130 tests, 99% coverage of `opsh.py`.
- **CI**: ruff, mypy, coverage gate 85% on Ubuntu/macOS/Windows × Python 3.10/3.12/3.13, gitleaks, CodeQL,
  Dependabot. Release workflow: tests, PyInstaller binaries, binary smoke test, SHA256SUMS; builds without
  publishing on `upgrade/**` pushes.
- **Docs**: README, CHANGELOG `[0.4.0] - 2026-10-22`, landing page, demo/banner SVGs, SKILLS_USED.md.

## Behaviour changes a reviewer should know about
- Minimum Python is now 3.10 (installers check it).
- Real environment variables win over `.env` values.
- Commands run in the detected shell (`bash`/`zsh`/`pwsh`) instead of `/bin/sh`.
- `opsh -c` exit code: command's code, 1 if skipped, 0 for a dry run (was always 0).
- PyInstaller binaries store settings next to the executable (they previously lost them after each run).
- A corrupt `config.json` stops OpenSH with a message instead of silently re-running setup over it.
- `config.json`/`.env` format and location are unchanged; new `config.json` keys are optional.

## Code review
An independent reviewer read the whole range. Its findings and what was done about them:
- Critical: wrapped commands (`sudo -u`, `VAR=`, `bash -c`, `ssh`, `cmd /c`, `docker exec`) slipped past the
  guard. **Fixed** in 896c97b with 20 new test pairs.
- Important: `OPENSH_SHELL` in `.env` ignored, `-c` always exited 0, Ctrl+C during a request was retried.
  **Fixed** in 534848a.
- Minor: Retry-After clamp, misleading "Invalid JSON" error, history file permissions, over-eager secret
  filter, corrupt config overwritten, `history` not git-ignored, binary settings location. **Fixed** in 534848a.
- Accepted trade-off: `echo "rm -rf build"` is now flagged (a command inside quotes counts as a command).
- Out of scope, unchanged: commands you type yourself bypass the guard (by design); package removals,
  `systemctl stop`, `iptables -F`, `userdel -r`, `rsync --delete` are not flagged.

## How to verify
```bash
python -m unittest discover -s tests
python -m coverage run -m unittest discover -s tests && python -m coverage report
ruff check . && mypy
OPENSH_PROVIDER=mock python opsh.py -e -n -c "clean the build folder"
```

## Next steps for the maintainer
1. Open the PR from `upgrade/v0.4.0`, review, merge.
2. Tag `v0.4.0` on the merge commit; the release workflow builds and publishes the binaries.
3. Redeploy the landing page (`docs/`) on Vercel.
4. Optional: render `docs/architecture/opsh-flow.archify.json` to HTML on a machine with a working
   headless Chrome and link it from the README (see TASKS.md).
