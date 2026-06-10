# PLAN_TOOL_ROUTE_EDIT

## Goal
Make Monitor feel more like a polished coding agent by enforcing an edit workflow that is:
- deterministic when the change is exact,
- conservative when the change is ambiguous,
- concise in its output,
- and always followed by verification.

This plan specifically covers the route from user intent to tool choice, edit execution, and post-edit validation.

The initial rollout should assume the existing toolset is already sufficient for most of the target behavior. The first implementation pass should therefore focus on prompt and tool-guidance changes rather than new tooling or heavy runtime enforcement.

## The target behaviors

### A. Deterministic edit pipeline
Prefer:
1. inspect
2. plan
3. exact edit
4. verify

Exact edits should use the most specific tool available:
- `text_file_str_replace_in_file` for a unique replacement
- `text_file_insert_text_at_line` for a precise insertion
- `text_file_create` for a new file
- `bulk_replace_in_files` for mechanical repeated changes
- `modify_source_code` only when the change is genuinely fuzzy or sweeping

### B. Reduced generic assistant behavior
The harness should speak like a code operator, not a chatty assistant.

Desired behavior:
- terse by default
- report what changed, not what is obvious
- avoid unnecessary offers or re-asking after approval
- say when uncertainty exists instead of bluffing

### C. Better tool selection
The assistant should route to tools the way a strong coding agent would:
- inspect before editing when the file or context is uncertain
- use the narrowest edit tool that fits the request
- prefer surgical tools over regeneration
- use history tools when regression suspicion exists

### D. Tight verification loop
After writes, the harness should verify the result before claiming success:
- always diff the change
- run focused tests when clearly relevant
- type-check Python changes when clearly relevant
- report verification failures plainly

The default verification policy should be conservative and cheap:
- always run diff after a write
- stop there for docs-only or clearly non-executable changes
- run language-specific checks when the changed files make that applicability obvious
- say when no relevant automated check was clearly applicable

## Recommended routing hierarchy

### Read/inspect tools first when needed
Use these before editing if context is incomplete:
- `find_files`
- `ripgrep_search_tool`
- `cat_file`
- `cat_file_range`
- `blame_lines`
- `search_commit_history`
- `perform_git_diff_range`

### Edit tools in priority order
1. `text_file_str_replace_in_file`
2. `text_file_insert_text_at_line`
3. `text_file_create`
4. `bulk_replace_in_files`
5. `modify_source_code`

### Post-edit verification tools
- `perform_git_diff`
- `perform_git_diff_file`
- `run_python_tests`
- `type_check_python`

## Implementation approach

### 1. Start with prompt and tool-guidance changes
The existing tools are already broad enough to support the target behavior. The first implementation pass should therefore update system guidance and tool-routing instructions before adding harness logic.

### 2. Make exact edits the default path
The tool descriptions already encourage exact tools. Strengthen that by making the assistant treat `modify_source_code` as a last resort.

### 3. Add routing bias toward inspection
If the assistant does not know the file layout or exact target text, it should inspect first rather than guessing.

### 4. Validate write outcomes conservatively
Every write tool should lead to some form of verification before the assistant reports completion, with diff as the baseline and heavier checks only when clearly applicable.

### 5. Keep output concise
Response templates should favor short factual summaries:
- what changed
- where it changed
- how it was verified

Prompt and tool-guidance changes should be treated as the initial delivery milestone. Runtime enforcement, telemetry, and deeper evaluation can follow later if behavior still drifts.

## Non-goals
- Do not remove fuzzy editing entirely.
- Do not force every edit through the same tool.
- Do not make the harness verbose or conversational by default.
- Do not weaken the deterministic edit tools in favor of LLM rewrites.

## Success criteria
- Exact edits are handled by exact tools most of the time.
- Mechanical changes use bulk replacement rather than file regeneration.
- `modify_source_code` becomes rare.
- The assistant verifies changes instead of assuming success.
- The harness feels closer to a disciplined coding agent than a general chatbot.
