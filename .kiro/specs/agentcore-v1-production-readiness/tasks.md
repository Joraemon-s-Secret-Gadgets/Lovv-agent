# Implementation Plan

- [ ] 1. Add a canonical/vendored runtime parity check.
  - Implement either a focused pytest test or a script that compares
    `src/lovv_agent` against `app/LovvAgentV1/lovv_agent`.
  - Print mismatched relative paths on failure.
  - Exclude cache files and package metadata.
  - Verify with `$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q`.
  - _Requirements: 3.1, 3.2, 3.3_

- [ ] 2. Add a live model availability check.
  - Read configured model IDs through `RuntimeConfig.from_env()`.
  - Check `us-east-1` Bedrock foundation models and inference profiles.
  - Classify each configured LLM node model as available, profile-backed,
    unavailable, or environment-blocked.
  - Avoid writing credentials, account IDs, or raw AWS auth details.
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 3. Add per-node structured-output smoke coverage.
  - Exercise Intent, Candidate Evidence reason-claim, and Planner explanation
    structured-output paths with compact fixtures.
  - Record Supervisor as configured-but-unused while deterministic Supervisor
    remains the v1 default.
  - Report node, model ID, pass/fail status, and schema error class.
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 4. Write the readiness result report.
  - Create `docs/tasks/results/AGENTCORE_V1_PRODUCTION_READINESS_RESULT.md`.
  - Include branch, timestamp, region, model IDs, model availability,
    structured-output smoke, parity, pytest, compileall, AgentCore validate,
    dry-run, blockers, and release recommendation.
  - _Requirements: 1.4, 2.4, 3.3, 4.3_

- [ ] 5. Prepare docs migration handoff.
  - Create `.kiro/specs/agentcore-v1-production-readiness/docs-migration-request.md`.
  - Name exact source Kiro files and target `docs/` paths.
  - Include conversion rules, non-goals, verification commands, and approval
    boundary.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [ ] 6. Run local verification gates.
  - Run `$env:UV_CACHE_DIR='.cache\\uv'; uv run pytest -q`.
  - Run `$env:UV_CACHE_DIR='.cache\\uv'; uv run python -m compileall src tests app\\LovvAgentV1`.
  - Fix code or docs issues found by the checks.
  - _Requirements: 4.1_

- [ ] 7. Run AgentCore validation gates.
  - Run `agentcore validate --json`.
  - Run `$env:UV_CACHE_DIR='D:\\bootcamp\\workspace\\project\\03_final\\04_Lovv-agent\\.cache\\uv'; agentcore deploy --target v1 --dry-run --json`.
  - Record exact output summary or environment blocker in the readiness report.
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 8. Review production model ID decision.
  - If all live checks pass, keep or update final v1 model IDs only after owner
    confirmation.
  - If a model is unavailable or schema-incompatible, document candidate
    replacements and leave production config unchanged until approved.
  - _Requirements: 1.3, 5.1, 5.5_
