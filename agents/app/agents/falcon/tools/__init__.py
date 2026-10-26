"""Tool collection exposed to the Falcon agent."""

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from ...common_tools import get_common_tools, hangup_call
from .calcom import check_calcom_availability, create_calcom_appointment
from .time import get_current_time


def get_tools() -> Sequence[BaseTool]:
    """Return the tools bound to every default Falcon model instance."""
    return (
        *get_common_tools(),
        get_current_time,
        check_calcom_availability,
        create_calcom_appointment,
    )


__all__ = [
    "check_calcom_availability",
    "create_calcom_appointment",
    "get_current_time",
    "get_tools",
    "hangup_call",
]
