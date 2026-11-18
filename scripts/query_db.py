"""Inspect / export the SQLite data layer without the sqlite3 CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battery_dt.common.config import load_system  # noqa: E402
from battery_dt.storage.db import Database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variable", default="voltage_V")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--csv", default=None, help="write the returned series to CSV")
    args = parser.parse_args()
    settings = load_system()
    db = Database(settings["storage"]["db_path"])
    db.init()
    print("table counts:")
    for name, count in db.counts().items():
        print(f"  {name:<16} {count}")
    asset = settings["asset_id"]
    series = db.get_series(args.variable, asset, limit=args.limit)
    print(f"\nlast {len(series)} rows for {args.variable} ({asset}):")
    if not series.empty:
        print(series.to_string(index=False))
    if args.csv:
        series.to_csv(args.csv, index=False)
        print(f"wrote {args.csv}")
    latest = db.latest_twin(asset)
    if latest:
        print("\nlatest twin output:")
        print(
            f"  ts={latest['ts_source']} soc={latest['soc']:.3f} "
            f"r0={latest['r0_ohm']:.4f} Tcore={latest['t_core_C']:.1f} "
            f"remaining_s={latest['remaining_s']}"
        )


if __name__ == "__main__":
    main()
