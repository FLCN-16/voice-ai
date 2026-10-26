"""Small, dependency-free Cal.com API client used by the LangChain tools."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CalComError(RuntimeError):
    """An actionable error returned while calling Cal.com."""


@dataclass(frozen=True)
class CalComSettings:
    """Environment-backed settings for the Cal.com API."""

    api_key: str
    base_url: str = "https://api.cal.com"
    slots_api_version: str = "2024-09-04"
    bookings_api_version: str = "2026-02-25"
    timeout_seconds: float = 20.0
    client_id: str | None = None
    secret_key: str | None = None
    default_event_type_id: int | None = None
    default_event_type_slug: str | None = None
    default_username: str | None = None
    default_team_slug: str | None = None
    default_organization_slug: str | None = None
    default_time_zone: str = "UTC"
    default_duration_minutes: int = 30

    @classmethod
    def from_environment(cls) -> "CalComSettings":
        """Build settings lazily so importing tools never requires credentials."""
        api_key = os.getenv("CALCOM_API_KEY") or os.getenv("CAL_API_KEY")
        if not api_key:
            raise CalComError(
                "Cal.com is not configured. Set CALCOM_API_KEY in the environment."
            )

        try:
            timeout_seconds = float(os.getenv("CALCOM_TIMEOUT_SECONDS", "20"))
        except ValueError as exc:
            raise CalComError("CALCOM_TIMEOUT_SECONDS must be a number.") from exc
        if timeout_seconds <= 0:
            raise CalComError("CALCOM_TIMEOUT_SECONDS must be greater than zero.")

        default_event_type_id = os.getenv("CALCOM_DEFAULT_EVENT_TYPE_ID") or None
        try:
            parsed_event_type_id = (
                int(default_event_type_id) if default_event_type_id else None
            )
        except ValueError as exc:
            raise CalComError(
                "CALCOM_DEFAULT_EVENT_TYPE_ID must be an integer."
            ) from exc
        try:
            default_duration_minutes = int(
                os.getenv("CALCOM_DEFAULT_DURATION_MINUTES", "30")
            )
        except ValueError as exc:
            raise CalComError(
                "CALCOM_DEFAULT_DURATION_MINUTES must be an integer."
            ) from exc
        if default_duration_minutes <= 0:
            raise CalComError(
                "CALCOM_DEFAULT_DURATION_MINUTES must be greater than zero."
            )

        return cls(
            api_key=api_key,
            base_url=os.getenv("CALCOM_API_BASE_URL", cls.base_url).rstrip("/"),
            slots_api_version=os.getenv(
                "CALCOM_SLOTS_API_VERSION", cls.slots_api_version
            ),
            bookings_api_version=os.getenv(
                "CALCOM_BOOKINGS_API_VERSION", cls.bookings_api_version
            ),
            timeout_seconds=timeout_seconds,
            client_id=os.getenv("CALCOM_CLIENT_ID") or None,
            secret_key=os.getenv("CALCOM_SECRET_KEY") or None,
            default_event_type_id=parsed_event_type_id,
            default_event_type_slug=os.getenv("CALCOM_DEFAULT_EVENT_TYPE_SLUG") or None,
            default_username=os.getenv("CALCOM_DEFAULT_USERNAME") or None,
            default_team_slug=os.getenv("CALCOM_DEFAULT_TEAM_SLUG") or None,
            default_organization_slug=os.getenv(
                "CALCOM_DEFAULT_ORGANIZATION_SLUG"
            )
            or None,
            default_time_zone=os.getenv("CALCOM_DEFAULT_TIME_ZONE", "UTC"),
            default_duration_minutes=default_duration_minutes,
        )


class CalComClient:
    """Synchronous client for the Cal.com v2 slots and bookings endpoints."""

    def __init__(self, settings: CalComSettings | None = None) -> None:
        self.settings = settings or CalComSettings.from_environment()

    def get_slots(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch available slots for an event type or a group of users."""
        return self._request(
            method="GET",
            path="/v2/slots",
            query=params,
            api_version=self.settings.slots_api_version,
        )

    def create_booking(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a regular, recurring, seated, or instant booking."""
        return self._request(
            method="POST",
            path="/v2/bookings",
            payload=payload,
            api_version=self.settings.bookings_api_version,
        )

    def _request(
        self,
        *,
        method: str,
        path: str,
        api_version: str,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.api_key}",
            "cal-api-version": api_version,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.settings.client_id:
            headers["x-cal-client-id"] = self.settings.client_id
        if self.settings.secret_key:
            headers["x-cal-secret-key"] = self.settings.secret_key

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = _response_detail(body)
            raise CalComError(
                f"Cal.com returned HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise CalComError(f"Could not reach Cal.com: {exc.reason}") from exc
        except TimeoutError as exc:
            raise CalComError("The Cal.com request timed out.") from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise CalComError("Cal.com returned an invalid JSON response.") from exc
        if not isinstance(result, dict):
            raise CalComError("Cal.com returned an unexpected response shape.")
        if result.get("status") == "error":
            raise CalComError(_response_detail(body))
        return result


def _response_detail(body: str) -> str:
    """Extract a useful, non-secret message from a Cal.com response."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:500] or "Unknown Cal.com error"
    if isinstance(parsed, dict):
        error = parsed.get("error") or parsed.get("message")
        if error:
            return str(error)
    return body[:500] or "Unknown Cal.com error"
