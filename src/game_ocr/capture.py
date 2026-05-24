from dataclasses import dataclass

import mss
import numpy as np
from PIL import Image

from game_ocr.config import MIN_REGION_SIZE


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    @property
    def is_valid(self) -> bool:
        return self.width >= MIN_REGION_SIZE and self.height >= MIN_REGION_SIZE


def normalize_region(x1: int, y1: int, x2: int, y2: int) -> Region | None:
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)
    region = Region(left, top, width, height)
    return region if region.is_valid else None


def capture_region(region: Region) -> Image.Image:
    monitor = {
        "left": region.left,
        "top": region.top,
        "width": region.width,
        "height": region.height,
    }
    with mss.mss() as screen_capture:
        shot = screen_capture.grab(monitor)
    array = np.array(shot)
    return Image.fromarray(array[:, :, [2, 1, 0]])
