"""Claim lifecycle API router (Issue #16).

Endpoints: claim, unclaim, claim history, T3 approval.
All mutation endpoints require authentication via get_current_user_id.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user_id
from app.models.claim import (
    ClaimCreate,
    ClaimHistoryResponse,
    ClaimResponse,
)
from app.services import claim_service

router = APIRouter(prefix="/api/bounties", tags=["claims"])


@router.post(
    "/{bounty_id}/claim",
    response_model=ClaimResponse,
    status_code=201,
    summary="Claim a bounty (T2/T3)",
)
async def claim_bounty(
    bounty_id: str,
    data: ClaimCreate = ClaimCreate(),
    user_id: str = Depends(get_current_user_id),
) -> ClaimResponse:
    """
    Claim a bounty for the authenticated user.

    - **T2**: Direct claim with 7-day deadline. Requires reputation ≥ 10.
    - **T3**: Requires `application_plan`. Claim enters `pending_approval` state
      until an admin approves. Requires reputation ≥ 50.
    - **T1**: Cannot be claimed (open contribution).
    """
    result, error = claim_service.claim_bounty(bounty_id, user_id, data)
    if error:
        status_code = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status_code, detail=error)
    return result


@router.post(
    "/{bounty_id}/unclaim",
    response_model=ClaimResponse,
    summary="Voluntarily release a claim",
)
async def unclaim_bounty(
    bounty_id: str,
    user_id: str = Depends(get_current_user_id),
) -> ClaimResponse:
    """Release the authenticated user's active claim on a bounty."""
    result, error = claim_service.unclaim_bounty(bounty_id, user_id)
    if error:
        status_code = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status_code, detail=error)
    return result


@router.get(
    "/{bounty_id}/claims",
    response_model=ClaimHistoryResponse,
    summary="View claim history for a bounty",
)
async def get_claim_history(bounty_id: str) -> ClaimHistoryResponse:
    """Return the full claim history for a bounty."""
    result = claim_service.get_claim_history(bounty_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Bounty not found")
    return result


@router.post(
    "/{bounty_id}/claims/{claim_id}/approve",
    response_model=ClaimResponse,
    summary="Approve a T3 claim application",
)
async def approve_claim(
    bounty_id: str,
    claim_id: str,
    _user_id: str = Depends(get_current_user_id),
) -> ClaimResponse:
    """
    Admin approves a T3 claim application.

    Moves the claim from `pending_approval` to `active` and sets
    the 14-day deadline.
    """
    result, error = claim_service.approve_t3_claim(bounty_id, claim_id)
    if error:
        status_code = 404 if "not found" in error.lower() else 400
        raise HTTPException(status_code=status_code, detail=error)
    return result
