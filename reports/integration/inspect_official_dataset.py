"""Read-only inspection of B2 JSON data; never imports or runs official code.

The only written artifact is the explicitly selected JSON report. Conversation
content is used for exact fingerprints and length statistics, never emitted.
The schema checker implements every validation keyword found in these two data
schemas, rather than claiming validation with an unavailable jsonschema package.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import statistics


ANNOTATIONS = {"$schema", "$id", "title", "description", "examples", "default", "$defs", "definitions"}
SUPPORTED = ANNOTATIONS | {"$ref", "type", "required", "additionalProperties", "properties", "items", "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems"}


def jsonl(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    records, invalid, blanks = [], [], 0
    for number, line in enumerate(lines, 1):
        if not line.strip():
            blanks += 1
            continue
        try:
            records.append(json.loads(line))
        except (ValueError, TypeError) as error:
            invalid.append({"line": number, "error_type": type(error).__name__})
    return records, {"physical_lines": len(lines), "valid_json_rows": len(records), "invalid_json_rows": len(invalid), "parse_errors": invalid, "blank_lines": blanks}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_keywords(schema, output):
    if not isinstance(schema, dict):
        return
    output.update(schema)
    for key in ("properties", "$defs", "definitions"):
        for value in schema.get(key, {}).values():
            schema_keywords(value, output)
    if "items" in schema:
        schema_keywords(schema["items"], output)


def validate(value, schema, root_schema, path="$"):
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("Only local schema references are supported")
        target = root_schema
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        yield from validate(value, target, root_schema, path)
        return
    expected = schema.get("type")
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool), "number": isinstance(value, (int, float)) and not isinstance(value, bool), "boolean": isinstance(value, bool), "null": value is None}
    if expected and not matches.get(expected, False):
        yield path, "type"
        return
    if "enum" in schema and value not in schema["enum"]:
        yield path, "enum"
    if "const" in schema and value != schema["const"]:
        yield path, "const"
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                yield path + "." + key, "required"
        if schema.get("additionalProperties") is False:
            for key in value.keys() - properties.keys():
                yield path + "." + key, "additionalProperties"
        for key, item in value.items():
            if key in properties:
                yield from validate(item, properties[key], root_schema, path + "." + key)
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            yield path, "minItems"
        if len(value) > schema.get("maxItems", float("inf")):
            yield path, "maxItems"
        if schema.get("uniqueItems") and len(value) != len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value}):
            yield path, "uniqueItems"
        if "items" in schema:
            for index, item in enumerate(value):
                yield from validate(item, schema["items"], root_schema, path + f"[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            yield path, "minLength"
        if len(value) > schema.get("maxLength", float("inf")):
            yield path, "maxLength"
        if "pattern" in schema and not re.search(schema["pattern"], value):
            yield path, "pattern"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            yield path, "minimum"
        if value > schema.get("maximum", float("inf")):
            yield path, "maximum"
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            yield path, "exclusiveMinimum"
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            yield path, "exclusiveMaximum"


def summary(values):
    return {"n": len(values), "min": min(values) if values else None, "max": max(values) if values else None, "mean": round(statistics.mean(values), 3) if values else None, "distribution": dict(sorted(Counter(values).items()))}


def dialogue_hash(row):
    sequence = [(turn["role"], turn["content"]) for turn in row.get("turns", row.get("history", []))]
    return hashlib.sha256(json.dumps(sequence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def distribution(values):
    counts = Counter(values)
    return {"counts": dict(counts), "percent": {key: round(count * 100 / len(values), 3) for key, count in counts.items()} if values else {}}


def inspect_split(root, name):
    folder = root / "训练-验证-数据集" / name
    data_path = folder / f"{name}_public.jsonl"
    schema_path = folder / f"{name}_public.schema.json"
    records, result = jsonl(data_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    keywords = set()
    schema_keywords(schema, keywords)
    unsupported = keywords - SUPPORTED
    if unsupported:
        raise ValueError(f"Unsupported schema keywords: {sorted(unsupported)}")
    errors, invalid_rows = Counter(), 0
    for row in records:
        found = list(validate(row, schema, schema))
        invalid_rows += bool(found)
        errors.update(error[1] for error in found)
    result.update({"data_path": str(data_path), "data_sha256": file_hash(data_path), "schema_path": str(schema_path), "schema_sha256": file_hash(schema_path), "schema_draft": schema.get("$schema"), "schema_check_method": "self-written checker covering every validation keyword found in these actual schemas; not a general Draft 2020-12 validator", "schema_keywords": sorted(keywords), "unsupported_schema_keywords": sorted(unsupported), "schema_invalid_rows": invalid_rows, "schema_error_counts": dict(errors)})
    ids = Counter(row["conversation_id"] for row in records)
    hashes = Counter(dialogue_hash(row) for row in records)
    keys = Counter("|".join(sorted(row)) for row in records)
    turn_lengths, point_lengths, response_lengths, memory_lengths = [], [], [], []
    emotions, refs = [], []
    roles, prediction_keys, target_ranks, semantic = Counter(), Counter(), Counter(), Counter()
    profiles = {key: Counter() for key in ("personality_traits", "interests", "style")}
    empty_profiles = Counter()
    anomalies = []
    for row in records:
        turns = row["turns"]
        by_id = {turn["turn_id"]: turn for turn in turns}
        turn_lengths.append(len(turns))
        point_lengths.append(len(row["prediction_points"]))
        roles.update(turn["role"] for turn in turns)
        if len(by_id) != len(turns):
            semantic["duplicate_turn_id_conversations"] += 1
        if [turn["turn_id"] for turn in turns] != list(range(1, len(turns) + 1)):
            semantic["non_contiguous_or_unsorted_turn_ids"] += 1
        if any(turns[index]["role"] == turns[index - 1]["role"] for index in range(1, len(turns))):
            semantic["non_alternating_conversations"] += 1
        if turns and turns[0]["role"] != "user":
            semantic["first_role_not_user"] += 1
        for point in row["prediction_points"]:
            uid, aid = point["target_user_turn_id"], point["assistant_response_turn_id"]
            target = point["target"]
            prediction_keys[(row["conversation_id"], uid)] += 1
            emotions.append(target["emotion_label"])
            response_lengths.append(len(target["response_text"]))
            memory_lengths.append(len(target["memory_refs"]))
            refs.extend(target["memory_refs"])
            if uid not in by_id:
                semantic["target_user_turn_id_missing"] += 1
            elif by_id[uid]["role"] != "user":
                semantic["target_id_role_not_user"] += 1
            else:
                target_ranks[sum(turn["role"] == "user" for turn in turns if turn["turn_id"] <= uid)] += 1
            if aid not in by_id:
                semantic["assistant_response_turn_id_missing"] += 1
            elif by_id[aid]["role"] != "assistant":
                semantic["assistant_id_role_not_assistant"] += 1
            if aid != uid + 1:
                semantic["assistant_not_next_turn_id"] += 1
                anomalies.append({"conversation_id": row["conversation_id"], "target_user_turn_id": uid, "assistant_response_turn_id": aid, "assistant_precedes_target": aid < uid})
            if aid in by_id and target["response_text"] != by_id[aid]["content"]:
                semantic["reference_response_differs_from_assistant_turn"] += 1
            for key in profiles:
                profiles[key].update(target["user_profile"][key])
                if not target["user_profile"][key]:
                    empty_profiles[key] += 1
    for key in ("duplicate_turn_id_conversations", "non_contiguous_or_unsorted_turn_ids", "non_alternating_conversations", "first_role_not_user", "target_user_turn_id_missing", "target_id_role_not_user", "assistant_response_turn_id_missing", "assistant_id_role_not_assistant", "assistant_not_next_turn_id", "reference_response_differs_from_assistant_turn"):
        semantic.setdefault(key, 0)
    result.update({"top_level_key_sets": dict(keys), "unique_conversation_ids": len(ids), "duplicate_conversation_id_rows": sum(count - 1 for count in ids.values()), "unique_complete_role_content_dialogs": len(hashes), "duplicate_complete_dialog_extra_rows": sum(count - 1 for count in hashes.values()), "duplicate_complete_dialog_groups": sum(count > 1 for count in hashes.values()), "largest_duplicate_multiplicity": max(hashes.values()), "turn_count_per_conversation": summary(turn_lengths), "total_turns": sum(turn_lengths), "role_distribution": dict(roles), "prediction_points_per_conversation": summary(point_lengths), "total_prediction_points": sum(point_lengths), "duplicate_conversation_target_prediction_keys": sum(count - 1 for count in prediction_keys.values()), "emotion_distribution": distribution(emotions), "profile_label_mentions": {key: dict(counts) for key, counts in profiles.items()}, "empty_profile_array_counts": dict(empty_profiles), "memory_refs_per_prediction": summary(memory_lengths), "total_memory_ref_mentions": len(refs), "unique_memory_refs": len(set(refs)), "memory_refs_all_match_pattern": all(re.fullmatch(r"mem_[0-9]{6}", ref) for ref in refs), "memory_refs_note": "Opaque memory identifiers, not turn identifiers. These JSONL records do not supply a memory bank or a mapping from memory IDs to their content.", "reference_response_characters": {"min": min(response_lengths), "max": max(response_lengths), "mean": round(statistics.mean(response_lengths), 3)}, "target_user_rank_distribution": dict(sorted(target_ranks.items())), "semantic_checks": dict(semantic), "nonadjacent_response_prediction_points": anomalies})
    return records, schema, set(refs), result


def schema_differences(first, second, path="$"):
    if type(first) is not type(second):
        return [{"path": path, "kind": "type differs"}]
    if isinstance(first, dict):
        result = []
        for key in sorted(set(first) | set(second)):
            if key not in first or key not in second:
                result.append({"path": path + "." + key, "kind": "field missing"})
            else:
                result.extend(schema_differences(first[key], second[key], path + "." + key))
        return result
    if first != second:
        return [{"path": path, "train": first, "val": second}]
    return []


def inspect_inference(root, splits):
    path = root / "test_inference_data.jsonl"
    records, result = jsonl(path)
    ids = Counter(row["id"] for row in records)
    conversation_ids = Counter(row["conversation_id"] for row in records)
    checks, fields = Counter(), Counter()
    grouped = {}
    for row in records:
        history = row["history"]
        turn_ids = [turn["turn_id"] for turn in history]
        fields["|".join(sorted(row))] += 1
        grouped.setdefault(row["conversation_id"], []).append(row)
        if len(turn_ids) != len(set(turn_ids)):
            checks["duplicate_history_turn_id"] += 1
        if turn_ids != sorted(turn_ids):
            checks["unsorted_history_turn_ids"] += 1
        if not history or history[-1]["role"] != "user":
            checks["last_history_role_not_user"] += 1
        if history and history[-1]["turn_id"] != row["target_user_turn_id"]:
            checks["last_history_id_not_target"] += 1
        if any(turn["turn_id"] > row["target_user_turn_id"] for turn in history):
            checks["future_turn_in_history"] += 1
    prefixes = []
    for group in grouped.values():
        group.sort(key=lambda row: len(row["history"]))
        for index in range(len(group) - 1):
            shorter, longer = group[index], group[index + 1]
            prefixes.append({"shorter_history_length": len(shorter["history"]), "longer_history_length": len(longer["history"]), "shorter_is_exact_prefix": shorter["history"] == longer["history"][:len(shorter["history"])]})
    output_schema_path = root / "participant" / "templates" / "submission_schema.json"
    output_schema = json.loads(output_schema_path.read_text(encoding="utf-8-sig"))
    id_constraint = output_schema["properties"]["id"]
    pattern = id_constraint.get("pattern")
    result.update({"data_path": str(path), "data_sha256": file_hash(path), "top_level_key_sets": dict(fields), "unique_ids": len(ids), "unique_conversation_ids": len(conversation_ids), "duplicate_ids": sum(count - 1 for count in ids.values()), "history_lengths": summary([len(row["history"]) for row in records]), "last_history_role_counts": dict(Counter(row["history"][-1]["role"] for row in records)), "history_checks": dict(checks), "repeated_conversation_prefix_checks": prefixes, "reference_target_fields_present": any("target" in row or "prediction_points" in row for row in records), "memory_bank_fields_present": any("memory_bank" in row or "memories" in row for row in records), "train_conversation_id_overlap": len(set(conversation_ids) & {row["conversation_id"] for row in splits["train"]}), "val_conversation_id_overlap": len(set(conversation_ids) & {row["conversation_id"] for row in splits["val"]}), "submission_schema_path": str(output_schema_path), "submission_schema_sha256": file_hash(output_schema_path), "submission_id_constraint": id_constraint, "input_ids": list(ids), "input_ids_passing_submission_pattern": sum(bool(re.search(pattern, value)) for value in ids) if pattern else None, "id_discrepancy_note": "The sample uses test1_... identifiers while the included submission schema accepts test_... only. Preserve input IDs; seek official clarification rather than silently renaming them."})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    root, output = Path(args.root), Path(args.report)
    split_rows, split_schemas, split_refs, split_reports = {}, {}, {}, {}
    for name in ("train", "val"):
        split_rows[name], split_schemas[name], split_refs[name], split_reports[name] = inspect_split(root, name)
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "source_root": str(root), "inspection_scope": "Read and statically inspect JSON/JSONL; no official source code executed; no personal dialogue text emitted; no licensing inference", "jsonschema_installed": importlib.util.find_spec("jsonschema") is not None, "splits": split_reports, "cross_split": {"conversation_id_overlap": len({row["conversation_id"] for row in split_rows["train"]} & {row["conversation_id"] for row in split_rows["val"]}), "complete_role_content_dialog_overlap": len({dialogue_hash(row) for row in split_rows["train"]} & {dialogue_hash(row) for row in split_rows["val"]}), "memory_ref_overlap": len(split_refs["train"] & split_refs["val"]), "schema_differences": schema_differences(split_schemas["train"], split_schemas["val"])}, "inference_sample": inspect_inference(root, split_rows), "contract_implications": ["Prediction inputs are history sliced through target_user_turn_id inclusive, with current user included once. Reference answer and later turns must not enter model input.", "Generate the official sixteen-category emotion_label, three user_profile arrays and memory_refs as well as response_text; the six-category demonstration emotion is not a lossless official label representation.", "memory_refs are opaque mem_XXXXXX identifiers. Do not interpret their numeric suffix as turn_id, invent a memory-bank mapping, or use reference memory IDs as inference inputs.", "Four training prediction points refer to a preceding assistant. Quarantine or explicitly resolve them; five training conversations have no annotated prediction points.", "Keep validation conversations out of training. Train has 202 repeated full-dialog groups; train and validation have no complete-dialog overlap.", "The three inference examples are smoke fixtures, not a labelled benchmark. IDs must be preserved, and the sample/schema pattern contradiction needs official clarification."]}
    # Keep the published report portable: omit local account and disk paths.
    source_prefix = str(root).rstrip("/\\")
    def portable(value):
        if isinstance(value, dict):
            return {key: portable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [portable(item) for item in value]
        if isinstance(value, str) and value == source_prefix:
            return root.name
        if isinstance(value, str) and value.startswith((source_prefix + "/", source_prefix + "\\")):
            return Path(value).relative_to(root).as_posix()
        return value
    report = portable(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(output), "train_rows": split_reports["train"]["valid_json_rows"], "train_points": split_reports["train"]["total_prediction_points"], "train_schema_invalid": split_reports["train"]["schema_invalid_rows"], "val_rows": split_reports["val"]["valid_json_rows"], "val_points": split_reports["val"]["total_prediction_points"], "val_schema_invalid": split_reports["val"]["schema_invalid_rows"], "train_anomalous_points": split_reports["train"]["nonadjacent_response_prediction_points"], "inference_id_pattern_pass_count": report["inference_sample"]["input_ids_passing_submission_pattern"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
