"""
Pulls a defined set of FRED series and loads them into a BigQuery raw table.
Then, utilizes Gemini to generate market commentary based on the latest data points 
and writes the commentary back to BigQuery.

Designed to run monthly via GitHub Actions, but safe to run more often.

Usage:
    python ingest/pull_fred.py
"""
import os
import sys
from datetime import datetime

import pandas as pd
from fredapi import Fred
from google.cloud import bigquery
from google import genai  # Requires google-genai package
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.environ["FRED_API_KEY"]
GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BQ_DATASET = os.environ.get("BQ_DATASET", "market_conditions_raw")
BQ_TABLE = "fred_series"
BQ_COMMENTARY_TABLE = "market_commentary"

# Add / remove series here. Key = FRED series ID, value = config dict.
SERIES = {
    "CPIAUCSL": {"label": "CPI Inflation", "units": "pc1"},
    "MORTGAGE30US": {"label": "30 Yr Mortgage"},
    "DGS30": {"label": "30 Yr Treasury"},
    "DGS20": {"label": "20 Yr Treasury"},
    "DGS10": {"label": "10 Yr Treasury"},
    "DGS5": {"label": "5 Yr Treasury"},
    "DGS2": {"label": "2 Yr Treasury"},
    "DGS1": {"label": "1 Yr Treasury"},
    "DGS3MO": {"label": "3 Mo Treasury"},
    "DGS1MO": {"label": "1 Mo Treasury"},
    "T10Y2Y": {"label": "10yr-2yr Spread"},
    "TGCRRATE": {"label": "Tri-Party Repo"},
    "SOFR": {"label": "SOFR"},
    "CSUSHPINSA": {"label": "House Price Index", "units": "pc1"},
    "COMREPUSQ159N": {"label": "CRE Price Index"},
}


def pull_series(fred: Fred) -> pd.DataFrame:
    """Pull each configured series and stack into one long-format DataFrame."""
    frames = []
    for series_id, config in SERIES.items():
        label = config["label"]
        units = config.get("units", "lin")  # "lin" = raw level, FRED's default
        try:
            s = fred.get_series(series_id, units=units)
        except Exception as e:
            print(f"WARNING: failed to pull {series_id} ({label}): {e}", file=sys.stderr)
            continue

        df = s.reset_index()
        df.columns = ["date", "value"]
        df["series_id"] = series_id
        df["label"] = label
        df["pulled_at"] = pd.Timestamp.utcnow()
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
        # Truncate on load removes duplicate risk, solving the 10 Yr Treasury visual doubling bug
        write_disposition="WRITE_TRUNCATE",  
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


def generate_market_commentary(df: pd.DataFrame) -> None:
    """
    Summarizes the latest values for key economic indicators, generates
    an AI commentary via Gemini, and appends the log to BigQuery.
    """
    print("Generating market commentary...")
    try:
        # 1. Prepare data context (extracting the latest valid data point for key metrics)
        summary_records = []
        for series_id, config in SERIES.items():
            series_df = df[df["series_id"] == series_id].dropna().sort_values(by="date", ascending=False)
            if not series_df.empty:
                latest_row = series_df.iloc[0]
                # Format date to string safely
                date_str = latest_row["date"].strftime("%Y-%m-%d") if isinstance(latest_row["date"], datetime) else str(latest_row["date"])[:10]
                summary_records.append(
                    f"- {config['label']}: {latest_row['value']:.2f}% (as of {date_str})"
                )
        
        data_context = "\n".join(summary_records)
        
        # 2. Build instructions for Gemini
        prompt = (
            "You are a macroeconomic analyst. Analyze the following recently updated FRED indicator values:\n\n"
            f"{data_context}\n\n"
            "Provide a highly professional 2-sentence market commentary detailing the current health "
            "of the economy, mentioning any notable moves in Treasury yields or inflation if relevant. "
            "Write it directly to display as a dashboard summary header."
        )

        # 3. Call Gemini (utilizing modern SDK defaults)
        # Assumes GCP credentials from GitHub actions auth step are in environment
        ai_client = genai.Client(
            enterprise=True,
            project=GCP_PROJECT_ID,
            location="us-central1"
        )
        
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        commentary_text = response.text.strip()
        print(f"\n--- Generated Commentary ---\n{commentary_text}\n----------------------------\n")

        # 4. Save to historical BigQuery Table
        bq_client = bigquery.Client(project=GCP_PROJECT_ID)
        commentary_table_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_COMMENTARY_TABLE}"
        
        # We define a "main" default here. Later, you can pass different values 
        # (e.g., "yield_curve_deepdive", "inflation_breakdown") to this parameter.
        commentary_type = "main" 

        commentary_df = pd.DataFrame([{
            "date": pd.Timestamp.now("UTC").date(),
            "commentary_type": commentary_type,  # <--- New metadata column
            "commentary": commentary_text,
            "generated_at": pd.Timestamp.now("UTC")
        }])

        commentary_job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            schema=[
                bigquery.SchemaField("date", "DATE"),
                bigquery.SchemaField("commentary_type", "STRING"), # <--- Added to BQ schema mapping
                bigquery.SchemaField("commentary", "STRING"),
                bigquery.SchemaField("generated_at", "TIMESTAMP"),
            ]
        )

        print(f"Saving commentary ({commentary_type}) to {commentary_table_id}...")
        job = bq_client.load_table_from_dataframe(commentary_df, commentary_table_id, job_config=commentary_job_config)
        job.result()
        print(f"Successfully appended commentary log to {commentary_table_id}")

    except Exception as ai_err:
        # Non-blocking catch ensures API/connection issues won't crash your primary data ingestion
        print(f"WARNING: Failed to generate/save market commentary: {ai_err}", file=sys.stderr)


def main():
    fred = Fred(api_key=FRED_API_KEY)
    df = pull_series(fred)
    load_to_bigquery(df)
    generate_market_commentary(df)


if __name__ == "__main__":
    main()