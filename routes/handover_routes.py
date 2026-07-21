"""
routes/handover_routes.py
--------------------------
Shift Handover Report page & shift notes management.
"""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import Ticket, Client, Setting, ActivityLog
from models.activity_log import EVENT_HANDOVER_SAVED
from models.ticket import SLA_BREACHED, SLA_NEAR_BREACH, SLA_CLOSED_WITHIN, SLA_CLOSED_AFTER_BREACH
from routes.decorators import permission_required

handover_bp = Blueprint("handover", __name__)


@handover_bp.route("/handover")
@login_required
@permission_required("view_dashboard")
def handover_page():
    client_id = request.args.get("client_id", type=int)
    clients = Client.query.filter_by(is_active=True).order_by(Client.name).all()

    # Query open tickets
    query = Ticket.query.filter(Ticket.closed_at_source.is_(None))
    if client_id:
        query = query.filter_by(client_id=client_id)
    
    open_tickets = query.order_by(
        # Priority: Breached -> Near Breach -> Within SLA
        db.case(
            (Ticket.sla_status == SLA_BREACHED, 1),
            (Ticket.sla_status == SLA_NEAR_BREACH, 2),
            else_=3
        ),
        Ticket.resolution_deadline.asc().nulls_last()
    ).all()

    # Closed tickets in last 12 hours
    since_12h = datetime.now(timezone.utc) - timedelta(hours=12)
    closed_query = Ticket.query.filter(
        Ticket.closed_at_source.isnot(None),
        Ticket.closed_at_source >= since_12h
    )
    if client_id:
        closed_query = closed_query.filter_by(client_id=client_id)
    recent_closed = closed_query.order_by(Ticket.closed_at_source.desc()).all()

    # Load current shift notes & timestamp from Setting model
    notes_setting = Setting.query.filter_by(key="shift_notes").first()
    notes_author_setting = Setting.query.filter_by(key="shift_notes_author").first()
    notes_updated_setting = Setting.query.filter_by(key="shift_notes_updated_at").first()

    shift_notes = notes_setting.value if notes_setting else ""
    shift_notes_author = notes_author_setting.value if notes_author_setting else None
    shift_notes_updated = notes_updated_setting.value if notes_updated_setting else None

    # Summary metrics for handover top cards
    breached_count = sum(1 for t in open_tickets if t.sla_status == SLA_BREACHED)
    near_breach_count = sum(1 for t in open_tickets if t.sla_status == SLA_NEAR_BREACH)

    return render_template(
        "handover.html",
        open_tickets=open_tickets,
        recent_closed=recent_closed,
        shift_notes=shift_notes,
        shift_notes_author=shift_notes_author,
        shift_notes_updated=shift_notes_updated,
        breached_count=breached_count,
        near_breach_count=near_breach_count,
        clients=clients,
        selected_client_id=client_id,
        now=datetime.now(timezone.utc),
    )


@handover_bp.route("/handover/notes", methods=["POST"])
@login_required
@permission_required("view_dashboard")
def save_notes():
    notes = request.form.get("shift_notes", "").strip()
    
    def set_setting(k, v):
        s = Setting.query.filter_by(key=k).first()
        if not s:
            s = Setting(key=k, value=v)
            db.session.add(s)
        else:
            s.value = v

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    author_str = current_user.username if current_user and current_user.is_authenticated else "Operator"

    set_setting("shift_notes", notes)
    set_setting("shift_notes_author", author_str)
    set_setting("shift_notes_updated_at", now_str)

    # Record in activity log
    log = ActivityLog(
        event_type=EVENT_HANDOVER_SAVED,
        description=f"Shift handover notes updated by {author_str}",
        actor=author_str
    )
    db.session.add(log)
    db.session.commit()

    flash("Shift handover report saved.", "success")
    return redirect(url_for("handover.handover_page"))
