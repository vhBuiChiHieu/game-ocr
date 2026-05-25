import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from game_ocr import translate_client


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


class TranslateClientTests(unittest.TestCase):
    def test_check_translate_health_ready(self) -> None:
        payload = {"status": "ok", "ollama_reachable": True, "model": "translategemma:4b", "model_ready": True}

        with mock.patch.object(translate_client, "urlopen", return_value=FakeResponse(payload)):
            health = translate_client.check_translate_health()

        self.assertTrue(health.backend_reachable)
        self.assertTrue(health.ready)
        self.assertEqual(health.model, "translategemma:4b")

    def test_check_translate_health_unavailable(self) -> None:
        with mock.patch.object(translate_client, "urlopen", side_effect=URLError("down")):
            health = translate_client.check_translate_health()

        self.assertFalse(health.backend_reachable)
        self.assertFalse(health.ready)

    def test_ensure_translate_backend_reuses_ready_backend(self) -> None:
        ready = translate_client.TranslateHealth(True, True, "ok", True, True, "translategemma:4b")

        with (
            mock.patch.object(translate_client, "check_translate_health", return_value=ready),
            mock.patch.object(translate_client.subprocess, "Popen") as popen,
        ):
            state = translate_client.ensure_translate_backend()

        self.assertTrue(state.ready)
        self.assertFalse(state.owns_process)
        popen.assert_not_called()

    def test_ensure_translate_backend_spawns_when_down(self) -> None:
        unavailable = translate_client.TranslateHealth(False, False, "unavailable", False, False, "translategemma:4b", "down")
        ready = translate_client.TranslateHealth(True, True, "ok", True, True, "translategemma:4b")
        process = FakeProcess()

        with mock.patch.object(translate_client, "check_translate_health", side_effect=[unavailable, ready]):
            state = translate_client.ensure_translate_backend(
                popen_factory=mock.Mock(return_value=process),
                sleep=lambda seconds: None,
            )

        self.assertTrue(state.ready)
        self.assertIs(state.process, process)

    def test_ensure_translate_backend_keeps_degraded_backend_external(self) -> None:
        degraded = translate_client.TranslateHealth(True, False, "degraded", True, False, "translategemma:4b", "translate model not ready")

        with (
            mock.patch.object(translate_client, "check_translate_health", return_value=degraded),
            mock.patch.object(translate_client.subprocess, "Popen") as popen,
        ):
            state = translate_client.ensure_translate_backend()

        self.assertFalse(state.ready)
        self.assertFalse(state.owns_process)
        self.assertEqual(state.reason, "translate model not ready")
        popen.assert_not_called()

    def test_stop_owned_translate_backend_terminates_only_owned_process(self) -> None:
        process = FakeProcess()
        state = translate_client.TranslateBackendState(True, "translategemma:4b", "started", process)

        translate_client.stop_owned_translate_backend(state)
        translate_client.stop_owned_translate_backend(None)

        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)

    def test_translate_text_returns_response_text(self) -> None:
        with mock.patch.object(translate_client, "urlopen", return_value=FakeResponse({"translated_text": "Xin chào"})):
            translated = translate_client.translate_text("Hello")

        self.assertEqual(translated, "Xin chào")

    def test_translate_text_wraps_http_error(self) -> None:
        error = HTTPError("http://local", 503, "unavailable", hdrs=None, fp=io.BytesIO())

        with mock.patch.object(translate_client, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "local translate api http error: 503"):
                translate_client.translate_text("Hello")


if __name__ == "__main__":
    unittest.main()
