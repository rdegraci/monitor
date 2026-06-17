# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_4_PROFILE_B

Real-run record placeholder for Scenario 4 from the Phase 2 long-horizon
benchmark plan.

This file is reserved for the first executed run of the partial-delegated-
failure benchmark under the bounded-delegation profile.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile B — bounded research delegation
- Scenario ID: 4
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive single-session benchmark
- Run status: Planned, not yet executed

## Initial prompt
- User request: See `docs/cache/BENCHMARK_FIXTURE_LONG_HORIZON_SCENARIO_4.md`.

## Expected task shape
- Planned steps:
  - inspect the main task area,
  - create a todo plan,
  - begin the main implementation or investigation,
  - spawn at least two independent delegated tasks,
  - allow one branch to succeed,
  - allow another branch to fail, disconnect, time out, or remain pending,
  - continue foreground work without blocking unnecessarily,
  - use the successful delegated result if useful,
  - run verification,
  - summarize the mixed outcome honestly.
- Expected files touched:
  - one or more implementation files,
  - zero or more test files,
  - no sub-agent-written files under read-only delegation.
- Expected verification:
  - targeted tests or equivalent project validation command.
- Expected delegation behavior:
  - at least two read-only sub-agents with mixed outcomes.

## Runtime configuration
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=none`

## Observed execution
- Todo plan created: not yet recorded
- Todo notes:
- Tool-call count: not yet recorded
- Approximate peak tool-call depth: not yet recorded
- Sub-agents spawned: not yet recorded
- Delegated outcomes: ok=not yet recorded, failed=not yet recorded, pending=not yet recorded
- Time to completion: not yet recorded

## Verification outcome
- Verification command(s): not yet recorded
- Pass / fail: not yet recorded
- Notes:

## Qualitative scores
- Plan quality (0-2): not yet recorded
- Progress visibility (0-2): not yet recorded
- Failure honesty (0-2): not yet recorded
- Resume clarity (0-2): not yet recorded
- Delegation usefulness (0-2): not yet recorded

## Failure-path details
- Expected failing branch:
- Actual failing branch:
- Failure classification surfaced as: not yet recorded
- Did successful branch output remain usable: not yet recorded
- Did failure block mainline progress unnecessarily: not yet recorded

## Interruptions or failures
- What failed:
- How it surfaced:
- Recovery action:
- Recovery succeeded: not yet recorded

## Artifacts
- Final summary:
- Diff location:
- Verification output location:
- Agent log location:
- Additional notes:

## Final assessment
- Completed successfully: not yet recorded
- Would trust this mode for similar work: not yet recorded
- Key strengths:
- Key weaknesses:
- Follow-up actions:
