## Matters

- Generated, never hand-edit: `instructions/` (in `OWNED_PREFIXES`); `agents/*.agent.md` and `hooks/hooks.json` are symlinks into `src/copilot-cli/` (ADR-119). `prompts/pr-quality-gate-*.md` regenerates only with `build/scripts/generate_pr_quality_prompts.py`, which `build_all.py` does not run.
- `copilot-instructions.md`: Copilot's always-on entry point (every Copilot CLI session). Byte ratchet 6351 (4707 today) in `scripts/validate_workspace_budget.py`, enforced by `tests/test_workspace_limits.py::test_per_file_limit` inside the required `Run Python Tests`; the pytest matrix runs on every event, so every edit here meets it.
- Cross-harness work: read `agent-harness-reference` first, route it through `ai-agents-portability-campaign`.
