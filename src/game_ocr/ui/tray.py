from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import Thread

from PIL import Image, ImageDraw
import pystray


@dataclass
class TrayIcon:
    icon: pystray.Icon
    thread: Thread

    def stop(self) -> None:
        self.icon.stop()
        if self.thread.is_alive():
            self.thread.join(timeout=2)


def start_tray_icon(
    on_exit: Callable[[], None],
    *,
    font_families: Sequence[str] = (),
    current_font: Callable[[], str] | None = None,
    on_font_selected: Callable[[str], None] | None = None,
) -> TrayIcon:
    """Start the tray icon.

    When `font_families`, `current_font`, and `on_font_selected` are all
    provided, a "Font" submenu is built with one radio item per family.
    Selecting an item invokes `on_font_selected(family)` so the caller can
    persist it; the checkmark re-reads `current_font()` whenever the menu
    is opened.
    """
    menu_items: list[pystray.MenuItem] = []
    if font_families and current_font is not None and on_font_selected is not None:
        font_items = tuple(
            pystray.MenuItem(
                family,
                _make_font_handler(family, on_font_selected),
                checked=_make_font_checked(family, current_font),
                radio=True,
            )
            for family in font_families
        )
        menu_items.append(pystray.MenuItem("Font", pystray.Menu(*font_items)))
    menu_items.append(pystray.MenuItem("Exit", lambda _icon, _item: on_exit()))

    icon = pystray.Icon(
        "game-ocr",
        _create_icon_image(),
        "Game OCR",
        pystray.Menu(*menu_items),
    )
    thread = Thread(target=icon.run, name="game-ocr-tray", daemon=True)
    thread.start()
    return TrayIcon(icon=icon, thread=thread)


def _make_font_handler(
    family: str,
    on_font_selected: Callable[[str], None],
) -> Callable[[pystray.Icon, pystray.MenuItem], None]:
    def handler(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        on_font_selected(family)
        # Refresh radio checkmarks immediately after selection.
        icon.update_menu()

    return handler


def _make_font_checked(
    family: str,
    current_font: Callable[[], str],
) -> Callable[[pystray.MenuItem], bool]:
    def checked(_item: pystray.MenuItem) -> bool:
        return current_font() == family

    return checked


def _create_icon_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (24, 24, 28, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 54, 54), outline=(80, 180, 255, 255), width=5)
    draw.rectangle((20, 28, 44, 36), fill=(255, 255, 255, 255))
    return image
