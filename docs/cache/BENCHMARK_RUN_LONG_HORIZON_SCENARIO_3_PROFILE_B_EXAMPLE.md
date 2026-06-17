# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_3_PROFILE_B_EXAMPLE

Example run record for Scenario 3 from the Phase 2 long-horizon benchmark plan.

This file is a starter example for documenting a background-audit plus
foreground-implementation workflow under the bounded-delegation profile. It is
intentionally a fillable record, not a claim that the benchmark has already
been executed.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile B — bounded research delegation
- Scenario ID: 3
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive single-session benchmark

## Initial prompt
- User request:
  - Implement a targeted change in a primary code path while also checking
    related surfaces for regressions, consistency issues, or adjacent risks.

## Expected task shape
- Planned steps:
  - inspect the main implementation area,
  - create a todo plan,
  - start foreground implementation,
  - delegate an independent background audit of adjacent files or call sites,
  - continue foreground work without blocking on the delegated task,
  - gather or absorb delegated findings,
  - apply any necessary follow-up changes,
  - run verification,
  - summarize final outcomes and any residual risks.
- Expected files touched:
  - one or more primary implementation files,
  - zero or more adjacent files informed by the delegated audit,
  - one or more test files if verification changes are needed.
- Expected verification:
  - targeted tests or equivalent project validation command.
- Expected delegation behavior:
  - one or more read-only sub-agents performing independent research or audit
    work.

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
