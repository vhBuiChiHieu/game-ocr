"""Font discovery, persistence, and runtime selection for overlay rendering.

Fonts dropped into `fonts/` (TTF/OTF/TTC) are registered with Qt at startup.
The active family is persisted to `font-config.json`; UI code reads it via
`active_family()` each paint cycle, so tray menu changes take effect on the
next OCR capture without restarting the app.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from game_ocr.config import PROJECT_ROOT

# Fonts users drop here are picked up at startup.
FONTS_DIR = PROJECT_ROOT / "fonts"
# Persisted active-font selection; absent file means "use default".
FONT_CONFIG_PATH = PROJECT_ROOT / "font-config.json"
DEFAULT_FONT_FAMILY = "Segoe UI"

_SUPPORTED_EXT = {".ttf", ".otf", ".ttc"}

logger = logging.getLogger(__name__)

# Module-level state: paint code reads `_active_family` indirectly through
# `active_family()`. Writes happen on the tray thread (rare, single string
# assignment) so we rely on Python's atomic attribute write semantics here.
_active_family: str = DEFAULT_FONT_FAMILY
_loaded_families: dict[str, str] = {}  # absolute path -> registered family name


def discover_font_files() -> list[Path]:
    """Return font files in `fonts/` sorted by filename."""
    if not FONTS_DIR.exists():
        return []
    return sorted(
        path
        for path in FONTS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in _SUPPORTED_EXT
    )


def load_application_fonts() -> dict[str, str]:
    """Register every font file in `fonts/` with QFontDatabase.

    Must be called after QApplication is created. Returns a mapping of
    absolute path -> family name for the fonts that loaded successfully.
    """
    from PySide6 import QtGui

    global _loaded_families
    mapping: dict[str, str] = {}
    for font_path in discover_font_files():
        font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            logger.warning("Failed to load font file: %s", font_path)
            continue
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            logger.warning("Font file registered but exposed no families: %s", font_path)
            continue
        family = families[0]
        mapping[str(font_path)] = family
        logger.info("Loaded font %s as family %r", font_path.name, family)
    _loaded_families = mapping
    return mapping


def available_families() -> list[str]:
    """Return font families offered in the tray menu.

    Default family is always first; custom families follow in load order,
    deduped so a custom font that happens to be named "Segoe UI" does not
    create a duplicate entry.
    """
    seen: set[str] = {DEFAULT_FONT_FAMILY}
    ordered: list[str] = [DEFAULT_FONT_FAMILY]
    for family in _loaded_families.values():
        if family not in seen:
            ordered.append(family)
            seen.add(family)
    return ordered


def load_selected_font() -> str:
    """Read persisted selection. Unknown/invalid values fall back to default.

    A custom family that is no longer present in `fonts/` falls back to the
    default so the overlay never tries to render with an unregistered family.
    """
    global _active_family
    if not FONT_CONFIG_PATH.exists():
        _active_family = DEFAULT_FONT_FAMILY
        return _active_family
    try:
        data = json.loads(FONT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read font config %s: %r", FONT_CONFIG_PATH, exc)
        _active_family = DEFAULT_FONT_FAMILY
        return _active_family
    family = data.get("family") if isinstance(data, dict) else None
    if not isinstance(family, str) or not family.strip():
        _active_family = DEFAULT_FONT_FAMILY
        return _active_family
    family = family.strip()
    if family != DEFAULT_FONT_FAMILY and family not in available_families():
        logger.warning("Saved font %r is not available; falling back to default.", family)
        _active_family = DEFAULT_FONT_FAMILY
        return _active_family
    _active_family = family
    return _active_family


def save_selected_font(family: str) -> None:
    """Persist selection and update the active family in memory."""
    global _active_family
    _active_family = family
    try:
        FONT_CONFIG_PATH.write_text(
            json.dumps({"family": family}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved active font family: %r", family)
    except OSError as exc:
        logger.warning("Failed to save font config %s: %r", FONT_CONFIG_PATH, exc)


def active_family() -> str:
    """Return the family the overlay should render with right now."""
    return _active_family


def set_active_family(family: str) -> None:
    """Override the active family without touching disk (tests / programmatic)."""
    global _active_family
    _active_family = family
