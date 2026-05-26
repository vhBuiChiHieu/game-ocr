# Game OCR Project Notes

## Commands

```bash
source .venv/Scripts/activate
python -m pip install -e ".[dev]"
python -m game_ocr
python -m pytest
python -m compileall src tests
```

Use targeted tests when touching focused areas:

| Area | Command |
|---|---|
| Detached launcher / logging path | `python -m pytest tests/test_main.py` |
| App startup / GPU gate / cleanup | `python -m pytest tests/test_app.py` |
| Capture region math | `python -m pytest tests/test_capture.py` |
| OCR config loading | `python -m pytest tests/test_ocr_config.py` |
| OCR parsing / overlay layout | `python -m pytest tests/test_ocr.py` |
| OCR sample screenshots / detail logs | `python -m pytest tests/test_ocr_image_samples.py` |

Manual UI check: run `python -m game_ocr`, verify terminal returns, tray icon appears, hotkey OCR works, tray Exit stops process, `logs/YYYY-MM-DD.log` captures output.

Use `.venv` / Python 3.10. Default system `python` may point to Python 3.13 and should be avoided for this project.

## Local Translate Backend

- Run backend: `.venv/Scripts/python.exe services/translate_api/run.py`; serves `127.0.0.1:8765` and calls Ollama `translategemma:4b`.
- Translator script: `scripts/trans-api/local_translate_gemma_4b.py` posts to `/v1/translate`; use with OCR Translator API menu for local Gemma.
- Translate backend lifecycle lives in `src/game_ocr/translate_client.py`; mock `ensure_translate_backend`/`stop_owned_translate_backend` in app lifecycle tests.
- Translated overlay translates units before display; backend/total failure falls back to source overlay, partial unit failure renders source for that unit.
- Translate deps: `fastapi`, `uvicorn`, `pydantic` are runtime dependencies in `pyproject.toml`.
- Verify backend: `.venv/Scripts/python.exe -m compileall services scripts/trans-api/local_translate_gemma_4b.py` and import `services.translate_api.app`.

## Environment

- Target: Windows-only, run from source.
- Runtime: GPU-only PaddleOCR; no CPU fallback for MVP.
- Expected GPU check: `paddle.device.is_compiled_with_cuda()` must be `True`, then app uses `gpu:0`.
- `ccache` warning from Paddle is non-blocking.

## Architecture

| Path | Role |
|---|---|
| `src/game_ocr/__main__.py` | `python -m game_ocr` entrypoint |
| `src/game_ocr/app.py` | app startup, GPU gate, OCR preload, hotkey lifecycle |
| `src/game_ocr/config.py` | constants for hotkey, OCR language/config path, region size, user-facing messages |
| `src/game_ocr/ocr.py` | PaddleOCR initialization, OCR call, timing log |
| `src/game_ocr/ocr_config.py` | loads root `ocr-config.json`, validates supported keys, filters `null` values |
| `src/game_ocr/logging_config.py` | daily log path/config for `logs/YYYY-MM-DD.log` |
| `src/game_ocr/capture.py` | screen-region capture |
| `src/game_ocr/clipboard.py` | copies recognized text with `pyperclip` |
| `src/game_ocr/hotkeys.py` | global hotkey registration |
| `src/game_ocr/ui/overlay.py` | drag-select overlay plus OCR result overlay; ESC closes both |
| `src/game_ocr/ui/notify.py` | console feedback |
| `src/game_ocr/ui/tray.py` | pystray icon lifecycle and Exit action |

Runtime flow:

1. `python -m game_ocr` starts `src/game_ocr/__main__.py`.
2. Parent process spawns detached child with `GAME_OCR_DETACHED=1`, then returns.
3. Child configures daily file logging, requires CUDA Paddle, preloads `OcrEngine`, registers `alt+shift+z`, and starts tray icon.
4. Hotkey opens `SelectionOverlay`; selected region is captured by `mss`.
5. `OcrEngine.read_text()` runs PaddleOCR, extracts text/layout, copies text to clipboard, prints bounded debug summary, and shows result overlay.
6. Tray Exit unregisters hotkey, stops tray thread, and quits Qt app.

## OCR Notes

- PaddleOCR 3.5 uses `predict(...)`; do not switch back to legacy `ocr(..., cls=False)`.
- Current OCR call disables textline orientation per capture with `use_textline_orientation=False`.
- PaddleOCR 3.5 recognized text can appear in `rec_texts`; extractor also supports legacy tuple shapes for tests.
- Root `ocr-config.json` can override PaddleOCR model names/dirs. `null` values are ignored, preserving PaddleOCR defaults.
- `ocr-config.json` rejects unknown keys via `load_ocr_config()`; add allowed keys in `ocr_config.py` before using new PaddleOCR options.
- `return_word_box: true` supports fallback layout extraction from `text_word_region`; keep it unless overlay fallback is no longer needed.
- OCR call logs processing time plus bounded line/box summary; avoid full raw Paddle dumps in normal logs.
- Detached launcher should lazy-import `game_ocr.app.run()` only in child mode so parent start returns fast.
- Detached logging: keep `game_ocr` logger on its own append-close handler; stdout/stderr append-close separately so Paddle output cannot silence app logs.
- Windows detached launcher may prefer `pythonw.exe` over `python.exe`; keep `python -u -m game_ocr` semantics when testing subprocess args.
- OCR result overlay should render line-level layout from `rec_texts` + `rec_boxes`; use word regions only as fallback.
- Result overlay uses semantic groups for font/gap consistency: body rows share fonts, button segments match, debug logs include groups/roles/fonts/gaps.
- Result overlay is topmost, same size as selected region, centered horizontally at ~75% screen height on the selection's monitor.
- Result overlay picks the monitor of the OCR selection via `QGuiApplication.screenAt(region center)`; falls back to primary screen when no monitor matches.
- Source overlay vertically centers content when total layout height is less than overlay height (`_build_display_lines` uses `overlay_height` to compute slack).
- After `_fit_groups_to_height` scales fonts, `_resync_gaps_to_fonts` re-clamps intra/inter gaps so stale gap budgets do not reintroduce overflow.
- Overlay layout and OCR debug-log behavior are covered in `tests/test_ocr.py`.
- OCR translation block grouping lives in `src/game_ocr/translation_blocks.py`; keep it pure and cover heuristics in `tests/test_translation_blocks.py`.
- Source overlay uses `layout_lines_for_display()`; translated overlay uses `layout_translated_blocks_for_display()` and `DisplayTextBox`.
- Translated box width shrinks to the wrapped text width: lower bound is source bbox width (preserve spatial mapping), upper bound is the role-derived cap returned by `_translated_box_size`.
- Translated collision resolver runs move-only passes first; if overlap remains, it refits the lower-priority candidate at a smaller `max_font` and re-runs the move pass. Buttons, titles, and speakers are protected from shrink.
- Translated box height and `_paint_boxes` step use `_translated_line_step ≈ font_size * 1.2` to cover ascent + descent; using bare `font_size` clips descenders below the computed box.
- Translated layout tests run without QApplication; guard Qt font metrics or use deterministic width estimates in pure tests.
- Translated overlay logs should include backend/model, block/unit counts, fallback reason, per-block bbox, completion, target box, font, align, wrap count, overflow/overlap.

## Testing Notes

- `tests/test_main.py` verifies parent/child detached behavior and daily log path format.
- `tests/test_app.py` verifies CUDA requirement, `gpu:0` selection, hotkey cleanup, tray cleanup, and queued Qt quit.
- `tests/test_capture.py` verifies drag direction normalization and rejects selections smaller than `MIN_REGION_SIZE`.
- `tests/test_ocr_config.py` verifies missing config defaults to `{"lang": "en"}`, `null` values are ignored, and unsupported keys fail fast.
- `tests/test_ocr.py` verifies PaddleOCR parsing, bounded logs, row/segment merging, semantic font consistency, compact gaps, and height fitting.
- `tests/test_ocr_image_samples.py` runs real OCR against `tests/imgs/*` and writes `tests/imgs/ocr_detail_*.log`; use it for visual tuning evidence, not as the fast default unit path.
- Keep sample detail logs capturing `layout_lines_for_display(...)` output so overlay group/role/font summaries appear in `captured_logs`.

Before changing OCR parsing or overlay layout, run:

```bash
python -m pytest tests/test_ocr.py
```

Before changing launcher/app lifecycle, run:

```bash
python -m pytest tests/test_main.py tests/test_app.py
```

Before changing translate lifecycle/grouping, run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_translate_client.py tests/test_translation_blocks.py tests/test_app.py
```

Before changing translated overlay flow/layout, run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_translation_blocks.py tests/test_ocr.py tests/test_app.py
.venv/Scripts/python.exe -m compileall src tests
```

## Scope

Keep MVP minimal unless explicitly requested:
- no packaging/installer
- no CPU fallback
- no settings UI
- no OCR history
- no multi-language switching
- no advanced preprocessing modes

Also keep UX minimal:
- default hotkey stays `alt+shift+z` unless requested
- tiny drag selections below `MIN_REGION_SIZE` cancel instead of OCR
- success path copies text to clipboard before showing result overlay

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **game-ocr** (1075 symbols, 1776 relationships, 47 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/game-ocr/context` | Codebase overview, check index freshness |
| `gitnexus://repo/game-ocr/clusters` | All functional areas |
| `gitnexus://repo/game-ocr/processes` | All execution flows |
| `gitnexus://repo/game-ocr/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
