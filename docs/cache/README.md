# Docs Cache

This directory stores working documentation artifacts used during design,
implementation, validation, and follow-up work.

## Purpose
- Capture in-progress thinking that is useful to developers but not yet ready
  for the main documentation set.
- Preserve planning, verification, and architectural notes that support code
  changes.
- Separate temporary or task-specific working docs from stable user-facing or
  long-term reference docs in `docs/`.
- Provide a place for implementation context that may later be summarized or
  distilled into primary documentation.

## Naming conventions
Use uppercase prefixes to signal document intent and expected lifecycle:
- `PLAN_*`: implementation approach, sequencing, and execution strategy.
- `CHECKLIST_*`: task tracking, verification items, and completion criteria.
- `ROADMAP_*`: phased work, milestones, or longer-horizon rollout guidance.
- `SPEC_*`: behavior definitions, contracts, or more formal design notes.

Files without one of these prefixes should still have descriptive names and
should exist only when they provide clear supporting value, such as shared
architecture notes or coding conventions.

## Relationship to main docs
Documents in `docs/cache/` are working artifacts. When their contents become
stable, broadly useful, or user-relevant, the important conclusions should be
summarized in the primary documentation under `docs/`.

## Maintenance guidance
- Keep cached docs concise, focused, and easy to scan.
- Prefer updating an existing cached document over creating a near-duplicate.
- Remove, archive, or consolidate stale working docs when they no longer add
  value.
- Keep filenames consistent with the conventions above so the directory remains
  easy to navigate.
