# A Data-Driven Framework for Price Trend Analysis, Visualization, Forecasting, and Decision Support

End-to-end system for analysing Pakistan commodity / consumer price movements and turning them
into decisions. The full pipeline is:

```
Data Collection -> Integration -> Cleaning -> EDA -> Factor Identification
      -> Forecasting -> Uncertainty Estimation -> Visualization -> Decision Support
```

and it is built to answer six questions: **WHAT** happened to the price, **WHEN** the significant
change happened, **WHERE** the largest changes occurred, **WHY** it changed, **WHAT** is likely
next, and **WHAT** decision-makers can do about it.

## Status

| Stage | Module | State |
|---|---|---|
| Collection + Integration + light Cleaning | `pricelab.ingestion`, `pricelab.integration` | **done** (this repo) |
| Storage (SQL Server + DuckDB snapshot) | `pricelab.integration.sql_export`, `.duckdb_export` | **done** |
| Visualization (web dashboard) | `dashboard/` (Streamlit) | **done**, basic pages |
| EDA, Events, Spatial, Factors, Forecasting, Uncertainty, Decision | — | planned (see `.claude/plans/`) |

Current output: a single tidy-long fact table (`data/processed/master_long.{parquet,csv,xlsx}`),
cleaned reference tables in `data/interim/`, `data/processed/ingestion_report.md`, a mirror in
your local SQL Server, and a DuckDB snapshot (`data/processed/pricelab.duckdb`) that powers the
dashboard.

## Setup - local (VS Code)

```powershell
# 1. Python 3.12 (once)
winget install --id Python.Python.3.12 -e --source winget --scope user

# 2. from the project folder
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
python -m ipykernel install --user --name pricelab --display-name "Python (pricelab)"
```

In VS Code: **Python: Select Interpreter** -> `.venv`. Install the recommended extensions
(`.vscode/extensions.json`).

Optional local extras:
```powershell
pip install -e ".[sqlserver]"   # mirror ingestion output into your local SQL Server
pip install -e ".[dashboard]"   # run the Streamlit dashboard (streamlit, plotly)
```
`sqlserver` needs "ODBC Driver 17 (or newer) for SQL Server" installed and a reachable SQL
Server instance - configure it in `config/database.yaml`.

Fallbacks if `winget` is blocked: install Python from the Microsoft Store (`python3`) or
<https://www.python.org/downloads/> (tick *Add to PATH*).

## Setup - Google Colab

The code runs unchanged on Colab. Upload the project `data/` folder to Google Drive, then in the
first notebook cell (already wired in `notebooks/01_ingestion.ipynb`):

```python
from google.colab import drive; drive.mount("/content/drive")
import os
os.environ["PRICELAB_DATA_DIR"] = "/content/drive/MyDrive/price-trend-framework/data"
!pip install -q -e /content/drive/MyDrive/price-trend-framework
```

`PRICELAB_DATA_DIR` is the only knob: set it and every loader reads from that location.

## Run the ingestion pipeline

```powershell
python -m pricelab.ingest --all              # all sources
python -m pricelab.ingest --source crop_production
python -m pricelab.ingest --all --no-write   # dry run
```

or open `notebooks/01_ingestion.ipynb` and *Run All*.

```python
from pricelab.ingest import run
result = run(all=True)          # -> IngestResult
result.master                   # tidy-long DataFrame
```

## Where the data actually lives

There are **two databases**, on purpose - see `config/database.yaml`:

| | Local SQL Server | DuckDB snapshot |
|---|---|---|
| File/location | `PriceTrendFramework` DB in your SQL Server instance | `data/processed/pricelab.duckdb` (committed to git) |
| Written by | `pricelab.integration.sql_export` | `pricelab.integration.duckdb_export` |
| Purpose | browse/query locally in SSMS | **the deployed dashboard's data source** |
| Reachable from the internet? | No, and it shouldn't be | N/A - it's a file shipped with the code |

Every `python -m pricelab.ingest --all` run refreshes both automatically (SQL Server mirroring is
best-effort: if the `[sqlserver]` extra isn't installed or the server isn't reachable, ingestion
logs a warning and continues - see `--no-sql` to skip it on purpose).

## The dashboard

```powershell
pip install -e ".[dashboard]"     # streamlit + plotly (once)
streamlit run dashboard/app.py    # or: .\run.cmd dashboard
```

Opens `http://localhost:8501` with 4 pages: **Home** (KPIs + General CPI), **CPI Trends**
(compare price groups over time), **Crop Production** (top districts by area/production/yield),
**Data Explorer** (filter + download `master_long`). It reads only the DuckDB snapshot - never
SQL Server - so it works identically once deployed.

### Deploying it publicly (Streamlit Community Cloud - free)

1. Push this repo to GitHub (see below).
2. Go to <https://share.streamlit.io>, sign in with GitHub, **New app**.
3. Pick this repo/branch, set **Main file path** to `dashboard/app.py`, Deploy.
4. Streamlit Cloud installs `requirements.txt` (which installs `pricelab` + the dashboard extra)
   and serves the same 4 pages at a public `*.streamlit.app` URL.
5. To publish new data: run ingestion locally (refreshes `pricelab.duckdb`), commit, push - the
   deployed app updates automatically (or click "Rerun" on share.streamlit.io).

## The tidy-long schema (`pricelab.schema`)

One row = one observation. Columns:

| column | meaning |
|---|---|
| `date` | period start (`datetime64`) |
| `freq` | `M` / `W` / `A` |
| `region` / `region_level` | canonical region + `national`/`province`/`division`/`district` |
| `commodity` | canonical commodity or CPI group (`""` for pure macro series) |
| `variable` | `cpi_index`, `crop_area`, `crop_production`, `crop_yield`, … |
| `value` / `unit` | measurement + unit string |
| `source` | key from `config/sources.yaml` |
| `is_imputed` | `True` if the value was filled/derived |

Uniqueness key: `date, freq, region, commodity, variable, source`.

## Current data sources

| source key | file / sheet | what | frequency | coverage |
|---|---|---|---|---|
| `inflation_cpi_groups` | `Inflation.xlsx` / Sheet1 | CPI index, 13 COICOP groups | monthly | 2016-07 → 2026-07 |
| `crop_production` | `crops intern.xlsx` / CropData | district crop area / production / yield | annual (FY) | FY2020-21 → FY2024-25 |
| `crop_dim` | `crops intern.xlsx` / Crops | crop dimension table | — | reference |
| `region_hierarchy` | `crops intern.xlsx` / ds | district → division → province | — | reference |
| `cpi_item_dictionary` | `CPI ITEMs.xlsx` / ITEMS | CPI item codes, descriptions, units | — | reference |

> Note: crop `Yield` is blank in the raw file and is computed as production / area
> (`is_imputed = True`). No per-product **retail price** series is loaded yet - the schema is
> ready for it (add SPI / retail-price sheets as new `sources.yaml` entries).

## Adding a new dataset

1. Put the file in `data/raw/`.
2. Add an entry to `config/sources.yaml` (`path`, `sheet`, `loader`, `kind`).
3. If the shape is new, add a loader function under `src/pricelab/ingestion/` decorated with
   `@register_loader("name")` returning tidy-long rows; otherwise reuse an existing loader.
4. Run `python -m pricelab.ingest --all` and check `ingestion_report.md` for unmapped
   region/commodity names → add aliases to `config/regions.yaml` / `config/commodities.yaml`.

## Project layout

```
config/            YAML: sources, commodities, regions, analysis, database settings
src/pricelab/
  config.py        config + path resolution (PRICELAB_DATA_DIR seam)
  schema.py        tidy-long schema + validation
  ingestion/       one loader per source shape
  integration/     harmonize keys, build master_long, write report,
                   sql_export.py (local SQL Server), duckdb_export.py (snapshot)
  dashboard/       data.py (duckdb reads), theme.py (chart colors)
  ingest.py        CLI: python -m pricelab.ingest
dashboard/         Streamlit app: app.py (home) + pages/ (CPI Trends, Crop
                   Production, Data Explorer) - this is what gets deployed
data/{raw,interim,processed}/
notebooks/         01_ingestion.ipynb (more to come)
tests/             pytest suite (runs against data/raw)
```

## Tests

```powershell
pytest
```
