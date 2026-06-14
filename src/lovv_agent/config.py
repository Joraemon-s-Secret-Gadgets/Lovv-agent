"""Configuration skeleton for Lovv agent runtime settings.

Task 1.2 will replace these section names with concrete typed settings. This
placeholder deliberately avoids environment reads so importing the package has
no external side effects.
"""

from __future__ import annotations

CONFIG_SECTIONS: tuple[str, ...] = (
    "aws",
    "s3_vectors",
    "dynamodb",
    "embeddings",
    "llm",
    "search_budget",
    "timeouts",
    "retries",
)

__all__ = ["CONFIG_SECTIONS"]
