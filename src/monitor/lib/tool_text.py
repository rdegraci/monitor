"""Shared tool-description text constants."""

MODIFY_SOURCE_CODE_DESCRIPTION = (
    "Edit a source file via a natural-language modification_request. **Fallback tool.** "
    "Use ONLY when the change genuinely can't be expressed as exact text edits — e.g. fuzzy "
    "intent like 'make this idiomatic', or sweeping refactors across many sites in one pass. "
    "Inspect first when the exact target text or file context is not already known. For precise edits, "
    "PREFER the narrowest deterministic tool that fits: text_file_str_replace_in_file for a unique "
    "replacement, text_file_insert_text_at_line for a precise insertion, text_file_create for a new file, "
    "and bulk_replace_in_files for mechanical repeated edits. These tools are deterministic, faster, "
    "reviewable, and don't invoke a second LLM. If the file exists at source_file, it is modified in place; "
    "if it does not exist, it is created. Edge case: if your modification_request itself asks to *create* a "
    "file at a path that already exists, no change is made and the existing file is preserved. After any "
    "write, inspect the diff before claiming success and run language-specific checks only when clearly "
    "applicable."
)
