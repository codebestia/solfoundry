"""Dispute Resolution Service."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException, status

from app.models.dispute import (
    DisputeDB,
    DisputeHistoryDB,
    DisputeStatus,
    DisputeOutcome,
    DisputeCreate,
    EvidenceItem,
    DisputeResolve,
    DisputeResponse,
    DisputeDetailResponse,
    DisputeHistoryItem,
)
from app.models.submission import SubmissionStatus, SubmissionDB
from app.models.bounty_table import BountyTable
from app.services import review_service
from app.services.notification_service import TelegramNotifier
from app.services.reputation_service import record_reputation, ReputationRecordCreate

logger = logging.getLogger(__name__)

class DisputeError(Exception):
    """Custom exception for dispute-related errors."""
    pass

class DisputeService:
    """Service handling the lifecycle of disputes using PostgreSQL persistence."""

    async def _create_history(
        self,
        db: AsyncSession,
        dispute_id: UUID,
        action: str,
        actor_id: str,
        previous_status: Optional[str] = None,
        new_status: Optional[str] = None,
        notes: Optional[str] = None
    ):
        """Internal helper to create an audit record for a dispute."""
        history = DisputeHistoryDB(
            dispute_id=dispute_id,
            action=action,
            actor_id=actor_id,
            previous_status=previous_status,
            new_status=new_status,
            notes=notes
        )
        db.add(history)
        # We don't commit here, let the caller handle it for transactional integrity

    async def create_dispute(self, db: AsyncSession, data: DisputeCreate, submitter_id: str) -> DisputeResponse:
        """Initiate a dispute for a rejected bounty submission."""
        submitter_id_uuid = UUID(submitter_id)
        
        # 1. Fetch the submission and verify business rules
        stmt = (
            select(SubmissionDB, BountyTable)
            .join(BountyTable, BountyTable.id == SubmissionDB.bounty_id)
            .where(SubmissionDB.bounty_id == UUID(data.bounty_id))
            .where(SubmissionDB.contributor_id == submitter_id_uuid)
        )
        result = await db.execute(stmt)
        row = result.first()
        
        if not row:
            raise DisputeError("Submission from this contributor for the given bounty was not found.")
        
        sub, bounty = row
        
        if sub.status != SubmissionStatus.REJECTED.value:
            raise DisputeError(f"Only rejected submissions can be disputed. Current status: {sub.status}")
            
        # 2. Enforce 72-hour filing window
        # We use updated_at as a proxy for when the status was changed to rejected
        if (datetime.now(timezone.utc) - sub.updated_at.replace(tzinfo=timezone.utc)) > timedelta(hours=72):
             raise DisputeError("Disputes must be filed within 72 hours of the rejection notice.")

        # 3. Create the dispute record
        dispute = DisputeDB(
            bounty_id=bounty.id,
            submitter_id=submitter_id_uuid,
            reason=data.reason,
            description=data.description,
            evidence_links=[e.model_dump() for e in data.evidence_links] if data.evidence_links else [],
            status=DisputeStatus.OPENED.value
        )
        db.add(dispute)
        await db.flush() # Get the ID
        
        # Update submission status to DISPUTED
        sub.status = SubmissionStatus.DISPUTED.value
        
        await self._create_history(
            db, dispute.id, "DISPUTE_OPENED", submitter_id, None, DisputeStatus.OPENED.value, "Dispute created by contributor"
        )
        
        await db.commit()
        await db.refresh(dispute)
        
        # 4. Immediately trigger AI mediation pipeline
        return await self._run_ai_mediation(db, dispute)

    async def get_dispute(self, db: AsyncSession, dispute_id: str) -> DisputeDetailResponse:
        """Retrieve full dispute details including the auditable timeline."""
        stmt = select(DisputeDB).where(DisputeDB.id == UUID(dispute_id))
        result = await db.execute(stmt)
        dispute = result.scalar_one_or_none()
        if not dispute:
            raise DisputeError("Dispute record not found.")
            
        history_stmt = (
            select(DisputeHistoryDB)
            .where(DisputeHistoryDB.dispute_id == dispute.id)
            .order_by(DisputeHistoryDB.created_at)
        )
        history_res = await db.execute(history_stmt)
        histories = history_res.scalars().all()
        
        resp = DisputeDetailResponse.model_validate(dispute)
        resp.history = [DisputeHistoryItem.model_validate(h) for h in histories]
        return resp

    async def add_evidence(self, db: AsyncSession, dispute_id: str, evidence: List[EvidenceItem], actor_id: str) -> DisputeResponse:
        """Append new evidence to an active dispute."""
        dispute_uuid = UUID(dispute_id)
        stmt = select(DisputeDB).where(DisputeDB.id == dispute_uuid)
        result = await db.execute(stmt)
        dispute = result.scalar_one_or_none()
        
        if not dispute:
            raise DisputeError("Dispute not found.")
            
        if dispute.status == DisputeStatus.RESOLVED.value:
            raise DisputeError("Cannot add evidence to a resolved dispute.")
            
        # Role Check: only submitter or bounty creator
        bounty_stmt = select(BountyTable).where(BountyTable.id == dispute.bounty_id)
        b_res = await db.execute(bounty_stmt)
        bounty = b_res.scalar_one()
        
        actor_uuid = UUID(actor_id)
        # Note: created_by in BountyTable is String(100), we compare as string
        if actor_uuid != dispute.submitter_id and actor_id != bounty.created_by:
             raise DisputeError("Unauthorized: Only the dispute submitter or bounty creator can add evidence.")
            
        # Add sanitized evidence
        new_links = dispute.evidence_links + [e.model_dump() for e in evidence]
        dispute.evidence_links = new_links
        
        prev_status = dispute.status
        # Transition to EVIDENCE state if currently just OPENED
        if dispute.status == DisputeStatus.OPENED.value:
            dispute.status = DisputeStatus.EVIDENCE.value
            
        await self._create_history(
            db, dispute.id, "EVIDENCE_ADDED", actor_id, prev_status, dispute.status, f"Added {len(evidence)} evidence items"
        )
        await db.commit()
        await db.refresh(dispute)
        
        return DisputeResponse.model_validate(dispute)

    async def _run_ai_mediation(self, db: AsyncSession, dispute: DisputeDB) -> DisputeResponse:
        """Attempt auto-resolution using AI review scores."""
        try:
            # We fetch the aggregated score for the specific submission
            # Since we don't have submission_id in DisputeDB yet, we find it
            sub_stmt = select(SubmissionDB).where(
                SubmissionDB.bounty_id == dispute.bounty_id,
                SubmissionDB.contributor_id == dispute.submitter_id
            )
            sub_res = await db.execute(sub_stmt)
            sub = sub_res.scalar_one_or_none()
            
            if not sub:
                logger.error(f"Integrity Error: No submission found for dispute {dispute.id}")
                return DisputeResponse.model_validate(dispute)

            from app.models.review import AI_REVIEW_SCORE_THRESHOLD
            score_data = review_service.get_aggregated_score(str(sub.id), str(dispute.bounty_id))
            
            if score_data and score_data.overall_score >= AI_REVIEW_SCORE_THRESHOLD:
                logger.info(f"AI Auto-Resolution triggered for {dispute.id} (Score: {score_data.overall_score})")
                return await self.resolve_dispute(
                    db,
                    str(dispute.id),
                    DisputeResolve(
                        outcome=DisputeOutcome.RELEASE_TO_CONTRIBUTOR,
                        review_notes=f"AI Mediation: Submission quality ({score_data.overall_score}) meets threshold. Reversing rejection.",
                        resolution_action="SYSTEM_AUTO_RESOLVE"
                    ),
                    actor_id="00000000-0000-0000-0000-000000000001" # System User ID
                )
        except Exception as e:
            logger.warning(f"AI Mediation skipped for {dispute.id}: {str(e)}")
            
        # Fallback: Move to MEDIATION for manual review
        prev = dispute.status
        dispute.status = DisputeStatus.MEDIATION.value
        
        await self._create_history(
            db, dispute.id, "MEDIATION_REQUIRED", "00000000-0000-0000-0000-000000000001", prev, dispute.status, "Threshold not met. Manual review required."
        )
        await db.commit()
        await db.refresh(dispute)
        
        # Notify admins via Telegram
        await TelegramNotifier.send_alert(
            f"🚨 *Manual Mediation Required*\nDispute: {dispute.id}\nBounty: {dispute.bounty_id}\nReason: {dispute.reason}"
        )
        
        return DisputeResponse.model_validate(dispute)

    async def resolve_dispute(self, db: AsyncSession, dispute_id: str, resolve_data: DisputeResolve, actor_id: str) -> DisputeResponse:
        """Finalize a dispute with a concrete outcome and apply side effects."""
        stmt = select(DisputeDB).where(DisputeDB.id == UUID(dispute_id))
        result = await db.execute(stmt)
        dispute = result.scalar_one_or_none()
        
        if not dispute:
            raise DisputeError("Dispute record not found.")
        if dispute.status == DisputeStatus.RESOLVED.value:
            raise DisputeError("Dispute is already resolved.")
            
        prev_status = dispute.status
        dispute.status = DisputeStatus.RESOLVED.value
        dispute.outcome = resolve_data.outcome
        dispute.reviewer_id = UUID(actor_id)
        dispute.review_notes = resolve_data.review_notes
        dispute.resolution_action = resolve_data.resolution_action
        dispute.resolved_at = datetime.now(timezone.utc)
        
        # 1. Update Submission Status based on outcome
        sub_stmt = select(SubmissionDB).where(
            SubmissionDB.bounty_id == dispute.bounty_id,
            SubmissionDB.contributor_id == dispute.submitter_id
        )
        sub_res = await db.execute(sub_stmt)
        sub = sub_res.scalar_one()
        
        if resolve_data.outcome == DisputeOutcome.RELEASE_TO_CONTRIBUTOR.value:
            sub.status = SubmissionStatus.APPROVED.value
            # Apply Reputation Bonus for winning a legitimate dispute
            try:
                 bounty_stmt = select(BountyTable).where(BountyTable.id == dispute.bounty_id)
                 b_res = await db.execute(bounty_stmt)
                 bounty = b_res.scalar_one()
                 
                 record_reputation(ReputationRecordCreate(
                     contributor_id=str(dispute.submitter_id),
                     bounty_id=str(bounty.id),
                     bounty_title=bounty.title,
                     bounty_tier=bounty.tier,
                     review_score=10.0 # Full marks for winning dispute
                 ))
            except Exception as e:
                logger.error(f"Reputation update failed during resolution: {e}")
        else:
            sub.status = SubmissionStatus.REJECTED.value
            # Frivolous dispute penalty logic can be added here
            
        await self._create_history(
            db, dispute.id, "DISPUTE_RESOLVED", actor_id, prev_status, dispute.status, f"Outcome: {resolve_data.outcome}"
        )
        
        await db.commit()
        await db.refresh(dispute)
        
        return DisputeResponse.model_validate(dispute)

# Singleton service instance
dispute_service = DisputeService()
