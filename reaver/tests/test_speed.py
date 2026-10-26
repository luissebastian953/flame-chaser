"""The network signal: measurement over a fake transport, the OS parsers, the meter. Offline."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from coreflame import speed
from coreflame.config import Config

TRACE = "fl=1\nh=speed.cloudflare.com\nip=114.12.3.184\ncolo=SIN\nloc=ID\n"


class Tick:
    """A clock that moves `step` seconds per look."""

    def __init__(self, step: float) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def fake_transport(down_bytes: int = 4 * speed.CHUNK * 10, offline: bool = False):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if offline:
            raise httpx.ConnectError("no route", request=request)
        if request.url.path == "/__down":
            n = int(request.url.params.get("bytes", "0"))
            return httpx.Response(200, content=b"\0" * min(n, down_bytes))
        if request.url.path == "/__up":
            request.read()  # consume the stream, as the server would
            return httpx.Response(200)
        if request.url.path == "/cdn-cgi/trace":
            return httpx.Response(200, text=TRACE)
        if request.url.host == "ipinfo.io":
            return httpx.Response(200, json={"org": "AS4761 INDOSAT Internet Network Provider"})
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def test_measure_light_and_full() -> None:
    transport, calls = fake_transport()
    client = httpx.Client(transport=transport)
    seen: list[tuple[str, float]] = []
    # 0.25 s per look: latency = 3 probes × 2 looks → 250 ms each; the download
    # loop looks once per 64 KB chunk → a sample every 4 chunks
    m = speed.measure(
        client, full=False, clock=Tick(0.25), on_sample=lambda k, v: seen.append((k, v))
    )
    assert m.online and m.error is None
    assert m.latency_ms == 250
    assert m.download_mbps and m.download_mbps > 0
    assert len(m.download_samples) >= 1 and all(s > 0 for s in m.download_samples)
    assert [k for k, _ in seen] == ["download"] * len(seen)
    assert m.upload_mbps is None and m.upload_samples == []
    assert m.colo == "SIN" and m.location == "Singapore"
    assert m.client_ip == "114.12.3.184" and m.ip_version == "IPv4"
    assert calls.count("GET /__down") == speed.LATENCY_PROBES + 1
    assert "POST /__up" not in calls

    seen.clear()
    m = speed.measure(
        client, full=True, clock=Tick(0.25), on_sample=lambda k, v: seen.append((k, v))
    )
    assert m.upload_mbps and m.upload_mbps > 0 and len(m.upload_samples) >= 1
    assert "POST /__up" in calls
    assert {k for k, _ in seen} == {"download", "upload"}
    print("  measure:              ok (latency, download tape, upload only when full, trace)")


def test_measure_offline() -> None:
    transport, _ = fake_transport(offline=True)
    m = speed.measure(httpx.Client(transport=transport))
    assert not m.online and m.latency_ms is None and m.download_mbps is None
    assert m.error and "ConnectError" in m.error

    class Forbidden(httpx.HTTPError):
        pass

    assert speed._short(
        Forbidden("Client error '403' for url 'x' For more information check: https://d")
    ) == ("Forbidden: Client error '403' for url 'x'")
    assert speed.to_json(m)["server"] == {"colo": None, "location": None, "ip_version": None}
    print("  offline:              ok (latency fails → offline, error named)")


def test_parsers() -> None:
    assert speed.parse_trace(TRACE)["colo"] == "SIN"
    assert speed.parse_org("AS4761 INDOSAT Internet Network Provider") == (
        "AS4761",
        "INDOSAT Internet Network Provider",
    )
    assert speed.parse_org("Some ISP") == (None, "Some ISP")
    assert speed.parse_org(None) == (None, None)
    assert speed.Measurement(0, True, client_ip="2001:db8::1").ip_version == "IPv6"
    assert speed.Measurement(0, True, colo="XYZ").location == "XYZ"

    assert speed.parse_mac_route("   route to: default\n  interface: en0\n") == "en0"
    ports = speed.parse_mac_ports(
        "Hardware Port: Wi-Fi\nDevice: en0\nEthernet Address: aa\n\n"
        "Hardware Port: Thunderbolt Ethernet\nDevice: en5\n"
    )
    assert ports == {"en0": "Wi-Fi", "en5": "Thunderbolt Ethernet"}
    assert speed.parse_mac_ssid("  SSID : Curio-5G\n  Security : WPA2\n") == "Curio-5G"
    assert speed.parse_mac_ssid("Current Wi-Fi Network: Curio-5G\n") == "Curio-5G"
    assert speed.parse_mac_ssid("You are not associated with an AirPort network.\n") is None
    assert (
        speed.parse_mac_ssid("  BSSID : <redacted>\n  SSID : <redacted>\n") is None
    )  # no Location Services
    assert speed.parse_linux_route("default via 10.0.0.1 dev wlp3s0 proto dhcp\n") == "wlp3s0"
    assert speed.parse_nmcli("no:Other\nyes:Curio-5G\n") == "Curio-5G"
    assert (
        speed.parse_netsh(
            "    State                  : connected\n    SSID                   : Curio-5G\n"
        )
        == "Curio-5G"
    )
    assert speed.parse_netsh("    State                  : disconnected\n") is None
    print("  parsers:              ok (trace, org, mac/linux/windows tools)")


def test_local_connection() -> None:
    def mac(args: list[str]) -> str:
        return {
            "route": "  interface: en0\n",
            "networksetup": (
                "Hardware Port: Wi-Fi\nDevice: en0\n"
                if args[1] == "-listallhardwareports"
                else "Current Wi-Fi Network: Curio-5G\n"
            ),
            "ipconfig": "  SSID : Curio-5G\n",
        }.get(args[0], "")

    c = speed.local_connection(mac, platform="darwin")
    assert (c.interface, c.ssid) == ("wifi", "Curio-5G")

    def mac_eth(args: list[str]) -> str:
        return {
            "route": "  interface: en5\n",
            "networksetup": "Hardware Port: Thunderbolt Ethernet\nDevice: en5\n",
        }.get(args[0], "")

    assert speed.local_connection(mac_eth, platform="darwin") == speed.Connection("ethernet", None)

    def linux(args: list[str]) -> str:
        return {"ip": "default via 10.0.0.1 dev wlan0\n", "nmcli": "yes:Home\n"}.get(args[0], "")

    assert speed.local_connection(linux, platform="linux") == speed.Connection("wifi", "Home")
    assert speed.local_connection(lambda a: "", platform="linux") == speed.Connection()

    def win(args: list[str]) -> str:
        return "    State : connected\n    SSID  : Office\n"

    assert speed.local_connection(win, platform="win32") == speed.Connection("wifi", "Office")

    def boom(args: list[str]) -> str:
        raise RuntimeError("tool exploded")

    assert speed.local_connection(boom, platform="darwin") == speed.Connection()
    print("  local connection:     ok (wifi/ethernet per OS; a broken tool → unknown)")


def test_meter(tmp: Path) -> None:
    from dawnmaker.speed import KEEP, SpeedMeter

    transport, calls = fake_transport()
    cfg = Config(home=tmp)
    asked = 0

    def conn() -> speed.Connection:
        nonlocal asked
        asked += 1
        return speed.Connection("wifi", "Curio-5G")

    meter = SpeedMeter(
        cfg, client=httpx.Client(transport=transport), connection=conn, clock=Tick(0.25)
    )
    empty = meter.snapshot()
    assert (
        empty["measured_at"] is None
        and not empty["online"]
        and empty["samples"]
        == {
            "download": [],
            "upload": [],
        }
    )
    assert empty["connection"] == {
        "interface": "wifi",
        "ssid": "Curio-5G",
        "isp": None,
        "asn": None,
    }

    s = meter.run(full=True)
    assert s["online"] and s["download_mbps"] > 0 and s["upload_mbps"] > 0
    assert s["server"]["location"] == "Singapore" and s["server"]["ip_version"] == "IPv4"
    assert s["connection"]["isp"] == "INDOSAT Internet Network Provider"
    assert s["connection"]["asn"] == "AS4761"
    assert s["samples"]["download"] and s["samples"]["upload"]
    assert asked == 1  # the OS is asked once, then cached

    # a short probe right after: the fresh answer, no new requests
    n = len(calls)
    assert meter.run(full=False)["measured_at"] == s["measured_at"]
    assert len(calls) == n
    # the ISP is asked once per IP
    assert calls.count("GET /json") == 1

    # a short probe later keeps the long one's upload figure
    meter.last.measured_at -= 10
    s2 = meter.run(full=False)
    assert s2["measured_at"] != s["measured_at"]
    assert s2["upload_mbps"] == s["upload_mbps"]
    assert len(s2["samples"]["download"]) <= KEEP and len(s2["samples"]["upload"]) <= KEEP

    # mid-run, a leg that has landed shows at once
    meter.testing = True
    meter.live = {"latency_ms": 12.5}
    assert meter.snapshot()["latency_ms"] == 12.5
    assert meter.snapshot()["download_mbps"] == s2["download_mbps"]  # not yet: the last answer
    meter.testing = False

    # offline: the modal still says which server it last reached
    meter.last = speed.Measurement(measured_at=0, online=False, error="ConnectError: no route")
    off = meter.snapshot()
    assert not off["online"] and off["server"]["location"] == "Singapore"
    assert off["connection"]["isp"] is None  # no public IP, no provider

    meter.reset()
    assert meter._client is None
    print("  meter:                ok (one run at a time, fresh window, tape, isp per ip, reset)")


if __name__ == "__main__":
    import tempfile

    print("speed")
    test_measure_light_and_full()
    test_measure_offline()
    test_parsers()
    test_local_connection()
    with tempfile.TemporaryDirectory() as td:
        test_meter(Path(td))
    print("\nall passed")
