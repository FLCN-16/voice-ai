"""LangChain tool for creating Cal.com appointments."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from .client import CalComClient, CalComError
from .models import AttendeeInput, CreateAppointmentToolInput, CreateBookingInput


@tool(args_schema=CreateAppointmentToolInput)
def create_calcom_appointment(**kwargs: Any) -> str:
    """Create a Cal.com appointment after the caller has confirmed its details.

    The event type, owner calendar, and timezone are configured privately in
    the application environment. Never ask the caller for those internal
    Cal.com values.
    """
    try:
        tool_input = CreateAppointmentToolInput.model_validate(kwargs)
        request = CreateBookingInput(
            start=tool_input.start,
            attendee=AttendeeInput(name=tool_input.name, email=tool_input.email),
        )
        client = CalComClient()
        request = _apply_defaults(request, client)
        _validate_booking_target(request)
        payload = request.model_dump(by_alias=True, exclude_none=True)
        response = client.create_booking(payload)
        return _success(response)
    except (CalComError, ValueError) as exc:
        return _failure(str(exc))


def _validate_booking_target(request: CreateBookingInput) -> None:
    """Validate the documented event-identification combinations."""
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


def _apply_defaults(
    request: CreateBookingInput, client: CalComClient
) -> CreateBookingInput:
    """Fill the configured event and attendee timezone defaults."""
    settings = client.settings
    attendee = request.attendee
    if attendee.time_zone is None:
        attendee = attendee.model_copy(update={"time_zone": settings.default_time_zone})

    if any((request.event_type_id, request.event_type_slug, request.usernames)):
        return request.model_copy(update={"attendee": attendee})
    return request.model_copy(
        update={
            "attendee": attendee,
            "event_type_id": settings.default_event_type_id,
            "event_type_slug": settings.default_event_type_slug,
            "username": request.username or settings.default_username,
            "team_slug": request.team_slug or settings.default_team_slug,
            "organization_slug": request.organization_slug
            or settings.default_organization_slug,
        }
    )


def _success(response: dict[str, Any]) -> str:
    return json.dumps({"success": True, "data": response}, ensure_ascii=False)


def _failure(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


__all__ = ["create_calcom_appointment"]
