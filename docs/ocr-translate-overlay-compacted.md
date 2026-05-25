Spec: Translated Result Overlay giữ vị trí tương đối OCR
Mục tiêu
Render text đã dịch lên ResultOverlay, giữ bố cục tương đối so với text gốc trong vùng capture.
┌───────────────────────┬───────────────────────────────────────────────────────────────────────────────┐
│        Yêu cầu        │                                   Chi tiết                                    │
├───────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
│ Input                 │ OcrResult.lines, capture Region, translate backend                            │
├───────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
│ Output                │ Overlay hiển thị text tiếng Việt tại vị trí tương ứng text gốc                │
├───────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
│ Ưu tiên               │ Bố cục đúng > font đẹp > tốc độ                                               │
├───────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
│ Độ khó chấp nhận      │ Thuật toán fit/wrap/collision phức tạp OK                                     │
├───────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
│ UX                    │ Overlay hiện sau khi dịch xong; không hiện source rồi flicker sang translated │
├───────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
│ Existing behavior giữ │ Clipboard vẫn copy OCR source text trước, trừ khi sau này yêu cầu đổi         │
└───────────────────────┴───────────────────────────────────────────────────────────────────────────────┘

Non-goals
┌────────────────────────────────────────────────────┬─────────────────────────────────────────┐
│                     Không làm                      │                  Lý do                  │
├────────────────────────────────────────────────────┼─────────────────────────────────────────┤
│ Không dịch trực tiếp trong paintEvent              │ UI freeze, khó debug                    │
├────────────────────────────────────────────────────┼─────────────────────────────────────────┤
│ Không dùng raw OCR line layout cho translated text │ Text Việt dài/ngắn khác, dễ tràn        │
├────────────────────────────────────────────────────┼─────────────────────────────────────────┤
│ Không replace layout_lines_for_display()           │ Source overlay vẫn cần fallback/test cũ │
├────────────────────────────────────────────────────┼─────────────────────────────────────────┤
│ Không thêm settings UI                             │ Ngoài MVP                               │
├────────────────────────────────────────────────────┼─────────────────────────────────────────┤
│ Không CPU fallback / backend fallback phức tạp     │ Project scope hiện tại                  │
└────────────────────────────────────────────────────┴─────────────────────────────────────────┘

Current flow cần đổi
Hiện tại

capture
→ OCR
→ copy source text
→ show source ResultOverlay
→ overlay closed
→ translate in background for logs only

Flow mới

capture
→ OCR
→ copy source text
→ build translation blocks
→ translate units
→ compose translated blocks
→ show translated ResultOverlay
→ overlay closed
→ log final translated layout

Nếu backend unavailable hoặc translate lỗi toàn bộ:

capture
→ OCR
→ copy source text
→ show source ResultOverlay
→ log translate skipped/error

Nếu translate lỗi một vài block:

block failed → render source text for that block
block success → render translated text
log per-block status

External API là boundary, nên partial failure handling hợp lệ.

Data model

Existing

TranslationUnit hiện có:

index
block_index
text
left/top/right/bottom
role
reasons

Vấn đề: 1 visual block có thể split thành nhiều unit, như log:

block 2 bbox=(155,116,541,136)
unit 2: Your progress will not be saved.
unit 3: Quit now?

Nếu render từng unit riêng, 2 câu chồng lên cùng bbox. Cần compose lại theo block_index.

New internal models

@dataclass(frozen=True)
class TranslatedBlock:
    block_index: int
    source_text: str
    translated_text: str
    left: int
    top: int
    right: int
    bottom: int
    role: str
    rows: int
    reasons: tuple[str, ...]
    complete: bool

@dataclass(frozen=True)
class DisplayTextBox:
    text: str
    x: int
    y: int
    width: int
    height: int
    font_size: int
    role: str
    align: str  # left | center
    source_bbox: tuple[int, int, int, int]
    wrapped_lines: tuple[str, ...]

DisplayLine giữ cho source overlay. Translated overlay dùng DisplayTextBox.

Translation composition

Step 1: Build grouping

grouping = build_translation_blocks(ocr_result.lines, width=region.width, height=region.height)

Step 2: Translate units

Dịch từng TranslationUnit.text, vì sentence-level thường tốt hơn paragraph-level.

unit 1 source -> vi
unit 2 source -> vi
unit 3 source -> vi
...

Step 3: Compose per block

Group units by block_index.

Rule:

┌──────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────┐
│       Case       │                                           Compose                                           │
├──────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1 unit/block     │ translated text = unit translation                                                          │
├──────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ many units/block │ join translated units bằng newline nếu source sentences tách rõ; space nếu role button/menu │
├──────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ failed unit      │ use source unit text for that part                                                          │
├──────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ all failed       │ complete=false, translated_text=source block text                                           │
└──────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────┘

Recommended join:

role in {"dialogue", "notice", "body"} -> "\n".join(parts)
role in {"button", "menu_item", "speaker"} -> " ".join(parts)

Reason: body/dialogue cần line break tự nhiên; button cần compact.

Layout engine mới

Function proposed:

def layout_translated_blocks_for_display(
    blocks: list[TranslatedBlock],
    width: int,
    height: int,
) -> list[DisplayTextBox]:

Không thay layout_lines_for_display().

Layout goals

Score-based fit. Không hardcode cho sample.

┌───────────────────────────┬───────────────────────────────┐
│           Goal            │            Meaning            │
├───────────────────────────┼───────────────────────────────┤
│ Preserve source anchor    │ translated block gần bbox gốc │
├───────────────────────────┼───────────────────────────────┤
│ Avoid overlap             │ boxes không đè nhau           │
├───────────────────────────┼───────────────────────────────┤
│ Fit within capture region │ không tràn overlay            │
├───────────────────────────┼───────────────────────────────┤
│ Preserve role semantics   │ title/body/button khác nhau   │
├───────────────────────────┼───────────────────────────────┤
│ Max readability           │ font lớn nhất có thể          │
├───────────────────────────┼───────────────────────────────┤
│ Stable output             │ cùng input ra cùng layout     │
└───────────────────────────┴───────────────────────────────┘

Role behavior

┌──────────────────────────┬────────────────────────────────────┬──────────────────────────────────────┬───────────────────────────────┐
│           Role           │               Anchor               │              Alignment               │           Expansion           │
├──────────────────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────────────────┤
│ title / speaker          │ source bbox top-left + center zone │ left unless near center              │ expand right/down moderate    │
├──────────────────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────────────────┤
│ dialogue / notice / body │ source bbox center                 │ center if source centered, else left │ expand into nearby whitespace │
├──────────────────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────────────────┤
│ button                   │ source bbox center                 │ center                               │ strict, minimal expansion     │
├──────────────────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────────────────┤
│ menu_item                │ source bbox top-left               │ left                                 │ horizontal expansion allowed  │
├──────────────────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────────────────┤
│ unknown                  │ source bbox top-left               │ left                                 │ conservative                  │
└──────────────────────────┴────────────────────────────────────┴──────────────────────────────────────┴───────────────────────────────┘

Alignment detection:

centered if abs(source_center_x - overlay_width / 2) <= overlay_width * 0.15
button always center
dialogue centered if original row centered
otherwise left

Candidate target box generation

For each TranslatedBlock, create target box candidates from source bbox.

Source:

source_w = right - left
source_h = bottom - top
source_cx = (left + right) / 2
source_cy = (top + bottom) / 2

Base padding

overlay_padding = 12
min_gap = 4

Role expansion rules

┌──────────────────────┬───────────────────────────────────────────────┬──────────────────┐
│         Role         │                Width candidate                │ Height candidate │
├──────────────────────┼───────────────────────────────────────────────┼──────────────────┤
│ title/speaker        │ source_w * 1.8, max 45% overlay               │ source_h * 2.2   │
├──────────────────────┼───────────────────────────────────────────────┼──────────────────┤
│ dialogue/body/notice │ max(source_w, 55% overlay), up to 80% overlay │ source_h * 3.5   │
├──────────────────────┼───────────────────────────────────────────────┼──────────────────┤
│ button               │ source_w * 1.6, max source_w + 80             │ source_h * 1.6   │
├──────────────────────┼───────────────────────────────────────────────┼──────────────────┤
│ menu_item            │ source_w * 2.0                                │ source_h * 2.0   │
└──────────────────────┴───────────────────────────────────────────────┴──────────────────┘

Clamp to overlay bounds.

Vertical whitespace expansion

Better than blind scaling: use neighbor gaps.

For block i:

prev_bottom = previous source bottom
next_top = next source top

available_top = midpoint(prev_bottom, current.top) if prev exists else padding
available_bottom = midpoint(current.bottom, next_top) if next exists else height - padding

Target box may expand inside:

top >= available_top
bottom <= available_bottom

For grouped body text between title and buttons, allow body stack to use shared vertical band.

Text fit algorithm

Use Qt metrics, not char-count approximation.

Function:

def fit_text_to_box(text, role, candidate_box, preferred_font, min_font) -> FitResult

Font size range

┌───────────────┬─────────────────────────┬─────┐
│     Role      │        Preferred        │ Min │
├───────────────┼─────────────────────────┼─────┤
│ title/speaker │ source_h * 1.05 to 1.25 │ 12  │
├───────────────┼─────────────────────────┼─────┤
│ dialogue/body │ source_h * 0.90 to 1.05 │ 11  │
├───────────────┼─────────────────────────┼─────┤
│ button        │ source_h * 0.95 to 1.10 │ 10  │
├───────────────┼─────────────────────────┼─────┤
│ small overlay │ clamp min lower to 8    │     │
└───────────────┴─────────────────────────┴─────┘

Try descending font sizes.

Wrap

Use QFontMetricsF:

split text into words
build lines while width <= box_width
if single word too long: allow it as own line and shrink font

Newlines from composition are hard breaks.

Fit constraints

Candidate valid if:

wrapped_height <= box_height
max_line_width <= box_width
font_size >= min_font

If none valid:

1. increase box height within allowed vertical band.
2. increase width within overlay bounds.
3. shrink to min font.
4. accept overflow only as last resort, log overflow.

Global collision resolution

After initial fit, boxes can overlap. Resolve by role priority.

Priority order:

title/speaker
body/dialogue/notice/menu_item
button

But buttons are anchored hard: do not move buttons unless overlap unavoidable.

Collision loop

For boxes sorted by source top:

1. If current overlaps previous:
  - body/dialogue: move current down until gap.
  - title: keep; move next body down.
  - button: keep center; shrink/move body above.
2. If current exceeds overlay bottom:
  - shrink current font.
  - reduce vertical gaps.
  - move body upward if safe.
3. If still impossible:
  - allow body multi-line overlap prevention by smaller font.
  - final clamp and log collision_unresolved.

Gap

min_vertical_gap = max(2, round(font_size * 0.15))

Special handling: same row buttons

Buttons from sample:

Cancel bbox=(113,227,185,254)
Confirm bbox=(507,228,589,254)

Render as same-row independent boxes.

Rule:

┌───────────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│                   Condition                   │                         Action                         │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ two+ short blocks same y band and role button │ lock same baseline                                     │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ translated button wider than source           │ expand around source center                            │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ overlap between buttons                       │ shrink font first, then reduce width, never swap order │
├───────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ one button much longer                        │ cap width to available half-row                        │
└───────────────────────────────────────────────┴────────────────────────────────────────────────────────┘

Button target:

center_x = source_center_x
target_width = max(source_w, measured_text_width + padding_x * 2)
target_height = measured_text_height
x = center_x - target_width / 2
y = shared_button_y

Shared button y:

median(button source top)

Example expected layout for provided log

Input size 704x295.

Blocks

┌───────┬───────────────────┬───────────────────┬──────────────────────────────────────────────────────────────┐
│ Block │       Role        │    Source bbox    │                          Translated                          │
├───────┼───────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 1     │ speaker/title-ish │ (22,18,128,40)    │ Bỏ cuộc ngay bây giờ?                                        │
├───────┼───────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 2     │ dialogue          │ (155,116,541,136) │ Tiến trình của bạn sẽ không được lưu.\nBỏ cuộc ngay bây giờ? │
├───────┼───────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 3     │ dialogue          │ (195,141,506,165) │ Bất kỳ tiến trình nào chưa được lưu sẽ bị mất.               │
├───────┼───────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 4     │ button            │ (113,227,185,254) │ Hủy                                                          │
├───────┼───────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 5     │ button            │ (507,228,589,254) │ Xác nhận                                                     │
└───────┴───────────────────┴───────────────────┴──────────────────────────────────────────────────────────────┘

Expected behavior

┌──────────────┬───────────────────────────────────────────────────────────────────┐
│     Text     │                             Placement                             │
├──────────────┼───────────────────────────────────────────────────────────────────┤
│ Title        │ near top-left, may expand right; not centered fullscreen          │
├──────────────┼───────────────────────────────────────────────────────────────────┤
│ Body block 2 │ centered in same horizontal band as source body, may wrap 2 lines │
├──────────────┼───────────────────────────────────────────────────────────────────┤
│ Body block 3 │ below block 2, same visual body group                             │
├──────────────┼───────────────────────────────────────────────────────────────────┤
│ Buttons      │ same row, near original x positions                               │
└──────────────┴───────────────────────────────────────────────────────────────────┘

Integration points

app.py

Change CaptureController._run_capture_flow():

Current:

ResultOverlay.show_result(ocr_result.lines, region)
logger.info("OCR result overlay closed.")
_start_translation_logging(...)

New:

translated_blocks = translate_ocr_result_for_overlay(...)
ResultOverlay.show_translated(translated_blocks, region)
logger.info("OCR translated result overlay closed.")

Keep fallback:

if translated_blocks is None:
    ResultOverlay.show_result(ocr_result.lines, region)

translation_blocks.py

Keep existing grouping. Add helper maybe:

def compose_translated_blocks(
    grouping: TranslationGrouping,
    translations: Mapping[int, str],
) -> tuple[TranslatedBlock, ...]:

But TranslatedBlock may live closer to overlay/translation service, depending import direction.

Avoid importing Qt in translation_blocks.py.

overlay.py

Add:

class TranslatedResultOverlay(QtWidgets.QDialog):
    ...

or extend ResultOverlay carefully:

ResultOverlay.show_result(...)       # source lines
ResultOverlay.show_translated(...)   # translated boxes

Recommended: same class, two constructors internally:

self._lines: list[DisplayLine]
self._boxes: list[DisplayTextBox]

paintEvent:

if _boxes: draw wrapped text boxes
else: draw source lines

Logging spec

Need logs useful like current OCR layout logs.

Translation phase

Translate overlay: source_lines=5 rows=5 blocks=5 units=6 backend=ready model=translategemma:4b

Per block:

Translate overlay block 2 role=dialogue bbox=(155,116,541,136) units=2 complete=True
  source: Your progress will not be saved. Quit now?
  vi: Tiến trình của bạn sẽ không được lưu.
      Bỏ cuộc ngay bây giờ?

Layout phase

Translated overlay layout:
  blocks=5 boxes=5 size=704x295
  fit={overflow=0 overlaps=0 min_font=11}
  box 1: role=speaker source=(22,18,128,40) target=(22,18,245,46) font=20 align=left lines=1 text='Bỏ cuộc ngay bây giờ?'
  box 2: role=dialogue source=(155,116,541,136) target=(150,92,555,142) font=18 align=center lines=2 text='Tiến trình...|Bỏ cuộc...'
  ...

If collision:

  collision_fix block=3 action=move_down delta=8

If fallback source:

Translate overlay fallback: reason='backend unavailable'

Tests

Unit tests

Add to tests/test_ocr.py or new tests/test_translated_overlay.py.

┌──────────────────────────────────┬─────────────────────────────────────────────────────────────┐
│               Test               │                           Verify                            │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ compose split units same block   │ two translated units become one TranslatedBlock             │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ translated body wraps            │ long Vietnamese body wraps inside target box                │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ buttons keep relative x          │ Hủy remains near left button, Xác nhận near right button    │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ no overlap sample                │ sample boxes do not overlap                                 │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ source fallback on total failure │ source overlay path still works                             │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ partial failure                  │ failed block uses source, successful blocks use translation │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ same row buttons                 │ same baseline and order preserved                           │
├──────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ tiny region                      │ min font/clamp no crash                                     │
└──────────────────────────────────┴─────────────────────────────────────────────────────────────┘

Golden sample from log

Use OCR lines:

[
    OcrLine("Quit Now?", 22, 18, 128, 40),
    OcrLine("Your progress will not be saved. Quit now?", 155, 116, 541, 136),
    OcrLine("Any unsaved progress will be lost.", 195, 141, 506, 165),
    OcrLine("Cancel", 113, 227, 185, 254),
    OcrLine("Confirm", 507, 228, 589, 254),
]

Expected assertions:

len(boxes) == 5
no overlaps
all boxes inside 704x295
button boxes y difference <= 4
left button center_x < right button center_x
body boxes between title and buttons
block 2 wrapped_lines >= 2

Acceptance criteria

┌─────────────────────┬───────────────────────────────────────────────────────────────────────┐
│      Criteria       │                            Pass condition                             │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Position preserved  │ translated boxes remain near source bbox / role zone                  │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Text readable       │ font >= min readable unless overlay tiny                              │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ No overlap          │ normal cases no box overlap                                           │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Buttons stable      │ buttons stay same row and source order                                │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Translation visible │ overlay shows Vietnamese, not only logs                               │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Fallback safe       │ backend failure still shows OCR source overlay                        │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Logs enough         │ layout logs include source bbox, target bbox, font, lines, fit result │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Existing tests      │ current OCR/overlay tests pass                                        │
├─────────────────────┼───────────────────────────────────────────────────────────────────────┤
│ Manual check        │ sample “Quit Now?” popup renders correctly                            │
└─────────────────────┴───────────────────────────────────────────────────────────────────────┘

Implementation order

1. Add translated block composition, keep existing grouping.
2. Add translated layout function returning DisplayTextBox.
3. Add paint support for wrapped boxes.
4. Move translate before overlay display in capture flow.
5. Keep source overlay fallback.
6. Add sample tests.
7. Run:
  - python -m pytest tests/test_ocr.py
  - python -m pytest tests/test_translation_blocks.py tests/test_app.py
  - manual python -m game_ocr

Best first cut: implement deterministic geometry + wrap + collision. Sau đó tinh chỉnh scoring bằng sample logs.
