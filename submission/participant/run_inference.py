"""B5 direct local-model inference. No browser, HTTP server or online fallback."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

# Runtime project artifacts belong in RESULT_DIR, including no bytecode caches.
sys.dont_write_bytecode = True

if __package__:
    from .adapter import SubmissionError, load_json, read_input, run_official, runtime_root, validate_submission
else:
    # Checkout scripts retain the same module identity as namespace imports in tests.
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "src/b2_core/contracts.py").is_file():
        sys.path.insert(0, str(checkout))
        from submission.participant.adapter import SubmissionError, load_json, read_input, run_official, runtime_root, validate_submission
    else:
        from adapter import SubmissionError, load_json, read_input, run_official, runtime_root, validate_submission

ROOT = runtime_root()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from b2_core.store import InMemoryStore

REQUIRED_ROUNDS = 100
FINAL_NAMES = ("submission.jsonl", "performance_report.json")
TRACE_FIELDS = ("mode", "parse_failures", "parse_failed", "emotion_source", "profile_source",
                "response_source", "prompt_tokens", "new_tokens", "dropped_turns", "schema_valid")


class _MissingModelConfig(SubmissionError):
    """Only the B preflight creates this diagnostic, outside A initialization."""
    def __init__(self, path: Path):
        self.path = path
        super().__init__("MODEL_CONFIG_MISSING", f"Local model configuration missing: {path}")


def emit(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=True, allow_nan=False), flush=True)


def force_offline() -> None:
    """Process connection guard; Docker --network none remains a B6 check."""
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")

    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise OSError("B5 offline runner forbids network connections")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.create_connection = blocked


class RealOfficialEngine:
    """Expose A's official generator and retain only safe trace metadata."""
    def __init__(self, config: Path):
        if not config.is_file():
            raise _MissingModelConfig(config)
        try:
            from b2_core.model import ModelEngine
            self.engine = ModelEngine(str(config), auto_load=True)
            self.is_mock = self.engine.is_mock
            self.model_version = self.engine.model_version
            if self.is_mock is not False or not isinstance(self.model_version, str) or not self.model_version.strip():
                raise ValueError("invalid real-engine metadata")
            if not callable(getattr(self.engine, "official_trace", None)):
                raise ValueError("A official_trace is required for truthful parse diagnostics")
            self.description = self.engine.describe()
            if self.description.get("loaded") is not True:
                raise ValueError("model not loaded")
        except Exception:
            raise SubmissionError("MODEL_UNAVAILABLE", "A local ModelEngine or complete local weights could not be loaded") from None
        self.last_trace: dict[str, Any] = {}

    def generate_official(self, request: Any) -> Any:
        if self.engine.is_mock is not False or self.engine.model_version != self.model_version:
            raise SubmissionError("ENGINE_METADATA", "Real engine metadata changed")
        prediction, trace = self.engine.official_trace(request)
        if self.engine.is_mock is not False or self.engine.model_version != self.model_version:
            raise SubmissionError("ENGINE_METADATA", "Real engine metadata changed")
        if not isinstance(trace, dict) or trace.get("is_mock") is not False or trace.get("model_version") != self.model_version:
            raise SubmissionError("ENGINE_TRACE", "A official trace metadata is invalid")
        if trace.get("sample_id") != request.sample_id:
            raise SubmissionError("ENGINE_TRACE", "A official trace ID differs from input")
        if type(trace.get("parse_failures")) is not int or trace["parse_failures"] < 0:
            raise SubmissionError("ENGINE_TRACE", "A official parse failure count is invalid")
        self.last_trace = {key: trace[key] for key in TRACE_FIELDS if key in trace}
        return prediction


def latency_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        raise SubmissionError("TIMING_INVALID", "No measured samples")
    ordered = sorted(values)
    return {
        "average_latency_ms": round(statistics.fmean(values), 6),
        "median_latency_ms": round(statistics.median(values), 6),
        "p95_latency_ms": round(ordered[math.ceil(.95 * len(values)) - 1], 6),
        "min_latency_ms": round(min(values), 6),
        "max_latency_ms": round(max(values), 6),
        "latencies_ms": values,
    }


def validate_performance(report: Any, requests: list[Any], input_sha: str, submission_sha: str) -> None:
    """Independent file check shared by check_output; no model needed."""
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise SubmissionError("PERFORMANCE_INVALID", message)

    require(isinstance(report, dict), "Performance report must be an object")
    n = min(len(requests), REQUIRED_ROUNDS)
    for name, value in (("required_rounds", REQUIRED_ROUNDS), ("rounds", n), ("samples", len(requests))):
        require(type(report.get(name)) is int and report[name] == value, f"Invalid {name}")
    require(type(report.get("complete")) is bool and report["complete"] == (n == REQUIRED_ROUNDS), "Invalid complete")
    require(report.get("test_file_sha256") == input_sha and report.get("submission_sha256") == submission_sha, "File digest mismatch")
    for name in ("backend", "version", "hardware_label", "timing_scope"):
        require(isinstance(report.get(name), str) and bool(report[name].strip()), f"Missing {name}")
    values = report.get("latencies_ms")
    require(isinstance(values, list) and len(values) == n, "Timing sample count mismatch")
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values), "Invalid latency")
    expected = latency_summary(values)
    for name in ("average_latency_ms", "median_latency_ms", "p95_latency_ms", "min_latency_ms", "max_latency_ms"):
        value = report.get(name)
        require(type(value) in (int, float) and math.isfinite(value) and abs(value - expected[name]) <= .0000011, f"Invalid {name}")
    ids = report.get("parse_failure_ids")
    require(isinstance(ids, list) and all(isinstance(value, str) for value in ids), "Invalid parse failure IDs")
    require(len(ids) == len(set(ids)), "Duplicate parse failure ID")
    source_ids = [request.sample_id for request in requests]
    require(ids == [value for value in source_ids if value in set(ids)], "Parse failure IDs must follow input order")
    require(type(report.get("parse_failure_count")) is int and report["parse_failure_count"] == len(ids), "Invalid parse failure count")


def run_batch(test_file: Path, result_dir: Path, engine_factory: Callable[[], Any],
              hardware_label: str = "unspecified", synchronize: Callable[[], None] = lambda: None,
              store_factory: Callable[[], Any] = InMemoryStore) -> dict[str, Any]:
    test_file, result_dir = Path(test_file), Path(result_dir)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    requests, input_sha = read_input(test_file)
    if not isinstance(hardware_label, str) or not hardware_label.strip():
        raise SubmissionError("HARDWARE_LABEL", "Hardware label must be nonblank")
    lock_path = result_dir / ".b5-run.lock"
    staged: list[Path] = []
    published: list[tuple[Path, Path]] = []
    own_lock = False
    lock_identity: tuple[int, int] | None = None
    success = False
    try:
        result_dir.mkdir(parents=True, exist_ok=True)
        if any(os.path.lexists(result_dir / name) for name in FINAL_NAMES):
            raise SubmissionError("OUTPUT_EXISTS", "Use a fresh result directory; existing candidate files are preserved")
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise SubmissionError("OUTPUT_BUSY", "Another run owns this result directory") from None
        own_lock = True
        status = os.fstat(descriptor)
        lock_identity = (status.st_dev, status.st_ino)
        os.close(descriptor)
        try:
            engine = engine_factory()
        except _MissingModelConfig as exc:
            raise _MissingModelConfig(exc.path) from None
        except Exception:
            raise SubmissionError("MODEL_UNAVAILABLE", "Local model initialization failed; no prediction files published") from None
        emit("model_ready", is_mock=getattr(engine, "is_mock", None), model_version=getattr(engine, "model_version", None), initializations=1)
        for name in FINAL_NAMES:
            descriptor, path = tempfile.mkstemp(prefix=".b5-", suffix="-" + name, dir=result_dir)
            os.close(descriptor)
            staged.append(Path(path))
        latencies: list[float] = []
        parse_ids: list[str] = []
        with staged[0].open("w", encoding="utf-8", newline="\n") as stream:
            for index, request in enumerate(requests):
                store = store_factory()
                try:
                    synchronize()
                    started = time.perf_counter()
                    output = run_official(request, engine)
                    synchronize()
                    elapsed = round((time.perf_counter() - started) * 1000, 6)
                    if not math.isfinite(elapsed) or elapsed < 0:
                        raise SubmissionError("TIMING_INVALID", "Invalid elapsed time")
                    if index < REQUIRED_ROUNDS:
                        latencies.append(elapsed)
                    trace = getattr(engine, "last_trace", {})
                    if not isinstance(trace, dict):
                        raise SubmissionError("ENGINE_TRACE", "Invalid official diagnostic trace")
                    failures = trace.get("parse_failures", 0)
                    if type(failures) is not int or failures < 0:
                        raise SubmissionError("ENGINE_TRACE", "Invalid parse failure count")
                    if failures:
                        parse_ids.append(request.sample_id)
                    stream.write(json.dumps(output, ensure_ascii=False, allow_nan=False) + "\n")
                except SubmissionError as exc:
                    emit("sample_failed", index=index + 1, id=request.sample_id, code=exc.code)
                    raise
                except Exception:
                    emit("sample_failed", index=index + 1, id=request.sample_id, code="GENERATION_FAILED")
                    raise SubmissionError("GENERATION_FAILED", "Sample generation or synchronization failed; no prediction files published") from None
                finally:
                    store.close()
                history_json = json.dumps([{"role": m.role, "content": m.content} for m in request.history],
                                          ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                emit("sample_complete", index=index + 1, id=request.sample_id, history_messages=len(request.history),
                     history_sha256=hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
                     memory_context_empty=request.memory_context == "", fresh_store_created=True, fresh_store_closed=True,
                     elapsed_ms=elapsed, **{key: trace[key] for key in TRACE_FIELDS if key in trace})
        checked = validate_submission(requests, staged[0])
        if hashlib.sha256(test_file.read_bytes()).hexdigest() != input_sha:
            raise SubmissionError("INPUT_CHANGED", "Input changed while inference was running")
        report = {
            "backend": "transformers", "version": "b2_b5_official_v1", "hardware_label": hardware_label,
            "timing_scope": "A official prompt/tokenization/generation/decode/parse/retry/fallback and B strict output validation; CUDA synchronized before/after; excludes model load, file writes and store creation",
            "required_rounds": REQUIRED_ROUNDS, "rounds": len(latencies), "complete": len(latencies) == REQUIRED_ROUNDS,
            "samples": checked["samples"], "test_file_sha256": input_sha, "submission_sha256": checked["sha256"],
            "parse_failure_count": len(parse_ids), "parse_failure_ids": parse_ids,
            "parse_failure_policy": "number of samples with at least one A JSON parse failure, once per sample including retries",
            **latency_summary(latencies),
        }
        description = getattr(engine, "description", {})
        if isinstance(description, dict):
            report["model_version"] = getattr(engine, "model_version", "")
            report["model_path_name"] = Path(str(description.get("model_dir", ""))).name
            report["model_loader"] = "A ModelEngine direct local Transformers"
        validate_performance(report, requests, input_sha, checked["sha256"])
        staged[1].write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        # No-clobber links refuse even a file created after the initial preflight.
        # Keep staging paths until both links succeed, so failure cleanup proves ownership.
        for stage, name in zip(staged, FINAL_NAMES):
            final = result_dir / name
            os.link(stage, final)
            published.append((stage, final))
        success = True
        emit("batch_complete", samples=len(requests), rounds=report["rounds"], complete=report["complete"], result_dir=str(result_dir))
        return report
    except SubmissionError:
        raise
    except OSError:
        raise SubmissionError("OUTPUT_IO", "Could not read/write/publish owned result files; existing files are preserved") from None
    finally:
        if not success:
            for stage, final in published:
                try:
                    if final.exists() and stage.exists() and final.samefile(stage):
                        final.unlink()
                except OSError:
                    pass
        for stage in staged:
            stage.unlink(missing_ok=True)
        if own_lock:
            try:
                status = lock_path.stat()
                if (status.st_dev, status.st_ino) == lock_identity:
                    lock_path.unlink()
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_file", type=Path)
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("B2_OFFICIAL_MODEL_CONFIG", str(ROOT / "weights/inference_config.json"))))
    parser.add_argument("--hardware-label", default=os.environ.get("B2_OFFICIAL_HARDWARE_LABEL"))
    args = parser.parse_args(argv)
    force_offline()
    holder: dict[str, Any] = {}

    def factory() -> RealOfficialEngine:
        engine = RealOfficialEngine(args.config)
        import torch
        holder["torch"] = torch
        emit("runtime", device=engine.description.get("device"), torch_version=torch.__version__,
             cuda_available=torch.cuda.is_available(), model_version=engine.model_version, is_mock=False)
        return engine

    def synchronize() -> None:
        torch = holder.get("torch")
        if torch is not None and torch.cuda.is_available():
            for index in range(torch.cuda.device_count()):
                torch.cuda.synchronize(index)

    # A reports the actual device separately; hardware-label is attribution, never a GPU claim.
    label = args.hardware_label or "local automatic device; see runtime event for actual CPU/CUDA"
    try:
        run_batch(args.test_file, args.result_dir, factory, label, synchronize)
        return 0
    except SubmissionError as exc:
        print(json.dumps({"event": "batch_failed", "code": exc.code, "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"event": "batch_failed", "code": "INTERNAL_ERROR", "exception_type": type(exc).__name__}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
