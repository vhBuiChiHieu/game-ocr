# Development Environment

## Target platform

| Item | Value |
|---|---|
| OS | Windows 11 Pro |
| Run mode | Source code, no packaging |
| Shell used by Claude Code | Bash on Windows |
| Project path | `C:\Users\Admin\Desktop\work\game-ocr` |
| Virtual environment | `.venv` |

## Current system

| Item | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 5060 Ti |
| VRAM | 16311 MB |
| NVIDIA driver | 591.86 |
| CUDA compiler (`nvcc`) | Not installed / not in PATH |

`nvcc` is not required for this project if PaddlePaddle GPU wheel runs correctly. The app uses prebuilt PaddlePaddle GPU binaries.

## Python installations detected

| Version | Path | Notes |
|---|---|---|
| Python 3.13 | `C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe` | Default `python`; avoid for this project |
| Python 3.11 | `C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe` | Available |
| Python 3.10 | `C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe` | Recommended and used |

Use Python 3.10 because PaddlePaddle/PaddleOCR GPU wheels are more reliable there than on Python 3.13.

## Active project venv

| Item | Value |
|---|---|
| Python | 3.10.11 |
| pip | 26.1.1 |
| Location | `.venv` |
| Activate command | `source .venv/Scripts/activate` |

## Installed key packages

| Package | Version / status |
|---|---|
| `paddlepaddle-gpu` | 3.0.0 |
| `paddleocr` | 3.5.0 |
| `PySide6` | 6.11.1 |
| `mss` | 10.2.0 |
| `keyboard` | installed |
| `pyperclip` | 1.11.0 |
| `opencv-python` | 4.10.0 |

## Paddle GPU verification

Current verification result inside `.venv`:

| Check | Result |
|---|---|
| `paddle.device.is_compiled_with_cuda()` | `True` |
| selected device | `gpu:0` |
| GPU count | `1` |

Verification command:

```bash
source .venv/Scripts/activate
python -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); paddle.set_device('gpu:0'); print(paddle.device.get_device()); print(paddle.device.cuda.device_count())"
```

## Recreate environment

From project root:

```bash
py -3.10 -m venv .venv
source .venv/Scripts/activate
python -m pip install -U pip
python -m pip install https://paddle-qa.bj.bcebos.com/paddle-pipeline/Develop-TagBuild-Training-Windows-Gpu-Cuda12.9-Cudnn9.9-Trt10.5-Mkl-Avx-VS2019-SelfBuiltPypiUse/86d658f56ebf3a5a7b2b33ace48f22d10680d311/paddlepaddle_gpu-3.0.0.dev20250717-cp310-cp310-win_amd64.whl
python -m pip install paddleocr PySide6 mss keyboard pyperclip opencv-python
```

## Notes

- App must stay GPU-only for MVP.
- If CUDA support check returns `False`, app should exit with a clear error.
- `ccache` warning from Paddle is non-blocking for normal app use.
- Default system `python` points to Python 3.13, so commands should use `.venv` or `py -3.10` explicitly.
