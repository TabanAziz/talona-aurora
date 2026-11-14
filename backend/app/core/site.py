"""Site time: the one place that turns a stored UTC moment into the local time a crew reads.

Events are stored in UTC; crews speak in site time. SITE_TIMEZONE overrides the default zone and every crew-facing
time goes through here, so a notice and a proposal summary can never disagree with what the crew reads elsewhere.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_SITE_TIMEZONE = "Europe/Berlin"


def zone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("SITE_TIMEZONE") or DEFAULT_SITE_TIMEZONE)


def local(moment: datetime) -> datetime:
    """The moment in site time; a naive moment is taken as already local, not shifted twice."""
    return moment.astimezone(zone()) if moment.tzinfo is not None else moment.replace(tzinfo=zone())
