# CHECKLIST_ADVANCED_TOOLS

- [ ] Define the exact output shape for the repo map / architecture summary tool.
- [ ] Define the input and output contract for reference tracing.
- [ ] Define how change-impact summaries will report likely affected files and tests.
- [ ] Define how scoped test selection will map changed paths to test targets.
- [ ] Define how instruction loading will decide whether companion instructions apply.
- [ ] Define the minimum viable AST-aware navigation capabilities.
- [ ] Add a lightweight planning step before edits where appropriate.
- [ ] Keep prompt-loading logic separate from task-execution logic.
- [ ] Add in-memory caching for reusable tool data in Python objects.
- [ ] Send only compact summaries from cached tool state to the LLM.
- [ ] Refresh cached data when files change.
- [ ] Choose a refresh strategy such as mtimes, hashes, file watchers, or diff-based invalidation.
- [ ] Verify the new tools improve task quality without adding excessive overhead.
- [ ] Add tests for any new tool contracts or routing logic.
- [ ] Document any assumptions or limitations in the repository notes.
- [ ] Make tool-layer summaries deterministic by default, with optional LLM rewriting only as a secondary step.
