# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_2_PROFILE_B_EXAMPLE

Example run record for Scenario 2 from the Phase 2 long-horizon benchmark plan.

This file is a starter example for documenting an investigate-then-fix bug
workflow under the bounded-delegation profile. It is intentionally a fillable
record, not a claim that the benchmark has already been executed.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile B — bounded research delegation
- Scenario ID: 2
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive single-session benchmark

## Initial prompt
- User request:
  - Investigate a failing behavior or test, determine the root cause, apply a
    focused fix, verify the result, and summarize any remaining risks.

## Expected task shape
- Planned steps:
  - reproduce the issue,
  - create a todo plan,
  - inspect relevant files,
  - optionally delegate an independent background search or audit,
  - apply a focused fix,
  - rerun verification,
  - summarize findings and result.
- Expected files touched:
  - one or more implementation files,
  - one or more test files if test updates are needed.
- Expected verification:
  - targeted failing test and follow-up passing verification.
- Expected delegation behavior:
  - optional bounded research delegation only if it materially helps.

## Runtime configuration
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=none`

## Observed execution
- Todo plan created: TBD
- Todo notes:
- Tool-call count: TBD
- Approximate peak tool-call depth: TBD
- Sub-agents spawned: TBD
- Delegated outcomes: ok=TBD, failed=TBD, pending=TBD
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
- Delegation usefulness (0-2): TBD

## Interruptions or failures
- What failed:
- How it surfaced:
- Recovery action:
- Recovery succeeded: Yes / No / not applicable

## Artifacts
- Final summary:
- Diff location:
- Verification output location:
- Agent log location:
- Additional notes:

## Final assessment
- Completed successfully: TBD
- Would trust this mode for similar work: TBD
- Key strengths:
- Key weaknesses:
- Follow-up actions:
