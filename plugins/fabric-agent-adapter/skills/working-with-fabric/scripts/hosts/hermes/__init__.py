# #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
"""Hermes native, session-frozen Fabric context; no model or lifecycle worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import threading
import time
from collections.abc import Mapping

MAX_CONTEXT_CHARS = 4000
TIMEOUT_SECONDS = 4
MAX_OUTPUT_BYTES = 16000
MAX_INPUT_BYTES = 4096


def _kill_owned(process):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass


def _capture(command, payload):
    """Bound output while reading, not after buffering a noisy helper's entire stdout."""
    if len(payload) > MAX_INPUT_BYTES:
        return None
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=os.name == "posix")
    output = bytearray()
    invalid = threading.Event()
    deadline = time.monotonic() + TIMEOUT_SECONDS

    def read_output():
        try:
            while True:
                chunk = process.stdout.read(min(1024, MAX_OUTPUT_BYTES + 1 - len(output)))
                if not chunk:
                    return
                output.extend(chunk)
                if len(output) > MAX_OUTPUT_BYTES:
                    invalid.set()
                    _kill_owned(process)
                    return
        except (OSError, ValueError):
            invalid.set()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        process.stdin.write(payload)
        process.stdin.close()
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        reader.join(timeout=max(0, deadline - time.monotonic()))
        if reader.is_alive() or invalid.is_set() or process.returncode != 0:
            return None
        return bytes(output)
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        # Own process group only: also close a pipe inherited by an owned child.
        _kill_owned(process)
        process.wait()
        reader.join(timeout=0.2)
        if not reader.is_alive():
            process.stdout.close()
        process.stdin.close()


def fabric_registered(config=None):
    """Read only the native registration flag; never forward server config or credentials."""
    try:
        if config is None:
            from hermes_cli.config import load_config_readonly
            config = load_config_readonly()
        servers = config.get("mcp_servers") if isinstance(config, Mapping) else None
        server = servers.get("fabric") if isinstance(servers, Mapping) else None
        if not isinstance(server, Mapping):
            return False
        enabled = server.get("enabled", True)
        return enabled is True or isinstance(enabled, str) and enabled.lower().strip() in ("true", "1", "yes", "on")
    except (ImportError, OSError, TypeError, ValueError):
        return False


def context_for_session(session_info, session_script=None):
    """Read the shared preamble through its bounded plain-text host protocol."""
    if not isinstance(session_info, Mapping):
        return ""
    cwd = session_info.get("cwd", "")
    if not isinstance(cwd, str) or len(cwd) > MAX_INPUT_BYTES // 2 or "\x00" in cwd:
        return ""
    try:
        if session_script is None:
            script = Path(__file__).resolve().parents[2] / "fabric_session.py"
        elif isinstance(session_script, str) and Path(session_script).is_absolute():
            script = Path(session_script)
        else:
            return ""
        if not script.is_file():
            return ""
        result = _capture(
            [sys.executable, "-S", str(script), "hook", "session-start", "--host", "hermes"],
            json.dumps({"cwd": cwd or os.getcwd(), "fabric_registered": fabric_registered()},
                       ensure_ascii=False).encode("utf-8"),
        )
        if result is None:
            return ""
        text = result.decode("utf-8").strip()
        if len(text) > MAX_CONTEXT_CHARS or any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            return ""
        return text
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Context is best effort; never leak configuration, diagnostics or hook input.
        return ""


def register(ctx):
    """Use Hermes' cache-safe prompt section API, not observer hook returns."""
    if not callable(getattr(ctx, "register_system_prompt_section", None)):
        return
    try:
        script = ctx.get_config("session_script", None)
    except (AttributeError, OSError, TypeError, ValueError):
        return
    ctx.register_system_prompt_section(
        "fabric.context", lambda info: context_for_session(info, script),
        position="after_memory", max_chars=MAX_CONTEXT_CHARS,
    )
# #endregion native-host-context
