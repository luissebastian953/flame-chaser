"""Source sessions. Curio never sees a password: the shell opens the site's
own login page in a second window and reads the resulting cookie, or the user
pastes one. This module stores, verifies and revokes what arrives.

pixiv   PHPSESSID           verified with one search request (the endpoint
                            the crawl actually needs; 401 = not signed in)
X       auth_token + ct0    written as a Netscape cookies.txt for gallery-dl;
                            no cheap verification exists without a request
                            that costs a timeline fetch, so "stored" is honest
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from coreflame.config import Config
from coreflame.handlers import make_pixiv

log = logging.getLogger("dawnmaker.auth")

PIXIV_SESSID = re.compile(r"^\d+_[A-Za-z0-9]{20,}$")
X_TOKEN = re.compile(r"^[A-Za-z0-9]{20,}$")
VERIFY_TAG = "オリジナル"  # always non-empty, safe mode
VERIFY_TTL = 3600.0


@dataclass
class PixivStatus:
    authed: bool
    user_id: str | None
    verified: bool | None  # None = not checked yet
    checked_at: float | None
    error: str | None


class Auth:
    def __init__(self, cfg: Config, verify_on_start: bool = True) -> None:
        self.cfg = cfg
        sessid = cfg.pixiv_php_sessid
        if sessid and not PIXIV_SESSID.match(sessid):
            # a placeholder in .env must not read as "connected"
            log.warning("PIXIV_PHPSESSID is not a session cookie; ignoring it")
            cfg.pixiv_php_sessid = sessid = None
            self._pixiv = PixivStatus(
                False, None, False, time.time(), "stored value is not a PHPSESSID"
            )
        else:
            self._pixiv = PixivStatus(bool(sessid), self._uid(sessid), None, None, None)
        if sessid and verify_on_start:
            # one search request, off the startup path: the rail shows
            # "unverified" until it lands, "expired" if it fails
            threading.Thread(target=self.verify_pixiv, name="pixiv-verify", daemon=True).start()

    @staticmethod
    def _uid(sessid: str | None) -> str | None:
        return (sessid or "").split("_")[0] or None

    # -- pixiv -----------------------------------------------------------
    def pixiv_status(self) -> PixivStatus:
        return self._pixiv

    def verify_pixiv(self) -> PixivStatus:
        """One search request with the current session. This is the request
        the crawl needs, so its verdict is the one that matters."""
        sessid = self.cfg.pixiv_php_sessid
        if not sessid:
            self._pixiv = PixivStatus(False, None, False, time.time(), "not signed in")
            return self._pixiv
        px = make_pixiv(self.cfg)
        try:
            px.probe_tag(VERIFY_TAG)
            self._pixiv = PixivStatus(True, self._uid(sessid), True, time.time(), None)
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            msg = "session expired or invalid" if code in (401, 403) else f"pixiv HTTP {code}"
            self._pixiv = PixivStatus(True, self._uid(sessid), False, time.time(), msg)
        except Exception as e:
            # network trouble is not an auth verdict; keep the last one
            self._pixiv = PixivStatus(
                True,
                self._uid(sessid),
                self._pixiv.verified,
                time.time(),
                f"unreachable: {e}"[:160],
            )
        finally:
            px.close()
        return self._pixiv

    def set_pixiv(self, sessid: str) -> PixivStatus:
        sessid = sessid.strip()
        if sessid.lower().startswith("phpsessid="):
            sessid = sessid.split("=", 1)[1]
        if not PIXIV_SESSID.match(sessid):
            raise ValueError("that is not a PHPSESSID (expected <userid>_<token>)")
        previous = self.cfg.pixiv_php_sessid
        self.cfg.pixiv_php_sessid = sessid
        st = self.verify_pixiv()
        if st.verified is False:
            self.cfg.pixiv_php_sessid = previous  # keep whatever worked before
            self._pixiv = PixivStatus(bool(previous), self._uid(previous), None, None, st.error)
            raise PermissionError(st.error or "session rejected")
        self.cfg.save_secrets()
        return st

    def clear_pixiv(self) -> None:
        self.cfg.pixiv_php_sessid = None
        self.cfg.save_secrets()
        self._pixiv = PixivStatus(False, None, None, None, None)

    # -- X ----------------------------------------------------------------
    def twitter_cookies_path(self) -> Path:
        return self.cfg.home / "twitter-cookies.txt"

    def set_twitter(self, auth_token: str, ct0: str) -> Path:
        auth_token, ct0 = auth_token.strip(), ct0.strip()
        if not X_TOKEN.match(auth_token) or not X_TOKEN.match(ct0):
            raise ValueError("auth_token and ct0 look wrong (expected long alphanumeric values)")
        p = self.twitter_cookies_path()
        exp = int(time.time()) + 365 * 86400
        lines = ["# Netscape HTTP Cookie File", "# written by dawnmaker -- do not share"]
        for domain in (".x.com", ".twitter.com"):
            lines.append(f"{domain}\tTRUE\t/\tTRUE\t{exp}\tauth_token\t{auth_token}")
            lines.append(f"{domain}\tTRUE\t/\tTRUE\t{exp}\tct0\t{ct0}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n")
        os.chmod(p, 0o600)
        self.cfg.twitter_cookies_file = str(p)
        self.cfg.twitter_cookies_from_browser = None
        self.cfg.save()
        return p

    def clear_twitter(self) -> None:
        p = self.twitter_cookies_path()
        if self.cfg.twitter_cookies_file == str(p) and p.exists():
            p.unlink()
        self.cfg.twitter_cookies_file = None
        self.cfg.save()

    def twitter_status(self) -> dict:
        import shutil

        f = self.cfg.twitter_cookies_file
        return {
            "authed": bool(f and Path(f).exists()) or bool(self.cfg.twitter_cookies_from_browser),
            "gallery_dl": shutil.which("gallery-dl") is not None,
            "cookies_file": bool(f),
            "from_browser": self.cfg.twitter_cookies_from_browser,
        }
