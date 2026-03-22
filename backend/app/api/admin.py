"""Admin dashboard API — management endpoints for bounties, contributors,
reviews, financials, system health, and audit log.

Authentication: Bearer token must match the ADMIN_API_KEY environment variable.
All mutating endpoints write a structured entry to the in-process audit store
so the /audit-log endpoint can surface them immediately without a DB round-trip.

Environment variables:
  ADMIN_API_KEY     Required. The shared secret for admin access.
"""

import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.audit import audit_event
from app.services.bounty_service import _bounty_store
from app.services.contributor_service import _store as _contributor_store
from app.models.bounty import BountyStatus
from app.constants import START_TIME

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
_security = HTTPBearer(auto_error=False)

# In-process audit ring buffer (last 1 000 admin actions)
_audit_log: deque[Dict[str, Any]] = deque(maxlen=1_000)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    """Verify the caller holds a valid admin API key.

    Returns the string ``"admin"`` on success so callers can use it as an
    actor ID in audit entries.

    Raises:
        HTTPException 401: No credentials supplied.
        HTTPException 403: Credentials present but invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured on this server",
        )
    if credentials.credentials != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin credentials",
        )
    return "admin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(event: str, actor: str = "admin", **details: Any) -> None:
    """Append an entry to the in-process audit log and structlog stream."""
    entry: Dict[str, Any] = {
        "event": event,
        "actor": actor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    _audit_log.appendleft(entry)
    audit_event(event, actor=actor, **details)


def _bounty_to_dict(b: Any) -> Dict[str, Any]:
    """Serialise a BountyDB to a JSON-safe dict for admin responses."""
    return {
        "id": b.id,
        "title": b.title,
        "status": b.status,
        "tier": b.tier,
        "reward_amount": b.reward_amount,
        "created_by": b.created_by,
        "deadline": b.deadline.isoformat() if hasattr(b.deadline, "isoformat") else str(b.deadline),
        "submission_count": len(b.submissions) if b.submissions else 0,
        "created_at": b.created_at.isoformat() if hasattr(b.created_at, "isoformat") else str(b.created_at),
    }


def _contributor_to_dict(c: Any) -> Dict[str, Any]:
    """Serialise a contributor to a JSON-safe dict."""
    return {
        "id": c.id,
        "username": c.username,
        "display_name": getattr(c, "display_name", c.username),
        "tier": getattr(c, "current_tier", "T1"),
        "reputation_score": getattr(c, "reputation_score", 0.0),
        "total_bounties_completed": getattr(c, "total_bounties_completed", 0),
        "total_earnings": float(getattr(c, "total_earnings", 0)),
        "is_banned": getattr(c, "is_banned", False),
        "skills": getattr(c, "skills", []),
        "created_at": (c.created_at.isoformat()
                       if hasattr(c, "created_at") and c.created_at and hasattr(c.created_at, "isoformat")
                       else str(getattr(c, "created_at", ""))),
    }


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AdminOverview(BaseModel):
    """Aggregate platform statistics for the admin overview panel."""

    total_bounties: int
    open_bounties: int
    completed_bounties: int
    cancelled_bounties: int
    total_contributors: int
    active_contributors: int
    banned_contributors: int
    total_fndry_paid: float
    total_submissions: int
    pending_reviews: int
    uptime_seconds: int
    timestamp: str


class BountyAdminItem(BaseModel):
    id: str
    title: str
    status: str
    tier: Any
    reward_amount: float
    created_by: str
    deadline: str
    submission_count: int
    created_at: str


class BountyListAdminResponse(BaseModel):
    items: List[BountyAdminItem]
    total: int
    page: int
    per_page: int


class BountyAdminUpdate(BaseModel):
    """Fields an admin can update on a bounty."""

    status: Optional[str] = Field(None, description="New lifecycle status")
    reward_amount: Optional[float] = Field(None, gt=0, description="Adjusted reward")
    title: Optional[str] = Field(None, min_length=3, max_length=200)


class ContributorAdminItem(BaseModel):
    id: str
    username: str
    display_name: str
    tier: str
    reputation_score: float
    total_bounties_completed: int
    total_earnings: float
    is_banned: bool
    skills: List[str]
    created_at: str


class ContributorListAdminResponse(BaseModel):
    items: List[ContributorAdminItem]
    total: int
    page: int
    per_page: int


class BanRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500, description="Reason for the ban")


class ReviewPipelineItem(BaseModel):
    bounty_id: str
    bounty_title: str
    submission_id: str
    pr_url: str
    submitted_by: str
    ai_score: float
    review_complete: bool
    meets_threshold: bool
    submitted_at: str


class ReviewPipelineResponse(BaseModel):
    active: List[ReviewPipelineItem]
    total_active: int
    pass_rate: float = Field(description="Fraction of completed reviews that meet threshold")
    avg_score: float


class FinancialOverview(BaseModel):
    total_fndry_distributed: float
    total_paid_bounties: int
    pending_payout_count: int
    pending_payout_amount: float
    avg_reward: float
    highest_reward: float


class PayoutHistoryItem(BaseModel):
    bounty_id: str
    bounty_title: str
    winner: str
    amount: float
    status: str
    completed_at: Optional[str]


class PayoutHistoryResponse(BaseModel):
    items: List[PayoutHistoryItem]
    total: int


class SystemHealthResponse(BaseModel):
    status: str
    uptime_seconds: int
    timestamp: str
    services: Dict[str, str]
    queue_depth: int
    webhook_events_processed: int
    active_websocket_connections: int


class AuditLogEntry(BaseModel):
    event: str
    actor: str
    timestamp: str
    details: Dict[str, Any] = Field(default_factory=dict)


class AuditLogResponse(BaseModel):
    entries: List[AuditLogEntry]
    total: int


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=AdminOverview,
    summary="Platform overview statistics",
)
async def get_overview(_: str = Depends(require_admin)) -> AdminOverview:
    """Return aggregate statistics used by the admin overview panel."""
    bounties = list(_bounty_store.values())
    contributors = list(_contributor_store.values())

    total_fndry = sum(
        b.reward_amount for b in bounties if b.status in (BountyStatus.PAID, BountyStatus.COMPLETED)
    )
    total_submissions = sum(
        len(b.submissions) for b in bounties if b.submissions
    )
    pending_reviews = sum(
        1 for b in bounties
        for s in (b.submissions or [])
        if getattr(s, "review_complete", False) is False
        and s.status == "pending"
    )

    return AdminOverview(
        total_bounties=len(bounties),
        open_bounties=sum(1 for b in bounties if b.status == BountyStatus.OPEN),
        completed_bounties=sum(1 for b in bounties if b.status in (BountyStatus.COMPLETED, BountyStatus.PAID)),
        cancelled_bounties=sum(1 for b in bounties if b.status == BountyStatus.CANCELLED),
        total_contributors=len(contributors),
        active_contributors=sum(1 for c in contributors if not getattr(c, "is_banned", False)),
        banned_contributors=sum(1 for c in contributors if getattr(c, "is_banned", False)),
        total_fndry_paid=total_fndry,
        total_submissions=total_submissions,
        pending_reviews=pending_reviews,
        uptime_seconds=round(time.monotonic() - START_TIME),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Bounty management
# ---------------------------------------------------------------------------


@router.get(
    "/bounties",
    response_model=BountyListAdminResponse,
    summary="List all bounties with admin-level detail",
)
async def list_bounties_admin(
    search: Optional[str] = Query(None, description="Filter by title substring"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    tier: Optional[int] = Query(None, description="Filter by tier (1, 2, 3)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _: str = Depends(require_admin),
) -> BountyListAdminResponse:
    """Return paginated bounty list with optional search and status filter."""
    items = list(_bounty_store.values())

    if search:
        q = search.lower()
        items = [b for b in items if q in b.title.lower() or q in getattr(b, "description", "").lower()]
    if status_filter:
        items = [b for b in items if b.status == status_filter]
    if tier is not None:
        items = [b for b in items if b.tier == tier]

    # Sort newest first
    items.sort(key=lambda b: getattr(b, "created_at", datetime.min), reverse=True)

    total = len(items)
    offset = (page - 1) * per_page
    page_items = items[offset: offset + per_page]

    return BountyListAdminResponse(
        items=[BountyAdminItem(**_bounty_to_dict(b)) for b in page_items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.patch(
    "/bounties/{bounty_id}",
    summary="Update a bounty (status, reward, title)",
)
async def update_bounty_admin(
    bounty_id: str,
    update: BountyAdminUpdate,
    actor: str = Depends(require_admin),
) -> Dict[str, Any]:
    """Allow an admin to patch a bounty's status, reward, or title."""
    bounty = _bounty_store.get(bounty_id)
    if not bounty:
        raise HTTPException(status_code=404, detail=f"Bounty {bounty_id!r} not found")

    changes: Dict[str, Any] = {}

    if update.status is not None:
        bounty.status = update.status
        changes["status"] = update.status

    if update.reward_amount is not None:
        old_reward = bounty.reward_amount
        bounty.reward_amount = update.reward_amount
        changes["reward_amount"] = {"from": old_reward, "to": update.reward_amount}

    if update.title is not None:
        bounty.title = update.title
        changes["title"] = update.title

    if not changes:
        raise HTTPException(status_code=400, detail="No changes provided")

    _log("admin_bounty_updated", actor=actor, bounty_id=bounty_id, changes=changes)
    return {"ok": True, "bounty_id": bounty_id, "changes": changes}


@router.post(
    "/bounties/{bounty_id}/close",
    summary="Force-close a bounty",
)
async def close_bounty_admin(
    bounty_id: str,
    actor: str = Depends(require_admin),
) -> Dict[str, str]:
    """Set a bounty to CANCELLED regardless of its current lifecycle state."""
    bounty = _bounty_store.get(bounty_id)
    if not bounty:
        raise HTTPException(status_code=404, detail=f"Bounty {bounty_id!r} not found")

    old_status = bounty.status
    bounty.status = BountyStatus.CANCELLED
    _log("admin_bounty_closed", actor=actor, bounty_id=bounty_id, previous_status=str(old_status))
    return {"ok": "true", "bounty_id": bounty_id, "status": BountyStatus.CANCELLED}


# ---------------------------------------------------------------------------
# Contributor management
# ---------------------------------------------------------------------------


@router.get(
    "/contributors",
    response_model=ContributorListAdminResponse,
    summary="List all contributors",
)
async def list_contributors_admin(
    search: Optional[str] = Query(None, description="Filter by username"),
    is_banned: Optional[bool] = Query(None, description="Filter by ban status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _: str = Depends(require_admin),
) -> ContributorListAdminResponse:
    """Return paginated contributors with admin-level fields."""
    items = list(_contributor_store.values())

    if search:
        q = search.lower()
        items = [c for c in items if q in c.username.lower()]
    if is_banned is not None:
        items = [c for c in items if getattr(c, "is_banned", False) == is_banned]

    items.sort(key=lambda c: getattr(c, "reputation_score", 0.0), reverse=True)

    total = len(items)
    offset = (page - 1) * per_page
    page_items = items[offset: offset + per_page]

    return ContributorListAdminResponse(
        items=[ContributorAdminItem(**_contributor_to_dict(c)) for c in page_items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/contributors/{contributor_id}/ban",
    summary="Ban a contributor",
)
async def ban_contributor(
    contributor_id: str,
    body: BanRequest,
    actor: str = Depends(require_admin),
) -> Dict[str, str]:
    """Set `is_banned = True` on a contributor profile."""
    contributor = _contributor_store.get(contributor_id)
    if not contributor:
        raise HTTPException(status_code=404, detail=f"Contributor {contributor_id!r} not found")

    contributor.is_banned = True
    _log(
        "admin_contributor_banned",
        actor=actor,
        contributor_id=contributor_id,
        username=contributor.username,
        reason=body.reason,
    )
    return {"ok": "true", "contributor_id": contributor_id, "action": "banned"}


@router.post(
    "/contributors/{contributor_id}/unban",
    summary="Unban a contributor",
)
async def unban_contributor(
    contributor_id: str,
    actor: str = Depends(require_admin),
) -> Dict[str, str]:
    """Clear the `is_banned` flag on a contributor profile."""
    contributor = _contributor_store.get(contributor_id)
    if not contributor:
        raise HTTPException(status_code=404, detail=f"Contributor {contributor_id!r} not found")

    contributor.is_banned = False
    _log(
        "admin_contributor_unbanned",
        actor=actor,
        contributor_id=contributor_id,
        username=contributor.username,
    )
    return {"ok": "true", "contributor_id": contributor_id, "action": "unbanned"}


# ---------------------------------------------------------------------------
# Review pipeline
# ---------------------------------------------------------------------------


@router.get(
    "/reviews/pipeline",
    response_model=ReviewPipelineResponse,
    summary="Review pipeline — active and aggregate metrics",
)
async def get_review_pipeline(_: str = Depends(require_admin)) -> ReviewPipelineResponse:
    """Return active (incomplete) reviews with pass-rate and average score."""
    active: List[ReviewPipelineItem] = []
    completed_count = 0
    passing_count = 0
    score_sum = 0.0

    for bounty in _bounty_store.values():
        for sub in (bounty.submissions or []):
            ai_score = getattr(sub, "ai_score", 0.0) or 0.0
            review_complete = getattr(sub, "review_complete", False)
            meets = getattr(sub, "meets_threshold", False)

            if review_complete:
                completed_count += 1
                score_sum += ai_score
                if meets:
                    passing_count += 1
            else:
                active.append(ReviewPipelineItem(
                    bounty_id=bounty.id,
                    bounty_title=bounty.title,
                    submission_id=str(getattr(sub, "id", "")),
                    pr_url=getattr(sub, "pr_url", ""),
                    submitted_by=getattr(sub, "submitted_by", ""),
                    ai_score=ai_score,
                    review_complete=review_complete,
                    meets_threshold=meets,
                    submitted_at=(
                        sub.submitted_at.isoformat()
                        if hasattr(sub, "submitted_at") and hasattr(sub.submitted_at, "isoformat")
                        else str(getattr(sub, "submitted_at", ""))
                    ),
                ))

    pass_rate = (passing_count / completed_count) if completed_count else 0.0
    avg_score = (score_sum / completed_count) if completed_count else 0.0

    return ReviewPipelineResponse(
        active=active,
        total_active=len(active),
        pass_rate=round(pass_rate, 4),
        avg_score=round(avg_score, 2),
    )


# ---------------------------------------------------------------------------
# Financial overview
# ---------------------------------------------------------------------------


@router.get(
    "/financial/overview",
    response_model=FinancialOverview,
    summary="Token distribution and payout summary",
)
async def get_financial_overview(_: str = Depends(require_admin)) -> FinancialOverview:
    """Return aggregate financial metrics across all bounties."""
    bounties = list(_bounty_store.values())
    paid = [b for b in bounties if b.status in (BountyStatus.PAID, BountyStatus.COMPLETED)]
    pending = [b for b in bounties if b.status in (BountyStatus.UNDER_REVIEW, BountyStatus.COMPLETED)]

    total_distributed = sum(b.reward_amount for b in paid)
    rewards = [b.reward_amount for b in bounties if b.reward_amount]
    avg_reward = (sum(rewards) / len(rewards)) if rewards else 0.0
    highest = max(rewards) if rewards else 0.0
    pending_amount = sum(b.reward_amount for b in pending)

    return FinancialOverview(
        total_fndry_distributed=total_distributed,
        total_paid_bounties=len(paid),
        pending_payout_count=len(pending),
        pending_payout_amount=pending_amount,
        avg_reward=round(avg_reward, 2),
        highest_reward=highest,
    )


@router.get(
    "/financial/payouts",
    response_model=PayoutHistoryResponse,
    summary="Payout history",
)
async def get_payout_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _: str = Depends(require_admin),
) -> PayoutHistoryResponse:
    """Return bounties that have completed payouts, newest first."""
    paid_bounties = [
        b for b in _bounty_store.values()
        if b.status in (BountyStatus.PAID, BountyStatus.COMPLETED)
    ]
    paid_bounties.sort(
        key=lambda b: getattr(b, "created_at", datetime.min), reverse=True
    )

    total = len(paid_bounties)
    offset = (page - 1) * per_page
    page_items = paid_bounties[offset: offset + per_page]

    items = [
        PayoutHistoryItem(
            bounty_id=b.id,
            bounty_title=b.title,
            winner=getattr(b, "winner_wallet", "") or getattr(b, "created_by", ""),
            amount=b.reward_amount,
            status=b.status,
            completed_at=(
                b.created_at.isoformat()
                if hasattr(b.created_at, "isoformat") else str(b.created_at)
            ),
        )
        for b in page_items
    ]

    return PayoutHistoryResponse(items=items, total=total)


# ---------------------------------------------------------------------------
# System health (enhanced)
# ---------------------------------------------------------------------------


@router.get(
    "/system/health",
    response_model=SystemHealthResponse,
    summary="Enhanced system health for admin dashboard",
)
async def get_system_health_admin(_: str = Depends(require_admin)) -> SystemHealthResponse:
    """Return service status, uptime, queue depth, and WS connections."""
    from app.database import engine
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    import os as _os
    from redis.asyncio import from_url as redis_from_url, RedisError

    # DB probe
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except (SQLAlchemyError, Exception):
        db_status = "disconnected"

    # Redis probe
    try:
        redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis_from_url(redis_url, decode_responses=True)
        async with client:
            await client.ping()
        redis_status = "connected"
    except (RedisError, Exception):
        redis_status = "disconnected"

    # WebSocket connection count
    try:
        from app.services.websocket_manager import manager as ws_manager
        ws_count = len(getattr(ws_manager, "active_connections", {}))
    except Exception:
        ws_count = 0

    # Review queue depth (pending reviews)
    pending_reviews = sum(
        1 for b in _bounty_store.values()
        for s in (b.submissions or [])
        if not getattr(s, "review_complete", False) and s.status == "pending"
    )

    return SystemHealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        uptime_seconds=round(time.monotonic() - START_TIME),
        timestamp=datetime.now(timezone.utc).isoformat(),
        services={"database": db_status, "redis": redis_status},
        queue_depth=pending_reviews,
        webhook_events_processed=len(_audit_log),
        active_websocket_connections=ws_count,
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get(
    "/audit-log",
    response_model=AuditLogResponse,
    summary="Admin action audit log",
)
async def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    event_filter: Optional[str] = Query(None, alias="event", description="Filter by event name"),
    _: str = Depends(require_admin),
) -> AuditLogResponse:
    """Return recent admin audit log entries, newest first."""
    entries = list(_audit_log)

    if event_filter:
        entries = [e for e in entries if event_filter in e.get("event", "")]

    total = len(entries)
    entries = entries[:limit]

    return AuditLogResponse(
        entries=[
            AuditLogEntry(
                event=e.get("event", ""),
                actor=e.get("actor", "admin"),
                timestamp=e.get("timestamp", ""),
                details={k: v for k, v in e.items() if k not in ("event", "actor", "timestamp")},
            )
            for e in entries
        ],
        total=total,
    )
