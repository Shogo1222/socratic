def total_price(quantity: int, unit_price: int) -> int:
    """MUT-002: the 10% volume discount is omitted entirely."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    subtotal = quantity * unit_price
    if quantity >= 100:
        return subtotal - subtotal * 20 // 100
    return subtotal
