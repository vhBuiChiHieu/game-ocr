# OCR Overlay Font Sizing Spec

## Goal

Result overlay text must look like one intentional UI layer, not raw OCR boxes redrawn with noisy heights. Font sizing and spacing must preserve readable hierarchy while keeping related lines visually consistent.

Primary target: dialogue/menu screenshots where OCR returns line-level boxes from `rec_texts` + `rec_boxes`.

## Current Problem

Current code derives row font from each row height against global median height. This works for simple rows but fails when OCR boxes in one semantic group have different heights.

Example from `tests/imgs/ocr_detail_img_test_001.log`:

| Text | OCR box | Current font | Expected role |
|---|---:|---:|---|
| `Quit Now?` | `25,23,143,48` | `23` | Title |
| `Your progress will not be saved. Quit now?` | `175,133,609,154` | `17` | Body line 1 |
| `Any unsaved progress will be lost.` | `221,163,569,187` | `23` | Body line 2 |
| `Cancel` | `128,259,208,289` | `23` | Button |
| `Confirm` | `572,261,663,288` | `23` | Button |

Body lines are one semantic paragraph but render as `17` and `23`. This is visually wrong even though row spacing is acceptable.

## Principles

1. Semantic groups control consistency.
   - Lines in one paragraph/list group should share one font size unless strong evidence says otherwise.
   - Buttons on the same row should share one font size.
2. Visual hierarchy must be explicit.
   - Title can be larger than body.
   - Buttons can match title or body depending on source height, but buttons on same row must match each other.
3. OCR box height is noisy.
   - Use OCR height as signal, not absolute truth.
   - Normalize by local context before assigning buckets.
4. Spacing must follow font size and source gaps.
   - Lines in one paragraph: compact, equal-ish gaps.
   - Different groups: larger gaps, proportional to source gap but capped.
5. Fit must degrade gracefully.
   - Preserve hierarchy as long as possible.
   - If forced to shrink, shrink all font sizes with minimum readable floor.
   - Never allow row overlap.

## Terms

| Term | Meaning |
|---|---|
| Source line | `OcrLine` from OCR parser. |
| Row | One or more source lines with overlapping/nearby vertical centers. |
| Display segment | One drawn `DisplayLine`; row may split into multiple segments when horizontal gap is large. |
| Semantic group | Consecutive rows that visually belong together, e.g. title, paragraph, button row. |
| Role | Classified group type: `title`, `body`, `button`, `standalone`, `list`. |

## Pipeline

Recommended pipeline replaces direct per-row bucket assignment:

1. Normalize source lines.
2. Build rows.
3. Split rows into display segments.
4. Build semantic groups from rows.
5. Classify group roles.
6. Compute group font sizes.
7. Assign row/display font sizes from group fonts.
8. Compute intra/inter-group gaps.
9. Fit height with constrained scaling.
10. Emit debug summary with groups, roles, fonts, gaps.

## 1. Normalize Source Lines

For each source line:

- `height = max(1, bottom - top)`
- `width = max(1, right - left)`
- `center_y = (top + bottom) / 2`
- `center_x = (left + right) / 2`

Use robust stats:

- `median_height = median(heights)`
- `q1_height`, `q3_height` if available
- `height_iqr = max(1, q3 - q1)`

Clamp effective source heights before bucket decisions:

```text
effective_height = clamp(height, median_height - 1.5 * IQR, median_height + 1.5 * IQR)
```

If fewer than 4 rows, use median-relative clamp:

```text
effective_height = clamp(height, median_height * 0.75, median_height * 1.25)
```

Reason: prevents one noisy OCR box from making one body row tiny/huge.

## 2. Row Building

Keep current row merge logic conceptually:

- Same row if vertical boxes overlap.
- Same row if center distance <= `max(6, median_height * 0.6)`.

After row build, compute:

| Row property | Formula |
|---|---|
| `row_top` | min source top |
| `row_bottom` | max source bottom |
| `row_height` | median source heights in row |
| `row_left` | min source left |
| `row_right` | max source right |
| `row_width` | `row_right - row_left` |
| `row_text` | text joined by horizontal order |

## 3. Display Segment Split

Within row:

- Sort by `left`.
- Merge adjacent segments if horizontal gap <= `merge_gap_limit`.
- Keep distant segments separate.

Current merge gap rule is acceptable:

```text
merge_gap_limit = max(16, median_height * 1.8)
```

After splitting, all display segments in same row share row font size.

## 4. Semantic Grouping

Build groups from consecutive rows using vertical gaps and horizontal alignment.

For adjacent rows `a`, `b`:

```text
source_gap = b.top - a.bottom
height_ref = median(a.height, b.height, global_median_height)
left_delta = abs(a.left - b.left)
center_delta = abs(a.center_x - b.center_x)
width_ratio = min(a.width, b.width) / max(a.width, b.width)
```

Rows belong to same group when any rule matches:

### Paragraph Rule

```text
source_gap <= height_ref * 0.75
AND center_delta <= overlay_width * 0.18
```

Use for dialogue body lines.

### Aligned Text Block Rule

```text
source_gap <= height_ref * 1.0
AND left_delta <= max(24, overlay_width * 0.08)
```

Use for left-aligned multi-line notices.

### Button Row Rule

Rows with multiple distant display segments on same row form one `button` group. They should not merge with previous paragraph unless source gap is very small.

### Hard Break Rule

Always split group if:

```text
source_gap >= height_ref * 1.8
```

or source gap consumes large overlay fraction:

```text
source_gap >= overlay_height * 0.08
```

## 5. Role Classification

Classify groups after grouping.

### Button Group

Role `button` if row has multiple display segments and each segment is short.

Heuristic:

```text
segments_count >= 2
AND median(segment_text_length) <= 16
AND row_width >= overlay_width * 0.45
```

Also role `button` if row is near bottom and contains common short action labels, but do not require text dictionary for MVP.

### Title Group

Role `title` if all true:

```text
group_row_count == 1
AND group_index == 0
AND next_group_gap >= median_height * 1.4
AND text_length <= 40
```

Optional source-position hint:

```text
row_top <= overlay_height * 0.20
```

### Body Group

Role `body` if group has 2+ rows or sits between title and button groups.

### Standalone Group

Role `standalone` for single non-title, non-button rows.

### List Group

Role `list` if 3+ rows with similar left alignment and similar font source height.

## 6. Font Size Model

Stop assigning font size directly from each row height. Compute group font, then assign group font to all rows in group.

### Base Body Font

Use global median source height, width fit, and overlay height.

```text
body_from_height = round(median_height * 0.95)
body_font = clamp(body_from_height, 14, 22)
```

For small captures, allow smaller but never below readability floor:

```text
body_font_min = 11 if overlay_height < 110 else 14
body_font = max(body_font_min, body_font)
```

### Width Fit Estimate

Use Qt `QFontMetricsF` when possible. If not available in pure layout tests, approximate:

```text
estimated_text_width = len(text) * font_size * 0.55
```

For each display segment:

```text
max_segment_width = overlay_width - x - padding
```

A font is width-safe when all non-button segments fit:

```text
estimated_text_width <= max_segment_width
```

If not width-safe, reduce only group font until safe or min font reached.

### Role Multipliers

Start from body font:

| Role | Font rule |
|---|---|
| `title` | `body_font * 1.20`, clamped to source evidence |
| `body` | `body_font` |
| `button` | `max(body_font, button_source_font)` but not above title unless source says so |
| `standalone` | source-informed body/large bucket |
| `list` | `body_font` |

### Source Evidence Clamp

For each group:

```text
group_source_font = round(median(group_effective_heights) * 0.95)
```

Clamp final group font near source:

```text
lower = max(min_font, group_source_font * 0.85)
upper = min(max_font, group_source_font * 1.20)
font = clamp(role_font, lower, upper)
```

But for body groups with 2+ rows, prefer consistency over source variance:

```text
font = clamp(body_font, min(row_source_fonts), max(row_source_fonts))
```

Then round to integer.

### Harmonic Font Set

Final fonts should belong to limited set to avoid noisy differences:

```text
allowed_fonts = sorted(unique([body_font - 2, body_font, body_font + 3, body_font + 5]))
```

Snap group font to nearest allowed font within 2 px. If no allowed font is close, keep computed font.

### Font Difference Rules

Hard constraints:

- Rows within same group: identical font.
- Two adjacent body/list groups: font difference <= 2 px unless hard break gap exists.
- Title vs body: title >= body + 2 px when source supports it.
- Button segments on same row: identical font.
- Avoid isolated 1-row body font different by > 3 px from neighboring body rows.

## 7. Spacing Model

Compute gaps between rows/groups, not just rows.

### Intra-Group Gap

For rows inside same paragraph/list group:

```text
intra_gap = round(body_font * 0.30)
```

Clamp:

```text
intra_gap = clamp(intra_gap, 4, 8)
```

All intra-group gaps should be equal unless fit forces compression.

### Inter-Group Gap

For groups:

```text
source_gap_scaled = source_gap * 0.65
role_gap = max(prev_font, next_font) * role_gap_multiplier
```

Multipliers:

| Boundary | Multiplier |
|---|---:|
| title -> body | 0.75 |
| body -> button | 1.10 |
| body -> body hard break | 0.90 |
| standalone -> standalone | 0.80 |

Final:

```text
inter_gap = max(role_gap, source_gap_scaled)
inter_gap = clamp(inter_gap, min_gap, max_gap)
```

Recommended clamps:

```text
min_gap = 6
max_gap = round(median_height * 2.0)
```

## 8. Height Fit

Total layout height:

```text
total = padding_top + sum(row_fonts) + sum(row_gaps) + padding_bottom
```

If total <= overlay height, keep fonts/gaps.

If total > overlay height:

1. Reduce inter-group gaps toward minimum.
2. Reduce intra-group gaps toward minimum `2`.
3. Scale fonts uniformly, preserving relative hierarchy.
4. Re-apply font difference constraints at smaller scale.
5. If still too tall, set all fonts to minimum readable floor and gaps to `0/1`, never overlap.

Minimum readable floors:

| Capture height | Min font |
|---:|---:|
| `< 90` | 8 |
| `90–140` | 10 |
| `> 140` | 11 |

## 9. Horizontal Position Rules

Keep source x when it is plausible, but avoid edge clipping:

```text
x = clamp(source_left, padding, overlay_width - padding)
```

Optional visual polish for centered UI lines:

If row center is near overlay center and text width can be estimated, center text rather than using OCR left:

```text
abs(row_center_x - overlay_width / 2) <= overlay_width * 0.08
```

Then:

```text
x = round((overlay_width - text_width) / 2)
```

This should be applied after font sizing and width measurement.

## 10. Expected Result For Image 1

Input: `img_test_001.png`, overlay `801x336`.

Expected grouping:

| Group | Rows | Role | Font target | Gap behavior |
|---|---|---|---:|---|
| 1 | `Quit Now?` | title | `22–24` | Large gap before body |
| 2 | two body lines | body | same font, `18–20` | Compact intra-gap `5–7` |
| 3 | `Cancel`, `Confirm` | button | same font, `21–24` | Larger gap after body |

Important: body line 1 and body line 2 must not render as `17` and `23`. They should both use one size.

Acceptable concrete layout:

| Text | Font range | Notes |
|---|---:|---|
| `Quit Now?` | `22–24` | Title hierarchy clear |
| `Your progress will not be saved. Quit now?` | `18–20` | Same as next body line |
| `Any unsaved progress will be lost.` | `18–20` | Same as previous body line |
| `Cancel` | `21–24` | Same as Confirm |
| `Confirm` | `21–24` | Same as Cancel |

## Regression Cases

Use existing `tests/imgs/ocr_detail_img_test_*.log` outputs as fixtures.

### `img_test_001`

Must verify:

- 5 display lines.
- body lines share font.
- title font >= body font + 2.
- button fonts equal.
- body->button gap > body intra-gap.
- no line overlap.

### `img_test_002`

System message with 4 lines.

Must verify:

- all 4 body lines share same font or differ by <= 1 px.
- gaps between 4 lines are equal or differ by <= 1 px.
- no single line becomes tiny because OCR box is shorter.

Current bad risk: line 2 got font `12` while other lines got `16`. New algorithm should normalize this.

### `img_test_003`

Speaker + one dialogue line.

Must verify:

- speaker/name can be same or slightly larger than body.
- if both boxes have similar heights, fonts remain equal.
- vertical gap keeps name/body relationship compact.

### `img_test_004`

Speaker + two emphatic dialogue rows.

Must verify:

- two dialogue rows share same body/emphasis font or differ by <= 1 px.
- all-caps row must not shrink just because OCR box height is smaller.
- speaker remains separate title/name group.

Current bad risk: final all-caps row got `14` while previous dialogue row got `18`.

### `img_test_005`

Speaker + one dialogue line.

Must verify:

- name font `21–23` acceptable.
- dialogue font chosen by width fit; may be smaller than name due long text.
- no clipping horizontally.

## Debug Log Requirements

Update overlay layout debug summary to include:

```text
Result overlay layout:
  source_lines=N rows=N groups=N display_lines=N size=WxH
  median_height=... effective_heights=[...]
  groups=[{role, rows, source_font, final_font, intra_gap, inter_gap_after}, ...]
  fit={total_before, total_after, scale, reduced_gaps}
  display 1: xy=(x,y) font=f group=g role=r text='...'
```

This is required because visual tuning needs numeric evidence from real screenshots.

## Test Strategy

Unit tests should focus on constraints, not exact pixels, except where current behavior is known bad.

Suggested tests in `tests/test_ocr.py`:

1. `test_layout_normalizes_body_font_with_noisy_box_heights`
   - Similar to image 1 body rows: heights 21 and 24 with same paragraph.
   - Assert body fonts equal.
2. `test_layout_normalizes_multiline_notice_fonts`
   - Similar to image 2: one short OCR box among 4 rows.
   - Assert max-min font <= 1.
3. `test_layout_keeps_button_row_fonts_equal`
   - Distant segments same row.
   - Assert display segments same font.
4. `test_layout_preserves_title_body_hierarchy`
   - Title + body group.
   - Assert title >= body + 2 when source title height supports it.
5. `test_layout_gives_body_to_button_gap_more_than_body_intra_gap`
   - Assert visual grouping.
6. `test_layout_scales_to_fit_without_overlap`
   - Dense rows in short overlay.
   - Assert no overlap and font >= min floor.

## Implementation Notes

- Keep public function `layout_lines_for_display(lines, width, height)` unchanged.
- Add internal dataclasses if helpful: `LayoutRow`, `LayoutGroup`, `Segment`.
- Prefer small pure helpers for testability.
- Use Qt font metrics only inside UI-safe paths; tests should work without a QApplication if current tests do.
- Avoid text dictionaries except optional button hints; geometry should drive behavior.

## Acceptance Criteria

Implementation is acceptable when:

1. Image 1 body lines render same size and look like one paragraph.
2. Image 2 notice lines do not have one visibly smaller middle line.
3. Image 4 all-caps line is not undersized versus previous dialogue row.
4. Button row segments always match font size.
5. Existing row merge/separate behavior remains intact.
6. `python -m pytest tests/test_ocr.py` passes.
7. Real OCR detail logs include group/role/font debug data for visual inspection.
