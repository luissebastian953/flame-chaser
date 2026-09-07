from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_HOME = Path(os.environ.get("REAVER_HOME", "~/.reaver")).expanduser()
SECRET_KEYS = ("pixiv_php_sessid",)
_UNSET = Path("<unset>")  # sentinel: resolved against `home` in __post_init__


@dataclass
class Config:
    home: Path = DEFAULT_HOME
    # resolved against `home` in __post_init__; never None afterwards
    db_path: Path = field(default_factory=lambda: _UNSET)
    blob_root: Path = field(default_factory=lambda: _UNSET)
    pixiv_php_sessid: str | None = None
    pixiv_rate: float = 1.0
    twitter_cookies_file: str | None = None
    twitter_cookies_from_browser: str | None = None
    twitter_timeline_limit: int = 200
    dupe_threshold: int = 6
    include_r18: bool = False
    resolver: str = "system"  # system | doh
    doh_endpoints: list[str] | None = None  # defaults to net.DEFAULT_DOH
    proxy_url: str | None = None  # applied to httpx AND gallery-dl

    def __post_init__(self) -> None:
        self.home = Path(self.home).expanduser()
        self.db_path = (
            self.home / "reaver.db" if self.db_path in (_UNSET, None) else Path(self.db_path)
        ).expanduser()
        self.blob_root = (
            self.home / "blobs" if self.blob_root in (_UNSET, None) else Path(self.blob_root)
        ).expanduser()

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        p = Path(path or DEFAULT_HOME / "config.json").expanduser()
        data: dict = {}
        if p.exists():
            data = json.loads(p.read_text())
        # session cookies live in secrets.json (0600) beside config.json, never
        # inside it -- config.json is the file people paste into bug reports
        sp = p.with_name("secrets.json")
        if sp.exists():
            data.update({k: v for k, v in json.loads(sp.read_text()).items() if k in SECRET_KEYS})
        # env wins -- keeps the session cookie out of any file at all
        if os.environ.get("PIXIV_PHPSESSID"):
            data["pixiv_php_sessid"] = os.environ["PIXIV_PHPSESSID"]
        if os.environ.get("TWITTER_COOKIES"):
            data["twitter_cookies_file"] = os.environ["TWITTER_COOKIES"]
        if os.environ.get("REAVER_PROXY"):
            data["proxy_url"] = os.environ["REAVER_PROXY"]
        if os.environ.get("REAVER_RESOLVER"):
            data["resolver"] = os.environ["REAVER_RESOLVER"]
        return cls(**data)

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path or self.home / "config.json").expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        d = {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(self).items()}
        for k in SECRET_KEYS:
            d.pop(k, None)  # never in config.json -- see save_secrets
        p.write_text(json.dumps(d, indent=2))
        return p

    def save_secrets(self, path: str | Path | None = None) -> Path:
        """Session cookies, owner-readable only. Removing a value removes it
        from the file; an empty file is fine."""
        p = Path(path or self.home / "secrets.json").expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        d = {k: getattr(self, k) for k in SECRET_KEYS if getattr(self, k)}
        p.write_text(json.dumps(d, indent=2))
        os.chmod(p, 0o600)
        return p
