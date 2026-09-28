from arbitrageve.market.arbitrage import calculate_opportunity

def test_calculate_opportunity():
    result = calculate_opportunity(34,10,15,10,0.1)
    assert result.gross_profit == 50
    assert result.roi == 0.5
