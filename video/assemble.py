"""Assemble slide narration, the live demo frames, and captions into one MP4."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

VIDEO = Path(__file__).resolve().parent
ROOT = VIDEO.parent
SEGMENTS = VIDEO / "segments"
FINAL = VIDEO / "final"
TMP = Path("/tmp/opencode/battery_dt_video")
TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def run(command: list[str]) -> None:
    print(" ".join(command[:7]) + (" ..." if len(command) > 7 else ""))
    subprocess.run(command, check=True)


def ffprobe_duration(path: Path) -> float:
    value = subprocess.check_output(
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
    return float(value)


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if not lines:
            continue
        time_index = next((i for i, line in enumerate(lines) if TIME_RE.search(line)), None)
        if time_index is None:
            continue
        match = TIME_RE.search(lines[time_index])
        if not match:
            continue
        values = [int(v) for v in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        cue_text = "\n".join(lines[time_index + 1 :]).strip()
        if cue_text:
            cues.append((start, end, cue_text))
    return cues


def srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    h, ms = divmod(millis, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    chunks = []
    for i, (start, end, text) in enumerate(cues, start=1):
        chunks.append(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    path.write_text("\n".join(chunks), encoding="utf-8")


def slide_segment(entry: dict, duration: float) -> Path:
    output = SEGMENTS / f"{entry['name']}.mp4"
    image = VIDEO / entry["image"]
    audio = VIDEO / entry["audio"]
    run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(image),
            "-i",
            str(audio),
            "-af",
            "apad",
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output),
        ]
    )
    return output


def build_demo_audio(manifest: dict, recording: dict) -> tuple[Path, list[dict]]:
    scenes_meta = {s["name"]: s for s in recording["scenes"]}
    demo_entries = [e for e in manifest["entries"] if e["kind"] == "demo"]
    WAVS = TMP / "demo_wav"
    WAVS.mkdir(parents=True, exist_ok=True)
    wav_paths: list[Path] = []
    timeline = []
    for entry in demo_entries:
        meta = scenes_meta[entry["name"]]
        duration = float(meta["duration_s"])
        wav_path = WAVS / f"{entry['name']}.wav"
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(VIDEO / entry["audio"]),
                "-af",
                f"apad=whole_dur={duration:.3f}",
                "-t",
                f"{duration:.3f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ]
        )
        wav_paths.append(wav_path)
        timeline.append(
            {
                **entry,
                "recorded_duration": duration,
                "scene_start": float(meta["start_frame"]) / recording["fps"],
                "scene_end": float(meta["end_frame"]) / recording["fps"],
            }
        )
    combined = TMP / "demo_audio.wav"
    with wave.open(str(wav_paths[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(combined), "wb") as dst:
        dst.setnchannels(params.nchannels)
        dst.setsampwidth(params.sampwidth)
        dst.setframerate(params.framerate)
        for wav_path in wav_paths:
            with wave.open(str(wav_path), "rb") as source:
                dst.writeframes(source.readframes(source.getnframes()))
    return combined, timeline


def demo_segment(manifest: dict, recording: dict) -> tuple[Path, list[dict], float]:
    demo_audio, timeline = build_demo_audio(manifest, recording)
    output = SEGMENTS / "live_demo.mp4"
    duration = float(recording["total_frames"]) / float(recording["fps"])
    run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(recording["fps"]),
            "-start_number",
            "0",
            "-i",
            str(VIDEO / "frames_demo" / "%05d.jpg"),
            "-i",
            str(demo_audio),
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output),
        ]
    )
    return output, timeline, duration


def concat(segments: list[Path]) -> Path:
    list_path = TMP / "concat.txt"
    lines = [f"file '{path.as_posix()}'" for path in segments]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = SEGMENTS / "draft.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(output),
        ]
    )
    return output


def burn_subtitles(draft: Path, srt: Path) -> Path:
    duration = ffprobe_duration(draft)
    TMP.mkdir(parents=True, exist_ok=True)
    local_srt = TMP / "captions.srt"
    shutil.copy2(srt, local_srt)
    style = (
        "FontName=DejaVu Sans,FontSize=15,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=1.5,Shadow=1,"
        "MarginV=38,Alignment=2"
    )
    fade_out_start = max(0.0, duration - 1.0)
    vf = (
        f"subtitles='{local_srt.as_posix()}':original_size=1920x1080:"
        f"force_style='{style}',"
        f"fade=t=in:st=0:d=0.8,fade=t=out:st={fade_out_start:.3f}:d=1.0"
    )
    output = FINAL / "battery_dt_course_project_1080p.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(draft),
            "-vf",
            vf,
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-metadata",
            "title=48 V Battery Pack Digital Twin - Course Project",
            "-metadata",
            "comment=Plant 2RC + MQTT + SQLite + 1RC EKF/RLS twin + Streamlit",
            str(output),
        ]
    )
    return output


def main() -> None:
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((VIDEO / "audio" / "manifest.json").read_text(encoding="utf-8"))
    recording = json.loads((VIDEO / "frames_demo" / "recording.json").read_text(encoding="utf-8"))
    slides = [e for e in manifest["entries"] if e["kind"] == "slide"]
    demo_entries = [e for e in manifest["entries"] if e["kind"] == "demo"]
    pre_slides = slides[:-1]
    post_slides = slides[-1:]
    if not (pre_slides and demo_entries and post_slides):
        raise RuntimeError("unexpected manifest ordering")

    segment_files: list[Path] = []
    cues: list[tuple[float, float, str]] = []
    cursor = 0.0

    print("building slide segments...")
    for entry in pre_slides:
        duration = entry["duration"] + entry["pause_s"]
        path = slide_segment(entry, duration)
        segment_files.append(path)
        for start, end, text in parse_srt(VIDEO / entry["srt"]):
            cues.append((cursor + start, cursor + end, text))
        cursor += duration
        print(f"  {entry['name']}: {duration:.1f}s")

    print("building live demo segment...")
    demo_path, demo_timeline, demo_duration = demo_segment(manifest, recording)
    segment_files.append(demo_path)
    for entry in demo_timeline:
        for start, end, text in parse_srt(VIDEO / entry["srt"]):
            cues.append(
                (
                    cursor + entry["scene_start"] + start,
                    cursor + entry["scene_start"] + end,
                    text,
                )
            )
    cursor += demo_duration
    print(f"  live_demo: {demo_duration:.1f}s")

    for entry in post_slides:
        duration = entry["duration"] + entry["pause_s"]
        path = slide_segment(entry, duration)
        segment_files.append(path)
        for start, end, text in parse_srt(VIDEO / entry["srt"]):
            cues.append((cursor + start, cursor + end, text))
        cursor += duration
        print(f"  {entry['name']}: {duration:.1f}s")

    srt_path = FINAL / "battery_dt_course_project.srt"
    write_srt(srt_path, cues)
    print(f"subtitles: {len(cues)} cues -> {srt_path}")

    print("concatenating...")
    draft = concat(segment_files)
    print(f"draft duration: {ffprobe_duration(draft)/60:.2f} min")
    print("burning captions and normalising audio...")
    final_path = burn_subtitles(draft, srt_path)
    duration = ffprobe_duration(final_path)
    shutil.copy2(VIDEO / "slides" / "01_title.png", FINAL / "thumbnail.png")
    meta = {
        "duration_s": round(duration, 3),
        "duration_min": round(duration / 60.0, 2),
        "segments": [p.name for p in segment_files],
        "subtitles": str(srt_path.relative_to(ROOT)),
        "video": str(final_path.relative_to(ROOT)),
        "slides": len(slides),
        "demo_scenes": len(demo_entries),
    }
    (FINAL / "video_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"FINAL: {final_path} ({duration/60:.2f} min)")
    print(f"SRT:   {srt_path}")


if __name__ == "__main__":
    main()
