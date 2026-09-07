"""Network path: resolve around DNS interference, and say which layer blocks.

pixiv is among the sites Indonesian ISPs interfere with. They do not use one
technique -- DNS hijacking, SNI filtering, DPI, TCP resets, and increasingly
blocking third-party resolvers -- so this module is two independent layers
plus a diagnostic that tells you which one you need:

  layer 1  DoH resolver inside the HTTP client   -> defeats DNS hijacking
  layer 2  a proxy (configured elsewhere)        -> the only thing that
                                                     survives SNI/DPI

TLS verification is never disabled. At least one Indonesian ISP has been seen
attempting HTTPS interception with a spoofed certificate; a validation failure
is evidence of an active MITM, and `verify=False` would convert a failed
interception into a successful one -- handing over PHPSESSID and auth_token.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import ssl
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import httpcore
import httpx
from httpcore._backends.sync import SyncBackend

log = logging.getLogger(__name__)

#: IP-addressed endpoints: no bootstrap dependency on the (possibly hijacked)
#: system resolver. Both operators put the IP in the certificate's SANs, so
#: verification against the literal address passes.
DEFAULT_DOH = (
    "https://1.1.1.1/dns-query",
    "https://8.8.8.8/resolve",
)


def is_bogus(ip: str) -> bool:
    """A resolver answer that is interference, not an answer."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        a.is_unspecified
        or a.is_loopback
        or a.is_private
        or a.is_link_local
        or a.is_reserved
        or a.is_multicast
    )


class ResolveError(RuntimeError):
    pass


class DohResolver:
    """DNS-over-HTTPS with a TTL cache and bogus-answer rejection."""

    def __init__(
        self,
        endpoints: Iterable[str] = DEFAULT_DOH,
        timeout: float = 4.0,
        ttl_floor: int = 60,
        ttl_ceiling: int = 3600,
    ) -> None:
        self.endpoints = list(endpoints)
        self.ttl_floor, self.ttl_ceiling = ttl_floor, ttl_ceiling
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        # a plain client: these URLs are IPs, so no resolver is involved
        self._client = httpx.Client(timeout=timeout, headers={"accept": "application/dns-json"})

    def resolve(self, host: str) -> str:
        try:
            ipaddress.ip_address(host)
            return host  # already an IP
        except ValueError:
            pass
        with self._lock:
            hit = self._cache.get(host)
            if hit and hit[1] > time.monotonic():
                return hit[0]
        last: Exception | None = None
        for ep in self.endpoints:
            try:
                ip, ttl = self._query(ep, host)
            except Exception as e:  # try the next endpoint
                last = e
                log.debug("DoH %s failed for %s: %s", ep, host, e)
                continue
            if is_bogus(ip):
                # a DoH answer should never be a block page; if it is, the
                # resolver itself is compromised or the name is junk
                last = ResolveError(f"{ep} answered {ip} for {host}")
                continue
            ttl = max(self.ttl_floor, min(self.ttl_ceiling, ttl))
            with self._lock:
                self._cache[host] = (ip, time.monotonic() + ttl)
            return ip
        raise ResolveError(f"no DoH endpoint could resolve {host}: {last}")

    def _query(self, endpoint: str, host: str) -> tuple[str, int]:
        r = self._client.get(endpoint, params={"name": host, "type": "A"})
        r.raise_for_status()
        data = json.loads(r.text)
        if data.get("Status", 0) != 0:
            raise ResolveError(f"DNS status {data.get('Status')}")
        answers = [a for a in data.get("Answer", []) if a.get("type") == 1]
        if not answers:
            raise ResolveError("no A records")
        a = answers[0]
        return str(a["data"]), int(a.get("TTL", self.ttl_floor))

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


class DohBackend(SyncBackend):
    """httpcore backend that resolves through DoH and dials the IP.

    httpcore calls `connect_tcp(host=origin.host)` and later
    `start_tls(server_hostname=origin.host)`; only the first is overridden, so
    SNI and certificate validation still target the real hostname.
    """

    def __init__(self, resolver: DohResolver) -> None:
        self.resolver = resolver

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ip = self.resolver.resolve(host)
        return super().connect_tcp(ip, port, timeout, local_address, socket_options)


class DohTransport(httpx.HTTPTransport):
    """`httpx.HTTPTransport` whose connections resolve via DoH.

    `verify` is accepted only as True or an SSL context -- False is refused.
    """

    def __init__(
        self,
        resolver: DohResolver,
        *,
        verify=True,
        retries: int = 0,
        limits: httpx.Limits | None = None,
        **kw,
    ) -> None:
        if verify is False:
            raise ValueError("TLS verification cannot be disabled (see net.py)")
        limits = limits or httpx.Limits()
        super().__init__(verify=verify, retries=retries, limits=limits, **kw)
        ssl_context = httpx.create_ssl_context(verify=verify)
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            retries=retries,
            network_backend=DohBackend(resolver),
        )


# ---------------------------------------------------------------- diagnosis
Verdict = (
    str  # ok | dns_hijack | resolver_blocked | ip_blackhole | sni_dpi | interception | unknown
)


@dataclass
class Diagnosis:
    host: str
    port: int
    system_ip: str | None = None
    doh_ip: str | None = None
    tcp_ok: bool | None = None
    tls_ok: bool | None = None
    verdict: Verdict = "unknown"
    steps: list[str] = field(default_factory=list)

    @property
    def advice(self) -> str:
        return {
            "ok": "no interference detected on this path",
            "dns_hijack": "system DNS is lying; enable the DoH resolver",
            "resolver_blocked": "third-party DNS is blocked too; a proxy is required",
            "ip_blackhole": "the real IP is unreachable; a proxy or tunnel is required",
            "sni_dpi": "the TLS handshake is being reset -- SNI/DPI filtering; "
            "DNS changes will not help, a proxy or tunnel is required",
            "interception": "CERTIFICATE DOES NOT VALIDATE -- the connection is "
            "being intercepted. Do not proceed. Never disable "
            "verification.",
        }.get(self.verdict, "inconclusive")


def _system_resolve(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        return str(infos[0][4][0]) if infos else None  # sockaddr[0] is str for AF_INET
    except socket.gaierror:
        return None


def _tcp(ip: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True, "open"
    except TimeoutError:
        return False, "timeout"
    except OSError as e:
        return False, type(e).__name__


def _tls(ip: str, host: str, port: int, timeout: float) -> tuple[bool | None, str]:
    ctx = ssl.create_default_context()
    try:
        with (
            socket.create_connection((ip, port), timeout=timeout) as raw,
            ctx.wrap_socket(raw, server_hostname=host) as s,
        ):
            return True, f"ok ({s.version()})"
    except ssl.SSLCertVerificationError as e:
        return None, f"cert: {e.reason or e}"  # None = interception
    except (ConnectionResetError, ssl.SSLEOFError, ssl.SSLZeroReturnError) as e:
        return False, f"reset: {type(e).__name__}"
    except TimeoutError:
        return False, "handshake timeout"
    except ssl.SSLError as e:
        return False, f"ssl: {e.reason or e}"
    except OSError as e:
        return False, type(e).__name__


def diagnose(
    host: str,
    port: int = 443,
    resolver: DohResolver | None = None,
    timeout: float = 5.0,
    *,
    _system=_system_resolve,
    _tcp=_tcp,
    _tls=_tls,
) -> Diagnosis:
    """Four steps, stop at the first that fails, name the layer.

    step 1 vs step 2 disagreeing is the clean signature of DNS hijacking, and
    the only way to know DoH will be enough before turning it on.
    """
    d = Diagnosis(host=host, port=port)
    resolver = resolver or DohResolver()

    d.system_ip = _system(host)
    sys_bogus = d.system_ip is None or is_bogus(d.system_ip)
    d.steps.append(
        f"1 system DNS  -> {d.system_ip or 'NXDOMAIN'}"
        + ("  (block page / bogus)" if sys_bogus else "")
    )

    try:
        d.doh_ip = resolver.resolve(host)
        d.steps.append(f"2 DoH         -> {d.doh_ip}")
    except Exception as e:
        d.steps.append(f"2 DoH         -> unreachable ({e})")

    if d.doh_ip is None and sys_bogus:
        d.verdict = "resolver_blocked"
        return d

    target = d.doh_ip or d.system_ip
    assert target
    if d.doh_ip and sys_bogus:
        d.steps.append("   system and DoH disagree -> DNS hijack")
    elif d.doh_ip and d.system_ip and d.doh_ip != d.system_ip:
        d.steps.append("   system and DoH differ (may be geo-DNS; testing the DoH answer)")

    d.tcp_ok, note = _tcp(target, port, timeout)
    d.steps.append(f"3 TCP {target}:{port} -> {note}")
    if not d.tcp_ok:
        d.verdict = "ip_blackhole"
        return d

    d.tls_ok, note = _tls(target, host, port, timeout)
    d.steps.append(f"4 TLS SNI={host} -> {note}")
    if d.tls_ok is None:
        d.verdict = "interception"
    elif not d.tls_ok:
        d.verdict = "sni_dpi"
    elif sys_bogus:
        d.verdict = "dns_hijack"  # everything works once DNS is honest
    else:
        d.verdict = "ok"
    return d
