"""Guarded HTTP fetcher for R4 (design §7.1, §6.6).

Every safety property is enforced here so no connector or phase can bypass it:
  * SSRF guard  — http(s) only; reject private / loopback / link-local / reserved
                  IPs (checked against the RESOLVED address, not just the literal).
  * robots.txt  — per-domain, honoured (cached).
  * politeness  — ≤1 req/s per domain, ≤10 fetches per domain per run.
  * size caps   — HTML ≤5 MB, PDF ≤20 MB (reject over-cap).
  * content-type allowlist — html / pdf / plain only.
  * dead links  — one Wayback Machine fallback before giving up.

The DNS resolver, clock-sleep and http client are injectable so the guards are
unit-testable with respx and without real network/DNS.
"""

import ipaddress
import socket
import time
from typing import Callable, NamedTuple, Optional
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit

import httpx

from app.research.sources.base import USER_AGENT
from app.utils.logging import get_logger

log = get_logger(__name__)

HTML_CAP = 5 * 1024 * 1024
PDF_CAP = 20 * 1024 * 1024
MAX_PER_DOMAIN = 10
ALLOWED_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "text/plain"}
WAYBACK_AVAILABLE = "https://archive.org/wayback/available"


class FetchResult(NamedTuple):
    data: bytes
    mimeType: str
    finalUrl: str
    viaArchive: bool = False


def _dns_resolve(host: str) -> list[str]:
    return list({info[4][0] for info in socket.getaddrinfo(host, None)})


def _maybe_ip(host: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def is_safe_url(url: str, resolve: Callable[[str], list[str]] = _dns_resolve) -> bool:
    """http(s) + all resolved addresses public. Blocks SSRF to internal hosts."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    literal = _maybe_ip(parts.hostname)
    if literal is not None:
        return _is_public(str(literal))
    try:
        addrs = resolve(parts.hostname)
    except Exception:  # noqa: BLE001 — resolution failure = unsafe
        return False
    return bool(addrs) and all(_is_public(a) for a in addrs)


class Fetcher:
    def __init__(self, client: Optional[httpx.Client] = None,
                 resolve: Callable[[str], list[str]] = _dns_resolve,
                 respect_robots: bool = True, rps: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self._client = client or httpx.Client(
            timeout=15, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        self._resolve = resolve
        self._respect_robots = respect_robots
        self._rps = rps
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self._domain_count: dict[str, int] = {}
        self._last_fetch: dict[str, float] = {}

    # -- guards ---------------------------------------------------------------
    def _robots_allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        parts = urlsplit(url)
        host = parts.hostname or ""
        if host not in self._robots:
            self._robots[host] = self._load_robots(f"{parts.scheme}://{parts.netloc}")
        rp = self._robots[host]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def _load_robots(self, origin: str) -> Optional[RobotFileParser]:
        try:
            resp = self._client.get(f"{origin}/robots.txt", timeout=10)
            if resp.status_code >= 400:
                return None  # no robots → allow
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
        except Exception:  # noqa: BLE001 — robots unreachable → allow
            return None

    def _rate_limit(self, host: str) -> None:
        if self._rps <= 0:
            return
        gap = 1.0 / self._rps
        last = self._last_fetch.get(host)
        now = self._clock()
        if last is not None and (now - last) < gap:
            self._sleep(gap - (now - last))
        self._last_fetch[host] = self._clock()

    # -- fetch ----------------------------------------------------------------
    def fetch(self, url: str) -> Optional[FetchResult]:
        if not is_safe_url(url, self._resolve):
            log.warning("fetch blocked (ssrf/scheme)", extra={"fields": {"url": url[:200]}})
            return None
        host = urlsplit(url).hostname or ""
        if self._domain_count.get(host, 0) >= MAX_PER_DOMAIN:
            log.info("fetch skipped (per-domain cap)", extra={"fields": {"host": host}})
            return None
        if not self._robots_allowed(url):
            log.info("fetch disallowed by robots", extra={"fields": {"url": url[:200]}})
            return None
        self._rate_limit(host)

        result = self._raw_fetch(url)
        if result is None:
            result = self._wayback(url)
        if result is not None:
            self._domain_count[host] = self._domain_count.get(host, 0) + 1
        return result

    def _raw_fetch(self, url: str, via_archive: bool = False) -> Optional[FetchResult]:
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch failed", extra={"fields": {"url": url[:200], "error": str(exc)}})
            return None
        mime = (resp.headers.get("content-type", "").split(";")[0].strip().lower())
        if mime and mime not in ALLOWED_TYPES:
            log.info("fetch rejected (content-type)", extra={"fields": {"mime": mime}})
            return None
        cap = PDF_CAP if mime == "application/pdf" else HTML_CAP
        clen = resp.headers.get("content-length")
        if clen and clen.isdigit() and int(clen) > cap:
            log.info("fetch rejected (declared size)", extra={"fields": {"len": clen}})
            return None
        data = resp.content
        if len(data) > cap:
            log.info("fetch rejected (body size)", extra={"fields": {"len": len(data)}})
            return None
        return FetchResult(data=data, mimeType=mime or "text/html",
                           finalUrl=str(resp.url), viaArchive=via_archive)

    def _wayback(self, url: str) -> Optional[FetchResult]:
        """One dead-link fallback: fetch the closest Wayback snapshot (§7.3)."""
        try:
            avail = self._client.get(WAYBACK_AVAILABLE, params={"url": url}, timeout=15)
            closest = ((avail.json().get("archived_snapshots") or {}).get("closest") or {})
        except Exception:  # noqa: BLE001
            return None
        snap = closest.get("url")
        if not closest.get("available") or not snap:
            return None
        log.info("using wayback snapshot", extra={"fields": {"url": url[:200]}})
        return self._raw_fetch(snap, via_archive=True)
