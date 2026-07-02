#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
# ─── How to run ───
# python scripts/filter_context_bundle.py --input source-bundle.jsonl --output filtered.jsonl --summary summary.json
"""Filter low-signal context records before AI-Q synthesis."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonRecord: TypeAlias = dict[str, JsonValue]

TEXT_FIELDS: Final = ("text", "content", "excerpt")
PATH_FIELDS: Final = ("path", "source_path")
CITATION_FIELDS: Final = ("source_id", "citation", "id")

@dataclass(frozen=True, slots=True)
class GateDecision:
    action: str
    reason: str
    record: JsonRecord

@dataclass(frozen=True, slots=True)
class CuratedInfo:
    label: str | None
    duplicate_of: str | None
    is_routing_anchor: bool

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove low-signal context before AI-Q synthesis")
    parser.add_argument("--input", required=True, help="JSON array or JSONL source bundle")
    parser.add_argument("--output", required=True, help="Filtered JSONL output")
    parser.add_argument("--summary", required=True, help="Removal summary JSON")
    parser.add_argument("--curated", help="Optional curated.jsonl map from context-signal-noise dataset")
    parser.add_argument("--required-citations", default="", help="Comma-separated citations/source IDs to force-keep")
    parser.add_argument("--max-mixed-chars", type=int, default=1200)
    parser.add_argument("--keep-low-signal", action="store_true")
    return parser.parse_args()

def as_record(value: JsonValue) -> JsonRecord | None:
    match value:
        case dict() as record:
            return record
        case _:
            return None

def as_text(value: JsonValue | None) -> str | None:
    match value:
        case str() as text:
            return text
        case int() | float() | bool() as scalar:
            return str(scalar)
        case _:
            return None

def as_bool(value: JsonValue | None) -> bool:
    match value:
        case bool() as flag:
            return flag
        case _:
            return False

def load_records(path: Path) -> list[JsonRecord]:
    if path.suffix.lower() == ".jsonl":
        records: list[JsonRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            loaded = as_record(json.loads(line))
            if loaded is not None:
                records.append(loaded)
        return records
    loaded_json = json.loads(path.read_text(encoding="utf-8"))
    match loaded_json:
        case list() as values:
            return [record for value in values if (record := as_record(value)) is not None]
        case dict() as record:
            records_value = record.get("records")
            match records_value:
                case list() as values:
                    return [item for value in values if (item := as_record(value)) is not None]
                case _:
                    return [record]
        case _:
            return []

def first_string(record: JsonRecord, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = as_text(record.get(key))
        if text:
            return text
    return None

def record_path(record: JsonRecord) -> str | None:
    return first_string(record, PATH_FIELDS)

def record_citation(record: JsonRecord) -> str | None:
    return first_string(record, CITATION_FIELDS)

def record_text(record: JsonRecord) -> str | None:
    return first_string(record, TEXT_FIELDS)

def record_label(record: JsonRecord, curated: dict[str, CuratedInfo]) -> str | None:
    label = as_text(record.get("curated_label")) or as_text(record.get("initial_label"))
    path = record_path(record)
    if path and path in curated and curated[path].label:
        return curated[path].label
    return label

def load_curated(path: Path | None) -> dict[str, CuratedInfo]:
    if path is None or not path.exists():
        return {}
    result: dict[str, CuratedInfo] = {}
    for record in load_records(path):
        path_value = record_path(record)
        if not path_value:
            continue
        result[path_value] = CuratedInfo(
            label=as_text(record.get("curated_label")) or as_text(record.get("initial_label")),
            duplicate_of=as_text(record.get("duplicate_of")),
            is_routing_anchor=as_bool(record.get("is_routing_anchor")),
        )
    return result

def compress_record(record: JsonRecord, max_chars: int) -> JsonRecord:
    compressed = dict(record)
    text = record_text(record)
    if text and len(text) > max_chars:
        snippet = text[:max_chars].rstrip()
        for key in TEXT_FIELDS:
            if key in compressed:
                compressed[key] = f"{snippet}\n[compressed: original length {len(text)} chars]"
                break
        else:
            compressed["excerpt"] = snippet
    return compressed

def add_gate(record: JsonRecord, action: str, reason: str) -> JsonRecord:
    updated = dict(record)
    updated["removal_gate"] = {"action": action, "reason": reason}
    return updated

def represented_ids(records: list[JsonRecord]) -> set[str]:
    ids: set[str] = set()
    for record in records:
        for value in (as_text(record.get("id")), record_citation(record), record_path(record)):
            if value:
                ids.add(value)
    return ids

def decide(
    record: JsonRecord,
    curated: dict[str, CuratedInfo],
    required: set[str],
    represented: set[str],
    keep_low_signal: bool,
    max_mixed_chars: int,
) -> GateDecision:
    path = record_path(record)
    citation = record_citation(record)
    info = curated.get(path or "")
    duplicate_of = as_text(record.get("duplicate_of")) or (info.duplicate_of if info else None)
    label = record_label(record, curated)
    routing_anchor = as_bool(record.get("is_routing_anchor")) or (info.is_routing_anchor if info else False)

    if citation and citation in required:
        return GateDecision("keep", "required_citation", add_gate(record, "keep", "required_citation"))
    if path and path in required:
        return GateDecision("keep", "required_path", add_gate(record, "keep", "required_path"))
    if duplicate_of and duplicate_of in represented and not routing_anchor:
        return GateDecision("drop", "duplicate_of_represented", add_gate(record, "drop", "duplicate_of_represented"))
    if routing_anchor:
        return GateDecision("keep", "routing_anchor", add_gate(record, "keep", "routing_anchor"))
    match label:
        case "high_signal":
            return GateDecision("keep", "high_signal", add_gate(record, "keep", "high_signal"))
        case "mixed_signal":
            return GateDecision(
                "compress",
                "mixed_signal_compressed",
                add_gate(compress_record(record, max_mixed_chars), "compress", "mixed_signal_compressed"),
            )
        case "low_signal_or_noise":
            if keep_low_signal:
                return GateDecision("keep", "low_signal_user_requested", add_gate(record, "keep", "low_signal_user_requested"))
            return GateDecision("drop", "low_signal_or_noise", add_gate(record, "drop", "low_signal_or_noise"))
        case None:
            return GateDecision(
                "compress",
                "unknown_label_keep_compressed",
                add_gate(compress_record(record, max_mixed_chars), "compress", "unknown_label_keep_compressed"),
            )
        case _:
            return GateDecision(
                "compress",
                "unrecognized_label_keep_compressed",
                add_gate(compress_record(record, max_mixed_chars), "compress", "unrecognized_label_keep_compressed"),
            )

def write_jsonl(path: Path, records: list[JsonRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")

def main() -> int:
    args = parse_args()
    records = load_records(Path(args.input))
    curated = load_curated(Path(args.curated) if args.curated else None)
    required = {part.strip() for part in str(args.required_citations).split(",") if part.strip()}
    represented = represented_ids(records)
    decisions = [
        decide(record, curated, required, represented, bool(args.keep_low_signal), int(args.max_mixed_chars))
        for record in records
    ]
    kept = [decision.record for decision in decisions if decision.action != "drop"]
    write_jsonl(Path(args.output), kept)
    counts = Counter(decision.reason for decision in decisions)
    summary = {
        "input_count": len(records),
        "kept_count": len(kept),
        "dropped_count": len(records) - len(kept),
        "compressed_count": sum(1 for decision in decisions if decision.action == "compress"),
        "reason_counts": dict(sorted(counts.items())),
    }
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
