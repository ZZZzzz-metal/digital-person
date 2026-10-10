"""B1 contract boundaries only; no model, server, database or submission run."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import get_args, get_type_hints

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from b2_core import contracts as c

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("b1_contract_export", ROOT / "contracts/export_schema.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def example(name):
    return json.loads((ROOT / "contracts/examples" / f"{name}.json").read_bytes())


def prediction(**changes):
    value = example("OfficialPrediction")
    value.update(changes)
    return value


def test_all_generated_schemas_and_examples_match_current_dtos():
    artifacts = export.build_artifacts()
    assert export.check_artifacts(artifacts) == []
    for model in export.MODELS:
        schema = json.loads((ROOT / "contracts/schema" / f"{model.__name__}.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        fixture = example(model.__name__)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(fixture)
        assert model.model_validate(fixture).model_dump(mode="json") == fixture
    assert example("CoreReply")["is_mock"] is True
    assert example("ChatResponse")["is_mock"] is True
    assert example("Health")["is_mock"] is True
    assert "is_mock" not in example("CoreRequest")


@pytest.mark.parametrize("model,field", [(c.CoreRequest, "messages"), (c.OfficialRequest, "history")])
@pytest.mark.parametrize("history", [[], [{"role": "assistant", "content": "fixture"}], [{"role": "user", "content": ""}], [{"role": "user", "content": " \n "}]])
def test_generation_input_requires_nonblank_last_user(model, field, history):
    value = {field: history}
    if model is c.OfficialRequest:
        value["sample_id"] = "test1_000001_t5"
    with pytest.raises(ValidationError):
        model.model_validate(value)


def test_request_preserves_history_without_reappending_or_text_deduplication():
    history = [{"role": "user", "content": "same"}, {"role": "assistant", "content": "fixture"}, {"role": "user", "content": "same"}]
    request = c.CoreRequest(messages=history)
    assert request.model_dump()["messages"] == history
    assert len(request.messages) == 3
    assert c.OfficialRequest(sample_id="test1_000001_t5", history=history).model_dump()["history"] == history


def test_official_request_preserves_source_id_without_prefix_conversion():
    history = [{"role": "user", "content": "fixture"}]
    for sample_id in ["test1_000001_t5", "arbitrary-source-id", " source-id-with-spaces "]:
        request = c.OfficialRequest(sample_id=sample_id, history=history)
        assert request.sample_id == sample_id
        assert request.model_dump()["sample_id"] == sample_id
    for value in [{"history": history}, {"sample_id": " \n ", "history": history}]:
        with pytest.raises(ValidationError):
            c.OfficialRequest.model_validate(value)


@pytest.mark.parametrize("changed", [{"max_new_tokens": 0}, {"max_new_tokens": 4097}, {"max_new_tokens": "256"}, {"temperature": -0.1}, {"temperature": 2.1}, {"user_id": "unexpected"}])
def test_core_request_rejects_invalid_generation_controls_and_metadata(changed):
    value = example("CoreRequest")
    value.update(changed)
    with pytest.raises(ValidationError):
        c.CoreRequest.model_validate(value)


def test_engine_protocols_expose_metadata_and_separate_generation_types():
    assert get_type_hints(c.Engine)["is_mock"] is bool
    assert get_type_hints(c.Engine)["model_version"] is str
    assert get_type_hints(c.Engine.generate) == {"request": c.CoreRequest, "return": c.CoreReply}
    assert get_type_hints(c.OfficialEngine)["is_mock"] is bool
    assert get_type_hints(c.OfficialEngine)["model_version"] is str
    assert get_type_hints(c.OfficialEngine.generate_official) == {"request": c.OfficialRequest, "return": c.OfficialPrediction}


@pytest.mark.parametrize("field,value", [("is_mock", "false"), ("model_version", " "), ("reply", "\n"), ("emotion", "joy"), ("expression", "invented")])
def test_demo_reply_has_strict_mock_metadata_and_demo_enums(field, value):
    reply = example("CoreReply")
    reply[field] = value
    with pytest.raises(ValidationError):
        c.CoreReply.model_validate(reply)


def test_official_enums_and_successful_prediction_match_b0_source():
    source = json.loads((ROOT / "contracts/official/model_prediction.schema.json").read_bytes())
    properties = source["properties"]
    assert list(get_args(c.OfficialEmotion)) == properties["emotion_label"]["enum"]
    profile = properties["user_profile"]["properties"]
    for field, enum in [("personality_traits", c.OfficialPersonality), ("interests", c.OfficialInterest), ("style", c.OfficialStyle)]:
        assert list(get_args(enum)) == profile[field]["items"]["enum"]
    fixture = prediction()
    Draft202012Validator(source).validate(fixture)
    assert c.OfficialPrediction.model_validate(fixture).model_dump() == fixture
    assert set(c.OfficialPrediction.model_fields) == set(source["required"])
    for emotion in get_args(c.OfficialEmotion):
        assert c.OfficialPrediction.model_validate(prediction(emotion_label=emotion)).emotion_label == emotion


@pytest.mark.parametrize("field", ["personality_traits", "interests", "style"])
def test_official_profile_rejects_duplicate_and_unknown_labels(field):
    value = example("OfficialProfile")
    valid_label = {"personality_traits": "open", "interests": "music", "style": "brief"}[field]
    value[field] = [valid_label, valid_label]
    with pytest.raises(ValidationError):
        c.OfficialProfile.model_validate(value)
    value[field] = ["invented"]
    with pytest.raises(ValidationError):
        c.OfficialProfile.model_validate(value)
    with pytest.raises(ValidationError):
        c.OfficialProfile.model_validate({"personality_traits": [], "interests": []})


@pytest.mark.parametrize("refs", [["mem_000001", "mem_000001"], ["memory-fixture-1"], ["mem_00001"], ["mem_１２３４５６"], ["mem_000001\n"]])
def test_official_reference_format_and_uniqueness_are_runtime_constraints(refs):
    with pytest.raises(ValidationError):
        c.OfficialPrediction.model_validate(prediction(memory_refs=refs))
    assert c.OfficialPrediction.model_validate(prediction(memory_refs=["mem_000001"])).memory_refs == ["mem_000001"]


@pytest.mark.parametrize("field,value", [("id", "test1_000001_t5"), ("sample_id", "test1_000001_t5"), ("is_mock", True), ("expression", "smile"), ("model_version", "fixture"), ("elapsed_ms", 0), ("emotion_label", "happy"), ("emotion_label", ""), ("response_text", ""), ("response_text", " \n ")])
def test_official_generation_forbids_sample_id_demo_metadata_and_failed_values(field, value):
    with pytest.raises(ValidationError):
        c.OfficialPrediction.model_validate(prediction(**{field: value}))


def test_memories_timestamps_and_chat_boundaries():
    assert c.MemorySave(value=" " + "x" * 200 + " ").value == "x" * 200
    for value in [" ", "x" * 201, 5]:
        with pytest.raises(ValidationError):
            c.MemorySave(value=value)
    item = example("MemoryItem")
    for change in [{"key": "diagnosis"}, {"updated_at": "2026-10-10T08:00:00+08:00"}, {"updated_at": "2026-02-30T00:00:00Z"}]:
        with pytest.raises(ValidationError):
            c.MemoryItem.model_validate({**item, **change})
    for text in ["", " \n ", "x" * 2001]:
        with pytest.raises(ValidationError):
            c.ChatRequest(session_id="s", client_turn_id="t", text=text)
    assert c.ChatRequest(session_id="s", client_turn_id="t", text="x" * 2000).text == "x" * 2000


def test_package_import_cannot_import_model_libraries_or_server():
    code = """
import importlib.abc
import sys
class RejectModelImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'b2_core.model' or fullname.split('.')[0] in {'torch', 'transformers', 'server'}:
            raise AssertionError('Type-only import attempted: ' + fullname)
sys.meta_path.insert(0, RejectModelImports())
import b2_core
from b2_core import CoreRequest, OfficialPrediction
assert 'b2_core.model' not in sys.modules
assert not {'torch', 'transformers', 'server'} & set(sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, " + repr(str(ROOT / "src")) + ");" + code], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
