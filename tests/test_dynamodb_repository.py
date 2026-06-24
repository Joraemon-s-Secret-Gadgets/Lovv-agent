from __future__ import annotations

import unittest
from typing import Any

from lovv_agent.config import DynamoDbSettings
from lovv_agent.repositories.dynamodb import DynamoDbRepository


class RecordingDynamoDbClient:
    def __init__(self) -> None:
        self.get_item_requests: list[dict[str, Any]] = []
        self.query_requests: list[dict[str, Any]] = []
        self.scan_requests: list[dict[str, Any]] = []

    def get_item(self, **request: Any) -> dict[str, Any]:
        self.get_item_requests.append(dict(request))
        return {}

    def query(self, **request: Any) -> dict[str, Any]:
        self.query_requests.append(dict(request))
        return {"Items": [{"entity_type": {"S": "festival"}}]}

    def scan(self, **request: Any) -> dict[str, Any]:
        self.scan_requests.append(dict(request))
        return {"Items": [{"entity_type": {"S": "festival"}}]}


class DynamoDbFestivalQueryTest(unittest.TestCase):
    def test_festival_month_lookup_uses_gsi_query_when_city_is_unknown(self) -> None:
        client = RecordingDynamoDbClient()
        repository = DynamoDbRepository(
            client=client,
            settings=DynamoDbSettings(table_name="TourKoreaDomainData"),
        )

        response = repository.query_festival_candidates(
            country="KR",
            travel_month=10,
            city_id=None,
        )

        self.assertEqual(response["Items"], [{"entity_type": {"S": "festival"}}])
        self.assertEqual(client.scan_requests, [])
        self.assertEqual(len(client.query_requests), 1)
        request = client.query_requests[0]
        self.assertEqual(request["TableName"], "TourKoreaDomainData")
        self.assertEqual(request["IndexName"], "FestivalMonthIndex")
        self.assertEqual(
            request["KeyConditionExpression"],
            "#entity_type = :entity_type AND begins_with(#gsi_sk, :month_prefix)",
        )
        self.assertEqual(
            request["ExpressionAttributeNames"],
            {
                "#entity_type": "entity_type",
                "#gsi_sk": "gsi_sk",
            },
        )
        self.assertEqual(
            request["ExpressionAttributeValues"],
            {
                ":entity_type": {"S": "festival"},
                ":month_prefix": {"S": "FESTIVAL#10"},
            },
        )

    def test_festival_lookup_keeps_city_partition_query_when_city_is_known(self) -> None:
        client = RecordingDynamoDbClient()
        repository = DynamoDbRepository(
            client=client,
            settings=DynamoDbSettings(table_name="TourKoreaDomainData"),
        )

        repository.query_festival_candidates(
            country="KR",
            travel_month=4,
            city_id="KR-Gyeongju",
        )

        self.assertEqual(client.scan_requests, [])
        self.assertEqual(len(client.query_requests), 1)
        request = client.query_requests[0]
        self.assertNotIn("IndexName", request)
        self.assertEqual(
            request["KeyConditionExpression"],
            "#pk = :pk AND begins_with(#sk, :festival_prefix)",
        )
        self.assertEqual(request["ExpressionAttributeValues"][":pk"], {"S": "CITY#Gyeongju"})
        self.assertEqual(request["ExpressionAttributeValues"][":month"], {"N": "4"})


if __name__ == "__main__":
    unittest.main()
