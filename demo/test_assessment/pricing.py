def total_price(quantity: int, unit_price: int) -> int:
    """Total with a 10% volume discount from 10 items and 20% from 100 items."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    subtotal = quantity * unit_price
    if quantity >= 100:
        return subtotal - subtotal * 20 // 100
    if quantity >= 10:
        return subtotal - subtotal // 10
    return subtotal
