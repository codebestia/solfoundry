"""Dispute database and Pydantic models for the SolFoundry platform."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, String, DateTime, JSON, Text, ForeignKey, Index, Float, Numeric
from app.database import Base, GUID


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DisputeStatus(str, Enum):
    """Lifecycle status of a dispute."""
    OPENED = "opened"
    EVIDENCE = "evidence"
    MEDIATION = "mediation"
    RESOLVED = "resolved"


class DisputeResolution(str, Enum):
    """Outcome of a dispute resolution."""
    PAYOUT = "payout"     # Released to contributor
    REFUND = "refund"     # Refunded to creator
    SPLIT = "split"       # Split between both
    NONE = "none"


# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------

class DisputeDB(Base):
    """PostgreSQL table for bounty disputes."""
    __tablename__ = "disputes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bounty_id = Column(
        GUID(), ForeignKey("bounties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_id = Column(String(100), nullable=False, index=True)
    contributor_id = Column(String(100), nullable=False, index=True)
    creator_id = Column(String(100), nullable=False, index=True)
    
    status = Column(String(20), default=DisputeStatus.OPENED.value, nullable=False, index=True)
    reason = Column(String(1000), nullable=False)
    
    # Store evidence as a list of EvidenceItem objects
    evidence = Column(JSON, default=list, nullable=False) 
    
    # Snapshot from the submission record
    ai_score = Column(Float, default=0.0)
    
    resolution = Column(String(20), default=DisputeResolution.NONE.value, nullable=False)
    resolved_by = Column(String(100), nullable=True) # Admin ID or "system"
    resolution_notes = Column(Text, nullable=True)
    
    # Financial split if resolution is SPLIT
    contributor_share = Column(Float, default=0.0) # Percentage or Amount? Let's use Percentage (0.0 to 1.0)
    creator_share = Column(Float, default=0.0)
    
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class DisputeHistoryDB(Base):
    """Audit trail for dispute lifecycle transitions."""
    __tablename__ = "dispute_history"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    dispute_id = Column(
        GUID(), ForeignKey("disputes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action = Column(String(50), nullable=False)
    previous_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    actor_id = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    """A single piece of evidence submitted for a dispute."""
    type: str = Field(..., examples=["link", "explanation", "screenshot"])
    content: str = Field(..., examples=["The PR satisfies section 2.1 of the requirements...", "https://github.com/PR-link"])
    actor_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DisputeCreate(BaseModel):
    """Payload for initiating a dispute."""
    bounty_id: str
    submission_id: str
    reason: str = Field(..., min_length=10, max_length=1000)


class DisputeEvidenceCreate(BaseModel):
    """Payload for submitting evidence."""
    type: str = Field(..., pattern="^(link|explanation)$")
    content: str = Field(..., min_length=1)


class DisputeResolve(BaseModel):
    """Payload for resolving a dispute."""
    resolution: DisputeResolution
    resolution_notes: str = Field(..., min_length=10, max_length=5000)
    contributor_share: Optional[float] = 0.0 # 0.0 to 1.0
    creator_share: Optional[float] = 0.0 # 0.0 to 1.0


class DisputeResponse(BaseModel):
    """Full API response for a dispute."""
    id: uuid.UUID
    bounty_id: uuid.UUID
    submission_id: str
    contributor_id: str
    creator_id: str
    status: DisputeStatus
    reason: str
    evidence: List[Dict[str, Any]]
    ai_score: float
    resolution: DisputeResolution
    resolved_by: Optional[str]
    resolution_notes: Optional[str]
    contributor_share: float
    creator_share: float
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class DisputeListItem(BaseModel):
    """Compact dispute representation for lists."""
    id: uuid.UUID
    bounty_id: uuid.UUID
    submission_id: str
    status: DisputeStatus
    resolution: DisputeResolution
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class DisputeListResponse(BaseModel):
    """Paginated list of disputes."""
    items: List[DisputeListItem]
    total: int
    skip: int
    limit: int
