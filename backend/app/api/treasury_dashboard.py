"""Treasury Dashboard API — admin-only read-only endpoints.

Provides aggregate treasury health data: balances, burn rate, runway,
inflow/outflow time series, recent transactions, and tier spending breakdown.
All endpoints require Bearer ADMIN_API_KEY authentication.
No write operations are exposed — this is a read-only dashboard.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.tables import PayoutTable, BuybackTable
from app.services.treasury_service import get_treasury_stats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/treasury-dashboard", tags=["treasury-dashboard"])

_ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
_security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    if not _ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")
    if credentials.credentials != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")
    return credentials.credentials


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TreasuryOverview(BaseModel):
    fndry_balance: float
    sol_balance: float
    total_paid_out_fndry: float
    total_paid_out_sol: float
    total_payouts: int
    total_buybacks: int
    burn_rate_daily: float       # avg FNDRY paid out per day (last 30 days)
    burn_rate_weekly: float
    burn_rate_monthly: float
    runway_days: float | None    # fndry_balance / burn_rate_daily; None if no burn
    last_updated: str


class FlowPoint(BaseModel):
    date: str          # ISO date string (day/week/month bucket)
    inflow: float      # FNDRY entering treasury (buybacks)
    outflow: float     # FNDRY leaving treasury (confirmed payouts)
    net: float         # inflow - outflow


class FlowResponse(BaseModel):
    view: str          # daily | weekly | monthly
    points: list[FlowPoint]


class TreasuryTransaction(BaseModel):
    id: str
    type: str          # payout | buyback
    amount: float
    token: str
    recipient: Optional[str]
    tx_hash: Optional[str]
    solscan_url: Optional[str]
    status: Optional[str]
    created_at: str


class TransactionsResponse(BaseModel):
    items: list[TreasuryTransaction]
    total: int


class TierSpend(BaseModel):
    tier: str
    total_fndry: float
    payout_count: int
    pct_of_total: float


class SpendingBreakdownResponse(BaseModel):
    tiers: list[TierSpend]
    total_fndry: float
    period_days: int


# ---------------------------------------------------------------------------
# Helper — date truncation SQL by view
# ---------------------------------------------------------------------------

_TRUNC: dict[str, str] = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
}


async def _get_flow_series(
    session: AsyncSession, view: str, since: datetime
) -> list[FlowPoint]:
    trunc = _TRUNC.get(view, "day")

    # Outflows: confirmed FNDRY payouts grouped by date bucket
    outflow_q = await session.execute(
        text(
            f"""
            SELECT date_trunc('{trunc}', created_at) AS bucket,
                   COALESCE(SUM(amount), 0)           AS total
            FROM payouts
            WHERE status = 'confirmed'
              AND token  = 'FNDRY'
              AND created_at >= :since
            GROUP BY bucket
            ORDER BY bucket
            """
        ),
        {"since": since},
    )
    outflow_rows = {str(row.bucket.date()): float(row.total) for row in outflow_q}

    # Inflows: buybacks (FNDRY acquired) grouped by date bucket
    inflow_q = await session.execute(
        text(
            f"""
            SELECT date_trunc('{trunc}', created_at) AS bucket,
                   COALESCE(SUM(amount_fndry), 0)    AS total
            FROM buybacks
            WHERE created_at >= :since
            GROUP BY bucket
            ORDER BY bucket
            """
        ),
        {"since": since},
    )
    inflow_rows = {str(row.bucket.date()): float(row.total) for row in inflow_q}

    # Merge by date key
    all_dates = sorted(set(outflow_rows) | set(inflow_rows))
    return [
        FlowPoint(
            date=d,
            inflow=inflow_rows.get(d, 0.0),
            outflow=outflow_rows.get(d, 0.0),
            net=inflow_rows.get(d, 0.0) - outflow_rows.get(d, 0.0),
        )
        for d in all_dates
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=TreasuryOverview)
async def get_overview(_: str = Depends(require_admin)):
    """Treasury balance + burn rate + estimated runway."""
    stats = await get_treasury_stats()
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)

    async with get_db_session() as session:
        result = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM payouts
                WHERE status = 'confirmed'
                  AND token  = 'FNDRY'
                  AND created_at >= :since
                """
            ),
            {"since": since_30d},
        )
        burned_30d = float(result.scalar_one() or 0)

    burn_daily = burned_30d / 30.0
    burn_weekly = burn_daily * 7
    burn_monthly = burn_daily * 30

    runway = (stats.fndry_balance / burn_daily) if burn_daily > 0 else None

    return TreasuryOverview(
        fndry_balance=stats.fndry_balance,
        sol_balance=stats.sol_balance,
        total_paid_out_fndry=stats.total_paid_out_fndry,
        total_paid_out_sol=stats.total_paid_out_sol,
        total_payouts=stats.total_payouts,
        total_buybacks=stats.total_buybacks,
        burn_rate_daily=round(burn_daily, 4),
        burn_rate_weekly=round(burn_weekly, 4),
        burn_rate_monthly=round(burn_monthly, 4),
        runway_days=round(runway, 1) if runway is not None else None,
        last_updated=now.isoformat(),
    )


@router.get("/flow", response_model=FlowResponse)
async def get_flow(
    view: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    _: str = Depends(require_admin),
):
    """Inflow/outflow time series. view: daily (30d), weekly (12w), monthly (12m)."""
    now = datetime.now(timezone.utc)
    lookback = {"daily": timedelta(days=30), "weekly": timedelta(weeks=12), "monthly": timedelta(days=365)}
    since = now - lookback[view]

    async with get_db_session() as session:
        points = await _get_flow_series(session, view, since)

    return FlowResponse(view=view, points=points)


@router.get("/transactions", response_model=TransactionsResponse)
async def get_transactions(
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(require_admin),
):
    """Recent treasury transactions (payouts + buybacks) sorted newest first."""
    async with get_db_session() as session:
        count_result = await session.execute(
            text("SELECT COUNT(*) FROM payouts UNION ALL SELECT COUNT(*) FROM buybacks")
        )
        # rough total for pagination display
        rows_count = list(count_result.fetchall())
        total = sum(int(r[0]) for r in rows_count)

        payouts_q = await session.execute(
            select(PayoutTable)
            .order_by(PayoutTable.created_at.desc())
            .limit(limit)
        )
        payout_rows = payouts_q.scalars().all()

        buybacks_q = await session.execute(
            select(BuybackTable)
            .order_by(BuybackTable.created_at.desc())
            .limit(limit)
        )
        buyback_rows = buybacks_q.scalars().all()

    items: list[TreasuryTransaction] = []
    for p in payout_rows:
        items.append(
            TreasuryTransaction(
                id=str(p.id),
                type="payout",
                amount=float(p.amount or 0),
                token=p.token or "FNDRY",
                recipient=p.recipient,
                tx_hash=p.tx_hash,
                solscan_url=p.solscan_url,
                status=p.status,
                created_at=p.created_at.isoformat() if p.created_at else "",
            )
        )
    for b in buyback_rows:
        items.append(
            TreasuryTransaction(
                id=str(b.id),
                type="buyback",
                amount=float(b.amount_fndry or 0),
                token="FNDRY",
                recipient=None,
                tx_hash=b.tx_hash,
                solscan_url=b.solscan_url,
                status="confirmed",
                created_at=b.created_at.isoformat() if b.created_at else "",
            )
        )

    items.sort(key=lambda x: x.created_at, reverse=True)
    return TransactionsResponse(items=items[:limit], total=total)


@router.get("/spending/tier", response_model=SpendingBreakdownResponse)
async def get_spending_by_tier(
    period_days: int = Query(30, ge=1, le=365),
    _: str = Depends(require_admin),
):
    """FNDRY spending breakdown by bounty tier (T1/T2/T3 + unlinked)."""
    since = datetime.now(timezone.utc) - timedelta(days=period_days)

    async with get_db_session() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    COALESCE(b.tier::text, 'unlinked') AS tier,
                    COALESCE(SUM(p.amount), 0)         AS total_fndry,
                    COUNT(p.id)                        AS payout_count
                FROM payouts p
                LEFT JOIN bounties b ON b.id = p.bounty_id
                WHERE p.status    = 'confirmed'
                  AND p.token     = 'FNDRY'
                  AND p.created_at >= :since
                GROUP BY tier
                ORDER BY total_fndry DESC
                """
            ),
            {"since": since},
        )
        rows = result.fetchall()

    total = sum(float(r.total_fndry) for r in rows)
    tiers = [
        TierSpend(
            tier=str(r.tier),
            total_fndry=float(r.total_fndry),
            payout_count=int(r.payout_count),
            pct_of_total=round(float(r.total_fndry) / total * 100, 1) if total > 0 else 0.0,
        )
        for r in rows
    ]
    return SpendingBreakdownResponse(tiers=tiers, total_fndry=total, period_days=period_days)


@router.get("/export.csv")
async def export_csv(_: str = Depends(require_admin)):
    """Download all treasury transactions as a CSV file."""
    async with get_db_session() as session:
        payouts_q = await session.execute(
            select(PayoutTable).order_by(PayoutTable.created_at.desc())
        )
        payout_rows = payouts_q.scalars().all()

        buybacks_q = await session.execute(
            select(BuybackTable).order_by(BuybackTable.created_at.desc())
        )
        buyback_rows = buybacks_q.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "type", "amount", "token", "recipient", "tx_hash", "status", "created_at"])

    for p in payout_rows:
        writer.writerow([
            str(p.id), "payout", float(p.amount or 0), p.token or "FNDRY",
            p.recipient or "", p.tx_hash or "", p.status or "",
            p.created_at.isoformat() if p.created_at else "",
        ])
    for b in buyback_rows:
        writer.writerow([
            str(b.id), "buyback", float(b.amount_fndry or 0), "FNDRY",
            "", b.tx_hash or "", "confirmed",
            b.created_at.isoformat() if b.created_at else "",
        ])

    buf.seek(0)
    filename = f"treasury_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
