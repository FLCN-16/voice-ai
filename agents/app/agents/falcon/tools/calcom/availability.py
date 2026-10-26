"""LangChain tool for checking Cal.com availability."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from langchain_core.tools import tool

from .client import CalComClient, CalComError
from .models import AvailabilityToolInput, CheckAvailabilityInput


@tool(args_schema=AvailabilityToolInput)
def check_calcom_availability(**kwargs: Any) -> str:
    """Check appointment availability for the caller's requested date or time.

    Ask only for the requested date or time. The event type and owner calendar
    are configured privately in the application environment; never ask the
    caller for a Cal.com event slug, event ID, username, or owner email.
    """
    try:
        request = CheckAvailabilityInput.model_validate(
            AvailabilityToolInput.model_validate(kwargs).model_dump(exclude_none=True)
        )
        client = CalComClient()
        request = _apply_default_event(request, client)
        request = _apply_default_range(request, client)
        _validate_availability_target(request)
        params = request.model_dump(by_alias=True, exclude_none=True)
        if request.usernames:
            params["usernames"] = ",".join(request.usernames)
        response = client.get_slots(params)
        return _success(response)
    except (CalComError, ValueError) as exc:
        return _failure(str(exc))


def _validate_availability_target(request: CheckAvailabilityInput) -> None:
    """Validate the mutually useful event-identification combinations."""
    if not any((request.event_type_id, request.event_type_slug, request.usernames)):
        raise ValueError(
            "Appointment scheduling is not configured for this assistant yet."
        )
    if request.event_type_slug and not (request.username or request.team_slug):
        raise ValueError("event_type_slug requires username or team_slug.")
    if request.usernames and (
        request.event_type_id
        or request.event_type_slug
        or request.username
        or request.team_slug
    ):
        raise ValueError(
            "usernames cannot be combined with event_type_id, event_type_slug, "
            "username, or team_slug."
        )


def _apply_default_event(
    request: CheckAvailabilityInput, client: CalComClient
) -> CheckAvailabilityInput:
    """Use the configured owner event when the caller did not supply one."""
    settings = client.settings
    if any((request.event_type_id, request.event_type_slug, request.usernames)):
        return request
    return request.model_copy(
        update={
            "event_type_id": settings.default_event_type_id,
            "event_type_slug": settings.default_event_type_slug,
            "username": request.username or settings.default_username,
            "team_slug": request.team_slug or settings.default_team_slug,
            "organization_slug": request.organization_slug
            or settings.default_organization_slug,
        }
    )


def _apply_default_range(
    request: CheckAvailabilityInput, client: CalComClient
) -> CheckAvailabilityInput:
    """Allow the caller to provide only a date or preferred start time."""
    if request.end:
        return request
    if len(request.start) == 10:
        # Cal.com interprets the same date as the full calendar day.
        return request.model_copy(update={"end": request.start})

    try:
        start = datetime.fromisoformat(request.start.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "start must be a YYYY-MM-DD date or UTC ISO 8601 date-time."
        ) from exc
    end = start + timedelta(minutes=client.settings.default_duration_minutes)
    return request.model_copy(
        update={"end": end.isoformat().replace("+00:00", "Z")}
    )


def _success(response: dict[str, Any]) -> str:
    return json.dumps({"success": True, "data": response}, ensure_ascii=False)


def _failure(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


__all__ = ["check_calcom_availability"]
