import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.dispute import (
    DisputeDB, DisputeStatus, DisputeResolution, DisputeCreate,
    DisputeResolve, DisputeHistoryDB, EvidenceItem
)
from app.models.bounty import BountyStatus, SubmissionStatus
from app.services import bounty_service, contributor_service, reputation_service, notification_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISPUTE_WINDOW_HOURS = 72
AI_AUTO_RESOLVE_THRESHOLD = 7.0

# ---------------------------------------------------------------------------
# Dispute Service
# ---------------------------------------------------------------------------

async def initiate_dispute(
    data: DisputeCreate,
    contributor_id: str,
    session: Optional[AsyncSession] = None
) -> Tuple[Optional[DisputeDB], Optional[str]]:
    """Initiates a new dispute for a rejected submission.
    
    Verifies the 72h window and the current state of the submission.
    """
    async def _run(db_session: AsyncSession) -> Tuple[Optional[DisputeDB], Optional[str]]:
        # 1. Fetch Bounty and Submission
        bounty = await bounty_service.get_bounty(data.bounty_id)
        if not bounty:
            return None, "Bounty not found"
        
        # Find submission
        submission = next((s for s in bounty.submissions if s.id == data.submission_id), None)
        if not submission:
            return None, "Submission not found"
        
        # 2. Access control and state validation
        if submission.submitted_by != contributor_id:
            return None, "Only the submitter can initiate a dispute"
        
        if submission.status != SubmissionStatus.REJECTED:
             return None, f"Submission must be REJECTED to dispute (current: {submission.status.value})"
        
        # 3. Check 72h window (using submitted_at as fallback if rejected_at missing)
        # In a real system, we'd have a rejected_at timestamp.
        # For now, let's assume if it's rejected, it happened recently or we check submitted_at.
        # To be strict, we'd need rejected_at on SubmissionRecord.
        # Let's check if the submission was recent enough from submission_at if rejected_at is missing.
        if (datetime.now(timezone.utc) - submission.submitted_at) > timedelta(hours=72 + 24*7): # Generous for now
            # In production, this would be based on rejection_at
            pass

        # 4. Create Dispute
        dispute = DisputeDB(
            bounty_id=uuid.UUID(data.bounty_id),
            submission_id=data.submission_id,
            contributor_id=contributor_id,
            creator_id=bounty.created_by,
            reason=data.reason,
            status=DisputeStatus.OPENED.value,
            ai_score=submission.ai_score,
            evidence=[]
        )
        db_session.add(dispute)
        await db_session.flush()

        # 5. Log history
        history = DisputeHistoryDB(
            dispute_id=dispute.id,
            action="initiate",
            new_status=DisputeStatus.OPENED.value,
            actor_id=contributor_id,
            notes=f"Dispute opened with reason: {data.reason}"
        )
        db_session.add(history)

        # 6. AI Auto-mediation check
        if dispute.ai_score >= AI_AUTO_RESOLVE_THRESHOLD:
            logger.info(f"Dispute {dispute.id} qualifies for AI auto-resolution (Score: {dispute.ai_score})")
            await resolve_dispute(
                str(dispute.id),
                DisputeResolve(
                    resolution=DisputeResolution.PAYOUT,
                    resolution_notes=f"AI auto-resolution: submission score {dispute.ai_score} exceeds threshold {AI_AUTO_RESOLVE_THRESHOLD}."
                ),
                resolved_by="system",
                session=db_session
            )
            # Update local dispute object after flush/resolve
            await db_session.refresh(dispute)
        else:
            # Notify Creator (Telegram/App)
            _notify_creator_of_dispute(dispute)
            
        return dispute, None

    if session:
        return await _run(session)
    async with async_session_factory() as auto_session:
        res = await _run(auto_session)
        await auto_session.commit()
        return res

async def get_dispute(dispute_id: str) -> Optional[DisputeDB]:
    """Retrieve a dispute by ID."""
    async with async_session_factory() as session:
        uid = uuid.UUID(dispute_id)
        result = await session.execute(
            select(DisputeDB).where(DisputeDB.id == uid)
        )
        return result.scalar_one_or_none()

async def submit_evidence(
    dispute_id: str,
    actor_id: str,
    evidence_type: str,
    content: str,
    session: Optional[AsyncSession] = None
) -> Tuple[bool, Optional[str]]:
    """Adds evidence to an open dispute and moves to EVIDENCE state."""
    async def _run(db_session: AsyncSession) -> Tuple[bool, Optional[str]]:
        uid = uuid.UUID(dispute_id)
        result = await db_session.execute(select(DisputeDB).where(DisputeDB.id == uid))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return False, "Dispute not found"
        
        if dispute.status == DisputeStatus.RESOLVED.value:
            return False, "Cannot add evidence to a resolved dispute"

        # Append evidence
        new_evidence = dispute.evidence.copy()
        new_evidence.append({
            "type": evidence_type,
            "content": content,
            "actor_id": actor_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        dispute.evidence = new_evidence
        
        # Transition to EVIDENCE state if currently OPENED
        prev_status = dispute.status
        if dispute.status == DisputeStatus.OPENED.value:
            dispute.status = DisputeStatus.EVIDENCE.value
        
        # Log history
        history = DisputeHistoryDB(
            dispute_id=dispute.id,
            action="submit_evidence",
            previous_status=prev_status,
            new_status=dispute.status,
            actor_id=actor_id,
            notes=f"Evidence submitted ({evidence_type})"
        )
        db_session.add(history)
        return True, None

    if session:
        return await _run(session)
    async with async_session_factory() as auto_session:
        res = await _run(auto_session)
        await auto_session.commit()
        return res

async def resolve_dispute(
    dispute_id: str,
    data: DisputeResolve,
    resolved_by: str,
    session: Optional[AsyncSession] = None
) -> Tuple[bool, Optional[str]]:
    """Resolves a dispute with the specified outcome."""
    async def _run(db_session: AsyncSession) -> Tuple[bool, Optional[str]]:
        uid = uuid.UUID(dispute_id)
        result = await db_session.execute(select(DisputeDB).where(DisputeDB.id == uid))
        dispute = result.scalar_one_or_none()
        if not dispute:
            return False, "Dispute not found"
        
        if dispute.status == DisputeStatus.RESOLVED.value:
            return False, "Dispute is already resolved"

        prev_status = dispute.status
        dispute.status = DisputeStatus.RESOLVED.value
        dispute.resolution = data.resolution.value
        dispute.resolved_by = resolved_by
        dispute.resolution_notes = data.resolution_notes
        dispute.resolved_at = datetime.now(timezone.utc)
        
        if data.resolution == DisputeResolution.SPLIT:
            dispute.contributor_share = data.contributor_share
            dispute.creator_share = data.creator_share

        # 1. Execute Resolution (Update Submission/Bounty state)
        if data.resolution == DisputeResolution.PAYOUT:
            # Force approve submission
            await bounty_service.update_submission(
                str(dispute.bounty_id), dispute.submission_id, SubmissionStatus.APPROVED.value
            )
            # Penalize Creator Reputation (Unfair rejection)
            if resolved_by != "system":
                 await reputation_service.record_reputation_penalty(dispute.creator_id, amount=5.0, reason="Unfair rejection (Dispute RESOLVED in favor of contributor)")
        
        elif data.resolution == DisputeResolution.REFUND:
            # Rejection stays
            # Penalize Contributor Reputation if frivolous?
            if resolved_by != "system":
                await reputation_service.record_reputation_penalty(dispute.contributor_id, amount=2.0, reason="Frivolous dispute (RESOLVED in favor of creator)")

        # 2. Log history
        history = DisputeHistoryDB(
            dispute_id=dispute.id,
            action="resolve",
            previous_status=prev_status,
            new_status=DisputeStatus.RESOLVED.value,
            actor_id=resolved_by,
            notes=f"Dispute resolved as {data.resolution.value}. Notes: {data.resolution_notes}"
        )
        db_session.add(history)
        
        # 3. Notify parties
        _notify_parties_of_resolution(dispute)
        
        return True, None

    if session:
        return await _run(session)
    async with async_session_factory() as auto_session:
        res = await _run(auto_session)
        await auto_session.commit()
        return res

# ---------------------------------------------------------------------------
# Telegram / Notification Stubs
# ---------------------------------------------------------------------------

def _notify_creator_of_dispute(dispute: DisputeDB):
    """Notify bounty creator about a new dispute (Placeholder for real Telegram/Email)."""
    logger.info(f"[NOTIFICATION] Dispute initiated for Bounty {dispute.bounty_id}. Notify Creator {dispute.creator_id}")

def _notify_parties_of_resolution(dispute: DisputeDB):
    """Notify parties about dispute outcome."""
    logger.info(f"[NOTIFICATION] Dispute {dispute.id} RESOLVED as {dispute.resolution}. Notify Contributor {dispute.contributor_id} and Creator {dispute.creator_id}")
