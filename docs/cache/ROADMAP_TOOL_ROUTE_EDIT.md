# ROADMAP_TOOL_ROUTE_EDIT

## Phase 1: Clarify policy and confirm tool sufficiency
- Document the desired edit flow: inspect -> plan -> exact edit -> verify.
- Spell out the preferred order of edit tools.
- Spell out the response style goals.
- Confirm the current toolset is already sufficient for the initial rollout.

## Phase 2: Bias tool selection through prompt guidance
- Strengthen the system prompt so exact tools are preferred.
- Make `modify_source_code` clearly the fallback.
- Reinforce inspect-first behavior when file context is incomplete.
- Encode the default verification rule: always diff after writes, then run language-specific checks only when clearly applicable.

## Phase 3: Tighten assistant style
- Reduce generic conversational filler.
- Keep summaries short and actionable.
- Avoid unnecessary offers or re-asking after approval.

## Phase 4: Add lightweight verification discipline
- After writes, run diff-based verification as the default path.
- Add targeted tests for the edited area when clearly available.
- Add type checking for Python changes when clearly appropriate.
- Report when no relevant automated check was clearly applicable.

## Phase 5: Measure and refine
- Track how often each edit tool is selected.
- Watch for overuse of `modify_source_code`.
- Add deeper enforcement only if prompt-first behavior proves too inconsistent.
- Iterate on tool descriptions and routing rules if the harness drifts from the target behavior.
