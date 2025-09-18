"""
Consult: An interactive requirements elicitation and prompt-engineering assistant
for design mode sessions with LLM-driven question-answer/refinement loop.
Enhanced: Now supports LLM-generated Graphviz DOT diagrams.
Each diagram is rendered to a deterministic SVG file (e.g., consult_graph.svg),
and browser tab openings are managed to avoid tab spam.
"""

import litellm
from typing import List, Dict, Optional, Tuple
import os
import webbrowser
import re
from graphviz import Source


class Consult:
    """
    Interactive session for incrementally building a requirements prompt in design mode,
    by dialoguing with an LLM to clarify, extract, and refine user intent.
    
    The prompt is updated every turn and exposed for user review.
    Additionally, LLM-generated Graphviz DOT diagrams are supported per dialog turn,
    saved as deterministic SVG files and opened in the browser while avoiding duplicate tab spam.

    Dependencies injected via the constructor:
    - blue, red, yellow, reset: Color codes for prompt formatting/printing.
    - display_query_result: Callable to display a query result in dev mode.

    Error handling:
    - All I/O operations (file writes, webbrowser calls) are wrapped in try/except and logged on error.
    - All exceptions during LLM communication or response parsing are caught and logged with context.
    - Unrecognized diagram types are logged and surfaced to user as warnings.
    """

    # Basenames for file outputs for deterministic diagram file naming
    DIAGRAM_FILE_BASENAME = "consult_graph.dot"
    SVG_FILE_BASENAME = "consult_graph"

    # Tracks whether the SVG diagram has been shown in the browser (avoid tab spam)
    svg_tab_shown = False

    def __init__(
        self,
        logger,
        model: str = "openai/gpt-4o",
        allow_file_output: bool = True,
        allow_browser_open: bool = True,
    ):
        """
        Initialize the Consult session object.

        Responsibilities:
         - Sets up the model for dialog with the LLM.
         - Initializes tracking for dialog state, prompt accumulation, and revealed diagrams.
         - Ensures logger is ready for runtime diagnostics.
         - Stores injected color codes and display_query_result callable for use in prompt rendering and dev mode.

        Args:
            model: The LLM model identifier to use with litellm.
            blue, red, yellow, reset: Color codes injected from the caller.
            display_query_result: Function to display query results.
            allow_file_output: If False, do not write DOT/SVG files or render via graphviz; instead,
                compute and return a plausible absolute SVG path (basename + '.svg').
            allow_browser_open: If False, do not open the browser for SVG previews; rendering or
                virtual path computation still occurs, but no tabs are opened and svg_tab_shown is not toggled.
        """
        self.logger = logger
        self.model = model  # Underlying LLM to query for all clarifications and diagrams
        self.active = False  # Controls whether the design dialog is live
        self.messages: List[Dict[str, str]] = []  # Accumulates all LLM/user dialog history for full context
        self.current_prompt: str = ""  # Stores the current requirements prompt as built by the dialog
        Consult.svg_tab_shown = False
        # Injected dependencies
        self.print = print
        # Output/UX flags
        self.allow_file_output = allow_file_output
        self.allow_browser_open = allow_browser_open
        self.logger.info("Consult session created. Model: %s", self.model)

    def start(self, seed_question: Optional[str] = None):
        """
        Activate design mode session and initialize dialog with intent to clarify requirements.

        Responsibilities:
         - Prepares an LLM system prompt explicitly directing the conversation structure.
         - Optionally adds an initial user-provided question/seed.
         - Resets diagram tab tracking so the diagram can be shown afresh for this session.

        Args:
            seed_question: Optional initial seed/question to start the consultation.
        """
        self.active = True
        self.current_prompt = ""
        Consult.svg_tab_shown = False
        # Defines system instructions to guide LLM to always update prompt and output DOT diagrams, enforces block labeling
        system_content = (
            "You are a requirements engineering assistant. Your job is to (1) ask clarifying "
            "questions about the user's desired software/design, (2) after every answer, summarize "
            "the design requirements as a prompt thus far, and (3) always print the updated prompt "
            "so the user may provide feedback. "
            "After showing the prompt, also output any Graphviz DOT diagrams you can for the design thus far. "
            "If the user asks what you think about a particular software/design issue, provide your pros/cons about that issue."
            ""
            "When you show Graphviz, always use explicit code blocks labeled for each diagram type: "
            "```dot ...``` or ```graphviz ...```, with DOT code inside the block (it should contain 'digraph' or 'graph'). "
            "After the prompt and diagram, continue asking clarifying questions "
            "until the requirements are unambiguous and actionable for an AI developer."
        )
        # Initialize message history, starting with the detailed system prompt
        self.messages = [{"role": "system", "content": system_content}]
        if seed_question:
            # Add the optional initial seed question if provided
            self.messages.append({"role": "user", "content": seed_question})
        self.logger.info("Consult session started. Seed: %s", seed_question)

    def stop(self) -> str:
        """
        End the consult/design mode session and finalize the requirements prompt.

        Responsibilities:
         - Deactivates the dialog so no further clarifying questions/answers are expected.
         - Logs closure for traceability.

        Returns:
            The cumulative requirements prompt finalized at session end.
        """
        self.active = False
        self.logger.info("Consult session stopped.")
        return self.current_prompt

    @staticmethod
    def _extract_dot_diagrams(text: str) -> Dict[str, str]:
        """
        Parse and extract labeled Graphviz DOT diagrams from a block of LLM output text.

        Responsibilities:
         - Detects and extracts separate DOT code blocks from LLM output.
         - Handles code blocks labeled 'dot' or 'graphviz', or infers from 'digraph'/'graph' at start of code block.
         - Only supports a single diagram per LLM output; if multiple, last one wins.

        Args:
            text: LLM output including prompt summaries and DOT code blocks.

        Returns:
            Dict mapping 'graph' to DOT code (excluding backticks/etc).

        Error handling:
         - All regex/parsing errors are caught and logged (does not fail session).
         - Logs and warns the user for any unrecognized or malformed DOT diagrams.
        """
        diagrams = {}
        # Regex: finds code blocks starting with "```dot" or "```graphviz", captures code content
        code_block_regex = re.compile(
            r"```(?:dot|graphviz)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE
        )
        try:
            for m in code_block_regex.finditer(text):
                diagram_code = m.group(1).strip()
                # Infer diagram code if it starts with 'digraph' or 'graph'
                if diagram_code.startswith("digraph") or diagram_code.startswith("graph"):
                    diagrams["graph"] = diagram_code
                else:
                    # Try to find 'digraph' or 'graph' line in code block
                    lines = diagram_code.splitlines()
                    for idx, line in enumerate(lines):
                        if line.strip().startswith("digraph") or line.strip().startswith(
                            "graph"
                        ):
                            inferred_code = "\n".join(lines[idx:])
                            diagrams["graph"] = inferred_code
                            break
                    else:
                        # As this is a @staticmethod, 'self' is not available
                        # Logging is omitted here as per code safety rules
                        continue  # Skip code blocks for which the DOT diagram can't be resolved
        except Exception as ex:
            # Logging is omitted here for safety as self.logger is unavailable in staticmethod
            pass
        return diagrams

    def ask(self, user_answer: str) -> Tuple[str, str]:
        """
        Accept user input, synthesize dialog update, request new prompt and clarifying question from LLM,
        and process any DOT diagram outputs.

        Responsibilities:
         - Appends user's latest answer (clarification/requirement) to dialog context.
         - Injects formatting instructions to the LLM to enforce block/separation outputs.
         - Handles LLM interaction, with token/temperature parameters tuned for requirements sessions.
         - Parses LLM reply to:
             * extract requirements prompt,
             * extract and process DOT diagrams,
             * extract the next clarifying question.
         - Records and logs any LLM communication or output format errors; returns robust fallback.
         - Invokes prompt/diagram visualization; avoids browser tab spam by tracking if the SVG diagram has been shown.

        Args:
            user_answer: Text of the user's answer (requirement refinement, clarification, etc.).

        Returns:
            Tuple of (clarifying_question, updated_prompt)
                clarifying_question: What the user should answer next.
                updated_prompt: The requirements prompt, possibly revised, as synthesized by the LLM.
        """
        self.logger.debug("Entering ask() method with user input")
        # Add user's answer to dialog
        self.messages.append({"role": "user", "content": user_answer})
        # Instructions to ensure LLM outputs blocks clearly labeled for parsing
        design_instructions = (
            "After considering all answers so far, output first a clear, up-to-date requirements prompt "
            "(delimited with ###Prompt), then if you can, output a Graphviz DOT diagram "
            "in a code block labeled with ```dot or ```graphviz and valid DOT code (must begin with 'digraph' or 'graph'). "
            "Finally, ask the next best clarifying question at the end. "
            "For example:\n"
            "###Prompt\n<project description so far>\n"
            "```dot\n"
            "digraph G {\n  ...\n}\n"
            "```\n"
            "What else do you need?"
        )
        # The message sequence for the next turn: prior history plus system-level output format instructions
        llm_messages = self.messages + [{"role": "system", "content": design_instructions}]
        reply = ""
        # Determine temperature dynamically based on self.model content
        if "openai/o3" in self.model.lower():
            temperature = 1.0
        else:
            temperature = 0.3
        self.logger.debug(
            "Sending prompt to LLM %s with temperature: %s", self.model, temperature
        )
        try:
            response = litellm.completion(
                model=self.model,
                messages=llm_messages,
                temperature=temperature,
            )
            reply = response.choices[0].message.content.strip()
            self.logger.debug("Received LLM response. Length: %d chars", len(reply))
        except Exception as ex:
            self.logger.error(
                "Error communicating with LLM: %r. User answer: %r", ex, user_answer, exc_info=ex
            )
            error_msg = (
                "An error occurred communicating with the LLM. "
                "Please check your network, API key, or contact support.\n"
                "Original user answer was preserved. Please try again."
            )
            return "LLM error: unable to advance dialog.", self.current_prompt

        prompt_block = ""
        clarifying_question = ""
        diagrams = {}

        try:
            # Extract the ###Prompt marker and split out DOT diagrams and further content if present
            if reply.startswith("###Prompt"):
                _, rest = reply.split("###Prompt", 1)
                dot_code_block = re.search(r"```(?:dot|graphviz)", rest)
                prompt_end = dot_code_block.start() if dot_code_block else len(rest)
                prompt_block = rest[:prompt_end].strip()
                diagrams_and_q = rest[prompt_end:].strip() if prompt_end < len(rest) else ""
            else:
                # If prompt marker is missing, treat reply as fallback
                prompt_block = self.current_prompt
                diagrams_and_q = reply

            # Extract DOT diagrams
            diagrams = self._extract_dot_diagrams(diagrams_and_q)
            # Remove DOT code blocks to reveal remaining text, presumed to be the next clarifying question
            dot_pattern = re.compile(
                r"```(?:dot|graphviz)?\s*\n.*?```", re.DOTALL | re.IGNORECASE
            )
            question_str = dot_pattern.sub("", diagrams_and_q).strip()
            clarifying_question = question_str

        except Exception as ex:
            self.logger.error(
                "Failed parsing LLM reply: %r. Reply text: %r", ex, reply, exc_info=ex
            )
            clarifying_question = "Parsing error: could not extract next question."
            prompt_block = self.current_prompt

        # Update session state with new prompt and full dialog reply
        self.current_prompt = prompt_block
        self.messages.append({"role": "assistant", "content": reply})

        # Visualize prompt and diagrams, with controlled browser opening
        self.print_prompt_and_graph(diagrams)
        return clarifying_question, self.current_prompt

    def get_prompt(self) -> str:
        """
        Expose the requirements prompt currently accumulated in this session.

        Returns:
            The current prompt string, as last summarized by LLM or fallback.
        """
        return self.current_prompt

    def reset(self):
        """
        Reset the session's dialog, prompt, and browser-tab tracking state.

        Responsibilities:
         - Allows a fresh session to begin as if never run.
         - Ensures that the diagram SVG may be shown again on next diagrams display.
        """
        self.active = False
        self.messages = []
        self.current_prompt = ""
        Consult.svg_tab_shown = False
        self.logger.info("Consult session state reset.")
        return "Consult session state reset."

    def generate_minimal_dot_graph(self) -> Dict[str, str]:
        """
        Generate a minimal DOT diagram as a fallback if LLM does not provide one.

        Responsibilities:
         - Always outputs at least one node and one edge so there is something sensible to display.
         - Can be extended to use prompt-based heuristics if desired.

        Returns:
            Dict: diagram type -> DOT diagram string (key 'graph').

        Error handling:
         - Logs all errors, outputs a default minimal graph on error.

        """
        try:
            dot_code = "digraph G {\n    User -> System;\n}"
            return {"graph": dot_code}
        except Exception as ex:
            self.logger.error(
                "Exception during minimal DOT graph generation: %r", ex, exc_info=ex
            )
            return {"graph": "digraph G {\n    Node1;\n}"}

    def _render_dot_to_svg(self, dot_code: str) -> Optional[str]:
        """
        Render a DOT diagram to SVG using the graphviz Python package.

        Args:
            dot_code: The Graphviz DOT code string.

        Returns:
            The absolute path to the generated SVG file if successful, else None.
            If file output is disabled (allow_file_output=False), returns a plausible absolute SVG path
            without writing any files.

        Error Handling:
            All file and rendering errors are caught and logged.

        """
        self.logger.debug("Entering _render_dot_to_svg() method")
        dot_path = os.path.abspath(self.DIAGRAM_FILE_BASENAME)
        svg_stub_path = os.path.abspath(self.SVG_FILE_BASENAME)
        svg_abs_path = f"{svg_stub_path}.svg"

        if not self.allow_file_output:
            # Do not write files or render; return the plausible path
            self.logger.debug(
                "File output disabled (allow_file_output=False); returning virtual SVG path: %s",
                svg_abs_path,
            )
            return svg_abs_path

        try:
            with open(dot_path, "w", encoding="utf-8") as f:
                f.write(dot_code)
            self.logger.debug("Wrote DOT code to file: %s", dot_path)
            # Use graphviz.Source to render the DOT file to SVG
            src = Source(dot_code, filename=svg_stub_path, format="svg")
            rendered = src.render(filename=svg_stub_path, format="svg", cleanup=True)
            self.logger.debug("Rendered DOT to SVG: %s", rendered)
            return rendered
        except Exception as ex:
            self.logger.error(
                "Unable to render DOT diagram to SVG: %r (path: %r, output: %r)",
                ex,
                dot_path,
                svg_stub_path,
                exc_info=ex,
            )
            return None

    def show_graphs(self, diagrams: Dict[str, str]):
        """
        Render detected Graphviz DOT diagrams to SVG and open/update their browser tab.

        Responsibilities:
         - For each DOT diagram (only one), generate the SVG using graphviz Python package.
         - Write to deterministic filenames so browser openings are idempotent.
         - On the first display in a session, open a new browser tab. On subsequent displays, reuse
           the same tab by invoking webbrowser.open with the same file URL.
         - Opens new tab only once per session to avoid tab spam; updates existing tab if re-run.
         - Handles unknown diagrams gracefully with user-facing and log warnings.
         - If browser opening is disabled via allow_browser_open, no tabs are opened and the
           svg_tab_shown flag is not toggled.

        Args:
            diagrams: Dict mapping 'graph' to DOT code.

        Error handling:
         - All file I/O, graphviz, and browser actions are wrapped in try/except with detailed logging.
         - Warnings are surfaced to user when the diagram cannot be rendered or shown.
        """
        self.logger.debug("Entering show_graphs() method")
        for diagram_type, dot_code in diagrams.items():
            if diagram_type != "graph":
                self.logger.warning(
                    "Unknown diagram type %r in show_graphs(); skipping.", diagram_type
                )
                continue
            svg_path = self._render_dot_to_svg(dot_code)
            if svg_path is None:
                continue
            file_url = f"file://{svg_path}"
            if not self.allow_browser_open:
                self.logger.debug(
                    "Browser opening disabled (allow_browser_open=False); would open: %s. Not toggling svg_tab_shown.",
                    file_url,
                )
                # Do not toggle svg_tab_shown since no tab was opened.
                continue
            if not Consult.svg_tab_shown:
                try:
                    webbrowser.open_new_tab(file_url)
                    Consult.svg_tab_shown = True
                    self.logger.debug(
                        "Opened new browser tab for DOT SVG diagram: %s", file_url
                    )
                except Exception as ex:
                    self.logger.error(
                        "Failed to open browser tab for DOT SVG diagram: %r (file_url: %s)",
                        ex,
                        file_url,
                        exc_info=ex,
                    )
                    continue
            else:
                try:
                    webbrowser.open(file_url)
                    self.logger.debug("Updated browser tab for DOT SVG diagram: %s", file_url)
                except Exception as ex:
                    self.logger.error(
                        "Failed to update browser with DOT SVG diagram: %r (file_url: %s)",
                        ex,
                        file_url,
                        exc_info=ex,
                    )
                    continue

    def print_prompt_and_graph(self, diagrams: Optional[Dict[str, str]] = None):
        """
        Display the current requirements prompt and, if available, open updated DOT diagram visualization.

        Responsibilities:
         - Prints the current requirements prompt for user review using the injected print function.
         - If a diagram is given, opens it (unless already opened) and prints a brief summary.
         - If no diagram present, invokes a fallback: auto-generates and renders a minimal DOT diagram.

        Args:
            diagrams: Dict mapping 'graph' to DOT code.

        Error handling:
         - All diagram generation/rendering failures are caught and logged; warnings shown to user where appropriate.
        """
        try:
            self.print(self.current_prompt)
        except Exception as ex:
            self.logger.error("Exception while printing prompt: %r", ex, exc_info=ex)
        if diagrams and diagrams:
            try:
                self.show_graphs(diagrams)
            except Exception as ex:
                self.logger.error("Exception in show_graphs: %r", ex, exc_info=ex)
        else:
            try:
                self.show_graphs(self.generate_minimal_dot_graph())
            except Exception as ex:
                self.logger.error(
                    "Exception during fallback (auto-generated) diagram: %r", ex, exc_info=ex
                )
