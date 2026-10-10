"""Validate completed B5 output independently, without loading model weights."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

if __package__:
    from .adapter import SubmissionError, load_json, read_input, validate_submission
    from .run_inference import validate_performance
else:
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "src/b2_core/contracts.py").is_file():
        sys.path.insert(0, str(checkout))
        from submission.participant.adapter import SubmissionError, load_json, read_input, validate_submission
        from submission.participant.run_inference import validate_performance
    else:
        from adapter import SubmissionError, load_json, read_input, validate_submission
        from run_inference import validate_performance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_file", type=Path)
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        requests, input_sha = read_input(args.test_file)
        checked = validate_submission(requests, args.result_dir / "submission.jsonl")
        report = load_json((args.result_dir / "performance_report.json").read_text(encoding="utf-8"))
        validate_performance(report, requests, input_sha, checked["sha256"])
        print(json.dumps({"event": "output_valid", **checked, "rounds": report["rounds"], "complete": report["complete"]}))
        return 0
    except SubmissionError as exc:
        print(json.dumps({"event": "output_invalid", "code": exc.code, "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"event": "output_invalid", "code": "FILE_OR_REPORT_INVALID", "exception_type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
