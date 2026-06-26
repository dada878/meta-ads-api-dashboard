#!/usr/bin/env python3
import argparse
import csv
import hashlib
import hmac
import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency
    certifi = None


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
DEFAULT_ENV = ROOT / ".env.meta"

TOTAL_HEADERS = [
    "行銷活動名稱",
    "廣告組合名稱",
    "曝光次數",
    "點擊次數（全部）",
    "花費金額 (TWD)",
    "成果類型",
    "成果",
    "每次成果成本",
    "貼文心情數",
    "貼文留言數",
    "貼文分享次數",
    "Facebook 的讚",
    "購買次數",
    "購買 ROAS（廣告投資報酬率）",
    "廣告組合預算",
    "廣告組合預算類型",
    "分析報告開始",
    "分析報告結束",
    "成果（初始）",
]

BREAKDOWN_HEADERS = {
    "age": ["行銷活動名稱", "廣告組合名稱", "年齡", *TOTAL_HEADERS[2:]],
    "publisher_platform": ["行銷活動名稱", "廣告組合名稱", "平台", *TOTAL_HEADERS[2:]],
    "gender": ["行銷活動名稱", "廣告組合名稱", "性別", *TOTAL_HEADERS[2:]],
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch Meta Marketing API insights and write report-compatible CSV files."
    )
    parser.add_argument("--start", required=True, help="Inclusive start date in YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Inclusive end date in YYYY-MM-DD.")
    parser.add_argument("--account-id", help="Meta ad account id without the act_ prefix.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV), help="Path to a KEY=VALUE env file.")
    parser.add_argument("--work-dir", default=str(WORK), help="Directory for generated CSV artifacts.")
    parser.add_argument("--api-version", help="Graph API version, e.g. v24.0.")
    parser.add_argument("--result-action-type", help="Primary action_type to treat as 成果.")
    parser.add_argument("--result-label", help="Display label for 成果類型.")
    parser.add_argument(
        "--purchase-action-types",
        help="Comma-separated purchase action_type candidates in priority order.",
    )
    return parser.parse_args()


def load_env_file(path_str):
    path = Path(path_str).expanduser()
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def require(value, label):
    if value:
        return value
    raise SystemExit(f"Missing required config: {label}")


def num(value):
    if value in (None, "", "null"):
        return 0.0
    return float(str(value).replace(",", ""))


def integer_string(value):
    if not value:
        return ""
    return str(int(round(value)))


def decimal_string(value):
    if not value:
        return ""
    return f"{value:.8f}".rstrip("0").rstrip(".")


def action_value(items, candidates):
    if not isinstance(items, list):
        return 0.0
    candidate_set = list(candidates)
    for action_type in candidate_set:
        for item in items:
            if item.get("action_type") == action_type:
                return num(item.get("value"))
    return 0.0


def appsecret_proof(token, app_secret):
    if not app_secret:
        return None
    digest = hmac.new(app_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def build_ssl_context():
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


class MetaClient:
    def __init__(self, token, app_secret=None, api_version="v24.0"):
        self.token = token
        self.api_version = api_version
        self.app_secret = app_secret
        self.proof = appsecret_proof(token, app_secret)
        self.ssl_context = build_ssl_context()

    def fetch_all(self, path, params):
        items = []
        after = None
        while True:
            payload = self._request(path, params | ({ "after": after } if after else {}))
            items.extend(payload.get("data", []))
            after = payload.get("paging", {}).get("cursors", {}).get("after")
            if not after:
                return items

    def _request(self, path, params):
        query = {
            "access_token": self.token,
            "limit": 500,
            **params,
        }
        if self.proof:
            query["appsecret_proof"] = self.proof
        url = f"https://graph.facebook.com/{self.api_version}/{path}?{urlencode(query, doseq=True)}"
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, context=self.ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                raise SystemExit(f"Meta API HTTP {exc.code}: {raw}") from exc
            error = payload.get("error", {})
            message = error.get("message", f"HTTP {exc.code}")
            raise SystemExit(f"Meta API request failed: {message}") from exc
        if "error" in payload:
            message = payload["error"].get("message", "Unknown Meta API error")
            raise SystemExit(f"Meta API request failed: {message}")
        return payload


def fetch_adset_map(client, account_id):
    fields = ",".join(
        [
            "id",
            "name",
            "campaign{name}",
            "daily_budget",
            "lifetime_budget",
            "bid_amount",
            "bid_strategy",
            "effective_status",
        ]
    )
    rows = client.fetch_all(f"act_{account_id}/adsets", {"fields": fields})
    return {
        row["id"]: {
            "name": row.get("name", ""),
            "campaign_name": (row.get("campaign") or {}).get("name", ""),
            "daily_budget": num(row.get("daily_budget")),
            "lifetime_budget": num(row.get("lifetime_budget")),
            "effective_status": row.get("effective_status", ""),
        }
        for row in rows
    }


def insights_params(start, end, breakdown=None):
    params = {
        "time_range": json.dumps({"since": start, "until": end}, separators=(",", ":")),
        "time_increment": "all_days",
        "level": "adset",
        "fields": ",".join(
            [
                "campaign_name",
                "adset_id",
                "adset_name",
                "impressions",
                "clicks",
                "spend",
                "actions",
                "cost_per_action_type",
                "purchase_roas",
                "date_start",
                "date_stop",
            ]
        ),
    }
    if breakdown:
        params["breakdowns"] = breakdown
    return params


def metric_row(raw, adset_meta, start, end, result_action_type, result_label, purchase_action_types):
    result_value = action_value(raw.get("actions"), [result_action_type])
    purchase_value = action_value(raw.get("actions"), purchase_action_types)
    purchase_roas = action_value(raw.get("purchase_roas"), purchase_action_types)
    cost_per_result = action_value(raw.get("cost_per_action_type"), [result_action_type])
    if not cost_per_result and result_value:
        cost_per_result = num(raw.get("spend")) / result_value

    budget_value = adset_meta.get("daily_budget") or adset_meta.get("lifetime_budget")
    budget_type = "每日" if adset_meta.get("daily_budget") else "終身" if adset_meta.get("lifetime_budget") else ""

    base = {
        "行銷活動名稱": raw.get("campaign_name") or adset_meta.get("campaign_name", ""),
        "廣告組合名稱": raw.get("adset_name") or adset_meta.get("name", ""),
        "曝光次數": integer_string(num(raw.get("impressions"))),
        "點擊次數（全部）": integer_string(num(raw.get("clicks"))),
        "花費金額 (TWD)": decimal_string(num(raw.get("spend"))),
        "成果類型": result_label,
        "成果": integer_string(result_value),
        "每次成果成本": decimal_string(cost_per_result),
        "貼文心情數": "",
        "貼文留言數": "",
        "貼文分享次數": "",
        "Facebook 的讚": "",
        "購買次數": integer_string(purchase_value),
        "購買 ROAS（廣告投資報酬率）": decimal_string(purchase_roas),
        "廣告組合預算": integer_string(budget_value),
        "廣告組合預算類型": budget_type,
        "分析報告開始": raw.get("date_start") or start,
        "分析報告結束": raw.get("date_stop") or end,
        "成果（初始）": integer_string(result_value),
    }
    return base


def normalize_age(value):
    if not value or value == "unknown":
        return "未分類"
    return value


def normalize_gender(value):
    if not value or value == "unknown":
        return "unknown"
    return value


def normalize_platform(value):
    if not value:
        return "unknown"
    return value


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def build_total_rows(client, account_id, start, end, adset_map, result_action_type, result_label, purchase_action_types):
    raw_rows = client.fetch_all(f"act_{account_id}/insights", insights_params(start, end))
    rows = []
    for raw in raw_rows:
        adset_meta = adset_map.get(raw.get("adset_id", ""), {})
        rows.append(metric_row(raw, adset_meta, start, end, result_action_type, result_label, purchase_action_types))
    return rows


def build_breakdown_rows(
    client,
    account_id,
    start,
    end,
    adset_map,
    breakdown,
    result_action_type,
    result_label,
    purchase_action_types,
):
    raw_rows = client.fetch_all(f"act_{account_id}/insights", insights_params(start, end, breakdown))
    output = []
    for raw in raw_rows:
        adset_meta = adset_map.get(raw.get("adset_id", ""), {})
        row = metric_row(raw, adset_meta, start, end, result_action_type, result_label, purchase_action_types)
        if breakdown == "age":
            row["年齡"] = normalize_age(raw.get("age"))
        elif breakdown == "gender":
            row["性別"] = normalize_gender(raw.get("gender"))
        elif breakdown == "publisher_platform":
            row["平台"] = normalize_platform(raw.get("publisher_platform"))
        output.append(row)
    return output


def suffix(start, end):
    return f"{start}_{end}"


def main():
    args = parse_args()
    env = {**load_env_file(args.env_file), **os.environ}
    work_dir = Path(args.work_dir).expanduser().resolve()

    token = require(env.get("META_ACCESS_TOKEN"), "META_ACCESS_TOKEN")
    app_secret = env.get("META_APP_SECRET", "")
    account_id = require(args.account_id or env.get("META_AD_ACCOUNT_ID"), "META_AD_ACCOUNT_ID / --account-id")
    api_version = args.api_version or env.get("META_API_VERSION") or "v24.0"
    result_action_type = args.result_action_type or env.get("META_RESULT_ACTION_TYPE") or "omni_complete_registration"
    result_label = args.result_label or env.get("META_RESULT_LABEL") or "網站完成註冊人數"
    purchase_action_types = (
        args.purchase_action_types or env.get("META_PURCHASE_ACTION_TYPES") or "omni_purchase,purchase,offsite_conversion.fb_pixel_purchase"
    )
    purchase_action_types = [item.strip() for item in purchase_action_types.split(",") if item.strip()]

    client = MetaClient(token=token, app_secret=app_secret, api_version=api_version)
    adset_map = fetch_adset_map(client, account_id)

    current_suffix = suffix(args.start, args.end)
    totals = build_total_rows(
        client,
        account_id,
        args.start,
        args.end,
        adset_map,
        result_action_type,
        result_label,
        purchase_action_types,
    )
    ages = build_breakdown_rows(
        client,
        account_id,
        args.start,
        args.end,
        adset_map,
        "age",
        result_action_type,
        result_label,
        purchase_action_types,
    )
    platforms = build_breakdown_rows(
        client,
        account_id,
        args.start,
        args.end,
        adset_map,
        "publisher_platform",
        result_action_type,
        result_label,
        purchase_action_types,
    )
    genders = build_breakdown_rows(
        client,
        account_id,
        args.start,
        args.end,
        adset_map,
        "gender",
        result_action_type,
        result_label,
        purchase_action_types,
    )

    write_csv(work_dir / f"meta_ads_adsets_{current_suffix}.csv", TOTAL_HEADERS, totals)
    write_csv(work_dir / f"meta_ads_age_{current_suffix}.csv", BREAKDOWN_HEADERS["age"], ages)
    write_csv(work_dir / f"meta_ads_platform_{current_suffix}.csv", BREAKDOWN_HEADERS["publisher_platform"], platforms)
    write_csv(work_dir / f"meta_ads_gender_{current_suffix}.csv", BREAKDOWN_HEADERS["gender"], genders)

    summary = {
        "account_id": account_id,
        "api_version": api_version,
        "result_action_type": result_action_type,
        "result_label": result_label,
        "rows": {
            "adsets": len(totals),
            "age": len(ages),
            "platform": len(platforms),
            "gender": len(genders),
        },
        "files": {
            "adsets": str(work_dir / f"meta_ads_adsets_{current_suffix}.csv"),
            "age": str(work_dir / f"meta_ads_age_{current_suffix}.csv"),
            "platform": str(work_dir / f"meta_ads_platform_{current_suffix}.csv"),
            "gender": str(work_dir / f"meta_ads_gender_{current_suffix}.csv"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
