"""Backwards-compatible facade.

Overlay logic split into three modules under ``game_ocr.ui``:
- ``layout_source``: source-text overlay layout (lines/groups/fonts/gaps).
- ``layout_translated``: translated overlay layout + collision resolver.
- ``widgets``: Qt dialogs ``SelectionOverlay`` and ``ResultOverlay``.

This shim re-exports the public surface so existing imports
(``from game_ocr.ui.overlay import ...``) keep working.
"""

from __future__ import annotations

from game_ocr.ui.layout_source import DisplayLine, layout_lines_for_display
from game_ocr.ui.layout_translated import (
    DisplayTextBox,
    layout_translated_blocks_for_display,
)
from game_ocr.ui.widgets import ResultOverlay, SelectionOverlay

__all__ = [
    "DisplayLine",
    "DisplayTextBox",
    "ResultOverlay",
    "SelectionOverlay",
    "layout_lines_for_display",
    "layout_translated_blocks_for_display",
]
