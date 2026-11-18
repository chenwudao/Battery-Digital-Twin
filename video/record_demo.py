"""Record the live Streamlit demo to a numbered JPEG frame sequence.

The recorder starts the full stack (unless --no-stack), waits for the system to
settle, then performs the actions in a fixed 8 fps timeline.  Cursor and click
effects are overlaid so the result reads like a screen recording.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
from PIL import Image, ImageDraw
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "video"
FRAMES = VIDEO / "frames_demo"
FPS = 8
WIDTH = 1920
HEIGHT = 1080
URL = "http://127.0.0.1:8501"


def chromium_path() -> str:
    candidates = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    if candidates:
        return str(candidates[-1])
    raise FileNotFoundError("no cached Playwright Chromium; run `playwright install chromium`")


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def wait_port(port: int, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return
        time.sleep(0.4)
    raise TimeoutError(f"port {port} did not open")


def load_manifest() -> list[dict]:
    manifest = json.loads((VIDEO / "audio" / "manifest.json").read_text(encoding="utf-8"))
    return [entry for entry in manifest["entries"] if entry["kind"] == "demo"]


def start_stack() -> subprocess.Popen:
    if port_open(1883) or port_open(8501):
        raise RuntimeError("ports 1883/8501 are already in use; stop old services first")
    log_path = VIDEO / "recording_stack.log"
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_all.py"),
            "--fresh",
            "--speed",
            "20",
            "--duration",
            "9000",
        ],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_port(8501)
    return process


def stop_stack(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=12)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def kill_simulator() -> None:
    killed = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
        except Exception:
            continue
        if "src/battery_dt/simulator/publisher.py" in cmdline:
            proc.kill()
            killed.append(proc.pid)
    print(f"killed simulator: {killed}")


class Recorder:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.frame_index = 0
        self.cursor = (960.0, 540.0)
        self.cursor_visible = False
        self.click_effects: list[tuple[int, float, float]] = []
        self.scenes: list[dict] = []
        FRAMES.mkdir(parents=True, exist_ok=True)
        for old in FRAMES.glob("*.jpg"):
            old.unlink()

    def _draw_overlay(self, img: Image.Image) -> None:
        if not self.cursor_visible:
            return
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        x, y = self.cursor
        for start, cx, cy in self.click_effects:
            age = self.frame_index - start
            if 0 <= age <= 6:
                radius = 12 + age * 8
                alpha = max(0, 190 - age * 30)
                draw.ellipse(
                    (cx - radius, cy - radius, cx + radius, cy + radius),
                    outline=(56, 189, 248, alpha),
                    width=4,
                )
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(255, 255, 255, 235), outline=(15, 23, 42, 255), width=3)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(14, 165, 233, 255))
        img.alpha_composite(overlay)
        self.click_effects = [e for e in self.click_effects if self.frame_index - e[0] <= 8]

    def capture(self) -> None:
        jpeg = self.page.screenshot(type="jpeg", quality=92)
        img = Image.open(io.BytesIO(jpeg)).convert("RGBA")
        self._draw_overlay(img)
        img.convert("RGB").save(FRAMES / f"{self.frame_index:05d}.jpg", quality=91)
        self.frame_index += 1

    def move_to(self, locator, *, click: bool = False) -> None:
        locator.scroll_into_view_if_needed(timeout=15000)
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError("element has no bounding box")
        self.cursor = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.cursor_visible = True
        locator.hover(timeout=15000)
        if click:
            self.click_effects.append((self.frame_index, *self.cursor))
            locator.click(timeout=15000)
            self.page.wait_for_timeout(700)

    def scroll_main(self, top: int) -> None:
        self.page.eval_on_selector(
            '[data-testid="stMain"]', "(el, top) => el.scrollTo({top: top, behavior: 'instant'})", top
        )

    def set_load_controls(self) -> None:
        slider_group = self.page.locator('[data-testid="stSlider"] [role="group"]').first
        self.move_to(slider_group)
        slider = self.page.locator('[data-testid="stSlider"] input[type="range"]').first
        slider.focus()
        for _ in range(6):
            slider.press("ArrowRight")
            self.page.wait_for_timeout(140)
        duration = self.page.get_by_label("持续 (min)")
        self.move_to(duration)
        duration.fill("60")
        duration.press("Enter")
        self.page.wait_for_timeout(900)
        apply_button = self.page.get_by_role("button", name="应用负载")
        self.move_to(apply_button, click=True)

    def click_cooling(self) -> None:
        button = self.page.get_by_role("button", name="冷却失效（hA → 5%）")
        self.move_to(button, click=True)

    def set_safe_load(self) -> None:
        slider_group = self.page.locator('[data-testid="stSlider"] [role="group"]').first
        self.move_to(slider_group)
        slider = self.page.locator('[data-testid="stSlider"] input[type="range"]').first
        slider.focus()
        slider.press("Home")
        self.page.wait_for_timeout(200)
        for _ in range(5):
            slider.press("ArrowRight")
            self.page.wait_for_timeout(140)
        apply_button = self.page.get_by_role("button", name="应用负载")
        self.move_to(apply_button, click=True)

    def click_tab(self, name: str) -> None:
        tab = self.page.get_by_role("tab", name=name)
        self.move_to(tab, click=True)
        self.page.wait_for_timeout(900)
        self.scroll_main(0)

    def run_whatif(self) -> None:
        self.click_tab("What-if 决策")
        button = self.page.get_by_role("button", name="运行场景评估")
        self.page.wait_for_timeout(500)
        self.move_to(button, click=True)
        self.page.wait_for_timeout(1400)

    def scene(self, name: str, frames: int, actions: list[tuple[int, callable]]) -> None:
        actions = sorted(actions, key=lambda item: item[0])
        action_pos = 0
        start_frame = self.frame_index
        start_time = time.monotonic()
        print(f"scene {name}: {frames} frames ({frames/FPS:.1f}s)")
        for index in range(frames):
            while action_pos < len(actions) and actions[action_pos][0] <= index:
                _frame, fn = actions[action_pos]
                try:
                    fn()
                except Exception as exc:
                    print(f"  action failed at frame {index}: {exc}")
                action_pos += 1
            self.capture()
            target = start_time + (index + 1) / FPS
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        end_frame = self.frame_index
        self.scenes.append(
            {
                "name": name,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "frames": end_frame - start_frame,
                "duration_s": round((end_frame - start_frame) / FPS, 3),
            }
        )

    def save_meta(self) -> None:
        meta = {
            "fps": FPS,
            "width": WIDTH,
            "height": HEIGHT,
            "total_frames": self.frame_index,
            "duration_s": round(self.frame_index / FPS, 3),
            "scenes": self.scenes,
        }
        (VIDEO / "frames_demo" / "recording.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        print(
            f"recorded {self.frame_index} frames / {self.frame_index/FPS:.1f}s "
            f"-> {FRAMES / 'recording.json'}"
        )


def prepare_page(page: Page) -> None:
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_selector("text=剩余续航", timeout=90000)
    page.wait_for_function(
        "() => document.body.innerText.includes('在线') && document.body.innerText.includes('活动告警')",
        timeout=90000,
    )
    page.add_style_tag(
        content="""
        [data-testid="stToolbar"], [data-testid="stHeader"],
        [data-testid="stDecoration"], footer { display: none !important; }
        [data-testid="stMain"]::-webkit-scrollbar,
        [data-testid="stSidebarContent"]::-webkit-scrollbar { width: 0px; }
        [data-testid="stMain"] { scrollbar-width: none; }
        .block-container { padding-top: 1.4rem !important; }
        """
    )
    page.eval_on_selector(
        '[data-testid="stMain"]', "(el) => el.scrollTo({top: 0, behavior: 'instant'})"
    )
    page.wait_for_timeout(1500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-stack", action="store_true", help="use an already running dashboard")
    parser.add_argument("--warmup", type=float, default=66.0, help="seconds to let initial transient leave chart")
    args = parser.parse_args()
    manifest = load_manifest()
    stack = None
    if not args.no_stack:
        print("starting fresh stack...")
        stack = start_stack()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=chromium_path(),
                args=["--no-sandbox", "--disable-dev-shm-usage", "--force-color-profile=srgb"],
            )
            context = browser.new_context(
                viewport={"width": WIDTH, "height": HEIGHT},
                device_scale_factor=1,
                reduced_motion="reduce",
            )
            page = context.new_page()
            print("waiting for live dashboard...")
            prepare_page(page)
            if args.warmup > 0:
                print(f"warming up {args.warmup:.0f}s so the initial transient leaves the chart...")
                time.sleep(args.warmup)

            recorder = Recorder(page)
            actions = {
                "d01_overview": [
                    (int(0.33 * round((manifest[0]["duration"] + manifest[0]["pause_s"]) * FPS)), lambda: recorder.scroll_main(320)),
                    (int(0.78 * round((manifest[0]["duration"] + manifest[0]["pause_s"]) * FPS)), lambda: recorder.scroll_main(0)),
                ],
                "d02_load": [(int(0.06 * FPS * (manifest[1]["duration"] + manifest[1]["pause_s"])), recorder.set_load_controls)],
                "d03_fault": [(int(0.06 * FPS * (manifest[2]["duration"] + manifest[2]["pause_s"])), recorder.click_cooling)],
                "d04_alarm": [
                    (int(0.06 * FPS * (manifest[3]["duration"] + manifest[3]["pause_s"])), lambda: recorder.click_tab("异常与解释")),
                    (int(0.36 * FPS * (manifest[3]["duration"] + manifest[3]["pause_s"])), recorder.set_safe_load),
                ],
                "d05_whatif": [(int(0.04 * FPS * (manifest[4]["duration"] + manifest[4]["pause_s"])), recorder.run_whatif)],
                "d06_data": [(int(0.06 * FPS * (manifest[5]["duration"] + manifest[5]["pause_s"])), lambda: recorder.click_tab("数据管理"))],
                "d07_lwt": [
                    (int(0.04 * FPS * (manifest[6]["duration"] + manifest[6]["pause_s"])), lambda: recorder.click_tab("监控")),
                    (int(0.13 * FPS * (manifest[6]["duration"] + manifest[6]["pause_s"])), kill_simulator),
                ],
            }
            for entry in manifest:
                frames = round((entry["duration"] + entry["pause_s"]) * FPS)
                recorder.scene(entry["name"], frames, actions.get(entry["name"], []))
            recorder.save_meta()
            context.close()
            browser.close()
    finally:
        if stack is not None:
            print("stopping stack...")
            stop_stack(stack)
            # Give the broker a moment to flush logs before the next run.
            time.sleep(1)


if __name__ == "__main__":
    main()
