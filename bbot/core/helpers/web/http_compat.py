"""
HTTP backend compatibility layer.

On Linux, prefer native blasthttp. On Windows (or when blasthttp is missing),
use an httpx-based client that duck-types the blasthttp surface BBOT expects.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlparse

log = logging.getLogger("bbot.core.helpers.web.http_compat")

_BACKEND = None  # "blasthttp" | "httpx"


def using_blasthttp() -> bool:
    return get_backend_name() == "blasthttp"


def get_backend_name() -> str:
    global _BACKEND
    if _BACKEND is None:
        force = (os_environ_get("BBOT_HTTP_BACKEND") or "").strip().lower()
        if force in ("httpx", "blasthttp"):
            if force == "blasthttp":
                try:
                    import blasthttp  # noqa: F401

                    _BACKEND = "blasthttp"
                    return _BACKEND
                except ImportError:
                    log.warning("BBOT_HTTP_BACKEND=blasthttp but blasthttp is not installed; falling back to httpx")
            _BACKEND = "httpx"
            return _BACKEND
        if sys.platform == "win32":
            _BACKEND = "httpx"
        else:
            try:
                import blasthttp  # noqa: F401

                _BACKEND = "blasthttp"
            except ImportError:
                _BACKEND = "httpx"
    return _BACKEND


def os_environ_get(key: str, default: str | None = None) -> str | None:
    import os

    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Shared exception / types used by web.py regardless of backend
# ---------------------------------------------------------------------------


class HTTPStatusError(Exception):
    """Raised when an HTTP response indicates failure (download helpers)."""

    def __init__(self, message: str, response=None):
        super().__init__(message)
        self.response = response


@dataclass
class ResponseHash:
    body_md5: str = ""
    body_mmh3: str = ""
    body_sha256: str = ""
    header_md5: str = ""
    header_mmh3: str = ""
    header_sha256: str = ""


@dataclass
class CertInfo:
    common_name: str = ""
    sans: list = field(default_factory=list)
    emails: list = field(default_factory=list)
    issuer: str = ""
    not_before: str = ""
    not_after: str = ""
    fingerprint_sha256: str = ""


def _mmh3_hash(data: bytes) -> str:
    try:
        import mmh3

        return str(mmh3.hash(data))
    except Exception:
        return ""


def _hash_bytes(data: bytes) -> ResponseHash:
    return ResponseHash(
        body_md5=hashlib.md5(data).hexdigest(),
        body_mmh3=_mmh3_hash(data),
        body_sha256=hashlib.sha256(data).hexdigest(),
        header_md5="",
        header_mmh3="",
        header_sha256="",
    )


class CompatResponse:
    """Duck-typed stand-in for blasthttp.Response."""

    def __init__(
        self,
        url: str,
        status_code: int,
        headers: dict,
        content: bytes,
        raw_headers: str = "",
        decode_error: str | None = None,
        cert_info: CertInfo | None = None,
    ):
        self.url = url
        self.status = status_code
        self.status_code = status_code
        self._headers = headers or {}
        self.content = content or b""
        self.body_bytes = self.content
        self.raw_headers = raw_headers
        self.decode_error = decode_error
        self.cert_info = cert_info
        self._text = None
        self._hash = None

    @property
    def headers(self):
        return self._headers

    @property
    def text(self) -> str:
        if self._text is None:
            if self.decode_error:
                self._text = ""
            else:
                try:
                    self._text = self.content.decode("utf-8", errors="replace")
                except Exception as e:
                    self.decode_error = str(e)
                    self._text = ""
        return self._text

    @property
    def body(self) -> str:
        return self.text

    @property
    def hash(self) -> ResponseHash:
        if self._hash is None:
            h = _hash_bytes(self.content)
            header_bytes = self.raw_headers.encode("utf-8", errors="replace")
            h.header_md5 = hashlib.md5(header_bytes).hexdigest()
            h.header_mmh3 = _mmh3_hash(header_bytes)
            h.header_sha256 = hashlib.sha256(header_bytes).hexdigest()
            self._hash = h
        return self._hash

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self):
        import json

        return json.loads(self.content)


@dataclass
class BatchConfig:
    url: str
    method: str = "GET"
    headers: list | None = None
    body: Any = None
    files: Any = None
    timeout: int = 10
    verify_certs: bool = False
    retries: int = 1
    follow_redirects: bool | None = None
    max_redirects: int | None = None
    redirect_cookies: bool | None = None
    proxy: str | None = None
    no_proxy: list | None = None
    max_body_size: int | None = None
    request_target: str | None = None
    resolve_ip: str | None = None

    def __post_init__(self):
        # Normalize so callers can read config.url after construction
        self.url = str(self.url)


@dataclass
class BatchResult:
    url: str
    response: Optional[CompatResponse] = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.response is not None and not self.error


class HttpxBlastClient:
    """httpx-backed client exposing the blasthttp.BlastHTTP methods BBOT uses."""

    def __init__(self):
        import httpx

        self._httpx = httpx
        self._rate_limit = 0
        self._semaphore: asyncio.Semaphore | None = None
        self._clients: dict[tuple, Any] = {}

    def set_rate_limit(self, rate_limit: int):
        self._rate_limit = int(rate_limit or 0)
        if self._rate_limit > 0:
            self._semaphore = asyncio.Semaphore(self._rate_limit)
        else:
            self._semaphore = None

    def _client_key(self, proxy: str | None, verify: bool):
        return (proxy or "", verify)

    def _get_client(self, proxy: str | None, verify: bool):
        key = self._client_key(proxy, verify)
        client = self._clients.get(key)
        if client is None:
            kwargs = {
                "verify": verify,
                "follow_redirects": True,
                "timeout": 30.0,
            }
            if proxy:
                kwargs["proxy"] = proxy
            client = self._httpx.AsyncClient(**kwargs)
            self._clients[key] = client
        return client

    async def aclose(self):
        for client in list(self._clients.values()):
            with_suppress = True
            try:
                await client.aclose()
            except Exception:
                if not with_suppress:
                    raise
        self._clients.clear()

    async def request(self, url: str, **kwargs) -> CompatResponse:
        method = kwargs.get("method", "GET")
        headers_in = kwargs.get("headers") or []
        body = kwargs.get("body")
        timeout = kwargs.get("timeout", 10)
        verify = bool(kwargs.get("verify_certs", False))
        retries = int(kwargs.get("retries", 1))
        follow_redirects = kwargs.get("follow_redirects")
        max_redirects = kwargs.get("max_redirects")
        proxy = kwargs.get("proxy")
        # resolve_ip / request_target are best-effort no-ops on httpx backend

        header_dict = {}
        if isinstance(headers_in, dict):
            header_dict = {str(k): str(v) for k, v in headers_in.items()}
        else:
            for item in headers_in:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    header_dict[str(item[0])] = str(item[1])

        client = self._get_client(proxy, verify)
        last_err = None
        attempts = max(1, retries + 1)

        for _ in range(attempts):
            try:
                if self._semaphore is not None:
                    await self._semaphore.acquire()
                try:
                    req_kwargs = {
                        "method": method,
                        "url": url,
                        "headers": header_dict,
                        "timeout": timeout,
                    }
                    if body is not None:
                        req_kwargs["content"] = body
                    if follow_redirects is not None:
                        req_kwargs["follow_redirects"] = follow_redirects
                    # httpx uses client-level follow; per-request override via request()
                    response = await client.request(**req_kwargs)
                finally:
                    if self._semaphore is not None:
                        self._semaphore.release()

                raw_header_lines = []
                for k, v in response.headers.multi_items():
                    raw_header_lines.append(f"{k}: {v}")
                raw_headers = "\r\n".join(raw_header_lines)
                headers_map = {k: v for k, v in response.headers.items()}
                content = response.content or b""
                if kwargs.get("max_body_size") is not None:
                    max_size = int(kwargs["max_body_size"])
                    if len(content) > max_size:
                        content = content[:max_size]

                decode_error = None
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError as e:
                    decode_error = str(e)

                return CompatResponse(
                    url=str(response.url),
                    status_code=response.status_code,
                    headers=headers_map,
                    content=content,
                    raw_headers=raw_headers,
                    decode_error=decode_error,
                )
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.05)

        raise RuntimeError(f"HTTP request failed for {url}: {last_err}")

    async def request_batch_stream(self, configs, concurrency: int = 10) -> AsyncIterator[list[BatchResult]]:
        sem = asyncio.Semaphore(max(1, int(concurrency)))
        queue: asyncio.Queue = asyncio.Queue()
        pending = len(configs)

        async def _one(cfg: BatchConfig):
            async with sem:
                try:
                    kwargs = {
                        "method": cfg.method,
                        "headers": cfg.headers,
                        "body": cfg.body,
                        "timeout": cfg.timeout,
                        "verify_certs": cfg.verify_certs,
                        "retries": cfg.retries,
                        "follow_redirects": cfg.follow_redirects,
                        "max_redirects": cfg.max_redirects,
                        "proxy": cfg.proxy,
                        "no_proxy": cfg.no_proxy,
                        "max_body_size": cfg.max_body_size,
                        "request_target": cfg.request_target,
                        "resolve_ip": cfg.resolve_ip,
                    }
                    # Drop Nones so request() uses defaults
                    kwargs = {k: v for k, v in kwargs.items() if v is not None or k in ("headers", "body")}
                    resp = await self.request(cfg.url, **kwargs)
                    await queue.put(BatchResult(url=cfg.url, response=resp))
                except Exception as e:
                    await queue.put(BatchResult(url=cfg.url, response=None, error=str(e)))

        tasks = [asyncio.create_task(_one(cfg)) for cfg in configs]

        completed = 0
        batch: list[BatchResult] = []
        while completed < pending:
            item = await queue.get()
            batch.append(item)
            completed += 1
            if len(batch) >= 50 or completed == pending:
                yield batch
                batch = []

        for t in tasks:
            if not t.done():
                t.cancel()


def create_http_client():
    """Return a BlastHTTP-compatible client for the active backend."""
    name = get_backend_name()
    if name == "blasthttp":
        import blasthttp

        log.debug("HTTP backend: blasthttp")
        return blasthttp.BlastHTTP()
    log.info("HTTP backend: httpx (Windows / blasthttp unavailable)")
    return HttpxBlastClient()


def get_batch_config_cls():
    if using_blasthttp():
        import blasthttp

        return blasthttp.BatchConfig
    return BatchConfig


def get_http_status_error():
    if using_blasthttp():
        from blasthttp import HTTPStatusError as BlastHTTPStatusError

        return BlastHTTPStatusError
    return HTTPStatusError
