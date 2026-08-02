"""HTTP client for the Rivult cloud API (bedwars-cloud Worker).

stdlib ``urllib`` only — the parser stays zero-dependency. Every response uses
the ``{ok, data, error}`` envelope; errors surface as :class:`CloudError` with
the server's stable machine code, so callers can branch on ``e.code``
(``DEVICE_LIMIT``, ``UNAUTHENTICATED``, ``NETWORK``, ...) instead of parsing
messages.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

DEFAULT_TIMEOUT_S = 15


class CloudError(Exception):
    """API or transport failure. ``status is None`` means we never reached the
    server (offline) — callers treat that differently from a real rejection."""

    def __init__(self, message: str, status: Optional[int] = None,
                 code: str = "UNKNOWN", extra: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra or {}


class CloudAPI:
    def __init__(self, base_url: str, token: Optional[str] = None,
                 device_id: Optional[str] = None, device_name: Optional[str] = None,
                 device_platform: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT_S):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.device_id = device_id
        self.device_name = device_name
        self.device_platform = device_platform
        self.timeout = timeout

    # -- transport ----------------------------------------------------------
    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 auth: bool = True) -> Any:
        headers = {"Content-Type": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.device_id:
            headers["X-Device-Id"] = self.device_id
            if self.device_name:
                headers["X-Device-Name"] = self.device_name
            if self.device_platform:
                headers["X-Device-Platform"] = self.device_platform
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return self._envelope(resp.read())
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                env = json.loads(payload)
                err = env.get("error") or {}
                raise CloudError(err.get("message", f"HTTP {e.code}"),
                                 status=e.code, code=err.get("code", "HTTP"),
                                 extra=err) from None
            except (ValueError, AttributeError):
                raise CloudError(f"HTTP {e.code}", status=e.code, code="HTTP") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise CloudError(f"network error: {e}", status=None, code="NETWORK") from None

    @staticmethod
    def _envelope(raw: bytes) -> Any:
        try:
            env = json.loads(raw)
        except ValueError:
            raise CloudError("malformed response from server", code="BAD_RESPONSE") from None
        if not isinstance(env, dict) or not env.get("ok"):
            err = (env or {}).get("error") or {}
            raise CloudError(err.get("message", "request failed"),
                             code=err.get("code", "UNKNOWN"), extra=err)
        return env.get("data")

    # -- auth ---------------------------------------------------------------
    def register(self, email: str, password: str) -> dict:
        data = self._request("POST", "/api/auth/register",
                             {"email": email, "password": password}, auth=False)
        self.token = data["token"]
        return data

    def login(self, email: str, password: str) -> dict:
        data = self._request("POST", "/api/auth/login",
                             {"email": email, "password": password}, auth=False)
        self.token = data["token"]
        return data

    def logout(self) -> None:
        self._request("POST", "/api/auth/logout")
        self.token = None

    def delete_account(self, password: str) -> dict:
        """Irreversibly delete the cloud account and everything in it. The
        password is re-confirmed server-side; a token alone can't do this."""
        return self._request("POST", "/api/auth/delete", {"password": password})

    # -- license / devices --------------------------------------------------
    def license(self) -> dict:
        return self._request("GET", "/api/license")

    def devices(self) -> dict:
        return self._request("GET", "/api/devices")

    def revoke_device(self, device_row_id: str) -> dict:
        return self._request("POST", f"/api/devices/{device_row_id}/revoke")

    # -- billing (design P2) -------------------------------------------------
    # Both return {url}: a Stripe-hosted page the desktop app opens in the
    # system browser. Card details never touch this app.
    def checkout(self, plan: str) -> dict:
        return self._request("POST", "/api/billing/checkout", {"plan": plan})

    def portal(self) -> dict:
        return self._request("POST", "/api/billing/portal")

    # -- sync ---------------------------------------------------------------
    def push(self, games: list, tags: list, game_tags: list) -> dict:
        return self._request("POST", "/api/sync/push", {
            "deviceId": self.device_id,
            "games": games, "tags": tags, "gameTags": game_tags,
        })

    def pull(self, since: int, limit: int = 500) -> dict:
        return self._request("GET", f"/api/sync/pull?since={int(since)}&limit={int(limit)}")
