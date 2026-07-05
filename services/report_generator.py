"""
services/report_generator.py
------------------------------
Generates PDF and Excel reports from ticket/SLA data.

Report types (see models/report.py for constants):
  - SLA Summary Report        : high-level compliance stats
  - Detailed Ticket SLA Report: full ticket-by-ticket breakdown
  - Breached Tickets Report   : only breached / closed-after-breach tickets
  - Analyst Performance Report: per-assignee SLA compliance stats

Uses pandas + openpyxl for Excel, and ReportLab for PDF.
"""

import os
import uuid
from datetime import datetime, timezone

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

from extensions import db
from models import Ticket, Report
from models.ticket import SLA_BREACHED, SLA_CLOSED_AFTER_BREACH, SLA_NEAR_BREACH, SLA_NO_RULE


def _ensure_reports_folder(app):
    folder = app.config["REPORTS_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    return folder


def _tickets_to_rows(tickets):
    rows = []
    for t in tickets:
        rows.append({
            "External ID": t.external_id,
            "Title": t.title,
            "Status": t.status,
            "Severity": t.severity,
            "Priority": t.priority,
            "Criticality": t.criticality,
            "Assigned To": t.assigned_to,
            "Created At": t.created_at_source.strftime("%Y-%m-%d %H:%M") if t.created_at_source else "",
            "SLA Rule Applied": t.sla_rule.rule_name if t.sla_rule_id and t.sla_rule else "N/A",
            "Resolution Deadline": t.resolution_deadline.strftime("%Y-%m-%d %H:%M") if t.resolution_deadline else "",
            "SLA Status": t.sla_status,
            "Breach Duration (min)": t.breach_duration_minutes or 0,
        })
    return rows


def _compute_summary_stats(tickets):
    total = len(tickets)
    breached = sum(1 for t in tickets if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH))
    near_breach = sum(1 for t in tickets if t.sla_status == SLA_NEAR_BREACH)
    no_rule = sum(1 for t in tickets if t.sla_status == SLA_NO_RULE)
    within = total - breached - near_breach - no_rule
    compliance_pct = round((within / total) * 100, 1) if total else 0.0

    return {
        "total_tickets": total,
        "within_sla": within,
        "near_breach": near_breach,
        "breached": breached,
        "no_matching_rule": no_rule,
        "sla_compliance_percent": compliance_pct,
    }


def _analyst_performance_rows(tickets):
    by_analyst = {}
    for t in tickets:
        analyst = t.assigned_to or "Unassigned"
        stats = by_analyst.setdefault(analyst, {"total": 0, "breached": 0, "within": 0})
        stats["total"] += 1
        if t.sla_status in (SLA_BREACHED, SLA_CLOSED_AFTER_BREACH):
            stats["breached"] += 1
        elif t.sla_status not in (SLA_NO_RULE,):
            stats["within"] += 1

    rows = []
    for analyst, stats in sorted(by_analyst.items(), key=lambda kv: -kv[1]["total"]):
        compliance = round((stats["within"] / stats["total"]) * 100, 1) if stats["total"] else 0.0
        rows.append({
            "Analyst": analyst,
            "Total Tickets": stats["total"],
            "Within SLA": stats["within"],
            "Breached": stats["breached"],
            "Compliance %": compliance,
        })
    return rows


def _filename(report_type, ext):
    safe_type = report_type.lower().replace(" ", "_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{safe_type}_{stamp}_{uuid.uuid4().hex[:6]}.{ext}"


def _get_tickets_for_report(report_type, client_id=None):
    query = Ticket.query
    if client_id:
        query = query.filter(Ticket.client_id == client_id)
    if report_type == "Breached Tickets Report":
        return query.filter(
            Ticket.sla_status.in_([SLA_BREACHED, SLA_CLOSED_AFTER_BREACH])
        ).order_by(Ticket.breach_duration_minutes.desc()).all()
    return query.order_by(Ticket.created_at_source.desc()).all()


# ---------------------------------------------------------------------------
# Excel generation
# ---------------------------------------------------------------------------

def generate_excel_report(app, report_type, generated_by_user_id=None, client_id=None):
    folder = _ensure_reports_folder(app)
    tickets = _get_tickets_for_report(report_type, client_id)
    summary = _compute_summary_stats(tickets)

    filename = _filename(report_type, "xlsx")
    filepath = os.path.join(folder, filename)

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        summary_df = pd.DataFrame([{
            "Report": report_type,
            "Generated At": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            **summary,
        }])
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        if report_type == "Analyst Performance Report":
            perf_df = pd.DataFrame(_analyst_performance_rows(tickets))
            perf_df.to_excel(writer, sheet_name="Analyst Performance", index=False)
        else:
            detail_df = pd.DataFrame(_tickets_to_rows(tickets))
            sheet_name = "Breached Tickets" if report_type == "Breached Tickets Report" else "Tickets"
            detail_df.to_excel(writer, sheet_name=sheet_name, index=False)

    report = Report(
        report_name=filename,
        report_type=report_type,
        file_format="xlsx",
        file_path=filepath,
        generated_by=generated_by_user_id,
    )
    db.session.add(report)
    db.session.commit()
    return report


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def generate_pdf_report(app, report_type, generated_by_user_id=None, client_id=None):
    folder = _ensure_reports_folder(app)
    tickets = _get_tickets_for_report(report_type, client_id)
    summary = _compute_summary_stats(tickets)

    filename = _filename(report_type, "pdf")
    filepath = os.path.join(folder, filename)

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=18)
    elements = []

    elements.append(Paragraph(report_type, title_style))
    elements.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 12))

    summary_table_data = [["Metric", "Value"]] + [
        [key.replace("_", " ").title(), str(value)] for key, value in summary.items()
    ]
    summary_table = Table(summary_table_data, hAlign="LEFT")
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 18))

    if report_type == "Analyst Performance Report":
        rows = _analyst_performance_rows(tickets)
        headers = ["Analyst", "Total Tickets", "Within SLA", "Breached", "Compliance %"]
    else:
        rows = _tickets_to_rows(tickets)
        headers = ["External ID", "Title", "Status", "SLA Rule Applied",
                   "Resolution Deadline", "SLA Status", "Breach Duration (min)"]

    table_data = [headers]
    for row in rows[:500]:  # cap rows per PDF page-set for sane file sizes
        table_data.append([str(row.get(h, "")) for h in headers])

    detail_table = Table(table_data, repeatRows=1, hAlign="LEFT")
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
    ]))
    elements.append(detail_table)

    doc.build(elements)

    report = Report(
        report_name=filename,
        report_type=report_type,
        file_format="pdf",
        file_path=filepath,
        generated_by=generated_by_user_id,
    )
    db.session.add(report)
    db.session.commit()
    return report


def generate_report(app, report_type, file_format, generated_by_user_id=None, client_id=None):
    if file_format == "xlsx":
        return generate_excel_report(app, report_type, generated_by_user_id, client_id)
    return generate_pdf_report(app, report_type, generated_by_user_id, client_id)
