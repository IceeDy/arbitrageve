import json
import zipfile

from arbitrageve.db.database import Base
from arbitrageve.db.models import Item, Stargate
from arbitrageve.sde.loader import (
    inspect_types_archive,
    load_stargates_from_archive,
    load_types,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


def _make_sde(tmp_path, records):
    archive_path = tmp_path / "sde.zip"
    types_path = tmp_path / "types.jsonl"
    types_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(types_path, "types.jsonl")
    return archive_path


def test_load_types_current_object_shape(tmp_path):
    archive_path = _make_sde(
        tmp_path,
        [
            {"_key": 34, "name": {"en": "Tritanium"}, "volume": 0.01},
            {"_key": 35, "name": {"en": "Pyerite"}, "volume": 0.01},
        ],
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    assert load_types(archive_path, session) == 2
    assert session.scalar(select(Item).where(Item.type_id == 34)).name == "Tritanium"


def test_inspect_types_archive(tmp_path):
    archive_path = _make_sde(
        tmp_path,
        [{"_key": 34, "name": {"en": "Tritanium"}, "volume": 0.01}],
    )

    result = inspect_types_archive(archive_path)

    assert result["sample_lines"] == 1
    assert result["sample_keyed"] == 1
    assert result["sample_named"] == 1


def test_load_stargates_current_object_shape(tmp_path):
    archive_path = tmp_path / "sde.zip"
    stargates_path = tmp_path / "mapStargates.jsonl"
    stargates_path.write_text(
        json.dumps(
            {
                "_key": 50000001,
                "solarSystemID": 30000001,
                "destination": {
                    "solarSystemID": 30000002,
                    "stargateID": 50000002,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(stargates_path, "mapStargates.jsonl")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    assert load_stargates_from_archive(archive_path, session) == 1
    gate = session.get(Stargate, 50000001)
    assert gate.system_id == 30000001
    assert gate.destination_system_id == 30000002


from arbitrageve.db.models import SolarSystem


def test_security_class():
    assert SolarSystem(system_id=1, name="High", security_status=0.9).security_class == "highsec"
    assert SolarSystem(system_id=2, name="Low", security_status=0.3).security_class == "lowsec"
    assert SolarSystem(system_id=3, name="Null", security_status=0.0).security_class == "nullsec"
