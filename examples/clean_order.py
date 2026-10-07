"""与反例对应的修正版，便于检查是否出现明显误报。"""


def add_order(item, orders=None):
    result = [] if orders is None else list(orders)
    result.append(item)
    return result


def average_price(prices):
    if not prices:
        raise ValueError("prices must not be empty")
    return sum(prices) / len(prices)


def parse_quantity(text):
    try:
        quantity = int(text)
    except (ValueError, TypeError) as exc:
        raise ValueError("quantity must be an integer") from exc
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    return quantity
