"""Shared tool-description text constants."""

MODIFY_SOURCE_CODE_DESCRIPTION = (
    "Write one file from a natural-language change request. Use this fallback only when exact text-edit "
    "tools do not fit. It writes files and makes an extra model call. Do not use it for unique replacements, "
    "line-based inserts, new-file creation, or mechanical multi-file edits; use text_file_str_replace_in_file, "
    "text_file_insert_text_at_line, text_file_create, or bulk_replace_in_files instead. Inspect first when the "
    "exact target text or file context is not already known. If the request itself says to create a file that "
    "already exists, it leaves the file unchanged. After any write, inspect the diff before claiming success."
)
