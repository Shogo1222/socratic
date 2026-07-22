import unittest

from .cohort_support import load_implementation


class ChangedPricingTests(unittest.TestCase):
    """The suite after an AI 'cleaned it up': one strong test added, one weakened, one deleted.

    The exact boundary assertion at ten items became a vague 'some discount'
    check, and the negative-quantity test was removed as 'redundant'.
    """

    def setUp(self) -> None:
        self.impl = load_implementation()

    def test_small_order_pays_full_price(self) -> None:
        self.assertEqual(500, self.impl.total_price(5, 100))

    def test_volume_orders_get_some_discount(self) -> None:
        self.assertLess(self.impl.total_price(12, 100), 1200)

    def test_bulk_discount_at_one_hundred_items(self) -> None:
        self.assertEqual(8000, self.impl.total_price(100, 100))


if __name__ == "__main__":
    unittest.main()
