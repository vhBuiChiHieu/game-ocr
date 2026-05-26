# Game OCR

Tiện ích OCR theo vùng màn hình dành cho Windows, tối ưu cho việc đọc text trong game. Nhấn hotkey, kéo chọn vùng cần đọc, kết quả OCR được sao chép vào clipboard và hiển thị overlay (kèm bản dịch tiếng Việt nếu bật backend dịch cục bộ).

- **OCR engine**: PaddleOCR 3.5 (GPU-only, không có CPU fallback).
- **Dịch**: backend FastAPI cục bộ gọi Ollama (`translategemma:4b`) → tiếng Việt.
- **UI**: PySide6 (overlay drag-select + overlay kết quả) + tray icon (pystray).
- **Hotkey mặc định**: `alt+shift+z`.

## Yêu cầu hệ thống

| Mục | Yêu cầu |
|---|---|
| OS | Windows 10/11 |
| Python | 3.10 (bắt buộc, không hỗ trợ 3.11+) |
| GPU | NVIDIA với CUDA (PaddlePaddle GPU build phải nhận được CUDA) |
| RAM | ≥ 8 GB khuyến nghị |
| Disk | ~5–10 GB cho PaddleOCR models + Ollama model |

> Kiểm tra Python: `python --version`. Nếu mặc định là 3.13, cài thêm 3.10 và dùng đúng binary đó cho venv.

## Cài đặt

### 1. Clone & tạo virtualenv Python 3.10

```powershell
git clone <repo-url> game-ocr
cd game-ocr

# Tạo venv bằng Python 3.10 (không dùng python mặc định nếu là 3.13)
py -3.10 -m venv .venv

# Kích hoạt venv
.\.venv\Scripts\Activate.ps1
# Hoặc trên Git Bash:
# source .venv/Scripts/activate
```

Xác nhận đang dùng đúng venv:

```powershell
python --version          # phải in: Python 3.10.x
where.exe python          # phải trỏ về .venv\Scripts\python.exe
```

### 2. Cài PaddlePaddle GPU

PaddleOCR cần `paddlepaddle-gpu` build khớp với CUDA driver của máy. Cài **trước** khi cài project deps để pip không kéo nhầm bản CPU.

Chọn build theo CUDA của máy (xem `nvidia-smi` để biết CUDA driver version). Ví dụ với CUDA 11.8:

```powershell
python -m pip install --upgrade pip
python -m pip install paddlepaddle-gpu==2.6.1 -f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html
```

> Tham khảo lệnh cài chính thức tại trang Paddle theo CUDA version của máy: <https://www.paddlepaddle.org.cn/install/quick>.

Kiểm tra GPU sẵn sàng:

```powershell
python -c "import paddle; print(paddle.device.is_compiled_with_cuda())"
# Phải in: True
```

Nếu in `False`, app sẽ thoát với thông báo `GPU OCR requires PaddlePaddle with CUDA support...`.

> Warning `ccache` từ Paddle là **không chặn**, có thể bỏ qua.

### 3. Cài project dependencies

```powershell
python -m pip install -e ".[dev]"
```

Lệnh này cài tất cả runtime deps khai báo trong `pyproject.toml`:

| Nhóm | Package |
|---|---|
| OCR | `paddleocr>=3.5.0` |
| UI | `PySide6>=6.11.1`, `pystray>=0.19` |
| Capture/IO | `mss>=10.2.0`, `opencv-python>=4.10.0`, `Pillow`, `numpy` |
| Hotkey/Clipboard | `keyboard`, `pyperclip>=1.11.0` |
| Translate backend | `fastapi>=0.115`, `uvicorn>=0.32`, `pydantic>=2.10` |
| Dev | `pytest>=8` |

Compile-check toàn bộ codebase để xác minh:

```powershell
python -m compileall src tests services scripts
```

### 4. Cài Ollama + model dịch

App vẫn chạy OCR mà không cần Ollama; chỉ tính năng dịch yêu cầu Ollama.

#### 4.1. Cài Ollama

Tải installer Windows: <https://ollama.com/download>. Sau khi cài, Ollama tự chạy daemon ở `http://127.0.0.1:11434`.

Kiểm tra:

```powershell
ollama --version
curl http://127.0.0.1:11434/api/tags
```

#### 4.2. Kéo model `translategemma:4b`

App mặc định gọi model tên `translategemma:4b` (khai báo trong `services/translate_api/app.py`, biến `MODEL_NAME`).

```powershell
ollama pull translategemma:4b
ollama list   # xác nhận model có trong danh sách
```

> Nếu muốn đổi model khác, sửa `MODEL_NAME` trong `services/translate_api/app.py`. Model nên hỗ trợ dịch EN→VI tốt.

### 5. Chạy translate backend (tùy chọn)

Backend FastAPI lắng nghe `127.0.0.1:8765` và làm proxy có prompt sang Ollama.

```powershell
.\.venv\Scripts\python.exe services\translate_api\run.py
```

Kiểm tra health:

```powershell
curl http://127.0.0.1:8765/health
# {"status":"ok","ollama_reachable":true,"model":"translategemma:4b","model_ready":true}
```

> App game-ocr sẽ tự khởi động backend này khi bật chế độ Translator API trong tray menu (xem `src/game_ocr/translate_client.py`). Chạy thủ công chỉ cần thiết khi debug riêng phần dịch.

### 6. Cấu hình OCR (tùy chọn)

File `ocr-config.json` ở thư mục gốc override các tham số `PaddleOCR(...)`. Giá trị `null` được bỏ qua (giữ default của PaddleOCR). Mặc định:

```json
{
  "lang": "en",
  "use_doc_orientation_classify": false,
  "use_doc_unwarping": false,
  "use_textline_orientation": false,
  "return_word_box": true
}
```

Chỉ thêm key đã được whitelist trong `src/game_ocr/ocr_config.py`; key lạ sẽ làm app fail fast khi khởi động.

## Chạy app

```powershell
python -m game_ocr
```

Khi chạy:

1. Parent process spawn child detached (`GAME_OCR_DETACHED=1`) rồi return — terminal không bị treo.
2. Child preload PaddleOCR (lần đầu sẽ tải models, mất vài chục giây), bật log ngày `logs/YYYY-MM-DD.log`.
3. Tray icon xuất hiện. Nhấn `alt+shift+z` → kéo vùng → OCR → clipboard + overlay.
4. Tray → **Exit** để thoát.

## Test

```powershell
python -m pytest                                          # full suite
python -m pytest tests\test_ocr.py                        # OCR parsing + overlay layout
python -m pytest tests\test_main.py tests\test_app.py     # launcher + app lifecycle
python -m pytest tests\test_translate_client.py tests\test_translation_blocks.py
```

`tests/test_ocr_image_samples.py` chạy OCR thật trên ảnh mẫu trong `tests/imgs/` và ghi log chi tiết; dùng cho tuning, không thuộc fast path.

## Troubleshooting

| Triệu chứng | Nguyên nhân / Cách xử lý |
|---|---|
| `GPU OCR requires PaddlePaddle with CUDA support` | `paddlepaddle-gpu` chưa cài, hoặc cài nhầm bản CPU. Cài lại bước 2, kiểm tra `paddle.device.is_compiled_with_cuda()`. |
| App im lặng không có tray | Kiểm tra `logs/YYYY-MM-DD.log`. Thường do PaddleOCR model lần đầu tải lâu, hoặc lỗi import. |
| Hotkey không phản hồi | Một số app chạy bằng admin sẽ block hotkey toàn cục. Chạy terminal với quyền admin. |
| Translate trả `degraded` / `ollama_reachable: false` | Ollama daemon chưa chạy. Mở Ollama hoặc `ollama serve`. |
| Translate trả `model_ready: false` | Chưa `ollama pull translategemma:4b`. Pull rồi restart backend. |
| Cài `python -m pip install -e .` báo Python version | Dùng nhầm Python 3.11+/3.13. Kích hoạt lại `.venv` Python 3.10. |

## Cấu trúc thư mục

```
game-ocr/
├── src/game_ocr/            # App chính (entrypoint, OCR, UI overlay, tray, hotkey)
├── services/translate_api/  # FastAPI backend dịch (proxy → Ollama)
├── scripts/trans-api/       # CLI client cho translate backend
├── tests/                   # pytest suite + ảnh mẫu OCR
├── ocr-config.json          # Override PaddleOCR runtime params
├── pyproject.toml           # Build + dependencies
└── logs/                    # Daily logs (sinh ra khi chạy)
```

Tham khảo thêm: `CLAUDE.md` (notes chi tiết cho contributor).
