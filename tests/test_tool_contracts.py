"""Unit tests for Tool I/O contract dataclasses.

Validates creation, to_dict() round-trip, and default values.
"""

from __future__ import annotations

import unittest

from lovv_agent.tools.contracts import (
    EmbedQueryInput,
    EmbedQueryOutput,
    EnrichPlaceDetailsInput,
    EnrichPlaceDetailsOutput,
    LookupFestivalSeedsInput,
    LookupFestivalSeedsOutput,
    SearchAttractionsInput,
    SearchAttractionsOutput,
    SearchPlacePoolInput,
    SearchPlacePoolOutput,
)


class TestSearchAttractionsContract(unittest.TestCase):
    def test_creation_with_defaults(self) -> None:
        inp = SearchAttractionsInput(query_vector=[0.1, 0.2, 0.3])
        self.assertEqual(inp.top_k, 50)
        self.assertIsNone(inp.city_id)
        self.assertIsNone(inp.theme)
        self.assertIsNone(inp.filters)

    def test_creation_full(self) -> None:
        inp = SearchAttractionsInput(
            query_vector=[0.1, 0.2],
            city_id="KR-36-4",
            theme="바다·해안",
            top_k=30,
            filters={"source": "tourkorea"},
        )
        self.assertEqual(inp.city_id, "KR-36-4")
        self.assertEqual(inp.theme, "바다·해안")

    def test_to_dict_roundtrip(self) -> None:
        inp = SearchAttractionsInput(
            query_vector=[0.5], city_id="C1", theme="T1", top_k=10,
        )
        d = inp.to_dict()
        self.assertEqual(d["query_vector"], [0.5])
        self.assertEqual(d["city_id"], "C1")
        self.assertEqual(d["top_k"], 10)

    def test_output_creation(self) -> None:
        out = SearchAttractionsOutput(
            candidates=({"place_id": "p1"},),
            retrieval_count=1,
        )
        self.assertEqual(out.retrieval_count, 1)
        self.assertFalse(out.truncated)

    def test_output_to_dict(self) -> None:
        out = SearchAttractionsOutput(
            candidates=({"id": "1"}, {"id": "2"}),
            retrieval_count=2,
            truncated=True,
        )
        d = out.to_dict()
        self.assertEqual(len(d["candidates"]), 2)
        self.assertTrue(d["truncated"])


class TestSearchPlacePoolContract(unittest.TestCase):
    def test_creation(self) -> None:
        inp = SearchPlacePoolInput(query_vector=[0.1], city_id="CITY1")
        self.assertEqual(inp.city_id, "CITY1")
        self.assertEqual(inp.exclude_place_ids, ())

    def test_to_dict(self) -> None:
        inp = SearchPlacePoolInput(
            query_vector=[0.1],
            city_id="C1",
            exclude_place_ids=("p1", "p2"),
        )
        d = inp.to_dict()
        self.assertEqual(d["exclude_place_ids"], ["p1", "p2"])


class TestLookupFestivalSeedsContract(unittest.TestCase):
    def test_creation(self) -> None:
        inp = LookupFestivalSeedsInput(
            city_id="CITY1", travel_month=7, travel_year=2026,
        )
        self.assertEqual(inp.max_candidates, 30)

    def test_output(self) -> None:
        out = LookupFestivalSeedsOutput(
            festivals=({"festival_id": "f1"},),
            retrieval_count=1,
        )
        d = out.to_dict()
        self.assertEqual(d["retrieval_count"], 1)


class TestEnrichPlaceDetailsContract(unittest.TestCase):
    def test_creation_empty(self) -> None:
        inp = EnrichPlaceDetailsInput()
        self.assertEqual(inp.place_keys, ())

    def test_output_with_missing(self) -> None:
        out = EnrichPlaceDetailsOutput(
            details=({"title": "장소1"},),
            missing_keys=({"pk": "P1", "sk": "S1"},),
        )
        d = out.to_dict()
        self.assertEqual(len(d["missing_keys"]), 1)


class TestEmbedQueryContract(unittest.TestCase):
    def test_creation(self) -> None:
        inp = EmbedQueryInput(text="바다 여행")
        self.assertIsNone(inp.model_id)

    def test_output(self) -> None:
        out = EmbedQueryOutput(vector=[0.1, 0.2, 0.3], dimension=3)
        d = out.to_dict()
        self.assertEqual(d["dimension"], 3)
        self.assertEqual(len(d["vector"]), 3)


if __name__ == "__main__":
    unittest.main()
