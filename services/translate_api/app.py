from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
MODEL_NAME = "translategemma:4b"
OLLAMA_TIMEOUT_SECONDS = 30

app = FastAPI(title="OCR Local Translate API", version="0.1.0")


@dataclass
class TranslateConfig:
    model: str = MODEL_NAME
    ollama_base_url: str = OLLAMA_BASE_URL
    timeout_seconds: int = OLLAMA_TIMEOUT_SECONDS


CONFIG = TranslateConfig()


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1)
    source_lang: str = Field(default="en", min_length=2, max_length=16)
    target_lang: str = Field(default="vi", min_length=2, max_length=16)


class TranslateResponse(BaseModel):
    translated_text: str
    source_lang: str
    target_lang: str
    model: str
    latency_ms: int


LANGUAGE_NAMES = {
    "en": "English",
    "vi": "Vietnamese",
}


def _build_prompt(text: str, source_lang: str, target_lang: str) -> str:
    source_code = source_lang.strip()
    target_code = target_lang.strip()
    source_name = LANGUAGE_NAMES.get(source_code.lower(), source_code)
    target_name = LANGUAGE_NAMES.get(target_code.lower(), target_code)
    return (
        f"You are a professional {source_name} ({source_code}) to {target_name} ({target_code}) translator specializing in video game UI text, menus, dialogue. "
        f"Translate using terminology natural to gamers (e.g. Quit/Exit, Save, Confirm, Cancel), preserving in-game tone and concise UI phrasing. "
        f"Your goal is to accurately convey the meaning and nuances of the original {source_name} text while adhering to {target_name} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {target_name} translation, without any additional explanations or commentary. "
        f"Please translate the following {source_name} game text into {target_name}:\n\n"
        f"{text}"
    )


def _ollama_chat(prompt: str) -> str:
    body = {
        "model": CONFIG.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0},
    }
    request = Request(
        f"{CONFIG.ollama_base_url}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=CONFIG.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Ollama HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=503, detail="Cannot reach Ollama on localhost:11434") from exc

    message = payload.get("message") or {}
    translated = (message.get("content") or "").strip()
    if not translated:
        raise HTTPException(status_code=502, detail="Empty response from model")
    return translated


@app.get("/health")
def health() -> dict[str, object]:
    request = Request(f"{CONFIG.ollama_base_url}/api/tags", method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return {"status": "degraded", "ollama_reachable": False, "model": CONFIG.model, "model_ready": False}

    models = payload.get("models") or []
    model_names = {item.get("name") for item in models if isinstance(item, dict)}
    return {
        "status": "ok" if CONFIG.model in model_names else "degraded",
        "ollama_reachable": True,
        "model": CONFIG.model,
        "model_ready": CONFIG.model in model_names,
    }


@app.post("/v1/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    start = time.perf_counter()
    prompt = _build_prompt(req.text, req.source_lang, req.target_lang)
    translated = _ollama_chat(prompt)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return TranslateResponse(
        translated_text=translated,
        source_lang=req.source_lang,
        target_lang=req.target_lang,
        model=CONFIG.model,
        latency_ms=latency_ms,
    )
