"""Generate a readable video script and chapter list from the narration + timeline."""

from __future__ import annotations

import json
from pathlib import Path

from content import DEMO_SCENES, SLIDES

VIDEO = Path(__file__).resolve().parent
TITLES = {
    "01_title": "Title and problem",
    "02_problem": "Hidden states and user decisions",
    "03_architecture": "Architecture and truth separation",
    "04_acquisition": "Acquisition and assumptions",
    "05_mqtt": "MQTT contract",
    "06_data": "Data management",
    "07_model": "Model and identification",
    "08_t1_t3": "Evaluation T1–T3",
    "09_t4_t5": "Evaluation T4–T5",
    "10_demo_intro": "Integrated demo setup",
    "11_conclusion": "Conclusion and limitations",
}
DEMO_TITLES = {
    "d01_overview": "Live dashboard overview",
    "d02_load": "Apply an 18 A load",
    "d03_fault": "Inject cooling failure",
    "d04_alarm": "Alarm explanation and safe load",
    "d05_whatif": "What-if decision",
    "d06_data": "SQLite data layer",
    "d07_lwt": "LWT offline / stale data",
}


def mmss(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def main() -> None:
    manifest = json.loads((VIDEO / "audio" / "manifest.json").read_text(encoding="utf-8"))
    recording = json.loads((VIDEO / "frames_demo" / "recording.json").read_text(encoding="utf-8"))
    slides = [e for e in manifest["entries"] if e["kind"] == "slide"]
    demo = [e for e in manifest["entries"] if e["kind"] == "demo"]
    scenes = {s["name"]: s for s in recording["scenes"]}
    cursor = 0.0
    chapters = []
    body = []
    body.append("# Video script\n")
    body.append(
        "Synthetic narration: `en-US-AndrewNeural`, rate `+3%`. "
        "The final video is 1080p with burned-in English captions and a separate SRT.\n"
    )
    for entry in slides[:-1]:
        duration = entry["duration"] + entry["pause_s"]
        title = TITLES.get(entry["name"], entry["name"])
        chapters.append((cursor, duration, title))
        body.append(f"## {mmss(cursor)} — {title}\n")
        body.append(SLIDES[[s["name"] for s in SLIDES].index(entry["name"])]["narration"] + "\n")
        cursor += duration
    body.append(f"## {mmss(cursor)} — Live dashboard demo\n")
    demo_start = cursor
    for entry in demo:
        meta = scenes[entry["name"]]
        title = DEMO_TITLES.get(entry["name"], entry["name"])
        chapters.append((cursor, float(meta["duration_s"]), title))
        body.append(f"### {mmss(cursor)} — {title}\n")
        scene = next(s for s in DEMO_SCENES if s["name"] == entry["name"])
        body.append(scene["narration"] + "\n")
        cursor += float(meta["duration_s"])
    demo_duration = cursor - demo_start
    body.append(f"## {mmss(cursor)} — Conclusion\n")
    slide = next(s for s in SLIDES if s["name"] == slides[-1]["name"])
    chapters.append((cursor, slides[-1]["duration"] + slides[-1]["pause_s"], TITLES[slides[-1]["name"]]))
    body.append(slide["narration"] + "\n")
    body.append("\n## Chapters\n")
    body.append("| start | title |")
    body.append("|---|---|")
    for start, duration, title in chapters:
        body.append(f"| {mmss(start)} | {title} ({duration:.0f}s) |")
    body.append("")
    (VIDEO / "script.md").write_text("\n".join(body), encoding="utf-8")
    chapter_lines = [f"{mmss(start)} {title}" for start, _duration, title in chapters]
    (VIDEO / "final" / "chapters.txt").write_text("\n".join(chapter_lines) + "\n", encoding="utf-8")
    print(f"wrote {VIDEO/'script.md'} with {len(chapters)} chapters; demo {demo_duration:.1f}s")


if __name__ == "__main__":
    main()
