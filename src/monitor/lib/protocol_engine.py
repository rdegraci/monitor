import difflib
import hashlib
import json
import litellm
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

from colored import attr, fg
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import BashLexer, DiffLexer, MarkdownLexer

from monitor import config
from monitor.lib import rate_limiter
from monitor.lib.progress import progress_dots
from monitor.lib.protocol_engine_utils import (
    PROHIBITED_SUMMARY_PATTERN,
    create_chunk_correction_prompt,
    create_compliance_warning,
    create_initial_modification_query,
    create_next_chunk_prompt,
    create_resume_chunk_prompt,
    create_system_prompt,
)
from monitor.lib.sound import ring_bell
from monitor.lib.token_management import count_message_tokens
from monitor.lib.edit_verification import verify_file_content

logger = logging.getLogger(__name__)

# Collateral-guard heuristic: warn (do NOT block) when a regenerated file
# changes more than this fraction of the original's lines relative to the
# original size. Whole-file regeneration's #1 failure is touching code it
# shouldn't; this surfaces the "rewrote half the file" case.
COLLATERAL_WARN_RATIO = 0.5
COLLATERAL_WARN_MIN_LINES = 20  # don't cry wolf on tiny files

# Module-level counter: how often the (risky, LLM-driven) tier-2 path runs.
# Visibility into whether the model is over-reaching for modify_source_code
# instead of the deterministic surgical / bulk-replace tools.
_MODIFY_SOURCE_CODE_CALLS = 0


class EditVerificationError(Exception):
    """Raised inside the assembly path when a regenerated file fails its
    pre-write verification gate. Carries enough context for the public
    entrypoint to return an actionable message to the model. The target file is
    never modified; the rejected content is saved to ``rejected_path``.
    """

    def __init__(self, source_file: str, tier: str, detail: str, rejected_path: str):
        self.source_file = source_file
        self.tier = tier
        self.detail = detail
        self.rejected_path = rejected_path
        super().__init__(f"{tier} verification failed for {source_file}: {detail}")

blue = fg("blue")
red = fg("red")
yellow = fg("yellow")
reset = attr("reset")

MESSAGE_HISTORY = []

# H-pe2: serializes modify_source_code / stream_code invocations because they
# share the module-level ENGINE singleton (chunks, message_history, source_file,
# checkpoint path). Without this lock, two concurrent tool calls trample each
# other's state mid-modification.
_ENGINE_LOCK = threading.Lock()


def _atomic_write_text(path: str, content: str) -> None:
    """Write ``content`` to ``path`` atomically.

    H-pe1: writes to a sibling tempfile in the same directory, fsyncs, and
    renames over the target. A crash mid-write leaves the original ``path``
    intact (or absent), never half-written. Same-directory tempfile guarantees
    the rename is a single filesystem operation.
    """
    dir_name = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
        dir=dir_name,
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync can legitimately fail on some filesystems (e.g. tmpfs
                # without backing storage); the rename is still atomic.
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def configure_protocol_engine_message_history(message_history: list):
    global MESSAGE_HISTORY
    logger.debug("Configuring message history, count: %d", len(message_history) if message_history else 0)
    MESSAGE_HISTORY.clear()
    if message_history:
        MESSAGE_HISTORY.extend(message_history)


class ProtocolEngine:
    """ProtocolEngine with global modification cycle retry logic."""

    MAX_RETRIES_PER_CHUNK = 3
    MAX_GLOBAL_MODIFICATION_ATTEMPTS = 2

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

        # Build contiguous line buckets, but snap each non-final boundary EARLIER
        # to a safe seam (blank line / top-level boundary at bracket depth zero)
        # so a chunk boundary never lands inside a construct. lines_per_chunk
        # stays the hard upper bound — we only ever cut sooner, never later.
        line_ranges = []
        start = 1  # 1-based inclusive
        while start <= total_lines:
            target_end = min(start + self.lines_per_chunk - 1, total_lines)
            if target_end < total_lines:
                end = self._safe_chunk_boundary(lines, start, target_end)
            else:
                end = target_end
            line_ranges.append((start, end))
            start = end + 1

        if not line_ranges:  # degenerate empty/whitespace file
            line_ranges = [(1, total_lines)]

        expected = max(1, len(line_ranges))
        plan = {
            "total_lines": total_lines,
            "expected_chunks": expected,
            "line_ranges": line_ranges,
        }

        logger.info(f"Created chunk plan: {total_lines} lines, {expected} expected chunks")
        logger.info(f"Line ranges: {plan['line_ranges']}")

        return plan

    def _safe_chunk_boundary(self, lines, start, target_end, lookback=None):
        """Return a 1-based end line ``<= target_end`` that is a safe place to cut.

        Snaps the boundary earlier (never later) to avoid splitting inside a
        construct: prefers a blank line, else a line after which the next line
        is dedented to column 0 (a top-level def/class/declaration boundary).
        A candidate is only accepted at bracket depth zero (all (), [], {}
        balanced from ``start``). Falls back to ``target_end`` if no safe seam
        is found within the lookback window.

        Bracket depth is a heuristic (it does not parse strings/comments), so
        the blank-line preference is the primary safety mechanism; the depth
        guard removes the obvious mid-bracket cuts.
        """
        if lookback is None:
            lookback = max(10, self.lines_per_chunk // 4)
        lo = max(start, target_end - lookback)

        # Prefix bracket depth at the END of each line in [start, target_end].
        depth_at = {}
        depth = 0
        for idx in range(start, target_end + 1):
            for ch in lines[idx - 1]:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth = max(0, depth - 1)
            depth_at[idx] = depth

        # 1) Prefer a blank line at depth 0 (cut AFTER it), scanning backward.
        for end in range(target_end, lo - 1, -1):
            if lines[end - 1].strip() == "" and depth_at.get(end, 1) == 0:
                return end
        # 2) Else a top-level boundary: the NEXT line starts at column 0
        #    (non-blank, non-continuation), at depth 0.
        for end in range(target_end, lo - 1, -1):
            if end >= len(lines):
                continue
            nxt = lines[end]  # 0-based index `end` == the line after 1-based `end`
            if nxt and not nxt[0].isspace() and depth_at.get(end, 1) == 0:
                return end
        return target_end

    def _non_compliance_message(self, chunk_index: int) -> str:
        return f"Non-compliant output at chunk {chunk_index} after all retries"

    def fetch_modified_script(self, script_content, modification_request, source_file):
        """
        Orchestrates source code modification with automatic retry after all chunk retries are exhausted.
        """
        self.modification_request = modification_request
        self.source_file = source_file
        self._modification_script_content = script_content
        logger.debug("fetch_modified_script called (global attempt: %d)", self.global_retries + 1)
        attempt_successful = False
        error_result = None
        result = None
        # M-pe6: ensure global_retries is reset even when _modification_cycle
        # raises. Previously the reset only ran on the graceful exit paths; an
        # exception during the cycle would leave global_retries non-zero for
        # the next invocation, eroding the available retry budget.
        try:
            while self.global_retries < self.MAX_GLOBAL_MODIFICATION_ATTEMPTS:
                result = self._modification_cycle(script_content, modification_request, source_file)
                if isinstance(result, str) and result.startswith("Non-compliant output at chunk"):
                    self.global_retries += 1
                    logger.warning(
                        f"Full modification cycle failed (attempt {self.global_retries} of {self.MAX_GLOBAL_MODIFICATION_ATTEMPTS}). Retrying from checkpoint..."
                    )
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
                logger.info(f"Modification completed in {self.global_retries + 1} cycles.")
                return result
            else:
                logger.error(
                    f"All modification attempts exhausted ({self.MAX_GLOBAL_MODIFICATION_ATTEMPTS}). Human intervention needed."
                )
                return error_result or "Modification process failed after all automatic retries. Manual intervention required."
        finally:
            self.global_retries = 0

    def _request_chunk_correction(self, non_compliant_chunk, original_source, chunk_index):
        """
        Ask the LLM to rewrite a non-compliant chunk, given the full original source code as reference.
        """
        prompt = create_chunk_correction_prompt(chunk_index, non_compliant_chunk, original_source)
        return self._send_request(prompt)

    def _modification_cycle(self, script_content, modification_request, source_file):
        if self.task_completed:
            logger.warning("Task already completed for file: %s", source_file)
            return "Task already completed"
        # Determine language from file extension
        ext = os.path.splitext(source_file)[1][1:].lower()
        languages = {
            "py": "Python",
            "swift": "Swift",
            "js": "JavaScript",
            "ts": "TypeScript",
            "java": "Java",
            "cpp": "C++",
            "c": "C",
            # Add more as needed
        }
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
        is_last_expected = start_chunk_index == self.expected_total_chunks
        (lo, hi) = line_ranges[start_chunk_index - 1] if line_ranges else (1, None)

        last_directive = ' last="true"' if is_last_expected else ""
        initial_query = create_initial_modification_query(
            script_content=script_content,
            modification_request=modification_request,
            start_chunk_index=start_chunk_index,
            expected_total_chunks=self.expected_total_chunks,
            lo=lo,
            hi=hi,
            lines_per_chunk=self.lines_per_chunk,
            chars_per_chunk=self.chars_per_chunk,
            last_directive=last_directive,
        )

        logger.info(f"Starting modification cycle for {source_file}")
        logger.info(f"start_chunk_index={start_chunk_index}, is_last_expected={is_last_expected}, lines={lo}..{hi}")
        logger.info(f"Initial query length: {len(initial_query)} chars")

        if not self.chunks:
            logger.info("No existing chunks, requesting initial chunk")
            chunk_index = 1
            try:
                initial_response = self._send_request_with_compliance_retry(initial_query, chunk_index=chunk_index)
            except ValueError as e:
                logger.warning(
                    "Chunk %s failed after all compliance retries: %s",
                    chunk_index,
                    str(e),
                )
                return self._non_compliance_message(chunk_index)
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

            # H-pe4: rate-limit preflight. Without this gate, a multi-chunk
            # modification fires N LLM calls in tight succession, each
            # accounted only post-hoc by tooling.py's flat estimate, easily
            # bursting past the TPM cap.
            try:
                if rate_limiter.RATE_LIMITER is not None:
                    estimated_request = count_message_tokens(self.message_history)
                    try:
                        estimated_request += int(TOKEN_BUDGET_PER_CHUNK)
                    except Exception:
                        pass
                    wait_result = rate_limiter.RATE_LIMITER.wait_if_needed(estimated_request)
                    if wait_result is None:
                        logger.warning(
                            "ProtocolEngine _send_request: estimated %s tokens exceeds rate-limiter safety threshold; aborting chunk",
                            estimated_request,
                        )
                        # Pop the user query we just appended so a retry can
                        # rebuild a clean history.
                        if query:
                            try:
                                self.message_history.pop()
                            except IndexError:
                                pass
                        raise RuntimeError(
                            f"Rate-limiter safety threshold exceeded ({estimated_request} estimated tokens)"
                        )
            except RuntimeError:
                raise
            except Exception:
                logger.exception("Rate-limit preflight failed; proceeding without gating")

            with progress_dots():
                response = self.middleware.completion(
                    model=self.model,
                    messages=self.message_history,
                    max_completion_tokens=TOKEN_BUDGET_PER_CHUNK,
                    drop_params=True,
                )

            # H-pe4: record actual usage from the provider response.
            try:
                if rate_limiter.RATE_LIMITER is not None:
                    usage = getattr(response, "usage", None)
                    actual_used = None
                    if usage is not None:
                        if isinstance(usage, dict):
                            actual_used = usage.get("total_tokens")
                        else:
                            actual_used = getattr(usage, "total_tokens", None)
                    if actual_used is None:
                        actual_used = count_message_tokens(self.message_history)
                    rate_limiter.RATE_LIMITER.add_request(int(actual_used or 0))
            except Exception:
                logger.exception("Failed to record actual usage with rate limiter after ProtocolEngine call")

            content = response.choices[0].message["content"]
            self.message_history.append({"role": "assistant", "content": content})
            return content
        except RuntimeError:
            raise
        except Exception as e:
            # M-pe4: preserve the original exception type and traceback via
            # `from e`. The previous bare `raise Exception("...")` discarded
            # the cause, leaving every LLM failure indistinguishable in
            # tracebacks.
            logger.error("Middleware completion error: %s", str(e))
            raise RuntimeError(f"LLM call failed: {e}") from e

    def _send_request_with_compliance_retry(self, query, chunk_index):
        retries = 0
        output = None
        last_noncompliant_output = None
        prohibited = set()
        while retries < self.MAX_RETRIES_PER_CHUNK:
            augmented_query = query
            if retries > 0:
                compliance_warn = create_compliance_warning(retries, self.MAX_RETRIES_PER_CHUNK, chunk_index)
                augmented_query = f"{query}\n\n{compliance_warn}"
            try:
                logger.debug(f"Requesting chunk {chunk_index}, retry {retries + 1}")
                output = self._send_request(augmented_query)
            except Exception as e:
                # M-pe4: preserve cause across the second wrapping layer too.
                logger.error("LLM call failed for chunk %s, retry %s: %s", chunk_index, retries + 1, str(e))
                raise RuntimeError(
                    f"LLM call failed for chunk {chunk_index}, retry {retries + 1}: {e}"
                ) from e
            prohibited = self._find_prohibited_phrases_in_text(output)
            if prohibited:
                retries += 1
                time.sleep(2**retries)
                last_noncompliant_output = output
                logger.warning(
                    f"Non-compliant output for chunk {chunk_index}, retry {retries} of {self.MAX_RETRIES_PER_CHUNK}. Markers: {list(prohibited) if prohibited else '-'} {last_noncompliant_output}"
                )
                continue
            return output
        # If retries exhausted, attempt LLM correction using the full original source
        logger.warning(
            f"All compliance retries failed for chunk {chunk_index}; retrying correction with full original source."
        )
        if last_noncompliant_output:
            corrected_chunk = self._request_chunk_correction(
                non_compliant_chunk=last_noncompliant_output,
                original_source=self._modification_script_content,
                chunk_index=chunk_index,
            )
            prohibited = self._find_prohibited_phrases_in_text(corrected_chunk) if corrected_chunk else set()
            if corrected_chunk and not prohibited:
                return corrected_chunk
        logger.warning(
            f"Non-compliant output for chunk {chunk_index}, retry {retries} of {self.MAX_RETRIES_PER_CHUNK}. Markers: {list(prohibited) if prohibited else '-'}"
        )
        self._assemble_and_save_partial()
        raise ValueError(self._non_compliance_message(chunk_index))

    def _has_prohibited_summary_marker(self, text):
        return bool(PROHIBITED_SUMMARY_PATTERN.search(text)) if text else False

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
            re.DOTALL,
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
        comments.extend(re.findall(r"(?m)#.*$", text))  # # comment (python/shell)
        comments.extend(re.findall(r"(?m)//.*$", text))  # // comment (C/JS/Java)

        # Block comments
        comments.extend(re.findall(r"/\*[\s\S]*?\*/", text))  # /* ... */
        comments.extend(re.findall(r"<!--[\s\S]*?-->", text))  # <!-- ... -->

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
            norm = re.sub(r"^\s*(?:#{1,}|//+|/\*+|<!--)\s*", "", comment)  # leading markers
            norm = re.sub(r"\s*(?:\*/|-->)\s*$", "", norm)  # trailing block markers

            # Now search only the comment text using the existing compiled pattern
            for m in PROHIBITED_SUMMARY_PATTERN.finditer(norm):
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
            re.DOTALL,
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
            logger.info(
                f'Received unexpected last="true" for chunk {expected_index} (expected at chunk {self.expected_total_chunks})'
            )
            raise ValueError(f'Received last="true" before final chunk (expected at chunk {self.expected_total_chunks}).')

        # Size constraints
        line_count = len(content.splitlines())
        char_count = len(content)
        logger.info(
            f"Chunk {expected_index} size check: {line_count}/{self.lines_per_chunk} lines, {char_count}/{self.chars_per_chunk} chars"
        )

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
        logger.info(
            f"_collect_chunks starting: initial_response={'provided' if initial_response else 'None'}, start_chunk_index={start_chunk_index}"
        )
        logger.info(f"Expected total chunks: {self.expected_total_chunks}, current chunks collected: {len(self.chunks)}")

        print_func("\nModifications complete.", end="", flush=True)
        line_ranges = getattr(self, "line_ranges", None)
        found_last_chunk = False
        iteration = 0
        max_iterations = 50  # Increased for larger files

        if initial_response is None:
            logger.info(f"No initial response provided, requesting chunk {start_chunk_index}")
            # For resume: Request the next chunk with specific index
            next_chunk_prompt = create_resume_chunk_prompt(start_chunk_index)
            try:
                current_response = self._send_request_with_compliance_retry(
                    next_chunk_prompt, chunk_index=start_chunk_index
                )
            except ValueError as e:
                logger.warning(
                    "Chunk %s failed after all compliance retries: %s",
                    start_chunk_index,
                    str(e),
                )
                return self._non_compliance_message(start_chunk_index)
            logger.info(
                f"Received response for chunk {start_chunk_index}: {len(current_response) if current_response else 0} chars"
            )
        else:
            logger.info(f"Using provided initial response: {len(initial_response)} chars")
            current_response = initial_response
        while not found_last_chunk and iteration < max_iterations:
            iteration += 1
            logger.info(f"_collect_chunks iteration {iteration}: processing chunk, found_last_chunk={found_last_chunk}")

            if current_response:
                expected_index = (
                    start_chunk_index if (iteration == 1 and initial_response is not None) else (len(self.chunks) + 1)
                )
                is_last_expected = expected_index == self.expected_total_chunks
                logger.info(
                    f"Processing current response for expected chunk {expected_index} (is_last_expected: {is_last_expected})"
                )

                try:
                    expected_index = (
                        start_chunk_index
                        if (iteration == 1 and initial_response is not None)
                        else (len(self.chunks) + 1)
                    )
                    is_last_expected = expected_index == self.expected_total_chunks

                    new_chunk, is_last_chunk = self._validate_and_extract_chunk(
                        response=current_response,
                        expected_index=expected_index,
                        is_last_expected=is_last_expected,
                    )
                    logger.info(f"Successfully extracted chunk {expected_index}, is_last_chunk={is_last_chunk}")
                except ValueError as e:
                    logger.debug(f"Chunk validation failed: {e}")
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
                logger.info(
                    f"Need more chunks. Requesting next chunk {len(self.chunks) + 1} of {self.expected_total_chunks}"
                )
                try:
                    next_index = len(self.chunks) + 1
                    is_last = next_index == self.expected_total_chunks
                    (lo, hi) = line_ranges[next_index - 1] if line_ranges else (None, None)

                    logger.info(f"Requesting chunk {next_index}, is_last={is_last}, lines {lo}..{hi}")

                    next_chunk_prompt = create_next_chunk_prompt(
                        next_index=next_index,
                        expected_total_chunks=self.expected_total_chunks,
                        lo=lo,
                        hi=hi,
                        lines_per_chunk=self.lines_per_chunk,
                        chars_per_chunk=self.chars_per_chunk,
                        is_last=is_last,
                    )
                    try:
                        current_response = self._send_request_with_compliance_retry(
                            next_chunk_prompt, chunk_index=next_index
                        )
                    except ValueError as e:
                        logger.warning(
                            "Chunk %s failed after all compliance retries: %s",
                            next_index,
                            str(e),
                        )
                        return self._non_compliance_message(next_index)
                    logger.info(
                        f"Received response for chunk {next_index}: {len(current_response) if current_response else 0} chars"
                    )
                except ValueError as e:
                    if "Non-compliant output at chunk" in str(e):
                        logger.error(f"Non-compliance error: {str(e)}")
                        self._assemble_and_save_partial()
                        return f"Non-compliant output at chunk {len(self.chunks) + 1}. Partial results saved."
                    else:
                        logger.error(f"Error in chunk processing: {str(e)}")
                        if self.chunks:
                            self._assemble_and_save_partial()
                        logger.info("Code modification completed with partial results.")
                        break
                except Exception as e:
                    logger.error("Error requesting next chunk: %s", str(e))
                    if self.chunks:
                        self._assemble_and_save_partial()
                    logger.info("Code modification completed with partial results.")
                    break
        if iteration >= max_iterations and self.chunks:
            logger.info(f"\nReached max iterations ({max_iterations}). Using collected chunks.")
            self._assemble_and_save()

    def _parse_chunks(self, response):
        chunks = []
        is_last_chunk = False
        matches = re.finditer(
            r'<chunk_(\d+)(?:\s+last="true")?>(.*?)(?:</chunk_\1>|</chunk_\1\s+last="true">)',
            response,
            re.DOTALL,
        )
        for match in matches:
            chunks.append(match.group(2))
            if 'last="true"' in match.group(0):
                is_last_chunk = True
        # Do not accept untagged code here; let validation handle non-compliance
        return chunks, is_last_chunk

    def _assemble_full_script(self) -> str:
        """Join collected chunks into the final, normalized file content.

        Shared by ``_assemble_and_save`` and ``_assemble_and_save_partial`` so
        the two assembly paths cannot drift. Strips trailing blank lines from
        non-final chunks, normalizes line endings to ``\\n``, and trims
        leading/trailing blank lines to a single trailing newline.
        """
        if not self.chunks:
            logger.debug(f"No content collected to save for file: {self.source_file}")
            raise ValueError("No content collected to save")
        full_lines = []
        for i, chunk in enumerate(self.chunks):
            lines = chunk.splitlines()
            if i < len(self.chunks) - 1:
                while lines and not lines[-1].strip():  # Remove trailing blank lines from non-final chunks
                    lines.pop()
            full_lines.extend(lines)
        full_script = "\n".join(full_lines)
        full_script = full_script.replace("\r\n", "\n").replace("\r", "\n")
        full_script = full_script + "\n"
        # Strip any number of blank / whitespace-only lines at the TOP
        full_script = re.sub(r"\A(?:[ \t]*\n)+", "", full_script)
        # Strip any number of blank / whitespace-only lines at the END
        #  and ensure the file ends with exactly one newline
        full_script = re.sub(r"(?:[ \t]*\n)+\Z", "\n", full_script)
        return full_script

    def _collateral_footprint(self, original: str, updated: str) -> dict:
        """Cheap change footprint of ``updated`` vs ``original``.

        Returns added/removed line counts, hunk count, and the changed-line
        ratio relative to the original size. Used by the collateral guard.
        """
        diff = list(difflib.unified_diff(original.splitlines(), updated.splitlines(), n=0))
        added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
        hunks = sum(1 for l in diff if l.startswith("@@"))
        base = max(1, len(original.splitlines()))
        return {"added": added, "removed": removed, "hunks": hunks, "ratio": (added + removed) / base}

    def _guard_and_verify(self, full_script: str) -> dict:
        """Collateral guard (log/warn, never block) + verification gate (blocks).

        Returns the footprint dict on success. On verification failure: writes
        the rejected content to a ``<source>.rejected`` sidecar, removes the
        checkpoint (so an auto-resume won't re-emit the same broken output), and
        raises :class:`EditVerificationError`. The target file is left untouched
        because this runs BEFORE ``_atomic_write_text``.
        """
        original = self._modification_script_content or ""
        fp = self._collateral_footprint(original, full_script)
        logger.info(
            "modify_source_code footprint for %s: +%d/-%d lines across %d hunk(s) (ratio=%.2f)",
            self.source_file, fp["added"], fp["removed"], fp["hunks"], fp["ratio"],
        )
        if (
            original
            and len(original.splitlines()) >= COLLATERAL_WARN_MIN_LINES
            and fp["ratio"] > COLLATERAL_WARN_RATIO
        ):
            logger.warning(
                "Large collateral footprint for %s: %.0f%% of lines changed — verify the "
                "regeneration did not rewrite unrelated code.",
                self.source_file, fp["ratio"] * 100,
            )

        ok, detail, tier = verify_file_content(self.source_file, full_script)
        if not ok:
            rejected_path = f"{self.source_file}.rejected"
            try:
                _atomic_write_text(rejected_path, full_script)
            except Exception as e:
                logger.error("Could not write rejected sidecar %s: %s", rejected_path, e)
                rejected_path = ""
            # Drop the checkpoint so an automatic resume doesn't re-emit and
            # re-reject the same broken chunks.
            self._remove_checkpoint()
            logger.error(
                "Edit verification (%s) rejected regenerated %s: %s",
                tier, self.source_file, detail,
            )
            raise EditVerificationError(self.source_file, tier, detail or "invalid", rejected_path)
        return fp

    def _assemble_and_save(self):
        full_script = self._assemble_full_script()
        # Collateral guard + verification gate run BEFORE the write. A rejected
        # edit raises here, so the target file is never modified.
        fp = self._guard_and_verify(full_script)
        _atomic_write_text(self.source_file, full_script)
        logger.info(f"Modified script saved to {self.source_file}")
        self.message_history = [{"role": "system", "content": self.system_prompt}]
        footprint_note = f" (changed +{fp['added']}/-{fp['removed']} lines across {fp['hunks']} hunk(s))"
        return full_script + f"\n\nTask completed successfully. File {self.source_file} updated.{footprint_note}"

    def _assemble_and_save_partial(self):
        # Partial saves are an explicit failure path: the content is incomplete
        # and goes to a ``.partial`` sidecar, NOT the target file, so it does
        # not run the verification gate (an incomplete file is expected to be
        # invalid).
        full_script = self._assemble_full_script()
        partial_file = f"{self.source_file}.partial"
        _atomic_write_text(partial_file, full_script)
        logger.info(f"Modified script saved to: {partial_file}")
        # M-pe2: reset message_history to match _assemble_and_save's behavior.
        # Without this, global retries accumulate the prior cycle's prompts +
        # assistant chunks and quickly balloon the context cost.
        self.message_history = [{"role": "system", "content": self.system_prompt}]
        return full_script + f"\n\nTask not completed successfully. Content saved to: {partial_file} file."

    def _get_checkpoint_path(self):
        return f"{self.source_file}.resume.json"

    def _hash_file(self, file_path):
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
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
                "file_hash": self._hash_file(self.source_file),
            }
            # M-pe3: atomic write so a crash mid-serialize doesn't leave a
            # corrupt JSON that _load_checkpoint will silently discard,
            # destroying progress.
            _atomic_write_text(self._get_checkpoint_path(), json.dumps(checkpoint_data))
        except Exception as e:
            logger.error(f"Could not save checkpoint: {e}")

    def _load_checkpoint(self, mod_request):
        path = self._get_checkpoint_path()
        try:
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                if (
                    data["mod_request"] == mod_request
                    and data["source_file"] == self.source_file
                    and data["file_hash"] == self._hash_file(self.source_file)
                ):
                    return data
                else:
                    logger.warning("Checkpoint context changed. Ignoring checkpoint.")
                    return None
        except Exception as e:
            logger.error(f"Could not load checkpoint: {e}")
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
        # H-pe3: re-seed message_history from the module-global MESSAGE_HISTORY
        # so that conversation context set by callers via
        # configure_protocol_engine_message_history actually reaches the LLM.
        # Previously reset_state discarded the history, leaving the engine
        # talking to the model with system prompt only — silently dropping the
        # user's prior turns and tool results.
        self.message_history = [{"role": "system", "content": self.system_prompt}]
        if MESSAGE_HISTORY:
            filtered_history = [msg for msg in MESSAGE_HISTORY if isinstance(msg, dict) and msg.get("role") != "system"]
            self.message_history.extend(filtered_history)
        logger.debug(
            "ProtocolEngine state has been reset (message_history seeded with %d non-system messages)",
            len(self.message_history) - 1,
        )


# Default to chatgpt-4.1 capabilities
MAX_LINES_PER_CHUNK = 1000
MAX_CHARS_PER_CHUNK = 100000
TOKEN_BUDGET_PER_CHUNK = 20000

# Hard cap on the source file modify_source_code will accept. Sized for ~15-20K
# lines of typical source — anything larger is almost always generated code,
# vendored bundles, minified output, or a file that should be refactored before
# automated editing.
MAX_SOURCE_FILE_BYTES = 1024 * 1024  # 1 MiB

# Cap on the diff text included in the tool result so the model isn't flooded
# with the entire change set every call.
MAX_DIFF_RESULT_CHARS = 8000


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
ENGINE = None


def configure_protocol_engine():
    global ENGINE
    _configure_protocol_engine_limits()

    system_prompt = create_system_prompt(
        max_lines_per_chunk=MAX_LINES_PER_CHUNK,
        max_chars_per_chunk=MAX_CHARS_PER_CHUNK,
        token_budget_per_chunk=TOKEN_BUDGET_PER_CHUNK,
    )

    ENGINE = ProtocolEngine(
        model=config.MODEL,
        system_prompt=system_prompt,
        middleware=litellm,
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
    # H-pe2: serialize access to the shared ENGINE singleton.
    with _ENGINE_LOCK:
        ENGINE.fetch_modified_script(
            script_content=STARTER_SCRIPT,
            modification_request=prompt,
            source_file=file_name,
        )
    return "Working."


def _try_perform_git_diff_file(path: str):
    try:
        from monitor.lib.git import perform_git_diff_file
    except Exception:
        perform_git_diff_file = None

    if not perform_git_diff_file:
        return None, "perform_git_diff_file not available"

    try:
        return perform_git_diff_file(path), None
    except Exception as e:
        return None, str(e)


def _get_git_run_git_capture():
    """Returns monitor.lib.git.run_git_capture if importable, else None."""
    try:
        from monitor.lib.git import run_git_capture
    except Exception:
        return None
    return run_git_capture


def _is_inside_git_work_tree(cwd: str | None = None) -> bool:
    """Returns True if the given directory is inside a Git work tree.

    This function avoids surfacing Git errors to end users by using a lightweight
    probe command: `git rev-parse --is-inside-work-tree`.

    Args:
        cwd: Optional working directory to run the Git command in.

    Returns:
        True if inside a Git work tree and Git is available; otherwise False.
    """
    run_git_capture = _get_git_run_git_capture()
    if run_git_capture:
        try:
            out = run_git_capture(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
            return str(out).strip().lower() == "true"
        except Exception:
            return False

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    except Exception:
        return False

    if proc.returncode != 0:
        return False
    return (proc.stdout or "").strip().lower() == "true"


def _get_os_print_diff():
    """Returns monitor.lib.os.print_diff if importable, else None."""
    try:
        from monitor.lib.os import print_diff
    except Exception:
        return None
    return print_diff


def _try_print_diff_helper(diff_text: str, print_func=print):
    """Prints a diff via monitor.lib.os.print_diff if available.

    Args:
        diff_text: Unified diff text to print.
        print_func: Fallback printing function to use if needed.

    Returns:
        True if monitor.lib.os.print_diff was called successfully, else False.
    """
    if not diff_text:
        return False
    print_diff = _get_os_print_diff()
    if not print_diff:
        return False

    try:
        print_diff(diff_text)
        return True
    except Exception:
        try:
            print_func(diff_text, end="")
            return True
        except Exception:
            return False


def _highlight_and_print_diff(diff_text: str, print_func=print):
    if not diff_text:
        return
    try:
        colored_diff = highlight(diff_text, DiffLexer(), TerminalFormatter(reset=True))
        print_func(colored_diff, end="")
    except Exception:
        print_func(diff_text, end="")


def _print_unified_diff(original_text: str, updated_text: str, path: str, print_func=print):
    if original_text is None or updated_text is None:
        return
    if original_text == updated_text:
        return
    diff_lines = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        updated_text.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    diff_text = "".join(diff_lines)
    if not diff_text.strip():
        return
    if _try_print_diff_helper(diff_text, print_func=print_func):
        return
    _highlight_and_print_diff(diff_text, print_func=print_func)


def modify_source_code(source_file: str, modification_request: str, print_func=print) -> str:
    """
    Modifies source code in place with global retry safeguard.
    """
    # Part 6 instrumentation: count how often the (risky, LLM-driven) tier-2
    # path runs, for visibility into whether the model is over-reaching for
    # modify_source_code instead of the deterministic surgical / bulk-replace
    # tools.
    global _MODIFY_SOURCE_CODE_CALLS
    _MODIFY_SOURCE_CODE_CALLS += 1
    logger.info(
        "modify_source_code invoked (count=%d) for %s — tier-2 LLM regeneration path.",
        _MODIFY_SOURCE_CODE_CALLS, source_file,
    )
    # H-pe2: serialize access to the shared ENGINE singleton for the full
    # duration of the modification. Concurrent invocations would otherwise
    # share chunks / message_history / source_file / checkpoint path.
    with _ENGINE_LOCK:
        try:
            return _modify_source_code_locked(source_file, modification_request, print_func)
        except EditVerificationError as e:
            # Agent-level reflection (Part 4): the regenerated file failed the
            # pre-write gate, so the target was left untouched. Return an
            # actionable message so the calling model can react — retry, switch
            # to a surgical edit, or refine the request.
            msg = (
                f"Edit rejected: the regenerated {e.source_file} failed {e.tier} "
                f"verification ({e.detail}). The original file was NOT modified"
                + (
                    f"; the rejected output was saved to {e.rejected_path} for inspection"
                    if e.rejected_path
                    else ""
                )
                + ". Consider a surgical edit (text_file_str_replace_in_file) or a more "
                "specific modification_request."
            )
            logger.warning(msg)
            return msg


def _modify_source_code_locked(source_file: str, modification_request: str, print_func=print) -> str:
    model = config.MODEL
    logger.debug(
        "modify_source_code called: file=%s, req-length=%d",
        source_file,
        len(modification_request) if modification_request else 0,
    )
    # M-pe5: re-derive chunk-budget constants from the current config.MODEL.
    # The values are frozen at configure_protocol_engine() time, so a runtime
    # set_model() leaves the engine with stale budgets — e.g., a switch from
    # a gpt-5-class model down to o3 would keep the larger limits and the
    # next LLM call would overshoot.
    _configure_protocol_engine_limits()
    ENGINE.lines_per_chunk = MAX_LINES_PER_CHUNK
    ENGINE.chars_per_chunk = MAX_CHARS_PER_CHUNK
    # S3: the engine's system_prompt embeds the chunk-limit numbers as text
    # via create_system_prompt(). M-pe5 fixes the int values used by code,
    # but the prompt string the model sees still has the startup values
    # interpolated. Rebuild it so the model and the validator agree.
    ENGINE.system_prompt = create_system_prompt(
        max_lines_per_chunk=MAX_LINES_PER_CHUNK,
        max_chars_per_chunk=MAX_CHARS_PER_CHUNK,
        token_budget_per_chunk=TOKEN_BUDGET_PER_CHUNK,
    )
    ENGINE.reset_state()

    # Hard size guard. Refuse files larger than MAX_SOURCE_FILE_BYTES rather
    # than loading them into memory and kicking off an enormous chunked edit;
    # files past 1 MiB are almost always generated, vendored, or minified.
    try:
        file_size = os.path.getsize(source_file)
    except FileNotFoundError:
        return {"ok": False, "file": source_file, "error": f"Unable to open {source_file}. Does not exist."}
    except Exception as e:
        logger.error("Error stat-ing %s: %s", source_file, str(e))
        return {"ok": False, "file": source_file, "error": f"Error checking size of {source_file}: {e}"}
    if file_size > MAX_SOURCE_FILE_BYTES:
        return {
            "ok": False,
            "file": source_file,
            "error": (
                f"File is {file_size} bytes; exceeds the {MAX_SOURCE_FILE_BYTES}-byte "
                f"(1 MiB) limit. Files this large are almost always generated, vendored, "
                f"or minified — edit a smaller, focused file, or pre-split the work."
            ),
        }

    original_source_content = None
    try:
        with open(source_file, "r") as file:
            logger.debug(f"Reading file {source_file}")
            print_func(f"{yellow}Analyzing {source_file} for modification.{reset}")
            source_content = file.read()
            original_source_content = source_content
            # Compute line_count after reading source_content and only show extended notice for large files (>500 LOC)
            try:
                line_count = len(source_content.splitlines())
            except Exception:
                line_count = 0
            if line_count > 500:
                print_func(f"{yellow}{source_file} has more than 500 lines.{reset}")
                print_func(f"{yellow}Analysis of the source code may take up to 45 seconds of inference/reasoning.{reset}")
                print_func(f"{yellow}Large or complex source code (>500 LOC) may take longer or require multiple modifications.{reset}")
    except FileNotFoundError:
        return {"ok": False, "file": source_file, "error": f"Unable to open {source_file}. Does not exist."}
    except Exception as e:
        logger.error("Error reading file %s: %s", source_file, str(e))
        return {"ok": False, "file": source_file, "error": f"Error reading file {source_file}: {str(e)}"}
    try:
        modified_script = ENGINE.fetch_modified_script(
            script_content=source_content,
            modification_request=modification_request,
            source_file=source_file,
        )
        ring_bell()
        print_func(f"{yellow}\nAnalyzing modifications made to {source_file}{reset}")

        updated_content = None
        try:
            with open(source_file, "r") as f:
                updated_content = f.read()
        except Exception as e:
            logger.error("Error reading updated file %s: %s", source_file, str(e))

        # Compute and display the diff (terminal-visible via print_func), and
        # keep a string copy to ship back in the tool result.
        diff_for_result = ""
        diff_text = None
        git_err = None
        is_git_repo = _is_inside_git_work_tree(cwd=os.path.dirname(os.path.abspath(source_file)) or None)
        if is_git_repo:
            diff_text, git_err = _try_perform_git_diff_file(source_file)
            if git_err:
                logger.info("Git diff failed; falling back to difflib. Error: %s", git_err)
                diff_text = None

        if diff_text and str(diff_text).strip():
            if isinstance(diff_text, bytes):
                try:
                    diff_text = diff_text.decode("utf-8", errors="replace")
                except Exception:
                    diff_text = str(diff_text)
            if not str(diff_text).endswith("\n"):
                diff_text = str(diff_text) + "\n"
            if not _try_print_diff_helper(str(diff_text), print_func=print_func):
                _highlight_and_print_diff(str(diff_text), print_func=print_func)
            diff_for_result = str(diff_text)
        else:
            import difflib
            diff_for_result = "".join(difflib.unified_diff(
                (original_source_content or "").splitlines(keepends=True),
                (updated_content or "").splitlines(keepends=True),
                fromfile=f"a/{source_file}",
                tofile=f"b/{source_file}",
            ))
            _print_unified_diff(original_source_content or "", updated_content or "", source_file, print_func=print_func)

        # Detect engine retry-exhaustion markers embedded in the returned text
        # (the engine signals some failures by returning a sentinel string
        # rather than raising).
        failure_markers = (
            "Modification process failed",
            "Manual intervention required",
            "No content collected to save",
        )
        if not modified_script or any(m in (modified_script or "") for m in failure_markers):
            return {
                "ok": False,
                "file": source_file,
                "error": modified_script or "Engine returned no content.",
            }

        if len(diff_for_result) > MAX_DIFF_RESULT_CHARS:
            diff_for_result = diff_for_result[:MAX_DIFF_RESULT_CHARS] + "\n... [diff truncated] ..."

        try:
            lines_changed = (
                len((updated_content or "").splitlines())
                - len((original_source_content or "").splitlines())
            )
        except Exception:
            lines_changed = None

        return {
            "ok": True,
            "file": source_file,
            "lines_changed": lines_changed,
            "diff": diff_for_result,
            "message": f"Modified {source_file}",
        }
    except Exception as e:
        print_func(
            f"{red}\nFailed to implement modifications to {source_file}.{reset}\n{red}Attempting to re-modify.{reset}"
        )
        logger.error("Error in modify_source_code: %s", str(e))

        error_msg = str(e)
        if "No content collected to save" in error_msg:
            error_text = (
                f"MODIFICATION FAILED: All automatic retries exhausted for {source_file}. "
                f"The AI model consistently failed to follow required chunk formatting instructions. "
                f"This indicates a fundamental model compliance issue that cannot be resolved through retries. "
                f"Manual code modification is required. "
                f"Original error: {error_msg}"
            )
        else:
            error_text = f"MODIFICATION FAILED: Unable to modify {source_file}. Error: {error_msg}"
        return {"ok": False, "file": source_file, "error": error_text}
