from game_ocr.config import CANCEL_MESSAGE, NO_TEXT_MESSAGE, SUCCESS_PREFIX


def show_success(text: str) -> None:
    print(f"{SUCCESS_PREFIX} {text}")


def show_no_text() -> None:
    print(NO_TEXT_MESSAGE)


def show_cancel() -> None:
    print(CANCEL_MESSAGE)


def show_error(message: str) -> None:
    print(f"OCR error: {message}")
