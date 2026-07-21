"""
routes/api_routes.py
--------------------
JSON API endpoints for frontend AJAX updates (notification bell, live counts).
"""

from flask import Blueprint, jsonify
from flask_login import login_required, current_user

from models import Ticket, Client
from models.ticket import SLA_BREACHED, SLA_NEAR_BREACH

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/notifications")
@login_required
def get_notifications():
    """Returns urgent open tickets (Breached & Near Breach) for the notification bell."""
    query = Ticket.query.filter(
        Ticket.sla_status.in_([SLA_BREACHED, SLA_NEAR_BREACH]),
        Ticket.closed_at_source.is_(None)
    )

    urgent_tickets = query.order_by(
        Ticket.resolution_deadline.asc().nulls_last(),
        Ticket.id.desc()
    ).limit(10).all()

    notifications = []
    breached_count = 0
    near_breach_count = 0

    for t in urgent_tickets:
        is_breached = t.sla_status == SLA_BREACHED
        if is_breached:
            breached_count += 1
        else:
            near_breach_count += 1

        client_name = "Unassigned"
        if t.client_id:
            c = Client.query.get(t.client_id)
            if c:
                client_name = c.name

        notifications.append({
            "id": t.id,
            "external_id": t.external_id,
            "title": t.title or f"Ticket #{t.external_id}",
            "client_name": client_name,
            "sla_status": t.sla_status,
            "badge_color": "danger" if is_breached else "warning",
            "url": f"/tickets/{t.id}"
        })

    total_count = query.count()

    return jsonify({
        "total_count": total_count,
        "breached_count": breached_count,
        "near_breach_count": near_breach_count,
        "notifications": notifications,
    })
