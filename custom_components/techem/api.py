"""Unofficial client for the Techem tenant portal (mieter.techem.de).

The portal renders server-side (Next.js); its backend API needs a key only the
portal server has. So we read the same pages a browser does, with the user's
NextAuth session cookie, and pick the data objects out of the embedded React
Server Components ("flight") payload. The cookie is re-issued on every session
check, so polling keeps it alive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from urllib.parse import quote

import aiohttp

from .const import BASE_URL, COOKIE_PREFIX, USER_AGENT

_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_ROW = re.compile(r'\{"period":"\d{4}-\d{2}","service":"[^{}]*\}')
_AVERAGE = re.compile(r'"averageConsumption":(\{[^{}]*\})')
_AGREEMENTS = re.compile(r'"rentalAgreements":(\[[^\]]*\])')
_DETAIL = re.compile(r'/consumptions/([a-z_-]+)/(\d{4}-\d{2})"')


class TechemAuthError(Exception):
    """The session cookie is missing, expired or rejected."""


class TechemError(Exception):
    """The portal answered with something we don't understand."""


@dataclass
class ServiceData:
    """Consumption of one service (heating, hot water, ...) of one flat."""

    rows: list[dict] = field(default_factory=list)  # {period, unitOfMeasure, amount, ...}
    average: dict | None = None  # comparable households, latest month


def parse_cookies(text: str) -> dict[str, str]:
    """Accept a bare token, a 'Cookie:' header or a raw request dump."""
    text = text.strip()
    found = dict(re.findall(rf"({re.escape(COOKIE_PREFIX)}(?:\.\d+)?)=([^;\s]+)", text))
    if not found and re.fullmatch(r"[\w.-]+", text):
        found = {COOKIE_PREFIX: text}
    return found


def flight(html: str) -> str:
    return "".join(json.loads(m) for m in _FLIGHT.findall(html))


class TechemClient:
    def __init__(self, session: aiohttp.ClientSession, cookies: dict[str, str]) -> None:
        self._session = session
        self.cookies = dict(cookies)

    async def _get(self, path: str) -> aiohttp.ClientResponse:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "de",
            "Cookie": "; ".join(f"{k}={v}" for k, v in sorted(self.cookies.items())),
        }
        resp = await self._session.get(
            BASE_URL + path, headers=headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=30)
        )
        # NextAuth rolls the session cookie (possibly split into .0/.1 chunks)
        rolled = {k: m.value for k, m in resp.cookies.items() if k.startswith(COOKIE_PREFIX)}
        if rolled:
            self.cookies = {k: v for k, v in rolled.items() if v}
        return resp

    async def _page(self, path: str) -> str:
        resp = await self._get(path)
        if resp.status in (301, 302, 303, 307, 308) and "auth" in resp.headers.get("location", ""):
            raise TechemAuthError("redirected to login")
        if resp.status != 200:
            raise TechemError(f"{path}: HTTP {resp.status}")
        return flight(await resp.text())

    async def session_user(self) -> str:
        """Check (and roll) the session; returns the account's subject id."""
        resp = await self._get("/api/auth/session")
        if resp.status != 200:
            raise TechemError(f"session check: HTTP {resp.status}")
        data = await resp.json(content_type=None)
        if not data or "user" not in data:
            raise TechemAuthError("session expired")
        return data.get("sub") or data["user"].get("email", "techem")

    async def units(self) -> list[str]:
        agreements = _AGREEMENTS.search(await self._page("/de"))
        if not agreements:
            raise TechemError("no rental agreements found")
        return [a["residentialUnitId"] for a in json.loads(agreements.group(1)) if a.get("residentialUnitId")]

    async def consumption(self, unit: str) -> dict[str, ServiceData]:
        base = f"/de/{quote(unit, safe=':')}/consumptions"
        services = dict(_DETAIL.findall(await self._page(base)))  # slug -> latest period
        result: dict[str, ServiceData] = {}
        for slug, period in services.items():
            page = await self._page(f"{base}/{slug}/{period}")
            data = ServiceData()
            for raw in _ROW.findall(page):
                row = json.loads(raw)
                if row.get("amount") is not None:
                    data.rows.append(row)
            if avg := _AVERAGE.search(page):
                data.average = json.loads(avg.group(1))
            # rows repeat across chart blocks: keep one per (period, unit)
            data.rows = sorted({(r["period"], r["unitOfMeasure"]): r for r in data.rows}.values(), key=lambda r: r["period"])
            service = data.rows[0]["service"] if data.rows else slug.upper()
            result[service] = data
        return result
