# CHECKLIST_TOOL_ROUTE_EDIT

- [x] Define the target behavior as inspect -> plan -> exact edit -> verify.
- [x] Confirm the edit hierarchy prefers exact tools before fallback regeneration.
- [x] Define the reduced-chat behavior: terse, factual, and non-repetitive.
- [x] Define the tool-selection policy for read tools, surgical edit tools, and fallback tools.
- [x] Define post-edit verification expectations.
- [x] Confirm the existing toolset is sufficient for an initial prompt-first rollout.
- [x] Define the default verification rule: always diff after writes, then run language-specific checks when clearly applicable.
- [ ] Encode the routing and verification policy in prompt or tool-guidance instructions.
- [ ] Add tests or assertions for tool-routing preference order.
- [ ] Add tests or assertions that `modify_source_code` is used only as a fallback.
- [ ] Add verification coverage for write-tool outcomes.
- [ ] Confirm the response style stays concise after edits.
- [ ] Confirm the assistant does not ask for unnecessary re-confirmation after approval.
- [ ] Confirm inspect-first behavior when the target file is not already known.
- [ ] Confirm bulk replacement is used for mechanical repeated edits.
- [ ] Confirm Python changes are type-checked when clearly relevant.
- [ ] Confirm targeted tests are run after writes when clearly relevant.
