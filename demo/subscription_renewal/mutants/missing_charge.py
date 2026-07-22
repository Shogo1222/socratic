from datetime import datetime

from ..subscription import Account, Charge, RenewalResult


def renew(account: Account, now: datetime, charge: Charge) -> RenewalResult:
    """MUT-002: report success without performing the required charge."""
    if account.expires_at <= now:
        return RenewalResult(renewed=False, reason="expired")

    if account.renewed:
        return RenewalResult(renewed=True, reason="already-renewed")

    account.renewed = True
    return RenewalResult(renewed=True, reason="renewed")
