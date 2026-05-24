from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import keyboard

from game_ocr.config import HOTKEY


@dataclass
class HotkeyRegistration:
    handle: Any

    def unregister(self) -> None:
        keyboard.remove_hotkey(self.handle)


def register_capture_hotkey(callback: Callable[[], None]) -> HotkeyRegistration:
    handle = keyboard.add_hotkey(HOTKEY, callback)
    return HotkeyRegistration(handle)
