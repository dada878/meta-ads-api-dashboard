#!/usr/bin/env python3
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PRICE = 9980


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def num(value):
    if value in (None, ""):
        return 0.0
    return float(str(value).replace(",", ""))


def revenue(row):
    roas = row.get("roas", 0.0)
    purchases = row.get("purchases", 0)
    spend = row.get("spend", 0.0)
    return spend * roas if roas else purchases * PRICE


def effect_rank(effect):
    return {"不錯": 0, "普通": 1, "較差": 2}.get(effect, 3)


def age_sort_key(item):
    order = {"18-24": 0, "25-34": 1, "35-44": 2, "45-54": 3, "55-64": 4, "65+": 5}
    return order.get(item, 99)


def translate_platform(item):
    return {
        "facebook": "Facebook",
        "audience_network": "Audience Network",
        "unknown": "未分類",
    }.get(item, item)


def translate_gender(item):
    return {
        "male": "男性",
        "female": "女性",
        "unknown": "未分類",
    }.get(item, item)


def latest_suffix(work_dir):
    summaries = sorted(Path(work_dir).glob("report_summary_*.json"))
    if not summaries:
        raise FileNotFoundError("No report_summary files found under work dir.")
    latest = max(summaries, key=lambda path: tuple(path.stem.split("_")[-2:]))
    return "_".join(latest.stem.split("_")[-2:])


def build_payload(work_dir, suffix=None, generated_at=None):
    work_dir = Path(work_dir)
    suffix = suffix or latest_suffix(work_dir)
    start, end = suffix.split("_")

    summary = load_json(work_dir / f"report_summary_{suffix}.json")
    inputs = load_json(work_dir / "recommendation_inputs.json")
    recs = load_json(work_dir / "ai_recommendations.json")
    adset_rows = load_csv(work_dir / f"meta_ads_adsets_{suffix}.csv")
    age_rows = load_csv(work_dir / f"meta_ads_age_{suffix}.csv")
    platform_rows = load_csv(work_dir / f"meta_ads_platform_{suffix}.csv")
    gender_rows = load_csv(work_dir / f"meta_ads_gender_{suffix}.csv")

    segments_by_dimension = {
        "年齡": defaultdict(list),
        "平臺": defaultdict(list),
        "性別": defaultdict(list),
    }

    for row in age_rows:
        segments_by_dimension["年齡"][row["廣告組合名稱"]].append(
            {
                "label": row["年齡"],
                "results": int(num(row["成果"])),
                "cpa": num(row["每次成果成本"]),
                "spend": num(row["花費金額 (TWD)"]),
                "purchases": int(num(row["購買次數"])),
                "roas": num(row["購買 ROAS（廣告投資報酬率）"]),
            }
        )

    for row in platform_rows:
        segments_by_dimension["平臺"][row["廣告組合名稱"]].append(
            {
                "label": translate_platform(row["平台"]),
                "results": int(num(row["成果"])),
                "cpa": num(row["每次成果成本"]),
                "spend": num(row["花費金額 (TWD)"]),
                "purchases": int(num(row["購買次數"])),
                "roas": num(row["購買 ROAS（廣告投資報酬率）"]),
            }
        )

    for row in gender_rows:
        segments_by_dimension["性別"][row["廣告組合名稱"]].append(
            {
                "label": translate_gender(row["性別"]),
                "results": int(num(row["成果"])),
                "cpa": num(row["每次成果成本"]),
                "spend": num(row["花費金額 (TWD)"]),
                "purchases": int(num(row["購買次數"])),
                "roas": num(row["購買 ROAS（廣告投資報酬率）"]),
            }
        )

    adsets = []
    for row in adset_rows:
        adset_name = row["廣告組合名稱"]
        budget_key = f"自動銷講::{adset_name}"
        budget_rule = inputs["adset_budget_rules"][budget_key]
        metrics = budget_rule["metrics"]
        current_budget = metrics["budget"]
        adjusted_budget = metrics["adjusted_budget"]
        adset = {
            "name": adset_name,
            "campaign": row["行銷活動名稱"],
            "results": int(num(row["成果"])),
            "cpa": num(row["每次成果成本"]),
            "spend": num(row["花費金額 (TWD)"]),
            "purchases": int(num(row["購買次數"])),
            "roas": num(row["購買 ROAS（廣告投資報酬率）"]),
            "budget": current_budget,
            "adjusted_budget": adjusted_budget,
            "budget_delta": adjusted_budget - current_budget,
            "effect": budget_rule["effect"],
            "rule": budget_rule["fixed_rule_conclusion"],
            "budget_advice": recs["adset_budget_advice"][budget_key],
            "estimated_revenue": revenue(metrics),
            "dimensions": [],
        }
        for dim in ("年齡", "平臺", "性別"):
            dim_key = f"{adset_name}::{dim}"
            dim_rule = inputs["dimension_rules"][dim_key]
            segs = list(segments_by_dimension[dim][adset_name])
            if dim == "年齡":
                segs.sort(key=lambda item: age_sort_key(item["label"]))
            else:
                segs.sort(key=lambda item: (-item["spend"], item["label"]))
            adset["dimensions"].append(
                {
                    "name": dim,
                    "title": {"年齡": "Age Window", "平臺": "Placement Mix", "性別": "Gender Signal"}[dim],
                    "fixed": dim_rule["fixed_rule_conclusion"],
                    "advice": recs["dimension_advice"][dim_key],
                    "segments": segs,
                }
            )
        adsets.append(adset)

    adsets.sort(key=lambda item: (effect_rank(item["effect"]), -item["spend"]))
    best_roas = max(adsets, key=lambda item: (item["roas"], item["estimated_revenue"]))
    lowest_cpa = min((item for item in adsets if item["results"] > 0), key=lambda item: item["cpa"])
    biggest_cut = min(adsets, key=lambda item: item["budget_delta"])
    biggest_raise = max(adsets, key=lambda item: item["budget_delta"])
    budget_delta = summary["adjusted_budget"] - summary["current_budget"]
    overall_roas = summary["total_revenue"] / summary["total_spend"] if summary["total_spend"] else 0
    budget_change_pct = (
        ((summary["adjusted_budget"] / summary["current_budget"]) - 1) * 100 if summary["current_budget"] else 0
    )

    return {
        "period": {
            "suffix": suffix,
            "start": start,
            "end": end,
            "tab": summary["tab"],
            "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "summary": {
            "rows": summary["rows"],
            "cols": summary["cols"],
            "total_spend": summary["total_spend"],
            "total_revenue": summary["total_revenue"],
            "current_budget": summary["current_budget"],
            "adjusted_budget": summary["adjusted_budget"],
            "results": summary["results"],
            "purchases": summary["purchases"],
            "budget_delta": budget_delta,
            "budget_change_pct": budget_change_pct,
            "overall_roas": overall_roas,
            "estimated_profit": summary["total_revenue"] - summary["total_spend"],
        },
        "highlights": {
            "best_roas": best_roas["name"],
            "lowest_cpa": lowest_cpa["name"],
            "biggest_cut": biggest_cut["name"],
            "biggest_raise": biggest_raise["name"],
        },
        "adsets": adsets,
    }
