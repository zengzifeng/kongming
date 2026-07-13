from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_DB_PATH = BACKEND_DIR / "instance" / "kongming.db"
DEFAULT_BASE_URL = "http://winlink.sre.ksyun.com/ksp_service/api/v1/kingress/resource-model-monitor-data/list"
DEFAULT_OUTPUT_DIR = Path.cwd()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch resource model monitor data for all and each enabled ai_consumer.")
    parser.add_argument("--hours", type=int, default=24, help="Time range length in hours. Default: 24")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to write JSON files. Default: current directory")
    parser.add_argument("--all-file", default="1hr.json", help="Filename for the all-data request. Default: 1hr.json")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"SQLite database path. Default: {DEFAULT_DB_PATH}")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Monitor API list endpoint URL.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds. Default: 30")
    return parser.parse_args()


def safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return name.strip("._") or "consumer"


def time_window(hours: int) -> tuple[str, str]:
    end = datetime.now().replace(microsecond=0)
    start = end - timedelta(hours=hours)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def build_url(base_url: str, start_time: str, end_time: str, ai_consumer: str | None = None) -> str:
    params: list[tuple[str, str]] = [
        ("start_time", start_time),
        ("end_time", end_time),
    ]
    if ai_consumer:
        params.append(("ai_consumer", ai_consumer))
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urllib.parse.urlencode(params)}"


def fetch_json(url: str, timeout: int) -> dict:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ai_consumers(db_path: Path) -> list[str]:
    if not db_path.exists():
        print(f"database not found, skip per-consumer requests: {db_path}", file=sys.stderr)
        return []

    query = """
        SELECT ai_consumer
        FROM monitor_consumers
        WHERE enabled = 1
        ORDER BY id ASC
    """
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(query).fetchall()
    except sqlite3.Error as exc:
        print(f"failed to read monitor_consumers, skip per-consumer requests: {exc}", file=sys.stderr)
        return []

    return [str(row[0]) for row in rows if row and row[0]]


def main() -> int:
    args = parse_args()
    if args.hours <= 0:
        raise SystemExit("--hours must be greater than 0")

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time, end_time = time_window(args.hours)
    ai_consumers = load_ai_consumers(args.db)

    all_url = build_url(args.base_url, start_time, end_time)
    all_payload = fetch_json(all_url, args.timeout)
    all_path = output_dir / args.all_file
    write_json(all_path, all_payload)
    print(f"wrote {all_path}")

    for ai_consumer in ai_consumers:
        url = build_url(args.base_url, start_time, end_time, ai_consumer=ai_consumer)
        payload = fetch_json(url, args.timeout)
        path = output_dir / f"consumer_{safe_filename(ai_consumer)}.json"
        write_json(path, payload)
        print(f"wrote {path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
