from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from . import __version__
from .errors import ApiError

USER_AGENT = f"youtube-multichannel-uploader/{__version__}"


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None

    def json(self) -> Any:
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(self.status, "invalid_json", "response was not valid JSON") from exc


def _error_from_http(status: int, body: bytes, headers: Mapping[str, str]) -> ApiError:
    message = "request failed"
    reason = "api_error"
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        error = payload.get("error", payload)
        if isinstance(error, dict):
            message = str(error.get("message") or message)
            errors = error.get("errors") or []
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                reason = str(errors[0].get("reason") or reason)
        elif isinstance(error, str):
            message = error
    except (UnicodeDecodeError, json.JSONDecodeError):
        if body:
            message = body.decode("utf-8", errors="replace")[:300]
    retry_after = None
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                retry_after = float(value)
            except ValueError:
                retry_after = None
            break
    retryable = status == 429 or status >= 500
    return ApiError(
        status=status,
        reason=reason,
        message=message,
        retryable=retryable,
        retry_after=retry_after,
    )


class HttpClient:
    def __init__(
        self,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 60.0,
    ) -> None:
        self.opener = opener
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        request_headers = {"User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            url=url,
            data=data,
            headers=request_headers,
            method=method.upper(),
        )
        try:
            with self.opener(request, timeout=timeout or self.timeout) as response:
                body = response.read()
                status = int(getattr(response, "status", response.getcode()))
                response_headers = dict(response.headers.items())
                return HttpResponse(status=status, headers=response_headers, body=body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            response_headers = dict(exc.headers.items()) if exc.headers else {}
            if exc.code == 308:
                return HttpResponse(status=308, headers=response_headers, body=body)
            raise _error_from_http(exc.code, body, response_headers) from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                status=None,
                reason="network_error",
                message=str(exc.reason),
                retryable=True,
            ) from exc

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> Any:
        response = self.request(method, url, headers=headers, data=data, timeout=timeout)
        return response.json()
