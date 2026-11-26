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

api._FRESH_TOKEN_RETRY_DELAY = 0.5  # keep the run fast

LOGINS: list[float] = []
MODE = {"login": 200, "api": 200}
# Tokens the backend has invalidated server-side (answered with 401).
REVOKED: set[str] = set()
LOGGED_IN = asyncio.Event()
# When each token was issued, for a backend that rejects brand-new tokens.
ISSUED: dict[str, float] = {}


def make_jwt(ttl_seconds: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"exp": int(time.time()) + ttl_seconds, "accountId": "x", "n": len(LOGINS)}
        ).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


async def handle_login(request: web.Request) -> web.Response:
    LOGINS.append(time.monotonic())
    if MODE["login"] != 200:
        return web.Response(status=MODE["login"])
    LOGGED_IN.set()
    token = make_jwt(MODE.get("ttl", 19 * 3600))
    ISSUED[token] = time.monotonic()
    return web.json_response({"token": token})


def _is_revoked(request: web.Request) -> bool:
    return request.headers.get("Authorization", "")[7:] in REVOKED


async def handle_bridges(request: web.Request) -> web.Response:
    if MODE["api"] != 200 or _is_revoked(request):
        return web.Response(status=MODE["api"] if MODE["api"] != 200 else 401)
    return web.json_response([{"id": "hh", "sensors": [{"id": "mid"}]}])


async def handle_sensor(request: web.Request) -> web.Response:
    token = request.headers.get("Authorization", "")[7:]
    if MODE.get("reject_all") or (
        token in ISSUED and time.monotonic() - ISSUED[token] < MODE.get("warmup", 0)
    ):
        # OBI's "Invalid token." for a token its own login just issued.
        return web.json_response({"error": "Invalid token."}, status=401)
    if _is_revoked(request):
        # Answer only after a concurrent caller has already logged in again,
        # i.e. the 401 for the old token arrives when a fresh one is current.
        await LOGGED_IN.wait()
        return web.json_response({"error": "Invalid token."}, status=401)
    return web.json_response({"id": "mid", "uploadInterval": 2})


async def main() -> None:
    app = web.Application()
    app.router.add_post("/login", handle_login)
    app.router.add_get("/bridges", handle_bridges)
    app.router.add_patch("/sensors/{mid_id}", handle_sensor)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8731)
    await site.start()

    api.LOGIN_URL = "http://127.0.0.1:8731/login"
    api.BRIDGES_URL = "http://127.0.0.1:8731/bridges"
    api.SENSOR_URL_TEMPLATE = "http://127.0.0.1:8731/sensors/{mid_id}"

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
        error = None
        try:
            await client.async_get_bridges()
        except api.ObiApiError as err:
            error = err
        check(
            "401 on a seconds-old token does not re-login (was: +1 login)",
            len(LOGINS) == 1,
            f"logins={len(LOGINS)}",
        )
        check(
            "...and is not reported as bad credentials (was: ObiAuthError -> reauth)",
            isinstance(error, api.ObiTokenRejectedError)
            and not isinstance(error, api.ObiAuthError),
            f"error={type(error).__name__}",
        )
        MODE["api"] = 200

        # 5b. OBI invalidates a long-lived token server-side while the poll and
        # the live-mode PATCH are both in flight. The poll logs in again; the
        # PATCH's late 401 (for the old token) must retry with the new token
        # instead of mistaking it for "a fresh token was rejected".
        LOGINS.clear()
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        await client.async_get_bridges()
        client._token_obtained_at -= api.timedelta(hours=1)
        client._last_login_attempt_at -= api.timedelta(hours=1)
        REVOKED.add(client._token)
        LOGGED_IN.clear()
        results = await asyncio.gather(
            client.async_set_sensor_upload_interval("mid", 2),
            client.async_get_bridges(),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, Exception)]
        check(
            "revoked token + concurrent 401s: all callers recover (was: ObiAuthError)",
            not errors and len(LOGINS) == 2,
            f"logins={len(LOGINS)} errors={[type(e).__name__ for e in errors]}",
        )
        REVOKED.clear()

        # 5c. OBI rejects a token it issued moments ago (seen in production as
        # "Invalid token." right after a re-login). A short pause and a retry
        # with the same token must recover it, without another login.
        LOGINS.clear()
        MODE["warmup"] = 0.3
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        error = None
        try:
            await client.async_set_sensor_upload_interval("mid", 2)
        except api.ObiApiError as err:
            error = err
        check(
            "freshly issued token rejected briefly: delayed retry recovers, no extra login",
            error is None and len(LOGINS) == 1,
            f"logins={len(LOGINS)} error={type(error).__name__ if error else None}",
        )
        MODE["warmup"] = 0

        # 5d. A backend that rejects every token must not cause a reauth flow
        # nor a stream of password logins.
        LOGINS.clear()
        client = api.ObiApiClient(session, "a@b.de", "pw", 55 * 60)
        await client.async_get_bridges()
        client._token_obtained_at -= api.timedelta(hours=1)
        client._last_login_attempt_at -= api.timedelta(hours=1)
        MODE["reject_all"] = True
        errors = []
        for _ in range(10):  # simulates the live reconnect loop
            try:
                await client.async_set_sensor_upload_interval("mid", 2)
            except api.ObiApiError as err:
                errors.append(err)
        check(
            "every token rejected: 1 re-login, then paused; never ObiAuthError",
            len(LOGINS) == 2
            and len(errors) == 10
            and all(isinstance(e, api.ObiTokenRejectedError) for e in errors)
            and not any(isinstance(e, api.ObiAuthError) for e in errors),
            f"logins={len(LOGINS)} errors={sorted({type(e).__name__ for e in errors})}",
        )
        MODE["reject_all"] = False

        # 6. Logins per day at the default settings.
        per_day_old = 24 * 60 // 55
        per_day_new = 1
        print(f"\nlogins/day  before: ~{per_day_old}   after: ~{per_day_new} (19h token)")

    await runner.cleanup()
    print("\n" + ("ALL CHECKS PASSED" if not failures else f"FAILED: {failures}"))
    sys.exit(1 if failures else 0)


asyncio.run(main())
