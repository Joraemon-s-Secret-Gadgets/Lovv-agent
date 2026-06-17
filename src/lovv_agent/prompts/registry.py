"""Prompt registry for versioned Lovv prompt assets.

Prompt text lives in adjacent Markdown files so live LLM contracts are explicit
project artifacts. Call sites request prompts by stable id and receive the
versioned asset text without embedding long prompt bodies inline.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

PROMPT_REGISTRY_NAME = "LovvPromptRegistry"

# 안정적인 prompt id는 runtime node와 테스트에서 참조한다.
CANDIDATE_REASON_CLAIM_PROMPT_ID = "candidate_reason_claim.v1"
INTENT_NORMALIZATION_PROMPT_ID = "intent_normalization.v1"
PLANNER_COPY_EXPLANATION_PROMPT_ID = "planner_copy_explanation.v1"


class PromptRegistryError(RuntimeError):
    """Raised when a requested prompt asset cannot be loaded."""


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Loaded prompt asset metadata and body."""

    prompt_id: str
    version: str
    filename: str
    text: str


PROMPT_FILES: dict[str, tuple[str, str]] = {
    # 값은 (의미상 prompt version, package resource 파일명)이다.
    CANDIDATE_REASON_CLAIM_PROMPT_ID: ("v1", "candidate_reason_claim.v1.md"),
    INTENT_NORMALIZATION_PROMPT_ID: ("v1", "intent_normalization.v1.md"),
    PLANNER_COPY_EXPLANATION_PROMPT_ID: ("v1", "planner_copy_explanation.v1.md"),
}


def load_prompt_template(prompt_id: str) -> PromptTemplate:
    """Load a prompt template by stable id."""

    if prompt_id not in PROMPT_FILES:
        raise PromptRegistryError(f"unknown prompt id: {prompt_id}")
    version, filename = PROMPT_FILES[prompt_id]
    try:
        text = (
            resources.files(__package__)
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise PromptRegistryError(f"prompt asset not found: {filename}") from exc
    normalized = text.strip()
    if not normalized:
        raise PromptRegistryError(f"prompt asset is empty: {filename}")
    return PromptTemplate(
        prompt_id=prompt_id,
        version=version,
        filename=filename,
        text=normalized,
    )


def prompt_text(prompt_id: str) -> str:
    """Return only the prompt body for a stable prompt id."""

    return load_prompt_template(prompt_id).text


__all__ = [
    "CANDIDATE_REASON_CLAIM_PROMPT_ID",
    "INTENT_NORMALIZATION_PROMPT_ID",
    "PLANNER_COPY_EXPLANATION_PROMPT_ID",
    "PROMPT_FILES",
    "PROMPT_REGISTRY_NAME",
    "PromptRegistryError",
    "PromptTemplate",
    "load_prompt_template",
    "prompt_text",
]
