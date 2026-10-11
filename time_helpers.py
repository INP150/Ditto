"""Helpers for parsing and formatting the point in time a reminder is due."""

import re
from datetime import datetime, timedelta, timezone

# "30m", "2h", "1d", "90s" - used for relative times in text arguments.
DURATION_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)

# Unix timestamps since 2001 have at least 10 digits, far more minutes than anyone types.
UNIX_TIMESTAMP_MIN_DIGITS = 10

DURATION_SUFFIX_MULTIPLIERS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
}


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Attach UTC to naive datetimes so aware and naive values can be compared."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_duration_to_seconds(value: str) -> int | None:
    """Parse a duration like "45", "90s", "2h" or "1d" into seconds.

    A bare number is treated as minutes, matching `repeat_every`'s default unit.
    Returns None when the value cannot be parsed.
    """
    value = value.strip()
    if not value:
        return None

    if value.isdigit():
        return int(value) * 60

    match = DURATION_RE.match(value)
    if match is None:
        return None

    amount, suffix = match.groups()
    return int(amount) * DURATION_SUFFIX_MULTIPLIERS[suffix.lower()]


def parse_when(value: str, *, now: datetime | None = None) -> datetime | None:
    """Parse when the first reminder should fire.

    Accepts a relative duration ("30m", "2h", "+1d"), a Unix timestamp, an ISO
    date/datetime ("2026-03-01", "2026-03-01T18:30") or "today"/"tomorrow".
    Returns None when the value cannot be parsed.
    """
    now = ensure_utc(now) if now is not None else utc_now()
    value = value.strip()
    if not value:
        return None

    # Checked before durations, which read a bare number as minutes.
    if value.isdigit() and len(value) >= UNIX_TIMESTAMP_MIN_DIGITS:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)

    duration = parse_duration_to_seconds(value.removeprefix("+"))
    if duration is not None:
        return now + timedelta(seconds=duration)

    lowered = value.lower()
    if lowered in ("today", "tomorrow"):
        day = now + timedelta(days=1 if lowered == "tomorrow" else 0)
        return day.replace(hour=9, minute=0, second=0, microsecond=0)

    iso = value.replace(" ", "T", 1) if " " in value and "T" not in value else value
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None

    return ensure_utc(parsed)


def format_duration(seconds: int) -> str:
    """Format a number of seconds as a short human readable duration."""
    if seconds <= 0:
        return "never"

    units = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    parts = []
    for suffix, size in units:
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{suffix}")
    return " ".join(parts)


def format_when(dt: datetime) -> str:
    """Format a datetime for display in Discord using its timestamp markup."""
    return f"<t:{int(ensure_utc(dt).timestamp())}:f>"
