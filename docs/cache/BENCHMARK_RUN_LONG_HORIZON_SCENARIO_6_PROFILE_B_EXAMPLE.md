# BENCHMARK_RUN_LONG_HORIZON_SCENARIO_6_PROFILE_B_EXAMPLE

Example run record for Scenario 6 from the Phase 2 long-horizon benchmark plan.

This file is a starter example for documenting a persistent-agent follow-up
workflow under the bounded-delegation profile. It is intentionally a fillable
record, not a claim that the benchmark has already been executed.

## Metadata
- Date: TBD
- Commit / branch: TBD
- Runtime profile: Profile B — bounded research delegation
- Scenario ID: 6
- Repo / fixture: TBD
- Operator: TBD
- Session type: Interactive multi-turn benchmark in one session

## Initial prompt
- User request:
  - Launch a persistent research sub-agent for a focused investigation, continue
    primary work in the main session, then send one or more follow-up prompts
    to refine the delegated investigation before gathering or terminating it.

## Expected task shape
- Planned steps:
  - inspect the main task area,
  - create a todo plan,
  - create a persistent sub-agent for a bounded side investigation,
  - continue mainline work while the sub-agent remains available,
  - send at least one follow-up prompt to narrow or extend the investigation,
  - gather results or inspect agent state,
  - terminate the persistent agent cleanly if still active,
  - summarize usefulness and lifecycle behavior.
- Expected files touched:
  - zero or more main-session implementation files,
  - zero or more test files,
  - no sub-agent-written files under read-only delegation.
- Expected verification:
  - targeted tests or equivalent project validation command if main-session code
    is changed.
- Expected delegation behavior:
  - one persistent read-only sub-agent with at least one follow-up message.

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
- Persistent follow-up messages sent: TBD
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

## Persistent-agent details
- Agent stayed available for follow-up: Yes / No / partially
- Follow-up prompt count:
- Follow-up prompts improved result quality: Yes / No / partially
- Agent lifecycle remained easy to understand: Yes / No / partially
- Agent required explicit kill at end: Yes / No

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
