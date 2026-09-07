---
name: diagnose-network
description: Diagnose and work around ISP interference reaching pixiv or X — DNS hijacking, SNI filtering, DPI, TLS interception. Use when requests fail, hang, or reset on a connection where the sites work elsewhere, or when setting up DoH or a proxy.
---

# Diagnose a blocked source

pixiv is among the sites Indonesian ISPs interfere with, so on some connections
this is the first thing that breaks — before any scraping logic is involved.

## Identify the layer before choosing a fix

They are not interchangeable. Run the four steps in order and stop at the first
failure:

```
1. system DNS      → resolves to the real IP?  | 0.0.0.0 / block page → HIJACK
2. DoH             → resolves to the real IP?  | unreachable          → RESOLVER BLOCKED
3. TCP connect     → opens?                    | timeout              → IP BLACKHOLE
4. TLS handshake   → cert valid, SNI accepted? | reset                → SNI / DPI
                                               | bad cert             → INTERCEPTION
```

Step 1 disagreeing with step 2 is the clean signature of DNS hijacking, and the
only way to know DoH will be enough before turning it on.

| Layer | Fix |
|---|---|
| DNS hijack / redirect | DoH resolver in `SourceClient` (`coreflame/net.py`, `coreflame/http.py`) |
| Resolver itself blocked | Fail over across DoH endpoints, then proxy |
| SNI filtering / DPI | **Nothing DNS-level.** Proxy or tunnel |
| IP blackhole | Proxy or tunnel |
| TLS interception | **Stop — see below** |

## DoH is layer one, a proxy is layer two

Indonesian ISPs use DNS hijacking *and* SNI filtering *and* DPI *and* TCP
resets; fixed ISPs increasingly block third-party resolvers, and mobile
operators mostly already do. So DoH alone is not a plan.

The proxy is also the **only** setting that covers both sources: `gallery-dl`
has its own network stack and cannot take our resolver, so `httpx(proxy=…)` on
our side and `--proxy` / `HTTPS_PROXY` on its side is the one shared config.
The app does not ship a proxy — it points at whatever the user already runs.

Reject a DoH answer of `0.0.0.0` or an RFC1918 address rather than dialling it.
That is interference, not an answer.

## Never disable certificate verification

At least one Indonesian ISP has been observed attempting HTTPS interception with
a spoofed certificate. A TLS validation failure is therefore **evidence of an
active MITM** — `verify=False` converts a failed interception into a successful
one and hands over the `PHPSESSID` and X `auth_token`.

It must not exist as a config option, a debug flag, or a fallback. On cert
failure the daemon says the connection is being intercepted and stops. Do not
"fix" this, and do not retry past a cert error as if it were flakiness.

When resolving by IP, always pass the original hostname as `server_hostname` so
SNI and certificate validation still target the real host.

## Verification

- `python3 -m coreflame net <host>` (or `POST /api/net/diagnose` from the UI)
  names a layer, not just "failed" — run it from a normal terminal on the
  host, not a sandboxed shell whose egress allowlist fakes `resolver_blocked`
- With DoH on, a hijacked hostname resolves to the real IP
- A blocked-page IP is rejected, not dialled
- `cd reaver && ./check.sh` is green — its last step greps `coreflame/` for
  `verify=False` (only `net.py` may name it, to refuse it) and ruff `S501`
  flags it as well
