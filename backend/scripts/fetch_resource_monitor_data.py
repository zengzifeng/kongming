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
    parser = argparse.ArgumentParser(
        description="Fetch resource model monitor data: a global request plus one per enabled "
                    "consumer (filtered by user_id=customer_code).")
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


def build_url(base_url: str, start_time: str, end_time: str, user_id: str | None = None) -> str:
    params: list[tuple[str, str]] = [
        ("start_time", start_time),
        ("end_time", end_time),
    ]
    if user_id:
        params.append(("user_id", user_id))
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urllib.parse.urlencode(params)}"


def fetch_json(url: str, timeout: int) -> dict:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_consumers(db_path: Path) -> list[tuple[str, str]]:
    """返回 [(ai_consumer, customer_code), ...]，仅 enabled 且带 customer_code。

    customer_code 在采集时作为接口的 user_id 过滤参数（线上逐客户过滤仅认 user_id）。
    """
    if not db_path.exists():
        print(f"database not found, skip per-consumer requests: {db_path}", file=sys.stderr)
        return []

    query = """
        SELECT ai_consumer, customer_code
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

    out: list[tuple[str, str]] = []
    for row in rows:
        if not row or not row[0] or not row[1]:
            continue
        out.append((str(row[0]), str(row[1])))
    return out


def main() -> int:
    args = parse_args()
    if args.hours <= 0:
        raise SystemExit("--hours must be greater than 0")

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time, end_time = time_window(args.hours)
    consumers = load_consumers(args.db)

    # 1) 全局（不区分客户）-> all_file：含 token 集群/GPU 产能 + kingress 全客户汇总
    all_url = build_url(args.base_url, start_time, end_time)
    all_payload = fetch_json(all_url, args.timeout)
    all_path = output_dir / args.all_file
    write_json(all_path, all_payload)
    print(f"wrote {all_path}")

    # 2) 逐客户：customer_code(user_id) 作为接口过滤参数；文件名用 customer_code(唯一，避免同客户名多 uid 覆盖)
    for ai_consumer, customer_code in consumers:
        url = build_url(args.base_url, start_time, end_time, user_id=customer_code)
        payload = fetch_json(url, args.timeout)
        path = output_dir / f"consumer_{safe_filename(customer_code)}.json"
        write_json(path, payload)
        print(f"wrote {path} (ai_consumer={ai_consumer}, user_id={customer_code})")

    if not consumers:
        print("no enabled consumer with customer_code; skipped per-consumer requests",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
