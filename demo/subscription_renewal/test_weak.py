import unittest
from datetime import datetime, timedelta, timezone

from .test_support import load_implementation


class WeakRenewalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.impl = load_implementation()
        self.now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

    def test_rejects_an_account_that_expired_yesterday(self) -> None:
        account = self.impl.Account("acct-expired", self.now - timedelta(days=1))

        result = self.impl.renew(account, self.now, lambda _: None)

        self.assertFalse(result.renewed)
        self.assertEqual("expired", result.reason)

    def test_renews_an_eligible_account(self) -> None:
        account = self.impl.Account("acct-active", self.now + timedelta(days=1))

        result = self.impl.renew(account, self.now, lambda _: None)

        self.assertTrue(result.renewed)


if __name__ == "__main__":
    unittest.main()
