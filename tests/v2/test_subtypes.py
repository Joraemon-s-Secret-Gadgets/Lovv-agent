from __future__ import annotations

import json
from pathlib import Path

from lovv_agent_v2.common.subtypes import subtype_label, subtype_name


def test_subtype_mapping_returns_tour_api_attraction_names() -> None:
    assert subtype_name("NA020900") == "해변. 해수욕장"
    assert subtype_label("NA020900") == "자연관광 > 자연경관(하천‧해양) > 해변. 해수욕장"
    assert subtype_label("UNKNOWN") == "UNKNOWN"


def test_subtype_resource_does_not_store_derived_label() -> None:
    path = Path("src/lovv_agent_v2/resources/attraction_subtypes.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert "label" not in data["NA020900"]
