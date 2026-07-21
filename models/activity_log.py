"""
models/activity_log.py
-----------------------
Audit trail for dashboard activity feed.

Tracks ticket lifecycle events (created, closed, breached, email sent, etc.)
so they can be displayed on the dashboard and handover page.
"""

from datetime import datetime, timezone
from extensions import db


# Event type constants
EVENT_TICKET_CREATED = "ticket_created"
EVENT_TICKET_CLOSED = "ticket_closed"
EVENT_SLA_BREACHED = "sla_breached"
EVENT_SLA_NEAR_BREACH = "sla_near_breach"
EVENT_EMAIL_SENT = "email_sent"
EVENT_HANDOVER_SAVED = "handover_saved"
EVENT_RULE_MATCHED = "rule_matched"


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
    event_type = db.Column(db.String(50), nullable=False, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    description = db.Column(db.String(500), nullable=False)
    actor = db.Column(db.String(200), nullable=True)  # username or "system"

    def __repr__(self):
        return f"<ActivityLog {self.event_type} ticket={self.ticket_id} at={self.timestamp}>"
