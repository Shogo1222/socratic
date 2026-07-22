import unittest
from datetime import date

from .base import ExpiredSubscriptionError
from .probe_support import load_implementation


class RenewalBehaviorProbes(unittest.TestCase):
    """Behavior probes generated against Base; each observes output only."""

    def setUp(self) -> None:
        self.impl = load_implementation()
        self.expires_at = date(2026, 7, 31)

    def test_renews_well_before_the_end_date(self) -> None:
        self.assertEqual("renewed", self.impl.renew(self.expires_at, date(2026, 7, 1)))

    def test_rejects_well_after_the_end_date(self) -> None:
        with self.assertRaises(ExpiredSubscriptionError):
            self.impl.renew(self.expires_at, date(2026, 8, 15))

    def test_renews_on_the_exact_end_date(self) -> None:
        self.assertEqual("renewed", self.impl.renew(self.expires_at, self.expires_at))


if __name__ == "__main__":
    unittest.main()
