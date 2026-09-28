from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCosts:
    """Configurable costs applied to an immediate cross-region trade.

    Sales tax applies to the sale proceeds. Broker fee is optional and is
    intended for strategies that create a non-immediate sell order; it is
    zero by default because this scanner currently sells into existing buy
    orders. Transport costs can be modeled as a flat trip cost plus an ISK
    cost per m3 per jump.
    """

    sales_tax_rate: float = 0.075
    broker_fee_rate: float = 0.0
    transport_flat_isk: float = 0.0
    transport_isk_per_m3_jump: float = 0.0
    safety_margin_rate: float = 0.0

    def validate(self) -> None:
        for name, value in (
            ("sales_tax_rate", self.sales_tax_rate),
            ("broker_fee_rate", self.broker_fee_rate),
            ("transport_flat_isk", self.transport_flat_isk),
            ("transport_isk_per_m3_jump", self.transport_isk_per_m3_jump),
            ("safety_margin_rate", self.safety_margin_rate),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.sales_tax_rate > 1 or self.broker_fee_rate > 1 or self.safety_margin_rate > 1:
            raise ValueError("rate values must be between 0 and 1")


def calculate_trade_costs(
    sell_revenue: float,
    volume_m3: float,
    jumps: int,
    costs: TradeCosts,
) -> dict[str, float]:
    costs.validate()
    jumps = max(0, int(jumps))

    sales_tax = sell_revenue * costs.sales_tax_rate
    broker_fee = sell_revenue * costs.broker_fee_rate
    transport = costs.transport_flat_isk + (
        volume_m3 * jumps * costs.transport_isk_per_m3_jump
    )
    safety_margin = (sales_tax + broker_fee + transport) * costs.safety_margin_rate

    return {
        "sales_tax": sales_tax,
        "broker_fee": broker_fee,
        "transport_cost": transport,
        "safety_margin": safety_margin,
        "total_costs": sales_tax + broker_fee + transport + safety_margin,
    }
