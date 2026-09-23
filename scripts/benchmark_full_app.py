"""Measure CPU and memory for the complete Lux desktop application.

The benchmark launches the normal application entry point, samples the entire
process tree, and closes only the processes that it started.  It intentionally
keeps every local subsystem enabled: Qt, camera/MediaPipe, PyBullet, audio,
Whisper, and Kokoro.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = ROOT / ".conda-env" / ("python.exe" if os.name == "nt" else "bin/python")


def build_application_command(python: Path, *, api_key_present: bool) -> list[str]:
    """Build a non-blocking Lux command for the benchmark environment."""

    command = [str(python), str(ROOT / "run.py")]
    if not api_key_present:
        command.append("--no-llm")
    return command


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def live_tree(root: psutil.Process) -> list[psutil.Process]:
    try:
        processes = [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []
    return [process for process in processes if process.is_running()]


def stop_tree(root: psutil.Process) -> None:
    processes = live_tree(root)
    for process in reversed(processes):
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.wait_procs(alive, timeout=3)


def summarize(samples: list[dict[str, float]], steady_after: float) -> dict[str, float | int]:
    steady = [sample for sample in samples if sample["elapsed_s"] >= steady_after]
    if not steady:
        steady = samples
    rss = [sample["rss_mib"] for sample in samples]
    cores = [sample["cpu_cores"] for sample in samples]
    steady_rss = [sample["rss_mib"] for sample in steady]
    steady_cores = [sample["cpu_cores"] for sample in steady]
    return {
        "sample_count": len(samples),
        "peak_process_count": int(max(sample["process_count"] for sample in samples)),
        "peak_rss_mib": round(max(rss), 1),
        "mean_rss_mib": round(statistics.fmean(rss), 1),
        "steady_mean_rss_mib": round(statistics.fmean(steady_rss), 1),
        "steady_p95_rss_mib": round(percentile(steady_rss, 0.95), 1),
        "peak_cpu_cores": round(max(cores), 2),
        "mean_cpu_cores": round(statistics.fmean(cores), 2),
        "steady_mean_cpu_cores": round(statistics.fmean(steady_cores), 2),
        "steady_p95_cpu_cores": round(percentile(steady_cores, 0.95), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=90.0, help="measurement duration in seconds")
    parser.add_argument("--steady-after", type=float, default=45.0, help="start of steady-state window")
    parser.add_argument("--interval", type=float, default=0.5, help="sampling interval in seconds")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON, help="Lux environment Python")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "full_app_resources.json")
    args = parser.parse_args()

    if not args.python.exists():
        parser.error(f"application Python not found: {args.python}")
    if args.duration <= 0 or args.interval <= 0:
        parser.error("duration and interval must be positive")
    if not 0 <= args.steady_after < args.duration:
        parser.error("steady-after must be within the measurement duration")

    api_key_present = bool(os.environ.get("OPENAI_API_KEY"))
    command = build_application_command(
        args.python,
        api_key_present=api_key_present,
    )
    child = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy())
    root = psutil.Process(child.pid)
    primed: set[int] = set()
    samples: list[dict[str, float]] = []
    start = time.perf_counter()
    exit_code: int | None = None

    try:
        while (elapsed := time.perf_counter() - start) < args.duration:
            if child.poll() is not None:
                exit_code = child.returncode
                break

            processes = live_tree(root)
            for process in processes:
                if process.pid not in primed:
                    try:
                        process.cpu_percent(None)
                        primed.add(process.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            time.sleep(min(args.interval, max(0.0, args.duration - elapsed)))
            rss_bytes = 0
            process_cpu_percent = 0.0
            live_count = 0
            for process in live_tree(root):
                try:
                    rss_bytes += process.memory_info().rss
                    process_cpu_percent += process.cpu_percent(None)
                    live_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            samples.append(
                {
                    "elapsed_s": round(time.perf_counter() - start, 3),
                    "rss_mib": rss_bytes / (1024 * 1024),
                    "cpu_cores": process_cpu_percent / 100.0,
                    "process_count": float(live_count),
                }
            )
    finally:
        if child.poll() is None:
            stop_tree(root)
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)

    if not samples:
        raise RuntimeError(f"Lux exited before a resource sample was collected (exit code {exit_code})")

    elapsed_total = samples[-1]["elapsed_s"]
    result = {
        "benchmark": "Lux full application process tree",
        "scope": [
            "PySide6 GUI",
            "camera and MediaPipe engagement",
            "PyBullet simulation",
            "audio threads",
            "faster-whisper with Whisper Small",
            "Kokoro-82M",
        ],
        "excludes": (
            []
            if api_key_present
            else ["remote GPT requests (OPENAI_API_KEY was not present)"]
        ),
        "command": command,
        "duration_s": round(elapsed_total, 3),
        "steady_after_s": args.steady_after,
        "sample_interval_s": args.interval,
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "host_total_memory_gib": round(psutil.virtual_memory().total / (1024**3), 1),
        "openai_api_key_present": api_key_present,
        "metrics": summarize(samples, args.steady_after),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
