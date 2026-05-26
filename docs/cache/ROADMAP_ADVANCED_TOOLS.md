# ROADMAP_ADVANCED_TOOLS

## Phase 1: Instruction routing
- Add task-based loading for companion instructions.
- Keep the base system prompt minimal and stable.
- Ensure code tasks can opt into extra repo guidance without affecting casual tasks.

## Phase 2: Planning and validation
- Add a short plan-before-edit step to encourage broader inspection.
- Add scoped test selection so validation aligns with touched code.

## Phase 3: Repository understanding
- Add a repo map / architecture summary capability.
- Add reference tracing so the agent can follow symbols across layers.
- Add change-impact summaries to estimate likely side effects.

## Phase 4: Navigation improvements
- Add AST-aware navigation where available.
- Prefer structure-aware lookup over raw text search for complex tasks.

## Phase 5: In-memory caching and refresh behavior
- Store tool state in memory to avoid recomputing repeated lookups within a session.
- Emit compact cache summaries to the LLM so it can reuse relevant context without flooding the prompt.
- Keep tool summaries deterministic by default; any LLM rewriting should be optional and secondary.
- Invalidate or refresh cache entries when files change to keep navigation and summaries aligned with the current repository state.

## Phase 6: Review and tuning
- Measure whether the new tools reduce short-sighted edits.
- Trim any tool that adds overhead without improving task quality.
- Document guidance for when each tool should be used.

## Success criteria
- More durable fixes.
- Better architectural fit.
- Fewer follow-up corrections.
- Better alignment between task type and loaded context.
