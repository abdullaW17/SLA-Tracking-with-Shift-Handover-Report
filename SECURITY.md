# Security Policy & Implementation Details

This document outlines the security policies, architecture, and threat mitigation measures implemented in the Automated SLA Tracking and Report Generation System.

---

## 1. Reporting a Vulnerability

We take the security of this project seriously. If you identify any security vulnerabilities or have concerns, please report them to us immediately.

### Submission Guidelines
* **Do NOT open public GitHub issues** for security vulnerabilities.
* Contact the maintainer team directly via email: `security-alerts@example.com` (replace with your organization's security email).
* In your report, please include:
  * A clear description of the vulnerability.
  * Step-by-step instructions to reproduce the issue.
  * The potential impact (e.g. privilege escalation, remote code execution, SQL injection).
  * Any proof-of-concept (PoC) code or requests.

### Disclosure Process
1. **Acknowledgement**: We will acknowledge receipt of your report within **24 hours**.
2. **Investigation**: Our team will investigate the issue and attempt to reproduce it. We aim to confirm the finding within **3 business days**.
3. **Patching**: We will write and test a fix. This process typically takes between **7 to 14 days** depending on complexity.
4. **Release**: A patched version will be merged. With your permission, we will credit you in the release notes or commit messages.

---

## 2. Supported Versions

Only the latest active major version receives security updates.

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |
| < 1.0   | No        |

---

## 3. Implemented Security Controls

This application uses a multi-layered security model built on modern security best practices. Below is a breakdown of the controls present in the codebase.

### A. Authentication & Password Hardening
* **Hashing Algorithm**: We do not store plaintext passwords. The system uses Werkzeug's `generate_password_hash` and `check_password_hash` functions, which utilize PBKDF2 with SHA-256 and a strong salt configuration.
* **Session Login**: Managed securely via **Flask-Login** (`LoginManager`). Session authentication tokens are linked to the database `User` records.
* **Rate Limiting**: To mitigate brute-force password guessing, an in-memory rate-limiter monitors failed login attempts per username and enforces a temporary lockout period when a limit is exceeded.

### B. Role-Based Access Control (RBAC)
User authorization is enforced at the route level using custom decorators. The roles are defined hierarchically:

1. **Admin**: Full access (manage SLA rules, settings, databases, reports, sync, view dashboards/tickets).
2. **Manager**: Access to dashboards, ticket lists, and report generation/downloads. Cannot manage SLA rules or settings.
3. **Viewer**: Read-only access to dashboards and ticket lists. Cannot trigger syncs, generate reports, or modify configuration.

#### Enforcement Mechanism
The decorators `routes/decorators.py:role_required` and `permission_required` check the current user's role against the permissions matrix defined in [models/user.py](file:///c:/Users/ma420/Downloads/automated-sla-tracker/automated-sla-tracker/models/user.py):
```python
ROLE_PERMISSIONS = {
    "Admin": ["view_dashboard", "view_tickets", "manage_rules", "generate_reports", "manage_settings"],
    "Manager": ["view_dashboard", "view_tickets", "generate_reports"],
    "Viewer": ["view_dashboard", "view_tickets"],
}
```
If a user lacks permission, a `403 Forbidden` response is returned.

### C. Session & Cookie Hardening
To protect against Session Hijacking and Session Fixation attacks:
* **HTTPOnly**: `SESSION_COOKIE_HTTPONLY` is set to `True` to prevent client-side scripts (XSS) from accessing session cookies.
* **SameSite**: `SESSION_COOKIE_SAMESITE` is set to `Lax` to prevent Cross-Site Request Forgery (CSRF) leakage via third-party requests.
* **Secure Flag**: In production deployments (`FLASK_ENV=production`), `SESSION_COOKIE_SECURE` should be enabled so cookies are only transmitted over TLS/HTTPS connections.
* **Session Lifetime**: Set to a strict maximum (`PERMANENT_SESSION_LIFETIME = timedelta(hours=8)`).

### D. Cross-Site Request Forgery (CSRF) Protection
* **Form Protection**: Flask-WTF's `CSRFProtect` is enabled globally. Every state-changing form (POST, PUT, DELETE) must include a unique CSRF token (`{{ form.csrf_token }}` or `<input type="hidden" name="csrf_token" value="...">`).
* **AJAX & Fetch requests**: AJAX endpoints retrieve the token from the page header `<meta name="csrf-token" content="{{ csrf_token() }}">` and include it in the `X-CSRFToken` request header.

### E. SQL Injection Prevention
* **ORM Usage**: All database queries are constructed using SQLAlchemy ORM expressions (e.g., `db.session.query(Ticket).filter(...)`). Parameterized queries are automatically handled by SQLAlchemy and SQLite/PostgreSQL drivers, rendering SQL injection impossible.
* **Direct Execution Safeguard**: Where direct SQL execution is used (such as model migrations), `db.text()` wrapper expressions are utilized with parameters rather than string formatting/concatenation.

### F. Cross-Site Scripting (XSS) Mitigation
* **Template Escaping**: Jinja2 automatic escaping is enabled for all templates (`.html` files). HTML characters (such as `<`, `>`, `&`, `"`, `'`) are automatically replaced with safe HTML entities before rendering.
* **Context Helper Sanitization**: Custom display functions (e.g., severity displays, names, customer labels) are sanitized prior to display to avoid execution of malicious payload scripts.

### G. Sensitive Configuration Management
* **Secrets Separation**: Sensitive values (such as `SECRET_KEY`, `IRIS_API_KEY`, `DATABASE_URL`, and `SMTP_PASSWORD`) are never hardcoded in python source code.
* **Environment Configuration**: Config values are loaded dynamically from environment variables using `python-dotenv`. An `.env.example` file is provided as a template. The real `.env` file containing production credentials is gitignored to prevent accidental commits to public repositories.
