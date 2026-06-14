"""DynamoDB repository placeholder.

Later tasks add primary-only place rehydration and festival seed/detail access.
Task 1.1 contains no boto3 calls.
"""

from __future__ import annotations

REPOSITORY_NAME = "DynamoDbRepository"

RESPONSIBILITY = "Read normalized detail records through an injected client."

__all__ = ["REPOSITORY_NAME", "RESPONSIBILITY"]
