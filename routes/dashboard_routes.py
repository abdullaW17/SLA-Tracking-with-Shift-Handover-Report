"""
routes/dashboard_routes.py
-----------------------------
Main dashboard: aggregate SLA metrics + data for Chart.js visualizations.

Multi-tenancy (Gap #1): metrics can be filtered by client_id. If no client
filter is provided, all clients' data is shown (admin view).
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required

from extensions import db
from models import Ticket, Client
from models.ticket import (
    SLA_WITHIN, SLA_NEAR_BREACH, SLA_BREACHED,
    SLA_CLOSED_WITHIN, SLA_CLOSED_AFTER_BREACH, SLA_NO_RULE,
)
from routes.decorators import permission_required

dashboard_bp = Blueprint("dashboard", __name__)


def _build_dashboard_metrics(client_id=None):
    query = Ticket.query
    if client_id:
        query = query.filter_by(client_id=client_id)

    tickets = query.all()
    total = len(tickets)
    open_tickets = sum(1 for t in tickets if t.is_open())
    closed_tickets = total - open_tickets

    status_counts = Counter(t.sla_status or SLA_NO_RULE for t in tickets)
    within_sla = status_counts.get(SLA_WITHIN, 0) + status_counts.get(SLA_CLOSED_WITHIN, 0)
    near_breach = status_counts.get(SLA_NEAR_BREACH, 0)
    breached = status_counts.get(SLA_BREACHED, 0) + status_counts.get(SLA_CLOSED_AFTER_BREACH, 0)
    no_rule = status_counts.get(SLA_NO_RULE, 0)

    compliance_pct = round((within_sla / total) * 100, 1) if total else 0.0

    # Average resolution time (minutes) for closed tickets that had a rule
    resolved = [t for t in tickets if t.closed_at_source and t.created_at_source]
    if resolved:
        total_minutes = sum(
            (t.closed_at_source - t.created_at_source).total_seconds() / 60 for t in resolved
        )
        avg_resolution_minutes = round(total_minutes / len(resolved), 1)
    else:
        avg_resolution_minutes = 0

    # Analyst-wise performance
    analyst_stats = defaultdict(lambda: {"total": 0, "breached": 0})
    for t in tickets:
        analyst = t.assigned_to or "Unassigned"
        analyst_stats[analyst]["total"] += 1
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            analyst_stats[analyst]["breached"] += 1

    # Severity / priority / criticality distribution (whichever field is used)
    taxonomy_counter = Counter()
    for t in tickets:
        label = t.severity or t.priority or t.criticality
        if label:
            taxonomy_counter[label] += 1

    # Monthly SLA trend (based on created_at_source month)
    monthly_trend = defaultdict(lambda: {"within": 0, "breached": 0})
    for t in tickets:
        if not t.created_at_source:
            continue
        key = t.created_at_source.strftime("%Y-%m")
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            monthly_trend[key]["breached"] += 1
        elif t.sla_status in (SLA_WITHIN, SLA_CLOSED_WITHIN):
            monthly_trend[key]["within"] += 1

    sorted_months = sorted(monthly_trend.keys())

    return {
        "total_tickets": total,
        "open_tickets": open_tickets,
        "closed_tickets": closed_tickets,
        "within_sla": within_sla,
        "near_breach": near_breach,
        "breached": breached,
        "no_matching_rule": no_rule,
        "sla_compliance_percent": compliance_pct,
        "avg_resolution_minutes": avg_resolution_minutes,
        "analyst_stats": dict(analyst_stats),
        "sla_status_distribution": {
            "Within SLA": within_sla,
            "Near Breach": near_breach,
            "Breached": breached,
            "No Matching Rule": no_rule,
        },
        "taxonomy_distribution": dict(taxonomy_counter),
        "monthly_trend": {
            "labels": sorted_months,
            "within": [monthly_trend[m]["within"] for m in sorted_months],
            "breached": [monthly_trend[m]["breached"] for m in sorted_months],
        },
    }


@dashboard_bp.route("/dashboard")
@login_required
@permission_required("view_dashboard")
def index():
    client_id = request.args.get("client_id", type=int)
    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    metrics = _build_dashboard_metrics(client_id=client_id)
    return render_template(
        "dashboard.html",
        metrics=metrics,
        clients=clients,
        selected_client_id=client_id,
    )


@dashboard_bp.route("/dashboard/metrics.json")
@login_required
@permission_required("view_dashboard")
def metrics_json():
    """Used by the dashboard template to refresh Chart.js data via fetch()."""
    client_id = request.args.get("client_id", type=int)
    return jsonify(_build_dashboard_metrics(client_id=client_id))
