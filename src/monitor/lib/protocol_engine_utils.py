"""
Utilities and constants for the protocol engine.
"""
import re

# Prohibited summary phrases (case-insensitive)
PROHIBITED_SUMMARY_MARKERS = [
    'file is unchanged', 'script is unchanged', 'remains the same', 'no change', 'no changes', 'no modification',
    'unmodified', 'identical', 'rest of the file is unchanged', 'everything else is unchanged',
    'nothing was changed', 'not modified', 'unchanged', 'nothing changed', 'has not changed',
    'output is the same', 'no update', 'unchanged from previous', 'no adjustment',
    '# unchanged', '// unchanged', '<!-- unchanged -->', '# (rest of the file is unchanged)',
    '// (rest of the file is unchanged)',
]

PROHIBITED_SUMMARY_PATTERN = re.compile(
    r'(' + r'|'.join([re.escape(marker) for marker in PROHIBITED_SUMMARY_MARKERS]) + r')',
    re.IGNORECASE
)

def create_chunk_correction_prompt(chunk_index: int, non_compliant_chunk: str, original_source: str) -> str:
    """
    Create a prompt for requesting LLM to correct a non-compliant chunk.
    
    Args:
        chunk_index: The index of the chunk that needs correction
        non_compliant_chunk: The previously returned non-compliant chunk content
        original_source: The full original source code for reference
        
    Returns:
        Formatted prompt string for chunk correction
    """
    prompt = (
        f"You previously returned a non-compliant chunk (index {chunk_index}) "
        f"that omits lines or uses forbidden summary language such as 'unchanged'.\n"
        f"Below is your previous, non-compliant chunk:\n"
        f"-----\n{non_compliant_chunk}\n-----\n"
        f"Here is the full original source code for the file:\n"
        f"-----\n{original_source}\n-----\n"
        f"Now, re-create chunk {chunk_index}. Include **every line**, with no omissions or summary phrases. "
        f"Do not use any forbidden phrases like 'unchanged', 'rest of the file is unchanged', etc. "
        f"Output the chunk using the <chunk_{chunk_index}></chunk_{chunk_index}> format. "
        f"Wait for 'Next chunk' before continuing. Never omit code."
    )
    return prompt

def create_initial_modification_query(
    script_content: str,
    modification_request: str,
    start_chunk_index: int,
    expected_total_chunks: int,
    lo: int,
    hi: int,
    lines_per_chunk: int,
    chars_per_chunk: int,
    last_directive: str
) -> str:
    """
    Create the initial modification query for starting a code modification cycle.
    
    Args:
        script_content: The original source code content
        modification_request: The modification task description
        start_chunk_index: Index of the first chunk to generate
        expected_total_chunks: Total number of expected chunks
        lo: Starting line number for this chunk
        hi: Ending line number for this chunk
        lines_per_chunk: Maximum lines allowed per chunk
        chars_per_chunk: Maximum characters allowed per chunk
        last_directive: The last="true" directive if this is the final chunk
        
    Returns:
        Formatted initial modification query string
    """
    query = (
        f"Here is the current source file:\n\n{script_content}\n\n"
        f"Task: Modify it to {modification_request}.\n\n"
        f"Output ONLY chunk {start_chunk_index} of {expected_total_chunks} now.\n"
        f"Do NOT include any other chunks. Do NOT mark last=\"true\" unless this is "
        f"chunk {expected_total_chunks}.\n"
        f"Chunk {start_chunk_index} should be approximately lines {lo}..{hi} of the final modified file, "
        f"but you MUST include every line of code that belongs to this chunk (no omissions, no summaries). "
        f"Respect these limits:\n"
        f"- Max lines per chunk: {lines_per_chunk}\n"
        f"- Max characters per chunk: {chars_per_chunk}\n\n"
        f"Format: <chunk_{start_chunk_index}{last_directive}>"
        f"<pure code only, no commentary>"
        f"</chunk_{start_chunk_index}>\n"
        f"Do not output anything else."
        f"REMINDER: Output every single line literally. Do not use 'unchanged' or summary phrases."
    )
    return query

def create_compliance_warning(retries: int, max_retries: int, chunk_index: int) -> str:
    """
    Create a compliance warning message for retry attempts.
    
    Args:
        retries: Current retry attempt number (0-based)
        max_retries: Maximum number of retries allowed
        chunk_index: The index of the chunk being processed
        
    Returns:
        Formatted compliance warning string
    """
    warning = (
        "\nIMPORTANT: You included summary comments or phrases that are strictly prohibited (e.g., 'unchanged', 'remains the same', 'no change', 'rest of the file is unchanged', etc). THIS IS NOT ALLOWED. Remove any such statements entirely. "
        "Return only the pure, raw source code fully split into explicit chunk tags as instructed, with NO summary markers, "
        "NO omitted code, NO comments or lines mentioning unmodified or unchanged code.\n"
        f"This is retry attempt {retries+1} of {max_retries} for chunk {chunk_index}. Strict compliance required."
    )
    return warning

def create_resume_chunk_prompt(start_chunk_index: int) -> str:
    """
    Create a prompt for resuming chunk collection from a specific index.
    
    Args:
        start_chunk_index: The chunk index to resume from
        
    Returns:
        Formatted resume chunk prompt string
    """
    prompt = (
        f"Continue from chunk {start_chunk_index}. IMPORTANT: Mark the last chunk with <chunk_n last=\"true\">. "
        "UNDER NO CIRCUMSTANCES may you output summary comments (such as 'unchanged', 'remains the same', 'no change', etc.), "
        "nor omit *any* lines from the file. Output every line, with no summary phrases."
    )
    return prompt

def create_next_chunk_prompt(
    next_index: int,
    expected_total_chunks: int,
    lo: int,
    hi: int,
    lines_per_chunk: int,
    chars_per_chunk: int,
    is_last: bool
) -> str:
    """
    Create a prompt for requesting the next chunk in sequence.
    
    Args:
        next_index: The index of the next chunk to request
        expected_total_chunks: Total number of expected chunks
        lo: Starting line number for this chunk
        hi: Ending line number for this chunk
        lines_per_chunk: Maximum lines allowed per chunk
        chars_per_chunk: Maximum characters allowed per chunk
        is_last: Whether this is the last chunk
        
    Returns:
        Formatted next chunk prompt string
    """
    directive_reminder = 'Mark last="true".' if is_last else 'Do NOT mark last="true".'
    last_directive = ' last="true"' if is_last else ''
    
    prompt = (
        f"Output ONLY chunk {next_index} of {expected_total_chunks} now.\n"
        f"Do NOT include any other chunks. {directive_reminder}\n"
        f"Chunk {next_index} should be approximately lines {lo}..{hi} of the final modified file.\n"
        f"Limits:\n"
        f"- Max lines per chunk: {lines_per_chunk}\n"
        f"- Max characters per chunk: {chars_per_chunk}\n\n"
        f"Format: <chunk_{next_index}{last_directive}>"
        f"<pure code only, no commentary>"
        f"</chunk_{next_index}>"
    )
    return prompt

def create_system_prompt(max_lines_per_chunk: int, max_chars_per_chunk: int, token_budget_per_chunk: int) -> str:
    """
    Create the system prompt for the protocol engine.
    
    Args:
        max_lines_per_chunk: Maximum lines allowed per chunk
        max_chars_per_chunk: Maximum characters allowed per chunk
        token_budget_per_chunk: Token budget per chunk for the model
        
    Returns:
        Formatted system prompt string
    """
    system_prompt = f"""
    You are an expert software engineer specializing in safe, in-place, large-scale source code modification.

    Mission:
    Update source files according to user instructions for high-stakes, auditable, and traceable software environments.

    MANDATORY OUTPUT RULES

    1) Chunked Output (one chunk per response)
       - ALWAYS divide your output into sequential code chunks, strictly one chunk per response.
       - Enclose the chunk in tags: <chunk_K> ... </chunk_K>, where K is the exact chunk index requested.
       - Only mark the final chunk with last="true": <chunk_K last="true"> ... </chunk_K>.
       - NEVER send more than one chunk per response.
       - Respect hard limits per chunk:
         • ≤ {max_lines_per_chunk} lines
         • ≤ {max_chars_per_chunk} characters
         • ≤ ~{token_budget_per_chunk} tokens (do not exceed this response size)
       - End chunks at logical boundaries (functions/classes) when possible. If the next line would exceed a limit, STOP and continue in the next chunk—no omissions.
       - Tag syntax (strict)
          - Opening tag (non-final): <chunk_K>
          - Opening tag (final only): <chunk_K last="true">
          - Closing tag (always): </chunk_K>
          - Here, `K` is a 1-based integer chunk index: 1, 2, 3, …  
          - Do not output the literal letter `K`. Always substitute the actual index with no leading zeros (e.g., `<chunk_1>`, `<chunk_2>`, not `<chunk_01>`).
          - Closing tags MUST NOT include attributes. Only the opening tag may include last="true".
          - If last="true" is present, it MUST be preceded by a single space after the tag name (i.e., <chunk_1 last="true">). Do not concatenate attributes to the tag name.
       - Exactly one chunk per response
          - Output ONLY the requested <chunk_K> … </chunk_K>.
          - No code fences, no commentary, no additional chunks or text outside the tags.
       - Final-chunk rule
          - Only set last="true" on the opening tag of the final chunk of the entire file.
          - Never set last="true" on non-final chunks.
          - Closing tag MUST be </chunk_K> even for the final chunk.

    2) No Summary or Omission
       - Output EVERY line of the final modified file, in order (changed and unchanged).
       - NEVER use summary/omission phrases like "unchanged", "rest of the file is unchanged", "no change", etc.
       - Do not omit imports, helpers, or any code. No placeholders.

    3) No Markdown or Output Outside Tags
       - Output PURE code ONLY inside the chunk tags.
       - No markdown fences (e.g., ```), no commentary, no prose outside tags.

    4) Order & Integrity
       - Preserve the original order of imports, functions, classes, and code blocks unless the user explicitly requests reordering.
       - Do not duplicate code, invent dependencies, or remove comments unless strictly necessary to satisfy the modification.

    5) Compliance & Retry Behavior
       - If the system indicates non-compliance (e.g., wrong chunk index, missing/extra chunk tags, early last="true", chunk too large, summary phrases), immediately resend the corrected chunk.
       - Do NOT repeat the same mistake. Follow the specific correction hint precisely.

    6) Responsiveness & Sequencing
       - After outputting a chunk, WAIT for "Next chunk" or an explicit "chunk K" request before sending the next one.
       - When asked for chunk K, output ONLY <chunk_K> ... </chunk_K> and nothing else. Do NOT include any other <chunk_*> tags.
       - Only set last="true" when you are outputting the final chunk of the entire file.

    Example allowed/forbidden forms:
      - Good:
        - <chunk_1> … </chunk_1>
        - <chunk_1 last="true"> … </chunk_1>
      - Bad (do not output):
        - <chunk_1last="true"> … </chunk_1>  ← missing space before attribute
        - </chunk_1last="true">              ← attributes on closing tag are forbidden
        - <chunk_1 last="true"> … </chunk_1 last="true"> ← attribute on closing tag
        - <chunk_01> … </chunk_1>            ← mismatched index
        - <chunk_1> … </chunk_2>             ← mismatched index
        - A response that has <chunk_K> … </chunk_K> and also additional text before or after those tags

    Further Notes:
    - If the modification request is ambiguous or risky, favor safety and preserve original intent.
    - Keep comments unless they conflict with the instructions.
    - Never omit code due to brevity. If limits are reached mid-section, stop at a safe boundary and continue in the next chunk.
    Begin by producing ONLY the first requested chunk according to these rules.

    CRITICAL FINAL REMINDERS:
    - You MUST output every single line of code, character by character
    - NEVER EVER use phrases like: "unchanged", "remains the same", "no change", "rest of file unchanged"
    - If a line doesn't need modification, output it EXACTLY as it appears in the original
    - Think: "Copy every line literally" not "summarize unchanged sections"
    - The system will REJECT your response if you use ANY summary language
    - When in doubt: OUTPUT THE ACTUAL CODE, never describe it

    Remember: Your job is to be a precise code printer, not a helpful summarizer.
    """
    return system_prompt