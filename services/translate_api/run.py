from pathlib import Path
import sys

from uvicorn import run

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.translate_api.app import app


if __name__ == "__main__":
    run(app, host="127.0.0.1", port=8765, reload=False)
