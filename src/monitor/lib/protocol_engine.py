import logging
import litellm
import re
import json
import time
import os
import hashlib

from colored import fg, attr
from pygments import highlight
from pygments.lexers import BashLexer, MarkdownLexer, DiffLexer
from pygments.formatters import TerminalFormatter

from monitor import config 
from monitor.lib.progress import progress_dots
from monitor.lib.sound import ring_bell

logger = logging.getLogger(__name__)

blue = fg('blue')
red = fg('red')
yellow = fg('yellow')
reset = attr('reset')

MESSAGE_HISTORY = []

def configure_protocol_engine_message_history(message_history: list):
    global MESSAGE_HISTORY
    logger.debug("Configuring message history, count: %d", len(message_history) if message_history else 0)
    MESSAGE_HISTORY.clear()
    if message_history:
        MESSAGE_HISTORY.extend(message_history)

class ProtocolEngine:
    """ProtocolEngine with global modification cycle retry logic."""
    # Prohibited summary phrases (case-insensitive)
    PROHIBITED_SUMMARY_MARKERS = [
        'file is unchanged', 'script is unchanged', 'remains the same', 'no change', 'no changes', 'no modification',
        'unmodified', 'identical', 'as-is', 'rest of the file is unchanged', 'everything else is unchanged',
        'nothing was changed', 'not modified', 'unchanged', 'nothing changed', 'has not changed',
        'output is the same', 'no update', 'unchanged from previous', 'no adjustment',
        '# unchanged', '// unchanged', '<!-- unchanged -->', '# (rest of the file is unchanged)',
        '// (rest of the file is unchanged)',
    ]
    PROHIBITED_SUMMARY_PATTERN = re.compile(
        r'(' + r'|'.join([re.escape(marker) for marker in PROHIBITED_SUMMARY_MARKERS]) + r')',
        re.IGNORECASE
    )
    MAX_RETRIES_PER_CHUNK = 3
    MAX_GLOBAL_MODIFICATION_RETRIES = 2

    def __init__(self, model, system_prompt, middleware=litellm, initial_message_history=None):
        logger.debug("Initializing ProtocolEngine with model: %s", model)
        self.model = model
        self.system_prompt = system_prompt
        self.middleware = middleware
        self.chunks = []
        self.source_file = None
        self.task_completed = False
        self.modification_request = ""
        self.message_history = [{"role": "system", "content": system_prompt}]
        self._modification_script_content = None
        self.global_retries = 0
        if initial_message_history is None:
            initial_message_history = MESSAGE_HISTORY
        if initial_message_history:
            if not isinstance(initial_message_history, list):
                logger.error("initial_message_history must be a list, got: %s", type(initial_message_history))
                raise ValueError("initial_message_history must be a list of message dictionaries")
            filtered_history = [msg for msg in initial_message_history if msg.get("role") != "system"]
            self.message_history.extend(filtered_history)
        logger.debug("ProtocolEngine initialized. Message history length: %d", len(self.message_history))

        self.expected_total_chunks = None
        self.lines_per_chunk = MAX_LINES_PER_CHUNK
        self.chars_per_chunk = MAX_CHARS_PER_CHUNK

    def _make_chunk_plan(self, script_content: str):
        lines = script_content.splitlines()
        total_lines = len(lines)
        # Simple plan: equally sized line buckets
        expected = max(1, (total_lines + self.lines_per_chunk - 1) // self.lines_per_chunk)
        
        plan = {
            "total_lines": total_lines,
            "expected_chunks": expected,
            "line_ranges": [
                (i*self.lines_per_chunk + 1, min((i+1)*self.lines_per_chunk, total_lines))
                for i in range(expected)
            ],
        }
        
        logger.info(f"Created chunk plan: {total_lines} lines, {expected} expected chunks")
        logger.info(f"Line ranges: {plan['line_ranges']}")
        
        return plan

    def fetch_modified_script(self, script_content, modification_request, source_file):
        """
        Orchestrates source code modification with automatic retry after all chunk retries are exhausted.
        """
        self.modification_request = modification_request
        self.source_file = source_file
        self._modification_script_content = script_content
        logger.debug("fetch_modified_script called (global attempt: %d)", self.global_retries+1)
        attempt_successful = False
        error_result = None
        while self.global_retries < self.MAX_GLOBAL_MODIFICATION_RETRIES:
            result = self._modification_cycle(script_content, modification_request, source_file)
            if isinstance(result, str) and result.startswith("Non-compliant output at chunk"):
                self.global_retries += 1
                logger.warning(f"Full modification cycle failed (attempt {self.global_retries}/{self.MAX_GLOBAL_MODIFICATION_RETRIES}). Retrying from checkpoint...")
                checkpoint = self._load_checkpoint(modification_request)
                if not checkpoint:
                    logger.error("Checkpoint unavailable or broken. Cannot auto-retry further.")
                    error_result = result
                    break
                continue
            else:
                attempt_successful = True
                error_result = None
                break
        if attempt_successful:
            logger.info(f"Modification completed in {self.global_retries+1} cycles.")
            self.global_retries = 0
            return result
        else:
            logger.error(f"All modification retries exhausted ({self.MAX_GLOBAL_MODIFICATION_RETRIES}). Human intervention needed.")
            self.global_retries = 0
            return error_result or "Modification process failed after all automatic retries. Manual intervention required."

    def _request_chunk_correction(self, non_compliant_chunk, original_source, chunk_index):
        """
        Ask the LLM to rewrite a non-compliant chunk, given the full original source code as reference.
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
        return self._send_request(prompt)

    def _modification_cycle(self, script_content, modification_request, source_file):
        if self.task_completed:
            logger.warning("Task already completed for file: %s", source_file)
            return "Task already completed"
        # Determine language from file extension
        ext = os.path.splitext(source_file)[1][1:].lower()
        languages = {
            'py': 'Python',
            'swift': 'Swift',
            'js': 'JavaScript',
            'ts': 'TypeScript',
            'java': 'Java',
            'cpp': 'C++',
            'c': 'C',
            # Add more as needed
        }
        language = languages.get(ext, 'source')
        # Resume from checkpoint if possible:
        checkpoint = self._load_checkpoint(modification_request)
        if checkpoint:
            self.chunks = checkpoint["completed_chunks"]
            start_chunk_index = checkpoint["next_chunk_index"]
            logger.info(f"Resuming modification at chunk {start_chunk_index} for {source_file}")
        else:
            self.chunks = []
            start_chunk_index = 1

        plan = self._make_chunk_plan(script_content)
        self.expected_total_chunks = plan["expected_chunks"]
        line_ranges = plan["line_ranges"]
        self.line_ranges = line_ranges

        # Compose a strict chunk-1-only instruction
        start_chunk_index = 1 if not checkpoint else checkpoint["next_chunk_index"]
        is_last_expected = (start_chunk_index == self.expected_total_chunks)
        (lo, hi) = line_ranges[start_chunk_index - 1] if line_ranges else (1, None)

        last_directive = 'last="true"' if is_last_expected else ''
        initial_query = (
            f"Here is the current source file:\n\n{script_content}\n\n"
            f"Task: Modify it to {modification_request}.\n\n"
            f"Output ONLY chunk {start_chunk_index} of {self.expected_total_chunks} now.\n"
            f"Do NOT include any other chunks. Do NOT mark last=\"true\" unless this is "
            f"chunk {self.expected_total_chunks}.\n"
            f"Chunk {start_chunk_index} should be approximately lines {lo}..{hi} of the final modified file, "
            f"but you MUST include every line of code that belongs to this chunk (no omissions, no summaries). "
            f"Respect these limits:\n"
            f"- Max lines per chunk: {self.lines_per_chunk}\n"
            f"- Max characters per chunk: {self.chars_per_chunk}\n\n"
            f"Format: <chunk_{start_chunk_index}{last_directive}>"
            f"<pure code only, no commentary>"
            f"</chunk_{start_chunk_index}>\n"
            f"Do not output anything else."
            f"REMINDER: Output every single line literally. Do not use 'unchanged' or summary phrases."
        )
        
        logger.info(f"Starting modification cycle for {source_file}")
        logger.info(f"start_chunk_index={start_chunk_index}, is_last_expected={is_last_expected}, lines={lo}..{hi}")
        logger.info(f"Initial query length: {len(initial_query)} chars")

        if not self.chunks:
            logger.info("No existing chunks, requesting initial chunk")
            initial_response = self._send_request_with_compliance_retry(initial_query, chunk_index=1, is_next_chunk=False)
            logger.info(f"Received initial response: {len(initial_response) if initial_response else 0} chars")
            ret = self._collect_chunks(initial_response, modification_request, start_chunk_index=1)
        else:
            logger.info(f"Resuming from existing chunks ({len(self.chunks)} chunks already collected)")
            ret = self._collect_chunks(None, modification_request, start_chunk_index=start_chunk_index)

        if isinstance(ret, str) and ret.startswith("Non-compliant output at chunk"):
            return ret

        self.task_completed = True
        # Note: _collect_chunks already saves on success; calling _assemble_and_save() again is harmless but redundant.
        return self._assemble_and_save()

    def _send_request(self, query):
        logger.debug(f"_send_request with query length: {len(query)}")
        try:
            if query:
                self.message_history.append({"role": "user", "content": query})
            with progress_dots("Analysis."):
                response = self.middleware.completion(
                    model=self.model,
                    messages=self.message_history,
                    max_completion_tokens=TOKEN_BUDGET_PER_CHUNK,
                    drop_params=True
                )
            content = response.choices[0].message['content']
            self.message_history.append({"role": "assistant", "content": content})
            return content
        except Exception as e:
            logger.debug("Middleware completion error: %s", str(e))
            raise Exception("LLM call failed. Check logs for details.")

    def _send_request_with_compliance_retry(self, query, chunk_index, is_next_chunk: bool):
        retries = 0
        output = None
        last_noncompliant_output = None
        prohibited = set()
        while retries < self.MAX_RETRIES_PER_CHUNK:
            augmented_query = query
            if retries > 0:
                compliance_warn = (
                    "\nIMPORTANT: You included summary comments or phrases that are strictly prohibited (e.g., 'unchanged', 'remains the same', 'no change', 'rest of the file is unchanged', etc). THIS IS NOT ALLOWED. Remove any such statements entirely. "
                    "Return only the pure, raw source code fully split into explicit chunk tags as instructed, with NO summary markers, "
                    "NO omitted code, NO comments or lines mentioning unmodified or unchanged code.\n"
                    f"This is retry attempt {retries+1} of {self.MAX_RETRIES_PER_CHUNK} for chunk {chunk_index}. Strict compliance required."
                )
                augmented_query = f"{query}\n\n{compliance_warn}"
            try:
                logger.debug(f"Requesting chunk {chunk_index}, retry {retries+1}")
                output = self._send_request(augmented_query)
            except Exception as e:
                logger.debug("LLM call failed for chunk %s, retry %s: %s", chunk_index, retries + 1, str(e))
                raise Exception(f"LLM call failed for chunk {chunk_index}, retry {retries+1}: {str(e)}")
            prohibited = self._find_prohibited_phrases_in_text(output)
            if prohibited:
                retries += 1
                time.sleep(2 ** retries)
                last_noncompliant_output = output
                logger.warning(f"Non-compliant output for chunk {chunk_index}, retry {retries} of {self.MAX_RETRIES_PER_CHUNK}. Markers: {list(prohibited) if prohibited else '-'} {last_noncompliant_output}")
                continue
            return output
        # If retries exhausted, attempt LLM correction using the full original source
        logger.warning(f"All compliance retries failed for chunk {chunk_index}; retrying correction with full original source.")
        if last_noncompliant_output:
            corrected_chunk = self._request_chunk_correction(
                non_compliant_chunk=last_noncompliant_output,
                original_source=self._modification_script_content,
                chunk_index=chunk_index,
            )
            prohibited = self._find_prohibited_phrases_in_text(corrected_chunk) if corrected_chunk else set()
            if corrected_chunk and not prohibited:
                return corrected_chunk
        logger.warning(f"Non-compliant output for chunk {chunk_index}, retry {retries} of {self.MAX_RETRIES_PER_CHUNK}. Markers: {list(prohibited) if prohibited else '-'}")
        self._assemble_and_save_partial()
        raise ValueError(f"Non-compliant output at chunk {chunk_index} after all retries")

    def _has_prohibited_summary_marker(self, text):
        return bool(self.PROHIBITED_SUMMARY_PATTERN.search(text)) if text else False

    # Helper: remove string literals so matches inside strings are not found.
    def _remove_string_literals(self, text: str) -> str:
        """
        Replace string literal contents with spaces to avoid matching inside strings.
        Handles:
          - triple-quoted Python strings ('''...''' or \"\"\"...\"\")
          - single- and double-quoted strings with escapes
          - JS/TS template literals with backticks (`)
        """
        if not text:
            return text
        string_re = re.compile(
            r"('''.*?'''|\"\"\".*?\"\"\"|"
            r"'(?:\\.|[^'\\])*'|"
            r"\"(?:\\.|[^\"\\])*\"|"
            r"`(?:\\.|[^`\\])*`)",
            re.DOTALL
        )
        # Replace matched string with spaces of the same length (keeps positions/line numbers stable)
        return string_re.sub(lambda m: " " * len(m.group(0)), text)

    # Helper: extract comment spans from the code (single-line and block comments)
    def _extract_comments_without_strings(self, text: str):
        """
        Return a list of comment strings found in text (after strings have been removed).
        Supports:
          - Hash comments (Python, shell): # ... (to end of line)
          - C/JS single line: // ...
          - C-style block: /* ... */
          - HTML comments: <!-- ... -->
        """
        comments = []
        if not text:
            return comments

        # Single-line comment patterns (multiline flag)
        comments.extend(re.findall(r'(?m)#.*$', text))    # # comment (python/shell)
        comments.extend(re.findall(r'(?m)//.*$', text))   # // comment (C/JS/Java)

        # Block comments
        comments.extend(re.findall(r'/\*[\s\S]*?\*/', text))      # /* ... */
        comments.extend(re.findall(r'<!--[\s\S]*?-->', text))    # <!-- ... -->

        return comments

    # Replacement implementation: only detect markers appearing inside comments
    def _find_prohibited_phrases_in_text(self, text: str):
        """
        Find prohibited summary markers only when they occur inside comments.
        Returns a set of matched markers (lowercased).
        """
        if not text:
            return set()

        # Step 1: remove string literals so markers inside strings won't match
        code_no_strings = self._remove_string_literals(text)

        # Step 2: extract comments from the stringless code
        comments = self._extract_comments_without_strings(code_no_strings)
        if not comments:
            return set()

        matches = set()
        for comment in comments:
            # Normalize comment by stripping common leading/trailing comment delimiters
            # Remove leading comment intro (e.g. '#', '//', '///', '/*', '<!--') and trailing end markers.
            # We intentionally keep internal punctuation and words intact.
            norm = re.sub(r'^\s*(?:#{1,}|//+|/\*+|<!--)\s*', '', comment)   # leading markers
            norm = re.sub(r'\s*(?:\*/|-->)\s*$', '', norm)                  # trailing block markers

            # Now search only the comment text using the existing compiled pattern
            for m in self.PROHIBITED_SUMMARY_PATTERN.finditer(norm):
                matches.add(m.group(0).lower())

        return matches

    def _validate_and_extract_chunk(self, response: str, expected_index: int, is_last_expected: bool):
        logger.info(f"_validate_and_extract_chunk: expected_index={expected_index}, is_last_expected={is_last_expected}")
        logger.info(f"Response length: {len(response) if response else 0} chars")
        
        if not response or not isinstance(response, str):
            logger.info("Invalid response type - response is None or not string")
            raise ValueError("Invalid response type")

        # Log first 200 chars of response for debugging
        logger.info(f"Response preview: {response[:200]}{'...' if len(response) > 200 else ''}")

        # Must have a matching chunk tag
        pattern = re.compile(
            rf'<chunk_{expected_index}(?:\s+last="true")?>(.*?)</chunk_{expected_index}(?:\s+last="true")?>',
            re.DOTALL
        )
        m = pattern.search(response)
        if not m:
            # If it tries any other index or no tags at all, reject
            if "<chunk_" not in response:
                logger.info(f"No chunk tags found in response for chunk {expected_index}")
                raise ValueError(f"Missing chunk tags for chunk {expected_index}")
            else:
                logger.info(f"Wrong chunk index found. Expected <chunk_{expected_index}> only.")
                # Log what chunk tags we actually found
                chunk_matches = re.findall(r'<chunk_(\d+)(?:\s+last="true")?>', response)
                logger.info(f"Found chunk tags: {chunk_matches}")
                raise ValueError(f"Wrong chunk index. Expected <chunk_{expected_index}> only.")

        tag_text = m.group(0)
        content = m.group(1)
        has_last = 'last="true"' in tag_text
        
        logger.info(f"Extracted chunk {expected_index}: {len(content)} chars, {len(content.splitlines())} lines")
        logger.info(f"Has last flag: {has_last}")

        # Early/late last flag
        if has_last and not is_last_expected:
            logger.info(f"Received unexpected last=\"true\" for chunk {expected_index} (expected at chunk {self.expected_total_chunks})")
            raise ValueError(f"Received last=\"true\" before final chunk (expected at chunk {self.expected_total_chunks}).")

        # Size constraints
        line_count = len(content.splitlines())
        char_count = len(content)
        logger.info(f"Chunk {expected_index} size check: {line_count}/{self.lines_per_chunk} lines, {char_count}/{self.chars_per_chunk} chars")
        
        if line_count > self.lines_per_chunk or char_count > self.chars_per_chunk:
            logger.info(f"Chunk {expected_index} exceeds size limits")
            raise ValueError(
                f"Chunk {expected_index} too large: {line_count} lines, {char_count} chars. "
                f"Limits: {self.lines_per_chunk} lines, {self.chars_per_chunk} chars."
            )

        # Forbidden summary markers (you already have this check; keep it)
        prohibited_phrases = self._find_prohibited_phrases_in_text(content)
        if prohibited_phrases:
            logger.info(f"Prohibited summary markers found in chunk {expected_index}: {list(prohibited_phrases)}")
            raise ValueError("Prohibited summary language detected in chunk content.")

        logger.info(f"Chunk {expected_index} validation successful")
        return content, has_last

    def _collect_chunks(self, initial_response=None, modification_request=None, start_chunk_index=1, print_func=print):
        logger.info(f"_collect_chunks starting: initial_response={'provided' if initial_response else 'None'}, start_chunk_index={start_chunk_index}")
        logger.info(f"Expected total chunks: {self.expected_total_chunks}, current chunks collected: {len(self.chunks)}")
        
        print_func("\nProcessing", end="", flush=True)
        line_ranges = getattr(self, "line_ranges", None)
        found_last_chunk = False
        iteration = 0
        max_iterations = 50  # Increased for larger files
        
        if initial_response is None:
            logger.info(f"No initial response provided, requesting chunk {start_chunk_index}")
            # For resume: Request the next chunk with specific index
            next_chunk_prompt = (
                f"Continue from chunk {start_chunk_index}. IMPORTANT: Mark the last chunk with <chunk_n last=\"true\">. "
                "UNDER NO CIRCUMSTANCES may you output summary comments (such as 'unchanged', 'remains the same', 'no change', etc.), "
                "nor omit *any* lines from the file. Output every line, with no summary phrases."
            )
            current_response = self._send_request_with_compliance_retry(next_chunk_prompt, chunk_index=start_chunk_index, is_next_chunk=True)
            logger.info(f"Received response for chunk {start_chunk_index}: {len(current_response) if current_response else 0} chars")
        else:
            logger.info(f"Using provided initial response: {len(initial_response)} chars")
            current_response = initial_response
        while not found_last_chunk and iteration < max_iterations:
            iteration += 1
            logger.info(f"_collect_chunks iteration {iteration}: processing chunk, found_last_chunk={found_last_chunk}")
            print_func(".", end="", flush=True)
            
            if current_response:
                expected_index = start_chunk_index if (iteration == 1 and initial_response is not None) else (len(self.chunks) + 1)
                is_last_expected = (expected_index == self.expected_total_chunks)
                logger.info(f"Processing current response for expected chunk {expected_index} (is_last_expected: {is_last_expected})")
                
                try:
                    expected_index = start_chunk_index if (iteration == 1 and initial_response is not None) else (len(self.chunks) + 1)
                    is_last_expected = (expected_index == self.expected_total_chunks)

                    new_chunk, is_last_chunk = self._validate_and_extract_chunk(
                        response=current_response,
                        expected_index=expected_index,
                        is_last_expected=is_last_expected
                    )
                    logger.info(f"Successfully extracted chunk {expected_index}, is_last_chunk={is_last_chunk}")
                except ValueError as e:
                    logger.error(f"Chunk validation failed: {e}")
                    # Treat as non-compliant and stop with a partial save
                    self._assemble_and_save_partial()
                    return f"Non-compliant output at chunk {expected_index}. Partial results saved."

                self.chunks.append(new_chunk)
                logger.info(f"Added chunk {expected_index} to collection. Total chunks now: {len(self.chunks)}")
                
                if modification_request:
                    self._save_checkpoint(self.chunks, len(self.chunks) + 1, modification_request)
                    logger.info(f"Saved checkpoint after chunk {expected_index}")

                if is_last_chunk:
                    found_last_chunk = True
                    logger.info(f"Found last chunk! Finalizing modification with {len(self.chunks)} total chunks")
                    self._assemble_and_save()
                    self._remove_checkpoint()
                    logger.info(f"\nModification complete. Updated {self.source_file}.")
                    return
            else:
                logger.warning("current_response is None or empty - this shouldn't happen")
            
            if not found_last_chunk:
                logger.info(f"Need more chunks. Requesting next chunk {len(self.chunks) + 1} of {self.expected_total_chunks}")
                try:
                    next_index = len(self.chunks) + 1
                    is_last = (next_index == self.expected_total_chunks)
                    (lo, hi) = line_ranges[next_index - 1] if line_ranges else (None, None)
                    
                    logger.info(f"Requesting chunk {next_index}, is_last={is_last}, lines {lo}..{hi}")

                    directive_reminder = 'Mark last="true".' if is_last else 'Do NOT mark last="true".'
                    last_directive = ' last="true"' if is_last else ''
                    next_chunk_prompt = (
                        f"Output ONLY chunk {next_index} of {self.expected_total_chunks} now.\n"
                        f"Do NOT include any other chunks. {directive_reminder}\n"
                        f"Chunk {next_index} should be approximately lines {lo}..{hi} of the final modified file.\n"
                        f"Limits:\n"
                        f"- Max lines per chunk: {self.lines_per_chunk}\n"
                        f"- Max characters per chunk: {self.chars_per_chunk}\n\n"
                        f"Format: <chunk_{next_index}{last_directive}>"
                        f"<pure code only, no commentary>"
                        f"</chunk_{next_index}>"
                    )
                    current_response = self._send_request_with_compliance_retry(
                        next_chunk_prompt, chunk_index=next_index, is_next_chunk=True
                    )
                    logger.info(f"Received response for chunk {next_index}: {len(current_response) if current_response else 0} chars")
                except ValueError as e:
                    if "Non-compliant output at chunk" in str(e):
                        logger.error(f"Non-compliance error: {str(e)}")
                        self._assemble_and_save_partial()
                        return f"Non-compliant output at chunk {len(self.chunks)+1}. Partial results saved."
                    else:
                        logger.error(f"Error in chunk processing: {str(e)}")
                        if self.chunks:
                            self._assemble_and_save_partial()
                        logger.info(f"Code modification completed with partial results.")
                        break
                except Exception as e:
                    logger.debug("Error requesting next chunk: %s", str(e))
                    if self.chunks:
                        self._assemble_and_save_partial()
                    logger.info(f"Code modification completed with partial results.")
                    break
        if iteration >= max_iterations and self.chunks:
            logger.info(f"\nReached max iterations ({max_iterations}). Using collected chunks.")
            self._assemble_and_save()

    def _parse_chunks(self, response):
        chunks = []
        is_last_chunk = False
        matches = re.finditer(r'<chunk_(\d+)(?:\s+last="true")?>(.*?)(?:</chunk_\1>|</chunk_\1\s+last="true">)', response, re.DOTALL)
        for match in matches:
            chunks.append(match.group(2))
            if 'last="true"' in match.group(0):
                is_last_chunk = True
        # Do not accept untagged code here; let validation handle non-compliance
        return chunks, is_last_chunk

    def _assemble_and_save(self):
        if not self.chunks:
            logger.error(f"No content collected to save for file: {self.source_file}")
            raise ValueError("No content collected to save")
        full_lines = []
        for i, chunk in enumerate(self.chunks):
            lines = chunk.splitlines()
            if i < len(self.chunks) - 1:
                while lines and not lines[-1].strip():  # Remove trailing blank lines from non-final chunks
                    lines.pop()
            full_lines.extend(lines)
        full_script = '\n'.join(full_lines)
        full_script = full_script.replace('\r\n', '\n').replace('\r', '\n')
        full_script = full_script + '\n'
        # Strip any number of blank / whitespace-only lines at the TOP
        full_script = re.sub(r'\A(?:[ \t]*\n)+', '', full_script)
        # Strip any number of blank / whitespace-only lines at the END
        #  and ensure the file ends with exactly one newline
        full_script = re.sub(r'(?:[ \t]*\n)+\Z', '\n', full_script)
        with open(self.source_file, "w") as f:
            f.write(full_script)
        logger.info(f"Modified script saved to {self.source_file}")
        self.message_history = [{"role": "system", "content": self.system_prompt}]
        return full_script + f"\n\nTask completed successfully. File {self.source_file} updated."

    def _assemble_and_save_partial(self):
        if not self.chunks:
            logger.error(f"No content collected to save (partial) for file: {self.source_file}")
            raise ValueError("No content collected to save")
        full_lines = []
        for i, chunk in enumerate(self.chunks):
            lines = chunk.splitlines()
            if i < len(self.chunks) - 1:
                while lines and not lines[-1].strip():  # Remove trailing blank lines from non-final chunks
                    lines.pop()
            full_lines.extend(lines)
        full_script = '\n'.join(full_lines)
        full_script = full_script.replace('\r\n', '\n').replace('\r', '\n')
        full_script = full_script + '\n'
        # Strip any number of blank / whitespace-only lines at the TOP
        full_script = re.sub(r'\A(?:[ \t]*\n)+', '', full_script)
        # Strip any number of blank / whitespace-only lines at the END
        #  and ensure the file ends with exactly one newline
        full_script = re.sub(r'(?:[ \t]*\n)+\Z', '\n', full_script)
        partial_file = f"{self.source_file}.partial"
        with open(partial_file, "w") as f:
            f.write(full_script)
        logger.info(f"Modified script saved to: {partial_file}")
        return full_script + f"\n\nTask not completed successfully. Content saved to: {partial_file} file."

    def _get_checkpoint_path(self):
        return f"{self.source_file}.resume.json"

    def _hash_file(self, file_path):
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _save_checkpoint(self, chunk_outputs, next_chunk_index, mod_request):
        try:
            checkpoint_data = {
                "completed_chunks": chunk_outputs,
                "next_chunk_index": next_chunk_index,
                "source_file": self.source_file,
                "mod_request": mod_request,
                "file_hash": self._hash_file(self.source_file)
            }
            with open(self._get_checkpoint_path(), "w") as f:
                json.dump(checkpoint_data, f)
        except Exception as e:
            logger.warning(f"Could not save checkpoint: {e}")

    def _load_checkpoint(self, mod_request):
        path = self._get_checkpoint_path()
        try:
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                if (data["mod_request"] == mod_request and 
                    data["source_file"] == self.source_file and 
                    data["file_hash"] == self._hash_file(self.source_file)):
                    return data
                else:
                    logger.warning("Checkpoint context changed. Ignoring checkpoint.")
                    return None
        except Exception as e:
            logger.warning(f"Could not load checkpoint: {e}")
        return None

    def _remove_checkpoint(self):
        try:
            os.remove(self._get_checkpoint_path())
        except Exception:
            pass

    def reset_state(self) -> None:
        self.task_completed = False
        self.chunks = []
        self.source_file = None
        self.modification_request = ""
        self.global_retries = 0
        self.message_history = [{"role": "system", "content": self.system_prompt}]
        logger.debug("ProtocolEngine state has been reset.")

# Default to chatgpt-4.1 capabilities
MAX_LINES_PER_CHUNK = 1000       
MAX_CHARS_PER_CHUNK = 100000     
TOKEN_BUDGET_PER_CHUNK = 20000   

def _configure_protocol_engine_limits():
    global MAX_LINES_PER_CHUNK, MAX_CHARS_PER_CHUNK, TOKEN_BUDGET_PER_CHUNK

    model = (config.MODEL or "").lower()
    if model.startswith("openai/gpt-5") or model.startswith("xai/grok-4"):
        MAX_LINES_PER_CHUNK = 15000       
        MAX_CHARS_PER_CHUNK = 2000000     
        TOKEN_BUDGET_PER_CHUNK = 120000   

    if model.startswith("openai/o3"):
        MAX_LINES_PER_CHUNK = 2000      
        MAX_CHARS_PER_CHUNK = 200000    
        TOKEN_BUDGET_PER_CHUNK = 40000

# Note: configure_protocol_engine() should be invoked before code that uses ENGINE.
ENGINE=None

def configure_protocol_engine():
    global ENGINE
    _configure_protocol_engine_limits()
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
         • ≤ {MAX_LINES_PER_CHUNK} lines
         • ≤ {MAX_CHARS_PER_CHUNK} characters
         • ≤ ~{TOKEN_BUDGET_PER_CHUNK} tokens (do not exceed this response size)
       - End chunks at logical boundaries (functions/classes) when possible. If the next line would exceed a limit, STOP and continue in the next chunk—no omissions.

    2) No Summary or Omission
       - Output EVERY line of the final modified file, in order (changed and unchanged).
       - NEVER use summary/omission phrases like “unchanged”, “rest of the file is unchanged”, “no change”, etc.
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
       - After outputting a chunk, WAIT for “Next chunk” or an explicit “chunk K” request before sending the next one.
       - When asked for chunk K, output ONLY <chunk_K> ... </chunk_K> and nothing else. Do NOT include any other <chunk_*> tags.
       - Only set last="true" when you are outputting the final chunk of the entire file.

    Example:
    <chunk_1>
    <all code from start of file up to a logical boundary without exceeding limits>
    </chunk_1>
    <chunk_2>
    <next contiguous section of code, strictly sequential, no omissions>
    </chunk_2>
    ...
    <chunk_N last="true">
    <all remaining code, to the end of file, within limits>
    </chunk_N>

    Further Notes:
    - If the modification request is ambiguous or risky, favor safety and preserve original intent.
    - Keep comments unless they conflict with the instructions.
    - Never omit code due to brevity. If limits are reached mid-section, stop at a safe boundary and continue in the next chunk.
    Begin by producing ONLY the first requested chunk according to these rules.

    CRITICAL FINAL REMINDERS:
    - You MUST output every single line of code, character by character
    - NEVER EVER use phrases like: "unchanged", "as-is", "remains the same", "no change", "rest of file unchanged"
    - If a line doesn't need modification, output it EXACTLY as it appears in the original
    - Think: "Copy every line literally" not "summarize unchanged sections"
    - The system will REJECT your response if you use ANY summary language
    - When in doubt: OUTPUT THE ACTUAL CODE, never describe it

    Remember: Your job is to be a precise code printer, not a helpful summarizer.
    """


    ENGINE = ProtocolEngine(
        model=config.MODEL,
        system_prompt=system_prompt,
        middleware=litellm
    )

STARTER_SCRIPT = ""  # Empty or minimal starter code

def stream_code(raw_user_input):
    logger.debug("stream_code called with user input (length: %d)", len(raw_user_input) if raw_user_input else 0)
    parts = raw_user_input.split(":", 1)
    if len(parts) == 1:
        logger.info(f"{red}Streaming code format: <file_name>:<prompt>{reset}")
        return
    file_name = parts[0]
    prompt = parts[1]
    logger.info("Streaming code for file: %s with prompt of length %d", file_name, len(prompt))
    ENGINE.fetch_modified_script(
        script_content=STARTER_SCRIPT,
        modification_request=prompt,
        source_file=file_name
    )
    return "Working."

def modify_source_code(source_file: str, modification_request: str, print_func=print) -> str:
    """
    Modifies source code in place with global retry safeguard.
    """
    model=config.MODEL
    logger.debug("modify_source_code called: file=%s, req-length=%d", source_file, len(modification_request) if modification_request else 0)
    ENGINE.reset_state()
    try:
        with open(source_file, 'r') as file:
            logger.debug(f"Reading file {source_file}")
            print_func(f"{yellow}Modifying file {source_file}{reset}")
            print_func(f"{yellow}Please wait. Modifications (with retries) may take up to 180 seconds of inference/reasoning.{reset}")
            print_func(f"{yellow}When the operation is complete, the BEL will ring.{reset}")
            source_content = file.read()
    except FileNotFoundError:
        return f"Unable to open {source_file}. Does not exist."
    except Exception as e:
        logger.debug("Error reading file %s: %s", source_file, str(e))
        return f"Error reading file {source_file}: {str(e)}"
    try:
        modified_script = ENGINE.fetch_modified_script(
            script_content=source_content,
            modification_request=modification_request,
            source_file=source_file
        )
        ring_bell()
        print_func(f"{yellow}\nModified {source_file}{reset}")

        return modified_script
    except Exception as e:
        print_func(f"{red}Failed to implement modifications to {source_file}.\nInstructions for manual modifications will follow.{reset}")
        logger.debug("Error in modify_source_code: %s", str(e))
        
        # Return error message instead of raising exception to maintain tool contract
        # This allows LLM to understand failure and avoid retry loops
        error_msg = str(e)
        if "No content collected to save" in error_msg:
            return (
                f"MODIFICATION FAILED: All automatic retries exhausted for {source_file}. "
                f"The AI model consistently failed to follow required chunk formatting instructions. "
                f"This indicates a fundamental model compliance issue that cannot be resolved through retries. "
                f"Manual code modification is required. "
                f"Original error: {error_msg}"
            )
        else:
            return f"MODIFICATION FAILED: Unable to modify {source_file}. Error: {error_msg}"
