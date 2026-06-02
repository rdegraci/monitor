"""Retrieval-augmented query helpers backed by embedcodeserv.

The :query command runs against the unified embedcodeserv Flask service's
``/analyze`` endpoint — which performs retrieval AND Ollama generation
server-side in a single round trip. The local-Ollama path that previously
lived here (with its own conversation history, prompt templates, and
query-type detection) has been removed; embedcodeserv does that work now.

What remains:
  - query_using_rag(raw_user_input): parses the ``topic[:k]:prompt`` form,
    calls /analyze, renders the response.
  - send_directory_to_indexing_service(directory_path): wraps the ECS
    directory walker for the :index command (kept for back-compat with the
    built-in registration).
"""

import logging
import os

from monitor.lib.colors import blue, red, reset, yellow
from monitor.lib.display_output import highlightMarkdown
from monitor.lib.ecs import embed_directory
from monitor.lib.external_services import (
    _cached_server_info,
    send_analyze_request_to_indexing_service,
)

logger = logging.getLogger(__name__)


# Maximum length of a code preview rendered into the :query terminal output.
# The server returns full chunks (potentially thousands of chars); we trim
# for legibility while keeping the model's `analysis` field in full.
PREVIEW_MAX_CHARS = 600


def send_directory_to_indexing_service(directory_path):
    """Walk a directory and queue each source file for embedding.

    Wraps lib/ecs.embed_directory. ``.`` resolves to the current working
    directory. Files are picked up by FILE_TYPE filter (see lib/ecs.py).
    """
    logger.info("Sending directory to indexing service: %s", directory_path)
    if directory_path == ".":
        embed_directory(os.getcwd())
        return
    embed_directory(directory_path)


def _parse_query_input(raw_user_input):
    """Parse the :query argument into (query_text, comment_top_k, prompt).

    Accepted forms:
      "topic:prompt"             → comment_top_k=None (server default)
      "topic:k=N:prompt"         → comment_top_k=N (use server default unless
                                                     N is a valid int)
    where the first colon-delimited segment is the retrieval query and the
    remaining text is the LLM prompt. Examples:
      "auth flow:explain how login works"        → (auth flow, None, explain...)
      "auth flow:k=0:explain how login works"    → (auth flow, 0,    explain...)

    Returns:
        tuple[str | None, int | None, str | None]: (query_text, comment_top_k,
        prompt). Returns (None, None, None) when the input doesn't include
        the required ``:`` separator.
    """
    if not isinstance(raw_user_input, str) or ":" not in raw_user_input:
        return None, None, None

    parts = raw_user_input.split(":", 2)
    query_text = parts[0].strip()

    # Optional k=N segment after the first colon.
    if len(parts) >= 3 and parts[1].strip().startswith("k="):
        try:
            comment_top_k = int(parts[1].strip()[2:])
            prompt = parts[2].strip()
        except (ValueError, IndexError):
            comment_top_k = None
            # Fallback: rejoin everything after the first colon as the prompt.
            prompt = raw_user_input.split(":", 1)[1].strip()
    else:
        comment_top_k = None
        prompt = raw_user_input.split(":", 1)[1].strip()

    return query_text, comment_top_k, prompt


def _print_query_results(results):
    """Render the retrieved chunks for the user.

    For each result, shows id + symbol + filename + distance, then a
    preview of `commented_code` (top-K results) or `raw_code_full`
    (everything else), truncated for legibility.
    """
    if not results:
        print(f"{yellow}No matching code found.{reset}")
        return

    for i, entry in enumerate(results, start=1):
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id", "<no id>")
        filename = entry.get("filename") or "<no filename>"
        symbol = entry.get("symbol_name") or ""
        chunk_type = entry.get("chunk_type") or ""
        distance = entry.get("distance")

        header_parts = [f"[{i}] {filename}"]
        if symbol:
            header_parts.append(symbol)
        if chunk_type:
            header_parts.append(f"({chunk_type})")
        if isinstance(distance, (int, float)):
            # Lower distance = more similar (cosine). Show 3 decimals.
            header_parts.append(f"distance={distance:.3f}")
        print(f"{blue}{'  '.join(header_parts)}{reset}")
        print(f"  id: {entry_id}")

        # Prefer the LLM-commented version when present (top comment_top_k
        # results carry it). Fall back to raw_code_full.
        body = entry.get("commented_code") or entry.get("raw_code_full") or ""
        if isinstance(body, str) and body.strip():
            preview = body if len(body) <= PREVIEW_MAX_CHARS else (
                body[:PREVIEW_MAX_CHARS] + "...\n[truncated]"
            )
            print(preview)
        print()


def query_using_rag(raw_user_input):
    """Run a retrieval-augmented query against embedcodeserv's /analyze.

    Input format (parsed by _parse_query_input):
        :query <query_text>:<prompt>
        :query <query_text>:k=<N>:<prompt>     # optional comment_top_k

    The server retrieves chunks for ``query_text`` and runs them plus
    ``prompt`` through its Ollama instance, returning ``results`` + an
    ``analysis`` string. This function renders both.

    Args:
        raw_user_input (str): The string after ``:query`` (or pipeline-stripped).
    """
    logger.info("query_using_rag called (input length: %d)",
                len(raw_user_input) if isinstance(raw_user_input, str) else 0)

    query_text, comment_top_k, prompt = _parse_query_input(raw_user_input)
    if not query_text or not prompt:
        print(
            f"{red}Query format: <query_text>:<prompt>"
            f"  (optionally <query_text>:k=N:<prompt> to override comment_top_k){reset}"
        )
        print(f"{red}Example: :query auth flow:explain how login works{reset}")
        logger.warning("Invalid :query input format: %r", raw_user_input)
        return

    # Surface which project's vector DB we're querying so the user can
    # spot mismatches (e.g., querying with the server set to EMBED_PROJECT=
    # swift while expecting Python results). Best-effort: silent when the
    # server is unreachable or doesn't return active_project.
    info = _cached_server_info()
    if isinstance(info, dict):
        active_project = info.get("active_project")
        active_language = info.get("active_language")
        if active_project or active_language:
            print(
                f"{yellow}Querying embedcodeserv "
                f"(project={active_project!r}, language={active_language!r}){reset}"
            )

    # The server's /analyze handles retrieval + LLM generation in one call.
    # comment_top_k applies to the retrieval-results post-processing (how
    # many of the top results get LLM-commented). Server default is 3.
    response = send_analyze_request_to_indexing_service(query_text, prompt)
    if response is None:
        print(
            f"{red}embedcodeserv /analyze failed. Check that the service is "
            f"reachable at the configured EMBEDCODESERV_HOST/PORT and that the "
            f"correct project is active (run with EMBED_PROJECT env var).{reset}"
        )
        return

    results = response.get("results", []) if isinstance(response, dict) else []
    analysis = response.get("analysis", "") if isinstance(response, dict) else ""

    if comment_top_k == 0:
        # User asked for no commenting; remind them they're seeing raw code.
        logger.debug("comment_top_k=0 honored — results show raw_code_full only")

    _print_query_results(results)

    if analysis:
        print(f"{yellow}--- Analysis ---{reset}")
        try:
            highlightMarkdown(analysis)
        except Exception as e:
            logger.error("Failed to render analysis markdown: %s", e, exc_info=True)
            print(analysis)
    else:
        print(f"{yellow}(No analysis returned.){reset}")
