# Meta Ads API Dashboard

這個 repo 現在同時包含：

- `Meta API -> CSV/JSON` 的報表重建 pipeline
- 一個會直接呼叫 `/api/meta_report` 的前端 dashboard
- 一條可部署到 Vercel Python Functions 的 serverless API route

## 內容

- API-driven 首頁：`index.html`
- 舊版靜態首頁備份：`campaign-library.html`
- Vercel API route：`api/meta_report.py`
- Meta API 匯出：`scripts/fetch_meta_insights.py`
- 報表規則重建：`scripts/build_meta_report.py`
- 全流程重建：`scripts/run_meta_api_report.py`
- Dashboard payload 組裝：`scripts/report_payload.py`

## 本地重建資料

在專案根目錄執行：

```bash
python3 scripts/run_meta_api_report.py --start 2026-06-19 --end 2026-06-25
```

這條流程會：

- 從 Marketing API 抓精準的 inclusive 日期區間資料
- 輸出 `meta_ads_adsets / age / platform / gender` CSV
- 重建 `recommendation_inputs.json`、`ai_recommendations.json`
- 重建 `report_summary_*.json`

也可以把產物寫到別的資料夾，給 serverless 或臨時測試用：

```bash
python3 scripts/run_meta_api_report.py \
  --start 2026-06-19 \
  --end 2026-06-25 \
  --skip-site \
  --work-dir /tmp/meta-report-work
```

## Meta API 設定

1. 以 [`.env.meta.example`](/Users/dada878/Documents/too-many-landing-pages/.env.meta.example) 為範本建立 `.env.meta`，填入：
   - `META_ACCESS_TOKEN`
   - `META_APP_SECRET`
   - `META_AD_ACCOUNT_ID`
2. 你也可以不用 `.env.meta`，直接用環境變數；script 會優先讀 process env。

單獨抓指定期間 CSV：

```bash
python3 scripts/fetch_meta_insights.py --start 2026-06-19 --end 2026-06-25
```

腳本會優先使用 `certifi` CA bundle，避免 macOS 上常見的 Python 憑證驗證失敗。

## Vercel API

部署後可直接呼叫：

```text
/api/meta_report?start=2026-06-19&end=2026-06-25&refresh=1
```

回傳內容包含：

- period
- summary
- highlights
- adsets

首頁 `index.html` 會直接 fetch 這條 API，而不是讀 baked static report。
