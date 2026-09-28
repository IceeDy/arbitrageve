import pytest

from arbitrageve.market.costs import TradeCosts, calculate_trade_costs


def test_trade_costs():
    costs = calculate_trade_costs(
        sell_revenue=1_500,
        volume_m3=10,
        jumps=5,
        costs=TradeCosts(
            sales_tax_rate=0.10,
            broker_fee_rate=0.02,
            transport_flat_isk=50,
            transport_isk_per_m3_jump=1,
        ),
    )
    assert costs["sales_tax"] == 150
    assert costs["broker_fee"] == 30
    assert costs["transport_cost"] == 100
    assert costs["total_costs"] == 280


def test_cost_rates_are_validated():
    with pytest.raises(ValueError):
        TradeCosts(sales_tax_rate=1.1).validate()
