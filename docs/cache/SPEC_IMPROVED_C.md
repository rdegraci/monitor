# SPEC_IMPROVED_C

## Summary
Improve the `C:` status indicator so it displays a conservative estimate of remaining context. The current value is already derived from live conversation state, but it can be made safer by applying a context margin before prompt rendering, based on conversation state and recent message metadata.

## Existing behavior
- `src/monitor/core/conversation.py` computes `context_remaining` from the active context budget and the token count of conversation history.
- `src/monitor/lib/display_output.py` formats the `C:` label and displays the passed value.
- Token usage is tracked separately via `monitor.lib.token_management` and updated from actual provider responses when available.

## Desired behavior
- Keep the existing conversation-history-based context accounting.
- Reduce the displayed remaining context by a configurable safety margin in `conversation.py` before prompt rendering.
- Use a larger safety margin when tools are likely to be used heavily.
- Preserve the existing meaning of `C:` as a remaining-context estimate, not a provider-reported exact value.
- Keep the display layer formatting-only.

## Margin policy
Use these default values:
- 128 tokens for normal chat
- 256 tokens when tools are enabled or likely to be used
- 512 tokens when the session is tool-heavy or agent mode is active

### Margin escalation signals
Prefer a larger margin when any of these are true:
- `config.AGENT` is enabled
- structured tool indicators are present in the active request path
- recent message metadata suggests tool calls or large tool outputs

## Implementation guidance
- Keep the token usage pipeline intact.
- Apply the margin at the point where `context_remaining` is finalized for display in `conversation.py`.
- Prefer conservative behavior over exactness.
- Avoid moving token counting logic into the display layer unless necessary.
- Keep `src/monitor/lib/display_output.py` as a formatting-only layer for the `C:` label.

## Acceptance criteria
- `C:` still renders in the prompt/status line.
- The displayed value is never more optimistic than the underlying context estimate.
- Tool-heavy sessions show a larger safety buffer.
- Existing token usage tracking remains unchanged.
- Existing startup and smoke tests continue to pass.

## Notes
This is intentionally a small, safe improvement rather than a rewrite of token accounting. The goal is to make the status line more trustworthy in real sessions, especially when structured tool usage and recent tool-related message metadata add extra overhead.
