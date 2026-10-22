# Agent notes for OpenSH

- Read `docs/PROJECT_BRAIN.md` first; update its Status / Next step / Session log as you work.
- `opsh.py` is the whole program: one file, Python standard library only. Keep it that way.
- Tests: `python -m unittest discover -s tests -q` (stdlib only, no network, no API key).
- Lint/type/coverage gates (CI): `ruff check .`, `ruff format --check .`, `mypy opsh.py`,
  `coverage run -m unittest discover -s tests && coverage report` (fail-under 85).
- Any change to the safety guard needs a row in `tests/test_safety.py` (destructive and benign).
- Use the offline provider for manual checks: `OPENSH_PROVIDER=mock python opsh.py -n -c "list files"`.
