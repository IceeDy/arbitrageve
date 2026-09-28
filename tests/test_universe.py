from arbitrageve.db.models import SolarSystem


def test_security_class():
    assert SolarSystem(system_id=1, name="High", security_status=0.9).security_class == "highsec"
    assert SolarSystem(system_id=2, name="Low", security_status=0.3).security_class == "lowsec"
    assert SolarSystem(system_id=3, name="Null", security_status=0.0).security_class == "nullsec"
