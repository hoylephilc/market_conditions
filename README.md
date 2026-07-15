# Market Conditions Pipeline

Rebuilds the monthly "market conditions" dataset (rates, spreads, inflation, prepayments)
that used to be a manual spreadsheet grab. Now automated, free, and indefinite.

## Stack
- **Ingest:** Python + `fredapi` — pulls series from FRED
- **Storage:** Google BigQuery (free tier, billing account attached to avoid 60-day sandbox expiry)
- **Orchestration:** GitHub Actions (scheduled monthly, free on public repos)
- **Viz:** Looker Studio, pointed at BigQuery

No transform layer yet on purpose. Get the raw data shaped the way you want
first (which series, what granularity, what's computed vs. pulled) before
adding dbt back in. The raw table (`market_conditions_raw.fred_series`) is
long-format -- one row per date/series -- so you can already query and pivot
it directly in BigQuery's console or Looker Studio while you decide what the
"clean" version should look like.

## Setup (one-time)
1. Get a free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
2. Create a GCP project, enable BigQuery, attach a billing account (stays free
   under 10GB storage / 1TB query per month — this just removes the 60-day
   sandbox table expiry).
3. Create a service account with BigQuery Data Editor + Job User roles,
   download the JSON key.
4. In your GitHub repo settings → Secrets and variables → Actions, add:
   - `FRED_API_KEY`
   - `GCP_SA_KEY` (paste the full JSON key contents)
   - `GCP_PROJECT_ID`
5. `pip install -r requirements.txt` locally to test `ingest/pull_fred.py` before
   trusting the scheduled job.

## Repo layout
```
ingest/pull_fred.py        # pulls FRED series, loads raw table to BigQuery
.github/workflows/         # monthly scheduled pull
```

## Series tracked (edit ingest/pull_fred.py to add/remove)
| FRED ID      | What it is                          |
|--------------|--------------------------------------|
| CPIAUCSL     | CPI, all urban consumers (inflation) |
| MORTGAGE30US | 30-year fixed mortgage rate           |
| DGS10        | 10-year Treasury yield                |
| DGS2         | 2-year Treasury yield                 |
| DGS5         | 5-year Treasury yield                 |
| T10Y2Y       | 10yr-2yr Treasury spread (precomputed)|

Spreads not precomputed by FRED (e.g. mortgage-to-10yr) aren't calculated yet --
that's deliberately left out until the raw shape is settled. Add the math in
Python in `ingest/pull_fred.py`, or in a transform layer later, once you know
what you actually want to track.
