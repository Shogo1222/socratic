from datetime import datetime

from ..subscription import Account, Charge, RenewalResult


def renew(account: Account, now: datetime, charge: Charge) -> RenewalResult:
    """MUT-001: treat the exact expiry instant as still eligible."""
    if account.expires_at < now:
        return RenewalResult(renewed=False, reason="expired")

    if account.renewed:
        return RenewalResult(renewed=True, reason="already-renewed")

    charge(account.account_id)
    account.renewed = True
    return RenewalResult(renewed=True, reason="renewed")
