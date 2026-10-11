"""CPU CLI protocol fixtures, never real model/performance submissions."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from threading import Event

import pytest

from b2_core.store import InMemoryStore
from submission.participant.adapter import SubmissionError, validate_submission, read_input
from submission.participant import run_inference
from submission.participant.run_inference import run_batch, validate_performance


def write_input(path, count=3):
    rows = [
        {"id": f"fixture-{index}", "conversation_id": "same-fixture-conversation", "history": [
            {"role": "user", "content": f"虚构独立样本-{index}"},
        ]}
        for index in range(count)
    ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return rows


class CliProtocolFixtureEngine:
    """Required nonmock declaration tests contracts only, not a real model."""

    is_mock = False
    model_version = "unit-only-cli-protocol-fixture"

    def __init__(self):
        self.calls = []
        self.last_trace = {}
        self.failure_at = None

    def generate_official(self, request):
        self.calls.append(request.model_copy(deep=True))
        if self.failure_at == len(self.calls):
            raise RuntimeError("DO_NOT_LOG_PRIVATE_FIXTURE_INPUT")
        self.last_trace = {"parse_failures": 0, "mode": "fixture", "source": "fixture-only"}
        return {
            "response_text": "【协议fixture】测试固定回复，非模型预测", "emotion_label": "neutral",
            "user_profile": {"personality_traits": [], "interests": [], "style": []}, "memory_refs": [],
        }


def performance(result_dir):
    return json.loads((result_dir / "performance_report.json").read_text(encoding="utf-8"))


def assert_no_success_files(directory):
    assert not (directory / "submission.jsonl").exists()
    assert not (directory / "performance_report.json").exists()


def test_batch_initializes_once_and_uses_one_fresh_closed_memory_store_per_sample(tmp_path):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    rows = write_input(path)
    engines, stores, synchronizations = [], [], []

    class TrackedStore(InMemoryStore):
        def __init__(self):
            super().__init__()
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            super().close()

    def store_factory():
        instance = TrackedStore()
        stores.append(instance)
        return instance

    def engine_factory():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        engine = CliProtocolFixtureEngine()
        engines.append(engine)
        return engine

    returned = run_batch(path, directory, engine_factory=engine_factory, hardware_label="CPU protocol fixture only", synchronize=lambda: synchronizations.append("sync"), store_factory=store_factory)
    assert isinstance(returned, dict)
    assert len(engines) == 1 and len(engines[0].calls) == 3
    assert len(stores) == len({id(instance) for instance in stores}) == 3
    assert all(instance.close_calls == 1 and instance._closed for instance in stores)
    assert len(synchronizations) == 6
    for original, request in zip(rows, engines[0].calls):
        assert request.memory_context == ""
        assert [m.content for m in request.history] == [original["history"][0]["content"]]
    report = performance(directory)
    assert report["samples"] == report["rounds"] == 3
    assert report["required_rounds"] == 100 and report["complete"] is False
    assert report["hardware_label"] == "CPU protocol fixture only"
    assert report["test_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    requests, _ = read_input(path)
    checked = validate_submission(requests, directory / "submission.jsonl")
    assert report["submission_sha256"] == checked["sha256"]
    assert {item.name for item in directory.iterdir()} == {"submission.jsonl", "performance_report.json"}


def test_batch_outputs_all_101_samples_but_statistics_cover_first_100(tmp_path):
    path, directory = tmp_path / "101.jsonl", tmp_path / "output"
    write_input(path, 101)
    engine = CliProtocolFixtureEngine()
    run_batch(path, directory, engine_factory=lambda: engine, hardware_label="CPU protocol fixture only", synchronize=lambda: None)
    report = performance(directory)
    assert report["samples"] == len(engine.calls) == 101
    assert len((directory / "submission.jsonl").read_text(encoding="utf-8").splitlines()) == 101
    assert report["required_rounds"] == report["rounds"] == len(report["latencies_ms"]) == 100
    assert report["complete"] is True
    values = report["latencies_ms"]
    assert all(isinstance(value, (int, float)) and value >= 0 and round(value, 6) == value for value in values)
    assert report["min_latency_ms"] == min(values)
    assert report["max_latency_ms"] == max(values)
    assert report["average_latency_ms"] == pytest.approx(statistics.fmean(values), abs=1e-6)
    assert report["median_latency_ms"] == pytest.approx(statistics.median(values), abs=1e-6)
    assert report["p95_latency_ms"] == sorted(values)[94]


@pytest.mark.parametrize("kind", ["missing-input", "empty-input", "invalid-later-row"])
def test_all_input_preflight_finishes_before_model_initialization(tmp_path, kind):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    if kind == "empty-input":
        path.write_text("\n", encoding="utf-8")
    elif kind == "invalid-later-row":
        write_input(path, 1)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"id":"fixture-bad","history":[]}\n')
    calls = []

    def factory():
        calls.append("initialize")
        return CliProtocolFixtureEngine()

    with pytest.raises(SubmissionError):
        run_batch(path, directory, engine_factory=factory)
    assert calls == []
    assert_no_success_files(directory)


@pytest.mark.parametrize("existing", ["submission.jsonl", "performance_report.json"])
def test_existing_candidate_is_never_overwritten_and_model_not_initialized(tmp_path, existing):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    directory.mkdir()
    original = b"retained-existing-candidate"
    (directory / existing).write_bytes(original)
    (directory / "other-team-file.txt").write_text("保留旁文件", encoding="utf-8")
    calls = []

    def factory():
        calls.append("initialize")
        return CliProtocolFixtureEngine()

    with pytest.raises(SubmissionError):
        run_batch(path, directory, engine_factory=factory)
    assert calls == []
    assert (directory / existing).read_bytes() == original
    assert (directory / "other-team-file.txt").read_text(encoding="utf-8") == "保留旁文件"
    assert {item.name for item in directory.iterdir()} == {existing, "other-team-file.txt"}


def test_generation_failure_closes_stores_leaves_no_success_and_hides_private_text(tmp_path, capsys, caplog):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    rows = write_input(path)
    rows[1]["history"][0]["content"] = "DO_NOT_LOG_PRIVATE_FIXTURE_INPUT"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    directory.mkdir()
    (directory / "other-team-file.txt").write_text("保留旁文件", encoding="utf-8")
    engine = CliProtocolFixtureEngine()
    engine.failure_at = 2
    stores = []

    def factory():
        instance = InMemoryStore()
        stores.append(instance)
        return instance

    with pytest.raises(SubmissionError) as failure:
        run_batch(path, directory, engine_factory=lambda: engine, store_factory=factory)
    assert len(stores) == 2 and all(instance._closed for instance in stores)
    assert_no_success_files(directory)
    assert (directory / "other-team-file.txt").read_text(encoding="utf-8") == "保留旁文件"
    assert {item.name for item in directory.iterdir()} == {"other-team-file.txt"}
    captured = capsys.readouterr()
    assert "DO_NOT_LOG_PRIVATE_FIXTURE_INPUT" not in str(failure.value)
    assert "DO_NOT_LOG_PRIVATE_FIXTURE_INPUT" not in captured.out + captured.err + caplog.text


def test_parse_failures_count_failed_samples_once_not_retry_attempts(tmp_path):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 3)

    class TraceFixture(CliProtocolFixtureEngine):
        def generate_official(self, request):
            result = super().generate_official(request)
            if len(self.calls) in {1, 3}:
                self.last_trace = {"parse_failures": 2, "mode": "fixture", "source": "fixture-only-retry"}
            return result

    run_batch(path, directory, engine_factory=TraceFixture)
    report = performance(directory)
    assert report["parse_failure_count"] == 2
    assert report["parse_failure_ids"] == ["fixture-0", "fixture-2"]


@pytest.mark.parametrize("invalid", [True, -1])
def test_invalid_trace_parse_count_cannot_be_reported_as_success(tmp_path, invalid):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)

    class InvalidTraceFixture(CliProtocolFixtureEngine):
        def generate_official(self, request):
            result = super().generate_official(request)
            self.last_trace = {"parse_failures": invalid}
            return result

    with pytest.raises(SubmissionError):
        run_batch(path, directory, engine_factory=InvalidTraceFixture)
    assert_no_success_files(directory)


def test_model_initialization_failure_is_sanitized_and_keeps_unrelated_file(tmp_path, capsys, caplog):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    directory.mkdir()
    (directory / "other-team-file.txt").write_text("保留旁文件", encoding="utf-8")

    def failing_factory():
        raise RuntimeError("DO_NOT_LOG_PRIVATE_FIXTURE_ASSET_PATH")

    with pytest.raises(SubmissionError) as failure:
        run_batch(path, directory, engine_factory=failing_factory)
    assert_no_success_files(directory)
    assert {item.name for item in directory.iterdir()} == {"other-team-file.txt"}
    captured = capsys.readouterr()
    assert "DO_NOT_LOG_PRIVATE_FIXTURE_ASSET_PATH" not in str(failure.value)
    assert "DO_NOT_LOG_PRIVATE_FIXTURE_ASSET_PATH" not in captured.out + captured.err + caplog.text


def test_two_batches_same_result_directory_do_not_overwrite_or_initialize_loser(tmp_path):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    entered, release = Event(), Event()
    loser_calls = []

    class BlockingFixture(CliProtocolFixtureEngine):
        def generate_official(self, request):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("fixture-only concurrency deadline")
            return super().generate_official(request)

    def loser_factory():
        loser_calls.append("initialize")
        return CliProtocolFixtureEngine()

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run_batch, path, directory, engine_factory=BlockingFixture)
        try:
            assert entered.wait(timeout=3)
            assert_no_success_files(directory)
            with pytest.raises(SubmissionError):
                run_batch(path, directory, engine_factory=loser_factory)
            assert loser_calls == []
            release.set()
            assert isinstance(first.result(timeout=3), dict)
            assert performance(directory)["samples"] == 1
        finally:
            release.set()


def test_second_publish_failure_rolls_back_first_owned_link_and_preserves_other_file(tmp_path, monkeypatch):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    directory.mkdir()
    (directory / "other-team-file.txt").write_bytes(b"retained-foreign-file")
    original_link = os.link
    published = []

    def fail_second_link(source, destination, *args, **kwargs):
        destination = Path(destination)
        if destination.name == "performance_report.json":
            assert (directory / "submission.jsonl").exists()
            assert published == ["submission.jsonl"]
            raise OSError("fixture-only second link failure")
        original_link(source, destination, *args, **kwargs)
        published.append(destination.name)

    monkeypatch.setattr(run_inference.os, "link", fail_second_link)
    with pytest.raises(SubmissionError) as failure:
        run_batch(path, directory, engine_factory=CliProtocolFixtureEngine)
    assert failure.value.code == "OUTPUT_IO"
    assert_no_success_files(directory)
    assert {item.name for item in directory.iterdir()} == {"other-team-file.txt"}
    assert (directory / "other-team-file.txt").read_bytes() == b"retained-foreign-file"


@pytest.mark.parametrize("foreign_name", ["submission.jsonl", "performance_report.json"])
def test_foreign_final_created_after_preflight_is_preserved_without_overwrite(tmp_path, foreign_name):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    directory.mkdir()
    other = directory / "other-team-file.txt"
    other.write_bytes(b"retained-side-file")
    foreign_bytes = b"external-writer-candidate-fixture"

    def factory():
        # Factory is called only after initial output checks and lock creation.
        assert (directory / ".b5-run.lock").exists()
        (directory / foreign_name).write_bytes(foreign_bytes)
        return CliProtocolFixtureEngine()

    with pytest.raises(SubmissionError) as failure:
        run_batch(path, directory, engine_factory=factory)
    assert failure.value.code == "OUTPUT_IO"
    assert (directory / foreign_name).read_bytes() == foreign_bytes
    assert {item.name for item in directory.iterdir()} == {foreign_name, other.name}
    assert other.read_bytes() == b"retained-side-file"


def test_failure_cleanup_does_not_delete_a_replacement_foreign_lock(tmp_path):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    foreign_lock_bytes = b"external-run-lock-fixture"
    lock_path = directory / ".b5-run.lock"

    def factory():
        assert lock_path.exists()
        lock_path.unlink()
        lock_path.write_bytes(foreign_lock_bytes)
        raise RuntimeError("fixture-only initialization failure after lock replacement")

    with pytest.raises(SubmissionError):
        run_batch(path, directory, engine_factory=factory)
    assert_no_success_files(directory)
    assert lock_path.read_bytes() == foreign_lock_bytes
    assert {item.name for item in directory.iterdir()} == {".b5-run.lock"}


@pytest.fixture
def measured_fixture_report(tmp_path):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 3)
    report = run_batch(path, directory, engine_factory=CliProtocolFixtureEngine, hardware_label="CPU protocol fixture only")
    requests, input_sha = read_input(path)
    submission_sha = hashlib.sha256((directory / "submission.jsonl").read_bytes()).hexdigest()
    validate_performance(report, requests, input_sha, submission_sha)
    return report, requests, input_sha, submission_sha


@pytest.mark.parametrize("invalid", ["input-hash", "submission-hash", "complete", "rounds", "nan", "statistics", "unknown-parse-id", "duplicate-parse-id", "parse-id-order"])
def test_performance_validation_rejects_tampered_report(measured_fixture_report, invalid):
    report, requests, input_sha, submission_sha = measured_fixture_report
    altered = deepcopy(report)
    if invalid == "input-hash":
        altered["test_file_sha256"] = "0" * 64
    elif invalid == "submission-hash":
        altered["submission_sha256"] = "0" * 64
    elif invalid == "complete":
        altered["complete"] = True
    elif invalid == "rounds":
        altered["rounds"] = True
    elif invalid == "nan":
        altered["latencies_ms"][0] = float("nan")
    elif invalid == "statistics":
        altered["p95_latency_ms"] += 1
    elif invalid == "unknown-parse-id":
        altered["parse_failure_ids"], altered["parse_failure_count"] = ["unknown-fixture-id"], 1
    elif invalid == "duplicate-parse-id":
        altered["parse_failure_ids"] = [requests[0].sample_id, requests[0].sample_id]
        altered["parse_failure_count"] = 2
    elif invalid == "parse-id-order":
        altered["parse_failure_ids"] = [requests[2].sample_id, requests[0].sample_id]
        altered["parse_failure_count"] = 2
    with pytest.raises(SubmissionError) as failure:
        validate_performance(altered, requests, input_sha, submission_sha)
    assert failure.value.code == "PERFORMANCE_INVALID"


def test_subprocess_missing_config_exits_one_without_success_or_private_input_log(tmp_path):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    rows = write_input(path, 1)
    rows[0]["history"][0]["content"] = "DO_NOT_LOG_PRIVATE_SUBPROCESS_FIXTURE_INPUT"
    path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    script = Path(run_inference.__file__).resolve()
    result = subprocess.run(
        [sys.executable, str(script), str(path), str(directory), "--config", str(tmp_path / "missing-config.json")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 1
    assert_no_success_files(directory)
    assert "DO_NOT_LOG_PRIVATE_SUBPROCESS_FIXTURE_INPUT" not in result.stdout + result.stderr
    failure_events = [json.loads(line) for line in result.stderr.splitlines() if line.strip()]
    assert failure_events == [{
        "event": "batch_failed", "code": "MODEL_CONFIG_MISSING",
        "message": failure_events[0]["message"],
    }]
    assert "Traceback" not in result.stderr


def test_factory_private_submission_error_is_sanitized_without_removing_other_file(tmp_path, capsys, caplog):
    path, directory = tmp_path / "input.jsonl", tmp_path / "output"
    write_input(path, 1)
    directory.mkdir()
    retained = directory / "other-team-file.txt"
    retained.write_bytes(b"retained-foreign-file")

    def factory():
        raise SubmissionError("PRIVATE_FIXTURE_CODE", "PRIVATE正文")

    with pytest.raises(SubmissionError) as failure:
        run_batch(path, directory, engine_factory=factory)
    assert failure.value.code == "MODEL_UNAVAILABLE"
    assert_no_success_files(directory)
    assert {item.name for item in directory.iterdir()} == {retained.name}
    assert retained.read_bytes() == b"retained-foreign-file"
    captured = capsys.readouterr()
    visible = str(failure.value) + captured.out + captured.err + caplog.text
    assert "PRIVATE_FIXTURE_CODE" not in visible and "PRIVATE正文" not in visible


def test_subprocess_offline_guard_blocks_all_connections_without_changing_pytest_sockets():
    source = """
import json
import os
import socket
from submission.participant.run_inference import force_offline

force_offline()
checked = []
with socket.socket() as connection:
    operations = [
        ('connect', lambda: connection.connect(('127.0.0.1', 9))),
        ('connect_ex', lambda: connection.connect_ex(('127.0.0.1', 9))),
        ('sendto', lambda: connection.sendto(b'fixture-only', ('127.0.0.1', 9))),
        ('create_connection', lambda: socket.create_connection(('127.0.0.1', 9))),
    ]
    for name, operation in operations:
        try:
            operation()
        except OSError as error:
            assert str(error) == 'B5 offline runner forbids network connections'
            checked.append(name)
        else:
            raise AssertionError(name + ' was not blocked')
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['TRANSFORMERS_OFFLINE'] == '1'
print(json.dumps({'blocked': checked, 'hf_offline': '1', 'transformers_offline': '1'}))
"""
    project = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-c", source], cwd=project, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "blocked": ["connect", "connect_ex", "sendto", "create_connection"],
        "hf_offline": "1", "transformers_offline": "1",
    }
