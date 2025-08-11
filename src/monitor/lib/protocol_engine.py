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

from monitor.lib.git import perform_git_diff_file

logger = logging.getLogger(__name__)

blue = fg('blue')
red = fg('red')
yellow = fg('yellow')
reset = attr('reset')

MESSAGE_HISTORY = []


def configure_protocol_engine_message_history(message_history):
    global MESSAGE_HISTORY
    logger.debug("Configuring message history, count: %d", len(message_history) if message_history else 0)
    MESSAGE_HISTORY = message_history


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

    def __init__(self, model, system_prompt, middleware=litellm, initial_message_history=MESSAGE_HISTORY):
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
        if initial_message_history:
            if not isinstance(initial_message_history, list):
                logger.error("initial_message_history must be a list, got: %s", type(initial_message_history))
                raise ValueError("initial_message_history must be a list of message dictionaries")
            filtered_history = [msg for msg in initial_message_history if msg.get("role") != "system"]
            self.message_history.extend(filtered_history)
        logger.debug("ProtocolEngine initialized. Message history length: %d", len(self.message_history))

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
        initial_query = (
            f"Here's source code:\n\n{script_content}\n\n"
            f"Modify it to {modification_request}. IMPORTANT: Return the full modified source code, "
            f"split into chunks tagged with <chunk_n></chunk_n>, starting with chunk 1."
            f"Send exactly one chunk per response, and stop after each chunk until I say 'Next chunk'. "
            f"IMPORTANT: Mark the last chunk with <chunk_n last=\"true\">. Each chunk can contain up to 12288 tokens "
            f"of code (measured by word count, where 1 word ≈ 1 token), unless the remaining code is less. "
            f"Do not generate small chunks like 400 tokens—this is critical for efficiency. The output window "
            f"is 16384 tokens, so up to 12288-token chunks fit perfectly. Return only raw {language} source code as text "
            f"within the chunks—do not include markdown (e.g., ```{language.lower()} or ``` or ```python), comments, or any formatting "
            f"outside the code itself. Do not reorder the functions—keep them in their original sequence for "
            f"git diff readability. Ensure every function, helper method, property, and dependency is included "
            f"across the chunks—do not omit any part of the modified code."
            f"Do not remove any comments from the code unless necessary."
            f"IMPORTANT: Do not leave out any code due to brevity. Do not leave out any code that is unchanged."
            f"IMPORTANT:"
            f"- You must print EVERY line of the new source file, including ALL unchanged code."
            f"- Do NOT insert lines such as \"# (rest of the file is unchanged)\"."
            f"- Every line must be present: even unchanged functions, classes, imports."
            f"- If you are unable to fit the whole file in a chunk, continue in the next chunk with NO OMISSION."
        )
        if not self.chunks:
            initial_response = self._send_request_with_compliance_retry(initial_query, chunk_index=1, is_next_chunk=False)
            self._collect_chunks(initial_response, modification_request, start_chunk_index=1)
        else:
            self._collect_chunks(None, modification_request, start_chunk_index=start_chunk_index)
        self.task_completed = True
        return self._assemble_and_save()

    def _send_request(self, query):
        logger.debug(f"_send_request with query length: {len(query)}")
        try:
            if query:
                self.message_history.append({"role": "user", "content": query})
            response = self.middleware.completion(
                model=self.model,
                messages=self.message_history,
                max_completion_tokens=16384,
                drop_params=True
            )
            content = response.choices[0].message['content']
            self.message_history.append({"role": "assistant", "content": content})
            return content
        except Exception as e:
            logger.error(f"Middleware completion error: {str(e)}", exc_info=True)
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
                logger.error(f"LLM call failed for chunk {chunk_index}, retry {retries+1}: {str(e)}", exc_info=True)
                raise Exception(f"LLM call failed for chunk {chunk_index}, retry {retries+1}: {str(e)}")
            if self._has_prohibited_summary_marker(output):
                retries += 1
                time.sleep(2 ** retries)
                last_noncompliant_output = output
                prohibited = self._find_prohibited_phrases_in_text(output)
                logger.warning(f"Non-compliant output for chunk {chunk_index}, retry {retries} of {self.MAX_RETRIES_PER_CHUNK}. Markers: {list(prohibited) if prohibited else '-'}")
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

    def _find_prohibited_phrases_in_text(self, text):
        if not text:
            return set()
        return set(match.group(0).lower() for match in self.PROHIBITED_SUMMARY_PATTERN.finditer(text))

    def _collect_chunks(self, initial_response=None, modification_request=None, start_chunk_index=1):
        print("\nProcessing", end="", flush=True)
        found_last_chunk = False
        iteration = 0
        max_iterations = 50  # Increased for larger files
        if initial_response is None:
            # For resume: Request the next chunk with specific index
            next_chunk_prompt = (
                f"Continue from chunk {start_chunk_index}. IMPORTANT: Mark the last chunk with <chunk_n last=\"true\">. "
                "UNDER NO CIRCUMSTANCES may you output summary comments (such as 'unchanged', 'remains the same', 'no change', etc.), "
                "nor omit *any* lines from the file. Output every line, with no summary phrases."
            )
            current_response = self._send_request_with_compliance_retry(next_chunk_prompt, chunk_index=start_chunk_index, is_next_chunk=True)
        else:
            current_response = initial_response
        while not found_last_chunk and iteration < max_iterations:
            iteration += 1
            print(".", end="", flush=True)
            if current_response:
                new_chunks, is_last_chunk = self._parse_chunks(current_response)
                if new_chunks:
                    self.chunks.extend(new_chunks)
                    if modification_request:
                        self._save_checkpoint(self.chunks, len(self.chunks) + 1, modification_request)
                if is_last_chunk:
                    found_last_chunk = True
                    self._assemble_and_save()
                    self._remove_checkpoint()
                    print(f"\nModification complete. Updated {self.source_file}.")
                    return
            if not found_last_chunk:
                try:
                    next_index = len(self.chunks) + 1
                    next_chunk_prompt = (
                        f"Next chunk (chunk {next_index}). IMPORTANT: Mark the last chunk with <chunk_n last=\"true\">. "
                        "UNDER NO CIRCUMSTANCES may you output summary comments (such as 'unchanged', 'remains the same', 'no change', etc.), "
                        "nor omit *any* lines from the file. Output every line, with no summary phrases."
                    )
                    current_response = self._send_request_with_compliance_retry(next_chunk_prompt, chunk_index=next_index, is_next_chunk=True)
                except ValueError as e:
                    if "Non-compliant output at chunk" in str(e):
                        logger.error(f"Non-compliance error: {str(e)}")
                        self._assemble_and_save_partial()
                        return f"Non-compliant output at chunk {len(self.chunks)+1}. Partial results saved."
                    else:
                        logger.error(f"Error in chunk processing: {str(e)}")
                        if self.chunks:
                            self._assemble_and_save_partial()
                        print(f"Code modification completed with partial results.")
                        break
                except Exception as e:
                    logger.error(f"Error requesting next chunk: {str(e)}", exc_info=True)
                    if self.chunks:
                        self._assemble_and_save_partial()
                    print(f"Code modification completed with partial results.")
                    break
        if iteration >= max_iterations and self.chunks:
            print(f"\nReached max iterations ({max_iterations}). Using collected chunks.")
            self._assemble_and_save()

    def _parse_chunks(self, response):
        if not response or not isinstance(response, str):
            logger.error(f"Invalid response for chunk parsing: {type(response)}")
            raise ValueError(f"Invalid response type: {type(response)}. Expected string.")
        chunks = []
        is_last_chunk = False
        matches = re.finditer(r'<chunk_(\d+)(?:\s+last="true")?>(.*?)(?:</chunk_\1>|</chunk_\1\s+last="true">)', response, re.DOTALL)
        for match in matches:
            chunks.append(match.group(2))
            if 'last="true"' in match.group(0):
                is_last_chunk = True
        if not chunks and response.strip() and any(response.strip().startswith(x) for x in ('def ', 'class ', 'import ', '#', 'function ', 'const ')):
            chunks = [response]
            is_last_chunk = True
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
        self.message_history = [{"role": "system", "content": self.system_prompt}]
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


ENGINE=None

def configure_protocol_engine():
    global ENGINE
    ENGINE = ProtocolEngine(
        model=config.MODEL,
        system_prompt="""
        You are an expert software engineer specializing in safe, in-place, large-scale source code modification.

        **Mission:**
        Update source files according to user instructions for high-stakes, auditable, and traceable software environments.

        ---

        **MANDATORY OUTPUT RULES:**

        1. **Chunked Output:**
           - ALWAYS divide your entire output into sequential code chunks, one per response, even for small files.
           - Enclose each in tags formatted as: <chunk_1></chunk_1>, <chunk_2></chunk_2>, etc. 
           - Chunks must NEVER exceed 12,288 tokens and ideally end at logical file boundaries (functions/classes).
           - Output only **one** chunk per response.
           - Tag the last chunk: <chunk_N last="true"> ... </chunk_N>.

        2. **No Summary or Omission:**
           - Output EVERY line of the file, including all changed and unchanged code—in order.
           - NEVER use summary comments, omissions, or statements like 'unchanged', 'rest of the file is unchanged', '# unchanged', etc.

        3. **No Markdown or Output Outside Chunks:**
           - Output PURE code—nothing but chunk tags and code INSIDE them. 
           - Never output markdown formatting (e.g. ```) or explanations outside tags.

        4. **Order & Integrity:**
           - Never change order of imports, functions, classes, or code blocks.
           - Never duplicate code. Do not invent dependencies.

        5. **Retry Behavior:**
           - If the result or "result-hint" from the system says your output failed due to compliance (e.g. forbidden phrases, missing lines, chunk misformatting), **you must immediately retry** as directed—precisely follow the hint and adjust your output for compliance.
           - Do NOT repeat prior mistakes: never ignore system retry advice.

        6. **Responsiveness & Sequencing:**
           - After outputting a chunk, always wait for the explicit “Next chunk” request before sending the next chunk.

        ---

        **EXAMPLE:**
        <chunk_1>
        <all code from start of file up to natural boundary and size limit>
        </chunk_1>
        <chunk_2>
        <next full section (e.g. function/class), strictly sequential code, without omission>
        </chunk_2>
        ...
        <chunk_N last="true">
        <all remaining code, to end of file>
        </chunk_N>

        ---

        **Further Notes:**  
        If the modification request is ambiguous or dangerous, err on the side of safety and preserve original intent. When uncertain, annotate only where absolutely required via unobtrusive code comments.

        **Begin now by producing only the first chunk according to these rules.**
        """,
        middleware=litellm
    )

STARTER_SCRIPT = ""  # Empty or minimal starter code

def stream_code(raw_user_input):
    logger.debug("stream_code called with user input (length: %d)", len(raw_user_input) if raw_user_input else 0)
    parts = raw_user_input.split(":", 1)
    if len(parts) == 1:
        print(f"{red}Streaming code format: <file_name>:<prompt>{reset}")
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

def modify_source_code(source_file: str, modification_request: str) -> str:
    """
    Modifies source code in place with global retry safeguard.
    """
    model=config.MODEL
    logger.debug("modify_source_code called: file=%s, req-length=%d", source_file, len(modification_request) if modification_request else 0)
    ENGINE.reset_state()
    try:
        with open(source_file, 'r') as file:
            logger.debug(f"Reading file {source_file}")
            print(f"{yellow}Modifying file {source_file}{reset}")
            source_content = file.read()
    except FileNotFoundError:
        return f"Unable to open {source_file}. Does not exist."
    except Exception as e:
        logger.error(f"Error reading file {source_file}: {str(e)}")
        return f"Error reading file {source_file}: {str(e)}"
    try:
        modified_script = ENGINE.fetch_modified_script(
            script_content=source_content,
            modification_request=modification_request,
            source_file=source_file
        )
        logger.info(f"Modified {source_file} in place")
        print(f"{yellow}Modified {source_file}{reset}")
        perform_git_diff_file(source_file)
        return modified_script
    except Exception as e:
        logger.error(f"Error in modify_source_code: {str(e)}", exc_info=True)
        raise Exception(f"Failed to modify script: {str(e)}")
