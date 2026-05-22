# PLAN_FUNCTION_KEYS

## Goal
Introduce grouped function-key bindings with a dedicated internal selector workflow. The user-facing mapping is organized by top-level group keys, with each F-key entry containing text and description. Descriptions are shown in the selector, F1-F8 are user-assignable, F9-F12 are reserved for internal use, and group selection resets on app startup with the first group as the default.

## Design Summary
- Top-level configuration keys define groups.
- Each group contains F-key entries with text and description fields.
- User bindings are limited to F1-F8.
- F9-F12 are reserved for the application.
- F12 opens the function-key group selector.
- The selector lets the user preview groups, cycle with Tab, accept with F12, and cancel with Escape.
- The selector displays descriptions instead of raw text.
- The currently active group determines which F1-F8 bindings are live.
- Group selection resets on app startup with the first group active by default.

## This Shape
- Keeps related shortcuts together by purpose.
- Makes the config easier to scan and document.
- Leaves room for internal navigation and UI controls.
- Avoids overloading a flat shortcut list as the feature grows.

## Configuration Shape
A proposed configuration layout:

- `group_name`
  - `F1` through `F8`
  - each entry contains `text` and `description`
  - optional group metadata in the future if needed

Example:

```json
{
  "navigation": {
    "F1": {"text": "build", "description": "Run the build"},
    "F2": {"text": "status", "description": "Show repository status"}
  },
  "workflow": {
    "F1": {"text": "test", "description": "Run tests"},
    "F2": {"text": "lint", "description": "Run linting"}
  }
}
```

## Runtime Behavior
- At startup, load all groups and validate them.
- Flatten the active group into runtime bindings for F1-F8.
- Reserve F9-F12 for internal features.
- Show the available groups in the selector UI.
- Allow one active group at a time.
- Keep selector state separate from the active runtime binding state.
- Reset group selection on app startup and default to the first configured group.
- The active group determines runtime behavior for F1-F8, and the same F-key may be assigned differently in different groups.

## Selector Behavior
- F12 opens the selector.
- Tab advances to the next group and loops back to the first group.
- F12 confirms the previewed group and activates it.
- Escape exits the selector with no changes.
- The selector should never mutate active bindings until confirmation.

## Validation Rules
- Only F1-F8 are allowed in user-defined groups.
- Each group may define any subset of F1-F8.
- The same F-key may repeat across different groups.
- Duplicate keys inside a group are invalid.
- Reserved keys F9-F12 must not be user-assignable.
- Each binding entry must include both `text` and `description` for selector display and insertion behavior.
- Invalid group shapes must fail fast during config loading.

## Implementation Notes
- The existing flat mapping can be adapted by flattening the selected group at runtime.
- The validation and loader layers should own normalization and shape checking.
- The keyboard layer should own binding registration and selector interaction.
- The selector should be explicit state, not hidden side effects.
- The selector displays group name, F key, and description only.
- F-key assignments may differ across groups; runtime activation uses only the currently selected group.
- The design should remain compatible with the current function-key insertion behavior.

## Success Criteria
- Users can organize bindings into named groups.
- Only one group is active at a time.
- F12 can be used to browse and activate groups safely.
- F1-F8 remain simple text insertion keys within the active group.
- The reserved internal key range does not conflict with user bindings.
- The feature remains understandable without introducing complex nested state.
