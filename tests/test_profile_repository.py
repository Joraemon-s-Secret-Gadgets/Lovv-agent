"""Unit tests for ProfileRepository DynamoDB adapter."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from lovv_agent.agents.profile import ProfileRecord
from lovv_agent.repositories.profile_dynamodb import ProfileRepository


def _make_dynamodb_item(
    saved_trip_count: int = 3,
    theme_counts: dict[str, int] | None = None,
) -> dict:
    """Build a mock DynamoDB item in wire format."""
    counts = theme_counts or {"sea_coast": 3, "nature_trekking": 1}
    return {
        "PK": {"S": "ACTOR#user-123"},
        "SK": {"S": "PROFILE#v1"},
        "saved_trip_count": {"N": str(saved_trip_count)},
        "saved_theme_counts": {
            "M": {k: {"N": str(v)} for k, v in counts.items()},
        },
    }


class TestProfileRepositoryGetProfile(unittest.TestCase):
    """Test get_profile() happy path and edge cases."""

    def test_returns_profile_record_on_success(self) -> None:
        client = MagicMock()
        client.get_item.return_value = {"Item": _make_dynamodb_item(5, {"sea_coast": 5})}

        repo = ProfileRepository(client=client, table_name="LovvUserProfile")
        result = repo.get_profile("user-123")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.saved_trip_count, 5)
        self.assertEqual(result.saved_theme_counts["sea_coast"], 5)

        # Verify correct DynamoDB call
        client.get_item.assert_called_once_with(
            TableName="LovvUserProfile",
            Key={"PK": {"S": "ACTOR#user-123"}, "SK": {"S": "PROFILE#v1"}},
            ConsistentRead=False,
        )

    def test_returns_none_when_item_not_found(self) -> None:
        client = MagicMock()
        client.get_item.return_value = {}  # No "Item" key

        repo = ProfileRepository(client=client, table_name="LovvUserProfile")
        result = repo.get_profile("unknown-user")

        self.assertIsNone(result)

    def test_returns_none_on_dynamodb_exception(self) -> None:
        client = MagicMock()
        client.get_item.side_effect = Exception("DynamoDB timeout")

        repo = ProfileRepository(client=client, table_name="LovvUserProfile")
        result = repo.get_profile("user-123")

        self.assertIsNone(result)

    def test_returns_none_for_empty_actor_id(self) -> None:
        client = MagicMock()
        repo = ProfileRepository(client=client, table_name="LovvUserProfile")

        self.assertIsNone(repo.get_profile(""))
        self.assertIsNone(repo.get_profile(None))  # type: ignore[arg-type]
        client.get_item.assert_not_called()

    def test_handles_zero_trip_count(self) -> None:
        client = MagicMock()
        item = {
            "PK": {"S": "ACTOR#new-user"},
            "SK": {"S": "PROFILE#v1"},
            "saved_trip_count": {"N": "0"},
            "saved_theme_counts": {"M": {}},
        }
        client.get_item.return_value = {"Item": item}

        repo = ProfileRepository(client=client, table_name="LovvUserProfile")
        result = repo.get_profile("new-user")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.saved_trip_count, 0)
        self.assertEqual(result.saved_theme_counts, {})

    def test_handles_missing_theme_counts_map(self) -> None:
        """Item exists but saved_theme_counts field is absent."""
        client = MagicMock()
        item = {
            "PK": {"S": "ACTOR#user-x"},
            "SK": {"S": "PROFILE#v1"},
            "saved_trip_count": {"N": "2"},
            # saved_theme_counts missing
        }
        client.get_item.return_value = {"Item": item}

        repo = ProfileRepository(client=client, table_name="LovvUserProfile")
        result = repo.get_profile("user-x")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.saved_trip_count, 2)
        self.assertEqual(result.saved_theme_counts, {})

    def test_handles_malformed_item_gracefully(self) -> None:
        """Completely unexpected item structure → None."""
        client = MagicMock()
        client.get_item.return_value = {"Item": {"garbage": {"BOOL": True}}}

        repo = ProfileRepository(client=client, table_name="LovvUserProfile")
        result = repo.get_profile("user-bad")

        # Should not crash, returns 0 trip count
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.saved_trip_count, 0)


if __name__ == "__main__":
    unittest.main()
