# Automated SLA Tracking and Report Generation System

A production-ready, multi-tenant SLA tracking system designed to integrate seamlessly with the **DFIR-IRIS** incident response platform. 

This system acts as a middleware layer that normalizes cases/alerts fetched from DFIR-IRIS, evaluates them against client-specific SLA rules, tracks response and resolution deadlines dynamically, and provides an administrative interface for dashboards, reports, and SLA configurations.

---

## 1. Key Architectural Concepts

The core architecture of the system is built around four fundamental design goals:

### A. Dynamic, Database-Driven SLA Rules
No severity, priority, or urgency taxonomies are hardcoded in the codebase. SLA rules are stored entirely in the database as generic matches.
* When a ticket is normalized, the engine evaluates rules dynamically by performing:
  ```python
  ticket_value = getattr(ticket, rule.field_name)
  ```
  It compares this value against `rule.field_value`.
* This allows the system to easily support any taxonomy defined by an organization (e.g. Critical/High/Medium/Low, P1-P4, Sev1-Sev5) purely through database rows, without code changes.

### B. Multi-Tenancy Scoping
The system is built from the ground up for multi-tenant service providers (MSSPs).
* Every entity (`Ticket`, `SLARule`, `FieldMapping`) is anchored to a specific `Client` through a `client_id` foreign key.
* During IRIS synchronization, incoming tickets are routed to their respective clients by matching the IRIS payload `case_customer_id` with `Client.iris_customer_id`.
* The rule evaluation engine scopes queries to the matching `client_id`, ensuring client rules never collide or leak.

### C. Precision Business Hours SLA Engine
Standard "wall-clock" calculations are insufficient for business-hour SLAs.
* If a rule has `business_hours_only` enabled, deadline calculations utilize client-specific calendars.
* Business minutes are counted sequentially through active working windows, omitting nights, weekends, and client-specific off-hours.
* Timezone operations are strictly normalized: all internal datetimes are stored and compared in UTC, while display conversions translate to the client's local timezone (e.g., `Asia/Karachi`).

### D. Pause/Resume Deadline Shifting
Incidents often enter pending or paused states (e.g. "Awaiting Customer Feedback" or "Under Vendor Investigation").
* When a ticket enters an IRIS status classified as a pause state, the system records `paused_at`.
* Upon resuming, the elapsed time is added to `total_paused_minutes`, and the response/resolution deadlines are shifted forward by that exact delta. This prevents false breach alerts caused by third-party delays.

---

## 2. Project Directory Structure

The codebase is organized logically as a standard Flask application package:

```text
automated-sla-tracker/
├── app.py                          # Flask application factory and entry point
├── config.py                       # Configuration classes loading from environment
├── extensions.py                   # Shared Flask extensions (avoids circular imports)
├── cli.py                          # Custom Flask CLI commands registration
├── requirements.txt                # Python dependencies list
├── .env.example                    # Template file for environment variables
├── .gitignore                      # Git exclusion rules
├── scripts/                        # Relocated standalone utility/admin scripts
│   ├── seed_data.py                # Standalone DB seeder
│   ├── clear_seed_data.py          # Standalone DB cleaner
│   └── fix_field_mappings.py       # Standalone field mappings script
├── models/                         # Database models (SQLAlchemy ORM)
│   ├── client.py                   # Client (multi-tenancy anchor, timezone, business hours)
│   ├── user.py                     # User account details and RBAC permission matrix
│   ├── ticket.py                   # Local normalized tickets and SLA thresholds
│   ├── sla_rule.py                 # SLA rule conditions and priority ranks
│   ├── field_mapping.py            # Local-to-source-system key maps
│   ├── report.py                   # PDF/Excel report audit log
│   ├── setting.py                  # Key/value runtime system settings
│   └── sync_log.py                 # Historical synchronization records
├── services/                       # Business logic and external API integrations
│   ├── iris_api_service.py         # DFIR-IRIS REST API Client
│   ├── field_mapping_service.py    # Ticket normalization and field translation service
│   ├── sla_calculator.py           # Core SLA evaluation, pause logic, and business hours math
│   ├── sync_service.py             # Orchestrates Fetch -> Normalize -> Evaluate -> Save lifecycle
│   ├── report_generator.py         # PDF (ReportLab) and Excel (Pandas) generation engine
│   ├── scheduler_service.py        # Background jobs using APScheduler
│   └── email_service.py            # SMTP notification client for breaches
├── routes/                         # Flask blueprints (controllers)
│   ├── decorators.py               # RBAC permission checking decorators
│   ├── auth_routes.py              # Login, lockout, and password change endpoints
│   ├── dashboard_routes.py         # Performance charts and analytics views
│   ├── ticket_routes.py            # Ticket search, filter, and detail views
│   ├── sla_rule_routes.py          # SLA rules CRUD management
│   ├── report_routes.py            # Report generation and download triggers
│   └── settings_routes.py          # General settings mapping and connection tests
├── templates/                      # Jinja2 HTML templates styled with Bootstrap 5
├── static/                         # Static assets directory
│   ├── css/style.css               # Core styling sheet
│   └── images/                     # Served image and logo files
├── instance/                       # Default folder for local SQLite database
└── generated_reports/              # Storage directory for output PDF/Excel reports
```

---

## 3. Configuration Reference (.env)

The application is configured dynamically using environment variables. Below is the list of available configuration parameters:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SECRET_KEY` | String | `dev-secret-key-change-me` | Key used by Flask to encrypt session cookies. Change in production. |
| `DATABASE_URL` | String | *SQLite default* | Database connection string. Use `postgresql://...` for PostgreSQL. |
| `FLASK_ENV` | String | `development` | Operating environment: `development` or `production`. |
| `IRIS_BASE_URL` | String | *None* | Base URL of your DFIR-IRIS instance (e.g. `https://iris.example.com`). |
| `IRIS_API_KEY` | String | *None* | API key for authenticating with the DFIR-IRIS REST API. |
| `IRIS_VERIFY_SSL` | Boolean | `True` | Set to `False` if your local IRIS server uses self-signed certificates. |
| `IRIS_TIMEOUT_SECONDS`| Integer | `30` | Network request timeout for IRIS API queries. |
| `SYNC_INTERVAL_MINUTES`| Integer| `15` | Interval in minutes at which the background sync job runs. |
| `SCHEDULER_ENABLED` | Boolean | `True` | Set to `False` to prevent the background scheduler from starting. |
| `DAILY_REPORT_ENABLED`| Boolean | `False` | Automatically generate a PDF summary report every day. |
| `DAILY_REPORT_HOUR` | Integer | `7` | Hour (0-23 UTC) at which the daily report is generated. |
| `DEFAULT_TIMEZONE` | String | `UTC` | Timezone fallback when a client's timezone is unspecified. |
| `EMAIL_NOTIFICATIONS_ENABLED` | Boolean | `False` | Enable SMTP-based email alerts for SLA warnings and breaches. |
| `SMTP_HOST` | String | *None* | Hostname of the outgoing SMTP email server. |
| `SMTP_PORT` | Integer | `587` | Connection port for the SMTP email server. |
| `SMTP_USER` | String | *None* | Username for SMTP authentication. |
| `SMTP_PASSWORD` | String | *None* | Password for SMTP authentication. |
| `SMTP_FROM_EMAIL` | String | *None* | Outbound email sender address. |
| `SMTP_USE_TLS` | Boolean | `True` | Enforce TLS encryption for SMTP connections. |
| `REPORTS_FOLDER` | String | `generated_reports`| Local path where PDF and Excel reports are saved. |

---

## 4. Setup and Run Instructions

### Prerequisites
* Python 3.10+
* pip
* Git

### Step-by-Step Installation

```bash
# 1. Clone the project and navigate inside it
git clone https://github.com/abdullaW17/SLA-Tracking-with-Shift-Handover-Report.git
cd SLA-Tracking-with-Shift-Handover-Report

# 2. Create and activate a Python virtual environment
python -m venv venv
source venv/bin/activate       # On Windows: venv\Scripts\activate

# 3. Install required packages
pip install -r requirements.txt

# 4. Copy the environment template and edit configuration
cp .env.example .env
# Edit the .env file with your specific configurations
```

---

## 5. Command-Line Interface (CLI) Usage

The application includes custom Flask CLI commands registered under the standard Flask runner for administrative tasks.

### Seeding the Database
To create database tables, seed the default RBAC roles/users, set default IRIS mappings, and run an initial sync:
```bash
flask seed
```
*Note: This can also be executed as a standalone script using `python scripts/seed_data.py`.*

#### Seed Demo Login Accounts:
| Username | Password | Role | Permissions |
|----------|----------|------|-------------|
| `admin` | `Admin123!` | Admin | Full Access |
| `manager`| `Manager123!`| Manager | Dashboard, Tickets, Reports |
| `viewer` | `Viewer123!` | Viewer | Read-only Dashboard and Tickets |

*Warning: Ensure you update these passwords via the user settings page before moving to production.*

### Clearing Seeded Data
To remove seeded clients, SLA rules, and tickets while leaving system settings and user accounts intact:
```bash
flask clear-seed
```
*Note: Standalone alternative: `python scripts/clear_seed_data.py`.*

### Updating/Repairing Mappings
If the sync payload keys returned by your DFIR-IRIS instance do not match local defaults:
```bash
flask fix-mappings
```
*Note: Standalone alternative: `python scripts/fix_field_mappings.py`.*

---

## 6. Development & Run Commands

### Running Locally
To launch the development server (with scheduler job triggers active):
```bash
python app.py
```
Or use the standard Flask CLI runner:
```bash
flask run --port=5000
```

### Running Tests
To run unit and integration tests (such as calculators and synchronization services):
```bash
pytest
```

---

## 7. Connecting to a Live DFIR-IRIS Server

1. Open your `.env` configuration file.
2. Provide the base URL and API token:
   ```env
   IRIS_BASE_URL=https://your-iris-domain.com
   IRIS_API_KEY=your_secured_api_key_here
   ```
3. Boot the Flask app and log in as `admin`.
4. Navigate to **Settings -> Test IRIS Connection** in the navigation bar to test connectivity.
5. If successful, review the **Field Mappings** page to verify mapping definitions match your IRIS instance fields (e.g. `severity` maps to `classification`).
6. Click **Sync from IRIS** on the Tickets page to ingest your current cases.

---

## 8. Database Migration to PostgreSQL

To swap from the default local SQLite database to a production PostgreSQL database:

1. Install the PostgreSQL database adapter:
   ```bash
   pip install psycopg2-binary
   ```
2. Modify `DATABASE_URL` in your `.env` file:
   ```env
   DATABASE_URL=postgresql+psycopg2://username:password@localhost:5432/db_name
   ```
3. Initialize the tables on your database server:
   ```bash
   flask seed
   ```
   *(Or run migrations using: `flask db upgrade` if upgrading an existing schema)*

---

## 9. Known Limitations

* **In-Memory Rate Limiting**: The login lockout counter is currently stored in memory. Relocating to a distributed cache (like Redis) is recommended for horizontal deployments to prevent counters from resetting during server restarts.
* **Single Business Calendar**: The engine computes business hour SLAs based on a single customizable working window. A calendar table configuration is recommended to support complex, per-client shifts.
* **Report Retention Policy**: Generated files are managed under a strict 90-day retention rule. Weekly, the scheduler executes the cleanup service which purges any database rows and corresponding disk files older than 90 days. Adjust the arguments in `services/cleanup_service.py` to change this duration.
