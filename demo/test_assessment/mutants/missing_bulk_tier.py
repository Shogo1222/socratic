def total_price(quantity: int, unit_price: int) -> int:
    """MUT-004: bulk orders fall back to the 10% discount instead of 20%."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    subtotal = quantity * unit_price
    if quantity >= 10:
        return subtotal - subtotal // 10
    return subtotal
