"""Start broker, ingestor, twin, simulator and dashboard.

    .venv/bin/python scripts/run_all.py --fresh

If 127.0.0.1:1883 is already open, an external Mosquitto broker is used.
Otherwise the embedded amqtt broker is launched, so Docker is optional.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battery_dt.common.config import load_system  # noqa: E402


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(host: str, port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(host, port):
            return True
        time.sleep(0.25)
    return False


class Runner:
    def __init__(self, args: argparse.Namespace, settings: dict) -> None:
        self.args = args
        self.settings = settings
        self.root = ROOT
        self.log_dir = ROOT / "logs"
        self.log_dir.mkdir(exist_ok=True)
        self.processes: list[tuple[str, subprocess.Popen, object]] = []
        self.env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONUNBUFFERED": "1",
            "MPLCONFIGDIR": str(ROOT / "logs" / "matplotlib"),
        }
        if args.port:
            settings["mqtt"]["port"] = int(args.port)
        self.host = settings["mqtt"]["host"]
        self.port = int(settings["mqtt"]["port"])
        self.stop_event = threading.Event()
        self.env["BATTERY_DT_MQTT_HOST"] = self.host
        self.env["BATTERY_DT_MQTT_PORT"] = str(self.port)

    def start(self, name: str, command: list[str]) -> subprocess.Popen:
        log_path = self.log_dir / f"{name}.log"
        log_file = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=self.env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes.append((name, process, log_file))
        print(f"  {name:<10} pid={process.pid:<7} log={log_path.relative_to(self.root)}")
        return process

    def run(self) -> int:
        if not self.args.no_broker and not port_open(self.host, self.port):
            print(f"starting embedded MQTT broker on {self.host}:{self.port}")
            self.start(
                "broker",
                [sys.executable, str(self.root / "scripts" / "broker.py"), "--port", str(self.port)],
            )
            if not wait_port(self.host, self.port):
                print("ERROR: embedded broker did not open the port; see logs/broker.log")
                return 1
        else:
            print(f"using existing MQTT broker at {self.host}:{self.port}")

        print("starting services:")
        ingestor_cmd = [sys.executable, "src/battery_dt/storage/ingestor.py"]
        if self.args.fresh:
            ingestor_cmd.append("--fresh")
        ingestor = self.start("ingestor", ingestor_cmd)
        time.sleep(0.8)
        if ingestor.poll() is not None:
            print("ERROR: ingestor exited. Check logs/ingestor.log")
            return 1
        self.start("twin", [sys.executable, "src/battery_dt/twin/service.py"])
        time.sleep(0.5)

        if not self.args.no_dashboard:
            self.start(
                "dashboard",
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "src/battery_dt/dashboard/app.py",
                    "--server.headless",
                    "true",
                    "--server.port",
                    str(self.args.dashboard_port),
                    "--browser.gatherUsageStats",
                    "false",
                    "--server.fileWatcherType",
                    "none",
                ],
            )
            if wait_port("127.0.0.1", self.args.dashboard_port, timeout=15):
                print(f"  dashboard  http://localhost:{self.args.dashboard_port}")
            else:
                print("  dashboard is still starting; check logs/dashboard.log")

        if not self.args.no_simulator:
            sim_cmd = [sys.executable, "src/battery_dt/simulator/publisher.py"]
            if self.args.profile:
                sim_cmd += ["--profile", self.args.profile]
            if self.args.speed:
                sim_cmd += ["--speed", str(self.args.speed)]
            if self.args.duration:
                sim_cmd += ["--duration", str(self.args.duration)]
            self.start("simulator", sim_cmd)

        print()
        print("Services are running. Press Ctrl+C to stop.")
        print("Useful checks:")
        print("  mosquitto_sub -v -t 'dt/#'")
        print("  sqlite3 data/battery_dt.db 'select count(*) from measurements;'")
        print()
        try:
            while not self.stop_event.wait(1.0):
                for name, process, _fh in self.processes:
                    if process.poll() is not None and name not in {"simulator"}:
                        print(f"WARNING: {name} exited with code {process.returncode}")
                        self.processes = [p for p in self.processes if p[1] is not process]
                if self.args.exit_with_simulator:
                    sim = next((p for n, p, _ in self.processes if n == "simulator"), None)
                    if sim is not None and sim.poll() is not None:
                        print("simulator finished; allowing 2 s for final MQTT messages...")
                        time.sleep(2.0)
                        print("stopping the rest (--exit-with-simulator)")
                        break
        except KeyboardInterrupt:
            print("\nstopping...")
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        for name, process, _fh in reversed(self.processes):
            if process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.time() + 6.0
        for name, process, _fh in self.processes:
            remaining = max(0.0, deadline - time.time())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for _name, _process, fh in self.processes:
            try:
                fh.flush()
                fh.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the complete battery DT stack")
    parser.add_argument("--fresh", action="store_true", help="recreate the SQLite database")
    parser.add_argument("--no-broker", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-simulator", action="store_true")
    parser.add_argument("--speed", type=float, default=None, help="simulation acceleration")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--duration", type=float, default=None, help="sim seconds")
    parser.add_argument("--port", type=int, default=None, help="MQTT broker port")
    parser.add_argument("--dashboard-port", type=int, default=8501)
    parser.add_argument("--exit-with-simulator", action="store_true")
    args = parser.parse_args()
    settings = load_system()
    runner = Runner(args, settings)

    def request_stop(*_args) -> None:
        runner.stop_event.set()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    raise SystemExit(runner.run())


if __name__ == "__main__":
    main()
