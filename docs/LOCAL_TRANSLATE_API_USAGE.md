# Local Translate API + Gemma 4B Translator

## 1. Cách code để start local translate API

Mục tiêu backend: tạo HTTP service local ở `http://127.0.0.1:8765`, nhận text cần dịch qua `POST /v1/translate`, gọi Ollama local ở `http://127.0.0.1:11434/api/chat`, rồi trả JSON chuẩn cho translator script.

Cài dependency tối thiểu:

```bash
pip install fastapi uvicorn pydantic
```

Tạo file backend, ví dụ `services/translate_api/app.py`:

```python
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

app = FastAPI(title="OCR Local Translate API", version="0.2.0")


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
        f"You are a professional {source_name} ({source_code}) to {target_name} ({target_code}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {source_name} text while adhering to {target_name} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {target_name} translation, without any additional explanations or commentary. "
        f"Please translate the following {source_name} text into {target_name}:\n\n\n"
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
```

Tạo file runner, ví dụ `services/translate_api/run.py`:

```python
from pathlib import Path
import sys

from uvicorn import run

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.translate_api.app import app


if __name__ == "__main__":
    run(app, host="127.0.0.1", port=8765, reload=False)
```

Flow backend cần dựng lại:

```text
client -> POST /v1/translate
       -> validate JSON bằng Pydantic
       -> build prompt dịch en -> vi
       -> POST http://127.0.0.1:11434/api/chat
       -> đọc payload["message"]["content"]
       -> trả { translated_text, source_lang, target_lang, model, latency_ms }
```

Request JSON backend nhận:

```json
{
  "text": "Hello",
  "source_lang": "en",
  "target_lang": "vi"
}
```

Response JSON backend trả:

```json
{
  "translated_text": "Xin chào",
  "source_lang": "en",
  "target_lang": "vi",
  "model": "translategemma:4b",
  "latency_ms": 1234
}
```

Chạy service:

```bash
.venv/Scripts/python.exe services/translate_api/run.py
```

Kiểm tra health:

```bash
curl http://127.0.0.1:8765/health
```

Test dịch:

```bash
curl -X POST http://127.0.0.1:8765/v1/translate -H "Content-Type: application/json" -d "{\"text\":\"Hello\\nHow are you?\",\"source_lang\":\"en\",\"target_lang\":\"vi\"}"
```

## 2. Cách sử dụng `local_translate_gemma_4b.py` khi đã có file này

File translator nằm tại:

```text
scripts/trans-api/local_translate_gemma_4b.py
```

Điều kiện trước khi dùng:

1. Ollama đang chạy.
2. Model `translategemma:4b` đã có trong Ollama.
3. Local translate API đã chạy ở `http://127.0.0.1:8765`.

Chạy thử translator script trực tiếp:

```bash
.venv/Scripts/python.exe scripts/trans-api/local_translate_gemma_4b.py "Hello world" --sl en --tl vi
```

Với text có xuống dòng, truyền newline dưới dạng chuỗi `\n`:

```bash
.venv/Scripts/python.exe scripts/trans-api/local_translate_gemma_4b.py "Hello\nHow are you?" --sl en --tl vi
```

Trong app OCR, chọn translator qua tray menu:

```text
Translator API -> local_translate_gemma_4b.py
```

Sau khi chọn, app lưu setting vào:

```text
config/settings.json
```

Khi output mode là `Translate` hoặc `Both`, app sẽ gọi `local_translate_gemma_4b.py` qua subprocess. Script gửi JSON tới local API `/v1/translate`, nhận `translated_text`, rồi trả text dịch về app để hiển thị trên result overlay.
