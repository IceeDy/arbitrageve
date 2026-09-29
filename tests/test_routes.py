from sqlalchemy.orm import sessionmaker

from arbitrageve.db.database import Base
from arbitrageve.db.models import SolarSystem, Stargate
from arbitrageve.sde.routes import LocalRouteClient


from tests.db import create_test_engine


def _session():
    engine = create_test_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_systems(session, *systems):
    session.add_all(
        SolarSystem(system_id=sid, name=name, security_status=security)
        for sid, name, security in systems
    )


def test_local_route_shorter_uses_fewest_jumps():
    session = _session()
    _add_systems(
        session,
        (1, "A", 1.0),
        (2, "B", 1.0),
        (3, "C", 1.0),
        (4, "D", 1.0),
        (5, "E", 1.0),
    )
    session.add_all([
        Stargate(stargate_id=10, system_id=1, destination_system_id=2),
        Stargate(stargate_id=11, system_id=2, destination_system_id=1),
        Stargate(stargate_id=12, system_id=2, destination_system_id=5),
        Stargate(stargate_id=13, system_id=5, destination_system_id=2),
        Stargate(stargate_id=18, system_id=5, destination_system_id=3),
        Stargate(stargate_id=19, system_id=3, destination_system_id=5),
        Stargate(stargate_id=14, system_id=1, destination_system_id=4),
        Stargate(stargate_id=15, system_id=4, destination_system_id=1),
        Stargate(stargate_id=16, system_id=4, destination_system_id=3),
        Stargate(stargate_id=17, system_id=3, destination_system_id=4),
    ])
    session.commit()

    route = LocalRouteClient(session).route(1, 3, "Shorter", 50)

    assert route == [1, 4, 3]


def test_local_route_safer_prefers_highsec_over_short_lowsec():
    session = _session()
    _add_systems(
        session,
        (1, "Origin", 0.9),
        (2, "Low", 0.3),
        (3, "High", 0.9),
        (4, "Destination", 0.9),
    )
    session.add_all([
        Stargate(stargate_id=10, system_id=1, destination_system_id=2),
        Stargate(stargate_id=11, system_id=2, destination_system_id=1),
        Stargate(stargate_id=12, system_id=2, destination_system_id=4),
        Stargate(stargate_id=13, system_id=4, destination_system_id=2),
        Stargate(stargate_id=14, system_id=1, destination_system_id=3),
        Stargate(stargate_id=15, system_id=3, destination_system_id=1),
        Stargate(stargate_id=16, system_id=3, destination_system_id=4),
        Stargate(stargate_id=17, system_id=4, destination_system_id=3),
    ])
    session.commit()

    route = LocalRouteClient(session).route(1, 4, "Safer", 50)

    assert route == [1, 3, 4]


def test_local_route_returns_empty_when_disconnected():
    session = _session()
    _add_systems(
        session,
        (1, "A", 0.9),
        (2, "B", 0.9),
    )
    session.commit()

    assert LocalRouteClient(session).route(1, 2) == []
