from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OCR_CONFIG_PATH = PROJECT_ROOT / "ocr-config.json"
HOTKEY = "alt+shift+z"
OCR_LANGUAGE = "en"
MIN_REGION_SIZE = 5
GPU_REQUIRED_ERROR = "GPU OCR requires PaddlePaddle with CUDA support. Install paddlepaddle-gpu and run again."
SUCCESS_PREFIX = "OCR copied to clipboard:"
NO_TEXT_MESSAGE = "No text detected."
CANCEL_MESSAGE = "OCR selection canceled."
