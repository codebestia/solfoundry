import pytest
from unittest.mock import AsyncMock, patch, MagicMock, ANY
from app.models.dispute import DisputeStatus, DisputeResolution, DisputeCreate, DisputeResolve
from app.services.dispute_service import initiate_dispute, resolve_dispute, submit_evidence

@pytest.mark.asyncio
async def test_initiate_dispute_success():
    # Mocking bounty and submission
    mock_bounty = MagicMock()
    mock_submission = MagicMock()
    mock_submission.id = "sub_123"
    mock_submission.submitted_by = "user_456"
    mock_submission.status = "rejected"
    mock_submission.ai_score = 6.5
    mock_bounty.submissions = [mock_submission]
    mock_bounty.created_by = "creator_789"

    with patch("app.services.bounty_service.get_bounty", new_callable=AsyncMock) as mock_get_bounty:
        mock_get_bounty.return_value = mock_bounty
        
        data = DisputeCreate(
            bounty_id="550e8400-e29b-41d4-a716-446655440000",
            submission_id="sub_123",
            reason="My submission was valid and fully functional."
        )
        
        mock_session = AsyncMock()
        dispute, error = await initiate_dispute(data, "user_456", session=mock_session)
        
        assert error is None
        assert dispute.status == DisputeStatus.OPENED.value
        assert dispute.creator_id == "creator_789"
        mock_session.add.assert_called()

@pytest.mark.asyncio
async def test_initiate_dispute_ai_auto_resolve():
    mock_bounty = MagicMock()
    mock_submission = MagicMock()
    mock_submission.id = "sub_123"
    mock_submission.submitted_by = "user_456"
    mock_submission.status = "rejected"
    mock_submission.ai_score = 8.5 # High score -> auto resolve
    mock_bounty.submissions = [mock_submission]
    mock_bounty.created_by = "creator_789"

    with patch("app.services.bounty_service.get_bounty", new_callable=AsyncMock) as mock_get_bounty:
        mock_get_bounty.return_value = mock_bounty
        
        data = DisputeCreate(
            bounty_id="550e8400-e29b-41d4-a716-446655440000",
            submission_id="sub_123",
            reason="Auto-resolve me please."
        )
        
        mock_session = AsyncMock()
        # Mocking resolve_dispute to avoid deep mocking
        with patch("app.services.dispute_service.resolve_dispute", new_callable=AsyncMock) as mock_resolve:
            dispute, error = await initiate_dispute(data, "user_456", session=mock_session)
            
            assert error is None
            mock_resolve.assert_called_once()
            # In the real code, resolve_dispute would update status to RESOLVED

@pytest.mark.asyncio
async def test_resolve_dispute_manual():
    mock_dispute = MagicMock()
    mock_dispute.id = "dis_123"
    mock_dispute.status = DisputeStatus.OPENED.value
    mock_dispute.bounty_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_dispute.submission_id = "sub_123"
    mock_dispute.creator_id = "creator_789"

    mock_session = AsyncMock()
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_dispute

    data = DisputeResolve(
        resolution=DisputeResolution.PAYOUT,
        resolution_notes="Admin review: Submission is indeed valid."
    )

    with patch("app.services.bounty_service.update_submission", new_callable=AsyncMock) as mock_update_sub, \
         patch("app.services.reputation_service.record_reputation_penalty", new_callable=AsyncMock) as mock_penalty:
        
        success, error = await resolve_dispute("dis_123", data, resolved_by="admin_000", session=mock_session)
        
        assert success is True
        assert mock_dispute.status == DisputeStatus.RESOLVED.value
        mock_update_sub.assert_called_with(ANY, "sub_123", "approved")
        mock_penalty.assert_called_once() # Penalize creator for unfair rejection
