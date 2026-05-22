# ROADMAP_IMPROVED_C

## Phase 1: Baseline confirmation
- Traced the current source of `context_remaining` and the final displayed `C:` value.
- Confirmed which state fields already indicate tool-heavy usage.

## Phase 2: Margin selection
- Completed the structured safety-margin helper for normal chat.
- Completed the heavier-margin path when tool usage is likely to be heavy.

## Phase 3: Integration
- Applied the conservative margin in `conversation.py` before the value is rendered.
- Kept token accounting and usage tracking unchanged.

## Phase 4: Validation
- Focused tests for the display output and margin-selection helper remain desirable.
- Run subprocess or smoke tests to confirm startup and prompt rendering still work.

## Phase 5: Review
- Confirm the user-facing behavior is conservative but still informative.
- Document the meaning of `C:` if needed in the README or developer notes.
