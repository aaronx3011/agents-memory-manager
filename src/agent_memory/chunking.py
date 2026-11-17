"""Deterministic, tokenizer-aware passage splitting. No LLM or network involved."""

import re

MAX_TEXT_TOKENS = 240
OVERLAP_TOKENS = 32
FALLBACK_CHARS_PER_TOKEN = 4
OVERLAP_WORDS = 8

_PARAGRAPH = re.compile(r"\n{2,}")


def fallback_counts(texts):
    """Deterministic heuristic when the tokenizer is unavailable (model loading failed)."""
    return [max(1, len(text) // FALLBACK_CHARS_PER_TOKEN) for text in texts]


def build_passages(count_fn, content, max_tokens=MAX_TEXT_TOKENS, overlap_tokens=OVERLAP_TOKENS):
    """Split content into overlapping passages whose token budgets include "
    "special tokens. Small final tails stay as their own passage rather than "
    "pushing a merge past the model's truncation window. Returns (text, "
    "token_count) tuples in order; counts use the same tokenizer as embedding."""
    if not content.strip():
        return []
    passages, current, current_tokens = [], [], 0
    carry = []
    carry_tokens = 0

    def flush():
        nonlocal current, current_tokens, carry, carry_tokens
        if current:
            text = "\n\n".join(current)
            passages.append((text, count_fn([text])[0]))
            carry, carry_tokens = [], 0
            for block in reversed(current):
                block_tokens = count_fn([block])[0]
                if carry_tokens + block_tokens <= overlap_tokens:
                    carry.insert(0, block)
                    carry_tokens += block_tokens
                else:
                    break
        current, current_tokens = list(carry), carry_tokens

    for raw in _PARAGRAPH.split(content):
        block = raw.strip()
        if not block:
            continue
        block_tokens = count_fn([block])[0]
        if block_tokens > max_tokens:
            if current:
                flush()
            for piece in hard_split(count_fn, block, max_tokens, overlap_tokens):
                passages.append((piece, count_fn([piece])[0]))
            carry, carry_tokens = [], 0
            current, current_tokens = [], 0
            continue
        if current_tokens and current_tokens + block_tokens > max_tokens:
            flush()
        current.append(block)
        current_tokens += block_tokens
    flush()
    return [(text, count) for text, count in passages if text.strip()]


def hard_split(count_fn, block, max_tokens, overlap_tokens):
    """Word-greedy split of an oversized block. A single word longer than the "
    "budget is kept verbatim rather than dropped."""
    words = block.split()
    pieces, start = [], 0
    while start < len(words):
        end = start
        while end < len(words):
            candidate = " ".join(words[start:end + 1])
            tokens = count_fn([candidate])[0]
            if tokens > max_tokens and end > start:
                break
            end += 1
        if end > start:
            pieces.append(" ".join(words[start:end]))
            if end >= len(words):
                start = end
            else:
                # Overlap back-off must always strictly advance start, even in
                # the final short window, or the piece would replay forever.
                back = min(end - 1, end - OVERLAP_WORDS) if overlap_tokens else end
                start = max(start + 1, back)
        else:
            pieces.append(words[start])
            start += 1
    return pieces
