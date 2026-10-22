# Skills used

Which agent skill drove which change, per release. Skills named in the brief but not used are listed
with the reason, so nothing reads as used when it was not.

## v0.4.0

| Skill | What it drove |
| :--- | :--- |
| `brainstorming` | Scoping the release. The interview was skipped (the brief said to proceed without questions), so every decision is recorded as the builder's call in `docs/superpowers/specs/2026-10-22-v040-design.md`: keep `opsh.py` single-file and stdlib-only, don't change the `config.json`/`.env` format, minimum Python 3.10, real environment beats `.env`. |
| `test-driven-development` | The guard. `tests/test_safety.py` (135 destructive/benign pairs across bash, zsh, PowerShell and cmd) was written first and failed (63 failures, 138 errors) before `GUARD_RULES`/`explain_risk` existed. The same red-then-green loop drove the `$env:` cd fix, the stdout-encoding fix and the explain-mode duplicate-reason fix. |
| `ui-ux-pro-max` | Landing-page direction (`docs/index.html`): dark OLED style for a developer tool, contrast ≥ 4.5:1, visible focus, keyboard-operable tabs, reduced-motion support, SVG icons instead of emoji. |
| `impeccable` | Landing-page build and checks: craft-floor rules (no eyebrow labels or card grid, themed selection/scrollbar/focus, one authored motion), the design detector (fixed skip-link hover contrast, replaced the overused Geist face with IBM Plex Sans/Mono), and renders checked at 1366 px and 390 px. Its PRODUCT.md interview was skipped per the brief. |
| `archify` | Code-backed request-flow diagram (`docs/architecture/opsh-flow.archify.json`): every node cites an `opsh.py` line range at a pinned revision. Passed validate, deliver and strict check; the browser check timed out on the memory-constrained build machine, so the HTML render is not committed yet (see TASKS.md). The README mermaid diagram follows the same structure. |
| `requesting-code-review` | Independent review of the whole branch by a fresh reviewer. It found a critical guard regression (commands behind `sudo -u`, `VAR=`, `bash -c`, `ssh`, `cmd /c`, `docker exec` slipped through), three important bugs (`-c` exit code, `OPENSH_SHELL` in `.env`, Ctrl+C retried) and seven minor ones; all were fixed test-first (20 new guard pairs, 155 total). Details in HANDOFF.md. |
| `verification-before-completion` | Final gate before the done report: full suite, ruff, mypy, coverage, gitleaks via the push script, and CI on the branch head, with the outputs quoted. |

Supporting tools that were not skills: headless Chromium screenshots for the landing page, banner and demo image; ruff, mypy and coverage in a scratch virtualenv.

### Named in the brief, not used

| Skill | Why not |
| :--- | :--- |
| `writing-plans` | The plan is the design spec plus the checklist in TASKS.md; a separate plan document would have duplicated them for a single-file change. |
| `systematic-debugging` | Not loaded. Its method (reproduce, isolate, root cause, then fix) was followed by hand for the hanging test: reproduced with an open stdin, isolated to one test, root cause was `input` bound as a default argument. |
| `understand` / `graphify` | The code is one ~1,360-line file; archify plus the mermaid diagram covered the architecture section. |
| `playwright-skill` | Playwright is not installed on the build machine; headless Chromium screenshots were used instead. |
| `caveman`, `ponytail` and the Android/Compose skills | Not relevant to this repository. |
