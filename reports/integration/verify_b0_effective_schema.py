"""Reproduce B0 contract checks using in-memory protocol fixtures only.

Run with Python and jsonschema installed, from any working directory:
    python reports/integration/verify_b0_effective_schema.py

This script never imports participant code, loads a model, or writes predictions.
It writes only the adjacent b0-effective-schema-check.json verification report.
"""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = Path(__file__).with_name("b0-effective-schema-check.json")
SNAPSHOT_PATH = "contracts/official/submission.schema.json"
EFFECTIVE_PATH = "contracts/official/effective_submission.schema.json"
MANIFEST_PATH = "contracts/official/source-manifest.json"
INPUT_PATH = "submission/official-reference/test_inference_data.jsonl"
TEMPLATE_PATH = "submission/official-reference/participant/templates/submission_schema.json"
SOURCE_PATH = "participant/templates/submission_schema.json"
EXPECTED_SNAPSHOT_SHA256 = "91c42d56ae433212aab7905eabdbb96cf8463c2f887dc46b3f31647ab3a5d591"
EXPECTED_INPUT_IDS = ["test1_000001_t5", "test1_000001_t7", "test1_000002_t5"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_input_alignment(output: dict[str, Any], input_row: dict[str, Any]) -> None:
    """A local verification check, not an inference adapter implementation."""
    if output["id"] != input_row["id"]:
        raise ValueError("OUTPUT_ID_MISMATCH")


def main() -> int:
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, **details: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), **details})

    snapshot_bytes = (ROOT / SNAPSHOT_PATH).read_bytes()
    snapshot_hash = sha256(snapshot_bytes)
    effective_bytes = (ROOT / EFFECTIVE_PATH).read_bytes()
    input_bytes = (ROOT / INPUT_PATH).read_bytes()
    manifest = json.loads((ROOT / MANIFEST_PATH).read_bytes())
    source_entry = next(item for item in manifest["source_files"] if item["path"] == SOURCE_PATH)
    copy_entry = next(item for item in manifest["copies"] if item["path"] == SNAPSHOT_PATH)
    input_entry = next(item for item in manifest["copies"] if item["path"] == INPUT_PATH)

    record("snapshot_matches_original_recorded_sha256", snapshot_hash == EXPECTED_SNAPSHOT_SHA256)
    record("snapshot_manifest_provenance_matches", source_entry["sha256"] == copy_entry["sha256"] == EXPECTED_SNAPSHOT_SHA256)
    record("snapshot_matches_untouched_reference_template", snapshot_bytes == (ROOT / TEMPLATE_PATH).read_bytes())
    record("input_fixture_matches_manifest_sha256", sha256(input_bytes) == input_entry["sha256"])

    original = json.loads(snapshot_bytes)
    effective = json.loads(effective_bytes)
    for name, schema in (("original", original), ("effective", effective)):
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            record(name + "_schema_is_valid", False, error_type=type(exc).__name__)
        else:
            record(name + "_schema_is_valid", True)

    expected = copy.deepcopy(original)
    removed_pattern = expected["properties"]["id"].pop("pattern")
    expected["description"] = effective.get("description")
    record("derivation_only_removes_id_pattern_and_adds_description", expected == effective)
    record("clarification_source_is_documented", isinstance(effective.get("description"), str) and "2026-10-10" in effective["description"] and "用户" in effective["description"])
    record("id_remains_required_string", effective["properties"]["id"] == {"type": "string"} and "id" in effective["required"])

    original_validator = Draft202012Validator(original)
    effective_validator = Draft202012Validator(effective)
    inputs = [json.loads(line) for line in input_bytes.decode("utf-8").splitlines() if line.strip()]
    record("original_three_fixture_ids_and_order", [row["id"] for row in inputs] == EXPECTED_INPUT_IDS)

    fixtures: list[dict[str, Any]] = []
    fixture_results: list[dict[str, Any]] = []
    for row in inputs:
        fixture = {
            "id": row["id"],
            "response_text": "protocol fixture: synthetic nonempty reply, not a model prediction",
            "emotion_label": "neutral",
            "user_profile": {"personality_traits": [], "interests": [], "style": []},
            "memory_refs": [],
        }
        effective_pass = effective_validator.is_valid(fixture)
        try:
            require_input_alignment(fixture, row)
        except ValueError:
            alignment_pass = False
        else:
            alignment_pass = True
        original_errors = list(original_validator.iter_errors(fixture))
        original_pattern_only = len(original_errors) == 1 and original_errors[0].validator == "pattern" and list(original_errors[0].path) == ["id"]
        record("fixture_effective_schema:" + row["id"], effective_pass)
        record("fixture_input_alignment:" + row["id"], alignment_pass)
        record("fixture_original_rejects_only_id_pattern:" + row["id"], original_pattern_only)
        fixtures.append(fixture)
        fixture_results.append({
            "label": "protocol fixture",
            "id": row["id"],
            "effective_schema_passed": effective_pass,
            "input_alignment_passed": alignment_pass,
            "original_rejected_only_id_pattern": original_pattern_only,
        })

    changed_id_fixture = copy.deepcopy(fixtures[0])
    changed_id_fixture["id"] = "test_000001_t5"
    changed_effective_pass = effective_validator.is_valid(changed_id_fixture)
    changed_original_pass = original_validator.is_valid(changed_id_fixture)
    record("changed_id_passes_effective_schema", changed_effective_pass)
    record("changed_id_also_passes_original_schema", changed_original_pass)
    alignment_error = None
    try:
        require_input_alignment(changed_id_fixture, inputs[0])
    except ValueError as exc:
        alignment_error = str(exc)
    record("changed_id_rejected_by_input_alignment", alignment_error == "OUTPUT_ID_MISMATCH")

    negatives: list[tuple[str, dict[str, Any], str]] = []
    fixture = fixtures[0]
    changed = copy.deepcopy(fixture)
    changed["id"] = 5
    negatives.append(("id_not_string", changed, "type"))
    changed = copy.deepcopy(fixture)
    del changed["id"]
    negatives.append(("id_missing", changed, "required"))
    changed = copy.deepcopy(fixture)
    changed["extra"] = True
    negatives.append(("additional_output_property", changed, "additionalProperties"))
    changed = copy.deepcopy(fixture)
    changed["emotion_label"] = "invented_emotion"
    negatives.append(("invalid_emotion_enum", changed, "enum"))
    changed = copy.deepcopy(fixture)
    del changed["user_profile"]["style"]
    negatives.append(("missing_profile_field", changed, "required"))
    changed = copy.deepcopy(fixture)
    changed["user_profile"]["style"] = ["brief", "brief"]
    negatives.append(("duplicate_profile_items", changed, "uniqueItems"))
    changed = copy.deepcopy(fixture)
    changed["memory_refs"] = ["mem_invalid"]
    negatives.append(("invalid_memory_ref_pattern", changed, "pattern"))
    changed = copy.deepcopy(fixture)
    changed["memory_refs"] = ["mem_000001", "mem_000001"]
    negatives.append(("duplicate_memory_refs", changed, "uniqueItems"))
    changed = copy.deepcopy(fixture)
    changed["response_text"] = 5
    negatives.append(("response_not_string", changed, "type"))
    negative_results = []
    for name, changed, expected_validator in negatives:
        errors = list(effective_validator.iter_errors(changed))
        actual_validators = sorted({error.validator for error in errors})
        passed = bool(errors) and expected_validator in actual_validators
        record("structural_negative:" + name, passed)
        negative_results.append({"name": name, "rejected_as_expected": passed, "expected_validator": expected_validator, "actual_validators": actual_validators})

    empty_allowed = copy.deepcopy(fixture)
    empty_allowed["response_text"] = ""
    empty_allowed["emotion_label"] = ""
    record("original_empty_response_and_emotion_allowance_preserved", original_validator.is_valid(empty_allowed) is False and effective_validator.is_valid(empty_allowed))
    # Restore a valid original-pattern ID to isolate the empty-field allowance.
    empty_allowed["id"] = "test_000001_t5"
    record("empty_field_allowance_agrees_in_both_schemas", original_validator.is_valid(empty_allowed) and effective_validator.is_valid(empty_allowed))
    record("original_snapshot_sha256_unchanged_after_checks", sha256((ROOT / SNAPSHOT_PATH).read_bytes()) == snapshot_hash == EXPECTED_SNAPSHOT_SHA256)

    passed_count = sum(item["passed"] for item in checks)
    checked = datetime.now(timezone.utc)
    executable = str(Path(sys.executable)).replace(str(ROOT.parent), "<WORKSPACE>")
    report = {
        "checked_at_utc": checked.isoformat(),
        "checked_at_beijing": checked.astimezone(timezone(timedelta(hours=8))).isoformat(),
        "status": "PASS" if passed_count == len(checks) else "FAIL",
        "scope": "B0 effective output contract verification",
        "protocol_fixture_only": True,
        "model_inference_verified": False,
        "prediction_files_written": False,
        "participant_code_executed": False,
        "fixture_notice": "All synthetic replies existed only in process memory; fixture payloads and input chat text are not saved in this report.",
        "clarification_source": "User relayed official clarification on 2026-10-10: output ID must exactly preserve the corresponding input ID; the original test_ pattern must not reject test1 input IDs.",
        "environment": {"python_version": platform.python_version(), "python_full_version": sys.version, "python_executable": executable, "jsonschema_version": version("jsonschema"), "validator": "Draft202012Validator"},
        "snapshot": {"path": SNAPSHOT_PATH, "sha256_before": snapshot_hash, "sha256_after": sha256((ROOT / SNAPSHOT_PATH).read_bytes()), "expected_sha256": EXPECTED_SNAPSHOT_SHA256, "sha256_source": {"manifest_path": MANIFEST_PATH, "manifest_checked_on": manifest["checked_on"], "archive_name": manifest["archive_name"], "archive_sha256": manifest["archive_sha256"], "source_files_entry_path": SOURCE_PATH, "copies_entry_path": SNAPSHOT_PATH}},
        "effective_schema": {"path": EFFECTIVE_PATH, "sha256": sha256(effective_bytes), "constraint_change": "Removed properties.id.pattern only", "annotation_change": "Added top-level description with clarification provenance and independent ID alignment requirement", "removed_pattern": removed_pattern},
        "inputs": {"path": INPUT_PATH, "sha256": sha256(input_bytes), "row_count": len(inputs)},
        "protocol_fixtures": fixture_results,
        "changed_id_alignment_check": {"original_input_id": inputs[0]["id"], "changed_output_id": changed_id_fixture["id"], "effective_schema_passed": changed_effective_pass, "original_schema_passed": changed_original_pass, "alignment_error": alignment_error},
        "structural_negative_cases": negative_results,
        "counts": {"checks_total": len(checks), "checks_passed": passed_count, "checks_failed": len(checks) - passed_count, "protocol_fixtures_total": len(fixture_results), "protocol_fixtures_passed": sum(item["effective_schema_passed"] and item["input_alignment_passed"] for item in fixture_results), "structural_negative_cases_total": len(negative_results), "structural_negative_cases_passed": sum(item["rejected_as_expected"] for item in negative_results)},
        "checks": checks,
        "reproduce": "python reports/integration/verify_b0_effective_schema.py (requires jsonschema; any working directory)",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": report["counts"], "environment": report["environment"], "protocol_fixture_only": True, "model_inference_verified": False, "report": str(REPORT_PATH)}, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
