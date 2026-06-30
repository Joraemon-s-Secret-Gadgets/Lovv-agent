from __future__ import annotations

import argparse
import json
from pathlib import Path

from lovv_agent_v2.models.city_identity import (
    DEFAULT_CITY_IDENTITY_MAP_PATH,
    DEFAULT_CITY_METADATA_PATH,
    build_city_identity_map_from_metadata,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact V2 city identity map")
    parser.add_argument("--metadata", default=str(DEFAULT_CITY_METADATA_PATH))
    parser.add_argument("--out", default=str(DEFAULT_CITY_IDENTITY_MAP_PATH))
    args = parser.parse_args()

    compact = build_city_identity_map_from_metadata(Path(args.metadata))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path} with {compact['city_count']} cities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
