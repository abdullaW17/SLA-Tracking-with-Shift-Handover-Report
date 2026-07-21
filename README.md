# Automated SLA Tracking and Report Generation System

A generic, database-driven SLA tracking system integrated with **DFIR-IRIS**.
Built with Flask, SQLAlchemy, and Bootstrap.

The core design goal: **no severity/priority/criticality values are ever
hardcoded in Python code.** SLA rules live entirely in the database as
`field_name` / `field_value` pairs, so the same code works whether an
organization uses Critical/High/Medium/Low, P1-P4, Sev1-Sev4, or any other
taxonomy.

---

## 1. Features

- **Authentication & RBAC** - Flask-Login, hashed passwords, 3 roles
  (Admin, Manager, Viewer) with a lightweight `@permission_required(...)` decorator.
- **DFIR-IRIS Integration** - `services/iris_api_service.py` fetches
  cases/alerts via the IRIS REST API.
- **Field Mapping Layer** - `field_mappings` table + `normalize_ticket()`
  translate arbitrary source field names into the generic local ticket model.
- **Generic SLA Rule Engine** - `sla_rules` table + `sla_calculator.py`
  match tickets to rules purely via `getattr(ticket, rule.field_name) == rule.field_value`.
- **Dashboard** - Chart.js visualizations: SLA status distribution,
  taxonomy breakdown, breach rate, monthly trend, analyst performance.
- **Ticket List** - search, multi-field filters, color-coded SLA badges.
- **SLA Rules CRUD** - Admin-only rule management UI.
- **Reports** - PDF (ReportLab) and Excel (Pandas/OpenPyXL) generation for
  4 report types, downloadable from the Reports page.
- **Scheduler** - APScheduler background job syncs IRIS + recalculates SLA
  on a configurable interval; optional daily report + email job.
- **Email Notifications** - SMTP-based near-breach/breach/daily-summary
  emails (structure included, disabled by default).
- **Sync Logs** - every sync run is recorded for debugging.

---

## 2. Project Structure

```
automated-sla-tracker/
├── app.py                     # Application factory + entry point
├── config.py                  # Env-driven configuration
├── extensions.py              # Shared db / login_manager / migrate / scheduler
├── cli.py                     # Custom Flask CLI commands (flask seed, flask clear-seed, etc)
├── requirements.txt
├── .env.example
├── scripts/                   # Relocated standalone utility/admin scripts
│   ├── seed_data.py           # Seeds users, rules, and triggers sync
│   ├── clear_seed_data.py     # Clears all seeded clients, rules, and tickets
│   └── fix_field_mappings.py  # Repairs/fixes IRIS field mapping keys
├── models/
│   ├── user.py                # User + RBAC permission matrix
│   ├── ticket.py               # Generic local ticket model
│   ├── sla_rule.py             # Generic SLA rule (field_name/field_value)
│   ├── field_mapping.py        # Source-field -> local-field mapping
│   ├── report.py               # Generated report records
│   ├── setting.py              # Key/value runtime settings
│   └── sync_log.py             # Sync run history
├── services/
│   ├── iris_api_service.py     # DFIR-IRIS REST API wrapper
│   ├── field_mapping_service.py# normalize_ticket() + mapping helpers
│   ├── sla_calculator.py       # The generic SLA rule engine
│   ├── sync_service.py         # Orchestrates fetch -> normalize -> save -> SLA
│   ├── report_generator.py     # PDF/Excel report generation
│   ├── scheduler_service.py    # APScheduler job registration
│   └── email_service.py        # SMTP notifications
├── routes/
│   ├── decorators.py           # @role_required / @permission_required
│   ├── auth_routes.py
│   ├── dashboard_routes.py
│   ├── ticket_routes.py
│   ├── sla_rule_routes.py
│   ├── report_routes.py
│   └── settings_routes.py
├── templates/                  # Jinja2 + Bootstrap 5 templates
├── static/css/style.css
├── generated_reports/          # PDF/Excel output (gitignored in practice)
└── instance/                   # SQLite DB lives here by default
```

---

## 3. Setup & Run (local development)

### Prerequisites
- Python 3.10+
- pip

### Steps

```bash
# 1. Clone / unzip the project, then cd into it
cd automated-sla-tracker

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env: set SECRET_KEY, and (when ready) IRIS_BASE_URL / IRIS_API_KEY

# 5. Initialize and seed the database
#    (creates tables, 3 demo users, sample SLA rules across 3 different
#     taxonomies, and 11 dummy tickets exercising every SLA status)
flask seed                      # (Alternative: python scripts/seed_data.py)

# 6. Run the app
python app.py
# App will be available at http://localhost:5000
```

### Demo logins (created by the seed command)

| Username | Password    | Role    |
|----------|-------------|---------|
| admin    | Admin123!   | Admin   |
| manager  | Manager123! | Manager |
| viewer   | Viewer123!  | Viewer  |

**Change these passwords before any real/production use.**

---

## 4. Connecting to a real DFIR-IRIS instance

1. In `.env`, set:
   ```
   IRIS_BASE_URL=https://your-iris-instance.example.com
   IRIS_API_KEY=your-real-api-key
   ```
2. Go to **Settings -> Test IRIS Connection** in the UI to verify connectivity.
3. Check **Settings -> Field Mappings** and adjust `local_field -> source_field`
   pairs if your IRIS instance's JSON field names differ from the defaults
   assumed in `services/field_mapping_service.py` (`DEFAULT_IRIS_FIELD_MAPPINGS`).
4. Click **Sync from IRIS** on the Tickets page, or wait for the scheduled
   sync (interval set by `SYNC_INTERVAL_MINUTES`).

If your IRIS deployment's actual endpoint paths differ from
`/api/cases/list`, `/api/alerts/filter`, `/api/cases/{id}`, or `/api/ping`,
update those paths in `services/iris_api_service.py` - that's the only file
that needs to change.

---

## 5. Configuring SLA Rules (no code changes needed)

Go to **SLA Rules** (Admin only) and click **Add SLA Rule**. Example:

| Field           | Value             |
|------------------|------------------|
| Rule Name        | Critical Severity SLA |
| Field Name        | severity          |
| Field Value       | Critical           |
| Response SLA (min)| 60                 |
| Resolution SLA (min)| 480              |
| Warning Threshold %| 80                |

To support a company using `priority = P1` instead, just add another rule
with `field_name = priority`, `field_value = P1` - no code changes.

---

## 6. Migrating from SQLite to PostgreSQL

1. `pip install psycopg2-binary`
2. In `.env`, change:
   ```
   DATABASE_URL=postgresql+psycopg2://sla_user:sla_password@localhost:5432/sla_tracker
   ```
3. Re-run `flask seed` (or use Flask-Migrate: `flask db upgrade`)
   against the new database.

No application code changes are required - all data access goes through
SQLAlchemy's ORM.

---

## 7. Running the scheduler / disabling it

The APScheduler background job starts automatically with the app
(`SCHEDULER_ENABLED=True` in `.env`). To disable it (e.g. during
`flask db migrate` commands or tests), set `SCHEDULER_ENABLED=False`, or
run with `RUN_SCHEDULER=0 python app.py`.

---

## 8. Testing report generation manually

From the **Reports** page (Admin/Manager), pick a report type and format
(PDF or Excel) and click **Generate**. Files are written to
`generated_reports/` and tracked in the `reports` table for later download.

---

## 9. Notes for future development (intern handoff)

- All monetary-equivalent "business logic" (SLA matching) lives in
  `services/sla_calculator.py` - read this file first.
- `services/field_mapping_service.py` is the translation layer; if IRIS
  changes field names, only `field_mappings` DB rows need updating.
- `raw_payload_json` on each ticket retains the original IRIS JSON, so
  tickets can be reprocessed if mapping rules change later.
- Add new report types by extending `models/report.py`'s `REPORT_TYPES`
  and adding a branch in `services/report_generator.py`.
- Add a new role by extending `ROLE_PERMISSIONS` in `models/user.py`.

---

## 10. Known Limitations & Report Retention Policy

- **Report Cleanup**: Generated reports are subject to a **90-day retention policy** (configured via `services/cleanup_service.py` and run weekly by the scheduler). Reports older than 90 days are automatically deleted from the database and disk to prevent unbounded disk usage in `generated_reports/`. To adjust this limit, modify `cleanup_old_reports(max_age_days)` arguments or configuration.
- **Single Calendar**: The business hours calculation currently assumes a standard Mon-Fri 09:00-17:00 work week for all clients. An extension to a per-client calendar table is recommended for customized schedules.
- **In-Memory Rate Limiting**: The login lockout mechanism is in-memory; restarting the Flask server resets failed attempt counters.

