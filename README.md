# Market Conditions Pipeline

Rebuilds the monthly **market conditions** dataset (rates, spreads, inflation, housing, and CRE) that used to be a manual spreadsheet grab — now automated, free, and indefinite, with an **AI-generated commentary layer** on top.

**[View the Live Market Conditions Report](https://datastudio.google.com/s/poCo72LdlOA)**

## Stack

- **Ingest:** Python + `fredapi` — pulls 15 economic and market series from FRED
- **Storage:** Google BigQuery — persistent cloud storage and SQL analytics
- **AI Commentary:** Gemini (`google-genai`) — summarizes the latest data pull into a 2-sentence dashboard header and writes the result to a separate BigQuery table
- **Orchestration:** GitHub Actions — scheduled monthly execution with keyless authentication via Workload Identity Federation
- **Visualization:** Looker Studio — connected directly to BigQuery for interactive reporting

## Architecture

```text
FRED API
   │
   ▼
Python + fredapi
   │
   ▼
BigQuery ────────────────► Looker Studio
   │                           │
   │                           └── KPI scorecards
   │                           └── Market trend charts
   │                           └── AI-generated commentary
   │
   ▼
Gemini
   │
   ▼
Market Commentary
   │
   └──────────────► BigQuery
```

GitHub Actions orchestrates the monthly pipeline using **Workload Identity Federation**, allowing the workflow to authenticate to Google Cloud with short-lived credentials rather than storing a service-account JSON key.

## Repo Layout

```text
ingest/pull_fred.py        # pulls FRED series, loads raw table to BigQuery,
                           # generates AI commentary via Gemini, and appends
                           # commentary to a separate BigQuery table

.github/workflows/         # monthly scheduled pipeline
```

## Series Tracked

Edit `ingest/pull_fred.py` to add or remove series.

| FRED ID | Label | Notes |
|---|---|---|
| `CPIAUCSL` | CPI Inflation | YoY % (`units=pc1`) |
| `MORTGAGE30US` | 30 Yr Mortgage | |
| `DGS30` | 30 Yr Treasury | |
| `DGS20` | 20 Yr Treasury | |
| `DGS10` | 10 Yr Treasury | |
| `DGS5` | 5 Yr Treasury | |
| `DGS2` | 2 Yr Treasury | |
| `DGS1` | 1 Yr Treasury | |
| `DGS3MO` | 3 Mo Treasury | |
| `DGS1MO` | 1 Mo Treasury | |
| `T10Y2Y` | 10yr–2yr Spread | Precomputed by FRED |
| `TGCRRATE` | Tri-Party Repo | NY Fed overnight Treasury repo benchmark |
| `SOFR` | SOFR | |
| `CSUSHPINSA` | House Price Index | YoY % (`units=pc1`) |
| `COMREPUSQ159N` | CRE Price Index | Quarterly, IMF-sourced |

The pipeline intentionally focuses on data available through **free, public FRED sources**. Agency OAS, refinance exposure, CRE NOI, and MBS/CMBS/Treasury issuance-volume data are not included because comparable datasets generally require SIFMA, MBA, NCREIF, Bloomberg, or other subscription sources.

A separate Treasury issuance proof-of-concept using the Fiscal Data API exists but is not yet integrated into this pipeline.

## AI Commentary

Each monthly run takes the latest observation for each tracked series and sends the market snapshot to **Gemini 2.5 Flash** for a short, dashboard-ready two-sentence summary.

The generated commentary is:

- Stored in a dedicated `market_commentary` BigQuery table
- **Appended rather than overwritten**, preserving historical commentary
- Tagged with a `commentary_type` field to support additional commentary formats later
- Generated as a non-blocking step — if the Gemini API call or commentary write fails, the core FRED-to-BigQuery pipeline still completes successfully

This creates an automated workflow from **data ingestion → cloud storage → AI analysis → narrative generation → dashboard reporting**.

## Dashboard

The Looker Studio report connects directly to BigQuery and includes:

- KPI scorecards for key market levels
- Treasury yield-curve time series
- CPI and inflation trends
- Housing and CRE price trends
- Short-term interest rates
- Yield spreads
- Funding-market rates
- Latest AI-generated market commentary

**[Open the Live Dashboard →](https://datastudio.google.com/s/poCo72LdlOA)**