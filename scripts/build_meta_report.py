#!/usr/bin/env python3
import argparse
import csv
import html
import json
from datetime import date
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
START = "2026-06-12"
END = "2026-06-18"
PERIOD = "2026-06-12 至 2026-06-18"
TAB = "6/12 ~ 6/18"
SUFFIX = "2026-06-12_2026-06-18"
ACCOUNT = "1985753195620846"
CAMPAIGN = "自動銷講"
PRICE = 9980


CURRENT_SETTINGS = {
    "業務": {"age": "45 到 64 歲", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
    "創業者 & Freelancer": {"age": "55 歲以上", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
    "已購課LAL": {"age": "25 到 44 歲", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
    "PM": {"age": "25 到 44 歲", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
    "廣泛受眾": {"age": "35 到 54 歲", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
    "行銷人": {"age": "45 到 54 歲", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
    "再行銷": {"age": "25 到 44 歲", "platform": "高效速成版位（平台由 Meta 自動分配）", "gender": "全部"},
}

ADSET_ORDER = ["再行銷", "已購課LAL", "行銷人", "創業者 & Freelancer", "業務", "PM", "廣泛受眾"]


def read_csv(name):
    with (WORK / name).open(encoding="utf-8-sig", newline="") as f:
        return [normalize_row(r) for r in csv.DictReader(f)]


def normalize_row(r):
    out = dict(r)
    # Ads Reporting exports use a lighter schema than Ads Manager table exports.
    # Normalize the few names and values the report builder consumes.
    if "成果類型" in out and "成果指標" not in out:
        out["成果指標"] = out.get("成果類型", "")
    if "CPM（每千次廣告曝光成本） (TWD)" not in out and "CPM（每千次廣告曝光成本）" in out:
        out["CPM（每千次廣告曝光成本） (TWD)"] = out.get("CPM（每千次廣告曝光成本）", "")
    if "廣告組合投遞" not in out:
        out["廣告組合投遞"] = "active"
    if "廣告組合預算" not in out:
        out["廣告組合預算"] = ""
    if "廣告組合預算類型" not in out:
        out["廣告組合預算類型"] = ""
    if out.get("平台") == "facebook":
        out["平台"] = "Facebook"
    elif out.get("平台") == "audience_network":
        out["平台"] = "Audience Network"
    elif out.get("平台") == "unknown":
        out["平台"] = "未分類"
    if out.get("性別") == "unknown":
        out["性別"] = "未分類"
    return out


def num(v):
    if v is None or v == "":
        return 0.0
    return float(str(v).replace(",", ""))


def fmt_twd(v):
    return f"TWD {round(v):,}"


def fmt_budget(v):
    return f"TWD {round(v):,} / 日"


def fmt_cpa(v):
    return fmt_twd(v) if v else ""


def fmt_roas(v):
    return f"{v:.2f}" if v else ""


def safe_text(v):
    if v is None:
        return ""
    return str(v).replace("\t", " ").replace("\n", " ")


def tsv_value(v):
    text = safe_text(v)
    if text.startswith(("+", "-", "=")):
        return "'" + text
    return text


def active_adsets(rows):
    out = {}
    for r in rows:
        if r.get("廣告組合投遞") == "active" and num(r.get("花費金額 (TWD)")) > 0:
            name = r["廣告組合名稱"]
            out[name] = {
                "adset": name,
                "results": int(num(r.get("成果"))),
                "cpa": num(r.get("每次成果成本")),
                "budget": num(r.get("廣告組合預算")),
                "spend": num(r.get("花費金額 (TWD)")),
                "purchases": int(num(r.get("購買次數"))),
                "roas": num(r.get("購買 ROAS（廣告投資報酬率）")),
            }
    return out


def day_count():
    return (date.fromisoformat(END) - date.fromisoformat(START)).days + 1


def output_name(prefix, ext):
    return f"{prefix}_{SUFFIX}.{ext}"


def budget_recommendations(adsets, ordered):
    plan = {}
    for adset in ordered:
        m = adsets[adset]
        eff = effect_adset(m)
        current = m["budget"]
        if eff == "不錯":
            adjusted = current * 1.2
        elif eff == "較差":
            adjusted = current * 0.8
        else:
            adjusted = current
        plan[adset] = round(adjusted)
    return plan


def rows_by_adset(rows, dim_col):
    grouped = defaultdict(list)
    for r in rows:
        if r.get("廣告組合投遞") != "active":
            continue
        if num(r.get("花費金額 (TWD)")) <= 0:
            continue
        name = r["廣告組合名稱"]
        grouped[name].append({
            "item": r[dim_col],
            "results": int(num(r.get("成果"))),
            "cpa": num(r.get("每次成果成本")),
            "spend": num(r.get("花費金額 (TWD)")),
            "purchases": int(num(r.get("購買次數"))),
            "roas": num(r.get("購買 ROAS（廣告投資報酬率）")),
        })
    return grouped


def revenue(row):
    return row["spend"] * row["roas"] if row["roas"] else row["purchases"] * PRICE


def effect_adset(m):
    if m["purchases"] and m["roas"] >= 2.9:
        return "不錯"
    if m["purchases"] and m["roas"] >= 1.8:
        return "普通"
    if not m["purchases"] and m["cpa"] >= 280:
        return "較差"
    return "普通"


def effect_segment(seg, baseline):
    if seg["purchases"] and (seg["roas"] >= max(3.0, baseline["roas"] * 1.15 if baseline["roas"] else 3.0)):
        return "不錯"
    if seg["results"] >= 2 and seg["cpa"] and baseline["cpa"] and seg["cpa"] <= baseline["cpa"] * 0.75:
        return "不錯"
    if seg["spend"] >= max(250, baseline["spend"] * 0.12) and not seg["results"] and not seg["purchases"]:
        return "較差"
    if seg["cpa"] and baseline["cpa"] and seg["cpa"] >= baseline["cpa"] * 1.45 and seg["spend"] >= 250:
        return "較差"
    return "普通"


def age_reco(segs, baseline):
    ages = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    good = []
    for s in segs:
        if s["item"] not in ages:
            continue
        if s["purchases"] or (s["results"] >= 3 and s["cpa"] and baseline["cpa"] and s["cpa"] <= baseline["cpa"] * 0.85):
            good.append(s["item"])
    if not good:
        return "持平", "持平不動", ""
    idxs = sorted(ages.index(a) for a in good)
    lo, hi = min(idxs), max(idxs)
    if ages[hi] == "65+":
        label = f"{ages[lo].split('-')[0]} 歲以上"
    else:
        label = f"{ages[lo].split('-')[0]} 到 {ages[hi].split('-')[-1]} 歲"
    if ages[lo] == ages[hi] == "65+":
        label = "65 歲以上"
    if ages[lo] == "55-64" and ages[hi] == "55-64":
        label = "55 到 64 歲"
    if ages[lo] == "45-54" and ages[hi] == "65+":
        label = "45 歲以上"
    return f"將年齡改測為 {label}", label, ""


def gender_reco(segs, baseline):
    ranked = {s["item"]: s for s in segs}
    f = ranked.get("female")
    m = ranked.get("male")
    if not f or not m:
        return "持平", "持平"
    # Require clear evidence before excluding a targetable gender.
    if f["purchases"] and not m["purchases"] and f["cpa"] and m["cpa"] and f["cpa"] <= m["cpa"] * 0.7:
        return "保留 female 為主測方向，其餘性別先維持小量觀察", "female 為主測方向"
    if m["purchases"] and not f["purchases"] and m["cpa"] and f["cpa"] and m["cpa"] <= f["cpa"] * 0.7:
        return "保留 male 為主測方向，其餘性別先維持小量觀察", "male 為主測方向"
    return "持平", "持平"


def platform_reco(segs):
    fb = next((s for s in segs if s["item"] == "Facebook"), None)
    an = next((s for s in segs if s["item"] == "Audience Network"), None)
    if fb and an and an["spend"] < 100:
        return "持平不動：Facebook 是主力，Audience Network 花費很低，維持現有版位設定。", "持平不動"
    return "持平不動", "持平不動"


def build():
    adsets = active_adsets(read_csv(f"meta_ads_adsets_{SUFFIX}.csv"))
    age = rows_by_adset(read_csv(f"meta_ads_age_{SUFFIX}.csv"), "年齡")
    platform = rows_by_adset(read_csv(f"meta_ads_platform_{SUFFIX}.csv"), "平台")
    gender = rows_by_adset(read_csv(f"meta_ads_gender_{SUFFIX}.csv"), "性別")

    ordered = [a for a in ADSET_ORDER if a in adsets]
    total_spend = sum(adsets[a]["spend"] for a in ordered)
    total_results = sum(adsets[a]["results"] for a in ordered)
    total_purchases = sum(adsets[a]["purchases"] for a in ordered)
    total_revenue = sum(revenue(adsets[a]) for a in ordered)
    current_budget = sum(adsets[a]["budget"] for a in ordered)

    budget_plan = budget_recommendations(adsets, ordered)
    adjusted_budget = sum(budget_plan[a] for a in ordered)

    inputs = {"rule_policy": f"Budget cap +/-20%; report period {START} to {END}.", "dimension_rules": {}, "adset_budget_rules": {}}
    recs = {"dimension_advice": {}, "adset_budget_advice": {}}

    def add_dim(adset, dim, fixed, text, segs, suggested):
        key = f"{adset}::{dim}"
        inputs["dimension_rules"][key] = {
            "campaign": CAMPAIGN, "adset": adset, "dimension": dim,
            "baseline": adsets[adset], "segments": segs,
            "fixed_rule_conclusion": fixed, "estimated_lift": "", "operating_limits": "遵守 Meta 可操作設定；年齡必須連續。"
        }
        recs["dimension_advice"][key] = text

    for adset in ordered:
        m = adsets[adset]
        cur = adsets[adset]["budget"]
        adj = budget_plan[adset]
        eff = effect_adset(m)
        if adj > cur:
            concl = "加預算上限 +20%"
            text = f"將「{adset}」廣告組合預算由 {fmt_budget(cur)} 調到 {fmt_budget(adj)}（+20%），本期有購買或 CPA/ROAS 仍可承接測試量。"
        elif adj < cur:
            concl = "減預算上限 -20%"
            text = f"將「{adset}」廣告組合預算由 {fmt_budget(cur)} 降到 {fmt_budget(adj)}（-20%），把預算轉給本期 ROAS 或 CPA 較佳的組合。"
        else:
            concl = "持平"
            if m["purchases"]:
                text = f"「{adset}」廣告組合預算維持 {fmt_budget(cur)}，本期有購買但 ROAS 或 CPA 未達明顯加碼門檻，先保留量體觀察。"
            else:
                text = f"「{adset}」廣告組合預算維持 {fmt_budget(cur)}，本期 CPA 尚可但未產生購買，先維持量體觀察。"
        inputs["adset_budget_rules"][f"{CAMPAIGN}::{adset}"] = {
            "campaign": CAMPAIGN, "adset": adset, "effect": eff, "fixed_rule_conclusion": concl,
            "budget_limit": "+/-20%", "metrics": m | {"adjusted_budget": adj}
        }
        recs["adset_budget_advice"][f"{CAMPAIGN}::{adset}"] = text

        age_fixed, age_setting, _ = age_reco(age[adset], m)
        age_text = f"{age_fixed}，優先保留有購買或 CPA 較低的連續年齡段。" if age_fixed != "持平" else "年齡先持平不動，等下一期累積更多購買後再收斂。"
        add_dim(adset, "年齡", age_fixed, age_text, age[adset], age_setting)

        plat_text, plat_fixed = platform_reco(platform[adset])
        add_dim(adset, "平臺", plat_fixed, plat_text, platform[adset], plat_fixed)

        gen_fixed, gen_setting = gender_reco(gender[adset], m)
        gen_text = gen_fixed if gen_fixed != "持平" else "性別先持平不動，男女皆仍有成果或資料量不足，保留全部性別。"
        add_dim(adset, "性別", gen_fixed, gen_text, gender[adset], gen_setting)

    rows = []
    rows.append([])
    rows.append(["", "廣告成效分析總表"])
    rows.append(["", "資料區間", "廣告帳號", "成果", "每次成果成本", "總花費", "推估營收", "購買數", "購買 ROAS", "總淨利", "總廣告淨利", "整體預估成長", "目前日預算合計", "平均每日花費"])
    days = day_count()
    rows.append(["", PERIOD, ACCOUNT, str(total_results), fmt_twd(total_spend / total_results) if total_results else "", fmt_twd(total_spend), fmt_twd(total_revenue), str(total_purchases), fmt_roas(total_revenue / total_spend) if total_spend else "", fmt_twd(total_revenue - total_spend), fmt_twd(total_revenue - total_spend), f"建議日預算 {fmt_budget(adjusted_budget)}（{(adjusted_budget/current_budget-1)*100:+.1f}%）；所有組合變動皆在 +/-20% 內", fmt_budget(current_budget), fmt_twd(total_spend / days)])
    rows.append([])
    rows.append(["", "廣告組合預算比較表"])
    rows.append(["", "Breakdown", "行銷活動", "廣告組合", "目前預算", "調整後預算", "成果", "每次成果成本", "花費", "推估營收", "購買數", "購買 ROAS", "成效", "廣告預算建議"])
    for a in ordered:
        m = adsets[a]
        rows.append(["", "廣告組合", CAMPAIGN, a, fmt_budget(m["budget"]), fmt_budget(budget_plan[a]), str(m["results"]), fmt_cpa(m["cpa"]), fmt_twd(m["spend"]), fmt_twd(revenue(m)) if revenue(m) else "", str(m["purchases"]) if m["purchases"] else "", fmt_roas(m["roas"]), inputs["adset_budget_rules"][f"{CAMPAIGN}::{a}"]["effect"], recs["adset_budget_advice"][f"{CAMPAIGN}::{a}"]])
    delta = adjusted_budget - current_budget
    rows.append(["", "總預算變化", "", "", "目前總預算", fmt_budget(current_budget), "調整後總預算", fmt_budget(adjusted_budget), "變動", f"TWD {delta:,.0f} / 日", f"{(adjusted_budget/current_budget-1)*100:+.1f}%", "限制", "所有組合 +/-20% 內", "策略：加不錯與可承接普通，較差降預算"])
    rows.append([])
    rows.append(["", "Breakdown 細分分析表"])
    rows.append(["", "行銷活動", "廣告組合", "Breakdown", "項目", "目前預算", "成果", "每次成果成本", "花費", "推估營收", "購買數", "購買 ROAS"])

    def add_segment_table(adset, title, dim_name, current, suggested, segs, advice):
        rows.append(["", "", "", title])
        rows.append(["", "", "", "設定對照", "原本設定", current, "建議設定", suggested, "", "成效資料", "見下方實際成果、CPA、花費、ROAS"])
        rows.append(["", "", "", "Breakdown", dim_name, "成果", "每次成果成本", "花費", "推估營收", "購買數", "購買 ROAS", "成效"])
        for i, s in enumerate(segs):
            rows.append(["", "", "", dim_name if i == 0 else "", s["item"], str(s["results"]) if s["results"] else "", fmt_cpa(s["cpa"]), fmt_twd(s["spend"]) if s["spend"] else "", fmt_twd(revenue(s)) if revenue(s) else "", str(s["purchases"]) if s["purchases"] else "", fmt_roas(s["roas"]), effect_segment(s, adsets[adset])])
        rows.append(["", "", "", "總結建議", advice])

    for a in ordered:
        m = adsets[a]
        rows.append(["", CAMPAIGN, a, "廣告組合總覽", "整體", fmt_budget(m["budget"]), str(m["results"]), fmt_twd(m["cpa"]), fmt_twd(m["spend"]), fmt_twd(revenue(m)) if revenue(m) else "", str(m["purchases"]) if m["purchases"] else "", fmt_roas(m["roas"])])
        add_segment_table(a, "年齡維度小表", "年齡", CURRENT_SETTINGS[a]["age"], inputs["dimension_rules"][f"{a}::年齡"]["fixed_rule_conclusion"].replace("將年齡改測為 ", ""), age[a], recs["dimension_advice"][f"{a}::年齡"])
        add_segment_table(a, "平臺維度小表", "平臺", CURRENT_SETTINGS[a]["platform"], inputs["dimension_rules"][f"{a}::平臺"]["fixed_rule_conclusion"], platform[a], recs["dimension_advice"][f"{a}::平臺"])
        add_segment_table(a, "性別維度小表", "性別", CURRENT_SETTINGS[a]["gender"], inputs["dimension_rules"][f"{a}::性別"]["fixed_rule_conclusion"], gender[a], recs["dimension_advice"][f"{a}::性別"])

    WORK.joinpath("recommendation_inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")
    WORK.joinpath("ai_recommendations.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    WORK.joinpath(output_name("sheet_rows", "json")).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_clipboard_files(rows)
    write_merged_html(adsets, age, platform, gender, ordered, inputs, recs, budget_plan)
    summary = {
        "tab": TAB, "rows": len(rows), "cols": max(len(r) for r in rows),
        "total_spend": total_spend, "total_revenue": total_revenue, "current_budget": current_budget,
        "adjusted_budget": adjusted_budget, "results": total_results, "purchases": total_purchases,
    }
    WORK.joinpath(output_name("report_summary", "json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def write_clipboard_files(rows):
    padded = []
    for row in rows:
        cells = [safe_text(x) for x in row]
        cells += [""] * (15 - len(cells))
        padded.append(cells[:15])

    tsv_lines = ["\t".join(tsv_value(c) for c in row[:15]) for row in padded]
    WORK.joinpath(output_name("sheet_rows", "tsv")).write_text("\n".join(tsv_lines), encoding="utf-8")

    widths = [24, 100, 112, 210, 112, 112, 92, 120, 110, 120, 95, 120, 110, 430, 24]
    title_rows = {1, 5, 16}
    header_rows = {2, 6, 17}
    total_rows = {14}
    table_ranges = [(1, 3, 1, 13), (5, 14, 1, 13), (16, len(padded) - 1, 1, 11)]

    def in_outer(r, c):
        borders = []
        for top, bottom, left, right in table_ranges:
            if top <= r <= bottom and left <= c <= right:
                if r == top:
                    borders.append("border-top:2px solid #000")
                if r == bottom:
                    borders.append("border-bottom:2px solid #000")
                if c == left:
                    borders.append("border-left:2px solid #000")
                if c == right:
                    borders.append("border-right:2px solid #000")
        return ";".join(borders)

    def cell_style(r, c, text):
        style = [
            f"width:{widths[c]}px",
            "font-family:Arial,'Noto Sans TC',sans-serif",
            "font-size:10pt",
            "padding:4px 6px",
            "vertical-align:middle",
            "white-space:normal",
            "word-break:break-word",
            "color:#1f2933",
            "background:#ffffff",
            "mso-number-format:'\\@'",
        ]
        border = in_outer(r, c)
        if border:
            style.append(border)
        if c in (0, 14):
            style.extend(["background:#ffffff", "padding:0"])
        if r in title_rows and 1 <= c <= 13:
            style.extend(["background:#8fb4d9", "font-weight:bold", "text-align:center", "font-size:11pt"])
        if r in header_rows and 1 <= c <= 13:
            style.extend(["background:#dbeaf7", "font-weight:bold", "text-align:center"])
        if r == 16 and 1 <= c <= 11:
            style.extend(["background:#6f9fc9", "font-weight:bold", "text-align:center"])
        if r >= 17 and c in (1, 2) and text:
            style.append("background:#d8e3ec")
        if "維度小表" in text:
            style.extend(["background:#b9d4ec", "font-weight:bold"])
        if text == "設定對照":
            style.extend(["background:#eef5fb", "font-weight:bold", "text-align:center"])
        if text == "總結建議":
            style.extend(["background:#fff4bf", "font-weight:bold", "text-align:center"])
        if r > 16 and padded[r][3] == "總結建議" and c == 4:
            style.extend(["background:#fff4bf", "font-weight:bold"])
        if text == "不錯":
            style.extend(["background:#d9ead3", "font-weight:bold", "text-align:center"])
        elif text == "較差":
            style.extend(["background:#f4cccc", "font-weight:bold", "text-align:center"])
        elif text == "普通":
            style.extend(["background:#ffffff", "text-align:center"])
        if r in total_rows and 1 <= c <= 13:
            style.extend(["background:#eef5fb", "font-weight:bold"])
        if c in (6, 7, 8, 9, 10, 11, 12):
            style.append("text-align:right")
        return ";".join(style)

    html_rows = []
    for r, row in enumerate(padded):
        html_cells = []
        for c, text in enumerate(row):
            display = html.escape(text)
            html_cells.append(f'<td style="{cell_style(r, c, text)}">{display}</td>')
        html_rows.append("<tr>" + "".join(html_cells) + "</tr>")
    doc = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;table-layout:fixed">
""" + "\n".join(html_rows) + "\n</table></body></html>"
    WORK.joinpath(output_name("sheet_rows", "html")).write_text(doc, encoding="utf-8")


def td(text="", colspan=1, rowspan=1, cls="", style=""):
    attrs = []
    if colspan > 1:
        attrs.append(f'colspan="{colspan}"')
    if rowspan > 1:
        attrs.append(f'rowspan="{rowspan}"')
    if cls:
        attrs.append(f'class="{cls}"')
    if style:
        attrs.append(f'style="{style}"')
    return f"<td {' '.join(attrs)}>{html.escape(safe_text(text))}</td>"


def write_merged_html(adsets, age, platform, gender, ordered, inputs, recs, budget_plan):
    total_spend = sum(adsets[a]["spend"] for a in ordered)
    total_results = sum(adsets[a]["results"] for a in ordered)
    total_purchases = sum(adsets[a]["purchases"] for a in ordered)
    total_revenue = sum(revenue(adsets[a]) for a in ordered)
    current_budget = sum(adsets[a]["budget"] for a in ordered)
    adjusted_budget = sum(budget_plan[a] for a in ordered)

    css = """
<style>
table{border-collapse:collapse;table-layout:fixed;font-family:Arial,'Noto Sans TC',sans-serif;font-size:10pt;color:#1f2933}
col.pad{width:24px}.c1{width:110px}.c2{width:210px}.c3{width:120px}.c4{width:112px}.c5{width:112px}.c6{width:92px}.c7{width:120px}.c8{width:110px}.c9{width:120px}.c10{width:95px}.c11{width:120px}.c12{width:110px}.c13{width:430px}
td{padding:4px 6px;vertical-align:middle;white-space:normal;word-break:break-word;mso-number-format:'\\@';background:#fff}
.padcell{background:#fff;padding:0}
.title{background:#8fb4d9;font-weight:bold;text-align:center;font-size:11pt}
.breaktitle{background:#6f9fc9;font-weight:bold;text-align:center;font-size:11pt}
.head{background:#dbeaf7;font-weight:bold;text-align:center}
.hierhead{background:#d8e3ec;font-weight:bold;text-align:center}
.camp{background:#d8e3ec;text-align:center;font-weight:bold;vertical-align:middle}
.adsetA{background:#e6eef6;vertical-align:middle}.adsetB{background:#f1f6fa;vertical-align:middle}
.dimtitle{background:#b9d4ec;font-weight:bold}.setting{background:#eef5fb;font-weight:bold;text-align:center}.summary{background:#fff4bf;font-weight:bold}
.good{background:#d9ead3;font-weight:bold;text-align:center}.bad{background:#f4cccc;font-weight:bold;text-align:center}.normal{background:#fff;text-align:center}
.num{text-align:right}.center{text-align:center}
.top{border-top:2px solid #000}.bottom{border-bottom:2px solid #000}.left{border-left:2px solid #000}.right{border-right:2px solid #000}
.treebottom td{border-bottom:2px solid #000}
</style>
"""
    colgroup = "<colgroup>" + "<col class='pad'>" + "".join(f"<col class='c{i}'>" for i in range(1, 14)) + "<col class='pad'>" + "</colgroup>"
    trs = []
    trs.append("<tr>" + td("", cls="padcell") * 15 + "</tr>")
    trs.append("<tr>" + td("", cls="padcell") + td("廣告成效分析總表", colspan=13, cls="title top left right") + td("", cls="padcell") + "</tr>")
    headers = ["資料區間","廣告帳號","成果","每次成果成本","總花費","推估營收","購買數","購買 ROAS","總淨利","總廣告淨利","整體預估成長","目前日預算合計","平均每日花費"]
    trs.append("<tr>" + td("", cls="padcell") + "".join(td(h, cls=("head left" if i == 0 else "head right" if i == len(headers)-1 else "head")) for i,h in enumerate(headers)) + td("", cls="padcell") + "</tr>")
    days = day_count()
    summary = [PERIOD, ACCOUNT, str(total_results), fmt_twd(total_spend / total_results) if total_results else "", fmt_twd(total_spend), fmt_twd(total_revenue), str(total_purchases), fmt_roas(total_revenue / total_spend) if total_spend else "", fmt_twd(total_revenue-total_spend), fmt_twd(total_revenue-total_spend), f"建議日預算 {fmt_budget(adjusted_budget)}（{(adjusted_budget/current_budget-1)*100:+.1f}%）；所有組合變動皆在 +/-20% 內", fmt_budget(current_budget), fmt_twd(total_spend/days)]
    trs.append("<tr>" + td("", cls="padcell") + "".join(td(v, cls=("bottom left" if i == 0 else "bottom right" if i == len(summary)-1 else "bottom") + (" num" if i >= 5 else "")) for i,v in enumerate(summary)) + td("", cls="padcell") + "</tr>")
    trs.append("<tr>" + td("", cls="padcell") * 15 + "</tr>")

    trs.append("<tr>" + td("", cls="padcell") + td("廣告組合預算比較表", colspan=13, cls="title top left right") + td("", cls="padcell") + "</tr>")
    bheads = ["Breakdown","行銷活動","廣告組合","目前預算","調整後預算","成果","每次成果成本","花費","推估營收","購買數","購買 ROAS","成效","廣告預算建議"]
    trs.append("<tr>" + td("", cls="padcell") + "".join(td(h, cls=("head left" if i == 0 else "head right" if i == len(bheads)-1 else "head")) for i,h in enumerate(bheads)) + td("", cls="padcell") + "</tr>")
    for a in ordered:
        m = adsets[a]
        eff = inputs["adset_budget_rules"][f"{CAMPAIGN}::{a}"]["effect"]
        effcls = "good" if eff == "不錯" else "bad" if eff == "較差" else "normal"
        vals = ["廣告組合", CAMPAIGN, a, fmt_budget(m["budget"]), fmt_budget(budget_plan[a]), str(m["results"]), fmt_cpa(m["cpa"]), fmt_twd(m["spend"]), fmt_twd(revenue(m)) if revenue(m) else "", str(m["purchases"]) if m["purchases"] else "", fmt_roas(m["roas"]), eff, recs["adset_budget_advice"][f"{CAMPAIGN}::{a}"]]
        cells = []
        for i,v in enumerate(vals):
            cls = "left" if i == 0 else "right" if i == len(vals)-1 else ""
            if i in (5,6,7,8,9,10):
                cls += " num"
            if i == 11:
                cls += " " + effcls
            cells.append(td(v, cls=cls.strip()))
        trs.append("<tr>" + td("", cls="padcell") + "".join(cells) + td("", cls="padcell") + "</tr>")
    delta = adjusted_budget - current_budget
    total = ["總預算變化","","","目前總預算",fmt_budget(current_budget),"調整後總預算",fmt_budget(adjusted_budget),"變動",f"{delta:+,.0f} TWD / 日",f"{(adjusted_budget/current_budget-1)*100:+.1f}%","限制","所有組合 +/-20% 內","策略：加不錯與可承接普通，較差降預算"]
    trs.append("<tr>" + td("", cls="padcell") + "".join(td(v, cls=("summary bottom left" if i == 0 else "summary bottom right" if i == len(total)-1 else "summary bottom")) for i,v in enumerate(total)) + td("", cls="padcell") + "</tr>")
    trs.append("<tr>" + td("", cls="padcell") * 15 + "</tr>")

    trs.append("<tr>" + td("", cls="padcell") + td("Breakdown 細分分析表", colspan=11, cls="breaktitle top left right") + td("", colspan=2) + td("", cls="padcell") + "</tr>")
    tree_heads = ["行銷活動","廣告組合","Breakdown","項目","目前預算","成果","每次成果成本","花費","推估營收","購買數","購買 ROAS"]
    trs.append("<tr>" + td("", cls="padcell") + "".join(td(h, cls=("hierhead left" if i == 0 else "head right" if i == len(tree_heads)-1 else "hierhead" if i < 2 else "head")) for i,h in enumerate(tree_heads)) + td("", colspan=2) + td("", cls="padcell") + "</tr>")

    def dim_rows(adset, title, dim_name, current, suggested, segs, advice, table_index):
        rows_html = []
        rows_html.append("<tr>" + td(title, colspan=9, cls="dimtitle") + "</tr>")
        rows_html.append("<tr>" + td("設定對照", cls="setting") + td("原本設定") + td(current) + td("建議設定") + td(suggested, colspan=2) + td("成效資料") + td("見下方實際成果、CPA、花費、ROAS", colspan=2, cls="right") + "</tr>")
        rows_html.append("<tr>" + td("Breakdown") + td(dim_name) + td("成果") + td("每次成果成本") + td("花費") + td("推估營收") + td("購買數") + td("購買 ROAS") + td("成效", cls="right") + "</tr>")
        for i,s in enumerate(segs):
            eff = effect_segment(s, adsets[adset])
            effcls = "good" if eff == "不錯" else "bad" if eff == "較差" else "normal"
            cells = []
            if i == 0:
                cells.append(td(dim_name, rowspan=len(segs), cls="center"))
            cells.extend([
                td(s["item"]),
                td(str(s["results"]) if s["results"] else "", cls="num"),
                td(fmt_cpa(s["cpa"]), cls="num"),
                td(fmt_twd(s["spend"]) if s["spend"] else "", cls="num"),
                td(fmt_twd(revenue(s)) if revenue(s) else "", cls="num"),
                td(str(s["purchases"]) if s["purchases"] else "", cls="num"),
                td(fmt_roas(s["roas"]), cls="num"),
                td(eff, cls=f"{effcls} right"),
            ])
            rows_html.append("<tr>" + "".join(cells) + "</tr>")
        rows_html.append("<tr>" + td("總結建議", cls="summary center") + td(advice, colspan=8, cls="summary right") + "</tr>")
        return rows_html

    blocks = []
    for ai, a in enumerate(ordered):
        block = []
        m = adsets[a]
        block.append({
            "kind": "overview",
            "cells": [
                td("廣告組合總覽"),
                td("整體"),
                td(fmt_budget(m["budget"])),
                td(str(m["results"]), cls="num"),
                td(fmt_twd(m["cpa"]), cls="num"),
                td(fmt_twd(m["spend"]), cls="num"),
                td(fmt_twd(revenue(m)) if revenue(m) else "", cls="num"),
                td(str(m["purchases"]) if m["purchases"] else "", cls="num"),
                td(fmt_roas(m["roas"]), cls="num right"),
            ]
        })
        for title, dim, cur, sug, segs, advice in [
            ("年齡維度小表", "年齡", CURRENT_SETTINGS[a]["age"], inputs["dimension_rules"][f"{a}::年齡"]["fixed_rule_conclusion"].replace("將年齡改測為 ", ""), age[a], recs["dimension_advice"][f"{a}::年齡"]),
            ("平臺維度小表", "平臺", CURRENT_SETTINGS[a]["platform"], inputs["dimension_rules"][f"{a}::平臺"]["fixed_rule_conclusion"], platform[a], recs["dimension_advice"][f"{a}::平臺"]),
            ("性別維度小表", "性別", CURRENT_SETTINGS[a]["gender"], inputs["dimension_rules"][f"{a}::性別"]["fixed_rule_conclusion"], gender[a], recs["dimension_advice"][f"{a}::性別"]),
        ]:
            block.extend({"kind":"raw","html":r} for r in dim_rows(a, title, dim, cur, sug, segs, advice, ai))
        blocks.append((a, block))

    campaign_span = sum(len(block) for _, block in blocks)
    first_campaign = True
    for ai, (a, block) in enumerate(blocks):
        adset_span = len(block)
        adset_cls = "adsetA" if ai % 2 == 0 else "adsetB"
        for ri, row in enumerate(block):
            prefix = td("", cls="padcell")
            if first_campaign:
                prefix += td(CAMPAIGN, rowspan=campaign_span, cls="camp left bottom")
                first_campaign = False
            if ri == 0:
                prefix += td(a, rowspan=adset_span, cls=(adset_cls + (" bottom" if ai == len(blocks) - 1 else "")))
            if row["kind"] == "overview":
                body = "".join(row["cells"])
            else:
                # Raw rows already cover D:K, so add nothing before them.
                body = row["html"][4:-5]
            suffix = td("", colspan=2) + td("", cls="padcell")
            row_cls = " class='treebottom'" if ai == len(blocks) - 1 and ri == len(block) - 1 else ""
            trs.append(f"<tr{row_cls}>" + prefix + body + suffix + "</tr>")

    html_doc = "<!doctype html><html><head><meta charset='utf-8'>" + css + "</head><body><table>" + colgroup + "\n" + "\n".join(trs) + "</table></body></html>"
    WORK.joinpath(output_name("sheet_rows_merged", "html")).write_text(html_doc, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--tab", default=TAB)
    parser.add_argument("--work-dir", default=str(WORK))
    args = parser.parse_args()
    START = args.start
    END = args.end
    PERIOD = f"{START} 至 {END}"
    TAB = args.tab
    SUFFIX = f"{START}_{END}"
    WORK = Path(args.work_dir).expanduser().resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    build()
