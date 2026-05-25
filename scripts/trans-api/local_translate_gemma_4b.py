import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OLLAMA_API_URL = "http://127.0.0.1:8765/v1/translate"


def translate_text(text: str, sl: str = "en", tl: str = "vi") -> str:
    payload = {
        "text": text,
        "source_lang": sl,
        "target_lang": tl,
    }
    request = Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=35) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"local translate api http error: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("cannot reach local translate api") from exc

    translated = (body.get("translated_text") or "").strip()
    if not translated:
        raise RuntimeError("empty translated_text from local translate api")
    return translated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="Text to translate")
    parser.add_argument("--sl", default="en", help="Source language, default: en")
    parser.add_argument("--tl", default="vi", help="Target language, default: vi")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    text = args.text.replace("\\n", "\n")
    print(translate_text(text, sl=args.sl, tl=args.tl))


if __name__ == "__main__":
    main()
