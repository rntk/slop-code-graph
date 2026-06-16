"""Port of ext/worker/topic_parser.js (text mode only) + RepairingGapHandler
(deterministic coverage repair) + AdjacentSameTopicJoiner.

Robustness contract (matches the Python txt_splitt library, not split_text.py's
specific handler choice): the parser is permissive -- it CLAMPS ranges to
[0, sentence_count-1] and never rejects the response for duplicate, missing, or
out-of-range markers. A separate deterministic repair step then trims overlaps
(first-claim-wins) and fills gaps by extending adjacent ranges, guaranteeing
continuous [0, sentence_count-1] coverage without any extra LLM calls. The only
remaining hard failure is a response with no parseable topic ranges at all,
which still raises TopicParseError so the orchestrator can retry.

This is a faithful, deterministic port: no LLM calls, no network.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

TOPIC_LINE_RE = re.compile(r"^(.+):\s*(\d[\d\s,-]*)\s*$")
RANGE_TOKEN_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
SINGLE_TOKEN_RE = re.compile(r"^(\d+)$")


class TopicParseError(Exception):
    """Thrown when the LLM response contains no parseable topic ranges at all."""

    def __init__(self, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics: dict = diagnostics if diagnostics is not None else {}


def normalize_label_parts(parts: list[str]) -> list[str]:
    out: list[str] = []
    for raw in parts:
        part = raw.strip()
        if not part:
            continue
        for sub in part.split(":"):
            s = sub.strip()
            if s:
                out.append(s)
    return out


def normalize_label_key(label: list[str]) -> str:
    pieces = []
    for p in label:
        s = unicodedata.normalize("NFKC", p).strip().casefold()
        s = re.sub(r"\s+", " ", s)
        pieces.append(s)
    return "|".join(pieces)


def parse_range_string(s: str) -> dict[str, Any]:
    results: list[tuple[int, int]] = []
    invalid_count = 0
    for part_raw in s.split(","):
        part = part_raw.strip()
        if not part:
            continue
        range_match = RANGE_TOKEN_RE.match(part)
        if range_match:
            results.append((int(range_match.group(1)), int(range_match.group(2))))
            continue
        single_match = SINGLE_TOKEN_RE.match(part)
        if single_match:
            n = int(single_match.group(1))
            results.append((n, n))
            continue
        invalid_count += 1
    return {"ranges": results, "invalidCount": invalid_count}


def clamp_range(start: float, end: float, max_index: int) -> dict[str, int] | None:
    """Clamp a (start, end) pair into [0, max_index], swapping if reversed.

    Port of parsers.py _clamp_range. Returns None when max_index < 0 or
    start/end are not finite numbers.
    """
    if max_index < 0:
        return None
    try:
        if start != start or end != end:  # NaN check
            return None
        if start in (float("inf"), float("-inf")) or end in (float("inf"), float("-inf")):
            return None
    except TypeError:
        return None
    start = max(0, min(start, max_index))
    end = max(0, min(end, max_index))
    if start > end:
        start, end = end, start
    return {"start": int(start), "end": int(end)}


def merge_ranges(ranges: list[dict]) -> list[dict]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: (r["start"], r["end"]))
    out = [dict(ordered[0])]
    for i in range(1, len(ordered)):
        cur = ordered[i]
        last = out[-1]
        if cur["start"] <= last["end"] + 1:
            last["end"] = max(last["end"], cur["end"])
        else:
            out.append(dict(cur))
    return out


def repair_coverage(groups: list[dict], sentence_count: int) -> list[dict]:
    """Repair group coverage so every index in [0, sentence_count-1] is covered
    exactly once. Port of gap_handlers.py RepairingGapHandler.handle (the
    deterministic, no-LLM variant):
      - Sorts all ranges by start; later overlapping ranges are trimmed so the
        earliest-starting range keeps the contested indices (first-claim-wins).
      - Fills gaps by extending an adjacent range: a gap at the very beginning
        pulls the first range's start back to 0; a gap in the middle extends the
        previously-added range forward; a trailing gap extends the last range.
    """
    max_index = sentence_count - 1

    # Flatten all (group_index, range) pairs and sort by start, then parse order.
    flat = []
    for gi, g in enumerate(groups):
        for r in g["ranges"]:
            flat.append({"gi": gi, "range": r})
    flat.sort(key=lambda item: (item["range"]["start"], item["range"]["ordinal"]))

    adjusted: list[list[dict]] = [[] for _ in groups]
    next_expected = 0
    last_added = None  # {"gi": gi, "idx": idx} of the most recently appended range

    for item in flat:
        gi = item["gi"]
        range_ = item["range"]
        if range_["end"] < next_expected:
            # Entirely consumed by an earlier range (overlap) -- drop it.
            continue
        start = max(range_["start"], next_expected)
        if start > range_["end"]:
            continue

        if start > next_expected:
            # Gap before this range.
            if last_added is None:
                # Gap at the very beginning: pull this first range back to 0.
                start = 0
            else:
                # Gap in the middle: extend the previously-added range forward.
                prev = adjusted[last_added["gi"]][last_added["idx"]]
                adjusted[last_added["gi"]][last_added["idx"]] = {
                    "start": prev["start"],
                    "end": start - 1,
                }

        adjusted[gi].append({"start": start, "end": range_["end"]})
        last_added = {"gi": gi, "idx": len(adjusted[gi]) - 1}
        next_expected = range_["end"] + 1

    # Trailing gap: extend the last added range to the final index.
    if next_expected <= max_index and last_added is not None:
        prev = adjusted[last_added["gi"]][last_added["idx"]]
        adjusted[last_added["gi"]][last_added["idx"]] = {"start": prev["start"], "end": max_index}

    # Rebuild groups in original order, dropping any that lost all ranges.
    result = []
    for gi, g in enumerate(groups):
        if adjusted[gi]:
            result.append({"label": g["label"], "ranges": adjusted[gi]})
    return result


def collect_diagnostics(raw_groups: list[dict], sentence_count: int, invalid_range_tokens: int = 0) -> dict:
    seen = [0] * sentence_count
    out_of_range = []

    for g in raw_groups:
        for r in g["ranges"]:
            if (
                r["rawStart"] < 0
                or r["rawEnd"] < 0
                or r["rawStart"] >= sentence_count
                or r["rawEnd"] >= sentence_count
            ):
                out_of_range.append((r["rawStart"], r["rawEnd"]))
            for i in range(r["start"], r["end"] + 1):
                seen[i] += 1

    duplicates = []
    missing = []
    for i, count in enumerate(seen):
        if count > 1:
            duplicates.append(i)
        if count == 0:
            missing.append(i)

    return {
        "outOfRange": out_of_range,
        "duplicates": duplicates,
        "missing": missing,
        "invalidRangeTokens": invalid_range_tokens,
    }


def finalize_groups(raw_groups: list[dict], sentence_count: int, invalid_range_tokens: int = 0) -> list[dict]:
    """Shared tail of parse_topic_ranges: takes label-grouped ranges (in
    first-appearance order, labels already deduped) and produces the final
    continuous, non-overlapping, adjacent-joined groups.
    """
    groups = []
    for g in raw_groups:
        merged = merge_ranges(g["ranges"])
        if not merged:
            continue
        groups.append({"label": g["label"], "ranges": merged})

    diagnostics = collect_diagnostics(raw_groups, sentence_count, invalid_range_tokens)
    if not groups:
        raise TopicParseError("No valid topic ranges found in response", diagnostics)

    # Repair overlaps and gaps so coverage is continuous over [0, max_index].
    groups = repair_coverage(groups, sentence_count)

    # AdjacentSameTopicJoiner: merge consecutive groups with identical labels.
    joined: list[dict] = []
    for g in groups:
        last = joined[-1] if joined else None
        if (
            last is not None
            and len(last["label"]) == len(g["label"])
            and all(a == b for a, b in zip(last["label"], g["label"]))
        ):
            last["ranges"] = merge_ranges(last["ranges"] + g["ranges"])
        else:
            joined.append({"label": list(g["label"]), "ranges": list(g["ranges"])})
    return joined


def groups_from_segments(segments: list[dict], sentence_count: int) -> list[dict]:
    """Rebuild final groups from a flat list of labeled segments (e.g. produced
    by re-splitting an oversized range). Segments sharing a normalized label
    key are merged into one group -- preserving the invariant that every topic
    name is unique -- and coverage is repaired/joined exactly like
    parse_topic_ranges.
    """
    if sentence_count <= 0:
        raise ValueError("sentenceCount must be positive")
    max_index = sentence_count - 1

    grouped: dict[str, dict] = {}
    order: list[str] = []
    key_to_canonical: dict[str, list[str]] = {}
    ordinal = 0
    for seg in segments:
        if not seg.get("label"):
            continue
        key = normalize_label_key(seg["label"])
        if key not in key_to_canonical:
            key_to_canonical[key] = seg["label"]
        label = key_to_canonical[key]
        range_ = clamp_range(seg["start"], seg["end"], max_index)
        if range_ is None:
            continue
        if key not in grouped:
            grouped[key] = {"label": label, "ranges": []}
            order.append(key)
        grouped[key]["ranges"].append(
            {
                "start": range_["start"],
                "end": range_["end"],
                "rawStart": seg["start"],
                "rawEnd": seg["end"],
                "ordinal": ordinal,
            }
        )
        ordinal += 1

    raw_groups = [grouped[k] for k in order]
    return finalize_groups(raw_groups, sentence_count)


def parse_topic_ranges(response: str, sentence_count: int) -> list[dict]:
    """Returns list[{"label": list[str], "ranges": list[{"start", "end"}]}]
    (inclusive 0-based)."""
    if sentence_count <= 0:
        raise ValueError("sentenceCount must be positive")
    max_index = sentence_count - 1
    lines = [l.strip() for l in re.split(r"\r?\n", response.strip())]
    lines = [l for l in lines if l]

    grouped: dict[str, dict] = {}
    order: list[str] = []
    key_to_canonical: dict[str, list[str]] = {}
    ordinal = 0
    invalid_range_tokens = 0

    for ln in lines:
        m = TOPIC_LINE_RE.match(ln)
        if m:
            topic_path = m.group(1).strip()
            ranges_str = m.group(2).strip()
        elif ":" in ln:
            idx = ln.index(":")
            topic_path = ln[:idx].strip()
            ranges_str = ln[idx + 1 :].strip()
        else:
            continue
        if not topic_path:
            continue

        label = normalize_label_parts(topic_path.split(">"))
        if not label:
            continue
        key = normalize_label_key(label)
        if key not in key_to_canonical:
            key_to_canonical[key] = label
        label = key_to_canonical[key]

        parsed = parse_range_string(ranges_str)
        invalid_range_tokens += parsed["invalidCount"]
        clamped = []
        for s, e in parsed["ranges"]:
            # Clamp to bounds (matches Python TopicRangeParser); never reject.
            r = clamp_range(s, e, max_index)
            if r is not None:
                clamped.append({"start": r["start"], "end": r["end"], "rawStart": s, "rawEnd": e, "ordinal": ordinal})
                ordinal += 1
        if not clamped:
            continue

        if key not in grouped:
            grouped[key] = {"label": label, "ranges": []}
            order.append(key)
        grouped[key]["ranges"].extend(clamped)

    raw_groups = [grouped[k] for k in order]
    return finalize_groups(raw_groups, sentence_count, invalid_range_tokens)
