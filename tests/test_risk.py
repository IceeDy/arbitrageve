from arbitrageve.db.models import SolarSystem
from arbitrageve.market.metrics import ExecutionProfile, estimate_isk_per_hour
from arbitrageve.services.risk import RiskProfile, analyze_route, route_allowed


def test_route_risk_classification():
    systems = [
        SolarSystem(system_id=1, name="High", security_status=0.9),
        SolarSystem(system_id=2, name="Low", security_status=0.3),
        SolarSystem(system_id=3, name="Null", security_status=0.0),
    ]
    analysis = analyze_route(systems, jumps=2)
    assert analysis["route_class"] == "nullsec"
    assert analysis["highsec_systems"] == 1
    assert analysis["lowsec_systems"] == 1
    assert analysis["nullsec_systems"] == 1
    assert analysis["min_security_status"] == 0.0
    assert analysis["route_known"] is True


def test_risk_profile_blocks_nullsec_and_excess_jumps():
    analysis = analyze_route(
        [SolarSystem(system_id=1, name="Null", security_status=0.0)],
        jumps=12,
    )
    analysis["jumps"] = 12
    assert not route_allowed(RiskProfile(allow_nullsec=False), analysis)
    assert not route_allowed(RiskProfile(max_jumps=10), analysis)


def test_execution_profile_calculates_isk_per_hour():
    profile = ExecutionProfile(fixed_minutes=10, minutes_per_jump=2, return_trip=False)
    assert estimate_isk_per_hour(120_000, 5, profile) == 360_000

    return_profile = ExecutionProfile(fixed_minutes=10, minutes_per_jump=2, return_trip=True)
    assert estimate_isk_per_hour(120_000, 5, return_profile) == 180_000
