from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.report_payload import build_payload

RUNNER = ROOT / "scripts" / "run_meta_api_report.py"
TAIPEI = ZoneInfo("Asia/Taipei")
CACHE_ROOT = Path(tempfile.gettempdir()) / "meta-report-cache"


def today_taipei() -> date:
    return datetime.now(TAIPEI).date()


def parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {value}") from exc


def resolve_period(query: dict[str, list[str]]) -> tuple[date, date]:
    end_raw = query.get("end", [None])[0]
    start_raw = query.get("start", [None])[0]

    if end_raw:
        end = parse_iso_date(end_raw, "end")
    else:
        end = today_taipei()

    if start_raw:
        start = parse_iso_date(start_raw, "start")
    else:
        start = end - timedelta(days=6)

    if start > end:
        raise ValueError("start must be on or before end")
    return start, end


def refresh_requested(query: dict[str, list[str]]) -> bool:
    value = (query.get("refresh", ["1"])[0] or "1").lower()
    return value not in {"0", "false", "no"}


def run_pipeline(start: date, end: date, work_dir: Path) -> None:
    command = [
        sys.executable,
        str(RUNNER),
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--tab",
        f"{start.month}/{start.day} ~ {end.month}/{end.day}",
        "--work-dir",
        str(work_dir),
        "--skip-site",
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


def get_payload(start: date, end: date, force_refresh: bool) -> dict:
    suffix = f"{start.isoformat()}_{end.isoformat()}"
    work_dir = CACHE_ROOT / suffix
    payload_file = work_dir / "payload.json"

    if force_refresh or not payload_file.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        run_pipeline(start, end, work_dir)
        payload = build_payload(work_dir, suffix=suffix, generated_at=datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M"))
        payload_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    return json.loads(payload_file.read_text(encoding="utf-8"))


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/meta_report":
            self._send_json(404, {"error": "Not found"})
            return

        query = parse_qs(parsed.query)
        try:
            start, end = resolve_period(query)
            payload = get_payload(start, end, refresh_requested(query))
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except subprocess.CalledProcessError as exc:
            self._send_json(
                500,
                {
                    "error": "Meta report pipeline failed",
                    "details": (exc.stderr or exc.stdout or str(exc)).strip(),
                },
            )
            return
        except Exception as exc:  # pragma: no cover - defensive surface for serverless runtime
            self._send_json(500, {"error": "Unexpected server error", "details": str(exc)})
            return

        self._send_json(200, payload)

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - keep serverless logs quiet
        return

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
