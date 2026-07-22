from datetime import date

from .base import ExpiredSubscriptionError


def _is_active(expires_at: date, today: date) -> bool:
    return today < expires_at


def renew(expires_at: date, today: date) -> str:
    """Presented as a readability refactoring of base.renew.

    Extracting _is_active silently flipped the boundary: on the exact end
    date the membership is now treated as expired.
    """
    if not _is_active(expires_at, today):
        raise ExpiredSubscriptionError(f"expired on {expires_at.isoformat()}")
    return "renewed"
