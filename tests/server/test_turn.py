"""Pure B4 turn checks; all generation fixtures are explicitly mock."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from b2_core.contracts import CoreReply, CoreRequest, Message
from b2_core.turn import build_core_request, run_turn


class FixtureEngine:
    is_mock = True
    model_version = "unit-only-mock"

    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else CoreReply(
            reply="【演示数据】固定测试回复", model_version=self.model_version, is_mock=True,
        )

    def generate(self, request):
        self.calls.append(request)
        return self.result


def reply_data(**updates):
    data = {
        "reply": "【演示数据】固定测试回复", "emotion": "unknown",
        "expression": "listening", "model_version": "unit-only-mock", "is_mock": True,
    }
    data.update(updates)
    return data


def pair(index, *, user="虚构输入", assistant="【演示数据】回复"):
    return [Message(role="user", content=f"{user}-{index}"), Message(role="assistant", content=f"{assistant}-{index}")]


def test_history_takes_latest_six_complete_pairs_and_current_exactly_once():
    history = [message for index in range(8) for message in pair(index)]
    before = [message.model_dump() for message in history]
    request = build_core_request("本次独立输入", history, "用户事实fixture")
    assert request.messages[:-1] == history[-12:]
    assert request.messages[-1] == Message(role="user", content="本次独立输入")
    assert len(request.messages) == 13
    assert sum(message.content == "本次独立输入" for message in request.messages) == 1
    assert request.memory_context == "用户事实fixture"
    request.messages[0].content = "篡改返回历史"
    assert [message.model_dump() for message in history] == before


def test_character_limit_removes_whole_old_pairs_without_truncating_current():
    history = [
        Message(role=role, content=character * 1000)
        for character in ("甲", "乙", "丙") for role in ("user", "assistant")
    ]
    current = "现" * 2000
    request = build_core_request(current, history)
    assert request.messages[:-1] == history[-4:]
    assert sum(len(message.content) for message in request.messages[:-1]) == 4000
    assert [message.role for message in request.messages] == ["user", "assistant", "user", "assistant", "user"]
    assert request.messages[-1].content == current
    oversized = [Message(role="user", content="甲" * 2000), Message(role="assistant", content="乙" * 2001)]
    assert build_core_request("当前", oversized).messages == [Message(role="user", content="当前")]


@pytest.mark.parametrize("roles", [["user"], ["assistant"], ["user", "user"], ["assistant", "user"]])
def test_partial_or_reordered_history_is_rejected(roles):
    with pytest.raises(ValueError):
        build_core_request("当前输入", [Message(role=role, content="虚构内容") for role in roles])


@pytest.mark.parametrize("text", ["", " \t", "字" * 2001, True])
def test_current_input_validation(text):
    with pytest.raises((ValueError, TypeError)):
        build_core_request(text, [])


def test_run_turn_revalidates_request_and_uses_an_independent_copy_once():
    request = build_core_request("虚构当前输入", pair(0))
    before = request.model_dump()

    class MutatingFixture(FixtureEngine):
        def generate(self, received):
            self.calls.append(received)
            received.messages[0].content = "fixture修改副本"
            return self.result

    engine = MutatingFixture()
    reply = run_turn(request, engine)
    assert len(engine.calls) == 1
    assert reply.is_mock is True and reply.model_version == engine.model_version
    assert request.model_dump() == before
    reply.reply = "篡改返回回复"
    assert engine.result.reply == "【演示数据】固定测试回复"
    request.messages[-1].role = "assistant"
    with pytest.raises(ValueError):
        run_turn(request, engine)
    assert len(engine.calls) == 1


@dataclass
class DataclassReply:
    reply: str = "【演示数据】dataclass回复"
    emotion: str = "unknown"
    expression: str = "listening"
    model_version: str = "unit-only-mock"
    is_mock: bool = True


class ModelDumpReply:
    def model_dump(self, **kwargs):
        return reply_data()


@pytest.mark.parametrize("result", [reply_data(), DataclassReply(), ModelDumpReply()])
def test_shared_shape_dict_dataclass_and_model_dump_are_accepted(result):
    engine = FixtureEngine(result)
    reply = run_turn(build_core_request("虚构当前输入", []), engine)
    assert isinstance(reply, CoreReply)
    assert reply.is_mock is True
    assert len(engine.calls) == 1


def test_invalid_emotion_and_expression_are_normalized_without_replacing_reply():
    engine = FixtureEngine(reply_data(emotion="invalid-emotion", expression=["invalid-expression"]))
    reply = run_turn(build_core_request("虚构当前输入", []), engine)
    assert reply.reply == "【演示数据】固定测试回复"
    assert reply.emotion == "unknown" and reply.expression == "neutral"
    defaults = FixtureEngine({"reply": "【演示数据】默认字段", "model_version": "unit-only-mock", "is_mock": True})
    assert run_turn(build_core_request("当前", []), defaults).expression == "listening"


@pytest.mark.parametrize("changes", [
    {"reply": " "}, {"reply": 12}, {"is_mock": 1}, {"is_mock": False},
    {"model_version": ""}, {"model_version": "different-version"}, {"model_version": 12},
    {"unexpected": "field"},
])
def test_invalid_result_is_rejected_without_a_fake_success(changes):
    engine = FixtureEngine(reply_data(**changes))
    with pytest.raises((ValueError, TypeError)):
        run_turn(build_core_request("当前", []), engine)
    assert len(engine.calls) == 1


@pytest.mark.parametrize("metadata", [{"is_mock": 0}, {"is_mock": None}, {"model_version": " "}, {"model_version": 12}])
def test_invalid_engine_metadata_fails_before_generate(metadata):
    engine = FixtureEngine()
    for key, value in metadata.items():
        setattr(engine, key, value)
    with pytest.raises((ValueError, TypeError)):
        run_turn(build_core_request("当前", []), engine)
    assert engine.calls == []


def test_engine_exception_propagates_and_no_second_generate_is_attempted():
    calls = []

    def fail(request):
        calls.append(request)
        raise RuntimeError("fixture-only model failure")

    engine = SimpleNamespace(is_mock=True, model_version="unit-only-mock", generate=fail)
    with pytest.raises(RuntimeError, match="fixture-only model failure"):
        run_turn(build_core_request("当前", []), engine)
    assert len(calls) == 1


def test_pure_turn_import_has_no_http_or_model_loading_dependency():
    source = """
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'server', 'fastapi', 'torch', 'transformers'} or fullname == 'b2_core.model':
            raise AssertionError('pure turn imported ' + fullname)
sys.meta_path.insert(0, Guard())
from b2_core.turn import build_core_request, run_turn
assert build_core_request('fixture', []).messages[-1].content == 'fixture'
"""
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    result = subprocess.run([sys.executable, "-c", source], env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
