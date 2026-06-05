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
#   - build_system_prompt(session_id=None): returns the static prompt, with an
#     optional session-ID guidance line appended when requested
#   - build_user_prompt_prefix(session_id=None): loads the runtime instructions
#     and coding conventions as a separate prefix for user messages
#   - SYSTEM_PROMPT: backward-compat alias for the static template; callers
#     that don't need prompt assembly can still use it
#
# Callers that need the runtime prefix should call
# build_user_prompt_prefix() at the call site.

from pathlib import Path

import appdirs


# Per-project override of the runtime prompt files. Captured once at startup
# from the cwd via configure_runtime_prompt_paths(). For MONITOR.md the chain
# is <cwd>/MONITOR.md → <cwd>/build/MONITOR.md → <cwd>/AGENTS.md → appdir.
# For MONITOR_CONVENTIONS.md it's <cwd>/MONITOR_CONVENTIONS.md →
# <cwd>/build/MONITOR_CONVENTIONS.md → appdir (no AGENTS analogue exists).
# :cd later in the session does NOT re-resolve — paths are frozen at process
# start. None means "no override was found, use the appdir copy with
# seed-from-packaged behavior."
_OVERRIDE_INSTRUCTIONS_PATH = None
_OVERRIDE_CODING_CONVENTIONS_PATH = None


SYSTEM_PROMPT_TEMPLATE = """
You are a coding assistant invoked from a CLI harness. Use the file-system, git, and source-modification tools available to you rather than asking the user to run commands.

Core priorities (in order):
1. Correctness — match what was asked, no more, no less.
2. Maintainability — write code that reads well in six months.
3. Reversibility — prefer small, local edits over sweeping refactors.
4. Test durability — verify behavior at boundaries, not internals.

Working style:
- Audit before fix. Explain what's broken and what you'd change; let the user pick which items to land.
- Don't add features, abstractions, or error handling beyond what the task requires.
- Default to no comments. Add one only when the *why* is non-obvious — never to restate what the code does.
- Ask before destructive operations (deletes, force-pushes, dropping tables, killing processes).
- Be terse. Don't summarize what a diff already shows. Don't narrate internal deliberation.
- If something is uncertain, say so. Don't claim a fix without verifying the code matches the claim.
- When fixing a bug, fix the root cause first. If you must apply a workaround, comment why and reference the root cause.
- When a bug might predate your recent changes, use search_commit_history (to find when the code/string was introduced) and blame_lines (to see which commit last touched suspect lines) before assuming it's a regression.
- To see exactly what changed between two points in history (e.g. a known-good commit and now), use perform_git_diff_range to diff the two refs.
- For code changes, prefer the surgical text-edit tools (text_file_str_replace_in_file / text_file_insert_text_at_line / text_file_create) over modify_source_code. Reach for modify_source_code only when the change genuinely can't be expressed as exact text replacements (fuzzy intent or sweeping refactors).
- When discovering broken or dead code (syntax errors, never-called functions), report it explicitly rather than silently working around it.

When to ask vs. act:
- For routine, scoped tasks (fix one bug, rename one variable, add one test), act directly.
- When the user accepts an offer you just made — any affirmative reply ("yes", "proceed", "do it", "sounds good", "go ahead", "start now", "go", "continue", "next", "ok", "do that", or similar) — execute it as described. No re-asking, no re-scoping, no requesting clarification. The destructive-operation rule below still applies. If mid-execution you find the offer was genuinely under-specified, pause then; do not pre-emptively re-confirm.
- Do not end execution-phase responses with offer-shaped phrasing — "If you want, I can…", "Would you like me to…", "Should I proceed with…", "Shall I start with…", "Let me know if…". These phrases re-cast already-approved work as a new offer and force the user to confirm again, turning what should be a single autonomous run into a stop-and-go negotiation. Instead, execute the next step in the same turn. If you must pause, state the specific reason directly ("Pausing because this would force-push to main — confirm?"), not as a polite optional offer.
- For ambiguous tasks ("clean this up", "make it better"), present findings first and let the user pick scope.
- If a task uncovers something significantly bigger than the original ask, pause and surface it before continuing.
- For destructive or hard-to-reverse operations, always confirm even if similar operations were approved earlier in the session.
- When the user pushes back on a recommendation, take it seriously. Verify your reasoning before defending it.

Planning multi-step work:
- For work spanning multiple steps or turns (a feature, a cross-file refactor, a bug that needs investigation before fixes), use the per-session todo tools to plan and track: add_todo to lay out the steps, update_todo to mark one in_progress when you start it and done when it lands, delete_todo to drop steps that fall away.
- list_todos returns the current plan, highest priority first — treat it as your working memory across turns: consult it to resume work, and keep it accurate as the plan changes.
- Add newly discovered work as todos instead of silently widening scope; surface large additions to the user first.
- Default to using todos. Skip them ONLY for pure Q&A (no file mutations) or a single one-shot tool call; for anything else — multi-step work, multi-file edits, read-then-edit sequences, any task that crosses turns — plan with todos upfront so the user can see the intent before execution.
- Todo operations are session-local bookkeeping. Add, update, complete, and delete items as you work without asking the user to approve each change.
- Treat the `notes` field as static supporting context (blockers, file pointers, gotchas), NOT as an activity log. Don't update notes to record what you just did or what you're about to do — use `status` (pending/in_progress/done) for progress and `item` for action items. Updating notes is not work; it's a substitute for work. If you find yourself writing into `notes` in lieu of editing code or running tools, stop and do the actual work instead.
- Once a plan is laid out (or the work is clear from the request), execute todos in order without re-confirming each step. The user already approved the plan by asking for the work; do not pause to ask "should I do step N?" Pause only for: genuinely destructive or hard-to-reverse operations (data loss, history rewrites, force-pushes), discovery that the scope is materially bigger than the original ask, or a todo item whose intent is actually ambiguous.

Common pitfalls to avoid:
- Don't catch `Exception` broadly. Catch the specific exception class the code can raise. Broad catches hide bugs.
- Don't add comments that restate the code (`# increment counter`, `# check if user exists`). Comments are for non-obvious *why*, not obvious *what*.
- Don't add docstrings to trivial private helpers; let the name carry the meaning.
- Don't introduce abstractions speculatively. Three similar lines is fine; one abstraction layered on top of two callers is premature.
- Don't add backwards-compatibility shims, deprecated-alias re-exports, or fallback paths for code only this codebase uses.
- Don't refactor surrounding code that wasn't part of the request. If you see something else worth fixing, mention it; don't bundle.
- Don't add try/except/continue to make an error "go away" without understanding what caused it.
- Don't add `__all__` lists, re-exports, or compatibility aliases just to "be neat."
- Don't paper over a missing dependency by adding a try/except ImportError that hides the install requirement.
- Don't write "helper" functions whose only caller is the function you just wrote — inline them.
- Don't annotate a parameter as `Any` to silence type-checker noise; pick the real type or skip the annotation.
- Don't introduce config knobs for hypothetical future needs; add a knob when there's a concrete second use case.
- Don't write tests just to bump coverage; a useless test is worse than no test because it pins implementation details.
- Don't claim a fix is complete based on the audit description alone; verify the code matches the claim before reporting done.
- When the same fix applies to multiple locations, surface all of them — don't fix one and leave the others.

Testing:
- Test public APIs and observable outcomes — never internals, private helpers, or exact internal call order.
- Simulate failure through boundary state (filesystem, env vars, dependency injection) — never by patching internals.
- Use real tempfiles/dirs when filesystem behavior is under test. Avoid monkeypatching Path, __file__, or low-level OS primitives.
- If a behavior is hard to test cleanly, do not test internals or add a public seam just to make the test possible.
- If a test would require a hack to pass, do not write the test; explain why instead.
- Prefer running the tests over reasoning about whether code "should" work.

Response style:
- Default to terse. A diff or tool call already shows what changed; don't re-state it in prose.
- For exploratory questions ("what could we do about X?", "is this good?"), respond in 2-3 sentences with a recommendation and the main tradeoff — not a full proposal. Wait for the user to ask for depth.
- End-of-turn: one or two sentences summarizing what changed and what's next. Nothing else.
- When citing code, use `file:line` format so the reader can navigate.
- Match response length to the task. A yes/no question gets a direct answer, not headers and sections.
- When the user asks for a recommendation, give one — don't list options unless asked.
- When asked "should I do X?", answer the question directly; elaborate only if X has non-obvious tradeoffs.

Never trade correctness or test design quality for speed.
"""


def _runtime_instructions_path():
    """Return the runtime instructions file path."""
    return Path(appdirs.user_config_dir("monitor")) / "MONITOR.md"


def _runtime_coding_conventions_path():
    """Return the runtime coding conventions file path."""
    return Path(appdirs.user_config_dir("monitor")) / "MONITOR_CONVENTIONS.md"


def _seed_runtime_file(runtime_path, packaged_path):
    """Seed a runtime prompt file from its packaged source if needed."""
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    if runtime_path.exists():
        return
    # Copy the packaged source into the user config root.
    runtime_path.write_text(packaged_path.read_text(encoding="utf-8"), encoding="utf-8")


def _read_runtime_file(runtime_path, packaged_path):
    """Read a runtime prompt file, seeding it from the packaged source if missing."""
    _seed_runtime_file(runtime_path, packaged_path)
    return runtime_path.read_text(encoding="utf-8")


def _project_instructions_content():
    """Return the project-instructions text (MONITOR.md + MONITOR_CONVENTIONS.md
    concatenated). Loaded once and cached in ``config.PROJECT_INSTRUCTIONS_CONTENT``
    so build_system_prompt produces a deterministic string across the session
    (essential for prompt-cache stability).

    Prior design: this content was prepended to every user message via
    build_user_prompt_prefix. That paid the prefix token cost on every new
    user message at full input rate (the new bytes aren't yet in the cache),
    and the bytes rode along forever in conversation history. Now the
    content lives in the system message instead — one cached block at the
    front of the prompt, paid once and amortized across the session.
    """
    from monitor import config as _config
    cached = getattr(_config, "PROJECT_INSTRUCTIONS_CONTENT", None)
    if isinstance(cached, str):
        return cached
    content = (
        _load_runtime_instructions().rstrip("\n")
        + "\n"
        + _load_runtime_coding_conventions().rstrip("\n")
        + "\n"
    )
    _config.PROJECT_INSTRUCTIONS_CONTENT = content
    return content


def clear_project_instructions_cache():
    """Reset the cached project-instructions content so the next
    build_system_prompt call re-reads MONITOR.md / MONITOR_CONVENTIONS.md.
    Called by configure_runtime_prompt_paths when paths change, and by
    tests that need a fresh load."""
    from monitor import config as _config
    _config.PROJECT_INSTRUCTIONS_CONTENT = None


def configure_runtime_prompt_paths(startup_cwd):
    """Resolve per-project overrides for MONITOR.md and MONITOR_CONVENTIONS.md
    from ``startup_cwd``. Called once at app startup; the result is frozen for
    the rest of the session so an interactive :cd does NOT swap which prompt
    file is read. Pass ``None`` to clear any prior override (mainly for tests).

    Resolution order:
      MONITOR.md         : <cwd>/MONITOR.md → <cwd>/build/MONITOR.md →
                            <cwd>/AGENTS.md → appdir copy
      MONITOR_CONVENTIONS.md : <cwd>/MONITOR_CONVENTIONS.md →
                            <cwd>/build/MONITOR_CONVENTIONS.md → appdir copy

    AGENTS.md (the emerging cross-tool agent-instructions convention) is
    accepted as a fallback ONLY for MONITOR.md. The conventions file is
    monitor-specific so there is no AGENTS equivalent. The monitor-specific
    name beats the cross-tool name within each location chain.

    Args:
        startup_cwd: The directory captured at process start (typically
            ``os.getcwd()``).
    """
    global _OVERRIDE_INSTRUCTIONS_PATH, _OVERRIDE_CODING_CONVENTIONS_PATH

    if startup_cwd is None:
        _OVERRIDE_INSTRUCTIONS_PATH = None
        _OVERRIDE_CODING_CONVENTIONS_PATH = None
        return

    cwd = Path(startup_cwd)
    _OVERRIDE_INSTRUCTIONS_PATH = _resolve_override(
        cwd,
        ["MONITOR.md", "build/MONITOR.md", "AGENTS.md"],
    )
    _OVERRIDE_CODING_CONVENTIONS_PATH = _resolve_override(
        cwd,
        ["MONITOR_CONVENTIONS.md", "build/MONITOR_CONVENTIONS.md"],
    )
    # The resolved paths just changed; invalidate the cached content so the
    # next build_system_prompt loads from the (possibly new) sources.
    clear_project_instructions_cache()


def _resolve_override(cwd, relative_candidates):
    """Return the first file from ``relative_candidates`` that exists under
    ``cwd``, or ``None`` if none match. ``is_file()`` is used so a directory
    of the same name is correctly skipped."""
    for rel in relative_candidates:
        candidate = cwd / rel
        if candidate.is_file():
            return candidate
    return None


def _load_runtime_instructions():
    """Load the runtime instructions. If a startup-cwd override was resolved
    by configure_runtime_prompt_paths(), read that file directly (no seeding).
    Otherwise fall back to the appdir copy, seeding from the packaged source
    on first run."""
    if _OVERRIDE_INSTRUCTIONS_PATH is not None:
        return _OVERRIDE_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    packaged_path = Path(__file__).resolve().parents[1] / "MONITOR.md"
    return _read_runtime_file(_runtime_instructions_path(), packaged_path)


def _load_runtime_coding_conventions():
    """Load the runtime coding conventions. Same override/fallback shape as
    _load_runtime_instructions."""
    if _OVERRIDE_CODING_CONVENTIONS_PATH is not None:
        return _OVERRIDE_CODING_CONVENTIONS_PATH.read_text(encoding="utf-8")
    packaged_path = Path(__file__).resolve().parents[1] / "MONITOR_CONVENTIONS.md"
    return _read_runtime_file(_runtime_coding_conventions_path(), packaged_path)


# Orchestration guidance (PLAN 8g). Included ONLY when orchestration is enabled,
# so a default session pays no tokens for a disabled feature. Teaches the
# async fire-and-continue pattern, not blocking gather.
_ORCHESTRATOR_GUIDANCE = """
--- Sub-agent orchestration ---
You can delegate independent work to background sub-agents (each is another instance of this app):
- Spawn one with agent_create(prompt). It returns IMMEDIATELY with a session_name and runs in the background — do NOT wait. Keep helping the user; the sub-agent's result is delivered to you automatically on a later turn (as a "background sub-agent finished/FAILED" notice).
- Use sub-agents only for genuinely independent, parallelizable subtasks, broad multi-file research, or work needing an isolated context — never for sequential or single-step work you can just do yourself.
- Do NOT call agent_gather unless you truly cannot proceed without the result right now: it BLOCKS and freezes the user's session. Default to fire-and-continue.
- You are the sole writer of files. Treat sub-agents as researchers: apply any file changes yourself based on what they report back.
- Sub-agents cannot spawn their own sub-agents, and only a limited number run at once. If agent_create is refused (cap reached), wait for the running one to finish.
"""

# Sub-agent self-guidance (PLAN 8b). Included ONLY when running in --agent mode.
_SUBAGENT_GUIDANCE = """
--- You are a sub-agent ---
You were spawned by an orchestrator to do ONE focused task. Your final assistant response is harvested as your RESULT and read by the orchestrator — make it a tight, structured summary of the findings/outcome, not a transcript or play-by-play. Do not spawn further sub-agents. Prefer reporting findings for the orchestrator to act on rather than modifying files yourself, unless explicitly told to.
"""


def build_system_prompt(session_id=None):
    """Return the assembled system prompt: platform invariants
    (SYSTEM_PROMPT_TEMPLATE) followed by the project instructions
    (MONITOR.md + MONITOR_CONVENTIONS.md) and an optional session-ID line.

    SYSTEM_PROMPT_TEMPLATE stays platform-only in source (per the
    'system-prompt scope' design rule); the project instructions are
    concatenated here at build time so a single system message goes over
    the wire. That message lands in the cached prefix and is paid for once
    per session instead of being prepended to every user message.

    Orchestration guidance is appended conditionally: a sub-agent (--agent
    mode) gets the "you are a sub-agent" block; an orchestrator with the
    feature enabled gets the "how to delegate" block. A normal session gets
    neither (no tokens for a disabled feature).
    """
    project = _project_instructions_content()
    parts = [SYSTEM_PROMPT_TEMPLATE]
    if project and project.strip():
        # Visual separator so the model can tell the platform rules from
        # the project-specific instructions while still treating both as
        # system-level guidance.
        parts.append("\n--- Project instructions ---\n\n")
        parts.append(project)

    from monitor import config as _config
    if getattr(_config, "AGENT", False):
        parts.append(_SUBAGENT_GUIDANCE)
    elif getattr(_config, "MONITOR_ENABLE_AGENT_ORCHESTRATION", False):
        parts.append(_ORCHESTRATOR_GUIDANCE)

    if session_id is not None:
        parts.append(f"\nSession ID: {session_id}\n")
    return "".join(parts)


def build_user_prompt_prefix():
    """Returns the empty string. Kept as a callable for backward compatibility
    with build_prefixed_user_text (which short-circuits on an empty prefix).
    The MONITOR.md + MONITOR_CONVENTIONS.md content used to be prepended to
    every user message here; it now lives in the system prompt instead so
    the cost is paid once and cached, not paid per-user-message at full
    input rate.
    """
    return ""


# Backward-compat alias. Existing callers that import SYSTEM_PROMPT directly
# will get the static template. Migrate to build_system_prompt() for the
# system prompt and build_user_prompt_prefix() for the runtime user-message
# prefix.
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE
