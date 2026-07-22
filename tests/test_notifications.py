"""
tests/test_notifications.py
----------------------------
Test verifying real-time SLA notification bell context processor.
"""

from datetime import datetime, timezone, timedelta
from models import Ticket, User
from models.ticket import SLA_NEAR_BREACH, SLA_BREACHED


def test_inject_notifications_near_breach_and_breached(app, db, sample_client):
    with app.app_context():
        user = User.query.first()
        if not user:
            user = User(username="admin_notif_test", role="administrator")
            user.set_password("AdminPass123!")
            db.session.add(user)
            db.session.commit()

        # Create a near breach ticket
        t_near = Ticket(
            client_id=sample_client.id,
            external_id="CASE-NOTIF-NEAR",
            source_system="dfir_iris",
            title="Near Breach Warning",
            status="open",
            sla_status=SLA_NEAR_BREACH,
            resolution_deadline=datetime.now(timezone.utc) + timedelta(minutes=15),
            created_at_source=datetime.now(timezone.utc),
        )
        # Create a breached ticket
        t_breach = Ticket(
            client_id=sample_client.id,
            external_id="CASE-NOTIF-BREACH",
            source_system="dfir_iris",
            title="SLA Breached Alert",
            status="open",
            sla_status=SLA_BREACHED,
            breach_duration_minutes=35,
            resolution_deadline=datetime.now(timezone.utc) - timedelta(minutes=35),
            created_at_source=datetime.now(timezone.utc),
        )
        db.session.add_all([t_near, t_breach])
        db.session.commit()

        with app.test_request_context("/dashboard"):
            from flask_login import login_user
            login_user(user)

            ctx = {}
            for funcs in app.template_context_processors.values():
                for f in funcs:
                    res = f()
                    if isinstance(res, dict) and "notifications" in res:
                        ctx = res
                        break

            assert "notifications" in ctx
            assert "unread_notification_count" in ctx
            assert ctx["unread_notification_count"] >= 2

            notifs = ctx["notifications"]
            near_notifs = [n for n in notifs if n["type"] == "near_breach"]
            breach_notifs = [n for n in notifs if n["type"] == "breach"]

            assert len(near_notifs) >= 1
            assert len(breach_notifs) >= 1
