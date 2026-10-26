"""Network signal: how fast the line is right now, and what it is.

The rail's signal card and its detail modal. One measurement is a handful of
requests to Cloudflare's speed-test host (the same thing speed.cloudflare.com
does in a browser): a few empty downloads for latency, a time-boxed download
stream, optionally a time-boxed upload stream, and `/cdn-cgi/trace` for the
edge location and the public IP. Everything goes through the configured
resolver and proxy, so the number is the path pixiv and X requests take.

Bandwidth is the cost: a download probe moves `seconds` × line rate. The
card's background probe is kept short (`LIGHT_SECONDS`) and the long one
(`FULL_SECONDS`, with upload) runs only when the modal asks.

The local side -- Wi-Fi or Ethernet, the SSID -- comes from the OS's own
tools (`route`/`networksetup`/`ipconfig` on macOS, `ip`/`nmcli` on Linux,
`netsh` on Windows), parsed here. Any of them missing means "unknown", never
an error: the card still shows the speed.
"""

from __future__ import annotations

import logging
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Config

log = logging.getLogger(__name__)

SPEED_HOST = "https://speed.cloudflare.com"
DOWN_URL = f"{SPEED_HOST}/__down"
UP_URL = f"{SPEED_HOST}/__up"
TRACE_URL = f"{SPEED_HOST}/cdn-cgi/trace"
#: ISP and ASN for the public IP; keyless, answered once per IP (dawnmaker caches)
ISP_URL = "https://ipinfo.io/json"

LIGHT_SECONDS = 1.5  # the card's 30 s cadence: latency + a short download
FULL_SECONDS = 3.0  # the modal: download, then upload
UPLOAD_SECONDS = 2.0
LATENCY_PROBES = 3
DOWN_BYTES = (
    50_000_000  # the largest the server allows (100 MB is 403); the clock stops the stream first
)
CHUNK = 64 * 1024
TIMEOUT = 10.0
USER_AGENT = "Curio (speed probe)"

#: Cloudflare colo (IATA) → the city, for "Server Singapore"
COLO_NAMES = {
    "SIN": "Singapore",
    "CGK": "Jakarta",
    "KUL": "Kuala Lumpur",
    "BKK": "Bangkok",
    "MNL": "Manila",
    "HKG": "Hong Kong",
    "TPE": "Taipei",
    "NRT": "Tokyo",
    "HND": "Tokyo",
    "KIX": "Osaka",
    "ICN": "Seoul",
    "SYD": "Sydney",
    "MEL": "Melbourne",
    "AKL": "Auckland",
    "BOM": "Mumbai",
    "MAA": "Chennai",
    "DEL": "Delhi",
    "DXB": "Dubai",
    "FRA": "Frankfurt",
    "AMS": "Amsterdam",
    "LHR": "London",
    "CDG": "Paris",
    "MAD": "Madrid",
    "MXP": "Milan",
    "WAW": "Warsaw",
    "STO": "Stockholm",
    "ARN": "Stockholm",
    "LAX": "Los Angeles",
    "SJC": "San Jose",
    "SEA": "Seattle",
    "ORD": "Chicago",
    "DFW": "Dallas",
    "IAD": "Ashburn",
    "EWR": "Newark",
    "MIA": "Miami",
    "YYZ": "Toronto",
    "YVR": "Vancouver",
    "GRU": "São Paulo",
    "EZE": "Buenos Aires",
    "JNB": "Johannesburg",
}

Clock = Callable[[], float]
OnSample = Callable[[str, float], None]
#: ("latency_ms" | "download_mbps" | "upload_mbps", value) as each leg finishes
OnLeg = Callable[[str, float], None]


@dataclass
class Measurement:
    measured_at: float  # unix seconds
    online: bool
    latency_ms: float | None = None
    download_mbps: float | None = None
    upload_mbps: float | None = None
    download_samples: list[float] = field(default_factory=list)  # ~1 s each, in order
    upload_samples: list[float] = field(default_factory=list)
    colo: str | None = None
    client_ip: str | None = None
    error: str | None = None

    @property
    def location(self) -> str | None:
        return COLO_NAMES.get(self.colo, self.colo) if self.colo else None

    @property
    def ip_version(self) -> str | None:
        if not self.client_ip:
            return None
        return "IPv6" if ":" in self.client_ip else "IPv4"


@dataclass
class Connection:
    interface: str | None = None  # wifi | ethernet | other | None (unknown)
    ssid: str | None = None


def make_client(cfg: Config) -> httpx.Client:
    """No rate limit (one short burst per measurement), the configured
    resolver and proxy, TLS verified -- as every client here."""
    transport = None
    if cfg.resolver == "doh" and not cfg.proxy_url:
        from .net import DEFAULT_DOH, DohResolver, DohTransport

        transport = DohTransport(DohResolver(cfg.doh_endpoints or DEFAULT_DOH))
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
        follow_redirects=False,
        http2=False,
        transport=transport,
        proxy=cfg.proxy_url,
    )


def _mbps(nbytes: int, seconds: float) -> float:
    return nbytes * 8 / 1_000_000 / max(seconds, 1e-6)


def latency(client: httpx.Client, clock: Clock = time.perf_counter) -> float:
    """Median round trip of a few empty downloads, in ms."""
    took: list[float] = []
    for _ in range(LATENCY_PROBES):
        t0 = clock()
        client.get(DOWN_URL, params={"bytes": 0}).raise_for_status()
        took.append((clock() - t0) * 1000)
    return statistics.median(took)


def download(
    client: httpx.Client,
    seconds: float,
    clock: Clock = time.perf_counter,
    on_sample: OnSample | None = None,
) -> tuple[float, list[float]]:
    """Stream until `seconds` pass (or the server's cap). Returns the overall
    Mbps and one Mbps per elapsed second, reported as each lands."""
    samples: list[float] = []
    total = win = 0
    with client.stream("GET", DOWN_URL, params={"bytes": DOWN_BYTES}) as r:
        r.raise_for_status()
        t0 = last = clock()
        for chunk in r.iter_bytes(CHUNK):
            total += len(chunk)
            win += len(chunk)
            now = clock()
            if now - last >= 1.0:
                samples.append(_mbps(win, now - last))
                if on_sample:
                    on_sample("download", samples[-1])
                win, last = 0, now
            if now - t0 >= seconds:
                break
        elapsed = clock() - t0
    overall = _mbps(total, elapsed)
    if not samples:  # done inside the first second: the whole run is the one sample
        samples.append(overall)
        if on_sample:
            on_sample("download", overall)
    return overall, samples


def upload(
    client: httpx.Client,
    seconds: float,
    clock: Clock = time.perf_counter,
    on_sample: OnSample | None = None,
) -> tuple[float, list[float]]:
    """POST a stream of zeros for `seconds`; the pace the socket accepts them
    is the upload rate. Same per-second samples as `download`."""
    samples: list[float] = []
    chunk = b"\0" * CHUNK
    box: dict[str, Any] = {"total": 0, "t0": None}

    def body() -> Iterator[bytes]:
        win = 0
        box["t0"] = last = clock()
        while True:
            yield chunk
            box["total"] += len(chunk)
            win += len(chunk)
            now = clock()
            if now - last >= 1.0:
                samples.append(_mbps(win, now - last))
                if on_sample:
                    on_sample("upload", samples[-1])
                win, last = 0, now
            if now - box["t0"] >= seconds:
                return

    client.post(UP_URL, content=body()).raise_for_status()
    elapsed = clock() - (box["t0"] if box["t0"] is not None else clock())
    overall = _mbps(box["total"], elapsed)
    if not samples:
        samples.append(overall)
        if on_sample:
            on_sample("upload", overall)
    return overall, samples


def parse_trace(text: str) -> dict[str, str]:
    """`/cdn-cgi/trace`: `key=value` lines."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def parse_org(org: str | None) -> tuple[str | None, str | None]:
    """ipinfo's `org`: "AS4761 INDOSAT Internet Network Provider" → (ASN, name)."""
    if not org:
        return None, None
    m = re.match(r"(AS\d+)\s*(.*)", org.strip())
    if not m:
        return None, org.strip() or None
    return m.group(1), m.group(2).strip() or None


def isp_lookup(client: httpx.Client) -> tuple[str | None, str | None]:
    """(ASN, ISP name) for the public IP, or (None, None)."""
    try:
        r = client.get(ISP_URL, headers={"Accept": "application/json"})
        r.raise_for_status()
        return parse_org(r.json().get("org"))
    except (httpx.HTTPError, ValueError):
        return None, None


def _short(e: Exception) -> str:
    """One line for the modal: httpx appends a docs link after "For more information"."""
    text = str(e).split(" For more information", 1)[0]
    return f"{type(e).__name__}: {text}"[:160]


def measure(
    client: httpx.Client,
    full: bool = False,
    clock: Clock = time.perf_counter,
    on_sample: OnSample | None = None,
    now: Callable[[], float] = time.time,
    on_leg: OnLeg | None = None,
) -> Measurement:
    """One run. Latency failing means offline; a later step failing keeps
    what came before and names the failure. `on_leg` hears each figure the
    moment it is known, so a watcher need not wait for the whole run."""
    m = Measurement(measured_at=now(), online=False)
    leg = on_leg or (lambda _k, _v: None)
    try:
        m.latency_ms = latency(client, clock)
    except httpx.HTTPError as e:
        m.error = _short(e)
        return m
    leg("latency_ms", m.latency_ms)
    m.online = True
    try:
        m.download_mbps, m.download_samples = download(
            client, FULL_SECONDS if full else LIGHT_SECONDS, clock, on_sample
        )
        leg("download_mbps", m.download_mbps)
        if full:
            m.upload_mbps, m.upload_samples = upload(client, UPLOAD_SECONDS, clock, on_sample)
            leg("upload_mbps", m.upload_mbps)
    except httpx.HTTPError as e:
        m.error = _short(e)
    try:
        trace = parse_trace(client.get(TRACE_URL).text)
        m.colo = trace.get("colo") or None
        m.client_ip = trace.get("ip") or None
    except httpx.HTTPError:
        pass
    return m


# ---------------------------------------------------------------- local side
Runner = Callable[[list[str]], str]


def _run(args: list[str]) -> str:
    """stdout of an OS tool, or "" when it is missing, fails or hangs."""
    try:
        # S603/S607: fixed argv (no user input, no shell), resolved on PATH on
        # purpose -- the tools live in different places per OS release.
        p = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout


def parse_mac_route(out: str) -> str | None:
    m = re.search(r"^\s*interface:\s*(\S+)", out, re.M)
    return m.group(1) if m else None


def parse_mac_ports(out: str) -> dict[str, str]:
    """`networksetup -listallhardwareports` → {device: hardware port name}."""
    ports: dict[str, str] = {}
    name = None
    for line in out.splitlines():
        if line.startswith("Hardware Port:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and name:
            ports[line.split(":", 1)[1].strip()] = name
            name = None
    return ports


def parse_mac_ssid(out: str) -> str | None:
    """`ipconfig getsummary en0` ("  SSID : name") or
    `networksetup -getairportnetwork en0` ("Current Wi-Fi Network: name")."""
    m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out, re.M) or re.search(
        r"Current Wi-Fi Network:\s*(.+?)\s*$", out, re.M
    )
    name = m.group(1) if m else None
    # macOS 14+ prints the literal "<redacted>" unless the caller has Location
    # Services permission, which a background daemon does not: unknown, not a name
    return None if not name or name.startswith("<") else name


def parse_linux_route(out: str) -> str | None:
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else None


def parse_nmcli(out: str) -> str | None:
    """`nmcli -t -f active,ssid dev wifi`: the `yes:` line."""
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:].strip() or None
    return None


def parse_netsh(out: str) -> str | None:
    """`netsh wlan show interfaces`: the SSID of a connected adapter."""
    if not re.search(r"^\s*State\s*:\s*connected", out, re.M | re.I):
        return None
    m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out, re.M)
    return m.group(1) if m else None


def _kind(port: str | None, dev: str | None) -> str | None:
    text = f"{port or ''} {dev or ''}".lower()
    if any(w in text for w in ("wi-fi", "wifi", "wlan", "airport", "wl")):
        return "wifi"
    if any(w in text for w in ("ethernet", "lan", "eth", "en", "thunderbolt")):
        return "ethernet"
    return "other" if (port or dev) else None


def local_connection(run: Runner = _run, platform: str = sys.platform) -> Connection:
    """Best effort, never raises. Unknown fields stay None."""
    try:
        if platform == "darwin":
            dev = parse_mac_route(run(["route", "-n", "get", "default"]))
            if not dev:
                return Connection()
            port = parse_mac_ports(run(["networksetup", "-listallhardwareports"])).get(dev)
            kind = _kind(port, dev)
            ssid = None
            if kind == "wifi":
                ssid = parse_mac_ssid(run(["ipconfig", "getsummary", dev])) or parse_mac_ssid(
                    run(["networksetup", "-getairportnetwork", dev])
                )
            return Connection(kind, ssid)
        if platform.startswith("linux"):
            dev = parse_linux_route(run(["ip", "route", "show", "default"]))
            if not dev:
                return Connection()
            ssid = parse_nmcli(run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]))
            kind = "wifi" if ssid else _kind(None, dev)
            return Connection(kind, ssid)
        if platform.startswith("win"):
            ssid = parse_netsh(run(["netsh", "wlan", "show", "interfaces"]))
            return Connection("wifi" if ssid else None, ssid)
    except Exception:
        log.debug(
            "local connection lookup failed", exc_info=True
        )  # the card must not fail over an OS tool
    return Connection()


def connection_dict(c: Connection) -> dict[str, Any]:
    return {"interface": c.interface, "ssid": c.ssid}


def to_json(m: Measurement) -> dict[str, Any]:
    return {
        "measured_at": m.measured_at,
        "online": m.online,
        "latency_ms": m.latency_ms,
        "download_mbps": m.download_mbps,
        "upload_mbps": m.upload_mbps,
        "server": {"colo": m.colo, "location": m.location, "ip_version": m.ip_version},
        "error": m.error,
    }


__all__ = [
    "Connection",
    "Measurement",
    "connection_dict",
    "download",
    "isp_lookup",
    "latency",
    "local_connection",
    "make_client",
    "measure",
    "parse_org",
    "parse_trace",
    "to_json",
    "upload",
]
