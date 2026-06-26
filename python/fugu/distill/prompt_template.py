"""Shared pairwise-judge prompt for training and eval (must be identical on both sides).

Gemma-2 chat templates support only user/model turns (no system role), so the judging
instruction lives in the user turn. The target is a single letter so a small model can both
learn and emit it reliably, and parsing is trivial.
"""

from __future__ import annotations

import re

JUDGE_INSTRUCTION = (
    "You are a strict, impartial judge. Read the question and the two candidate responses, then "
    "decide which response is more correct and complete.\n\n"
    "Question:\n{q}\n\n"
    "[Response A]\n{a}\n\n"
    "[Response B]\n{b}\n\n"
    "Reply with ONLY a single letter — A or B — for the better response."
)


def user_content(question: str, resp_a: str, resp_b: str) -> str:
    return JUDGE_INSTRUCTION.format(q=question, a=resp_a, b=resp_b)


def train_messages(question: str, resp_a: str, resp_b: str, gold: str) -> list[dict]:
    return [
        {"role": "user", "content": user_content(question, resp_a, resp_b)},
        {"role": "assistant", "content": gold},
    ]


def eval_messages(question: str, resp_a: str, resp_b: str) -> list[dict]:
    return [{"role": "user", "content": user_content(question, resp_a, resp_b)}]


def parse_letter(text: str) -> str | None:
    """First standalone A/B in the model's output."""
    m = re.search(r"\b([AB])\b", text.strip().upper())
    return m.group(1) if m else None


# Gemma-2-it assistant turn marker — used for completion-only loss masking.
RESPONSE_TEMPLATE = "<start_of_turn>model\n"
