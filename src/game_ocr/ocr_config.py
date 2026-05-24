from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from game_ocr.config import OCR_CONFIG_PATH, OCR_LANGUAGE

_ALLOWED_KEYS = {
    "doc_orientation_classify_model_name",
    "doc_orientation_classify_model_dir",
    "doc_unwarping_model_name",
    "doc_unwarping_model_dir",
    "text_detection_model_name",
    "text_detection_model_dir",
    "textline_orientation_model_name",
    "textline_orientation_model_dir",
    "textline_orientation_batch_size",
    "text_recognition_model_name",
    "text_recognition_model_dir",
    "text_recognition_batch_size",
    "use_doc_orientation_classify",
    "use_doc_unwarping",
    "use_textline_orientation",
    "text_det_limit_side_len",
    "text_det_limit_type",
    "text_det_thresh",
    "text_det_box_thresh",
    "text_det_unclip_ratio",
    "text_rec_score_thresh",
    "return_word_box",
    "lang",
    "ocr_version",
}


def load_ocr_config(path: Path = OCR_CONFIG_PATH) -> dict[str, Any]:
    config: dict[str, Any] = {"lang": OCR_LANGUAGE}
    if not path.exists():
        return config

    with path.open("r", encoding="utf-8") as config_file:
        raw_config = json.load(config_file)
    if not isinstance(raw_config, dict):
        raise ValueError(f"OCR config must be a JSON object: {path}")

    for key, value in raw_config.items():
        if key not in _ALLOWED_KEYS:
            raise ValueError(f"Unsupported OCR config key: {key}")
        if value is not None:
            config[key] = value
    return config
