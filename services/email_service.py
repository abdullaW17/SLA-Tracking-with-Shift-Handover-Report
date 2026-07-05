"""
services/email_service.py
----------------------------
Basic SMTP email notifications. Structure exists for the MVP even though
actual sending can remain disabled (EMAIL_NOTIFICATIONS_ENABLED=False) until
an organization is ready to configure SMTP + recipient lists.

Notification types:
  - Near breach alert
  - Breach alert
  - Daily SLA summary
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from models import Ticket, User
from models.ticket import SLA_BREACHED, SLA_NEAR_BREACH
from models.user import ROLE_ADMIN, ROLE_MANAGER

logger = logging.getLogger(__name__)


def _send_email(app, subject, body_html, recipients):
    if not recipients:
        logger.info("No recipients configured - skipping email '%s'", subject)
        return False

    cfg = app.config
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_FROM_EMAIL"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as server:
            if cfg.get("SMTP_USE_TLS", True):
                server.starttls()
            if cfg.get("SMTP_USER"):
                server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            server.sendmail(cfg["SMTP_FROM_EMAIL"], recipients, msg.as_string())
        return True
    except Exception:
        logger.exception("Failed to send email: %s", subject)
        return False


def _admin_and_manager_emails():
    users = User.query.filter(User.role.in_([ROLE_ADMIN, ROLE_MANAGER])).all()
    return [u.email for u in users if u.email]


def send_breach_alerts_if_needed(app):
    """Sends one consolidated email listing tickets that are currently
    Breached or Near Breach. Intended to be called after each sync."""
    breached = Ticket.query.filter_by(sla_status=SLA_BREACHED).all()
    near_breach = Ticket.query.filter_by(sla_status=SLA_NEAR_BREACH).all()

    if not breached and not near_breach:
        return False

    rows = "".join(
        f"<tr><td>{t.external_id}</td><td>{t.title}</td><td>{t.sla_status}</td>"
        f"<td>{t.assigned_to or ''}</td></tr>"
        for t in (breached + near_breach)
    )
    body = f"""
    <h3>SLA Alert</h3>
    <p>{len(breached)} breached, {len(near_breach)} near breach.</p>
    <table border="1" cellpadding="4" cellspacing="0">
      <tr><th>External ID</th><th>Title</th><th>Status</th><th>Assigned To</th></tr>
      {rows}
    </table>
    """
    return _send_email(app, "SLA Alert: Breached / Near Breach Tickets",
                        body, _admin_and_manager_emails())


def send_daily_summary_email(app):
    total = Ticket.query.count()
    breached = Ticket.query.filter_by(sla_status=SLA_BREACHED).count()
    near_breach = Ticket.query.filter_by(sla_status=SLA_NEAR_BREACH).count()

    body = f"""
    <h3>Daily SLA Summary</h3>
    <ul>
      <li>Total tickets: {total}</li>
      <li>Breached: {breached}</li>
      <li>Near breach: {near_breach}</li>
    </ul>
    """
    return _send_email(app, "Daily SLA Summary", body, _admin_and_manager_emails())
