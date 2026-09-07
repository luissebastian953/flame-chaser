"""Loopback is reachable by any process on the machine, including a browser
tab on a malicious page (DNS rebinding). Three cheap defences:

  1. ephemeral port  -- bound by __main__
  2. per-launch bearer token -- handed to the shell over stdout, never a file
  3. reject foreign Host / Origin -- this is what actually stops rebinding
"""

from __future__ import annotations

import hmac

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# The webview is always a *different* origin from the daemon (tauri://localhost
# on macOS, http://tauri.localhost on Windows), so every request is CORS and
# the browser preflights anything carrying Authorization. We answer CORS
# ourselves -- reflecting only an allowed origin, never "*".
TAURI_ORIGIN_PREFIXES = ("tauri://", "http://tauri.localhost", "https://tauri.localhost")
DEV_ORIGIN_PREFIXES = ("http://localhost:", "http://127.0.0.1:")  # vite, --dev only
ALLOWED_ORIGIN_PREFIXES = TAURI_ORIGIN_PREFIXES + DEV_ORIGIN_PREFIXES


class LoopbackAuth(BaseHTTPMiddleware):
    def __init__(self, app, token: str, port: int, dev: bool = False) -> None:
        super().__init__(app)
        self.token = token
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.dev = dev

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in self.hosts:
            return JSONResponse({"error": {"code": "bad_host", "message": "refused"}}, 421)
        origin = request.headers.get("origin")
        allowed = TAURI_ORIGIN_PREFIXES + (DEV_ORIGIN_PREFIXES if self.dev else ())
        if origin and not origin.startswith(allowed):
            return JSONResponse({"error": {"code": "bad_origin", "message": "refused"}}, 403)
        if request.method == "OPTIONS" and origin:
            # Preflight carries no Authorization by definition; it only learns
            # whether the origin may ask at all. Nothing is served here.
            return Response(status_code=204, headers=self._cors(origin, preflight=True))
        auth = request.headers.get("authorization", "")
        # Neither EventSource nor <img src> can set headers: the token may ride
        # as ?token= on exactly those surfaces -- the event stream and the
        # image routes (media, preview) -- and is ignored everywhere else.
        path = request.url.path
        query_ok = (
            path.endswith("/api/events")
            or path.startswith("/api/media/")
            or path.startswith("/api/preview/")
        )
        qtoken = request.query_params.get("token", "") if query_ok else ""
        presented = auth.removeprefix("Bearer ").strip() or qtoken
        if not hmac.compare_digest(presented, self.token):
            return JSONResponse({"error": {"code": "unauthorized", "message": "bad token"}}, 401)
        response = await call_next(request)
        if origin:
            response.headers.update(self._cors(origin))
        return response

    @staticmethod
    def _cors(origin: str, preflight: bool = False) -> dict[str, str]:
        h = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        if preflight:
            h.update(
                {
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, Last-Event-ID",
                    "Access-Control-Max-Age": "600",
                }
            )
        return h
