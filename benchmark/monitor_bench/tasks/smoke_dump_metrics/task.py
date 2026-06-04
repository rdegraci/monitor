"""Smoke-test task: exercises the bench pipeline end-to-end with no LLM call.

The prompt is the built-in command ``:macros``, which prints the current
macro table and returns immediately. The runner's own appended
``:dump_metrics`` line then fires, writing the metrics JSON that the
grader checks.

What this proves when it passes:
  - python -m monitor launches as a subprocess under the runner's cwd
  - --script reads lines one at a time
  - process_input dispatches built-in commands correctly
  - :dump_metrics writes the JSON the runner expects
  - The grader can ingest the JSON and call the run a pass

What it does NOT prove (intentionally — that's the live-LLM test's job):
  - LLM completion path
  - Tool-call chain blocking
  - Cost / token accounting under real model load
"""

NAME = "smoke_dump_metrics"
TAGS = ["smoke"]

# Two built-ins back-to-back. ``:macros`` is a side-effect-only print that
# does not invoke the model — so this task costs $0 and runs in <2s. The
# runner appends ``:dump_metrics`` itself.
PROMPT = ":macros"


def grade(workspace, metrics, stdout, stderr, exit_code, history=None):
    """Pass if Monitor exited cleanly and both dump JSONs landed.

    We deliberately do NOT check token / cost values — they are zero on
    a no-LLM run, and we don't want the smoke test to fail if a future
    change adds startup-time token counting. Same for history length:
    pure built-in prompts never touch CONVERSATION_HISTORY, so a length
    of zero is the *correct* observation here. We just check the
    pipeline plumbing: did both dumps fire, and is the history payload
    structurally a list?
    """
    if exit_code != 0:
        return False, f"non-zero exit ({exit_code}); stderr tail: {stderr[-300:]!r}"
    if metrics is None:
        return False, "no metrics JSON written — :dump_metrics did not fire"
    if metrics.get("schema_version") != 1:
        return False, f"unexpected schema_version: {metrics.get('schema_version')!r}"
    required = {
        "session_id",
        "model",
        "session_cost_usd",
        "session_total_tokens",
        "session_tool_call_count",
        "session_loop_detector_trips",
        "session_compaction_count",
        "conversation_length",
        "user_message_count",
    }
    missing = required - set(metrics.keys())
    if missing:
        return False, f"metrics JSON missing keys: {sorted(missing)}"
    # History plumbing check — :dump_history must have fired and parsed
    # into a list. Empty list is fine: :macros doesn't touch
    # CONVERSATION_HISTORY, so a zero-length transcript is expected.
    if history is None:
        return False, "no conversation history written — :dump_history did not fire"
    if not isinstance(history, list):
        return False, f"history is not a list: {type(history).__name__}"
    return True, "metrics+history dumps fired with correct shape"
