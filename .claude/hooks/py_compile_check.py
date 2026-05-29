"""PostToolUse hook: fast syntax-check edited Python files.

Reads the hook JSON payload from stdin, extracts the edited file path, and if it
is a .py file runs `py_compile`. On failure, emits a PostToolUse JSON result so
the compile error is fed back to the model as additional context. No external
deps (no jq) — uses the project interpreter that runs this script.
"""
import json
import os
import subprocess
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed/empty payload -> do nothing

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return 0

    # Use the same interpreter running this hook (the project .venv python).
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", file_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "py_compile failed").strip()
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": f"py_compile failed for {file_path}:\n{message}",
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
