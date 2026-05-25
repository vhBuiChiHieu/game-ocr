import logging

from game_ocr.config import CANCEL_MESSAGE, NO_TEXT_MESSAGE, SUCCESS_PREFIX

logger = logging.getLogger(__name__)


def show_success(text: str) -> None:
    logger.info("%s %s", SUCCESS_PREFIX, text)


def show_no_text() -> None:
    logger.info("%s", NO_TEXT_MESSAGE)


def show_cancel() -> None:
    logger.info("%s", CANCEL_MESSAGE)


def show_error(message: str) -> None:
    logger.error("OCR error: %s", message)
