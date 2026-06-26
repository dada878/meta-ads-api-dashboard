#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def parse_args():
    parser = argparse.ArgumentParser(description="Run the Meta API export and rebuild the local report artifacts.")
    parser.add_argument("--start", required=True, help="Inclusive start date in YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Inclusive end date in YYYY-MM-DD.")
    parser.add_argument("--tab", help="Tab label, defaults to M/D ~ M/D.")
    parser.add_argument("--account-id", help="Meta ad account id without the act_ prefix.")
    parser.add_argument("--env-file", default=str(ROOT / ".env.meta"), help="Path to a KEY=VALUE env file.")
    parser.add_argument("--work-dir", default=str(ROOT / "work"), help="Directory for generated report artifacts.")
    parser.add_argument("--skip-site", action="store_true", help="Only rebuild CSV/report JSON, skip the website.")
    return parser.parse_args()


def default_tab(start, end):
    start_month, start_day = start.split("-")[1:]
    end_month, end_day = end.split("-")[1:]
    return f"{int(start_month)}/{int(start_day)} ~ {int(end_month)}/{int(end_day)}"


def run(cmd):
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    args = parse_args()
    tab = args.tab or default_tab(args.start, args.end)

    fetch_cmd = [
        sys.executable,
        str(SCRIPTS / "fetch_meta_insights.py"),
        "--start",
        args.start,
        "--end",
        args.end,
        "--env-file",
        args.env_file,
        "--work-dir",
        args.work_dir,
    ]
    if args.account_id:
        fetch_cmd.extend(["--account-id", args.account_id])
    run(fetch_cmd)

    run(
        [
            sys.executable,
            str(SCRIPTS / "build_meta_report.py"),
            "--start",
            args.start,
            "--end",
            args.end,
            "--tab",
            tab,
            "--work-dir",
            args.work_dir,
        ]
    )

    if not args.skip_site:
        run([sys.executable, str(ROOT / "build_report_site.py")])


if __name__ == "__main__":
    main()
