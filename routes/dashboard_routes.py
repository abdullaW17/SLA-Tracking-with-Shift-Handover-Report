"""
routes/dashboard_routes.py
-----------------------------
Main dashboard: aggregate SLA metrics + data for Chart.js visualizations.
Includes Client Health Scorecards, Analyst Leaderboard, Activity Feed,
and PDF/Excel Export endpoints.
"""

import io
from collections import Counter, defaultdict
from datetime import datetime, timezone

from flask import Blueprint, render_template, jsonify, request, send_file
from flask_login import login_required

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from extensions import db
from models import Ticket, Client, ActivityLog
from models.ticket import (
    SLA_WITHIN, SLA_NEAR_BREACH, SLA_BREACHED,
    SLA_CLOSED_WITHIN, SLA_CLOSED_AFTER_BREACH, SLA_NO_RULE,
)
from routes.decorators import permission_required

dashboard_bp = Blueprint("dashboard", __name__)


def _build_dashboard_metrics(client_id=None, month=None):
    query = Ticket.query
    if client_id:
        query = query.filter_by(client_id=client_id)

    tickets = query.all()

    # --- Month filtering ---
    if month:
        tickets = [
            t for t in tickets
            if t.created_at_source and t.created_at_source.strftime("%Y-%m") == month
        ]

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

    # --- Analyst-wise performance & Leaderboard ---
    analyst_map = defaultdict(lambda: {"total": 0, "breached": 0, "within": 0, "closed_minutes": 0, "closed_count": 0})
    for t in tickets:
        analyst = t.assigned_to or "Unassigned"
        analyst_map[analyst]["total"] += 1
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            analyst_map[analyst]["breached"] += 1
        elif t.sla_status in (SLA_WITHIN, SLA_CLOSED_WITHIN):
            analyst_map[analyst]["within"] += 1

        if t.closed_at_source and t.created_at_source:
            analyst_map[analyst]["closed_minutes"] += (t.closed_at_source - t.created_at_source).total_seconds() / 60
            analyst_map[analyst]["closed_count"] += 1

    analyst_leaderboard = []
    for name, s in analyst_map.items():
        comp = round(((s["total"] - s["breached"]) / s["total"]) * 100, 1) if s["total"] else 0.0
        avg_res = round(s["closed_minutes"] / s["closed_count"], 1) if s["closed_count"] else 0
        analyst_leaderboard.append({
            "name": name,
            "total": s["total"],
            "breached": s["breached"],
            "within": s["within"],
            "compliance": comp,
            "avg_resolution": avg_res
        })
    # Sort analysts by compliance desc, then total desc
    analyst_leaderboard.sort(key=lambda x: (x["compliance"], x["total"]), reverse=True)

    # --- Client Health Scorecards ---
    all_clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    client_health = []
    for c in all_clients:
        c_query = Ticket.query.filter_by(client_id=c.id)
        if month:
            c_tickets = [t for t in c_query.all() if t.created_at_source and t.created_at_source.strftime("%Y-%m") == month]
        else:
            c_tickets = c_query.all()

        c_total = len(c_tickets)
        c_open = sum(1 for t in c_tickets if t.is_open())
        c_breached = sum(1 for t in c_tickets if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH))
        c_within = sum(1 for t in c_tickets if t.sla_status in (SLA_WITHIN, SLA_CLOSED_WITHIN))
        c_comp = round((c_within / c_total) * 100, 1) if c_total else 100.0

        client_health.append({
            "id": c.id,
            "name": c.name,
            "city": c.city or "Islamabad",
            "total": c_total,
            "open": c_open,
            "breached": c_breached,
            "compliance": c_comp,
        })

    # --- Severity / priority / criticality distribution ---
    taxonomy_counter = Counter()
    for t in tickets:
        label = t.severity or t.priority or t.criticality
        if label:
            taxonomy_counter[label] += 1

    # --- Monthly SLA trend (based on created_at_source month) ---
    monthly_trend = defaultdict(lambda: {"within": 0, "breached": 0})
    all_tickets = Ticket.query.all()
    if client_id:
        all_tickets = [t for t in all_tickets if t.client_id == client_id]
    for t in all_tickets:
        if not t.created_at_source:
            continue
        key = t.created_at_source.strftime("%Y-%m")
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            monthly_trend[key]["breached"] += 1
        elif t.sla_status in (SLA_WITHIN, SLA_CLOSED_WITHIN):
            monthly_trend[key]["within"] += 1

    sorted_months = sorted(monthly_trend.keys())

    # --- Top Issues ---
    top_issues_counter = Counter()
    top_issues_breach = Counter()
    for t in tickets:
        label = t.severity or t.priority or t.criticality or "Unclassified"
        top_issues_counter[label] += 1
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            top_issues_breach[label] += 1

    top_issues = []
    for label, count in top_issues_counter.most_common(6):
        breach_count = top_issues_breach.get(label, 0)
        compliance = round(((count - breach_count) / count) * 100, 1) if count else 0
        top_issues.append({
            "label": label,
            "count": count,
            "breached": breach_count,
            "compliance": compliance,
        })

    # --- Quarterly received cases ---
    quarterly = defaultdict(int)
    for t in all_tickets:
        if not t.created_at_source:
            continue
        if client_id and t.client_id != client_id:
            continue
        m = t.created_at_source.month
        q = "Q1" if m <= 3 else ("Q2" if m <= 6 else ("Q3" if m <= 9 else "Q4"))
        y = t.created_at_source.strftime("%Y")
        quarterly[f"{y} {q}"] += 1

    sorted_quarters = sorted(quarterly.keys())

    # --- Client-wise ticket counts ---
    client_counts = Counter()
    for t in tickets:
        if t.client_id:
            client_obj = Client.query.get(t.client_id)
            if client_obj:
                client_counts[client_obj.name] += 1
        else:
            client_counts["Unassigned"] += 1

    # --- Available months ---
    available_months = sorted(set(
        t.created_at_source.strftime("%Y-%m")
        for t in all_tickets
        if t.created_at_source
    ), reverse=True)

    # --- Year-to-date SLA compliance ---
    now = datetime.now(timezone.utc)
    ytd_tickets = [
        t for t in all_tickets
        if t.created_at_source and t.created_at_source.year == now.year
    ]
    if client_id:
        ytd_tickets = [t for t in ytd_tickets if t.client_id == client_id]
    ytd_total = len(ytd_tickets)
    ytd_within = sum(
        1 for t in ytd_tickets
        if t.sla_status in (SLA_WITHIN, SLA_CLOSED_WITHIN)
    )
    ytd_compliance = round((ytd_within / ytd_total) * 100, 1) if ytd_total else 0.0

    # --- Regional stats (Pakistan map) ---
    pakistan_cities = {
        "Karachi": {"lat": 24.8607, "lng": 67.0011},
        "Lahore": {"lat": 31.5204, "lng": 74.3587},
        "Islamabad": {"lat": 33.6844, "lng": 73.0479},
        "Rawalpindi": {"lat": 33.5651, "lng": 73.0169},
        "Peshawar": {"lat": 34.0151, "lng": 71.5249},
        "Quetta": {"lat": 30.1798, "lng": 66.9750},
        "Faisalabad": {"lat": 31.4504, "lng": 73.1350},
        "Multan": {"lat": 30.1575, "lng": 71.5249},
    }

    region_data = defaultdict(lambda: {"total": 0, "within": 0, "breached": 0})
    for t in tickets:
        city = "Islamabad"
        if t.client_id:
            c = Client.query.get(t.client_id)
            if c and c.city:
                city = c.city
        region_data[city]["total"] += 1
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            region_data[city]["breached"] += 1
        elif t.sla_status in (SLA_WITHIN, SLA_CLOSED_WITHIN):
            region_data[city]["within"] += 1

    region_stats = {}
    for city_name, stats in region_data.items():
        total_c = stats["total"]
        within_c = stats["within"]
        breached_c = stats["breached"]
        comp = round((within_c / total_c) * 100, 1) if total_c else 0.0
        coords = pakistan_cities.get(city_name, pakistan_cities["Islamabad"])
        region_stats[city_name] = {
            "total": total_c,
            "within": within_c,
            "breached": breached_c,
            "compliance": comp,
            "lat": coords["lat"],
            "lng": coords["lng"],
        }

    # --- Recent Activity Feed ---
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(12).all()
    recent_activity = [
        {
            "id": l.id,
            "event_type": l.event_type,
            "description": l.description,
            "actor": l.actor or "System",
            "time_str": l.timestamp.strftime("%b %d, %H:%M") if l.timestamp else ""
        }
        for l in logs
    ]

    return {
        "total_tickets": total,
        "open_tickets": open_tickets,
        "closed_tickets": closed_tickets,
        "within_sla": within_sla,
        "near_breach": near_breach,
        "breached": breached,
        "no_matching_rule": no_rule,
        "sla_compliance_percent": compliance_pct,
        "ytd_compliance_percent": ytd_compliance,
        "avg_resolution_minutes": avg_resolution_minutes,
        "analyst_stats": dict(analyst_map),
        "analyst_leaderboard": analyst_leaderboard,
        "client_health": client_health,
        "recent_activity": recent_activity,
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
        "top_issues": top_issues,
        "quarterly_received": {
            "labels": sorted_quarters,
            "values": [quarterly[q] for q in sorted_quarters],
        },
        "client_counts": dict(client_counts),
        "available_months": available_months,
        "region_stats": region_stats,
    }


@dashboard_bp.route("/dashboard")
@login_required
@permission_required("view_dashboard")
def index():
    client_id = request.args.get("client_id", type=int)
    month = request.args.get("month", type=str)
    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    metrics = _build_dashboard_metrics(client_id=client_id, month=month)
    return render_template(
        "dashboard.html",
        metrics=metrics,
        clients=clients,
        selected_client_id=client_id,
        selected_month=month,
    )


@dashboard_bp.route("/dashboard/metrics.json")
@login_required
@permission_required("view_dashboard")
def metrics_json():
    """Used by the dashboard template to refresh Chart.js data via fetch()."""
    client_id = request.args.get("client_id", type=int)
    month = request.args.get("month", type=str)
    return jsonify(_build_dashboard_metrics(client_id=client_id, month=month))


@dashboard_bp.route("/dashboard/export")
@login_required
@permission_required("view_dashboard")
def export():
    """Exports current dashboard metrics as Excel (.xlsx) or PDF (.pdf)."""
    export_format = request.args.get("format", "excel").lower()
    client_id = request.args.get("client_id", type=int)
    month = request.args.get("month", type=str)

    metrics = _build_dashboard_metrics(client_id=client_id, month=month)
    filename_base = f"SLA_Dashboard_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"

    if export_format == "excel":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            # Sheet 1: Summary Metrics
            summary_df = pd.DataFrame([
                {"Metric": "SLA Compliance Rate", "Value": f"{metrics['sla_compliance_percent']}%"},
                {"Metric": "Year to Date SLA", "Value": f"{metrics['ytd_compliance_percent']}%"},
                {"Metric": "Total Received Tickets", "Value": metrics["total_tickets"]},
                {"Metric": "Open Tickets", "Value": metrics["open_tickets"]},
                {"Metric": "Resolved Tickets", "Value": metrics["closed_tickets"]},
                {"Metric": "Within SLA", "Value": metrics["within_sla"]},
                {"Metric": "Near Breach", "Value": metrics["near_breach"]},
                {"Metric": "Breached", "Value": metrics["breached"]},
                {"Metric": "Avg Resolution Time (min)", "Value": metrics["avg_resolution_minutes"]},
            ])
            summary_df.to_excel(writer, sheet_name="Summary KPIs", index=False)

            # Sheet 2: Client Health
            if metrics["client_health"]:
                pd.DataFrame(metrics["client_health"]).to_excel(writer, sheet_name="Client Health", index=False)

            # Sheet 3: Analyst Performance
            if metrics["analyst_leaderboard"]:
                pd.DataFrame(metrics["analyst_leaderboard"]).to_excel(writer, sheet_name="Analyst Performance", index=False)

            # Sheet 4: Top Issues
            if metrics["top_issues"]:
                pd.DataFrame(metrics["top_issues"]).to_excel(writer, sheet_name="Top Issues", index=False)

        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{filename_base}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    elif export_format == "pdf":
        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=landscape(A4),
            rightMargin=1.5 * 10,
            leftMargin=1.5 * 10,
            topMargin=1.5 * 10,
            bottomMargin=1.5 * 10
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleStyle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=colors.HexColor("#1a2980"),
            alignment=0,
            spaceAfter=15,
        )

        elements = []
        elements.append(Paragraph("Service Level Management — Dashboard Summary", title_style))
        elements.append(Spacer(1, 10))

        # KPI summary table
        kpi_data = [
            ["Metric", "Value", "Metric", "Value"],
            ["SLA Compliance Rate", f"{metrics['sla_compliance_percent']}%", "Total Received Tickets", str(metrics["total_tickets"])],
            ["YTD SLA Compliance", f"{metrics['ytd_compliance_percent']}%", "Open Tickets", str(metrics["open_tickets"])],
            ["Within SLA", str(metrics["within_sla"]), "Breached Tickets", str(metrics["breached"])],
            ["Near Breach", str(metrics["near_breach"]), "Avg Resolution (min)", str(metrics["avg_resolution_minutes"])],
        ]

        t = Table(kpi_data, colWidths=[150, 100, 150, 100])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1a2980")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#d5dde8")),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 15))

        # Client Health table
        if metrics["client_health"]:
            elements.append(Paragraph("<b>Client Health Summary</b>", styles["Heading2"]))
            elements.append(Spacer(1, 6))
            ch_data = [["Client", "City", "Total", "Open", "Breached", "Compliance"]]
            for ch in metrics["client_health"]:
                ch_data.append([ch["name"], ch["city"], str(ch["total"]), str(ch["open"]), str(ch["breached"]), f"{ch['compliance']}%"])
            ch_table = Table(ch_data, colWidths=[140, 100, 70, 70, 70, 90])
            ch_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#26418f")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#d5dde8")),
            ]))
            elements.append(ch_table)

        doc.build(elements)
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{filename_base}.pdf",
            mimetype="application/pdf"
        )

    return jsonify({"error": "Unsupported export format"}), 400
