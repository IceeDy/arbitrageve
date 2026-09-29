import json
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from arbitrageve.db.database import Base
from arbitrageve.db.models import Item, Region, SolarSystem, Stargate
from arbitrageve.sde.loader import (
from tests.db import create_test_engine
    inspect_types_archive,
    load_regions_from_archive,
    load_solar_systems_from_archive,
    load_stargates_from_archive,
    load_types,
)


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

    engine = create_test_engine()
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

    engine = create_test_engine()
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    assert load_stargates_from_archive(archive_path, session) == 1
    gate = session.get(Stargate, 50000001)
    assert gate.system_id == 30000001
    assert gate.destination_system_id == 30000002


def test_security_class():
    assert SolarSystem(system_id=1, name="High", security_status=0.9).security_class == "highsec"
    assert SolarSystem(system_id=2, name="Low", security_status=0.3).security_class == "lowsec"
    assert SolarSystem(system_id=3, name="Null", security_status=0.0).security_class == "nullsec"


def _make_jsonl_archive(tmp_path, member_name, records):
    archive_path = tmp_path / f"{member_name}.zip"
    source = tmp_path / member_name
    source.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(source, member_name)
    return archive_path


def test_load_regions_from_archive(tmp_path):
    archive_path = _make_jsonl_archive(
        tmp_path,
        "mapRegions.jsonl",
        [{"_key": 10000002, "name": {"en": "The Forge"}}],
    )

    engine = create_test_engine()
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    assert load_regions_from_archive(archive_path, session) == 1
    assert session.get(Region, 10000002).name == "The Forge"


def test_load_solar_systems_includes_region(tmp_path):
    archive_path = _make_jsonl_archive(
        tmp_path,
        "mapSolarSystems.jsonl",
        [
            {
                "_key": 30000142,
                "name": {"en": "Jita"},
                "regionID": 10000002,
                "securityStatus": 0.945,
            }
        ],
    )

    engine = create_test_engine()
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    assert load_solar_systems_from_archive(archive_path, session) == 1
    system = session.get(SolarSystem, 30000142)
    assert system.region_id == 10000002
