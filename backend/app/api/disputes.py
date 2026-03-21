from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user_id
from app.constants import INTERNAL_SYSTEM_USER_ID
from app.models.dispute import (
    DisputeCreate, DisputeResponse, DisputeListResponse,
    DisputeEvidenceCreate, DisputeResolve
)
from app.services import dispute_service

router = APIRouter(prefix="/disputes", tags=["disputes"])

@router.post("", response_model=DisputeResponse, status_code=201)
async def create_dispute(
    data: DisputeCreate,
    user_id: str = Depends(get_current_user_id)
):
    """Initiate a dispute for a rejected submission."""
    dispute, error = await dispute_service.initiate_dispute(data, user_id)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    return dispute

@router.get("/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(
    dispute_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """Retrieve dispute details."""
    dispute = await dispute_service.get_dispute(dispute_id)
    if not dispute:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    
    # Access control: Contributor, Creator, or Admin
    if user_id not in [dispute.contributor_id, dispute.creator_id, INTERNAL_SYSTEM_USER_ID]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    return dispute

@router.post("/{dispute_id}/evidence", status_code=200)
async def submit_evidence(
    dispute_id: str,
    data: DisputeEvidenceCreate,
    user_id: str = Depends(get_current_user_id)
):
    """Submit evidence (link or explanation) for an open dispute."""
    # Logic is handled in service (which checks dispute state)
    success, error = await dispute_service.submit_evidence(
        dispute_id, user_id, data.type, data.content
    )
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    return {"status": "success", "message": "Evidence submitted"}

@router.post("/{dispute_id}/resolve", response_model=DisputeResponse)
async def resolve_dispute(
    dispute_id: str,
    data: DisputeResolve,
    user_id: str = Depends(get_current_user_id)
):
    """Resolve a dispute (Admin only)."""
    # Simple admin check for now
    if user_id != INTERNAL_SYSTEM_USER_ID:
         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only platform admins can resolve disputes")
    
    success, error = await dispute_service.resolve_dispute(dispute_id, data, user_id)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    
    # Return updated dispute
    return await dispute_service.get_dispute(dispute_id)
