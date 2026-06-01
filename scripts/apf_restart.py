#!/usr/bin/env python3
"""Cross-platform restart for the apf proxy (apf-d6y).

Mirrors ``scripts/apf_restart.sh`` (which stays as the POSIX-bash
default) so Windows users without WSL2 — or anyone who'd rather have
one script for both — can stop, start, or status-check the proxy
without bash. stdlib-only on purpose; the proxy itself owns httpx,
but a restart script shouldn't drag heavy deps in.

Usage::

    python scripts/apf_restart.py            # restart, wired to oMLX
    python scripts/apf_restart.py stop       # stop, don't relaunch
    python scripts/apf_restart.py status     # show health + pid

Env overrides (identical to the shell script)::

    APF_OPENAI_UPSTREAM  (default http://127.0.0.1:8000 — oMLX)
    APF_PORT             (default 8765)
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DEFAULT_UPSTREAM = "http://127.0.0.1:8000"
DEFAULT_PORT = 8765


def _tmp_dir() -> Path:
    """Persistent-ish temp dir for log + pidfile.

    POSIX: ``/tmp/claude`` (the project convention from CLAUDE.md).
    Windows: ``%TEMP%/claude`` — same naming, native temp root.
    """
    if sys.platform == "win32":
        root = Path(tempfile.gettempdir())
    else:
        root = Path("/tmp")
    p = root / "claude"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _venv_python() -> Path:
    """The repo's .venv python (matches the bash script's $PY)."""
    if sys.platform == "win32":
        return REPO / ".venv" / "Scripts" / "python.exe"
    return REPO / ".venv" / "bin" / "python"


def _port_open(port: int) -> bool:
    """True iff something is currently listening on ``127.0.0.1:port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _healthz(port: int) -> dict | None:
    """Return parsed /healthz JSON if the proxy answers, else None."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=1.0
        ) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"raw": body}
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _kill_pid(pid: int) -> None:
    """Best-effort terminate of a single PID, cross-platform."""
    if sys.platform == "win32":
        # taskkill ships with every supported Windows; /T includes
        # the process tree, /F forces. Suppress its own output.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return


def _stop(port: int, pidfile: Path) -> None:
    """Bring any running apf instance down. Idempotent."""
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            _kill_pid(pid)
        except (ValueError, OSError):
            pass
    # POSIX fallback: pkill catches strays the pidfile lost (e.g.
    # crashed parent). On Windows we rely on the pidfile + port
    # check; taskkill on the whole tree already covers most cases.
    if sys.platform != "win32" and shutil.which("pkill"):
        subprocess.run(
            ["pkill", "-f", r"apf\.proxy"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    for _ in range(30):
        if not _port_open(port):
            return
        time.sleep(0.2)
    print(f"warning: port {port} still bound after kill", file=sys.stderr)


def _status(port: int, pidfile: Path) -> int:
    """Print one-line status + healthz body. Returns shell exit code."""
    info = _healthz(port)
    pid = pidfile.read_text().strip() if pidfile.exists() else "?"
    if info is not None:
        print(f"apf: UP on :{port}  (pid {pid})")
        print(json.dumps(info))
        return 0
    print(f"apf: DOWN on :{port}")
    return 1


def _start(
    port: int, upstream: str, pidfile: Path, log_path: Path
) -> int:
    """Launch the proxy detached; wait for /healthz to answer."""
    env = os.environ.copy()
    env["APF_OPENAI_UPSTREAM"] = upstream
    env["APF_PORT"] = str(port)

    log_fh = log_path.open("ab")
    py = _venv_python()
    cmd = [str(py), "-m", "apf.proxy"]
    if sys.platform == "win32":
        # DETACHED_PROCESS so closing the parent shell doesn't reap it.
        # CREATE_NEW_PROCESS_GROUP makes the child its own ctrl-C target.
        flags = (
            subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        proc = subprocess.Popen(
            cmd,
            cwd=REPO,
            env=env,
            stdout=log_fh,
            stderr=log_fh,
            creationflags=flags,
            close_fds=True,
        )
    else:
        # start_new_session is the modern replacement for the old
        # double-fork + setsid + nohup dance. Proxy becomes its own
        # process group; the parent (this script) can exit cleanly.
        proc = subprocess.Popen(
            cmd,
            cwd=REPO,
            env=env,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
            close_fds=True,
        )
    pidfile.write_text(str(proc.pid))

    # MLX detector cold-load can be > 60s under memory pressure;
    # mirror the bash script's 180s budget. Polling cost is trivial.
    for _ in range(360):
        info = _healthz(port)
        if info is not None:
            print(
                f"apf up on :{port} (pid {proc.pid}) — "
                f"OpenAI upstream: {upstream}"
            )
            print(json.dumps(info))
            return 0
        time.sleep(0.5)

    print("apf did NOT come up within 180s. Last log lines:", file=sys.stderr)
    try:
        tail = log_path.read_text("utf-8", errors="replace").splitlines()[-25:]
    except OSError:
        tail = []
    for line in tail:
        print(line, file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else "restart"
    if action not in ("restart", "stop", "status"):
        print(f"usage: {argv[0]} [restart|stop|status]", file=sys.stderr)
        return 2

    port = int(os.environ.get("APF_PORT", str(DEFAULT_PORT)))
    upstream = os.environ.get("APF_OPENAI_UPSTREAM", DEFAULT_UPSTREAM)
    tmp = _tmp_dir()
    pidfile = tmp / "apf.pid"
    log_path = tmp / "apf.log"

    if action == "status":
        return _status(port, pidfile)
    if action == "stop":
        _stop(port, pidfile)
        print("apf stopped.")
        return 0

    _stop(port, pidfile)
    return _start(port, upstream, pidfile, log_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
