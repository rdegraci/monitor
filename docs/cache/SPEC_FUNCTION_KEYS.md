# SPEC_FUNCTION_KEYS

## Overview
This specification defines the implementation of grouped function-key bindings with a selector workflow in the Monitor application. The feature replaces a flat function-key mapping with a grouped model that is easier to browse and maintain.

## Goals
- Organize function keys into named groups.
- Limit user-assignable function keys to F1-F8.
- Reserve F9-F12 for internal use.
- Use F12 to open a group selector.
- Allow Tab to cycle through groups.
- Allow F12 to confirm the selected group.
- Allow Escape to cancel the selector with no changes.
- Show group name, key name, and description in the selector.
- Keep the selected group session-local and reset to the first configured group on startup.

## Configuration Format
The configuration is a top-level dictionary of groups. Each group contains F-key entries.

Example:

```json
{
  "navigation": {
    "F1": {
      "text": "build",
      "description": "Run the build"
    },
    "F2": {
      "text": "status",
      "description": "Show repository status"
    }
  },
  "workflow": {
    "F1": {
      "text": "test",
      "description": "Run tests"
    },
    "F2": {
      "text": "lint",
      "description": "Run linting"
    }
  }
}
```

### Configuration Rules
- The outer dictionary keys are group names.
- Each group value must be a dictionary.
- Each function-key entry must be a dictionary.
- Each function-key entry must contain a non-empty `text` string.
- Each function-key entry must contain a non-empty `description` string.
- Only F1-F8 are allowed for user-defined bindings.
- F9-F12 are reserved and must not appear in user configuration.
- Each group defines its own F-key bindings.
- Duplicate F-key assignments across groups are allowed.
- The first configured group is the default active group at startup.
- Group selection does not persist across sessions.

## Runtime Behavior
### Startup
1. Load the grouped function-key configuration.
2. Validate the full structure.
3. Reject invalid group shapes, reserved keys, and missing fields.
4. Activate the first configured group.
5. Register live key bindings for the active group.

### Normal Key Handling
- F1-F8 insert the text defined by the active group.
- The active group determines runtime behavior for F1-F8.
- Insert text should preserve the existing behavior of prefixing a space when the buffer already contains text.
- The selector hotkey F12 is always reserved for internal use.
- F9-F11 remain reserved for future internal controls.

### Selector Mode
- F12 opens the selector.
- The selector displays the group name and each F-key with its description.
- The selector does not display the raw insertion text.
- Tab advances to the next group and loops back to the first group.
- F12 confirms the previewed group and makes it active.
- Escape exits selector mode and leaves the active group unchanged.
- The selector must not alter active key bindings until confirmation.

## Internal Data Model
The implementation should maintain two conceptual layers:

- `GroupConfig`
  - name
  - key mapping
- `BindingConfig`
  - key name
  - text
  - description

The runtime may flatten the active group into the current handler table, but the source of truth remains the grouped config.

## Validation Behavior
Validation must fail fast and produce a clear error when:
- the root config is not a dictionary
- a group value is not a dictionary
- a key is outside F1-F8
- a binding entry is missing `text`
- a binding entry is missing `description`
- a binding entry is not a dictionary
- a group is empty, if empty groups are disallowed by policy

The validator should normalize F-key names consistently and enforce per-group structure validation across groups.

## Selector UX
The selector should present:
- group name
- F-key name
- description

It should not present:
- raw insertion text
- internal metadata not needed for selection

This makes the selector useful as a browsing tool rather than an editor.

## Implementation Notes
- Add a loader path that reads grouped config and validates it before registration.
- Add a selector state machine that tracks the current group and preview group.
- Add a binding activation step that updates live F1-F8 handlers from the selected group.
- Keep selector state separate from the normal input path.
- Preserve the current insertion semantics for active F-key text expansion.
- Ensure the first configured group is the default selection on app startup.
- Ensure active group selection is session-local only.

## Error Handling
- Invalid configuration should stop startup or reload with a clear error.
- Selector cancellation should be a no-op.
- Binding validation should be rejected before any runtime binding is activated.
- Logging should include enough context to identify the failing group and key.

## Testing Requirements
Tests should verify:
- grouped config parsing
- required fields on each binding entry
- reserved-key rejection
- selector navigation
- selector accept/cancel behavior
- startup default group selection
- non-persistence across restarts
- text insertion behavior for the active group
- selector display contents

## Non-Goals
- Persisting group selection across sessions
- Showing raw insertion text in the selector
- Supporting user-defined keys beyond F1-F8
- Allowing F9-F12 in user config
- Enforcing unique F-key assignments across groups

## Acceptance Criteria
The feature is complete when:
- grouped configuration is supported
- only one active group exists at a time
- F12 opens a working selector
- Tab cycles through groups
- F12 confirms the selected group
- Escape cancels without side effects
- descriptions are required and displayed
- startup defaults to the first group
- duplicate F-key assignments across groups are allowed
- the behavior is covered by tests
