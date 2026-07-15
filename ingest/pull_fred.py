"""
Pulls a defined set of FRED series and loads them into a BigQuery raw table.
Designed to run monthly via GitHub Actions, but safe to run more often --
FRED data doesn't change retroactively often, and this does a full
upsert-by-date rather than blind append.

Usage:
    python ingest/pull_fred.py
"""
import os
import sys
from datetime import datetime

import pandas as pd
from fredapi import Fred
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.environ["FRED_API_KEY"]
GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BQ_DATASET = os.environ.get("BQ_DATASET", "market_conditions_raw")
BQ_TABLE = "fred_series"

# Add / remove series here. Key = FRED series ID, value = human label.
SERIES = {
    "CPIAUCSL": "cpi_all_urban",
    "MORTGAGE30US": "mortgage_30yr_fixed",
    "DGS10": "treasury_10yr",
    "DGS5": "treasury_5yr",
    "DGS2": "treasury_2yr",
    "T10Y2Y": "treasury_10yr_2yr_spread",
}


def pull_series(fred: Fred) -> pd.DataFrame:
    """Pull each configured series and stack into one long-format DataFrame."""
    frames = []
    for series_id, label in SERIES.items():
        try:
            s = fred.get_series(series_id)
        except Exception as e:
            print(f"WARNING: failed to pull {series_id} ({label}): {e}", file=sys.stderr)
            continue

        df = s.reset_index()
        df.columns = ["date", "value"]
        df["series_id"] = series_id
        df["label"] = label
        df["pulled_at"] = datetime.utcnow().isoformat()
        frames.append(df)

    if not frames:
        raise RuntimeError("No series were successfully pulled -- aborting load.")

    return pd.concat(frames, ignore_index=True)


def ensure_dataset(client: bigquery.Client, dataset_id: str) -> None:
    dataset_ref = bigquery.DatasetReference(client.project, dataset_id)
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        print(f"Dataset {dataset_id} not found -- creating it.")
        client.create_dataset(bigquery.Dataset(dataset_ref))


def load_to_bigquery(df: pd.DataFrame) -> None:
    client = bigquery.Client(project=GCP_PROJECT_ID)
    ensure_dataset(client, BQ_DATASET)

    table_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",  # full refresh -- data volume is tiny
        schema=[
            bigquery.SchemaField("date", "DATE"),
            bigquery.SchemaField("value", "FLOAT64"),
            bigquery.SchemaField("series_id", "STRING"),
            bigquery.SchemaField("label", "STRING"),
            bigquery.SchemaField("pulled_at", "TIMESTAMP"),
        ],
    )

    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # wait for completion
    print(f"Loaded {len(df)} rows into {table_id}")


def main():
    fred = Fred(api_key=FRED_API_KEY)
    df = pull_series(fred)
    load_to_bigquery(df)


if __name__ == "__main__":
    main()
