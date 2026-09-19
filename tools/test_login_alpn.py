#!/usr/bin/env python3
"""Demonstrate the ALPN-dependent HTTP 404 on OBI's login endpoint (#28).

Background
----------
aiohttp's default SSL context hardcodes ``set_alpn_protocols(("http/1.1",))``.
OBI's CloudFront WAF answers such ClientHellos with an empty-bodied HTTP 404,
so the integration cannot log in, while the heyOBI app and a plain browser -
which also offer h2 - keep working. The endpoint itself was never removed.

This script sends the same login request twice, differing *only* in the TLS
ClientHello, and reports the status codes:

    ALPN ["http/1.1"] only   -> 404   (aiohttp's default; what breaks)
    no ALPN extension        -> 401   (the fix; credentials rejected normally)

No OBI account is required: it deliberately uses an address in the reserved
``.invalid`` TLD, so the credentials can never be valid and no real account is
touched. A 401 therefore means "endpoint reachable, credentials rejected",
which is exactly the outcome we want to prove.

Usage:
    python tools/test_login_alpn.py
"""
from __future__ import annotations

import asyncio
import json
import ssl
import sys

import aiohttp

LOGIN_URL = "https://www.obi.de/regi/auth/api/public/login"
USER_AGENT = "heyOBI APP / iPhone17,2 / 4.9.1 / 560"

PAYLOAD = json.dumps(
    {
        "password": "not-a-real-password",
        "country": "de",
        "email": "probe@example.invalid",
    },
    separators=(",", ":"),
).encode("utf-8")

HEADERS = {
    "content-type": "application/json",
    "accept": "*/*",
    "user-agent": USER_AGENT,
    "accept-language": "de-DE,de;q=0.9",
    "accept-encoding": "identity",
    "cookie": "obi_storeid=527",
    "origin": "https://www.obi.de",
    "referer": "https://www.obi.de/",
}


def ctx_with_alpn() -> ssl.SSLContext:
    """Reproduce aiohttp's default context (ALPN: http/1.1 only)."""
    context = ssl.create_default_context()
    context.set_alpn_protocols(("http/1.1",))
    return context


def ctx_without_alpn() -> ssl.SSLContext:
    """The fix: no ALPN extension at all."""
    return ssl.create_default_context()


async def attempt(label: str, context: ssl.SSLContext) -> tuple[int, str | None]:
    connector = aiohttp.TCPConnector(ssl=context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(
            LOGIN_URL,
            data=PAYLOAD,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            pop = resp.headers.get("X-Amz-Cf-Pop")
            print(f"  {label:<26} -> HTTP {resp.status}   (CloudFront PoP: {pop})")
            return resp.status, pop


async def main() -> int:
    print(f"POST {LOGIN_URL}")
    print("identical request bytes; only the TLS ClientHello differs\n")

    broken, _ = await attempt('ALPN ["http/1.1"] only', ctx_with_alpn())
    await asyncio.sleep(3)
    fixed, _ = await attempt("no ALPN extension", ctx_without_alpn())

    print()
    ok = True
    if broken == 404:
        print("PASS  ALPN-only-http/1.1 reproduces the #28 HTTP 404")
    else:
        ok = False
        print(f"NOTE  expected 404 with ALPN http/1.1, got {broken}"
              " - OBI may have changed the WAF rule")
    if fixed in (200, 401):
        print(f"PASS  omitting ALPN reaches the origin (HTTP {fixed})")
    else:
        ok = False
        print(f"FAIL  expected 401 without ALPN, got {fixed}")

    print("\nALL CHECKS PASSED" if ok else "\nCHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
