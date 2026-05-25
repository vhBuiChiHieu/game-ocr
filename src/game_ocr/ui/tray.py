from __future__ import annotations

from collections.abc import Callable
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


def start_tray_icon(on_exit: Callable[[], None]) -> TrayIcon:
    icon = pystray.Icon(
        "game-ocr",
        _create_icon_image(),
        "Game OCR",
        pystray.Menu(pystray.MenuItem("Exit", lambda _icon, _item: on_exit())),
    )
    thread = Thread(target=icon.run, name="game-ocr-tray", daemon=True)
    thread.start()
    return TrayIcon(icon=icon, thread=thread)


def _create_icon_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (24, 24, 28, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 54, 54), outline=(80, 180, 255, 255), width=5)
    draw.rectangle((20, 28, 44, 36), fill=(255, 255, 255, 255))
    return image
