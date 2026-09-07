"""net.py, offline: verdict classification with injected steps, bogus-answer
rejection, and the verify=False refusal. No network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coreflame.net import DohResolver, DohTransport, diagnose, is_bogus


class FakeResolver(DohResolver):
    def __init__(self, answer):
        self.answer = answer

    def resolve(self, host):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def run(system, doh, tcp=(True, "open"), tls=(True, "ok")):
    return diagnose(
        "www.pixiv.net",
        resolver=FakeResolver(doh),
        _system=lambda h: system,
        _tcp=lambda ip, p, t: tcp,
        _tls=lambda ip, h, p, t: tls,
    )


def test_bogus():
    for ip in ("0.0.0.0", "127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.0.9", "junk"):
        assert is_bogus(ip), ip
    for ip in (
        "104.18.30.219",
        "8.8.8.8",
        "1.1.1.1",
    ):  # 203.0.113.0/24 is TEST-NET, correctly bogus
        assert not is_bogus(ip), ip
    print("  bogus answers:        ok")


def test_verdicts():
    real = "104.18.30.219"
    assert run(real, real).verdict == "ok"
    assert run("0.0.0.0", real).verdict == "dns_hijack"
    assert run(None, real).verdict == "dns_hijack"
    assert run("0.0.0.0", RuntimeError("blocked")).verdict == "resolver_blocked"
    assert run(real, real, tcp=(False, "timeout")).verdict == "ip_blackhole"
    assert run(real, real, tls=(False, "reset")).verdict == "sni_dpi"
    assert run(real, real, tls=(None, "cert")).verdict == "interception"
    # hijacked DNS but DoH path works end to end -> still dns_hijack (DoH is enough)
    d = run("10.0.0.1", real)
    assert d.verdict == "dns_hijack" and "disagree" in " ".join(d.steps)
    print("  six verdicts:         ok")


def test_verify_false_refused():
    try:
        DohTransport(FakeResolver("1.2.3.4"), verify=False)
    except ValueError as e:
        assert "cannot be disabled" in str(e)
        print("  verify=False refused: ok")
        return
    raise AssertionError("DohTransport accepted verify=False")


def test_no_verify_false_in_tree():
    import re

    root = Path(__file__).resolve().parents[1] / "coreflame"
    hits = [
        str(p)
        for p in root.rglob("*.py")
        if re.search(r"verify\s*=\s*False", p.read_text()) and p.name != "net.py"
    ]  # net.py names it only to refuse it
    assert not hits, hits
    print("  no verify=False:      ok (tree is clean)")


if __name__ == "__main__":
    print("network path")
    test_bogus()
    test_verdicts()
    test_verify_false_refused()
    test_no_verify_false_in_tree()
    print("\nall passed")
