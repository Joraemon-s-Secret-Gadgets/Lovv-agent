"""Adapter namespace for provider/runtime integration boundaries."""

from __future__ import annotations

# import skeleton 테스트와 패키지 문서를 위한 안정적인 모듈 목록이다.
ADAPTER_MODULES: tuple[str, ...] = (
    "bedrock_converse",
    "aws_clients",
    "aws_runtime",
    "boto3_clients",
    "embeddings",
)

__all__ = ["ADAPTER_MODULES"]
