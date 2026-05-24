import sys
import types
import unittest
from unittest import mock

from game_ocr.app import require_gpu
from game_ocr.config import GPU_REQUIRED_ERROR


class FakeDevice:
    def __init__(self, compiled_with_cuda: bool) -> None:
        self.compiled_with_cuda = compiled_with_cuda
        self.selected: str | None = None

    def is_compiled_with_cuda(self) -> bool:
        return self.compiled_with_cuda

    def set_device(self, device: str) -> None:
        self.selected = device

    def get_device(self) -> str:
        return self.selected or "cpu"


def install_fake_paddle(compiled_with_cuda: bool) -> FakeDevice:
    device = FakeDevice(compiled_with_cuda)
    fake_paddle = types.SimpleNamespace(device=device, set_device=device.set_device)
    sys.modules["paddle"] = fake_paddle
    return device


class AppTests(unittest.TestCase):
    def test_require_gpu_rejects_non_cuda_paddle(self) -> None:
        with mock.patch.dict(sys.modules):
            install_fake_paddle(compiled_with_cuda=False)
            with self.assertRaisesRegex(RuntimeError, GPU_REQUIRED_ERROR):
                require_gpu()

    def test_require_gpu_selects_gpu_zero(self) -> None:
        with mock.patch.dict(sys.modules):
            install_fake_paddle(compiled_with_cuda=True)
            status = require_gpu()

        self.assertEqual(status.device, "gpu:0")


if __name__ == "__main__":
    unittest.main()
