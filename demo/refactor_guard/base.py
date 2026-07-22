from datetime import date


class ExpiredSubscriptionError(Exception):
    """Raised when a membership can no longer renew."""


def renew(expires_at: date, today: date) -> str:
    """Renew a membership; the end date itself is still inside the term."""
    if today > expires_at:
        raise ExpiredSubscriptionError(f"expired on {expires_at.isoformat()}")
    return "renewed"
