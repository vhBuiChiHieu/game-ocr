# MVP Spec: GPU-only Screen OCR

## Goal

Build a Windows-only Python app that lets the user press `Alt+Shift+Z`, drag-select one screen region, OCR the captured image with PaddleOCR on GPU, then copy recognized English text to clipboard and show feedback.

## Scope

### In scope

- Windows-only runtime.
- Run from source inside local Python virtual environment.
- PaddleOCR with English language model.
- GPU-only execution.
- Global hotkey: `Alt+Shift+Z`.
- Single drag-selection overlay per hotkey press.
- `ESC` cancels selection.
- Clipboard copy after successful OCR.
- Toast notification or console log for success/error feedback.

### Out of scope

- Packaging/building installer.
- CPU fallback.
- Settings UI.
- OCR history.
- Multi-language switching.
- Reusing previous region.
- Advanced preprocessing modes.

## Requirements

### GPU-only startup check

On app startup:

1. Import `paddle`.
2. Check `paddle.device.is_compiled_with_cuda()`.
3. If `False`, print a clear error and exit with non-zero status.
4. If `True`, set device to `gpu:0` and continue.

Expected error example:

```text
GPU OCR requires PaddlePaddle with CUDA support. Install paddlepaddle-gpu and run again.
```

No CPU fallback should exist in MVP.

### OCR language

- Use PaddleOCR English language config: `lang="en"`.
- Model should be initialized once at app startup, not per capture.
- First hotkey press may wait for model preload only if startup preload fails or is deferred, but preferred behavior is preload at startup.

### Overlay selection

When user presses `Alt+Shift+Z`:

1. Show fullscreen transparent overlay.
2. User clicks and drags to select one rectangular screen region.
3. On mouse release, overlay closes and selected region is captured.
4. If user presses `ESC`, overlay closes and no OCR runs.

Selection behavior:

- One selection per hotkey activation.
- Empty or near-zero region is treated as cancel.
- Overlay should not remain visible during screenshot capture.

### OCR output

After OCR succeeds:

1. Join detected text lines into one plain-text string.
2. Copy text to clipboard.
3. Show toast notification if practical; otherwise log to console.

Minimum console feedback:

```text
OCR copied to clipboard: <recognized text>
```

If OCR returns no text:

```text
No text detected.
```

## Project structure

Use a `src/` layout from the start so app code, tests, docs, and runtime artifacts stay separated.

```text
game-ocr/
├─ docs/
│  └─ mvp-spec.md
├─ src/
│  └─ game_ocr/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ app.py
│     ├─ config.py
│     ├─ hotkeys.py
│     ├─ ocr.py
│     ├─ capture.py
│     ├─ clipboard.py
│     └─ ui/
│        ├─ __init__.py
│        ├─ overlay.py
│        └─ notify.py
├─ tests/
│  └─ test_*.py
├─ .venv/
├─ .gitignore
├─ pyproject.toml
└─ README.md
```

### Module responsibilities

| File | Responsibility |
|---|---|
| `src/game_ocr/__main__.py` | CLI entrypoint for `python -m game_ocr` |
| `src/game_ocr/app.py` | App startup, GPU check, OCR preload, hotkey lifecycle |
| `src/game_ocr/config.py` | Constants for hotkey, OCR language, minimum region size |
| `src/game_ocr/hotkeys.py` | Global hotkey registration and cleanup |
| `src/game_ocr/ocr.py` | PaddleOCR GPU initialization and image OCR |
| `src/game_ocr/capture.py` | Screen-region capture via `mss` |
| `src/game_ocr/clipboard.py` | Clipboard copy helper |
| `src/game_ocr/ui/overlay.py` | Transparent drag-selection overlay and ESC cancel |
| `src/game_ocr/ui/notify.py` | Toast notification or console fallback |
| `tests/` | Unit tests for pure logic and smoke tests where practical |

### Structure rules

- Keep all importable app code under `src/game_ocr/`.
- Keep UI code under `src/game_ocr/ui/`.
- Keep runtime config in `config.py` for MVP; do not add settings UI yet.
- Keep generated screenshots/debug images out of git.
- Use `python -m game_ocr` as the main run command.

## Acceptance criteria

- Running app with CUDA-enabled Paddle starts successfully and logs GPU device.
- Running app without CUDA-enabled Paddle exits with clear GPU-only error.
- Pressing `Alt+Shift+Z` shows selection overlay.
- Drag-selecting a region runs OCR on captured image.
- Pressing `ESC` cancels without OCR.
- Recognized English text is copied to clipboard.
- Success, cancel, no-text, and error states are visible via toast or console log.
