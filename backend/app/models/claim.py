"""Claim lifecycle models for T2/T3 bounty claiming (Issue #16).

T1 bounties are open-contribution (no claiming).
T2: direct claim, 7-day deadline, reputation ≥ 10.
T3: application + admin approval, 14-day deadline, reputation ≥ 50.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

T2_MIN_REPUTATION = 10
T3_MIN_REPUTATION = 50
T2_DEADLINE_DAYS = 7
T3_DEADLINE_DAYS = 14


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ClaimStatus(str, Enum):
    """Lifecycle status of a claim."""
    PENDING_APPROVAL = "pending_approval"  # T3 only: awaiting admin approval
    ACTIVE = "active"                      # Claim is active, deadline running
    COMPLETED = "completed"                # Work was completed successfully
    EXPIRED = "expired"                    # Deadline passed, auto-released
    RELEASED = "released"                  # Voluntarily released by claimer


# ---------------------------------------------------------------------------
# Internal storage model
# ---------------------------------------------------------------------------

class ClaimRecord(BaseModel):
    """Internal in-memory storage representation of a claim."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bounty_id: str
    claimed_by: str  # username
    status: ClaimStatus = ClaimStatus.ACTIVE
    application_plan: Optional[str] = None  # T3 only
    deadline: Optional[datetime] = None
    claimed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None  # when released/completed/expired
    outcome: Optional[str] = None  # "completed", "released", "expired"


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ClaimCreate(BaseModel):
    """Payload for POST /bounties/{id}/claim."""
    application_plan: Optional[str] = Field(
        None,
        max_length=5000,
        description="Required for T3 bounties: describe your approach and timeline.",
    )


class ClaimResponse(BaseModel):
    """API response for a single claim."""
    id: str
    bounty_id: str
    claimed_by: str
    status: ClaimStatus
    application_plan: Optional[str] = None
    deadline: Optional[datetime] = None
    claimed_at: datetime
    resolved_at: Optional[datetime] = None
    outcome: Optional[str] = None


class ClaimHistoryResponse(BaseModel):
    """List of all claims for a bounty."""
    bounty_id: str
    claims: list[ClaimResponse]
    total: int
