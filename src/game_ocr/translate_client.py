from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

TRANSLATE_BASE_URL = "http://127.0.0.1:8765"
TRANSLATE_MODEL = "translategemma:4b"
HEALTH_TIMEOUT_SECONDS = 2.0
STARTUP_TIMEOUT_SECONDS = 10.0
HEALTH_POLL_INTERVAL_SECONDS = 0.25
TRANSLATE_TIMEOUT_SECONDS = 35.0


@dataclass(frozen=True)
class TranslateHealth:
    backend_reachable: bool
    ready: bool
    status: str
    ollama_reachable: bool
    model_ready: bool
    model: str
    reason: str = ""


@dataclass(frozen=True)
class TranslateBackendState:
    ready: bool
    model: str
    reason: str
    process: subprocess.Popen[Any] | None = None

    @property
    def owns_process(self) -> bool:
        return self.process is not None


def check_translate_health(base_url: str = TRANSLATE_BASE_URL, timeout: float = HEALTH_TIMEOUT_SECONDS) -> TranslateHealth:
    request = Request(f"{base_url}/health", method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return TranslateHealth(
            backend_reachable=False,
            ready=False,
            status="unavailable",
            ollama_reachable=False,
            model_ready=False,
            model=TRANSLATE_MODEL,
            reason=str(exc),
        )

    status = str(payload.get("status") or "degraded")
    model = str(payload.get("model") or TRANSLATE_MODEL)
    ollama_reachable = bool(payload.get("ollama_reachable"))
    model_ready = bool(payload.get("model_ready"))
    ready = status == "ok" and ollama_reachable and model_ready
    reason = "" if ready else _health_degraded_reason(status, ollama_reachable, model_ready)
    return TranslateHealth(
        backend_reachable=True,
        ready=ready,
        status=status,
        ollama_reachable=ollama_reachable,
        model_ready=model_ready,
        model=model,
        reason=reason,
    )


def ensure_translate_backend(
    *,
    base_url: str = TRANSLATE_BASE_URL,
    log_path: Path | None = None,
    script_path: Path | None = None,
    python_executable: str | None = None,
    startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    poll_interval: float = HEALTH_POLL_INTERVAL_SECONDS,
    popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> TranslateBackendState:
    health = check_translate_health(base_url)
    if health.ready:
        logger.info("Translate backend already ready: model=%s", health.model)
        return TranslateBackendState(ready=True, model=health.model, reason="reused")
    if health.backend_reachable:
        logger.warning("Translate backend degraded: %s", health.reason)
        return TranslateBackendState(ready=False, model=health.model, reason=health.reason)

    try:
        process = _start_backend_process(
            log_path=log_path,
            script_path=script_path,
            python_executable=python_executable,
            popen_factory=popen_factory,
        )
    except Exception as exc:
        logger.exception("Translate backend spawn failed")
        return TranslateBackendState(ready=False, model=TRANSLATE_MODEL, reason=f"spawn failed: {exc}")

    deadline = monotonic() + startup_timeout
    last_health = health
    while monotonic() < deadline:
        sleep(poll_interval)
        if process.poll() is not None:
            reason = f"backend exited with code {process.returncode}"
            logger.warning("Translate backend unavailable: %s", reason)
            return TranslateBackendState(ready=False, model=TRANSLATE_MODEL, reason=reason, process=process)
        last_health = check_translate_health(base_url)
        if last_health.ready:
            logger.info("Translate backend started: model=%s", last_health.model)
            return TranslateBackendState(ready=True, model=last_health.model, reason="started", process=process)
        if last_health.backend_reachable and not last_health.ready:
            logger.warning("Translate backend started degraded: %s", last_health.reason)
            return TranslateBackendState(ready=False, model=last_health.model, reason=last_health.reason, process=process)

    reason = last_health.reason or "health timeout"
    logger.warning("Translate backend health timeout: %s", reason)
    return TranslateBackendState(ready=False, model=last_health.model, reason=reason, process=process)


def stop_owned_translate_backend(state: TranslateBackendState | None) -> None:
    if state is None or state.process is None:
        return
    process = state.process
    if process.poll() is not None:
        return
    logger.info("Stopping owned translate backend process.")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Translate backend did not terminate; killing owned process.")
        process.kill()
        process.wait(timeout=5)


def translate_text(text: str, source_lang: str = "en", target_lang: str = "vi", base_url: str = TRANSLATE_BASE_URL) -> str:
    payload = {"text": text, "source_lang": source_lang, "target_lang": target_lang}
    request = Request(
        f"{base_url}/v1/translate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TRANSLATE_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"local translate api http error: {exc.code}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise RuntimeError("cannot reach local translate api") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid json from local translate api") from exc

    translated = (body.get("translated_text") or "").strip()
    if not translated:
        raise RuntimeError("empty translated_text from local translate api")
    return translated


def _start_backend_process(
    *,
    log_path: Path | None,
    script_path: Path | None,
    python_executable: str | None,
    popen_factory: Callable[..., subprocess.Popen[Any]],
) -> subprocess.Popen[Any]:
    script = script_path or Path(__file__).resolve().parents[2] / "services" / "translate_api" / "run.py"
    executable = python_executable or sys.executable
    command = [executable, str(script)]
    if log_path is None:
        return popen_factory(command)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        return popen_factory(command, stdout=log_file, stderr=subprocess.STDOUT)


def _health_degraded_reason(status: str, ollama_reachable: bool, model_ready: bool) -> str:
    if not ollama_reachable:
        return "Ollama unavailable"
    if not model_ready:
        return "translate model not ready"
    return f"backend status={status}"
