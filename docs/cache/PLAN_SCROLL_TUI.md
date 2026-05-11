# PLAN_SCROLL_TUI

## Goal
Update the `monitor_oop` TUI plan so it matches the current implementation state of the transcript viewport in `src/monitor_oop/core/presentation/tui.py`.

The Output pane now behaves like an internal transcript window backed by explicit transcript state, rather than relying on the terminal's native scrollback.

The viewport should:
- keep the newest transcript visible by default
- allow mouse wheel scrolling inside the Output pane
- avoid scrolling the whole Terminal.app window when the user scrolls over the transcript
- preserve the current rich transcript rendering
- continue to show assistant output with Bash syntax highlighting
- continue to render STX/ETX as visible yellow markers
- keep error and subagent transcript entries plain text

## Current direction
The TUI already has a transcript rendering pipeline and explicit viewport-related state. The next work is to keep this model accurate and complete as the transcript system evolves, rather than introducing a viewport architecture from scratch.

The current architecture is centered around:
- `TranscriptBuffer` for storing the full transcript history
- `TranscriptRenderer` for converting transcript entries into rendered visual lines and fragments
- `TranscriptViewport` for tracking the visible window over the rendered transcript

Instead of rendering the full transcript directly into the visible pane, the TUI maintains:
- a full internal transcript history in the buffer
- rendered transcript output produced by the renderer
- a visible viewport window over the rendered lines
- logic to map viewport changes to the currently visible portion of the transcript

This viewport is driven by the TUI, not by Terminal.app.

## Proposed implementation shape
1. Keep transcript entries in an internal history buffer.
2. Render entries into visual lines/fragments through `TranscriptRenderer`.
3. Track the current visible window through `TranscriptViewport`.
4. Make mouse wheel events adjust the viewport window.
5. Keep the viewport pinned to the bottom when new transcript entries arrive, unless the user has scrolled up.
6. Add a "follow tail" behavior so new output is automatically visible when the viewport is already at the bottom.

## Interaction model
- Normal transcript updates append to history in `TranscriptBuffer`.
- If the user has not scrolled up, the Output pane stays pinned to the newest lines through follow-tail behavior.
- If the user scrolls upward, the viewport should stay where the user left it until they scroll back down or follow-tail is re-enabled.
- Mouse wheel scrolling over the Output pane should move the viewport, not the terminal window.

## Rendering notes
- Transcript rendering still needs to preserve the current formatting behavior.
- Assistant transcript entries should remain Bash-highlighted.
- STX and ETX markers should remain visible and yellow.
- Error and subagent transcript entries should remain plain text.

## Risks
- Wrapped lines complicate viewport math because a single transcript entry may occupy multiple visual rows.
- Mouse support must be enabled in the prompt_toolkit application.
- The scroll behavior must not break the current keyboard interactions or output refresh path.
- The viewport implementation should avoid duplicating transcript state between the buffer, renderer, and visible window.

## Success criteria
- Scrolling over the Output pane changes only the transcript viewport.
- Terminal.app itself does not scroll when interacting with the Output pane.
- New transcript output still appears automatically when the viewport is at the bottom.
- Rich formatting remains intact.
- The input pane remains fixed and usable while transcript scrolling works.

## Remaining work
- Confirm mouse-wheel hit testing and event routing are enabled for the Output pane.
- Verify the follow-tail state transitions when the user scrolls up, scrolls back down, or new transcript entries arrive.
- Validate viewport math for wrapped lines and mixed-format transcript entries.
- Exercise the behavior in Terminal.app and other prompt_toolkit-capable terminals to ensure the terminal window does not absorb scroll events.
- Add or update tests that cover buffer growth, renderer output, viewport position changes, and follow-tail restoration.
