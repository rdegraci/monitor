# PLAN_IMPROVED_C

## Goal
Improve the `C:` status indicator so it remains a conservative, useful estimate of remaining context during normal chat and tool-heavy workflows.

## Current state
- `C:` is rendered in `src/monitor/lib/display_output.py`.
- The conservative margin is applied in `src/monitor/core/conversation.py` before prompt rendering.
- The display layer remains unchanged.
- Tool-heavy detection now uses structured indicators and recent message metadata rather than free-text substring matching.
- The numeric value comes from `context_remaining` / `tokens_remaining` passed by `src/monitor/core/conversation.py`.
- The app already tracks token usage separately via `monitor.lib.token_management`.
- `monitor.core.llm` and related adapters already update token usage based on provider responses when available.

## Proposed approach
Keep the existing history-based remaining-context calculation, but make the displayed value more conservative by applying a safety margin before rendering or before passing the value to the display layer.

### Margin policy
- Base margin: 128 tokens
- Typical tool usage: 256 tokens
- Heavy tool usage / agent mode: 512 tokens

### Heuristics for larger margins
Prefer a larger margin when:
- `config.AGENT` is enabled
- tool-capable request paths are active
- recent turns involved tool calls or large tool output

## Rationale
This approach avoids rewiring the token pipeline while making the status line less optimistic in scenarios where tool overhead can be significant.

## Non-goals
- Do not replace the existing token accounting pipeline.
- Do not make the display line depend solely on provider-reported usage.
- Do not change the meaning of `C:` away from a remaining-context estimate.
