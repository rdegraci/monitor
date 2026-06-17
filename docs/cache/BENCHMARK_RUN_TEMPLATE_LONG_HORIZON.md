# BENCHMARK_RUN_TEMPLATE_LONG_HORIZON

Reusable run-record template for Phase 2 long-horizon benchmark execution.

Use this template to capture a single benchmark run consistently across
scenarios, runtime profiles, repositories, and fixture tasks. It is designed to
pair with `docs/cache/BENCHMARKS_LONG_HORIZON.md`.

## Instructions

1. Copy this template into a new run record.
2. Replace placeholder values with concrete benchmark data.
3. Keep the initial prompt and verification steps exact where possible.
4. Record failures honestly, including partial completion and pending work.
5. Link any related logs, diffs, or verification output.

## File naming recommendation

Use a name in this form:

`BENCHMARK_RUN_LONG_HORIZON_<SCENARIO>_<PROFILE>_<YYYYMMDD>.md`

Example:

`BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_B_20260616.md`

---

# Benchmark Run: <scenario name>

## Metadata
- Date:
- Commit / branch:
- Runtime profile:
- Scenario ID:
- Repo / fixture:
- Operator:
- Session type:

## Initial prompt
- User request:

## Expected task shape
- Planned steps:
- Expected files touched:
- Expected verification:
- Expected delegation behavior:

## Runtime configuration
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=`
- `MONITOR_AGENT_MAX_DEPTH=`
- `MONITOR_AGENT_MAX_BREADTH=`
- `MONITOR_AGENT_MAX_TOTAL=`
- `SUBAGENT_WRITE_ACCESS=`

## Observed execution
- Todo plan created: Yes / No
- Todo notes:
- Tool-call count:
- Approximate peak tool-call depth:
- Sub-agents spawned:
- Delegated outcomes: ok=<n>, failed=<n>, pending=<n>
- Time to completion:

## Verification outcome
- Verification command(s):
- Pass / fail:
- Notes:

## Qualitative scores
- Plan quality (0-2):
- Progress visibility (0-2):
- Failure honesty (0-2):
- Resume clarity (0-2):
- Delegation usefulness (0-2):

## Interruptions or failures
- What failed:
- How it surfaced:
- Recovery action:
- Recovery succeeded: Yes / No

## Artifacts
- Final summary:
- Diff location:
- Verification output location:
- Agent log location:
- Additional notes:

## Final assessment
- Completed successfully: Yes / No
- Would trust this mode for similar work: Yes / No
- Key strengths:
- Key weaknesses:
- Follow-up actions:
