# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_5_PROFILE_B_EXAMPLE

Example run record for Scenario 5 from the Phase 2 long-horizon benchmark plan.

This file is a starter example for documenting an interruption-and-resume
workflow in the same session under the bounded-delegation profile. It is
intentionally a fillable record, not a claim that the benchmark has already
been executed.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile B — bounded research delegation
- Scenario ID: 5
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive multi-turn benchmark in one session

## Initial prompt
- User request:
  - Start a moderate multi-step coding task, pause after a meaningful partial
    completion point, then resume later in the same session and finish with
    verification.

## Expected task shape
- Planned steps:
  - inspect the task area,
  - create a todo plan,
  - begin implementation or investigation,
  - stop after a meaningful intermediate state,
  - resume in a later turn using retained plan and context,
  - complete remaining work,
  - run verification,
  - summarize the completed task and any remaining follow-up.
- Expected files touched:
  - one or more implementation files,
  - zero or more test files,
  - potentially additional files discovered during resumed work.
- Expected verification:
  - targeted tests or equivalent project validation command after resumption.
- Expected delegation behavior:
  - optional bounded research delegation if it helps either before or after the
    interruption.

## Runtime configuration
- `MONITOR_ENABLE_AGENT_ORCHESTRATION=1`
- `MONITOR_AGENT_MAX_DEPTH=1`
- `MONITOR_AGENT_MAX_BREADTH=2`
- `MONITOR_AGENT_MAX_TOTAL=4`
- `SUBAGENT_WRITE_ACCESS=none`

## Observed execution
- Todo plan created: TBD
- Todo notes:
- Tool-call count before interruption: TBD
- Tool-call count after resumption: TBD
- Approximate peak tool-call depth: TBD
- Sub-agents spawned: TBD
- Delegated outcomes: ok=TBD, failed=TBD, pending=TBD
- Time to interruption: TBD
- Time from resumption to completion: TBD
- Total time to completion: TBD

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

## Interruption details
- Interruption point:
- What state was already complete:
- What state remained incomplete:
- Was the retained todo state sufficient: Yes / No / partially
- Was resumed progress straightforward: Yes / No / partially

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
