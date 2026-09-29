from arbitrageve.services.opportunities import _deduplicate_opportunities


def test_deduplicate_opportunities_keeps_best_execution_per_system_lane():
    results = [
        {
            "type_id": 34,
            "source_system_id": 100,
            "destination_system_id": 200,
            "source_location_id": 1,
            "destination_location_id": 2,
            "net_profit": 1_000_000,
        },
        {
            "type_id": 34,
            "source_system_id": 100,
            "destination_system_id": 200,
            "source_location_id": 3,
            "destination_location_id": 4,
            "net_profit": 1_200_000,
        },
        {
            "type_id": 35,
            "source_system_id": 100,
            "destination_system_id": 200,
            "net_profit": 900_000,
        },
        {
            "type_id": 34,
            "source_system_id": 101,
            "destination_system_id": 200,
            "net_profit": 800_000,
        },
    ]

    deduplicated = _deduplicate_opportunities(results)

    assert len(deduplicated) == 3
    assert any(
        row["type_id"] == 34
        and row["source_system_id"] == 100
        and row["net_profit"] == 1_200_000
        for row in deduplicated
    )


def test_deduplicate_opportunities_respects_sort_metric():
    results = [
        {
            "type_id": 34,
            "source_system_id": 100,
            "destination_system_id": 200,
            "net_profit": 2_000_000,
            "roi": 0.20,
        },
        {
            "type_id": 34,
            "source_system_id": 100,
            "destination_system_id": 200,
            "net_profit": 1_000_000,
            "roi": 0.50,
        },
    ]

    deduplicated = _deduplicate_opportunities(results, sort_by="roi")

    assert len(deduplicated) == 1
    assert deduplicated[0]["roi"] == 0.50
