"""Contributor webhook subscription — database and Pydantic models.

Outbound webhooks let contributors receive HTTP POST notifications when
bounty-related events happen (bounty claimed, review started/passed/failed,
bounty paid).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

# ── event types ────────────────────────────────────────────────────────────────

WEBHOOK_EVENTS = (
    "bounty.claimed",
    "review.started",
    "review.passed",
    "review.failed",
    "bounty.paid",
    # ── on-chain events ──
    "escrow.locked",
    "escrow.released",
    "reputation.updated",
    "stake.deposited",
    "stake.withdrawn",
)


class WebhookEvent(str, Enum):
    """Supported outbound webhook event types."""

    BOUNTY_CLAIMED = "bounty.claimed"
    REVIEW_STARTED = "review.started"
    REVIEW_PASSED = "review.passed"
    REVIEW_FAILED = "review.failed"
    BOUNTY_PAID = "bounty.paid"
    # ── on-chain events ──
    ESCROW_LOCKED = "escrow.locked"
    ESCROW_RELEASED = "escrow.released"
    REPUTATION_UPDATED = "reputation.updated"
    STAKE_DEPOSITED = "stake.deposited"
    STAKE_WITHDRAWN = "stake.withdrawn"


# ── SQLAlchemy model ───────────────────────────────────────────────────────────


class ContributorWebhookDB(Base):
    """Outbound webhook subscription registered by a contributor."""

    __tablename__ = "contributor_webhooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    url = Column(Text, nullable=False)
    # HMAC-SHA256 secret supplied by the contributor at registration time.
    # Stored as plaintext (contributor's choice); used to sign outgoing payloads.
    secret = Column(String(256), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Delivery stats (updated on each dispatch attempt)
    last_delivery_at = Column(DateTime(timezone=True), nullable=True)
    last_delivery_status = Column(String(20), nullable=True)  # success | failed
    failure_count = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_contributor_webhooks_user_id", "user_id"),
        Index("ix_contributor_webhooks_active", "active"),
    )


class OutboundWebhookQueueDB(Base):
    """Temporary storage for events before they are batched and dispatched."""

    __tablename__ = "outbound_webhook_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(50), nullable=False)
    # The subscriber user_id that should receive this event.
    # If None, it targets all active webhooks (broadcast).
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    payload = Column(Text, nullable=False)  # JSON serialized WebhookPayload
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    processed = Column(Boolean, default=False, nullable=False, index=True)


class OutboundWebhookLogDB(Base):
    """History of all outbound webhook delivery attempts."""

    __tablename__ = "outbound_webhook_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    webhook_id = Column(
        UUID(as_uuid=True),
        sa.ForeignKey("contributor_webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # success | failed
    response_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    delivered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class WebhookRegisterRequest(BaseModel):
    """Request body for POST /api/webhooks/register."""

    url: AnyHttpUrl = Field(..., description="HTTPS URL that will receive POST events")
    secret: str = Field(
        ...,
        min_length=16,
        max_length=256,
        description="Secret used to sign the HMAC-SHA256 payload signature",
    )

    @field_validator("url")
    @classmethod
    def must_be_https(cls, v: AnyHttpUrl) -> AnyHttpUrl:
        if str(v).startswith("http://"):
            raise ValueError("Webhook URL must use HTTPS")
        return v


class WebhookResponse(BaseModel):
    """Webhook subscription representation returned to callers."""

    id: str
    url: str
    active: bool
    created_at: datetime
    last_delivery_at: Optional[datetime] = None
    last_delivery_status: Optional[str] = None
    failure_count: int

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    """Paginated list of webhook subscriptions."""

    items: list[WebhookResponse]
    total: int


class WebhookPayload(BaseModel):
    """Shape of the JSON body for a single event."""

    event: str
    bounty_id: Optional[str] = None
    timestamp: str
    # on-chain metadata
    tx_signature: Optional[str] = None
    slot: Optional[int] = None
    data: dict[str, Any]


class WebhookBatchPayload(BaseModel):
    """Payload for batched webhook delivery."""

    webhook_id: str
    batch_id: str
    timestamp: str
    events: list[WebhookPayload]


class WebhookDeliveryStats(BaseModel):
    """Detailed stats for a specific webhook."""

    total_deliveries: int
    success_rate: float
    failure_rate: float
    last_10_deliveries: list[dict[str, Any]]
