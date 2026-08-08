# Monitor Knowledge Wiki

The Monitor knowledge wiki is a project-local, persistent guidance layer that Monitor can provision and reference for a repository.

## What it is for

The wiki is intended to hold durable project knowledge that is useful across sessions, such as:
- repository orientation
- subsystem boundaries
- conventions
- recurring pitfalls
- links to deeper project pages

Monitor treats it as a compact, high-signal reference for the current project.

## Where it lives

Monitor stores wiki content under the user config directory, inside a `monitor-wiki` tree.
The per-project directory is derived from the project identity path, so different repositories get separate wiki locations.

The wiki root is managed by `monitor.lib.monitor_wiki`.

## Initialization and provisioning

When Monitor starts in a project, it resolves the project identity path from the startup directory.
If a project wiki does not already exist, Monitor can provision one and create a starter `INDEX.md`.

The starter index is meant to be edited into a real project guide. It begins with sections for:
- Overview
- Architecture
- Conventions
- Pitfalls

## How Monitor uses the wiki

If a configured project wiki has substantive content, Monitor includes wiki guidance in the system prompt.
That lets the model use the wiki as a session-local source of project context.

If the wiki is only the starter template, Monitor can still point the model at the wiki location, but it does not treat the content as substantive guidance yet.

Retrieval is intentionally simple:
- `INDEX.md` is the anchor page
- Monitor looks for up to two additional pages referenced from that index
- only existing markdown pages are included
- linked pages must match the uppercase name pattern `\b([A-Z][A-Z0-9_-]*\.md)\b` in `INDEX.md` (for example `ARCHITECTURE.md`, not `notes.md`)
- the page list is derived from those explicit references, not from broad topic search

This means the wiki is best treated as a curated navigation surface, not a free-form knowledge graph.

## Relevant built-ins

Wiki command handlers live in `src/monitor/lib/built_in_commands.py` and are
registered from `src/monitor/core/built_ins.py`. Helpers for drafts, orientation
context, and diff sizing live in `src/monitor/lib/built_ins_wiki_utils.py`.

Common entry points include:
- `wiki_init`
- `wiki_lint`
- `wiki_fix`

### `wiki_init`

`wiki_init` drafts a project-aware `INDEX.md` from repository context.
It can preview the draft or apply it to the project wiki.

### `wiki_lint`

`wiki_lint` checks the wiki for stale or inconsistent content.
It is meant to catch claims that no longer match the codebase or project state.

### `wiki_fix`

`wiki_fix` can generate or apply targeted fixes for wiki drift.
It is intended for repairing semantic mismatches, not for rewriting the wiki wholesale.

## Startup interaction

Monitor resolves project wiki paths during startup and freezes them for the session.
That means changing directories later in the session does not switch the wiki context.

The wiki also interacts with project prompt guidance:
- project instructions come from the startup-scoped prompt resolution path
- the wiki is a separate project knowledge layer
- both can influence the model, but they serve different purposes

A practical workflow is:
1. let `wiki_init` draft a starter index
2. edit `INDEX.md` into a durable guide
3. link a small number of stable topic pages from the index
4. use `wiki_lint` and `wiki_fix` when the wiki starts drifting from the codebase

## Good practices

A useful wiki should be:
- concise
- durable
- written for future maintainers
- focused on facts that are expensive to rediscover

Good candidates include:
- repo-specific architecture notes
- ownership boundaries
- conventions that are not obvious from code alone
- common failure modes
- links to related project docs

## Common pitfalls

Avoid using the wiki for:
- transient task notes
- duplicated code comments
- design ideas that are still unsettled
- content that belongs in a changelog or issue tracker

If a claim changes frequently, it probably does not belong in the wiki.

## Related code

- `src/monitor/lib/monitor_wiki.py`
- `src/monitor/lib/built_in_commands.py` (`wiki_init_command`, `wiki_lint_command`, `wiki_fix_command`)
- `src/monitor/core/built_ins.py` (registration)
- `src/monitor/lib/built_ins_wiki_utils.py` (helpers)
- `src/monitor/lib/system_prompt.py`
- `src/monitor/app.py`
