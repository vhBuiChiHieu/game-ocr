---
name: run-targeted-tests
description: Pick and run the correct pytest suite(s) for the area you changed, using the game-ocr area→command routing table. User-invoked only.
disable-model-invocation: true
---

# run-targeted-tests

Map changed files to the right pytest command(s) and run them with `.venv/Scripts/python.exe`. Avoid full-suite runs (slow, GPU). Real OCR sample tests are opt-in, not the default.

## Steps

1. Determine changed files: `git status --short` and `git diff --name-only`. If the user passed paths/area in args, use those instead.
2. Match each changed path to suites via the routing table below. Union the commands; dedupe.
3. Run each command with the project interpreter. On Windows prefer:
   `.venv/Scripts/python.exe -m pytest <suite> -q`
4. If any source under `src/game_ocr/` changed, also run `.venv/Scripts/python.exe -m compileall src tests` as a fast sanity gate.
5. Report pass/fail per suite with the tail of output. Do not claim success unless pytest exited 0.

## Routing table

| Changed area / file | Suite(s) to run |
|---|---|
| `__main__.py`, detached launcher, `logging_config.py` | `tests/test_main.py` |
| `app.py`, startup / GPU gate / cleanup, tray lifecycle | `tests/test_app.py` |
| `capture.py` | `tests/test_capture.py` |
| `ocr_config.py`, root `ocr-config.json` | `tests/test_ocr_config.py` |
| `ocr.py`, `ui/layout_source.py`, `ui/layout_translated.py`, `ui/widgets.py`, `ui/overlay.py` | `tests/test_ocr.py` |
| `translation_blocks.py` | `tests/test_translation_blocks.py` |
| `translate_client.py`, translate lifecycle | `tests/test_translate_client.py` |
| Real-image OCR / preview PNG tuning (opt-in only) | `tests/test_ocr_image_samples.py` |

## Combined gates from CLAUDE.md

- Translate lifecycle/grouping change:
  `.venv/Scripts/python.exe -m pytest tests/test_translate_client.py tests/test_translation_blocks.py tests/test_app.py`
- Translated overlay flow/layout change:
  `.venv/Scripts/python.exe -m pytest tests/test_translation_blocks.py tests/test_ocr.py tests/test_app.py` then
  `.venv/Scripts/python.exe -m compileall src tests`
- Launcher/app lifecycle change:
  `.venv/Scripts/python.exe -m pytest tests/test_main.py tests/test_app.py`

## Notes

- NEVER run plain `python` — PreToolUse hook denies it. Always `.venv/Scripts/python.exe`.
- `tests/test_ocr_image_samples.py` hits real GPU OCR and writes detail logs/preview PNGs — run only when the user asks for visual-tuning evidence, never as the fast default.
- If changed paths span multiple rows, run the union (e.g. ocr + translate change → `test_ocr.py` + `test_translation_blocks.py` + `test_app.py`).
