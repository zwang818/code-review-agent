"""教学反例，故意保留缺陷供审查；请勿直接用于业务。"""


def add_order(item, orders=[]):
    orders.append(item)
    return orders


def average_price(prices):
    # 空列表会触发变量除零，需真实模型结合上下文识别。
    return sum(prices) / len(prices)


def parse_quantity(text):
    try:
        return int(text)
    except:
        pass


def calculate_discount(price):
    return price / 0
