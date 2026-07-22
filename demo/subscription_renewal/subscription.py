from dataclasses import dataclass
from datetime import datetime
from typing import Callable


Charge = Callable[[str], None]


@dataclass
class Account:
    account_id: str
    expires_at: datetime
    renewed: bool = False


@dataclass(frozen=True)
class RenewalResult:
    renewed: bool
    reason: str


def renew(account: Account, now: datetime, charge: Charge) -> RenewalResult:
    """Renew an eligible account once, with exactly one charge."""
    if account.expires_at <= now:
        return RenewalResult(renewed=False, reason="expired")

    if account.renewed:
        return RenewalResult(renewed=True, reason="already-renewed")

    charge(account.account_id)
    account.renewed = True
    return RenewalResult(renewed=True, reason="renewed")
