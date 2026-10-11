"""Strict, stateless official input/output boundaries, separate from demo chat.

This module loads no model, server, store, Torch or network client. Shared DTOs
are imported lazily so the CLI can discover runtime_root before adding its
bundled src directory to the Python import path. Errors contain categories and
generic messages, never input content or underlying model exception text.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from b2_core.contracts import OfficialRequest


class SubmissionError(RuntimeError):
    """A safe public error; callers must not print an exception's raw context."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def runtime_root() -> Path:
    """Prefer a self-contained /root/participant bundle, else the repo root."""
    participant = Path(__file__).resolve().parent
    if (participant / "src/b2_core/contracts.py").is_file() and (participant / "contracts/official").is_dir():
        return participant
    repository = participant.parent.parent
    if (repository / "src/b2_core/contracts.py").is_file() and (repository / "contracts/official").is_dir():
        return repository
    raise SubmissionError("RUNTIME_UNAVAILABLE", "Official runtime layout is missing")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON constant")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def load_json(text: str) -> Any:
    """Reject duplicate keys at every depth and all non-finite numbers."""
    if not isinstance(text, str):
        raise SubmissionError("INVALID_JSON", "JSON input must be text")
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except Exception:
        raise SubmissionError("INVALID_JSON", "JSON is malformed or ambiguous") from None


@lru_cache(maxsize=4)
def _validator(path: Path) -> Draft202012Validator:
    try:
        schema = load_json(path.read_text(encoding="utf-8-sig"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except Exception:
        raise SubmissionError("SCHEMA_UNAVAILABLE", "Official schema is missing or invalid") from None


def _validate_schema(filename: str, value: Any, *, code: str, message: str) -> None:
    validator = _validator(runtime_root() / "contracts/official" / filename)
    try:
        validator.validate(value)
    except Exception:
        raise SubmissionError(code, message) from None


def _payload(value: Any) -> dict:
    if isinstance(value, dict):
        payload = value
    else:
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            payload = dump(mode="python")
        elif is_dataclass(value) and not isinstance(value, type):
            payload = asdict(value)
        else:
            raise ValueError("unsupported DTO representation")
    if not isinstance(payload, dict):
        raise ValueError("DTO dump must be an object")
    return deepcopy(payload)


def _fresh_request(request: OfficialRequest) -> OfficialRequest:
    from b2_core.contracts import OfficialRequest

    try:
        return OfficialRequest.model_validate(_payload(request))
    except Exception:
        raise SubmissionError("INVALID_INPUT", "Official request does not satisfy the contract") from None


def project_sample(row: dict) -> OfficialRequest:
    from b2_core.contracts import OfficialRequest

    _validate_schema(
        "inference_input.schema.json", row,
        code="INVALID_INPUT", message="Input sample does not satisfy the contract",
    )
    history = row["history"]
    previous_id = None
    for turn in history:
        if "turn_id" in turn:
            turn_id = turn["turn_id"]
            # JSON Schema treats 1.0 as an integer; our metadata is stricter.
            if type(turn_id) is not int or turn_id <= 0:
                raise SubmissionError("INVALID_INPUT", "Provided turn IDs must be positive integers")
            if previous_id is not None and turn_id <= previous_id:
                raise SubmissionError("INVALID_INPUT", "Provided turn IDs must be unique and increasing")
            previous_id = turn_id
    if "target_user_turn_id" in row:
        target = row["target_user_turn_id"]
        if type(target) is not int or target <= 0:
            raise SubmissionError("INVALID_INPUT", "Target turn ID must be a positive integer")
        if history[-1].get("turn_id") != target or history[-1]["role"] != "user":
            raise SubmissionError("INVALID_INPUT", "Target must match the last user turn ID")
    try:
        # Ignore all other raw fields, including training labels and answers.
        # Preserve every supplied history message without demo length limits.
        return OfficialRequest.model_validate({
            "sample_id": row["id"],
            "history": [{"role": turn["role"], "content": turn["content"]} for turn in history],
            "memory_context": "",
        })
    except Exception:
        raise SubmissionError("INVALID_INPUT", "Input history must end with a nonblank user message") from None


def read_input(path: Path) -> tuple[list[OfficialRequest], str]:
    path = Path(path)
    if path.suffix.lower() != ".jsonl":
        raise SubmissionError("INVALID_INPUT", "Input must be a JSONL file")
    try:
        raw = path.read_bytes()
    except OSError:
        raise SubmissionError("INPUT_IO", "Input file cannot be read") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise SubmissionError("INVALID_INPUT", "Input must use UTF-8 encoding") from None
    requests = []
    seen = set()
    # Only physical JSONL newlines delimit records; Unicode separators such as
    # U+2028 may legally occur inside a JSON string and must remain untouched.
    for number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            request = project_sample(load_json(line))
        except SubmissionError as exc:
            # Line position is safe; the raw line and model content are not.
            raise SubmissionError(exc.code, f"Input line {number} failed validation") from None
        if request.sample_id in seen:
            raise SubmissionError("INVALID_INPUT", f"Input line {number} repeats a sample ID")
        seen.add(request.sample_id)
        requests.append(request)
    if not requests:
        raise SubmissionError("INVALID_INPUT", "Input contains no samples")
    return requests, hashlib.sha256(raw).hexdigest()


def make_output(sample_id: str, prediction: Any) -> dict:
    from b2_core.contracts import OfficialPrediction

    if not isinstance(sample_id, str) or not sample_id.strip():
        raise SubmissionError("INVALID_PREDICTION", "Output requires the unchanged nonblank sample ID")
    try:
        # Dump the entire object: never drop extras, fill absent fields or
        # treat the official schema's failure blanks as successful prediction.
        validated = OfficialPrediction.model_validate(_payload(prediction))
    except Exception:
        raise SubmissionError("INVALID_PREDICTION", "Prediction does not satisfy the success contract") from None
    if validated.memory_refs:
        raise SubmissionError("INVALID_PREDICTION", "Public-input predictions must use empty memory references")
    output = {"id": sample_id, **validated.model_dump(mode="python")}
    _validate_schema(
        "effective_submission.schema.json", output,
        code="INVALID_PREDICTION", message="Prediction does not satisfy the effective output schema",
    )
    return output


def _engine_metadata(engine: Any) -> tuple[bool, str]:
    is_mock = getattr(engine, "is_mock", None)
    version = getattr(engine, "model_version", None)
    if is_mock is not False or not isinstance(version, str) or not version.strip():
        raise ValueError("official engine metadata is invalid")
    return is_mock, version


def run_official(request: OfficialRequest, engine: Any) -> dict:
    validated = _fresh_request(request)
    sample_id = validated.sample_id
    try:
        before = _engine_metadata(engine)
        generate = getattr(engine, "generate_official", None)
        if not callable(generate):
            raise ValueError("official generator is unavailable")
    except Exception:
        raise SubmissionError("MODEL_UNAVAILABLE", "A non-mock official engine is required") from None
    try:
        prediction = generate(validated)
    except Exception:
        # Even a model-raised SubmissionError is replaced, not passed through.
        raise SubmissionError("MODEL_UNAVAILABLE", "Official model generation failed") from None
    output = make_output(sample_id, prediction)
    try:
        after = _engine_metadata(engine)
    except Exception:
        raise SubmissionError("MODEL_UNAVAILABLE", "Official engine metadata changed during generation") from None
    if after != before:
        raise SubmissionError("MODEL_UNAVAILABLE", "Official engine metadata changed during generation")
    return output


def validate_submission(requests: list[OfficialRequest], path: Path) -> dict:
    """Independently re-read strict JSONL and check every row/ID in order."""
    if not isinstance(requests, list) or not requests:
        raise SubmissionError("INVALID_INPUT", "Expected input samples are required")
    expected = [_fresh_request(request) for request in requests]
    if len({request.sample_id for request in expected}) != len(expected):
        raise SubmissionError("INVALID_INPUT", "Expected input IDs must be unique")
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise SubmissionError("SUBMISSION_IO", "Submission file cannot be read") from None
    try:
        lines = raw.decode("utf-8").split("\n")
    except UnicodeError:
        raise SubmissionError("INVALID_SUBMISSION", "Submission must use UTF-8 encoding") from None
    if lines and lines[-1] == "":
        lines.pop()  # A single final JSONL newline is expected, not a record.
    if len(lines) != len(expected):
        raise SubmissionError("INVALID_SUBMISSION", "Submission sample count differs from input")
    for number, (line, request) in enumerate(zip(lines, expected), 1):
        try:
            row = load_json(line)
            _validate_schema(
                "effective_submission.schema.json", row,
                code="INVALID_SUBMISSION", message="Submission row violates the output schema",
            )
            if row["id"] != request.sample_id:
                raise ValueError("sample ID mismatch")
            make_output(row["id"], {key: value for key, value in row.items() if key != "id"})
        except Exception:
            raise SubmissionError("INVALID_SUBMISSION", f"Submission line {number} failed validation") from None
    return {"samples": len(expected), "sha256": hashlib.sha256(raw).hexdigest()}
