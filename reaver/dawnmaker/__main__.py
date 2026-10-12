"""dawnmaker entry point: the sidecar the Tauri shell spawns.

    bind 127.0.0.1:0 -> lockfile -> print ONE handshake line -> serve

The token travels over the stdout pipe because that pipe is private to the
parent process -- argv is visible in `ps`, a file is readable by anything.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from coreflame.config import Config
from coreflame.handlers import default_runner

from .app import State, create_app
from .events import EventHub

log = logging.getLogger("dawnmaker")


def _listen(host: str, port: int) -> socket.socket:
    """Bound and listening BEFORE the handshake, then handed to uvicorn: a shell
    that connects the moment it reads the port waits in the backlog instead of
    being refused (binding a free port, closing it and letting uvicorn bind it
    again left a window where /api/health failed and the UI said "unreachable")."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(128)
    return s


def _lock(path: Path, port: int) -> bool:
    """Layer 3: refuse to be the second daemon on this db. Returns False if a
    live daemon already holds the lock (the caller should attach, not spawn)."""
    if path.exists():
        try:
            other = json.loads(path.read_text())
            pid, other_port = int(other["pid"]), int(other["port"])
            # A pid check alone is fooled by pid reuse -- inside a fresh
            # container we ARE pid 9 again, and macOS recycles pids after a
            # reboot. The lock is only live if that pid exists, is not us, and
            # something actually answers on the recorded port.
            if pid != os.getpid():
                os.kill(pid, 0)  # raises if that pid is gone
                with socket.create_connection(("127.0.0.1", other_port), timeout=0.5):
                    return False
        except (OSError, ValueError, KeyError):
            pass  # stale lock
    path.write_text(json.dumps({"pid": os.getpid(), "port": port, "started_at": time.time()}))
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dawnmaker")
    ap.add_argument("--port", type=int, default=0, help="0 = ephemeral")
    ap.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address; anything but loopback needs --dev (container use only)",
    )
    ap.add_argument("--no-heartbeat", action="store_true", help="dev: never self-exit")
    ap.add_argument("--dev", action="store_true", help="allow http://localhost:* origins")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.host not in ("127.0.0.1", "::1", "localhost") and not args.dev:
        ap.error("--host other than loopback requires --dev; the daemon is not a network service")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )  # stdout is the handshake channel

    cfg = Config.load()
    sock = _listen(args.host, args.port)
    port = int(sock.getsockname()[1])
    lock = cfg.home / "dawnmaker.lock"
    cfg.home.mkdir(parents=True, exist_ok=True)
    if not _lock(lock, port):
        sock.close()
        other = json.loads(lock.read_text())
        print(json.dumps({"error": "already_running", **other}), flush=True)
        return 3

    token = secrets.token_urlsafe(32)
    hub = EventHub()
    runner = default_runner(cfg)
    runner.subscribers.append(hub.from_job_event)
    runner.start()
    state = State(cfg, runner, hub, token, port)
    state.heartbeat.enabled = not args.no_heartbeat
    app = create_app(state, dev=args.dev)

    server = uvicorn.Server(
        uvicorn.Config(app, host=args.host, port=port, log_level="warning", access_log=False)
    )

    def watchdog() -> None:
        while not server.should_exit:
            time.sleep(2.0)
            if state.heartbeat.expired():
                log.warning("no heartbeat for %.0fs; exiting", state.heartbeat.timeout)
                server.should_exit = True

    threading.Thread(target=watchdog, name="heartbeat-watchdog", daemon=True).start()

    def stop(*_: object) -> None:
        server.should_exit = True

    signal.signal(signal.SIGTERM, stop)

    # the one line the shell waits for -- exactly one, before anything else on stdout
    print(
        "DAWNMAKER_READY " + json.dumps({"port": port, "token": token, "pid": os.getpid()}),
        flush=True,
    )
    if runner.interrupted:
        log.warning("marked %d job(s) interrupted from a previous run", runner.interrupted)
    try:
        server.run(sockets=[sock])  # the socket the handshake announced, already listening
    finally:
        runner.stop()
        if lock.exists():
            try:
                if json.loads(lock.read_text()).get("pid") == os.getpid():
                    lock.unlink()
            except (OSError, ValueError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
