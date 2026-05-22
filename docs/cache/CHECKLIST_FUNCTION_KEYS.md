# CHECKLIST_FUNCTION_KEYS

## Scope
- [x] Confirm grouped function-key bindings are the desired UX.
- [x] Confirm top-level group names are the outer configuration keys.
- [x] Confirm user-assignable keys are limited to F1-F8.
- [x] Confirm F9-F12 are reserved for internal application use.
- [x] Confirm F12 is the dedicated selector hotkey.
- [x] Confirm Tab cycles through groups in the selector.
- [x] Confirm F12 accepts the currently previewed group.
- [x] Confirm Escape exits the selector with no changes.

## Configuration
- [x] Define the JSON shape for grouped bindings.
- [x] Use group names as the outer configuration keys.
- [x] Keep group metadata optional for now.
- [ ] Decide whether inactive groups can contain invalid entries without blocking other groups.
- [x] Do not persist group selection across restarts.
- [ ] Require each binding entry to include both text and description.

## Validation
- [x] Validate that each group is a dictionary.
- [x] Validate that only F1-F8 are present in each group.
- [x] Reject F9-F12 in user configuration.
- [x] Normalize key names consistently.
- [x] Reject malformed or empty group definitions.
- [ ] Define the error message strategy for invalid function-key configuration.
- [ ] Reject binding entries missing text or description.

## Runtime Behavior
- [ ] Load grouped bindings from configuration.
- [ ] Flatten the active group into prompt-toolkit key bindings.
- [ ] Keep selector state separate from active binding state.
- [ ] Ensure switching groups updates the live bindings cleanly.
- [ ] Ensure selector cancellation leaves the active group unchanged.
- [x] Ensure the current group is visible in the prompt or selector UI.
- [x] Show the available group names in the selector.
- [x] Show the mappings in the currently previewed group.

## User Experience
- [x] Make the selector interaction discoverable in help text or docs.
- [x] Document that F1-F8 are user keys and F9-F12 are reserved.
- [x] Document the purpose of the selector hotkey.

## Testing
- [ ] Add tests for grouped configuration parsing.
- [ ] Add tests for per-group key validation.
- [ ] Add tests for selector navigation.
- [ ] Add tests for accept/cancel behavior.
- [ ] Add tests for reserved-key rejection.
- [ ] Add tests that the active group determines the bound keys.
- [ ] Add tests that selector cancellation leaves bindings unchanged.
- [ ] Add tests that binding entries require both text and description.
- [ ] Add tests that duplicate F-key assignments across groups are allowed.

## Future Considerations
- [ ] Decide whether groups should support descriptions.
- [ ] Decide whether groups should support enabled/disabled flags.
- [ ] Decide whether the selector should support search once many groups exist.
- [ ] Decide whether more internal keys beyond F12 are needed later.
