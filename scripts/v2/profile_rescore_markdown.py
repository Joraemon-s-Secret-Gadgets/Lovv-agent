from __future__ import annotations

from pathlib import Path
from typing import Any


def _cell(value: str) -> str:
    return value.replace("|", "\\|")


def write_markdown(
    path: Path,
    smoke_dir: Path,
    configs: list[dict[str, Any]],
    representative: list[dict[str, Any]],
) -> None:
    top_configs = sorted(
        configs,
        key=lambda row: (row["persona_changed_max"], row["persona_changed_avg"]),
        reverse=True,
    )[:5]
    changed_personas = [row for row in representative if row["changed_count"]]
    lines = [
        "# Profile Theme Persona Rescore Comparison",
        "",
        f"- smoke_dir: `{smoke_dir}`",
        "- scoring: active theme weights normalized; single-theme requests are invariant.",
        "",
        "## Grid Summary Top Churn",
        "",
        "| config | personas_with_any_change | max_changed | avg_changed |",
        "|---|---:|---:|---:|",
    ]
    for row in top_configs:
        lines.append(
            f"| {_cell(row['config_id'])} | {row['personas_with_any_change']} | "
            f"{row['persona_changed_max']} | {row['persona_changed_avg']} |",
        )
    lines.extend([
        "",
        "## Representative Config",
        "",
        "`alpha=1.5|range=medium|cap=0.05`",
        "",
        f"- changed personas: {len(changed_personas)}/{len(representative)}",
        f"- max changed cases/persona: {max((row['changed_count'] for row in representative), default=0)}",
        "",
        "| persona | changed | examples |",
        "|---|---:|---|",
    ])
    for row in representative:
        examples = ", ".join(
            f"{item['case_id']} {item['before']}->{item['after']}"
            for item in row["changed_cases"][:5]
        )
        if len(row["changed_cases"]) > 5:
            examples = f"{examples}, ... +{len(row['changed_cases']) - 5}"
        lines.append(f"| {row['persona_id']} | {row['changed_count']} | {examples or '-'} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
