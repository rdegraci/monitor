#!/usr/bin/env python3
"""
rlm.py

Simple Recursive Language Model (RLM) CLI agent example.

This script demonstrates the RLM inference strategy:
- chunk a long document
- recursively process chunks via an LLM client
- aggregate partial outputs into a final answer

Replace MockLLMClient with a real client that calls ChatGPT-5.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import time
from typing import Dict, List, Optional, Tuple


class LLMClient:
    """Abstract interface for an LLM client.

    Implementations should provide a concrete `call` method that returns the
    model's text output for a given prompt.
    """

    def call(self, prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
        """Call the LLM with the given prompt.

        Args:
            prompt: Prompt to send to the model.
            max_tokens: Max tokens to receive in response.
            temperature: Sampling temperature.

        Returns:
            The model's text output.
        """
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Mock LLM client for offline testing.

    This client returns deterministic, synthetic outputs useful for unit tests
    and development without contacting a remote API.
    """

    def call(self, prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
        """Produce deterministic mock responses for common prompt patterns.

        Args:
            prompt: The prompt text sent to the model.
            max_tokens: Max tokens to generate (ignored by mock).
            temperature: Sampling temperature (ignored by mock).

        Returns:
            A synthetic text response based on simple heuristics.
        """
        prompt_short = prompt.strip()[:200].lower()
        if "plan" in prompt_short or "split" in prompt_short or "chunk" in prompt_short:
            return json.dumps({"strategy": "simple_chunk", "chunk_size_words": 300})
        if "summarize chunk" in prompt_short or "summarize the following" in prompt_short:
            summary = "Summary: " + " ".join(prompt.split()[:20]) + "..."
            return summary
        if "combine partials" in prompt_short or "synthesize" in prompt_short:
            if "PARTIALS_START" in prompt:
                partials = prompt.split("PARTIALS_START", 1)[1]
                lines = [l.strip() for l in partials.splitlines() if l.strip()]
                combined = "Combined result:\n" + " ".join(lines[:6]) + "..."
                return combined
            return "Combined (mock) result."
        return "Mock response: " + " ".join(prompt.split()[:30]) + "..."


def chunk_text_by_words(text: str, chunk_size_words: int, overlap_words: int = 0) -> List[str]:
    """Split text into chunks by words with optional overlap.

    Args:
        text: The input document.
        chunk_size_words: Maximum words per chunk.
        overlap_words: Number of overlapping words between consecutive chunks.

    Returns:
        A list of text chunks.
    """
    words = text.split()
    if chunk_size_words <= 0 or chunk_size_words >= len(words):
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size_words, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start = end - overlap_words
    return chunks


def stable_hash(text: str) -> str:
    """Return a stable SHA256 hex digest for the given text.

    Args:
        text: Input string to hash.

    Returns:
        Hexadecimal SHA256 digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RecursiveLanguageModelAgent:
    """Controller that implements the recursive strategy over a long document.

    The agent splits large documents into chunks, processes each chunk (possibly
    recursively), and composes partial outputs into a final answer.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        chunk_size_words: int = 400,
        overlap_words: int = 40,
        max_depth: int = 3,
        parallelism: int = 4,
    ) -> None:
        """Initialize the agent.

        Args:
            llm_client: An implementation of LLMClient for making LLM calls.
            chunk_size_words: Target chunk size in words.
            overlap_words: Overlap between consecutive chunks in words.
            max_depth: Maximum recursion depth.
            parallelism: How many chunks to process concurrently.
        """
        self.llm = llm_client
        self.chunk_size_words = chunk_size_words
        self.overlap_words = overlap_words
        self.max_depth = max_depth
        self.parallelism = parallelism
        self.cache: Dict[str, str] = {}

    def _cached_call(self, key: str, prompt: str, max_tokens: int = 512) -> str:
        """Call the LLM with caching based on a key derived from prompt and params.

        Args:
            key: Cache key for this request.
            prompt: Prompt to send to the LLM.
            max_tokens: Max tokens to request (forwarded to client).

        Returns:
            The LLM response text (from cache if available).
        """
        if key in self.cache:
            return self.cache[key]
        resp = self.llm.call(prompt, max_tokens=max_tokens)
        self.cache[key] = resp
        return resp

    def _call_on_chunk(self, chunk_text: str, task: str) -> str:
        """Call the LLM to handle a single chunk for the specified task.

        Args:
            chunk_text: Text chunk to process.
            task: The user task (e.g., 'summarize', 'answer question').

        Returns:
            LLM text output for the chunk.
        """
        prompt = (
            f"You are given the following snippet of a larger document.\n"
            f"Task: {task}\n\n"
            f"--- SNIPPET START ---\n{chunk_text}\n--- SNIPPET END ---\n\n"
            f"Please produce a concise response grounded in the snippet."
        )
        key = stable_hash(task + "|" + chunk_text)[:16]
        return self._cached_call(key, prompt)

    def _compose_partials(self, partials: List[Tuple[int, str]], task: str) -> str:
        """Compose partial results into a final answer via the LLM.

        Args:
            partials: Sequence of (index, partial_text).
            task: The original user task.

        Returns:
            Final synthesized answer.
        """
        partials_sorted = sorted(partials, key=lambda p: p[0])
        partials_text = "\n\n".join(f"[CHUNK {i}]\n{txt}" for i, txt in partials_sorted)
        prompt = (
            f"Combine partials to complete this task: {task}\n\n"
            f"PARTIALS_START\n{partials_text}\nPARTIALS_END\n\n"
            f"Please produce a final answer that cites which partials support each claim."
        )
        key = stable_hash(task + "|compose|" + partials_text)[:24]
        return self._cached_call(key, prompt)

    def process_document(self, text: str, task: str) -> str:
        """Process a document recursively to perform the given task.

        If the document is larger than the chunk size it will be split, subresults
        computed, and then combined. The process recurses until chunks are at-most
        chunk_size_words or max_depth is reached.

        Args:
            text: Full document text.
            task: Task description for the model.

        Returns:
            Final output text for the task.
        """
        return self._process_document_recursive(text, task, depth=0)

    def _process_document_recursive(self, text: str, task: str, depth: int) -> str:
        """Internal recursive routine.

        Args:
            text: The text to process at this recursion level.
            task: The task description.
            depth: Current recursion depth.

        Returns:
            The processed text (either a direct LLM response or a composed result).
        """
        words = text.split()
        if depth >= self.max_depth or len(words) <= self.chunk_size_words:
            return self._call_on_chunk(text, task)

        chunks = chunk_text_by_words(text, self.chunk_size_words, self.overlap_words)

        partials: List[Tuple[int, str]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallelism) as exc:
            futures = {}
            for i, chunk in enumerate(chunks):
                futures[exc.submit(self._process_document_recursive, chunk, task, depth + 1)] = i
            for fut in concurrent.futures.as_completed(futures):
                idx = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:  # pragma: no cover - defensive
                    result = f"ERROR on chunk {idx}: {e}"
                partials.append((idx, result))

        combined = self._compose_partials(partials, task)
        return combined


def main() -> None:
    """CLI entrypoint for running the RLM agent on a file.

    Command-line arguments:
        --file / -f: Path to input file.
        --task / -t: Task to perform on the file.
        --chunk: Chunk size in words.
        --overlap: Overlap words between chunks.
    """
    parser = argparse.ArgumentParser(description="Recursive Language Model CLI example.")
    parser.add_argument("--file", "-f", required=True, help="Path to input file.")
    parser.add_argument("--task", "-t", required=True, help="Task to perform (e.g., 'Summarize').")
    parser.add_argument("--chunk", type=int, default=400, help="Chunk size in words.")
    parser.add_argument("--overlap", type=int, default=40, help="Overlap words between chunks.")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        raise SystemExit(f"File not found: {args.file}")

    with open(args.file, "r", encoding="utf-8") as fh:
        text = fh.read()

    llm = MockLLMClient()
    agent = RecursiveLanguageModelAgent(
        llm_client=llm,
        chunk_size_words=args.chunk,
        overlap_words=args.overlap,
        max_depth=3,
        parallelism=4,
    )

    start = time.time()
    result = agent.process_document(text, args.task)
    elapsed = time.time() - start
    print("=== FINAL RESULT ===")
    print(result)
    print("---")
    print(f"Elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
