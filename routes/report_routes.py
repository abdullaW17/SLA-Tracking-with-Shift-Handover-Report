"""
routes/report_routes.py
--------------------------
Report listing, generation, and download.
"""

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    send_file, current_app,
)
from flask_login import login_required, current_user

from models import Report, Client
from models.report import REPORT_TYPES
from routes.decorators import permission_required

report_bp = Blueprint("reports", __name__)


@report_bp.route("/reports")
@login_required
@permission_required("view_reports")
def report_list():
    reports = Report.query.order_by(Report.generated_at.desc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()
    return render_template("reports.html", reports=reports, report_types=REPORT_TYPES, clients=clients)


@report_bp.route("/reports/generate", methods=["POST"])
@login_required
@permission_required("generate_reports")
def generate():
    from services.report_generator import generate_report

    report_type = request.form.get("report_type")
    file_format = request.form.get("file_format", "pdf")
    client_id_val = request.form.get("client_id")
    client_id = int(client_id_val) if client_id_val else None

    if report_type not in REPORT_TYPES:
        flash("Unknown report type.", "danger")
        return redirect(url_for("reports.report_list"))

    try:
        report = generate_report(current_app, report_type, file_format, current_user.id, client_id=client_id)
        flash(f"Report generated: {report.report_name}", "success")
    except Exception as exc:  # noqa: BLE001
        flash(f"Report generation failed: {exc}", "danger")

    return redirect(url_for("reports.report_list"))


@report_bp.route("/reports/download/<int:report_id>")
@login_required
@permission_required("view_reports")
def download(report_id):
    report = Report.query.get_or_404(report_id)
    return send_file(report.file_path, as_attachment=True, download_name=report.report_name)
