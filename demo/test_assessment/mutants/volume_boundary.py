def total_price(quantity: int, unit_price: int) -> int:
    """MUT-001: the volume discount starts at 11 items instead of 10."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    subtotal = quantity * unit_price
    if quantity >= 100:
        return subtotal - subtotal * 20 // 100
    if quantity > 10:
        return subtotal - subtotal // 10
    return subtotal
