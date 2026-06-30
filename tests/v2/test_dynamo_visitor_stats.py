from __future__ import annotations

from typing import Any

from lovv_agent_v2.infra.config import DynamoDbSettings
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository


class RecordingBatchGetClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def batch_get_item(self, **request: Any) -> dict[str, Any]:
        self.requests.append(dict(request))
        return {
            "Responses": {
                "lovv-table": (
                    {
                        "PK": {"S": "CITY#DONGHAE"},
                        "SK": {"S": "STAT#202509"},
                        "statistics": {"M": {"total_visitors": {"N": "3133861.39"}}},
                    },
                ),
            },
        }


def test_batch_get_city_visitor_stats_preserves_v2_uppercase_city_pk() -> None:
    client = RecordingBatchGetClient()
    repository = DynamoDbRepository(
        client=client,
        settings=DynamoDbSettings(table_name="lovv-table"),
    )

    result = repository.batch_get_city_visitor_stats(
        city_ids=("CITY#DONGHAE",),
        travel_month=9,
        partition_key_by_city={"CITY#DONGHAE": "CITY#DONGHAE"},
    )

    request = client.requests[0]
    requested_key = request["RequestItems"]["lovv-table"]["Keys"][0]
    assert requested_key["PK"]["S"] == "CITY#DONGHAE"
    assert requested_key["SK"]["S"] == "STAT#202509"
    assert result == {"CITY#DONGHAE": 3133861.39}
