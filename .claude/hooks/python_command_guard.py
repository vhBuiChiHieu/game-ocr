"""PreToolUse guard: force this project's Bash python calls onto .venv/Scripts/python.exe.

Replaces the previous inline `jq` hook so the gate no longer depends on jq being
on PATH (it ships with Git for Windows but is not guaranteed). Reads the tool-call
JSON from stdin, inspects the proposed Bash command, and emits a PreToolUse deny
decision when a bare `python` / `python3` / `python.exe` is used instead of the venv
interpreter. Anything else prints nothing (empty output = no opinion, allowed).

The guard inspects every COMMAND-START position, not just the start of the whole
string, so compound commands like `ls; python ...`, `cd x && python ...`, or
`foo | python ...` cannot smuggle a bare interpreter past the gate. Leading env-var
assignments (`VAR=val python ...`) are skipped so they don't shield the interpreter
either. The command is tokenized with `shlex` (quote-aware), so a bare `python`
appearing INSIDE a quoted string — e.g. a `git commit -m "...python..."` message or
an `echo "python"` argument — is correctly treated as data, not an invocation.
"""

import json
import re
import shlex
import sys

# Bare interpreter token: python | python3 | python.exe | python3.exe.
_BARE_PYTHON = re.compile(r"^python(3)?(\.exe)?$")
# The sanctioned venv interpreter, optionally prefixed with ./.
_VENV_PYTHON = re.compile(r"^(\./)?\.venv/Scripts/python\.exe$")
# A leading env-var assignment (VAR=value) that precedes the real command word.
_ENV_ASSIGN = re.compile(r"^\w+=")
# Shell operators that begin a fresh command. Passed to shlex so they tokenize alone.
_PUNCTUATION = "();<>|&"
# Semicolon is a command separator too; shlex omits it from the default set, so add it.
_PUNCTUATION += ";"


def _invokes_bare_python(command: str) -> bool:
    """True when any command-start position invokes a bare (non-venv) python."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        # Unbalanced quotes etc.: can't reason about it, stay silent (don't block).
        return False

    at_command_start = True
    punct_set = set(_PUNCTUATION) | {";"}
    for token in tokens:
        # An operator token (e.g. ;, &&, |, () resets us to a fresh command start.
        if token and all(ch in punct_set for ch in token):
            at_command_start = True
            continue
        if not at_command_start:
            continue
        # Leading `VAR=val` assignments stay in command-start position.
        if _ENV_ASSIGN.match(token):
            continue
        # First real word of a command: this is the interpreter being invoked.
        if _BARE_PYTHON.match(token) and not _VENV_PYTHON.match(token):
            return True
        at_command_start = False
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed input: stay silent so we never block on parser failure.
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0

    # Deny if any command-start position invokes a bare (non-venv) python.
    if _invokes_bare_python(command):
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
