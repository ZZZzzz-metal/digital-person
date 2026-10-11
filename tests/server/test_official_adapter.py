"""B5 protocol fixtures only; no real model, score or container is verified."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from b2_core.contracts import OfficialPrediction, OfficialProfile, OfficialRequest
from submission.participant.adapter import (
    SubmissionError, load_json, make_output, project_sample, read_input,
    run_official, validate_submission,
)


PROJECT = Path(__file__).resolve().parents[2]
PUBLIC_INPUT = PROJECT / "submission/official-reference/test_inference_data.jsonl"


def sample(sample_id="fixture-1"):
    return {
        "id": sample_id, "conversation_id": "fixture-conversation", "target_user_turn_id": 3,
        "history": [
            {"turn_id": 1, "role": "user", "content": "虚构第一条输入"},
            {"turn_id": 2, "role": "assistant", "content": "虚构历史回复"},
            {"turn_id": 3, "role": "user", "content": "虚构当前输入"},
        ],
    }


def prediction():
    return OfficialPrediction(
        response_text="【协议fixture】这是测试固定回复，非模型结果", emotion_label="neutral",
        user_profile=OfficialProfile(personality_traits=[], interests=[], style=[]), memory_refs=[],
    )


class ProtocolFixtureEngine:
    """Required nonmock metadata fixture; never a real inference candidate."""

    is_mock = False
    model_version = "unit-only-official-protocol-fixture"

    def __init__(self, result=None):
        self.calls = []
        self.result = prediction() if result is None else result

    def generate_official(self, request):
        self.calls.append(request.model_copy(deep=True))
        return self.result


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_public_three_samples_preserve_id_current_turn_and_entire_history():
    raw = [json.loads(line) for line in PUBLIC_INPUT.read_text(encoding="utf-8").splitlines()]
    requests, digest = read_input(PUBLIC_INPUT)
    assert digest == hashlib.sha256(PUBLIC_INPUT.read_bytes()).hexdigest()
    assert [r.sample_id for r in requests] == ["test1_000001_t5", "test1_000001_t7", "test1_000002_t5"]
    for row, request in zip(raw, requests):
        assert row["history"][-1]["turn_id"] == row["target_user_turn_id"]
        assert request.history[-1].role == "user"
        assert [(m.role, m.content) for m in request.history] == [(m["role"], m["content"]) for m in row["history"]]
        assert request.memory_context == ""


def test_extra_answer_fields_are_ignored_without_mutating_source():
    row = sample()
    row["target"] = {"assistant_response": "SECRET_FIXTURE_ANSWER"}
    row["emotion_label"] = "SECRET_FIXTURE_LABEL"
    row["memory_context"] = "SECRET_FIXTURE_MEMORY"
    row["history"][0]["reference_answer"] = "SECRET_FIXTURE_HISTORY_ANSWER"
    before = deepcopy(row)
    request = project_sample(row)
    assert set(request.model_dump()) == {"sample_id", "history", "memory_context"}
    assert "SECRET_FIXTURE" not in request.model_dump_json()
    assert row == before
    request.history[0].content = "篡改投影副本"
    assert row == before


def test_official_history_has_no_demo_length_truncation_or_text_deduplication():
    row = sample()
    row["history"] = [
        {"turn_id": index, "role": "user" if index % 2 else "assistant", "content": "字" * (3001 if index == 17 else 300)}
        for index in range(1, 18)
    ]
    row["target_user_turn_id"] = 17
    request = project_sample(row)
    assert len(request.history) == 17
    assert sum(len(m.content) for m in request.history) > 4000
    assert len(request.history[-1].content) == 3001
    repeated = sample("repeated-text-fixture")
    repeated["history"][0]["content"] = repeated["history"][-1]["content"] = "相同但不同轮次的输入"
    result = project_sample(repeated)
    assert len(result.history) == 3
    assert sum(m.content == "相同但不同轮次的输入" for m in result.history) == 2


def test_optional_metadata_can_be_absent_without_inventing_turns():
    request = project_sample({"id": "unprefixed-fixture-id", "history": [{"role": "user", "content": "虚构输入"}]})
    assert request == OfficialRequest(sample_id="unprefixed-fixture-id", history=[{"role": "user", "content": "虚构输入"}], memory_context="")
    partial_ids = sample("partial-metadata-fixture")
    del partial_ids["history"][0]["turn_id"]
    assert len(project_sample(partial_ids).history) == 3


@pytest.mark.parametrize("invalid", [
    "target-assistant", "target-missing", "target-bool", "missing-target-turn",
    "turn-bool", "turn-string", "duplicate-turn", "out-of-order-turn",
    "last-assistant", "blank-content", "empty-history", "blank-id", "nonstr-id", "nonstr-conversation",
])
def test_invalid_input_links_or_types_are_rejected(invalid):
    row = sample()
    if invalid == "target-assistant":
        row["target_user_turn_id"] = 2
    elif invalid == "target-missing":
        row["target_user_turn_id"] = 4
    elif invalid == "target-bool":
        row["target_user_turn_id"] = True
    elif invalid == "missing-target-turn":
        del row["history"][-1]["turn_id"]
    elif invalid == "turn-bool":
        row["history"][0]["turn_id"] = True
    elif invalid == "turn-string":
        row["history"][0]["turn_id"] = "1"
    elif invalid == "duplicate-turn":
        row["history"][1]["turn_id"] = 1
    elif invalid == "out-of-order-turn":
        row["history"][1]["turn_id"], row["history"][2]["turn_id"] = 3, 2
        row["target_user_turn_id"] = 2
    elif invalid == "last-assistant":
        row["history"][-1]["role"] = "assistant"
    elif invalid == "blank-content":
        row["history"][0]["content"] = " \n"
    elif invalid == "empty-history":
        row["history"] = []
    elif invalid == "blank-id":
        row["id"] = " "
    elif invalid == "nonstr-id":
        row["id"] = 12
    elif invalid == "nonstr-conversation":
        row["conversation_id"] = True
    with pytest.raises(SubmissionError):
        project_sample(row)


@pytest.mark.parametrize("text", ['{"id":"one","id":"two"}', '{"nested":{"x":1,"x":2}}', '{"x":NaN}', '{"x":Infinity}'])
def test_json_duplicate_keys_and_nonfinite_numbers_are_rejected(text):
    with pytest.raises(SubmissionError):
        load_json(text)


@pytest.mark.parametrize("kind", ["empty", "duplicate-id", "invalid-json"])
def test_invalid_entire_input_file_is_rejected(tmp_path, kind):
    path = tmp_path / "input.jsonl"
    if kind == "empty":
        path.write_text(" \n\n", encoding="utf-8")
    elif kind == "duplicate-id":
        write_jsonl(path, [sample(), sample()])
    else:
        path.write_text(json.dumps(sample(), ensure_ascii=False) + "\n{broken\n", encoding="utf-8")
    with pytest.raises(SubmissionError):
        read_input(path)


def test_official_fixture_generates_once_and_only_b_adds_input_id():
    request = project_sample(sample("test1_fixture_original_id"))
    engine = ProtocolFixtureEngine()
    output = run_official(request, engine)
    assert len(engine.calls) == 1
    assert engine.calls[0] == request
    assert set(output) == {"id", "response_text", "emotion_label", "user_profile", "memory_refs"}
    assert output["id"] == "test1_fixture_original_id"
    assert output["memory_refs"] == []
    assert "unit-only" not in json.dumps(output)


@pytest.mark.parametrize("metadata", [{"is_mock": True}, {"is_mock": 0}, {"is_mock": None}, {"model_version": " "}, {"model_version": 12}])
def test_mock_or_invalid_metadata_never_calls_official_generate(metadata):
    engine = ProtocolFixtureEngine()
    for key, value in metadata.items():
        setattr(engine, key, value)
    with pytest.raises(SubmissionError):
        run_official(project_sample(sample()), engine)
    assert engine.calls == []


@pytest.mark.parametrize("invalid", ["mutated-dto", "extra-field", "blank-response", "empty-emotion", "invalid-profile", "duplicate-profile", "invalid-ref", "duplicate-ref"])
def test_complete_prediction_is_strictly_revalidated(invalid):
    result = prediction()
    if invalid == "mutated-dto":
        result.emotion_label = ""
    else:
        result = result.model_dump()
        if invalid == "extra-field":
            result["is_mock"] = False
        elif invalid == "blank-response":
            result["response_text"] = " \n"
        elif invalid == "empty-emotion":
            result["emotion_label"] = ""
        elif invalid == "invalid-profile":
            result["user_profile"]["style"] = ["not-an-enum"]
        elif invalid == "duplicate-profile":
            result["user_profile"]["style"] = ["brief", "brief"]
        elif invalid == "invalid-ref":
            result["memory_refs"] = ["mem_000001\n"]
        elif invalid == "duplicate-ref":
            result["memory_refs"] = ["mem_000001", "mem_000001"]
    with pytest.raises(SubmissionError):
        make_output("fixture-id", result)


def test_submission_validation_checks_hash_count_order_id_and_success_dto(tmp_path):
    requests = [project_sample(sample("fixture-a")), project_sample(sample("fixture-b"))]
    rows = [make_output(r.sample_id, prediction()) for r in requests]
    path = tmp_path / "submission.jsonl"
    write_jsonl(path, rows)
    result = validate_submission(requests, path)
    assert result["samples"] == 2
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("invalid", ["order", "missing", "extra", "wrong-id", "blank-emotion", "duplicate-json-key", "invalid-json"])
def test_submission_misalignment_and_invalid_lines_are_rejected(tmp_path, invalid):
    requests = [project_sample(sample("fixture-a")), project_sample(sample("fixture-b"))]
    rows = [make_output(r.sample_id, prediction()) for r in requests]
    if invalid == "order":
        rows.reverse()
    elif invalid == "missing":
        rows.pop()
    elif invalid == "extra":
        rows.append(make_output("fixture-extra", prediction()))
    elif invalid == "wrong-id":
        rows[0]["id"] = "fixture-other"
    elif invalid == "blank-emotion":
        rows[0]["emotion_label"] = ""
    path = tmp_path / "submission.jsonl"
    write_jsonl(path, rows)
    if invalid == "duplicate-json-key":
        path.write_text('{"id":"fixture-a","id":"fixture-b"}\n', encoding="utf-8")
    elif invalid == "invalid-json":
        path.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(SubmissionError):
        validate_submission(requests, path)
