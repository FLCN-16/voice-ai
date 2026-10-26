"""Input schemas for Cal.com availability and booking tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_camel(value: str) -> str:
    """Convert Python field names to Cal.com's camelCase names."""
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class CalComModel(BaseModel):
    """Base model that emits Cal.com's camelCase field names."""

    model_config = ConfigDict(
        alias_generator=lambda name: _to_camel(name),
        populate_by_name=True,
        extra="forbid",
    )


class CheckAvailabilityInput(CalComModel):
    """All documented query parameters for GET /v2/slots."""

    start: str = Field(
        description="UTC ISO 8601 start date/time, or a date such as 2033-09-05.",
    )
    end: str | None = Field(
        default=None,
        description="Optional UTC end; defaults to the date end or configured duration.",
    )
    booking_uid_to_reschedule: str | None = Field(
        default=None,
        description="Existing booking UID to exclude while checking reschedule slots.",
    )
    organization_slug: str | None = None
    team_slug: str | None = None
    username: str | None = Field(
        default=None, description="Event owner's username when using event_type_slug."
    )
    event_type_slug: str | None = None
    event_type_id: int | None = None
    usernames: list[str] | None = Field(
        default=None,
        description="At least two usernames for a dynamic group availability check.",
    )
    format: Literal["time", "range"] | None = Field(
        default=None, description="Use range to receive each slot's start and end."
    )
    duration: int | None = Field(
        default=None,
        ge=1,
        description="Requested slot length in minutes for flexible/dynamic event types.",
    )
    time_zone: str | None = Field(
        default=None,
        description="IANA timezone for returned slots, such as America/New_York.",
    )

    @field_validator("usernames")
    @classmethod
    def validate_usernames(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) < 2:
            raise ValueError("usernames must contain at least two usernames.")
        return value


class AvailabilityToolInput(BaseModel):
    """Minimal input exposed to Falcon for an availability request."""

    start: str = Field(
        description="The caller's requested date or start time in ISO 8601 format."
    )
    end: str | None = Field(
        default=None,
        description="Optional end time; omit this for a single requested slot or date.",
    )


class AttendeeInput(CalComModel):
    """Attendee fields accepted by the create-booking endpoint."""

    name: str = Field(description="Attendee's full name.")
    email: str = Field(description="Attendee's email address.")
    time_zone: str | None = Field(
        default=None,
        description="Attendee's IANA timezone; defaults to CALCOM_DEFAULT_TIME_ZONE.",
    )
    phone_number: str | None = Field(
        default=None, description="International phone number, required for SMS workflows."
    )
    language: str | None = Field(
        default=None, description="Attendee's preferred confirmation language, such as en."
    )


class LocationInput(CalComModel):
    """Union-compatible location fields accepted by Cal.com."""

    type: Literal[
        "address",
        "attendeeAddress",
        "attendeeDefined",
        "attendeePhone",
        "integration",
        "link",
        "phone",
        "organizersDefaultApp",
    ] = Field(description="Cal.com location type.")
    address: str | None = None
    location: str | None = None
    phone: str | None = None
    integration: str | None = Field(
        default=None,
        description="Integration slug, for example cal-video, google-meet, or zoom.",
    )


class RoutingInput(CalComModel):
    """Routing-form and CRM assignment fields accepted by Cal.com."""

    queued_response_id: str | None = None
    response_id: int | None = None
    team_member_ids: list[int] | None = None
    team_member_email: str | None = None
    skip_contact_owner: bool | None = None
    crm_app_slug: str | None = None
    crm_owner_record_type: str | None = None
    crm_record_owner_fallback_team_member_ids: list[int] | None = None
    crm_record_owner_fallback_mode: Literal["relationship", "attributeRules"] | None = None


class CreateBookingInput(CalComModel):
    """All documented fields for POST /v2/bookings."""

    start: str = Field(description="Booking start in UTC ISO 8601 format.")
    attendee: AttendeeInput = Field(description="The required attendee details.")
    booking_fields_responses: dict[str, Any] | None = Field(
        default=None,
        description="Custom booking-field answers keyed by field slug.",
    )
    lead_enrichment_opt_out: bool | None = None
    event_type_id: int | None = None
    event_type_slug: str | None = None
    username: str | None = None
    team_slug: str | None = None
    organization_slug: str | None = None
    usernames: list[str] | None = Field(
        default=None,
        description="Two to twenty hosts for a dynamic group booking.",
    )
    guests: list[str] | None = None
    meeting_url: str | None = Field(
        default=None, description="Deprecated Cal.com meeting URL override."
    )
    location: LocationInput | None = None
    metadata: dict[str, str] | None = None
    length_in_minutes: int | None = Field(default=None, ge=1)
    routing: RoutingInput | None = None
    email_verification_code: str | None = None
    allow_conflicts: bool | None = None
    allow_booking_out_of_bounds: bool | None = None
    skip_booking_limits: bool | None = None
    instant: bool | None = Field(
        default=None, description="Create an instant team booking when true."
    )
    recurrence_count: int | None = Field(default=None, ge=1, le=32)

    @field_validator("usernames")
    @classmethod
    def validate_usernames(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not 2 <= len(value) <= 20:
            raise ValueError("usernames must contain between two and twenty usernames.")
        return value


class CreateAppointmentToolInput(BaseModel):
    """Minimal input exposed to Falcon for creating an appointment."""

    start: str = Field(description="Confirmed appointment start time in ISO 8601 format.")
    name: str = Field(description="Caller's full name.")
    email: str = Field(description="Caller's email address.")
