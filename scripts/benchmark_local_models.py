"""Measure local speech-model latency and process memory without network calls.

The benchmark synthesizes one fixed sentence with Kokoro and transcribes the
result with the project's Faster-Whisper configuration.  It reports both the
first pass (model loading plus inference) and a warm pass in the same process.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from io import BytesIO
from ctypes import wintypes
from pathlib import Path

import numpy as np
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.lamp_character.speech import (
    iter_kokoro_audio,
    load_transcription_model,
    load_tts_pipeline,
    transcribe_speech_wav,
)


DEFAULT_WHISPER = "small"
PHRASE = "Please look toward the green cup and remember where it is."


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_memory_mib() -> dict[str, float] | None:
    if os.name != "nt":
        return None
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory = kernel32.K32GetProcessMemoryInfo
    get_memory.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_memory.restype = wintypes.BOOL
    handle = kernel32.GetCurrentProcess()
    ok = get_memory(
        handle, ctypes.byref(counters), counters.cb
    )
    if not ok:
        return None
    scale = 1024 * 1024
    return {
        "working_set_mib": round(counters.WorkingSetSize / scale, 1),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / scale, 1),
    }


def _seconds(callable_) -> tuple[object, float, float]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    value = callable_()
    return (
        value,
        round(time.perf_counter() - started, 3),
        round(time.process_time() - cpu_started, 3),
    )


def _synthesize_wav() -> bytes:
    pipeline = load_tts_pipeline()
    samples = np.concatenate(list(iter_kokoro_audio(pipeline, PHRASE)))
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16).tobytes()
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(pcm)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper-model", default=DEFAULT_WHISPER)
    args = parser.parse_args()

    whisper = None
    cold_audio, cold_tts, cold_tts_cpu = _seconds(_synthesize_wav)
    cold_text, cold_stt, cold_stt_cpu = _seconds(
        lambda: transcribe_speech_wav(
            load_transcription_model(args.whisper_model), cold_audio
        )
    )
    warm_audio, warm_tts, warm_tts_cpu = _seconds(_synthesize_wav)
    whisper = load_transcription_model(args.whisper_model)
    warm_text, warm_stt, warm_stt_cpu = _seconds(
        lambda: transcribe_speech_wav(whisper, warm_audio)
    )

    print(
        json.dumps(
            {
                "platform": "Windows development laptop" if os.name == "nt" else os.name,
                "phrase": PHRASE,
                "cold_tts_seconds": cold_tts,
                "cold_stt_seconds": cold_stt,
                "warm_tts_seconds": warm_tts,
                "warm_stt_seconds": warm_stt,
                "cold_tts_cpu_seconds": cold_tts_cpu,
                "cold_stt_cpu_seconds": cold_stt_cpu,
                "warm_tts_cpu_seconds": warm_tts_cpu,
                "warm_stt_cpu_seconds": warm_stt_cpu,
                "warm_average_cpu_cores": round(
                    (warm_tts_cpu + warm_stt_cpu) / (warm_tts + warm_stt), 2
                ),
                "cold_transcript": cold_text,
                "warm_transcript": warm_text,
                "process_memory": _windows_memory_mib(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
