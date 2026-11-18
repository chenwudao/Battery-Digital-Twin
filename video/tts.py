"""Generate narration audio + SRT captions for every slide and demo scene."""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

from content import DEMO_SCENES, SLIDES

VIDEO = Path(__file__).resolve().parent
AUDIO = VIDEO / "audio"
VOICE = "en-US-AndrewNeural"
RATE = "+3%"


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def generate(name: str, text: str, force: bool = False) -> dict:
    audio = AUDIO / f"{name}.mp3"
    srt = AUDIO / f"{name}.srt"
    if force or not audio.exists() or audio.stat().st_size < 1000 or not srt.exists() or srt.stat().st_size < 20:
        cli = Path(sys.executable).parent / "edge-tts"
        command = [
            str(cli),
            "--voice",
            VOICE,
            "--rate",
            RATE,
            "--text",
            text,
            "--write-media",
            str(audio),
            "--write-subtitles",
            str(srt),
        ]
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                subprocess.run(
                    command, check=True, capture_output=True, text=True, timeout=300
                )
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_error = exc
                print(f"tts retry {attempt + 1} for {name}: {exc}")
        else:
            raise RuntimeError(f"edge-tts failed for {name}: {last_error}")
    return {
        "audio": audio.relative_to(VIDEO).as_posix(),
        "srt": srt.relative_to(VIDEO).as_posix(),
        "duration": round(ffprobe_duration(audio), 3),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    AUDIO.mkdir(parents=True, exist_ok=True)
    print(f"voice={VOICE} rate={RATE}")
    jobs: list[tuple[str, str, str, dict]] = []
    for slide in SLIDES:
        jobs.append(
            (
                "slide",
                slide["name"],
                slide["narration"],
                {
                    "image": f"slides/{slide['name']}.png",
                    "pause_s": slide["pause_s"],
                },
            )
        )
    for scene in DEMO_SCENES:
        jobs.append(
            (
                "demo",
                scene["name"],
                scene["narration"],
                {"action": scene["action"], "pause_s": scene["pause_s"]},
            )
        )

    def work(job):
        kind, name, narration, extra = job
        try:
            data = generate(name, narration, force=args.force)
            return {"kind": kind, "name": name, **extra, **data, "ok": True}
        except Exception as exc:
            return {"kind": kind, "name": name, **extra, "ok": False, "error": str(exc)}

    entries = []
    total = 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for entry in executor.map(work, jobs):
            if not entry["ok"]:
                raise RuntimeError(f"TTS failed for {entry['name']}: {entry['error']}")
            entries.append(entry)
            total += entry["duration"] + entry["pause_s"]
            print(f"  {entry['name']:<18} {entry['duration']:7.1f}s + {entry['pause_s']:.1f}s")
    manifest = {
        "voice": VOICE,
        "rate": RATE,
        "entries": entries,
        "planned_total_s": round(total, 2),
    }
    (VIDEO / "audio" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"planned total: {total/60:.2f} min")
    if total > 14.5 * 60:
        print("WARNING: planned video is close to the 15 minute limit")


if __name__ == "__main__":
    main()
