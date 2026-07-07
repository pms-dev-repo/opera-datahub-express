# Opera DataHub Express

An automated ETL pipeline for **Oracle Hospitality OPERA Cloud Reporting & Analytics (R&A)**.

Opera DataHub Express automatically retrieves PDF reports from email, extracts structured data, and loads it into a PostgreSQL/Supabase database for reporting with Power BI, Excel, or any Business Intelligence platform.

---

## Features

- Automatic email retrieval via IMAP
- Oracle OPERA Cloud PDF report parsing
- High-performance PDF extraction using `pdfplumber`
- Automatic data transformation
- Direct loading into PostgreSQL / Supabase
- Scheduled execution with GitHub Actions
- Automatic email cleanup after successful processing
- Power BI ready
- Modular parser architecture for easy report expansion

---

## Supported Reports

The following Oracle OPERA Cloud reports are currently supported:

| Report | Destination Table |
|---------|-------------------|
| ODATA Arrivals Detail | `odata_arr_detail` |
| ODATA Departures All | `odata_departures_all` |
| ODATA Forecast | `odata_forecast` |
| ODATA Transportation | `odata_transportation` |
| ODATA GIH Birthday | `odata_gih_birthday` |
| Snapshot | `snapshot` |

Additional reports can be added by implementing a new parser and registering it in the processing pipeline.

---

# Architecture

```
                 Oracle OPERA Cloud
                         │
                         ▼
          Reporting & Analytics (R&A)
                         │
                  PDF Reports (Email)
                         ▼
                     Gmail / IMAP
                         │
                         ▼
               Opera DataHub Express
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     Download PDFs   Parse Reports   Transform Data
                         │
                         ▼
                PostgreSQL / Supabase
                         │
                         ▼
                 Power BI / Excel
```

---

# Project Structure

```
src/
│
├── app.py
├── settings.py
├── db.py
│
├── connectors/
│   └── email_client.py
│
├── parsers/
│   ├── pdf_engine.py
│   ├── parser_snapshot.py
│   ├── parser_odata_arr_detail.py
│   ├── parser_odata_departures_all.py
│   ├── parser_odata_forecast.py
│   ├── parser_odata_transportation.py
│   └── parser_odata_gih_birthday.py
│
├── processors/
│   ├── core.py
│   └── utils.py
│
└── config/
    └── reports.yaml

powerquery/
└── Power Query templates

.github/
└── GitHub Actions workflow
```

---

# Requirements

- Python 3.13+
- PostgreSQL or Supabase
- Gmail account with IMAP enabled
- Gmail App Password

---

# Installation

Clone the repository:

```bash
git clone https://github.com/pms-dev-repo/opera-datahub-express.git

cd opera-datahub-express
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Configuration

Create a `.env` file:

```env
DATABASE_URL=

EMAIL_HOST=imap.gmail.com
EMAIL_PORT=993

EMAIL_USER=
EMAIL_PASSWORD=

EMAIL_FOLDER=INBOX

EMAIL_DELETE_AFTER_SUCCESS=true
```

---

# Run

Execute manually:

```bash
python -m src.app
```

---

# GitHub Actions

The project supports fully automated execution using GitHub Actions.

Current schedule:

```yaml
schedule:
  - cron: "*/15 * * * *"
```

Required Repository Secrets:

```
DATABASE_URL

EMAIL_HOST
EMAIL_PORT
EMAIL_USER
EMAIL_PASSWORD
EMAIL_FOLDER

EMAIL_DELETE_AFTER_SUCCESS
```

---

# Power BI

The PostgreSQL database can be connected directly from Power BI using the PostgreSQL connector.

Sample Power Query templates are included for:

- Daily Arrivals
- Daily Departures
- Birthdays Today
- Hotel Figures

---

# Database

Successfully tested with:

- PostgreSQL
- Supabase

---

# Logging

During execution the application reports:

- Downloaded reports
- Processed reports
- Loaded rows
- Processing errors
- Deleted emails

---

# Adding New Reports

Adding a new Oracle report is straightforward:

1. Create a new parser inside `src/parsers`.
2. Return a Pandas DataFrame.
3. Register the parser in `processors/core.py`.
4. Create the destination table in PostgreSQL.
5. Run the application.

No additional changes are required.

---

# Roadmap

- Additional Oracle OPERA reports
- Incremental loading
- Data validation
- Duplicate detection
- Processing statistics
- Load history
- Monitoring dashboard
- Docker support
- Multi-property support

---

# License

MIT License

---

# Author

**PMS Consulting**

Oracle Hospitality Specialists

- Oracle OPERA Cloud
- Reporting & Analytics
- Business Intelligence
- Integrations
- PostgreSQL
- Power BI
