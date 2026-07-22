import unittest
from datetime import datetime, timedelta, timezone

from .test_support import load_implementation


class HardenedRenewalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.impl = load_implementation()
        self.now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

    def test_rejects_an_account_at_the_exact_expiry_boundary_without_charging(self) -> None:
        account = self.impl.Account("acct-boundary", self.now)
        charges: list[str] = []

        result = self.impl.renew(account, self.now, charges.append)

        self.assertFalse(result.renewed)
        self.assertEqual("expired", result.reason)
        self.assertFalse(account.renewed)
        self.assertEqual([], charges)

    def test_eligible_renewal_charges_exactly_once_and_updates_state(self) -> None:
        account = self.impl.Account("acct-active", self.now + timedelta(days=1))
        charges: list[str] = []

        result = self.impl.renew(account, self.now, charges.append)

        self.assertTrue(result.renewed)
        self.assertEqual("renewed", result.reason)
        self.assertTrue(account.renewed)
        self.assertEqual(["acct-active"], charges)

    def test_repeated_renewal_is_idempotent(self) -> None:
        account = self.impl.Account("acct-retry", self.now + timedelta(days=1))
        charges: list[str] = []

        first = self.impl.renew(account, self.now, charges.append)
        second = self.impl.renew(account, self.now, charges.append)

        self.assertTrue(first.renewed)
        self.assertEqual("already-renewed", second.reason)
        self.assertEqual(["acct-retry"], charges)


if __name__ == "__main__":
    unittest.main()
