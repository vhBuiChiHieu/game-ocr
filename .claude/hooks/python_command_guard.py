"""PreToolUse guard: force this project's Bash python calls onto .venv/Scripts/python.exe.

Replaces the previous inline `jq` hook so the gate no longer depends on jq being
on PATH (it ships with Git for Windows but is not guaranteed). Reads the tool-call
JSON from stdin, inspects the proposed Bash command, and emits a PreToolUse deny
decision when a bare `python` / `python.exe` is used instead of the venv interpreter.
Anything else prints nothing (empty output = no opinion, command allowed).
"""

import json
import re
import sys

# Bare interpreter at the start of the command: python | python.exe (then space/end).
_BARE_PYTHON = re.compile(r"^python(\.exe)?(\s|$)")
# The sanctioned venv interpreter, optionally prefixed with ./.
_VENV_PYTHON = re.compile(r"^(\./)?\.venv/Scripts/python\.exe(\s|$)")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed input: stay silent so we never block on parser failure.
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0
    command = command.lstrip()

    # Deny only a bare python that is not already the venv interpreter.
    if _BARE_PYTHON.match(command) and not _VENV_PYTHON.match(command):
        decision = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Use .venv/Scripts/python.exe for this project (Python 3.10).",
            }
        }
        json.dump(decision, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
