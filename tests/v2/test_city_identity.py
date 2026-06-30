from __future__ import annotations

import json
from pathlib import Path

from lovv_agent_v2.models.city_identity import (
    CityIdentity,
    CityIdentityMap,
    build_city_identity_map_from_metadata,
    enrich_city_select_identity,
    load_city_identity_map,
)


def _metadata_path(tmp_path: Path) -> Path:
    payload = {
        "records": [
            {
                "metadata": {
                    "country": "KR",
                    "province": "경상남도",
                    "city_id": "KR-36-4",
                    "ddb_pk": "CITY#GIMHAE",
                    "city_name_ko": "김해시",
                    "city_name_en": "GIMHAE",
                    "entity_type": "attraction",
                },
            },
            {
                "metadata": {
                    "country": "KR",
                    "province": "전북특별자치도",
                    "city_id": "KR-35-11",
                    "ddb_pk": "CITY#JEONJU",
                    "city_name_ko": "전주시",
                    "city_name_en": "JEONJU",
                    "entity_type": "festival",
                },
            },
        ],
    }
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _compact_map_path(tmp_path: Path) -> Path:
    payload = {
        "cities": [
            {
                "country": "KR",
                "province": "경상남도",
                "city_id": "KR-36-4",
                "ddb_pk": "CITY#GIMHAE",
                "city_key": "CITY#GIMHAE",
                "city_name_ko": "김해시",
                "city_name_en": "GIMHAE",
            },
        ],
    }
    path = tmp_path / "city_identity_map.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_city_identity_map_loads_compact_city_id_pk_and_names(tmp_path: Path) -> None:
    city_map = load_city_identity_map(_compact_map_path(tmp_path))

    assert city_map.require("KR-36-4").ddb_pk == "CITY#GIMHAE"
    assert city_map.require("CITY#GIMHAE").city_id == "KR-36-4"
    assert city_map.require("김해시").city_name_en == "GIMHAE"
    assert city_map.require("gimhae").city_name_ko == "김해시"


def test_build_city_identity_map_from_metadata_outputs_compact_cities(
    tmp_path: Path,
) -> None:
    compact = build_city_identity_map_from_metadata(_metadata_path(tmp_path))

    assert compact["city_count"] == 2
    assert compact["cities"][0]["city_key"] == compact["cities"][0]["ddb_pk"]


def test_enrich_city_select_identity_preserves_destination_id_and_adds_city_key() -> None:
    city_map = CityIdentityMap(
        (
            CityIdentity(
                city_id="KR-36-4",
                ddb_pk="CITY#GIMHAE",
                city_name_ko="김해시",
                city_name_en="GIMHAE",
                province="경상남도",
                country="KR",
            ),
        ),
    )

    enriched = enrich_city_select_identity(
        {"destination_id": "KR-36-4"},
        city_map=city_map,
    )

    assert enriched["destination_id"] == "KR-36-4"
    assert enriched["city_key"] == "CITY#GIMHAE"
    assert enriched["ddb_pk"] == "CITY#GIMHAE"
    assert enriched["destination_label"] == "김해시"
