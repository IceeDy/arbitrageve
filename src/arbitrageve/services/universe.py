from sqlalchemy.orm import Session

from arbitrageve.db.models import SolarSystem
from arbitrageve.esi.universe import UniverseClient


def ensure_system(session: Session, system_id: int, client: UniverseClient | None = None) -> SolarSystem:
    system = session.get(SolarSystem, system_id)
    if system:
        return system

    client = client or UniverseClient()
    data = client.get_system(system_id)
    system = SolarSystem(
        system_id=system_id,
        name=data["name"],
        security_status=float(data.get("security_status", 0)),
    )
    session.add(system)
    session.commit()
    return system
