#!/usr/bin/env python3
import csv
import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUT = ROOT / "index.html"
README = ROOT / "README.md"
PRICE = 9980


def latest_suffix():
    summaries = sorted(WORK.glob("report_summary_*.json"))
    if not summaries:
        raise SystemExit("No report_summary files found under work/.")
    latest = max(summaries, key=lambda path: tuple(path.stem.split("_")[-2:]))
    return "_".join(latest.stem.split("_")[-2:])


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def num(value):
    if value in (None, ""):
        return 0.0
    return float(str(value).replace(",", ""))


def fmt_int(value):
    return f"{round(value):,}"


def fmt_twd(value):
    return f"TWD {round(value):,}"


def fmt_budget(value):
    return f"{fmt_twd(value)} / 日"


def fmt_pct(value):
    return f"{value:+.1f}%"


def fmt_roas(value):
    return "-" if not value else f"{value:.2f}"


def fmt_delta_twd(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{round(value):,}"


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


def effect_note(effect):
    return {
        "不錯": "可優先承接更多量體",
        "普通": "保留觀察，不急著擴張",
        "較差": "應優先回收預算或縮小測試",
    }.get(effect, "")


def chart_width(value, max_value):
    if max_value <= 0:
        return "0%"
    return f"{max(8, min(100, value / max_value * 100)):.1f}%"


def build_data():
    suffix = latest_suffix()
    start, end = suffix.split("_")
    summary = load_json(WORK / f"report_summary_{suffix}.json")
    inputs = load_json(WORK / "recommendation_inputs.json")
    recs = load_json(WORK / "ai_recommendations.json")
    adset_rows = load_csv(WORK / f"meta_ads_adsets_{suffix}.csv")
    age_rows = load_csv(WORK / f"meta_ads_age_{suffix}.csv")
    platform_rows = load_csv(WORK / f"meta_ads_platform_{suffix}.csv")
    gender_rows = load_csv(WORK / f"meta_ads_gender_{suffix}.csv")

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
            dim_entry = {
                "name": dim,
                "title": {"年齡": "Age Window", "平臺": "Placement Mix", "性別": "Gender Signal"}[dim],
                "fixed": dim_rule["fixed_rule_conclusion"],
                "advice": recs["dimension_advice"][dim_key],
                "segments": segs,
            }
            adset["dimensions"].append(dim_entry)
        adsets.append(adset)

    adsets.sort(key=lambda item: (effect_rank(item["effect"]), -item["spend"]))
    best_roas = max(adsets, key=lambda item: (item["roas"], item["estimated_revenue"]))
    lowest_cpa = min([item for item in adsets if item["results"] > 0], key=lambda item: item["cpa"])
    biggest_cut = min(adsets, key=lambda item: item["budget_delta"])
    biggest_raise = max(adsets, key=lambda item: item["budget_delta"])
    budget_delta = summary["adjusted_budget"] - summary["current_budget"]
    roas = summary["total_revenue"] / summary["total_spend"] if summary["total_spend"] else 0
    budget_change_pct = (
        ((summary["adjusted_budget"] / summary["current_budget"]) - 1) * 100 if summary["current_budget"] else 0
    )
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "suffix": suffix,
        "start": start,
        "end": end,
        "summary": summary,
        "adsets": adsets,
        "best_roas": best_roas["name"],
        "lowest_cpa": lowest_cpa["name"],
        "biggest_cut": biggest_cut["name"],
        "biggest_raise": biggest_raise["name"],
        "budget_delta": budget_delta,
        "budget_change_pct": budget_change_pct,
        "overall_roas": roas,
        "generated_at": generated_at,
    }


def render_segment_rows(adset):
    blocks = []
    for dimension in adset["dimensions"]:
        max_spend = max((seg["spend"] for seg in dimension["segments"]), default=0)
        rows = []
        for segment in dimension["segments"]:
            rows.append(
                f"""
                <tr>
                  <td>{html.escape(segment["label"])}</td>
                  <td>{fmt_int(segment["results"]) if segment["results"] else "-"}</td>
                  <td>{fmt_twd(segment["cpa"]) if segment["cpa"] else "-"}</td>
                  <td>
                    <div class="meter">
                      <span class="meter-fill" style="width:{chart_width(segment["spend"], max_spend)}"></span>
                      <strong>{fmt_twd(segment["spend"]) if segment["spend"] else "-"}</strong>
                    </div>
                  </td>
                  <td>{fmt_int(segment["purchases"]) if segment["purchases"] else "-"}</td>
                  <td>{fmt_roas(segment["roas"])}</td>
                </tr>
                """
            )
        blocks.append(
            f"""
            <section class="dimension-block">
              <div class="dimension-head">
                <div>
                  <p class="dimension-kicker">{dimension["title"]}</p>
                  <h4>{html.escape(dimension["name"])}</h4>
                </div>
                <span class="decision-chip">{html.escape(dimension["fixed"])}</span>
              </div>
              <p class="dimension-copy">{html.escape(dimension["advice"])}</p>
              <div class="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Breakdown</th>
                      <th>成果</th>
                      <th>CPA</th>
                      <th>花費</th>
                      <th>購買數</th>
                      <th>ROAS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {"".join(rows)}
                  </tbody>
                </table>
              </div>
            </section>
            """
        )
    return "".join(blocks)


def render_adset_cards(data):
    blocks = []
    for adset in data["adsets"]:
        blocks.append(
            f"""
            <article class="adset-card effect-{html.escape(adset["effect"])}">
              <div class="adset-topline">
                <p class="adset-label">Ad Set</p>
                <span class="effect-pill">{html.escape(adset["effect"])}</span>
              </div>
              <div class="adset-heading">
                <h3>{html.escape(adset["name"])}</h3>
                <p>{html.escape(effect_note(adset["effect"]))}</p>
              </div>
              <div class="metric-grid">
                <div class="metric-box"><span>花費</span><strong>{fmt_twd(adset["spend"])}</strong></div>
                <div class="metric-box"><span>成果</span><strong>{fmt_int(adset["results"])}</strong></div>
                <div class="metric-box"><span>CPA</span><strong>{fmt_twd(adset["cpa"])}</strong></div>
                <div class="metric-box"><span>購買 / ROAS</span><strong>{fmt_int(adset["purchases"])} / {fmt_roas(adset["roas"])}</strong></div>
              </div>
              <div class="budget-band">
                <div>
                  <p>目前預算</p>
                  <strong>{fmt_budget(adset["budget"])}</strong>
                </div>
                <div>
                  <p>建議預算</p>
                  <strong>{fmt_budget(adset["adjusted_budget"])}</strong>
                </div>
                <div>
                  <p>日變化</p>
                  <strong>{fmt_delta_twd(adset["budget_delta"])} TWD</strong>
                </div>
              </div>
              <p class="budget-copy">{html.escape(adset["budget_advice"])}</p>
              <div class="dimension-grid">
                {render_segment_rows(adset)}
              </div>
            </article>
            """
        )
    return "".join(blocks)


def render_overview_rows(data):
    max_spend = max(adset["spend"] for adset in data["adsets"])
    rows = []
    for adset in data["adsets"]:
        rows.append(
            f"""
            <tr>
              <td>
                <div class="adset-cell">
                  <strong>{html.escape(adset["name"])}</strong>
                  <span>{html.escape(adset["rule"])}</span>
                </div>
              </td>
              <td><span class="effect-pill">{html.escape(adset["effect"])}</span></td>
              <td>{fmt_twd(adset["spend"])}</td>
              <td>{fmt_int(adset["results"])}</td>
              <td>{fmt_twd(adset["cpa"])}</td>
              <td>{fmt_int(adset["purchases"]) if adset["purchases"] else "-"}</td>
              <td>{fmt_roas(adset["roas"])}</td>
              <td>{fmt_budget(adset["budget"])}</td>
              <td>{fmt_budget(adset["adjusted_budget"])}</td>
              <td>
                <div class="meter">
                  <span class="meter-fill" style="width:{chart_width(adset["spend"], max_spend)}"></span>
                  <strong>{fmt_delta_twd(adset["budget_delta"])} TWD</strong>
                </div>
              </td>
            </tr>
            """
        )
    return "".join(rows)


def build_html(data):
    summary = data["summary"]
    hero_cards = [
        ("總花費", fmt_twd(summary["total_spend"])),
        ("成果", fmt_int(summary["results"])),
        ("購買數", fmt_int(summary["purchases"])),
        ("整體 ROAS", f"{data['overall_roas']:.2f}"),
        ("目前日預算", fmt_budget(summary["current_budget"])),
        ("建議日預算", fmt_budget(summary["adjusted_budget"])),
    ]
    hero_stats = "".join(
        f'<article class="hero-stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>'
        for label, value in hero_cards
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Meta Ads 電子版成效報表 | {html.escape(summary["tab"])}</title>
    <meta
      name="description"
      content="Meta Ads 電子版成效報表，涵蓋 {html.escape(data["start"])} 到 {html.escape(data["end"])} 的花費、成果、ROAS 與 ad set 操作建議。"
    />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=Sora:wght@400;600;700;800&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {{
        --bg: #f6f0e8;
        --paper: #fffdf9;
        --panel: rgba(255, 255, 255, 0.72);
        --ink: #132321;
        --muted: #5d6a67;
        --line: rgba(19, 35, 33, 0.12);
        --sea: #0f766e;
        --mint: #d7f0e8;
        --sand: #ffe0b5;
        --rose: #ffd0cf;
        --sky: #c8dfff;
        --shadow: 0 24px 60px rgba(17, 24, 39, 0.08);
      }}
      * {{
        box-sizing: border-box;
      }}
      html {{
        scroll-behavior: smooth;
      }}
      body {{
        margin: 0;
        min-width: 320px;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(15, 118, 110, 0.18), transparent 32%),
          radial-gradient(circle at top right, rgba(255, 165, 0, 0.16), transparent 30%),
          linear-gradient(180deg, #f9f5ef 0%, #f4ece2 45%, #efe7dc 100%);
        font: 400 16px/1.65 "Noto Sans TC", ui-sans-serif, sans-serif;
      }}
      a {{
        color: inherit;
      }}
      img {{
        max-width: 100%;
        display: block;
      }}
      .shell {{
        width: min(1320px, calc(100% - 32px));
        margin: 0 auto;
      }}
      .hero {{
        position: relative;
        overflow: hidden;
        padding: 42px 0 28px;
      }}
      .hero::before,
      .hero::after {{
        content: "";
        position: absolute;
        border-radius: 999px;
        filter: blur(8px);
      }}
      .hero::before {{
        inset: 42px auto auto -60px;
        width: 220px;
        height: 220px;
        background: rgba(15, 118, 110, 0.12);
      }}
      .hero::after {{
        inset: auto -20px 10px auto;
        width: 280px;
        height: 280px;
        background: rgba(255, 176, 84, 0.16);
      }}
      .hero-grid {{
        position: relative;
        display: grid;
        grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
        gap: 20px;
        align-items: stretch;
      }}
      .hero-copy,
      .hero-panel,
      .band,
      .overview,
      .adset-card,
      .method-card {{
        border: 1px solid var(--line);
        border-radius: 28px;
        background: var(--panel);
        box-shadow: var(--shadow);
        backdrop-filter: blur(16px);
      }}
      .hero-copy {{
        padding: 34px;
      }}
      .hero-kicker {{
        margin: 0 0 14px;
        color: var(--sea);
        font: 800 13px/1 "Sora", sans-serif;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }}
      h1, h2, h3, h4, p {{
        margin: 0;
      }}
      h1 {{
        max-width: 12ch;
        font: 800 clamp(36px, 7vw, 72px)/0.96 "Sora", sans-serif;
        letter-spacing: -0.04em;
      }}
      .hero-copy .lede {{
        max-width: 62ch;
        margin-top: 18px;
        color: var(--muted);
        font-size: 18px;
      }}
      .hero-notes {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 22px;
      }}
      .hero-notes span,
      .effect-pill,
      .decision-chip {{
        display: inline-flex;
        align-items: center;
        min-height: 34px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid rgba(19, 35, 33, 0.09);
        background: rgba(255, 255, 255, 0.72);
        font-weight: 700;
      }}
      .hero-panel {{
        position: relative;
        overflow: hidden;
        padding: 28px;
      }}
      .hero-panel::after {{
        content: "";
        position: absolute;
        inset: auto -50px -60px auto;
        width: 180px;
        height: 180px;
        border-radius: 50%;
        background: linear-gradient(135deg, rgba(15, 118, 110, 0.12), rgba(120, 175, 255, 0.08));
      }}
      .panel-kicker {{
        margin-bottom: 10px;
        color: var(--muted);
        font-size: 14px;
      }}
      .panel-number {{
        display: flex;
        align-items: end;
        gap: 10px;
        font-family: "Sora", sans-serif;
      }}
      .panel-number strong {{
        font-size: clamp(42px, 8vw, 74px);
        line-height: 0.95;
      }}
      .panel-number span {{
        margin-bottom: 10px;
        color: var(--muted);
      }}
      .budget-delta {{
        margin-top: 18px;
        padding: 18px;
        border-radius: 22px;
        background: linear-gradient(135deg, rgba(15, 118, 110, 0.12), rgba(255, 255, 255, 0.9));
      }}
      .budget-delta small {{
        display: block;
        color: var(--muted);
        font-size: 13px;
      }}
      .budget-delta strong {{
        display: block;
        margin-top: 6px;
        font: 700 28px/1.1 "Sora", sans-serif;
      }}
      .hero-stat-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-top: 26px;
      }}
      .hero-stat {{
        padding: 16px 18px;
        border-radius: 22px;
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid rgba(19, 35, 33, 0.08);
      }}
      .hero-stat span,
      .metric-box span,
      .budget-band p {{
        display: block;
        color: var(--muted);
        font-size: 13px;
      }}
      .hero-stat strong,
      .metric-box strong,
      .budget-band strong {{
        display: block;
        margin-top: 8px;
        font: 700 26px/1.08 "Sora", sans-serif;
      }}
      .topbar {{
        position: sticky;
        top: 0;
        z-index: 20;
        border-block: 1px solid rgba(19, 35, 33, 0.08);
        background: rgba(246, 240, 232, 0.78);
        backdrop-filter: blur(16px);
      }}
      .topbar .shell {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        min-height: 64px;
      }}
      .brand {{
        font: 800 16px/1 "Sora", sans-serif;
      }}
      .nav-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        color: var(--muted);
        font-size: 14px;
      }}
      main {{
        padding: 28px 0 60px;
      }}
      .band {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0;
        overflow: hidden;
      }}
      .band article {{
        padding: 22px 24px;
        border-right: 1px solid rgba(19, 35, 33, 0.08);
      }}
      .band article:last-child {{
        border-right: 0;
      }}
      .band label {{
        display: block;
        color: var(--muted);
        font-size: 13px;
      }}
      .band strong {{
        display: block;
        margin-top: 10px;
        font: 800 30px/1.05 "Sora", sans-serif;
      }}
      .band p {{
        margin-top: 8px;
        color: var(--muted);
      }}
      .section-head {{
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 16px;
        margin: 42px 0 16px;
      }}
      .section-head h2 {{
        font: 800 clamp(26px, 4.2vw, 42px)/1.02 "Sora", sans-serif;
        letter-spacing: -0.04em;
      }}
      .section-head p {{
        max-width: 58ch;
        color: var(--muted);
      }}
      .overview {{
        overflow: hidden;
      }}
      .table-wrap {{
        overflow-x: auto;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th,
      td {{
        padding: 15px 16px;
        border-bottom: 1px solid rgba(19, 35, 33, 0.08);
        text-align: left;
        vertical-align: middle;
        white-space: nowrap;
      }}
      th {{
        color: var(--muted);
        font-size: 13px;
        font-weight: 700;
      }}
      tbody tr:hover {{
        background: rgba(255, 255, 255, 0.6);
      }}
      .adset-cell {{
        display: grid;
        gap: 4px;
      }}
      .adset-cell strong {{
        font-weight: 800;
      }}
      .adset-cell span {{
        color: var(--muted);
        font-size: 13px;
        white-space: normal;
      }}
      .meter {{
        position: relative;
        overflow: hidden;
        min-width: 160px;
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(15, 118, 110, 0.08);
      }}
      .meter-fill {{
        position: absolute;
        inset: 0 auto 0 0;
        background: linear-gradient(90deg, rgba(15, 118, 110, 0.18), rgba(15, 118, 110, 0.34));
      }}
      .meter strong {{
        position: relative;
        z-index: 1;
        font-size: 13px;
      }}
      .adset-grid {{
        display: grid;
        gap: 18px;
      }}
      .adset-card {{
        padding: 24px;
      }}
      .effect-不錯 {{
        box-shadow: 0 24px 60px rgba(14, 116, 110, 0.14);
      }}
      .effect-較差 {{
        box-shadow: 0 24px 60px rgba(220, 38, 38, 0.08);
      }}
      .adset-topline,
      .dimension-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }}
      .adset-label,
      .dimension-kicker {{
        color: var(--muted);
        font: 700 12px/1 "Sora", sans-serif;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }}
      .adset-heading {{
        margin-top: 16px;
      }}
      .adset-heading h3 {{
        font: 800 clamp(24px, 4vw, 36px)/1 "Sora", sans-serif;
        letter-spacing: -0.04em;
      }}
      .adset-heading p {{
        margin-top: 10px;
        color: var(--muted);
      }}
      .metric-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-top: 18px;
      }}
      .metric-box,
      .method-card {{
        padding: 16px;
        border-radius: 22px;
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid rgba(19, 35, 33, 0.08);
      }}
      .budget-band {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-top: 18px;
      }}
      .budget-band > div {{
        padding: 16px;
        border-radius: 22px;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(240, 247, 245, 0.9));
        border: 1px solid rgba(19, 35, 33, 0.08);
      }}
      .budget-copy,
      .dimension-copy {{
        margin-top: 14px;
        color: var(--muted);
      }}
      .dimension-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
        margin-top: 18px;
      }}
      .dimension-block {{
        padding: 16px;
        border-radius: 24px;
        background: rgba(250, 247, 241, 0.76);
        border: 1px solid rgba(19, 35, 33, 0.08);
      }}
      .dimension-block h4 {{
        margin-top: 6px;
        font: 800 22px/1.05 "Sora", sans-serif;
      }}
      .table-shell {{
        margin-top: 12px;
        overflow-x: auto;
        border-radius: 18px;
        border: 1px solid rgba(19, 35, 33, 0.07);
      }}
      .table-shell table {{
        min-width: 100%;
        background: rgba(255, 255, 255, 0.8);
      }}
      .table-shell th,
      .table-shell td {{
        padding: 11px 12px;
      }}
      .method-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
      }}
      .method-card strong {{
        display: block;
        font: 800 20px/1.1 "Sora", sans-serif;
      }}
      .method-card p {{
        margin-top: 10px;
        color: var(--muted);
      }}
      footer {{
        padding: 26px 0 40px;
        color: var(--muted);
        font-size: 14px;
      }}
      @media (max-width: 1120px) {{
        .hero-grid,
        .dimension-grid,
        .method-grid {{
          grid-template-columns: 1fr;
        }}
        .metric-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}
      @media (max-width: 860px) {{
        .hero-stat-grid,
        .band,
        .budget-band {{
          grid-template-columns: 1fr;
        }}
        .band article {{
          border-right: 0;
          border-bottom: 1px solid rgba(19, 35, 33, 0.08);
        }}
        .band article:last-child {{
          border-bottom: 0;
        }}
        .topbar .shell,
        .section-head {{
          align-items: start;
          flex-direction: column;
        }}
      }}
      @media (max-width: 640px) {{
        .shell {{
          width: min(100% - 20px, 1320px);
        }}
        .hero-copy,
        .hero-panel,
        .adset-card {{
          padding: 20px;
        }}
        .metric-grid {{
          grid-template-columns: 1fr;
        }}
        th,
        td {{
          padding: 12px 10px;
        }}
      }}
    </style>
  </head>
  <body>
    <header class="hero" id="top">
      <div class="shell hero-grid">
        <section class="hero-copy">
          <p class="hero-kicker">Meta Ads Report · Electronic Edition</p>
          <h1>{html.escape(summary["tab"])} 的 Meta 廣告決策版報表</h1>
          <p class="lede">
            這份頁面把原本 Google Sheets 的週期報表重組成更適合閱讀與決策的 dashboard。
            重點不只是看數字，而是直接看哪個 ad set 應該加、哪些維度該收斂、哪些地方只應維持觀察。
          </p>
          <div class="hero-notes">
            <span>資料區間：{html.escape(data["start"])} 至 {html.escape(data["end"])}</span>
            <span>帳號：1985753195620846</span>
            <span>產生時間：{html.escape(data["generated_at"])}</span>
          </div>
          <div class="hero-stat-grid">
            {hero_stats}
          </div>
        </section>
        <aside class="hero-panel">
          <p class="panel-kicker">本期總體判讀</p>
          <div class="panel-number">
            <strong>{fmt_pct(data["budget_change_pct"])}</strong>
            <span>建議日預算變動</span>
          </div>
          <div class="budget-delta">
            <small>由 {fmt_budget(summary["current_budget"])} 調整為 {fmt_budget(summary["adjusted_budget"])}</small>
            <strong>{fmt_delta_twd(data["budget_delta"])} TWD / 日</strong>
          </div>
          <div class="hero-stat-grid">
            <article class="hero-stat">
              <span>最高 ROAS</span>
              <strong>{html.escape(data["best_roas"])}</strong>
            </article>
            <article class="hero-stat">
              <span>最低 CPA</span>
              <strong>{html.escape(data["lowest_cpa"])}</strong>
            </article>
            <article class="hero-stat">
              <span>最大預算下修</span>
              <strong>{html.escape(data["biggest_cut"])}</strong>
            </article>
          </div>
        </aside>
      </div>
    </header>

    <nav class="topbar">
      <div class="shell">
        <div class="brand">Meta Ads Decision Dashboard</div>
        <div class="nav-links">
          <a href="#overview">整體比較</a>
          <a href="#adsets">Ad Set 詳細</a>
          <a href="#method">方法與資料來源</a>
        </div>
      </div>
    </nav>

    <main class="shell">
      <section class="band" aria-label="Quick takeaways">
        <article>
          <label>本期最值得加碼</label>
          <strong>{html.escape(data["best_roas"])}</strong>
          <p>以本期購買 ROAS / 推估營收來看，是最接近可承接更多量體的 ad set。</p>
        </article>
        <article>
          <label>最值得保守控管</label>
          <strong>{html.escape(data["biggest_cut"])}</strong>
          <p>這組被規則層判定需要優先回收日預算，避免把花費留在低效區段。</p>
        </article>
        <article>
          <label>整體判斷</label>
          <strong>{fmt_twd(summary["total_revenue"] - summary["total_spend"])}</strong>
          <p>目前仍有正向推估淨利，但預算方向應該更集中，而不是全面放大。</p>
        </article>
      </section>

      <section id="overview">
        <div class="section-head">
          <div>
            <h2>Ad Set 總覽比較</h2>
            <p>先用同一張表看花費、成果、CPA、購買、ROAS 和預算調整方向，快速知道每一組的優先順序。</p>
          </div>
        </div>
        <div class="overview">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ad Set</th>
                  <th>成效</th>
                  <th>花費</th>
                  <th>成果</th>
                  <th>CPA</th>
                  <th>購買數</th>
                  <th>ROAS</th>
                  <th>目前預算</th>
                  <th>建議預算</th>
                  <th>預算變化</th>
                </tr>
              </thead>
              <tbody>
                {render_overview_rows(data)}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="adsets">
        <div class="section-head">
          <div>
            <h2>每組詳細操作建議</h2>
            <p>每個 ad set 下面都保留三層資訊：目前成效、預算決策、以及年齡 / 平台 / 性別的可操作建議與證據。</p>
          </div>
        </div>
        <div class="adset-grid">
          {render_adset_cards(data)}
        </div>
      </section>

      <section id="method">
        <div class="section-head">
          <div>
            <h2>方法與資料來源</h2>
            <p>這不是手填網頁。頁面來自同一份 Meta 匯出資料與規則驗證結果，目的是讓這份報表之後可以持續電子化更新。</p>
          </div>
        </div>
        <div class="method-grid">
          <article class="method-card">
            <strong>Exact Period Export</strong>
            <p>資料只使用 {html.escape(data["start"])} 到 {html.escape(data["end"])} 的 Meta Ads 匯出，沒有用更長時間再手動切片。</p>
          </article>
          <article class="method-card">
            <strong>Rule First, AI Second</strong>
            <p>先由固定規則判定預算與維度方向，再生成自然語言建議，最後再經過 validator 檢查避免錯配。</p>
          </article>
          <article class="method-card">
            <strong>Static and Deployable</strong>
            <p>網站是靜態單頁，適合直接丟上 GitHub 與 Vercel；也代表之後只要重跑 generator 就能更新下一期。</p>
          </article>
        </div>
      </section>
    </main>

    <footer class="shell">
      <p>
        Source period: {html.escape(data["start"])} 至 {html.escape(data["end"])} · Generated from local Meta export artifacts ·
        <a href="#top">回到頂部</a>
      </p>
    </footer>
  </body>
</html>
"""


def build_readme(data):
    return f"""# Meta Ads 電子版成效報表

這個 repo 目前部署的是 `{data["summary"]["tab"]}` 的 Meta Ads 電子版報表。

## 內容

- 靜態首頁：`index.html`
- 原始首頁備份：`campaign-library.html`
- 生成腳本：`scripts/build_report_site.py`

## 重新產生

在專案根目錄執行：

```bash
python3 scripts/build_report_site.py
```

腳本會自動抓 `work/` 底下最新的 `report_summary_*.json`，並用同 suffix 的 Meta 匯出資料重建網站首頁。
"""


def main():
    data = build_data()
    OUTPUT.write_text(build_html(data), encoding="utf-8")
    README.write_text(build_readme(data), encoding="utf-8")
    print(json.dumps({"index": str(OUTPUT), "readme": str(README), "suffix": data["suffix"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
