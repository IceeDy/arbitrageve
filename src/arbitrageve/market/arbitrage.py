from dataclasses import dataclass


@dataclass(frozen=True)
class Opportunity:
    type_id: int
    buy_price: float
    sell_price: float
    quantity: int
    gross_profit: float
    net_profit: float
    roi: float
    volume_m3: float


def calculate_opportunity(
    type_id: int,
    buy_price: float,
    sell_price: float,
    quantity: int,
    volume_m3: float,
    costs: float = 0,
) -> Opportunity:
    gross = (sell_price - buy_price) * quantity
    net = gross - costs
    invested = buy_price * quantity
    return Opportunity(
        type_id=type_id,
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
        gross_profit=gross,
        net_profit=net,
        roi=net / invested if invested else 0,
        volume_m3=volume_m3 * quantity,
    )
