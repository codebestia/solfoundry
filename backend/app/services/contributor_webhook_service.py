"""Outbound contributor webhook dispatch service.

Handles:
- CRUD for webhook subscriptions (max 10 per user)
- Signing payloads with HMAC-SHA256
- Dispatching events with 3-attempt exponential backoff
- Updating delivery stats on each attempt
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import aiohttp
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contributor_webhook import (
    ContributorWebhookDB,
    WebhookBatchPayload,
    WebhookDeliveryStats,
    WebhookRegisterRequest,
    WebhookResponse,
)

logger = logging.getLogger(__name__)

MAX_WEBHOOKS_PER_USER = 10
DISPATCH_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2  # delays: 2s, 4s, 8s


class WebhookLimitExceededError(Exception):
    """Raised when a user exceeds MAX_WEBHOOKS_PER_USER."""


class WebhookNotFoundError(Exception):
    """Raised when a webhook is not found or doesn't belong to the user."""


# ── helpers ────────────────────────────────────────────────────────────────────


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Return ``sha256=<hex>`` HMAC-SHA256 signature."""
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _build_single_payload(
    event: str, bounty_id: str | None, data: dict[str, Any], tx_signature: str | None = None, slot: int | None = None
) -> WebhookPayload:
    """Build a single WebhookPayload."""
    return WebhookPayload(
        event=event,
        bounty_id=bounty_id,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tx_signature=tx_signature,
        slot=slot,
        data=data,
    )


def _build_batch_payload(webhook_id: str, events: list[WebhookPayload]) -> bytes:
    """Serialise a WebhookBatchPayload to JSON bytes."""
    body = WebhookBatchPayload(
        webhook_id=webhook_id,
        batch_id=str(uuid.UUID(int=uuid.getnode())), # Placeholder for a better batch ID
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        events=events,
    )
    # Use a real UUID for batch_id
    body.batch_id = str(uuid.uuid4())
    return body.model_dump_json().encode()


# ── service ────────────────────────────────────────────────────────────────────


class ContributorWebhookService:
    """CRUD and dispatch for outbound contributor webhooks."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── registration ──────────────────────────────────────────────────────────

    async def register(
        self, user_id: str, req: WebhookRegisterRequest
    ) -> WebhookResponse:
        """Register a new webhook URL for the authenticated user."""
        count_result = await self._db.execute(
            select(func.count())
            .select_from(ContributorWebhookDB)
            .where(
                ContributorWebhookDB.user_id == UUID(user_id),
                ContributorWebhookDB.active.is_(True),
            )
        )
        count = count_result.scalar_one()
        if count >= MAX_WEBHOOKS_PER_USER:
            raise WebhookLimitExceededError(
                f"Maximum {MAX_WEBHOOKS_PER_USER} active webhooks per user"
            )

        record = ContributorWebhookDB(
            user_id=UUID(user_id),
            url=str(req.url),
            secret=req.secret,
        )
        self._db.add(record)
        await self._db.commit()
        await self._db.refresh(record)
        logger.info("Webhook registered: id=%s user=%s", record.id, user_id)
        return self._to_response(record)

    # ── unregister ────────────────────────────────────────────────────────────

    async def unregister(self, user_id: str, webhook_id: str) -> None:
        """Soft-delete a webhook (set active=False)."""
        result = await self._db.execute(
            select(ContributorWebhookDB).where(
                ContributorWebhookDB.id == UUID(webhook_id),
                ContributorWebhookDB.user_id == UUID(user_id),
                ContributorWebhookDB.active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise WebhookNotFoundError(webhook_id)
        record.active = False
        await self._db.commit()
        logger.info("Webhook unregistered: id=%s user=%s", webhook_id, user_id)

    # ── list ──────────────────────────────────────────────────────────────────

    async def list_for_user(self, user_id: str) -> list[WebhookResponse]:
        """Return all active webhooks owned by the user."""
        result = await self._db.execute(
            select(ContributorWebhookDB)
            .where(
                ContributorWebhookDB.user_id == UUID(user_id),
                ContributorWebhookDB.active.is_(True),
            )
            .order_by(ContributorWebhookDB.created_at.desc())
        )
        return [self._to_response(r) for r in result.scalars().all()]

    # ── dispatch ──────────────────────────────────────────────────────────────

    async def dispatch_event(
        self,
        event: str,
        bounty_id: str | None,
        data: dict[str, Any],
        user_id: str | None = None,
        tx_signature: str | None = None,
        slot: int | None = None,
    ) -> None:
        """Queue an event for future batched dispatch.

        If *user_id* is given, the event is only queued for that user's webhooks.
        If *user_id* is None, it's a broadcast event for all active webhooks.
        """
        from app.models.contributor_webhook import (
            WEBHOOK_EVENTS,
            OutboundWebhookQueueDB,
        )

        if event not in WEBHOOK_EVENTS:
            raise ValueError(
                f"Unsupported webhook event: {event!r}. "
                f"Must be one of: {', '.join(WEBHOOK_EVENTS)}"
            )

        payload = _build_single_payload(event, bounty_id, data, tx_signature, slot)
        record = OutboundWebhookQueueDB(
            event_type=event,
            user_id=UUID(user_id) if user_id else None,
            payload=payload.model_dump_json(),
        )
        self._db.add(record)
        await self._db.commit()
        logger.debug("Event queued for dispatch: event=%s user=%s", event, user_id)

    async def periodic_batch_dispatch(self) -> None:
        """Process the queue and dispatch batched events to active webhooks.

        Typically called every 5 seconds by a background task.
        """
        from app.models.contributor_webhook import (
            ContributorWebhookDB,
            OutboundWebhookQueueDB,
            WebhookPayload,
        )

        # 1. Fetch all unprocessed events
        result = await self._db.execute(
            select(OutboundWebhookQueueDB)
            .where(OutboundWebhookQueueDB.processed.is_(False))
            .order_by(OutboundWebhookQueueDB.created_at.asc())
        )
        queue_items = result.scalars().all()
        if not queue_items:
            return

        # 2. Mark as processed immediately to prevent double-processing
        item_ids = [item.id for item in queue_items]
        await self._db.execute(
            update(OutboundWebhookQueueDB)
            .where(OutboundWebhookQueueDB.id.in_(item_ids))
            .values(processed=True)
        )
        await self._db.commit()

        # 3. Fetch all active webhooks
        result = await self._db.execute(
            select(ContributorWebhookDB).where(ContributorWebhookDB.active.is_(True))
        )
        webhooks = result.scalars().all()

        # 4. Group events by webhook
        # For each webhook, we collect events that apply to it.
        # - If OutboundWebhookQueueDB.user_id is None, it applies to ALL webhooks.
        # - If OutboundWebhookQueueDB.user_id matches webhook.user_id, it applies.
        webhook_to_events: dict[UUID, list[WebhookPayload]] = {
            wh.id: [] for wh in webhooks
        }

        for item in queue_items:
            payload = WebhookPayload.model_validate_json(item.payload)
            target_user_id = item.user_id
            for wh in webhooks:
                if target_user_id is None or target_user_id == wh.user_id:
                    webhook_to_events[wh.id].append(payload)

        # 5. Dispatch batches
        tasks = []
        for wh in webhooks:
            events = webhook_to_events.get(wh.id, [])
            if events:
                tasks.append(self._deliver_batch(wh, events))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _deliver_batch(
        self,
        webhook: ContributorWebhookDB,
        events: list[WebhookPayload],
    ) -> None:
        """Deliver a batch of events to a single webhook."""
        from app.models.contributor_webhook import OutboundWebhookLogDB

        payload_bytes = _build_batch_payload(str(webhook.id), events)
        signature = _sign_payload(payload_bytes, webhook.secret)
        headers = {
            "Content-Type": "application/json",
            "X-SolFoundry-Signature": signature,
            "User-Agent": "SolFoundry-Webhooks/1.0",
        }

        batch_id = str(uuid.uuid4()) # We'll re-generate or pass it through
        # Re-parse to get the batch_id from the actual payload
        import json
        batch_id = json.loads(payload_bytes)["batch_id"]

        last_exc: Exception | None = None
        status = "failed"
        response_code = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook.url,
                        data=payload_bytes,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=DISPATCH_TIMEOUT_SECONDS),
                    ) as resp:
                        response_code = resp.status
                        if 200 <= resp.status < 300:
                            status = "success"
                            await self._record_delivery(webhook.id, success=True)
                            logger.info(
                                "Webhook batch delivered: id=%s batch=%s attempt=%d status=%d",
                                webhook.id,
                                batch_id,
                                attempt,
                                resp.status,
                            )
                            break
                        last_exc = RuntimeError(f"HTTP {resp.status}")
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Webhook batch delivery error: id=%s batch=%s attempt=%d error=%s",
                    webhook.id,
                    batch_id,
                    attempt,
                    exc,
                )

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_BASE_SECONDS**attempt)

        # Log completion
        if status == "failed":
            await self._record_delivery(webhook.id, success=False)

        # Record in outbound logs
        log_entry = OutboundWebhookLogDB(
            webhook_id=webhook.id,
            batch_id=batch_id,
            status=status,
            response_code=response_code,
            error_message=str(last_exc) if last_exc else None,
        )
        self._db.add(log_entry)
        await self._db.commit()

    async def get_delivery_stats(self, webhook_id: str) -> WebhookDeliveryStats:
        """Calculate delivery stats and return recent history for the dashboard."""
        from app.models.contributor_webhook import OutboundWebhookLogDB

        # Total attempted
        count_result = await self._db.execute(
            select(func.count()).select_from(OutboundWebhookLogDB).where(OutboundWebhookLogDB.webhook_id == UUID(webhook_id))
        )
        total = count_result.scalar_one()

        if total == 0:
            return WebhookDeliveryStats(
                total_deliveries=0,
                success_rate=0.0,
                failure_rate=0.0,
                last_10_deliveries=[],
            )

        # Success count
        success_result = await self._db.execute(
            select(func.count()).select_from(OutboundWebhookLogDB).where(
                OutboundWebhookLogDB.webhook_id == UUID(webhook_id),
                OutboundWebhookLogDB.status == "success"
            )
        )
        success_count = success_result.scalar_one()

        # Last 10
        history_result = await self._db.execute(
            select(OutboundWebhookLogDB)
            .where(OutboundWebhookLogDB.webhook_id == UUID(webhook_id))
            .order_by(OutboundWebhookLogDB.delivered_at.desc())
            .limit(10)
        )
        history = history_result.scalars().all()

        return WebhookDeliveryStats(
            total_deliveries=total,
            success_rate=round(success_count / total, 4),
            failure_rate=round((total - success_count) / total, 4),
            last_10_deliveries=[
                {
                    "batch_id": h.batch_id,
                    "status": h.status,
                    "response_code": h.response_code,
                    "delivered_at": h.delivered_at.isoformat(),
                    "error": h.error_message,
                }
                for h in history
            ],
        )

    async def test_webhook(self, user_id: str, webhook_id: str) -> None:
        """Send a 'test.ping' event to verify the webhook integration."""
        from app.models.contributor_webhook import ContributorWebhookDB

        result = await self._db.execute(
            select(ContributorWebhookDB).where(
                ContributorWebhookDB.id == UUID(webhook_id),
                ContributorWebhookDB.user_id == UUID(user_id)
            )
        )
        webhook = result.scalar_one_or_none()
        if not webhook:
            raise WebhookNotFoundError(webhook_id)

        payload = _build_single_payload("test.ping", None, {"message": "Verification successful!"})
        await self._deliver_batch(webhook, [payload])

    async def _record_delivery(self, webhook_id: UUID, *, success: bool) -> None:
        """Update last_delivery stats; increment failure_count on failure."""
        values: dict[str, Any] = {
            "last_delivery_at": datetime.now(timezone.utc),
            "last_delivery_status": "success" if success else "failed",
        }
        if not success:
            # Increment via SQL expression to avoid race conditions

            await self._db.execute(
                update(ContributorWebhookDB)
                .where(ContributorWebhookDB.id == webhook_id)
                .values(
                    last_delivery_at=values["last_delivery_at"],
                    last_delivery_status=values["last_delivery_status"],
                    failure_count=ContributorWebhookDB.failure_count + 1,
                )
            )
        else:
            await self._db.execute(
                update(ContributorWebhookDB)
                .where(ContributorWebhookDB.id == webhook_id)
                .values(**values)
            )
        await self._db.commit()

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_response(record: ContributorWebhookDB) -> WebhookResponse:
        return WebhookResponse(
            id=str(record.id),
            url=record.url,
            active=record.active,
            created_at=record.created_at,
            last_delivery_at=record.last_delivery_at,
            last_delivery_status=record.last_delivery_status,
            failure_count=record.failure_count,
        )


async def periodic_batch_dispatch(interval_seconds: int = 5) -> None:
    """Background task that periodically pulls events from the queue and dispatches batches."""
    from app.database import get_db_session

    while True:
        try:
            async with get_db_session() as db:
                service = ContributorWebhookService(db)
                await service.periodic_batch_dispatch()
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.error("Periodic webhook dispatch error: %s", exc)
        await asyncio.sleep(interval_seconds)
