# ROADMAP_FUNCTION_KEYS

## Purpose
This roadmap tracks the evolution of the function-key subsystem from a flat mapping to a grouped, selector-driven configuration model.

## Current Direction
The implemented model is:
- organize bindings by named groups
- use a top-level dictionary of groups in the configuration
- store each F-key entry as text plus description
- require each binding entry to include both text and description
- restrict user bindings to F1-F8
- allow duplicate F-key assignments across groups
- reserve F9-F12 for internal use
- use F12 as the selector entry point
- allow Tab to cycle groups
- allow F12 to activate the selected group
- allow Escape to cancel without changes
- show group name, F key, and description in the selector
- keep selection state ephemeral so it does not persist across sessions
- use the first configured group as the default on startup

## Why This Matters
The current flat function-key model is simple, but it becomes harder to manage as the set of shortcuts grows. Grouping keys by purpose improves readability, discoverability, and long-term maintainability.

## Planned Evolution

### Phase 1: Config Structure
- Finalize the top-level grouped configuration shape.
- Treat group names as the outer dictionary keys.
- Represent each F-key entry with text and description fields.
- Require both text and description on every binding entry.
- Keep each group limited to F1-F8.
- Preserve the existing insertion semantics for text expansion.

### Phase 2: Validation and Loading
- Add validation for grouped definitions.
- Reject reserved keys in user config.
- Allow duplicate F-key assignments across groups.
- Normalize group and key names consistently.
- Load grouped bindings into a runtime-friendly structure.
- Use the first group in configuration order as the initial active group.

### Phase 3: Selector UX
- Add the F12 selector entry point.
- Render the current group, key, and description for each binding.
- Support Tab for cycling through groups.
- Support F12 to confirm the previewed group.
- Support Escape to cancel safely.
- Keep selection changes local until explicitly confirmed.

### Phase 4: Runtime Binding Activation
- Make the active group determine which F1-F8 handlers are live.
- Ensure group switching updates bindings cleanly.
- Keep the selector state isolated from the normal insertion path.
- Ensure the startup group remains the default until changed within the session.

### Phase 5: Documentation and Testing
- Document the group-based config format.
- Document the reserved internal key range.
- Document the required text and description fields for each binding.
- Document the selector display fields and session behavior.
- Add tests for parsing, validation, selector flow, reserved key handling, required fields, and activation behavior.
- Verify that cancellation leaves the current group unchanged.
- Verify that selection does not persist across sessions.

## Risks and Constraints
- Terminal environments may not always report modified function keys consistently.
- The selector should not depend on unsupported modifier combinations.
- The config design should stay simple enough for manual editing.
- Duplicate or conflicting key definitions need a clear policy.

## Success Criteria
- Users can define multiple named function-key groups.
- Users can switch groups with a dedicated hotkey and keyboard navigation.
- The system remains easy to reason about and easy to extend.
- Reserved keys do not conflict with user-defined mappings.
- The feature stays compatible with the existing text-insertion behavior.

## Relationship to Other Documents
- Use `PLAN_FUNCTION_KEYS.md` for the feature design.
- Use `CHECKLIST_FUNCTION_KEYS.md` for implementation tracking.
- Use this roadmap for feature evolution and decision history.
