# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B_EXAMPLE

Example run record for Scenario 4 from the Phase 2 long-horizon benchmark plan.

This file is a starter example for documenting a partial-delegated-failure
workflow under the bounded-delegation profile. It is intentionally a fillable
record, not a claim that the benchmark has already been executed.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile B — bounded research delegation
- Scenario ID: 4
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive single-session benchmark

## Initial prompt
- User request:
  - Complete a coding task while delegating independent background work, with at
    least one delegated branch expected to fail, time out, or disconnect so the
    main session's failure handling can be evaluated.

## Expected task shape
- Planned steps:
  - inspect the main task area,
  - create a todo plan,
  - launch at least two independent delegated tasks,
  - continue the mainline task without blocking unnecessarily,
  - observe a mixed delegated outcome with success and failure or pending work,
  - gather or absorb useful delegated results,
  - complete verification for the main task,
  - summarize mixed outcomes honestly.
- Expected files touched:
  - one or more implementation files,
  - zero or more test files,
  - no sub-agent-written files under read-only delegation.
- Expected verification:
  - targeted tests or equivalent project validation command.
- Expected delegation behavior:
  - at least two read-only sub-agents, with one expected to succeed and one
    expected to fail, time out, or remain pending.

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

## Failure-path details
- Expected failing branch:
- Actual failing branch:
- Failure classification surfaced as: failed / pending / other
- Did successful branch output remain usable: Yes / No / partially
- Did failure block mainline progress unnecessarily: Yes / No / partially

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
