# OCR Translate Block Logging Spec

## Goal

When the app starts, it should also ensure the local translate backend is available. After each OCR capture, the app should group OCR text into translation blocks, translate each block, and log source/translation pairs for tuning. No translated overlay UI is required in this phase.

Primary target: game dialogue/menu screenshots where OCR returns line-level boxes from PaddleOCR `rec_texts` + `rec_boxes`.

## Non-Goals

- No translated overlay rendering yet.
- No OCR history UI.
- No settings UI.
- No CPU fallback.
- No remote translation provider fallback.
- No batching API change unless needed later for performance.

## Current Components

| Path | Current role |
|---|---|
| `src/game_ocr/app.py` | app startup/shutdown lifecycle |
| `src/game_ocr/ocr.py` | OCR engine and OCR timing/debug logs |
| `src/game_ocr/ui/overlay.py` | selection/result overlay and display layout |
| `services/translate_api/run.py` | local FastAPI server entrypoint on `127.0.0.1:8765` |
| `services/translate_api/app.py` | `/health` and `/v1/translate`; forwards to Ollama `translategemma:4b` |
| `scripts/trans-api/local_translate_gemma_4b.py` | command-line client for manual translator API use |

## Startup Backend Lifecycle

### Desired Behavior

1. App child process starts as usual after detached launcher returns.
2. During app startup, before OCR hotkey becomes usable, app checks `GET http://127.0.0.1:8765/health`.
3. If backend is healthy enough to serve requests, app reuses it.
4. If backend is unavailable, app starts `services/translate_api/run.py` as a subprocess.
5. App polls `/health` until backend responds or timeout expires.
6. App continues running even if translate backend is degraded, but logs the degraded state.
7. On tray Exit/app shutdown, only subprocess started by this app is terminated.

### Health States

| `/health` result | Meaning | App action |
|---|---|---|
| `status=ok`, `ollama_reachable=true`, `model_ready=true` | backend ready | enable translate logging |
| `status=degraded`, `ollama_reachable=true`, `model_ready=false` | Ollama up, model missing | log warning, skip translate requests |
| `status=degraded`, `ollama_reachable=false` | backend up, Ollama down | log warning, skip translate requests |
| no response | backend down | spawn backend subprocess |

### Process Rules

- Use current Python executable or project venv Python for backend subprocess.
- Keep subprocess handle in app lifecycle state.
- Do not kill a backend process that was already running before app startup.
- Backend stdout/stderr should go to app daily log or a dedicated translate backend log.
- Startup timeout target: 10 seconds total.
- Health poll interval: 250-500 ms.

### Failure Handling

Translate backend failure must not block OCR itself.

| Failure | Behavior |
|---|---|
| backend spawn fails | log exception; OCR still works |
| health timeout | log timeout; OCR still works |
| backend exits later | log exit; skip future translate logging until app restart or later recovery is implemented |
| translate request fails | log block id + error; continue next block |

## OCR Translation Block Pipeline

The translation pipeline runs after OCR text/layout extraction and before or after existing result overlay display. For this phase, output is logs only.

Recommended sequence:

1. OCR returns source lines with text and boxes.
2. Normalize OCR lines.
3. Build layout rows.
4. Build text blocks using graph scoring.
5. Split blocks into sentence-level translation units when needed.
6. Translate each translation unit.
7. Log source text, box, grouping reasons, and translated text.

## Terms

| Term | Meaning |
|---|---|
| OCR line | one PaddleOCR text item with `text` and `bbox` |
| Row | one or more OCR lines on same visual baseline |
| Block | one semantic text unit to translate together |
| Translation unit | final text sent to `/v1/translate`; usually one block, sometimes one sentence split from a block |
| Hard break | evidence that two nearby OCR items should not belong to same sentence/block |
| Soft join | evidence that two OCR items likely form one sentence/block |

## Data Model

Suggested internal dataclasses:

```python
@dataclass(frozen=True)
class OcrTextNode:
    index: int
    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float | None = None

@dataclass(frozen=True)
class TextRow:
    index: int
    nodes: tuple[OcrTextNode, ...]
    text: str
    left: int
    top: int
    right: int
    bottom: int

@dataclass(frozen=True)
class TextBlock:
    index: int
    rows: tuple[TextRow, ...]
    text: str
    left: int
    top: int
    right: int
    bottom: int
    role: str
    reasons: tuple[str, ...]
```

Keep helpers pure where possible so grouping tests do not need Qt or PaddleOCR.

## 1. Normalize OCR Lines

For each OCR result item:

- Strip text.
- Collapse repeated whitespace.
- Drop empty strings.
- Normalize box into `left, top, right, bottom`.
- Compute:

```text
width = max(1, right - left)
height = max(1, bottom - top)
center_x = (left + right) / 2
center_y = (top + bottom) / 2
```

Global stats:

```text
median_height = median(node.height)
median_width = median(node.width)
median_char_width = median(node.width / max(1, len(node.text)))
```

Use robust defaults when node count is small:

```text
median_height = max(8, median_height)
median_char_width = clamp(median_char_width, 4, median_height * 0.9)
```

## 2. Build Rows

Sort nodes by `top`, then `left`. A node belongs to an existing row if either rule matches:

```text
vertical_overlap_ratio >= 0.45
```

or:

```text
abs(node.center_y - row.center_y) <= max(6, median_height * 0.55)
```

Within each row:

- Sort nodes by `left`.
- Join text with space unless punctuation spacing says otherwise.
- Preserve row bounding box as union of node boxes.

## 3. Detect Hard Separators Inside Rows

Some rows contain multiple independent UI labels/buttons. Split row segments before block building if adjacent nodes have a large horizontal gap.

For adjacent nodes `a`, `b` in same row:

```text
gap = b.left - a.right
normal_gap = median_char_width * 2.5
large_gap = max(median_height * 2.0, normal_gap)
```

Hard split if:

```text
gap >= large_gap
AND a.text does not end with open punctuation
AND b.text does not start with closing punctuation
```

Also hard split if both sides are short UI labels:

```text
len(a.text) <= 16
AND len(b.text) <= 16
AND gap >= median_height * 1.2
```

This prevents button/menu rows like `Cancel    Confirm` from becoming one translation sentence.

## 4. Graph-Based Block Grouping

Represent row segments as graph nodes. Add candidate edges only between nearby nodes in reading order.

### Reading Order

Default reading order:

1. top to bottom by row center
2. left to right inside row

Column-aware adjustment:

- Detect columns if many rows share similar `left` clusters and horizontal overlap between clusters is low.
- Process one column top-to-bottom before moving to next column when columns are clearly separated.
- For MVP, only apply this when horizontal gap between clusters is at least `overlay_width * 0.18`.

### Edge Scoring

For candidate previous node `a` and next node `b`:

```text
score = 0
```

Add positive evidence:

| Evidence | Score |
|---|---:|
| same row and horizontal gap <= `median_char_width * 2.5` | +4 |
| next row and vertical gap <= `median_height * 0.8` | +3 |
| left aligned within `max(20, median_height)` | +2 |
| centers aligned within `overlay_width * 0.15` | +1 |
| similar height ratio >= 0.75 | +1 |
| previous text has no terminal punctuation | +2 |
| previous text ends with comma/colon/open quote | +2 |
| next text starts lowercase/continuation punctuation | +1 |
| short orphan word near previous text | +2 |

Subtract negative evidence:

| Evidence | Score |
|---|---:|
| previous text ends with `.`, `!`, `?`, `。`, `！`, `？` | -4 |
| vertical gap >= `median_height * 1.6` | -5 |
| horizontal gap in same row >= `median_height * 2.0` | -4 |
| both sides short UI labels | -4 |
| next text looks like bullet/list marker | -3 |
| next text looks like speaker/name label and previous block already has body text | -3 |
| strong indentation change >= `overlay_width * 0.12` | -2 |
| row widths differ by more than 4x and not aligned | -2 |

Merge if:

```text
score >= 3
```

Hard split overrides score if any hard split rule fires.

### Hard Split Rules

Always split if:

```text
vertical_gap >= median_height * 2.2
```

or:

```text
same_row_gap >= overlay_width * 0.18
```

or:

```text
previous_text ends with terminal punctuation
AND next_text starts with uppercase/titlecase
AND vertical_gap >= median_height * 0.4
```

or:

```text
next_text matches bullet/list marker pattern
```

Bullet/list marker examples:

```text
- text
• text
1. text
[1] text
(A) text
```

## 5. Role Classification

Assign role after blocks are built. Role improves logging and later UI decisions.

| Role | Heuristic |
|---|---|
| `dialogue` | multi-row natural language block or long sentence in dialogue area |
| `speaker` | short standalone row above dialogue, often followed by body text |
| `button` | short standalone text in bottom row or multiple short row segments |
| `menu_item` | short standalone row in vertical list |
| `notice` | centered multi-row text block |
| `unknown` | fallback |

Role does not decide translation by itself; it only guides split/skip decisions and debug logs.

## 6. Sentence-Level Split Inside Blocks

After graph grouping, split overly broad blocks into translation units.

Split at terminal punctuation when all are true:

```text
punctuation in [. ! ? 。 ！ ？]
AND remaining text length >= 2
AND next token starts uppercase/titlecase/digit/open quote
```

Do not split for common false positives:

- decimal numbers: `3.14`
- ellipsis: `...`
- initials/abbreviations: `Mr.`, `Ms.`, `Dr.`, `St.`, `e.g.`, `i.e.`
- version numbers: `v1.2`

Keep quoted text together when possible:

```text
"Hello." she said
```

should remain one unit unless OCR geometry already split it strongly.

## 7. Translation Request Behavior

For each translation unit:

```json
{
  "text": "source text",
  "source_lang": "en",
  "target_lang": "vi"
}
```

Request target:

```text
POST http://127.0.0.1:8765/v1/translate
```

Timeout:

```text
35 seconds
```

Execution mode:

- First implementation can translate sequentially for simpler logs.
- Later implementation may use a worker thread or queue to avoid blocking UI.
- OCR overlay should still appear even if translation is slow. If synchronous translation delays overlay noticeably, move translation logging to background worker.

## 8. Logging Requirements

Log one summary per OCR capture:

```text
Translate grouping: source_lines=N rows=N blocks=N units=N backend=ready model=translategemma:4b
```

Log each block:

```text
Translate block 1 role=dialogue bbox=(l,t,r,b) rows=2 reason="line_wrap,no_terminal_punct"
  source: Hello there. Are you ready?
  vi: Xin chào. Bạn đã sẵn sàng chưa?
```

If translation fails:

```text
Translate block 1 failed role=dialogue bbox=(l,t,r,b) error="local translate api http error: 503"
  source: Hello there. Are you ready?
```

Log grouping debug details at debug level:

```text
Translate grouping edges:
  edge 1->2 score=6 merge reasons=[next_row_gap,left_align,no_terminal_punct]
  edge 2->3 score=-5 split reasons=[terminal_punct,strong_gap]
```

Do not log full raw PaddleOCR dumps in normal logs.

## 9. UTF-8 Output Note

Manual translator script can fail on Windows consoles using `cp1252` when printing Vietnamese characters. App logging should write UTF-8 daily logs and avoid console encoding dependence. If manual script remains supported, configure stdout UTF-8 in the script or document `PYTHONUTF8=1` usage.

## Implementation Plan

### Phase 1: Backend Lifecycle

Files likely touched:

| File | Change |
|---|---|
| `src/game_ocr/app.py` | start/check translate backend during app startup; stop owned subprocess during cleanup |
| `src/game_ocr/logging_config.py` | ensure backend subprocess output goes to log if needed |
| `tests/test_app.py` | verify backend reuse, spawn, timeout, cleanup |

Acceptance:

- App starts when backend already running.
- App starts backend when not running.
- App does not kill externally running backend on exit.
- App terminates owned backend on tray Exit.
- OCR still starts if backend unavailable.

### Phase 2: Pure Text Block Grouper

Files likely touched:

| File | Change |
|---|---|
| `src/game_ocr/ocr.py` or new internal module | add pure grouping helpers and block dataclasses |
| `tests/test_ocr.py` | unit tests for rows, hard splits, multi-line sentence joins, button splits |

Acceptance:

- Wrapped dialogue lines become one block.
- Separate buttons remain separate blocks.
- Speaker/name row remains separate from dialogue unless geometry/text strongly says same sentence.
- Bullet/list rows remain separate units.
- Debug reasons explain merges/splits.

### Phase 3: Translation Logging

Files likely touched:

| File | Change |
|---|---|
| `src/game_ocr/ocr.py` | call grouping after OCR extraction and log translation results |
| `src/game_ocr/translate_client.py` | optional small client wrapper for `/v1/translate` |
| `tests/test_ocr.py` | mock translate client and verify block logging behavior |

Acceptance:

- Each translation unit is sent to local API.
- Translation output is logged with source text and bbox.
- One failed unit does not stop later units.
- OCR overlay behavior remains unchanged.

### Phase 4: Real Screenshot Tuning

Run sample OCR tests and inspect detail logs:

```bash
.venv/Scripts/python.exe -m pytest tests/test_ocr.py
.venv/Scripts/python.exe -m pytest tests/test_ocr_image_samples.py
```

Tune thresholds only when logs show incorrect merge/split decisions.

## Test Cases

### Wrapped Dialogue

Input:

```text
[10,10,300,30] "This is the first part of"
[10,34,280,54] "the same sentence."
```

Expected:

- one block
- one translation unit
- reason includes `next_row_gap` and `no_terminal_punct`

### Speaker + Dialogue

Input:

```text
[10,10,80,30] "Alice"
[10,45,320,65] "We should leave now."
```

Expected:

- two blocks
- roles: `speaker`, `dialogue`

### Button Row

Input:

```text
[50,200,130,230] "Cancel"
[500,200,590,230] "Confirm"
```

Expected:

- two blocks
- both role `button`
- hard split due same-row large gap

### Multi-Sentence Paragraph

Input:

```text
[10,10,500,30] "Hello there. Are you ready?"
```

Expected:

- one block
- two translation units if sentence splitting enabled

### Bullet List

Input:

```text
[10,10,200,30] "- Attack"
[10,35,200,55] "- Defend"
```

Expected:

- two blocks
- no merge despite close vertical gap

## Acceptance Criteria

Feature is acceptable when:

1. Starting `python -m game_ocr` ensures local translate backend is running or logs why it is unavailable.
2. App shutdown cleans up only backend process it started.
3. OCR still works when translate backend/Ollama/model is unavailable.
4. OCR result produces text blocks with deterministic geometry/text rules.
5. Wrapped dialogue is translated as one unit, while buttons/menu items remain separate.
6. Logs include block source text, bbox, role, grouping reason, and translated text/error.
7. `python -m pytest tests/test_app.py tests/test_ocr.py` passes.
8. Real sample logs from `tests/test_ocr_image_samples.py` show useful grouping/translation diagnostics.
