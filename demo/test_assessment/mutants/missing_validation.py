def total_price(quantity: int, unit_price: int) -> int:
    """MUT-003: a negative quantity is silently accepted."""
    subtotal = quantity * unit_price
    if quantity >= 100:
        return subtotal - subtotal * 20 // 100
    if quantity >= 10:
        return subtotal - subtotal // 10
    return subtotal
