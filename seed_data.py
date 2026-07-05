"""
seed_data.py
------------
One-shot script to initialize the database with:
  - Tables (db.create_all())
  - Sample clients (Gap #1: multi-tenancy)
  - Default users (Admin/Manager/Viewer) with hashed passwords
  - Default DFIR-IRIS field mappings
  - Sample SLA rules scoped to clients (demonstrates different taxonomies)
  - Dummy tickets assigned to clients, exercising every SLA status

Run:
    python seed_data.py
"""

from datetime import datetime, timedelta, timezone

from app import create_app
from extensions import db
from models import User, SLARule, FieldMapping, Ticket, Client
from services.field_mapping_service import seed_default_iris_mappings
from services.sla_calculator import apply_sla_to_ticket

app = create_app()


def seed_clients():
    """Create sample clients for multi-tenant demo."""
    clients_data = [
        ("Acme Corp", "CUST001", "America/New_York"),
        ("Globex Industries", "CUST002", "Europe/London"),
        ("Initech", "CUST003", "Asia/Tokyo"),
    ]
    created = 0
    for name, iris_id, tz in clients_data:
        if Client.query.filter_by(name=name).first():
            continue
        client = Client(name=name, iris_customer_id=iris_id, timezone=tz)
        db.session.add(client)
        created += 1
    db.session.commit()
    print(f"Seeded {created} client(s): Acme Corp, Globex Industries, Initech.")
    return Client.query.all()


def seed_users():
    users = [
        ("admin", "admin@example.com", "Admin123!", "Admin"),
        ("manager", "manager@example.com", "Manager123!", "Manager"),
        ("viewer", "viewer@example.com", "Viewer123!", "Viewer"),
    ]
    for username, email, password, role in users:
        if User.query.filter_by(username=username).first():
            continue
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
    db.session.commit()
    print("Seeded users: admin/Admin123! , manager/Manager123! , viewer/Viewer123!")


def seed_sla_rules(clients):
    if SLARule.query.first():
        print("SLA rules already exist - skipping.")
        return

    acme = next((c for c in clients if c.name == "Acme Corp"), clients[0])
    globex = next((c for c in clients if c.name == "Globex Industries"), clients[1] if len(clients) > 1 else clients[0])
    initech = next((c for c in clients if c.name == "Initech"), clients[2] if len(clients) > 2 else clients[0])

    rules = [
        # --- Acme Corp: Severity-based taxonomy ---
        SLARule(client_id=acme.id, rule_name="Critical Severity SLA", field_name="severity",
                field_value="Critical", priority=10,
                response_sla_minutes=60, resolution_sla_minutes=480,
                warning_threshold_percent=80, stop_status="closed,resolved",
                pause_status="awaiting_client,on_hold"),
        SLARule(client_id=acme.id, rule_name="High Severity SLA", field_name="severity",
                field_value="High", priority=20,
                response_sla_minutes=120, resolution_sla_minutes=960,
                warning_threshold_percent=80, stop_status="closed,resolved",
                pause_status="awaiting_client,on_hold"),
        SLARule(client_id=acme.id, rule_name="Medium Severity SLA", field_name="severity",
                field_value="Medium", priority=30,
                response_sla_minutes=240, resolution_sla_minutes=2880,
                warning_threshold_percent=85, stop_status="closed,resolved"),
        SLARule(client_id=acme.id, rule_name="Low Severity SLA", field_name="severity",
                field_value="Low", priority=40,
                response_sla_minutes=480, resolution_sla_minutes=7200,
                warning_threshold_percent=90, stop_status="closed,resolved"),

        # --- Globex Industries: Priority-based taxonomy (P1-P4) ---
        SLARule(client_id=globex.id, rule_name="P1 Priority SLA", field_name="priority",
                field_value="P1", priority=10,
                response_sla_minutes=30, resolution_sla_minutes=240,
                warning_threshold_percent=75, stop_status="closed",
                business_hours_only=True),
        SLARule(client_id=globex.id, rule_name="P2 Priority SLA", field_name="priority",
                field_value="P2", priority=20,
                response_sla_minutes=60, resolution_sla_minutes=480,
                warning_threshold_percent=80, stop_status="closed",
                business_hours_only=True),

        # --- Initech: Criticality-based taxonomy (Sev1-Sev2) ---
        SLARule(client_id=initech.id, rule_name="Sev1 Criticality SLA", field_name="criticality",
                field_value="Sev1", priority=10,
                response_sla_minutes=45, resolution_sla_minutes=360,
                warning_threshold_percent=80, stop_status="closed"),
    ]
    db.session.add_all(rules)
    db.session.commit()
    print(f"Seeded {len(rules)} SLA rule(s) across 3 clients with different taxonomies.")


def seed_dummy_tickets(clients):
    if Ticket.query.first():
        print("Tickets already exist - skipping.")
        return

    acme = next((c for c in clients if c.name == "Acme Corp"), clients[0])
    globex = next((c for c in clients if c.name == "Globex Industries"), clients[1] if len(clients) > 1 else clients[0])
    initech = next((c for c in clients if c.name == "Initech"), clients[2] if len(clients) > 2 else clients[0])

    now = datetime.now(timezone.utc)

    dummy = [
        # (client, external_id, title, status, severity, priority, criticality, assigned_to, created_offset_hrs, closed_offset_hrs)
        (acme, "CASE-1001", "Suspicious PowerShell execution on DC01", "open", "Critical", None, None, "alice", -2, None),
        (acme, "CASE-1002", "Phishing email reported by finance team", "open", "High", None, None, "bob", -20, None),
        (acme, "CASE-1003", "Malware alert on endpoint WKS-114", "closed", "Critical", None, None, "alice", -30, -25),
        (acme, "CASE-1004", "Firewall rule change - unauthorized", "open", "Medium", None, None, "carol", -70, None),
        (acme, "CASE-1005", "Data exfiltration attempt blocked by DLP", "closed", "High", None, None, "bob", -50, -12),
        (globex, "CASE-1006", "Brute force login attempts on VPN", "open", None, "P1", None, "dave", -6, None),
        (globex, "CASE-1007", "Ransomware indicator detected", "open", None, "P1", None, "alice", -1, None),
        (globex, "CASE-1008", "Unusual outbound traffic to known bad IP", "closed", None, "P2", None, "carol", -14, -9),
        (initech, "CASE-1009", "Insider threat - unusual file access pattern", "open", None, None, "Sev1", "dave", -3, None),
        (acme, "CASE-1010", "Low priority policy violation", "open", "Low", None, None, "bob", -100, None),
        (acme, "CASE-1011", "Unclassified alert - no taxonomy field set", "open", None, None, None, "carol", -5, None),
    ]

    tickets = []
    for client, external_id, title, status, severity, priority, criticality, assigned_to, created_h, closed_h in dummy:
        t = Ticket(
            client_id=client.id,
            external_id=external_id,
            source_system="dfir_iris",
            title=title,
            status=status,
            severity=severity,
            priority=priority,
            criticality=criticality,
            assigned_to=assigned_to,
            created_at_source=now + timedelta(hours=created_h),
            closed_at_source=(now + timedelta(hours=closed_h)) if closed_h is not None else None,
            last_synced_at=now,
        )
        db.session.add(t)
        tickets.append(t)

    db.session.flush()
    for t in tickets:
        apply_sla_to_ticket(t, commit=False)
    db.session.commit()
    print(f"Seeded {len(tickets)} dummy ticket(s) across 3 clients with calculated SLA status.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        clients = seed_clients()
        seed_users()
        seed_default_iris_mappings()
        seed_sla_rules(clients)
        seed_dummy_tickets(clients)
        print("\nDatabase initialized and seeded successfully.")
