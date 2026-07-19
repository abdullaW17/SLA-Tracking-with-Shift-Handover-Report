"""
routes/settings_routes.py
----------------------------
Admin settings page: IRIS base URL, sync interval, timezone, email toggle,
plus a "Test Connection" action and field-mapping management.

Multi-tenancy (Gap #1): includes client CRUD (create/edit/deactivate).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required

from extensions import db
from models import Setting, FieldMapping, Client
from routes.decorators import permission_required

settings_bp = Blueprint("settings", __name__)

SETTINGS_KEYS = [
    ("iris_base_url", "DFIR-IRIS Base URL (overrides .env if set)"),
    ("sync_interval_minutes", "Sync Interval (minutes)"),
    ("default_timezone", "Default Timezone"),
    ("email_notifications_enabled", "Email Notifications Enabled (true/false)"),
]


@settings_bp.route("/settings", methods=["GET", "POST"])
@login_required
@permission_required("manage_iris_settings")
def settings_page():
    if request.method == "POST":
        for key, _label in SETTINGS_KEYS:
            value = request.form.get(key, "")
            Setting.set(key, value)
        flash("Settings saved. Note: sync interval changes take effect after restart.", "success")
        return redirect(url_for("settings.settings_page"))

    current_values = {key: Setting.get(key, "") for key, _label in SETTINGS_KEYS}
    field_mappings = FieldMapping.query.filter_by(source_system="dfir_iris", client_id=None).all()
    clients = Client.query.order_by(Client.name).all()

    return render_template(
        "settings.html",
        settings_keys=SETTINGS_KEYS,
        current_values=current_values,
        field_mappings=field_mappings,
        iris_configured=bool(current_app.config.get("IRIS_API_KEY")),
        clients=clients,
    )


@settings_bp.route("/settings/test-iris-connection", methods=["POST"])
@login_required
@permission_required("manage_iris_settings")
def test_iris_connection():
    from services.iris_api_service import test_connection

    success, message = test_connection()
    flash(message, "success" if success else "danger")
    return redirect(url_for("settings.settings_page"))


@settings_bp.route("/settings/field-mappings/save", methods=["POST"])
@login_required
@permission_required("manage_iris_settings")
def save_field_mapping():
    local_field = request.form.get("local_field", "").strip()
    source_field = request.form.get("source_field", "").strip()

    if not local_field or not source_field:
        flash("Local field and source field are both required.", "danger")
        return redirect(url_for("settings.settings_page"))

    mapping = FieldMapping.query.filter_by(
        source_system="dfir_iris", client_id=None, local_field=local_field
    ).first()

    if mapping:
        mapping.source_field = source_field
    else:
        mapping = FieldMapping(
            source_system="dfir_iris", client_id=None,
            local_field=local_field, source_field=source_field,
        )
        db.session.add(mapping)

    db.session.commit()
    flash(f"Field mapping saved: {local_field} <- {source_field}", "success")
    return redirect(url_for("settings.settings_page"))


# --- Client CRUD (Gap #1) ---

@settings_bp.route("/settings/clients")
@login_required
@permission_required("manage_iris_settings")
def client_list():
    clients = Client.query.order_by(Client.name).all()
    return render_template("clients.html", clients=clients)


@settings_bp.route("/settings/clients/create", methods=["POST"])
@login_required
@permission_required("manage_iris_settings")
def client_create():
    name = request.form.get("name", "").strip()
    iris_customer_id = request.form.get("iris_customer_id", "").strip() or None
    client_timezone = request.form.get("timezone", "Asia/Karachi").strip()
    city = request.form.get("city", "Islamabad").strip()

    if not name:
        flash("Client name is required.", "danger")
        return redirect(url_for("settings.client_list"))

    if Client.query.filter_by(name=name).first():
        flash(f"Client '{name}' already exists.", "warning")
        return redirect(url_for("settings.client_list"))

    client = Client(
        name=name,
        iris_customer_id=iris_customer_id,
        timezone=client_timezone,
        city=city,
    )
    db.session.add(client)
    db.session.commit()
    flash(f"Client '{name}' created.", "success")
    return redirect(url_for("settings.client_list"))


@settings_bp.route("/settings/clients/<int:client_id>/edit", methods=["POST"])
@login_required
@permission_required("manage_iris_settings")
def client_edit(client_id):
    client = Client.query.get_or_404(client_id)
    client.name = request.form.get("name", client.name).strip()
    client.iris_customer_id = request.form.get("iris_customer_id", "").strip() or None
    client.timezone = request.form.get("timezone", "Asia/Karachi").strip()
    client.city = request.form.get("city", client.city or "Islamabad").strip()
    db.session.commit()
    flash(f"Client '{client.name}' updated.", "success")
    return redirect(url_for("settings.client_list"))



@settings_bp.route("/settings/clients/<int:client_id>/toggle", methods=["POST"])
@login_required
@permission_required("manage_iris_settings")
def client_toggle(client_id):
    client = Client.query.get_or_404(client_id)
    client.is_active = not client.is_active
    db.session.commit()
    flash(
        f"Client '{client.name}' is now {'active' if client.is_active else 'inactive'}.",
        "info",
    )
    return redirect(url_for("settings.client_list"))
