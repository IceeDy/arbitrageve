def max_affordable_quantity(capital_isk, unit_price):
    return int(capital_isk // unit_price) if unit_price > 0 else 0
