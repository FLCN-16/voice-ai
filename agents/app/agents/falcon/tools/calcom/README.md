# Cal.com LangChain tools

This folder exposes two tools through Falcon's default tool collection:

- `check_calcom_availability`: calls `GET /v2/slots` and supports event IDs,
  event slugs, users, teams, dynamic group availability, date ranges, timezones,
  durations, response format, and rescheduling.
- `create_calcom_appointment`: calls `POST /v2/bookings` and supports regular,
  recurring, seated, dynamic-group, and instant booking fields, including
  attendee, location, guest, metadata, routing, verification, and booking-limit
  options.

## Configuration

Copy `.env.example` values into the project-root `.env` file:

```env
CALCOM_API_KEY=cal_...
CALCOM_API_BASE_URL=https://api.cal.com
CALCOM_SLOTS_API_VERSION=2024-09-04
CALCOM_BOOKINGS_API_VERSION=2026-02-25
CALCOM_TIMEOUT_SECONDS=20
CALCOM_DEFAULT_EVENT_TYPE_ID=123
CALCOM_DEFAULT_TIME_ZONE=UTC
CALCOM_DEFAULT_DURATION_MINUTES=30
```

`CALCOM_API_KEY` is read only when a tool is invoked. `CAL_API_KEY` is also
accepted as a compatibility alias. Platform integrations can additionally set
`CALCOM_CLIENT_ID` and `CALCOM_SECRET_KEY`.

Availability does not require the caller's email. Configure
`CALCOM_DEFAULT_EVENT_TYPE_ID`, or configure
`CALCOM_DEFAULT_EVENT_TYPE_SLUG` together with `CALCOM_DEFAULT_USERNAME` or
`CALCOM_DEFAULT_TEAM_SLUG`, so Falcon can check the owner's calendar directly.
With an event target and `CALCOM_DEFAULT_TIME_ZONE` configured, creating a
booking only asks Falcon for the start time, caller name, and caller email.
Timezone and all other Cal.com fields remain private defaults or internal
overrides.
For availability, callers can provide only a date or preferred start time.
`CALCOM_DEFAULT_DURATION_MINUTES` supplies the end time when one is not given.

The booking start and slot range values must be UTC ISO 8601 values. The tools
return JSON strings with either `success: true` and the Cal.com response or
`success: false` and an actionable error.
