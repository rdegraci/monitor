# PLAN_ADVANCED_TOOLS

## Goal
Document a higher-quality tool stack for code editing tasks so the agent can understand repository structure, trace impact, and choose better fix locations before editing.

## Problem statement
The current workflow relies heavily on text search and direct file inspection. That is enough for many tasks, but it can encourage local fixes that miss the broader architecture.

## Desired outcome
Add a small set of tools that help the agent:
- understand repository structure before editing
- trace symbols and references across files
- estimate the impact of a change before applying it
- select targeted validation tests
- keep repo-specific guidance separate from the base system prompt

## Proposed tools

### 1. Repo map / architecture summary
A tool that produces a compact overview of the repository:
- top-level modules
- important layers
- key entry points
- major data flow paths

Why it matters:
- helps the agent orient itself before searching
- reduces the chance of changing the wrong layer
- makes context gathering less ad hoc

### 2. Reference tracing
A tool that follows a symbol or concept across callers, implementers, and consumers.

Why it matters:
- exposes architectural dependencies
- helps distinguish the source of behavior from the visible symptom
- supports deeper, more durable fixes

### 3. Change-impact summary
A tool that estimates what files, tests, and code paths are likely affected by a proposed change.

Why it matters:
- reduces accidental breakage
- improves tradeoff decisions
- guides targeted validation

### 4. Scoped test selection
A tool that picks the most relevant tests based on touched modules and affected paths.

Why it matters:
- keeps validation focused
- speeds feedback
- encourages better test coverage for the change at hand

### 5. Instruction loader with task routing
A tool or mechanism that loads repo-level instructions only when they are relevant to the current task.

Why it matters:
- keeps the base system prompt small
- avoids prompt bloat
- makes code-task guidance available without forcing it onto all requests

### 6. AST-aware navigation
A structure-aware lookup mechanism for symbols, definitions, imports, and references.

Why it matters:
- works better than raw text search for code understanding
- catches indirect relationships
- scales better in larger repositories

### 7. Lightweight plan-before-edit step
A planning step that asks the agent to inspect, summarize, and choose an approach before changing files.

Why it matters:
- discourages the first-hit patch
- makes the model state its assumptions
- improves edit quality when tasks are ambiguous

## In-memory persistence and refresh behavior
Advanced tools can keep working state in Python objects for the duration of a session, which makes repeated lookups and summaries faster without persisting extra data to disk.

To keep that state useful and safe:
- only compact summaries should be sent to the LLM
- detailed caches can stay in memory inside the tool layer
- cached data should be refreshed when files change
- refresh triggers can include mtimes, content hashes, file watchers, or diff-based invalidation

Why it matters:
- keeps tool responses fast during interactive use
- avoids sending bulky internal state into the prompt
- reduces stale results after edits or external file updates
- lets the tool layer manage freshness without increasing prompt size

### Deterministic summary behavior
Tool-layer summaries should be deterministic by default. The same input state should produce the same summary output, which makes testing and caching easier. LLM-based rewriting should remain optional and secondary, used only when a more flexible presentation is explicitly needed.

## Implementation strategy
Start with the highest-value, lowest-complexity capabilities:
1. instruction loader with task routing
2. scoped test selection
3. lightweight plan-before-edit
4. repo map / architecture summary
5. reference tracing
6. change-impact summary
7. AST-aware navigation

## Constraints
- Keep tools fast enough for interactive use.
- Prefer compact, high-signal output.
- Avoid duplicating capabilities already covered by existing search and file-reading tools.
- Keep the prompt-loading design separate from model behavior where possible.

## Success criteria
- The agent needs fewer exploratory file reads to understand a task.
- The agent makes fewer local-but-short-sighted fixes.
- The agent can validate changes with more relevant tests.
- Repo-specific instructions remain separate from the base prompt unless intentionally combined.
