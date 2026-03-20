"""Claim service for T2/T3 bounty claiming (Issue #16).

In-memory implementation following the same MVP pattern as bounty_service.
Handles claim creation, validation, release, and deadline enforcement.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.bounty import BountyStatus, BountyTier
from app.models.claim import (
    ClaimCreate,
    ClaimHistoryResponse,
    ClaimRecord,
    ClaimResponse,
    ClaimStatus,
    T2_DEADLINE_DAYS,
    T2_MIN_REPUTATION,
    T3_DEADLINE_DAYS,
    T3_MIN_REPUTATION,
)
from app.services import bounty_service, contributor_service

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

# bounty_id -> list of ClaimRecords (full history)
_claim_store: dict[str, list[ClaimRecord]] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_claim_response(c: ClaimRecord) -> ClaimResponse:
    return ClaimResponse(
        id=c.id,
        bounty_id=c.bounty_id,
        claimed_by=c.claimed_by,
        status=c.status,
        application_plan=c.application_plan,
        deadline=c.deadline,
        claimed_at=c.claimed_at,
        resolved_at=c.resolved_at,
        outcome=c.outcome,
    )


def _get_active_claim(bounty_id: str) -> Optional[ClaimRecord]:
    """Return the active or pending claim for a bounty, if any."""
    claims = _claim_store.get(bounty_id, [])
    for claim in claims:
        if claim.status in (ClaimStatus.ACTIVE, ClaimStatus.PENDING_APPROVAL):
            return claim
    return None


def _get_reputation(username: str) -> int:
    """Look up a contributor's reputation score."""
    contributor = contributor_service.get_contributor_by_username(username)
    if contributor is None:
        return 0
    return contributor.stats.reputation_score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def claim_bounty(
    bounty_id: str,
    user_id: str,
    data: ClaimCreate,
) -> tuple[Optional[ClaimResponse], Optional[str]]:
    """
    Claim a bounty.

    Validates:
    - Bounty exists and is open
    - Tier allows claiming (T1 not claimable)
    - User reputation meets minimum for the tier
    - No active claim already exists on this bounty

    Returns (ClaimResponse, None) on success or (None, error_message) on failure.
    """
    # --- Bounty existence & status ---
    bounty = bounty_service._bounty_store.get(bounty_id)
    if not bounty:
        return None, "Bounty not found"

    # --- Duplicate claim check ---
    active = _get_active_claim(bounty_id)
    if active is not None:
        return None, "This bounty already has an active claim"

    # --- Bounty status check ---
    if bounty.status != BountyStatus.OPEN:
        return None, f"Bounty is not open for claiming (status: {bounty.status.value})"

    # --- Tier validation ---
    if bounty.tier == BountyTier.T1:
        return None, "T1 bounties are open-contribution and cannot be claimed"

    # --- Reputation gate ---
    reputation = _get_reputation(user_id)

    if bounty.tier == BountyTier.T2 and reputation < T2_MIN_REPUTATION:
        return None, (
            f"Insufficient reputation to claim T2 bounty. "
            f"Required: {T2_MIN_REPUTATION}, current: {reputation}"
        )

    if bounty.tier == BountyTier.T3 and reputation < T3_MIN_REPUTATION:
        return None, (
            f"Insufficient reputation to claim T3 bounty. "
            f"Required: {T3_MIN_REPUTATION}, current: {reputation}"
        )

    # --- T3 requires application plan ---
    if bounty.tier == BountyTier.T3 and not data.application_plan:
        return None, "T3 bounties require an application_plan describing your approach"

    # --- Create the claim ---
    now = datetime.now(timezone.utc)

    if bounty.tier == BountyTier.T2:
        # T2: direct activation with 7-day deadline
        claim = ClaimRecord(
            bounty_id=bounty_id,
            claimed_by=user_id,
            status=ClaimStatus.ACTIVE,
            deadline=now + timedelta(days=T2_DEADLINE_DAYS),
            claimed_at=now,
        )
        # Update bounty state
        bounty.status = BountyStatus.IN_PROGRESS
        bounty.claimed_by = user_id
        bounty.claim_deadline = claim.deadline
        bounty.updated_at = now
    else:
        # T3: pending admin approval, no deadline until approved
        claim = ClaimRecord(
            bounty_id=bounty_id,
            claimed_by=user_id,
            status=ClaimStatus.PENDING_APPROVAL,
            application_plan=data.application_plan,
            claimed_at=now,
        )

    # Store the claim
    if bounty_id not in _claim_store:
        _claim_store[bounty_id] = []
    _claim_store[bounty_id].append(claim)

    return _to_claim_response(claim), None


def unclaim_bounty(
    bounty_id: str,
    user_id: str,
) -> tuple[Optional[ClaimResponse], Optional[str]]:
    """
    Voluntarily release an active claim.

    Returns (ClaimResponse, None) on success or (None, error_message) on failure.
    """
    bounty = bounty_service._bounty_store.get(bounty_id)
    if not bounty:
        return None, "Bounty not found"

    active = _get_active_claim(bounty_id)
    if active is None:
        return None, "No active claim on this bounty"

    if active.claimed_by != user_id:
        return None, "You can only release your own claim"

    # Release the claim
    now = datetime.now(timezone.utc)
    active.status = ClaimStatus.RELEASED
    active.resolved_at = now
    active.outcome = "released"

    # Reset bounty state
    bounty.status = BountyStatus.OPEN
    bounty.claimed_by = None
    bounty.claim_deadline = None
    bounty.updated_at = now

    return _to_claim_response(active), None


def approve_t3_claim(
    bounty_id: str,
    claim_id: str,
) -> tuple[Optional[ClaimResponse], Optional[str]]:
    """
    Admin approves a T3 claim application.

    Moves claim from pending_approval → active and sets the 14-day deadline.

    Returns (ClaimResponse, None) on success or (None, error_message) on failure.
    """
    bounty = bounty_service._bounty_store.get(bounty_id)
    if not bounty:
        return None, "Bounty not found"

    claims = _claim_store.get(bounty_id, [])
    claim = next((c for c in claims if c.id == claim_id), None)
    if claim is None:
        return None, "Claim not found"

    if claim.status != ClaimStatus.PENDING_APPROVAL:
        return None, f"Claim is not pending approval (status: {claim.status.value})"

    # Activate the claim
    now = datetime.now(timezone.utc)
    claim.status = ClaimStatus.ACTIVE
    claim.deadline = now + timedelta(days=T3_DEADLINE_DAYS)

    # Update bounty state
    bounty.status = BountyStatus.IN_PROGRESS
    bounty.claimed_by = claim.claimed_by
    bounty.claim_deadline = claim.deadline
    bounty.updated_at = now

    return _to_claim_response(claim), None


def get_claim_history(bounty_id: str) -> Optional[ClaimHistoryResponse]:
    """
    Return the full claim history for a bounty.

    Returns None if the bounty does not exist.
    """
    bounty = bounty_service._bounty_store.get(bounty_id)
    if not bounty:
        return None

    claims = _claim_store.get(bounty_id, [])
    return ClaimHistoryResponse(
        bounty_id=bounty_id,
        claims=[_to_claim_response(c) for c in claims],
        total=len(claims),
    )


def get_active_claim(bounty_id: str) -> Optional[ClaimResponse]:
    """Return the current active claim for a bounty, if any."""
    active = _get_active_claim(bounty_id)
    return _to_claim_response(active) if active else None


def release_expired_claims() -> int:
    """
    Scan all active claims and release those past their deadline.

    Called by the deadline watcher background task.
    Returns the number of claims released.
    """
    now = datetime.now(timezone.utc)
    released_count = 0

    for bounty_id, claims in _claim_store.items():
        for claim in claims:
            if (
                claim.status == ClaimStatus.ACTIVE
                and claim.deadline is not None
                and now >= claim.deadline
            ):
                claim.status = ClaimStatus.EXPIRED
                claim.resolved_at = now
                claim.outcome = "expired"

                # Reset bounty state
                bounty = bounty_service._bounty_store.get(bounty_id)
                if bounty:
                    bounty.status = BountyStatus.OPEN
                    bounty.claimed_by = None
                    bounty.claim_deadline = None
                    bounty.updated_at = now

                released_count += 1

    return released_count
