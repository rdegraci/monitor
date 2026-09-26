"""Jev Score reorder for code-search top-K blocks after lexical shortlist."""

from __future__ import annotations

import logging
from typing import List

from monitor.lib import typesafe_client as tc
from monitor.lib.search_rank import score_block, split_rg_output_blocks, strip_ansi

logger = logging.getLogger(__name__)

TOP_K = 10
QUESTION_PREFIX = "blk_"


def rerank_rg_output_with_jev(stdout: str, query: str, *, top_k: int = TOP_K) -> str:
    """Lexical rerank first, then optionally Score the top-K with Jev.

    Soft-fail returns the lexical ranking unchanged.
    """
    from monitor.lib.search_rank import rerank_rg_output

    lexically = rerank_rg_output(stdout, query)
    if not tc.is_enabled() or not lexically or not query:
        return lexically

    blocks = split_rg_output_blocks(lexically)
    if len(blocks) <= 1:
        return lexically

    head = blocks[:top_k]
    tail = blocks[top_k:]

    questions = {}
    for i, block in enumerate(head):
        qid = f"{QUESTION_PREFIX}{i}"
        snippet = strip_ansi(block)[:1200]
        questions[qid] = {
            "type": "score",
            "instructions": {
                "query": query[:500],
                "snippet": snippet,
                "question": (
                    "How relevant is `snippet` to answering `query` in a "
                    "codebase search?"
                ),
            },
            "criteria": [
                "Irrelevant",
                "Weakly related",
                "Useful",
                "Highly relevant hit",
            ],
        }

    response = tc.system_one({"query": query[:500]}, questions)
    if not response:
        return lexically

    scored: List[tuple[float, int, str]] = []
    floor = tc.confidence_floor()
    any_acted = False
    for i, block in enumerate(head):
        qid = f"{QUESTION_PREFIX}{i}"
        answer = tc.score_answer(response, qid)
        if not answer:
            scored.append((score_block(block, query), i, block))
            continue
        try:
            conf = (
                float(answer["confidence"])
                if answer.get("confidence") is not None
                else None
            )
            val = float(answer.get("score"))
        except (TypeError, ValueError):
            scored.append((score_block(block, query), i, block))
            continue
        if conf is None or conf < floor:
            scored.append((score_block(block, query), i, block))
            continue
        any_acted = True
        scored.append((val, i, block))

    if not any_acted:
        return lexically

    scored.sort(key=lambda t: (t[0], -t[1]), reverse=True)
    ordered = [b for _s, _i, b in scored] + tail
    joined = "".join(ordered)
    if lexically.endswith("\n") and not joined.endswith("\n"):
        joined += "\n"
    logger.info("Jev search rerank acted on top-%d of %d blocks", len(head), len(blocks))
    return joined
