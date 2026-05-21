# System prompt template used to initialize the system's state and guidelines.
#
# SP-1/SP-2/SP-7: previously this module exposed a mutable SYSTEM_PROMPT
# global, which conversation.py rebound via `global SYSTEM_PROMPT;
# SYSTEM_PROMPT += ...` to inject the session ID. Because of `from … import …`
# semantics, that rebind only affected conversation.py's local binding —
# other modules (llm.py, history.py, built_in_commands.py) kept their
# original reference and sent the prompt *without* the session-ID line.
# Re-initialization also compounded duplicate session-ID appendages.
#
# This module now exposes:
#   - SYSTEM_PROMPT_TEMPLATE: the static base prompt (no session-specific bits)
#   - build_system_prompt(session_id=None): assembles the final prompt fresh
#     on every call, no global state mutated
#   - SYSTEM_PROMPT: backward-compat alias for the static template; callers
#     that don't need session injection can still use it
#
# Callers that need the session ID line should call
# build_system_prompt(session_id=config.SESSION_ID) at the call site.

SYSTEM_PROMPT_TEMPLATE = """
Formatting re-enabled - code output should be wrapped in markdown.

You are an advanced command-line coding assistant.

Core priorities:
1. Write maintainable code.
2. Prefer small, reversible changes.
3. Fix root causes, not symptoms.
4. Verify behavior with tests.
5. Optimize for test durability and non-brittleness.

Testing rules:
- Test public APIs and observable outcomes only — not internals, private helpers, or exact internal call order.
- For failure cases, simulate via boundary state (filesystem, env vars, dependency injection) — never by patching internals.
- Use real tempfiles/dirs when filesystem behavior is under test; avoid monkeypatching Path, __file__, or low-level OS primitives.
- Keep fixtures small, deterministic, behavior-focused. No timing-sensitive assertions, no brittle boundary math.
- If a behavior is hard to test cleanly, expose a small public seam in the production code rather than testing internals.
- If a test requires a hack to pass, stop and redesign the test or the code.

Code change rules:
- Use the appropriate file-edit tool for code changes.
- After changes, verify the updated file and summarize what changed.

Never trade correctness or test design quality for speed.
"""


def build_system_prompt(session_id=None):
    """Return the assembled system prompt, optionally with a session-ID instruction appended.

    Args:
        session_id: If provided, appends a line instructing the model to use
            this session ID in todo tool calls. If None, only the static
            template is returned.

    Returns:
        str: The fully assembled system prompt.
    """
    if not session_id:
        return SYSTEM_PROMPT_TEMPLATE
    return (
        SYSTEM_PROMPT_TEMPLATE
        + f"\nCurrent session ID: {session_id}. Use this SESSION_ID in all todo tool calls.\n"
    )


# Backward-compat alias. Existing callers that import SYSTEM_PROMPT directly
# will get the static template (without session injection). Migrate to
# build_system_prompt(session_id=...) at the call site to get the
# session-aware version. The name remains a plain string, so monkeypatching
# in tests continues to work.
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE
