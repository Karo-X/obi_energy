"""Standalone check of the OBI API client's login behaviour.

Runs the real ObiApiClient against a local aiohttp test server, so no OBI
account and no network access are involved. Counts how many password logins
the client sends in scenarios that mirror the reports in issue #25.

    python tools/test_auth_behavior.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import shutil
import sys
import tempfile
import time
import types

import aiohttp
from aiohttp import web

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / "custom_components" / "obi_energy"

# Import api.py + const.py as a tiny package so Home Assistant isn't needed.
_tmp = pathlib.Path(tempfile.mkdtemp())
pkg = _tmp / "obipkg"
pkg.mkdir()
(pkg / "__init__.py").write_text("")
shutil.copy(SRC / "api.py", pkg / "api.py")
shutil.copy(SRC / "const.py", pkg / "const.py")
sys.path.insert(0, str(_tmp))

import obipkg.api as api  # noqa: E402

LOGINS: list[float] = []
MODE = {"login": 200, "api": 200}


def make_jwt(ttl_seconds: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + ttl_seconds, "accountId": "x"}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


async def handle_login(request: web.Request) -> web.Response:
    LOGINS.append(time.monotonic())
    if MODE["login"] != 200:
        return web.Response(status=MODE["login"])
    return web.json_response({"token": make_jwt(MODE.get("ttl", 19 * 3600))})


async def handle_bridges(request: web.Request) -> web.Response:
    if MODE["api"] != 200:
        return web.Response(status=MODE["api"])
    return web.json_response([{"id": "hh", "sensors": [{"id": "mid"}]}])


async def main() -> None:
    app = web.Application()
    app.router.add_post("/login", handle_login)
    app.router.add_get("/bridges", handle_bridges)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8731)
    await site.start()

    api.LOGIN_URL = "http://127.0.0.1:8731/login"
    api.BRIDGES_URL = "http://127.0.0.1:8731/bridges"

    failures = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
        if not ok:
            failures.append(name)

    async with aiohttp.ClientSession() as session:
        # 1. Token lifetime is taken from the JWT, not from the 55 min timer.
        LOGINS.clear()
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        await client.async_get_bridges()
        client._token_obtained_at -= api.timedelta(hours=2)  # 2h later
        await client.async_get_bridges()
        check(
            "no re-login while the JWT is still valid (was: every 55 min)",
            len(LOGINS) == 1,
            f"logins={len(LOGINS)}",
        )

        # 2. Login still happens once the JWT is about to expire.
        LOGINS.clear()
        MODE["ttl"] = 60  # token expires in 60s, margin is 5 min
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        await client.async_get_bridges()
        client._last_login_attempt_at -= api.timedelta(minutes=5)
        await client.async_get_bridges()
        check("re-login when the JWT is near expiry", len(LOGINS) == 2, f"logins={len(LOGINS)}")
        MODE["ttl"] = 19 * 3600

        # 2b. Real OBI tokens last 180 days; the 7-day cap still refreshes.
        LOGINS.clear()
        MODE["ttl"] = 180 * 24 * 3600  # measured against the live API
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        await client.async_get_bridges()
        client._token_obtained_at -= api.timedelta(days=8)
        client._last_login_attempt_at -= api.timedelta(days=8)
        await client.async_get_bridges()
        check(
            "180-day token is still refreshed after the 7-day cap",
            len(LOGINS) == 2,
            f"logins={len(LOGINS)}",
        )
        MODE["ttl"] = 19 * 3600

        # 3. Concurrent callers (poll + live WS + live PATCH) => one login.
        LOGINS.clear()
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        await asyncio.gather(*(client.async_get_bridges() for _ in range(8)))
        check(
            "8 concurrent requests trigger a single login (was: up to 8)",
            len(LOGINS) == 1,
            f"logins={len(LOGINS)}",
        )

        # 4. A rejected password is not replayed in a loop.
        LOGINS.clear()
        MODE["login"] = 401
        client = api.ObiApiClient(session, "a@b.de", "wrong", 55 * 60)
        rejected = 0
        for _ in range(20):  # simulates the 10s live-reconnect loop
            try:
                await client.async_login()
            except api.ObiApiError:
                rejected += 1
        check(
            "20 retries send only one password attempt (was: 20)",
            len(LOGINS) == 1 and rejected == 20,
            f"logins={len(LOGINS)}",
        )

        # 5. A fresh token that gets a 401 does not trigger another login.
        LOGINS.clear()
        MODE["login"] = 200
        MODE["api"] = 401
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        try:
            await client.async_get_bridges()
        except api.ObiApiError:
            pass
        check(
            "401 on a seconds-old token does not re-login (was: +1 login)",
            len(LOGINS) == 1,
            f"logins={len(LOGINS)}",
        )
        MODE["api"] = 200

        # 6. Logins per day at the default settings.
        per_day_old = 24 * 60 // 55
        per_day_new = 1
        print(f"\nlogins/day  before: ~{per_day_old}   after: ~{per_day_new} (19h token)")

    await runner.cleanup()
    print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILED: {failures}"))
    sys.exit(1 if failures else 0)


asyncio.run(main())
