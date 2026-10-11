"""Generate B1 team schemas/examples, or check committed artifacts without edits."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = ROOT / "contracts"
# Always use this checkout's types, including when run from another directory.
sys.path.insert(0, str(ROOT / "src"))

from b2_core import contracts as c  # noqa: E402

MODELS = (
    c.Message, c.MemoryItem, c.MemoryContext, c.CoreRequest, c.CoreReply,
    c.ChatRequest, c.ChatResponse, c.SessionDTO, c.SessionCreate, c.SessionList,
    c.MessageList, c.MemorySave, c.MemorySettings, c.MemoryList, c.Health,
    c.ErrorDetail, c.ErrorResponse, c.OkResponse, c.OfficialProfile,
    c.OfficialRequest, c.OfficialPrediction,
)


def build_examples() -> dict[str, c.DTO | c.SessionList | c.MessageList]:
    """Fictional protocol fixtures, not model outputs or timing measurements."""
    message = c.Message(role="user", content="【虚构协议样例】我想聊聊复习安排。")
    memory = c.MemoryItem(id="memory-fixture-1", key="exam_subject", value="虚构课程",
                          updated_at="2026-10-10T00:00:00Z")
    core_request = c.CoreRequest(messages=[message])
    core_reply = c.CoreReply(reply="【虚构协议样例】你想从哪部分复习聊起？",
                             emotion="unknown", expression="listening",
                             model_version="protocol-fixture-v1", is_mock=True)
    chat_request = c.ChatRequest(session_id="session-fixture-1", client_turn_id="turn-fixture-1",
                                 text=message.content)
    chat_response = c.ChatResponse(**chat_request.model_dump(exclude={"text"}),
                                   **core_reply.model_dump(), retrieved_memories=[], elapsed_ms=0)
    session = c.SessionDTO(id=chat_request.session_id, title="虚构协议会话",
                           created_at="2026-10-10T00:00:00Z")
    profile = c.OfficialProfile(personality_traits=[], interests=[], style=[])
    error = c.ErrorDetail(code="MODEL_UNAVAILABLE", message="模型暂不可用")
    examples = {
        "Message": message,
        "MemoryItem": memory,
        "MemoryContext": c.MemoryContext(),
        "CoreRequest": core_request,
        "CoreReply": core_reply,
        "ChatRequest": chat_request,
        "ChatResponse": chat_response,
        "SessionDTO": session,
        "SessionCreate": c.SessionCreate(),
        "SessionList": c.SessionList([session]),
        "MessageList": c.MessageList([message]),
        "MemorySave": c.MemorySave(value="虚构课程"),
        "MemorySettings": c.MemorySettings(enabled=True),
        "MemoryList": c.MemoryList(enabled=True, items=[]),
        "Health": c.Health(status="ok", model_ready=True, is_mock=True,
                            model_version="protocol-fixture-v1"),
        "ErrorDetail": error,
        "ErrorResponse": c.ErrorResponse(error=error),
        "OkResponse": c.OkResponse(),
        "OfficialProfile": profile,
        "OfficialRequest": c.OfficialRequest(sample_id="test1_protocol_fixture_t1", history=[message]),
        "OfficialPrediction": c.OfficialPrediction(
            response_text="【protocol fixture】虚构回复，仅用于字段校验。",
            emotion_label="neutral", user_profile=profile, memory_refs=[]),
    }
    return examples


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_artifacts() -> dict[Path, bytes]:
    artifacts: dict[Path, bytes] = {}
    examples = build_examples()
    for model in MODELS:
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$comment"] = "B1 team contract; official snapshots remain separate. Examples are fictional protocol fixtures, not inference verification."
        artifacts[Path("schema") / f"{model.__name__}.schema.json"] = json_bytes(schema)
        example = examples[model.__name__].model_dump(mode="json")
        model.model_validate(example)
        artifacts[Path("examples") / f"{model.__name__}.json"] = json_bytes(example)
    return artifacts


def check_artifacts(artifacts: dict[Path, bytes]) -> list[str]:
    problems = []
    for relative, expected in artifacts.items():
        path = CONTRACTS_ROOT / relative
        if not path.is_file():
            problems.append("missing: " + relative.as_posix())
        elif path.read_bytes() != expected:
            problems.append("different: " + relative.as_posix())
    expected_files = {path.as_posix() for path in artifacts}
    for directory in ("schema", "examples"):
        for path in (CONTRACTS_ROOT / directory).glob("*.json"):
            relative = path.relative_to(CONTRACTS_ROOT).as_posix()
            if relative not in expected_files:
                problems.append("unexpected: " + relative)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare schema/examples; do not write files")
    args = parser.parse_args()
    artifacts = build_artifacts()
    if args.check:
        problems = check_artifacts(artifacts)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
    else:
        for relative, payload in artifacts.items():
            path = CONTRACTS_ROOT / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    print(f"{'Checked' if args.check else 'Generated'} {len(MODELS)} schemas and {len(MODELS)} fictional protocol examples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
