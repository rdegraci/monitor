# CHECKLIST_SCROLL_TUI

## Goal
Track the work needed to make the `monitor_oop` TUI Output pane behave like an internally scrollable transcript window.

## Scope
This tracker covers:
- `TranscriptBuffer` for transcript history storage
- `TranscriptViewport` for visible range and follow-tail state
- `TranscriptRenderer` for mapping buffered transcript lines into the Output pane
- mouse wheel scrolling inside the Output pane
- follow-tail behavior when new transcript entries arrive
- preserving the current Bash/yellow/plain transcript rendering semantics
- preventing the terminal window from scrolling when the user interacts with the Output pane

## Milestone 1: Transcript model and viewport
- [x] Introduce an internal transcript history buffer.
- [x] Define a rendered line model for the transcript history.
- [x] Add a visible viewport start index.
- [x] Add a visible viewport end index.
- [x] Define how wrapped transcript lines map into viewport lines.
- [x] Define follow-tail behavior for new transcript entries.

## Milestone 2: Mouse interaction
- [ ] Enable mouse support in the prompt_toolkit application.
- [ ] Capture mouse wheel events over the Output pane.
- [ ] Interpret wheel-up events as viewport scroll-up.
- [ ] Interpret wheel-down events as viewport scroll-down.
- [ ] Prevent the terminal window from handling scroll events when the TUI captures them.

## Milestone 3: Rendering integration
- [x] Render only the visible transcript window in the Output pane.
- [x] Preserve Bash syntax highlighting for assistant transcript content.
- [x] Preserve visible yellow STX/ETX markers.
- [x] Preserve plain-text rendering for error transcript entries.
- [x] Preserve plain-text rendering for subagent transcript entries.

## Milestone 4: Behavior and UX
- [x] Keep the viewport pinned to the bottom when no manual scroll position is active.
- [x] Keep the viewport stable when the user scrolls upward.
- [ ] Allow the user to return to the bottom of the transcript.
- [x] Keep the input pane fixed and responsive while scrolling the Output pane.
- [x] Keep output updates from blocking input editing.

## Milestone 5: Verification
- [ ] Add tests that scrolling the Output pane updates the internal viewport state.
- [ ] Add tests that new transcript entries follow the tail when appropriate.
- [ ] Add tests that formatting remains intact after viewport changes.
- [ ] Add tests that mouse scroll does not move the whole terminal window when captured by the TUI.

## Notes
- Prefer explicit viewport state over relying on terminal scrollback.
- Keep the first implementation small and predictable.
- Preserve the current transcript rendering semantics while introducing scroll control.
- Use `TranscriptBuffer`, `TranscriptViewport`, and `TranscriptRenderer` as the primary model/rendering components.
- Keep follow-tail behavior explicit so new transcript entries can either auto-scroll or preserve the user's manual position.
