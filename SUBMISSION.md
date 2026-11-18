# Submission checklist

Project: 48 V / 13S battery-pack digital twin.

## Included

- `video/final/battery_dt_course_project_1080p.mp4` — final course video, 10:55, 1080p,
  English synthetic narration, burned-in English subtitles.
- `video/final/battery_dt_course_project.srt` — external subtitle file.
- `video/final/thumbnail.png`, `video/final/chapters.txt`.
- `video/script.md`, `video/README.md` — full narration and rebuild instructions.
- Source code in `src/`, launcher/evaluation scripts in `scripts/`, tests in `tests/`.
- Config in `config/`, profiles/OCV/HPPC data in `data/`.
- Evaluation report and figures in `reports/`.

## Not included in the ZIP

- `.venv/` (local environment; recreate with `requirements.txt`).
- `data/battery_dt.db`, `data/truth_pack01.csv` (generated at run time).
- `logs/` (generated at run time).
- `video/frames_demo/`, `video/segments/`, `video/recording_stack.log` (regenerable
  video intermediates, about 300 MB).

## Reproduce

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
python scripts/run_all.py --fresh
# open http://localhost:8501
```

No Docker is required: `run_all.py` starts the embedded amqtt broker when port
1883 is closed. `docker compose up -d` is also supported.

## Verification

- `13 passed` with `.venv/bin/pytest -q`.
- Fresh no-Docker stack tested: broker → ingestor → twin → simulator → dashboard.
- MQTT QoS1/retained/LWT, load commands, fault injection, and what-if tested.
- T1: 13.0 mV RMS; T2: 6 s / 0.11%; T3: 4.23% MAPE; T4: 0 false alarms,
  63 s R0, 352 s cooling, 1 s sensor; T5: 5% loss + 2× noise.
- Video was recorded from the live dashboard at 20× simulation speed and shows
  load update, thermal alarm, what-if, SQLite page, and LWT offline/stale state.

## Video rebuild (optional)

```bash
pip install -r video/requirements-video.txt
python video/build_slides.py
python video/tts.py
python video/record_demo.py
python video/assemble.py
python video/build_script.py
```

Requires `ffmpeg`, Playwright Chromium, and network access for Edge TTS.
