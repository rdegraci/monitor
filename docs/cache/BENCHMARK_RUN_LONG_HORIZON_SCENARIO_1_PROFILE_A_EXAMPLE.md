# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_1_PROFILE_A_EXAMPLE

Example run record for Scenario 1 from the Phase 2 long-horizon benchmark plan.

This file is a starter example for documenting a single-session multi-file
feature benchmark under the no-orchestration profile. It is intentionally a
fillable record, not a claim that the benchmark has already been executed.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile A — no orchestration
- Scenario ID: 1
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive single-session benchmark

## Initial prompt
- User request:
  - Implement a moderate multi-file feature that requires reading existing code,
    editing multiple files, updating tests, and verifying the final behavior.

## Expected task shape
- Planned steps:
  - inspect current implementation,
  - create a todo plan,
  - implement the feature across multiple files,
  - update or add tests,
  - run verification,
  - summarize the result.
- Expected files touched:
  - at least 2 to 4 source files,
  - at least 1 test file.
- Expected verification:
  - targeted test run or equivalent project verification command.
- Expected delegation behavior:
  - none.

## Runtime configuration
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=0`
- `MONITOR_AGENT_MAX_DEPTH=` not applicable
- `MONITOR_AGENT_MAX_BREADTH=` not applicable
- `MONITOR_AGENT_MAX_TOTAL=` not applicable
- `SUBAGENT_WRITE_ACCESS=none`

## Observed execution
- Todo plan created: TBD
- Todo notes:
- Tool-call count: TBD
- Approximate peak tool-call depth: TBD
- Sub-agents spawned: 0
- Delegated outcomes: ok=0, failed=0, pending=0
- Time to completion: TBD

## Verification outcome
- Verification command(s): TBD
- Pass / fail: TBD
- Notes:

## Qualitative scores
- Plan quality (0-2): TBD
- Progress visibility (0-2): TBD
- Failure honesty (0-2): TBD
- Resume clarity (0-2): TBD
- Delegation usefulness (0-2): not applicable

## Interruptions or failures
- What failed:
- How it surfaced:
- Recovery action:
- Recovery succeeded: Yes / No / not applicable

## Artifacts
- Final summary:
- Diff location:
- Verification output location:
- Agent log location: not applicable
- Additional notes:

## Final assessment
- Completed successfully: TBD
- Would trust this mode for similar work: TBD
- Key strengths:
- Key weaknesses:
- Follow-up actions:
