from datetime import datetime

from ..subscription import Account, Charge, RenewalResult


def renew(account: Account, now: datetime, charge: Charge) -> RenewalResult:
    """MUT-003: charge again when the same renewal is retried."""
    if account.expires_at <= now:
        return RenewalResult(renewed=False, reason="expired")

    charge(account.account_id)
    account.renewed = True
    return RenewalResult(renewed=True, reason="renewed")
