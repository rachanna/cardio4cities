"""Calendar arithmetic used by the rules. Pure: the caller passes `today`."""

from datetime import date


def years_before(day: date, years: int) -> date:
    """The same calendar day `years` earlier; 29 February falls back to 28 February."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def months_between(a: date, b: date) -> int:
    """Whole calendar months from the earlier date to the later one."""
    early, late = sorted((a, b))
    months = (late.year - early.year) * 12 + (late.month - early.month)
    return months - 1 if late.day < early.day else months
