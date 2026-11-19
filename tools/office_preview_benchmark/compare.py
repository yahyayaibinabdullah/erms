"""Validate paired trial evidence and emit a compact JSON report."""

import argparse
import json
from pathlib import Path


def read(directory, filename):
    return json.loads((directory / filename).read_text())


def summarize(directory, workers):
    browser = read(directory, "browser-results.json")
    lifecycle = read(directory, "lifecycle.json")
    assert lifecycle["test_exit_code"] == 0 and lifecycle["database_dropped"]
    assert browser["complete"] and all(c["status"] == "pass" for c in browser["checks"])
    jobs = [
        json.loads(row)
        for row in (directory / "office-jobs.jsonl").read_text().splitlines()
    ]
    ready, jobs = jobs[0], jobs[1:]
    assert ready["workers"] == workers and len(jobs) == 18
    worker_ids = {job["worker"] for job in jobs if job["worker"] is not None}
    assert len(worker_ids) == workers
    if workers:
        shutdown = read(directory, "office-shutdown.json")
        assert (
            shutdown["profiles_removed"]
            and set(shutdown["stopped_workers"]) == worker_ids
        )
    samples = []
    for s in browser["office_samples"]:
        exports = s["conversions"]
        assert s["rss_samples"] > 1
        active = max(
            sum(j["begin"] <= k["begin"] < j["end"] for j in exports) for k in exports
        )
        assert not workers or active <= workers
        assert len(exports) == s["viewers"] == len(s["first_pages"])
        samples.append(
            {
                "viewers": s["viewers"],
                "repeat": s["repeat"],
                "first_ms": {x["format"]: x["first_ms"] for x in s["first_pages"]},
                "all_first_ms": s["all_ms"],
                "max_active_exports": active,
                "queue_ms": {
                    j["format"][1:]: round(1000 * (j["begin"] - j["arrival"]))
                    for j in exports
                },
                "export_ms": {
                    j["format"][1:]: round(1000 * (j["end"] - j["begin"]))
                    for j in exports
                },
                "rss_samples": s["rss_samples"],
                "idle_mib": {k: round(v / 1024, 1) for k, v in s["idle_kib"].items()},
                "peak_mib": {k: round(v / 1024, 1) for k, v in s["peak_kib"].items()},
            }
        )
    assert len(samples) == 12
    mixed = [s for s in samples if s["viewers"] == 3]
    assert len(mixed) == 3 and all(
        s["max_active_exports"] == (workers or 3) for s in mixed
    )
    for ext in ("docx", "xlsx", "pptx"):
        assert sum(s["viewers"] == 1 and ext in s["first_ms"] for s in samples) == 3
    return browser, {
        "database_dropped": True,
        "resident_pids_verified_stopped": len(worker_ids),
        "prewarm_s": ready["startup_s"],
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fresh", type=Path)
    parser.add_argument("warm", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--warm-repeat", type=Path, help="Independent second pool startup and trial"
    )
    args = parser.parse_args()
    fresh_report, fresh = summarize(args.fresh, 0)
    warm_report, warm = summarize(args.warm, 2)
    assert fresh_report["fixtures"] == warm_report["fixtures"]
    assert fresh_report["version"] == warm_report["version"]
    report = {
        "chrome": fresh_report["version"],
        "fixtures": fresh_report["fixtures"],
        "fresh": fresh,
        "two_warm_workers": warm,
    }
    if args.warm_repeat:
        repeat_report, repeat = summarize(args.warm_repeat, 2)
        assert repeat_report["fixtures"] == fresh_report["fixtures"]
        assert repeat_report["version"] == fresh_report["version"]
        report["two_warm_workers_repeat"] = repeat
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
