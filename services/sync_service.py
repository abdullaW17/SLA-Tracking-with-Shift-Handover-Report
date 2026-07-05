"""
services/sync_service.py
--------------------------
Orchestrates a full sync cycle:
  1. Fetch raw cases from DFIR-IRIS (iris_api_service)
  2. Resolve each case's client via case_customer_id → Client.iris_customer_id
  3. Normalize each one into the generic ticket shape (field_mapping_service)
  4. Upsert into the local Ticket table, storing raw_payload_json
  5. Recalculate SLA status for affected tickets (sla_calculator)
  6. Soft-delete tickets that disappeared from IRIS (Gap #8)
  7. Detect and handle reopened tickets (Gap #10)
  8. Record the run in SyncLog
"""

import json
import logging
from datetime import datetime, timezone

from extensions import db
from models import Ticket, SyncLog, Client
from services import iris_api_service
from services.field_mapping_service import get_active_field_mappings, normalize_ticket
from services.sla_calculator import apply_sla_to_ticket

logger = logging.getLogger(__name__)


def _resolve_client(raw_case):
    """Map a raw IRIS case to a Client using ``case_customer_id`` / name.

    Gap #8: returns None if no matching client is found (ticket will be
    skipped with a log warning).
    """
    customer_id = (
        raw_case.get("client_name") or
        raw_case.get("customer_name") or
        raw_case.get("case_customer_id") or
        raw_case.get("customer_id")
    )
    if customer_id is None:
        return None

    customer_id_str = str(customer_id).strip()
    return Client.query.filter_by(
        iris_customer_id=customer_id_str, is_active=True
    ).first()


def _apply_normalized_to_ticket(ticket, normalized):
    """Apply normalized field values to a Ticket model instance.

    Gap #10 (Reopened tickets): if the ticket previously had a
    ``closed_at_source`` timestamp but the new sync data no longer has one,
    the ticket has been reopened in IRIS. We clear the closed timestamp and
    force SLA re-evaluation.
    """
    # Gap #10: detect reopen
    was_closed = ticket.closed_at_source is not None
    new_closed = normalized.get("closed_at")

    ticket.title = normalized.get("title")
    ticket.status = normalized.get("status")
    ticket.severity = normalized.get("severity")
    ticket.priority = normalized.get("priority")
    ticket.criticality = normalized.get("criticality")
    ticket.assigned_to = normalized.get("assigned_to")
    if normalized.get("created_at"):
        ticket.created_at_source = normalized["created_at"]
    ticket.closed_at_source = new_closed
    ticket.last_synced_at = datetime.now(timezone.utc)

    # Gap #10: if reopened, clear SLA status to force re-evaluation
    if was_closed and new_closed is None:
        logger.info(
            "Ticket %s (client=%s) was reopened — clearing closed_at, "
            "forcing SLA re-evaluation.",
            ticket.external_id, ticket.client_id,
        )
        ticket.sla_status = None
        # Optionally reset pause tracking since the ticket is "new" again
        ticket.paused_at = None


def _soft_delete_missing_tickets(client_id, source_system, seen_external_ids):
    """Gap #8: Mark tickets that were in the DB but not in the latest IRIS
    sync response. These have presumably been deleted in IRIS.

    We use a soft-delete: set ``status = 'deleted_in_source'`` rather than
    removing the row, so historical SLA data is preserved.
    """
    if not seen_external_ids:
        return 0

    missing_tickets = Ticket.query.filter(
        Ticket.client_id == client_id,
        Ticket.source_system == source_system,
        Ticket.external_id.notin_(seen_external_ids),
        Ticket.status != "deleted_in_source",
    ).all()

    for ticket in missing_tickets:
        ticket.status = "deleted_in_source"
        logger.info(
            "Ticket %s (client=%s) not found in IRIS response — marking as "
            "deleted_in_source.",
            ticket.external_id, client_id,
        )

    return len(missing_tickets)


def sync_cases_from_iris(source_system="dfir_iris"):
    """
    Runs one full sync cycle against DFIR-IRIS. Safe to call manually
    (from a route) or on a schedule (from scheduler_service).

    Gap #1: tickets are routed to clients via case_customer_id.
    Gap #8: explicit upsert logic + soft-delete for missing tickets.
    Gap #10: reopened ticket detection.

    Returns a summary dict: {fetched, created, updated, skipped, soft_deleted, sync_log_id}
    """
    sync_log = SyncLog(sync_started_at=datetime.now(timezone.utc))
    db.session.add(sync_log)
    db.session.commit()

    try:
        raw_cases = iris_api_service.fetch_all_cases()

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Track which external_ids we saw per client for soft-delete (Gap #8)
        seen_by_client = {}  # { client_id: set(external_ids) }

        for raw_case in raw_cases:
            # Fetch full case details to get precise timestamp fields like initial_date
            try:
                case_id = raw_case.get("case_id")
                if case_id:
                    detailed = iris_api_service.fetch_case_by_id(case_id)
                    if detailed:
                        raw_case.update(detailed)
            except Exception as exc:
                logger.warning("Could not fetch detailed case %s: %s", raw_case.get("case_id"), exc)

            # Gap #1: resolve client
            client = _resolve_client(raw_case)
            if client is None:
                customer_id = raw_case.get("case_customer_id") or raw_case.get("customer_id") or raw_case.get("client_name")
                logger.warning(
                    "Skipping case (customer_id=%s): no matching Client found.",
                    customer_id,
                )
                skipped_count += 1
                continue

            # Get client-aware field mappings
            field_mappings = get_active_field_mappings(
                source_system=source_system, client_id=client.id
            )
            normalized = normalize_ticket(raw_case, field_mappings)
            external_id = normalized.get("external_id")
            if not external_id:
                # Can't upsert without a stable external identifier - skip,
                # but don't fail the whole sync over one bad record.
                skipped_count += 1
                continue

            # Track for soft-delete
            seen_by_client.setdefault(client.id, set()).add(str(external_id))

            # Gap #8: explicit upsert — does it exist → update, else → insert
            ticket = Ticket.query.filter_by(
                client_id=client.id,
                source_system=source_system,
                external_id=str(external_id),
            ).first()

            if ticket is None:
                ticket = Ticket(
                    client_id=client.id,
                    source_system=source_system,
                    external_id=str(external_id),
                )
                db.session.add(ticket)
                created_count += 1
            else:
                updated_count += 1

            _apply_normalized_to_ticket(ticket, normalized)
            ticket.raw_payload_json = json.dumps(raw_case, default=str)

            # Flush so the ticket has an id / persisted created_at_source
            # available before SLA calc reads it back.
            db.session.flush()
            apply_sla_to_ticket(ticket, commit=False)

        # Gap #8: soft-delete tickets not seen in this sync
        soft_deleted_count = 0
        for client_id, seen_ids in seen_by_client.items():
            soft_deleted_count += _soft_delete_missing_tickets(
                client_id, source_system, seen_ids
            )

        db.session.commit()

        total_fetched = len(raw_cases)
        sync_log.mark_success(
            fetched=total_fetched, created=created_count, updated=updated_count
        )
        db.session.commit()

        summary = {
            "fetched": total_fetched,
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "soft_deleted": soft_deleted_count,
            "sync_log_id": sync_log.id,
        }
        logger.info("Sync complete: %s", summary)
        return summary

    except Exception as exc:  # noqa: BLE001 - we want to log any failure and re-raise
        db.session.rollback()
        sync_log.mark_failed(exc)
        db.session.commit()
        raise
