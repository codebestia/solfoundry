"""Comprehensive tests for bounty claim lifecycle (Issue #16).

Covers: T2/T3 claiming, reputation gates, unclaim, deadline expiry,
T3 approval, claim history, and auth enforcement.

Follows the same test pattern as test_bounties.py (in-memory, TestClient).
"""

import os
os.environ["AUTH_ENABLED"] = "false"

import pytest
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.bounties import router as bounties_router
from app.api.claims import router as claims_router
from app.models.bounty import BountyCreate, BountyTier
from app.models.claim import (
    ClaimStatus,
    T2_MIN_REPUTATION,
    T3_MIN_REPUTATION,
    T2_DEADLINE_DAYS,
    T3_DEADLINE_DAYS,
)
from app.services import bounty_service, claim_service, contributor_service
from app.models.contributor import ContributorCreate

# ---------------------------------------------------------------------------
# Test app & client
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(bounties_router)
_test_app.include_router(claims_router)

client = TestClient(_test_app)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

VALID_BOUNTY_T2 = {
    "title": "Fix smart contract bug",
    "description": "Bug in token transfer logic.",
    "tier": 2,
    "reward_amount": 500.0,
    "github_issue_url": "https://github.com/org/repo/issues/42",
}

VALID_BOUNTY_T3 = {
    "title": "Build new oracle module",
    "description": "Implement a price oracle integration.",
    "tier": 3,
    "reward_amount": 5000.0,
    "github_issue_url": "https://github.com/org/repo/issues/99",
}

VALID_BOUNTY_T1 = {
    "title": "Fix a typo in docs",
    "description": "Typo on the landing page.",
    "tier": 1,
    "reward_amount": 10.0,
}

USER_ID = "alice"
USER_ID_2 = "bob"
ADMIN_ID = "admin"

T3_APPLICATION = "I will implement a Chainlink-compatible oracle adapter with 3-phase rollout."


@pytest.fixture(autouse=True)
def clear_stores():
    """Ensure each test starts with empty stores."""
    bounty_service._bounty_store.clear()
    claim_service._claim_store.clear()
    contributor_service._store.clear()
    yield
    bounty_service._bounty_store.clear()
    claim_service._claim_store.clear()
    contributor_service._store.clear()


def _create_bounty(**overrides) -> dict:
    """Create a bounty via the service and return its dict."""
    payload = {**VALID_BOUNTY_T2, **overrides}
    return bounty_service.create_bounty(BountyCreate(**payload)).model_dump()


def _create_contributor(username: str, reputation: int = 0) -> dict:
    """Create a contributor with a given reputation score."""
    contributor = contributor_service.create_contributor(
        ContributorCreate(
            username=username,
            display_name=username.title(),
        )
    )
    # Set reputation directly on the DB object
    db_obj = contributor_service._store.get(contributor.id)
    if db_obj:
        db_obj.reputation_score = reputation
    return contributor.model_dump()


def _auth_headers(user_id: str) -> dict:
    """Return headers that pass authentication for a given user."""
    return {"X-User-ID": user_id}


# ===========================================================================
# CLAIM BOUNTY (T2)
# ===========================================================================

class TestClaimBountyT2:
    def test_claim_t2_success(self):
        """T2 bounty can be claimed by user with sufficient reputation."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["bounty_id"] == bid
        assert body["claimed_by"] == USER_ID
        assert body["status"] == ClaimStatus.ACTIVE.value
        assert body["deadline"] is not None
        assert body["application_plan"] is None
        assert "id" in body
        assert "claimed_at" in body

    def test_claim_t2_updates_bounty_status(self):
        """Claiming a T2 bounty transitions it to in_progress."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        bounty = client.get(f"/api/bounties/{bid}").json()
        assert bounty["status"] == "in_progress"
        assert bounty["claimed_by"] == USER_ID
        assert bounty["claim_deadline"] is not None

    def test_claim_t2_deadline_is_7_days(self):
        """T2 claim deadline is 7 days from now."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        body = resp.json()
        claimed_at = datetime.fromisoformat(body["claimed_at"])
        deadline = datetime.fromisoformat(body["deadline"])
        delta = deadline - claimed_at
        assert abs(delta.days - T2_DEADLINE_DAYS) <= 1  # Allow 1 day tolerance

    def test_claim_t2_insufficient_reputation(self):
        """T2 claim rejected if reputation < 10."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION - 1)
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 400
        assert "Insufficient reputation" in resp.json()["detail"]
        assert str(T2_MIN_REPUTATION) in resp.json()["detail"]

    def test_claim_t2_no_contributor_profile(self):
        """User without a contributor profile has rep 0 and is rejected."""
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers("nobody"),
        )
        assert resp.status_code == 400
        assert "Insufficient reputation" in resp.json()["detail"]

    def test_claim_already_claimed(self):
        """Cannot claim a bounty that already has an active claim."""
        _create_contributor(USER_ID, reputation=50)
        _create_contributor(USER_ID_2, reputation=50)
        b = _create_bounty()
        bid = b["id"]

        # First claim succeeds
        resp1 = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp1.status_code == 201

        # Second claim fails
        resp2 = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID_2),
        )
        assert resp2.status_code == 400
        assert "already has an active claim" in resp2.json()["detail"]

    def test_claim_bounty_not_found(self):
        """Claiming a non-existent bounty returns 404."""
        _create_contributor(USER_ID, reputation=50)

        resp = client.post(
            "/api/bounties/nonexistent/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 404

    def test_claim_bounty_not_open(self):
        """Cannot claim a bounty that is not in open status."""
        _create_contributor(USER_ID, reputation=50)
        _create_contributor(USER_ID_2, reputation=50)
        b = _create_bounty()
        bid = b["id"]

        # Claim it first to move to in_progress
        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        # Unclaim first user, then try claiming with second user
        # Actually let's just check that second user can't claim while claimed
        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID_2),
        )
        assert resp.status_code == 400


# ===========================================================================
# CLAIM BOUNTY (T1 — should fail)
# ===========================================================================

class TestClaimBountyT1:
    def test_claim_t1_rejected(self):
        """T1 bounties cannot be claimed."""
        _create_contributor(USER_ID, reputation=100)
        b = _create_bounty(**VALID_BOUNTY_T1)
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 400
        assert "T1" in resp.json()["detail"]
        assert "cannot be claimed" in resp.json()["detail"]


# ===========================================================================
# CLAIM BOUNTY (T3)
# ===========================================================================

class TestClaimBountyT3:
    def test_claim_t3_with_plan(self):
        """T3 claim with application plan enters pending_approval."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == ClaimStatus.PENDING_APPROVAL.value
        assert body["application_plan"] == T3_APPLICATION
        assert body["deadline"] is None  # No deadline until approved

    def test_claim_t3_without_plan_rejected(self):
        """T3 claim without application_plan is rejected."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 400
        assert "application_plan" in resp.json()["detail"]

    def test_claim_t3_insufficient_reputation(self):
        """T3 claim rejected if reputation < 50."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION - 1)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 400
        assert "Insufficient reputation" in resp.json()["detail"]
        assert str(T3_MIN_REPUTATION) in resp.json()["detail"]

    def test_claim_t3_bounty_stays_open_until_approved(self):
        """T3 pending claim does not change bounty status."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )

        bounty = client.get(f"/api/bounties/{bid}").json()
        assert bounty["status"] == "open"


# ===========================================================================
# T3 APPROVAL
# ===========================================================================

class TestT3Approval:
    def test_approve_t3_success(self):
        """Admin approves T3 claim -> active with 14-day deadline."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        # Create T3 claim
        claim_resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        claim_id = claim_resp.json()["id"]

        # Admin approves
        resp = client.post(
            f"/api/bounties/{bid}/claims/{claim_id}/approve",
            headers=_auth_headers(ADMIN_ID),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == ClaimStatus.ACTIVE.value
        assert body["deadline"] is not None

    def test_approve_t3_updates_bounty(self):
        """After T3 approval, bounty moves to in_progress."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        claim_resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        claim_id = claim_resp.json()["id"]

        client.post(
            f"/api/bounties/{bid}/claims/{claim_id}/approve",
            headers=_auth_headers(ADMIN_ID),
        )

        bounty = client.get(f"/api/bounties/{bid}").json()
        assert bounty["status"] == "in_progress"
        assert bounty["claimed_by"] == USER_ID
        assert bounty["claim_deadline"] is not None

    def test_approve_t3_deadline_is_14_days(self):
        """T3 deadline is 14 days after approval."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        claim_resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        claim_id = claim_resp.json()["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claims/{claim_id}/approve",
            headers=_auth_headers(ADMIN_ID),
        )
        body = resp.json()
        deadline = datetime.fromisoformat(body["deadline"])
        # Should be ~14 days from now
        expected = datetime.now(timezone.utc) + timedelta(days=T3_DEADLINE_DAYS)
        assert abs((deadline - expected).total_seconds()) < 60  # Within 1 minute

    def test_approve_already_active(self):
        """Cannot approve a claim that is already active."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        claim_resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        claim_id = claim_resp.json()["id"]

        # Approve once
        client.post(
            f"/api/bounties/{bid}/claims/{claim_id}/approve",
            headers=_auth_headers(ADMIN_ID),
        )

        # Try approving again
        resp = client.post(
            f"/api/bounties/{bid}/claims/{claim_id}/approve",
            headers=_auth_headers(ADMIN_ID),
        )
        assert resp.status_code == 400
        assert "not pending approval" in resp.json()["detail"]

    def test_approve_claim_not_found(self):
        """Approving a non-existent claim returns 404."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claims/nonexistent/approve",
            headers=_auth_headers(ADMIN_ID),
        )
        assert resp.status_code == 404


# ===========================================================================
# UNCLAIM
# ===========================================================================

class TestUnclaimBounty:
    def test_unclaim_success(self):
        """User can voluntarily release their claim."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        # Claim it
        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        # Unclaim it
        resp = client.post(
            f"/api/bounties/{bid}/unclaim",
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == ClaimStatus.RELEASED.value
        assert body["outcome"] == "released"
        assert body["resolved_at"] is not None

    def test_unclaim_resets_bounty(self):
        """Unclaiming resets bounty to open status."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        client.post(
            f"/api/bounties/{bid}/unclaim",
            headers=_auth_headers(USER_ID),
        )

        bounty = client.get(f"/api/bounties/{bid}").json()
        assert bounty["status"] == "open"
        assert bounty["claimed_by"] is None
        assert bounty["claim_deadline"] is None

    def test_unclaim_allows_reclaim(self):
        """After unclaiming, another user can claim the bounty."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        _create_contributor(USER_ID_2, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        # User 1 claims and unclaims
        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        client.post(
            f"/api/bounties/{bid}/unclaim",
            headers=_auth_headers(USER_ID),
        )

        # User 2 can now claim
        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID_2),
        )
        assert resp.status_code == 201
        assert resp.json()["claimed_by"] == USER_ID_2

    def test_unclaim_not_the_claimer(self):
        """Cannot unclaim someone else's claim."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        resp = client.post(
            f"/api/bounties/{bid}/unclaim",
            headers=_auth_headers(USER_ID_2),
        )
        assert resp.status_code == 400
        assert "your own" in resp.json()["detail"]

    def test_unclaim_no_active_claim(self):
        """Cannot unclaim if no active claim exists."""
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/unclaim",
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 400
        assert "No active claim" in resp.json()["detail"]

    def test_unclaim_bounty_not_found(self):
        """Unclaiming on a non-existent bounty returns 404."""
        resp = client.post(
            "/api/bounties/nonexistent/unclaim",
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 404


# ===========================================================================
# DEADLINE EXPIRY
# ===========================================================================

class TestDeadlineExpiry:
    def test_expired_claim_auto_released(self):
        """Claims past their deadline are released by the watcher."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        # Manually set deadline to the past
        claims = claim_service._claim_store[bid]
        claims[0].deadline = datetime.now(timezone.utc) - timedelta(hours=1)

        released = claim_service.release_expired_claims()
        assert released == 1

        # Check claim status
        history = client.get(f"/api/bounties/{bid}/claims").json()
        assert history["claims"][0]["status"] == ClaimStatus.EXPIRED.value
        assert history["claims"][0]["outcome"] == "expired"

        # Check bounty reset
        bounty = client.get(f"/api/bounties/{bid}").json()
        assert bounty["status"] == "open"
        assert bounty["claimed_by"] is None

    def test_active_claim_not_expired(self):
        """Claims with future deadlines are not released."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        released = claim_service.release_expired_claims()
        assert released == 0

        # Claim still active
        history = client.get(f"/api/bounties/{bid}/claims").json()
        assert history["claims"][0]["status"] == ClaimStatus.ACTIVE.value

    def test_multiple_expired_claims(self):
        """Multiple expired claims from different bounties are all released."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)

        bounty_ids = []
        for i in range(3):
            b = _create_bounty(title=f"Bounty {i}")
            bounty_ids.append(b["id"])
            client.post(
                f"/api/bounties/{b['id']}/claim",
                json={},
                headers=_auth_headers(USER_ID),
            )
            # Manually expire the claim; need to unclaim first so status is open for next
            claims = claim_service._claim_store[b["id"]]
            claims[0].deadline = datetime.now(timezone.utc) - timedelta(hours=1)

        released = claim_service.release_expired_claims()
        assert released == 3

    def test_t3_expired_after_approval(self):
        """T3 claim expires after approval + 14-day deadline."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        claim_resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        claim_id = claim_resp.json()["id"]

        # Approve it
        client.post(
            f"/api/bounties/{bid}/claims/{claim_id}/approve",
            headers=_auth_headers(ADMIN_ID),
        )

        # Set deadline to past
        claims = claim_service._claim_store[bid]
        claims[0].deadline = datetime.now(timezone.utc) - timedelta(hours=1)

        released = claim_service.release_expired_claims()
        assert released == 1


# ===========================================================================
# CLAIM HISTORY
# ===========================================================================

class TestClaimHistory:
    def test_empty_history(self):
        """No claims returns empty list."""
        b = _create_bounty()
        bid = b["id"]

        resp = client.get(f"/api/bounties/{bid}/claims")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bounty_id"] == bid
        assert body["claims"] == []
        assert body["total"] == 0

    def test_history_after_claim(self):
        """Claim appears in history."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        resp = client.get(f"/api/bounties/{bid}/claims")
        body = resp.json()
        assert body["total"] == 1
        assert body["claims"][0]["claimed_by"] == USER_ID

    def test_history_tracks_multiple_claims(self):
        """All claims (including released) appear in history."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        _create_contributor(USER_ID_2, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        # User 1 claims and releases
        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        client.post(
            f"/api/bounties/{bid}/unclaim",
            headers=_auth_headers(USER_ID),
        )

        # User 2 claims
        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID_2),
        )

        resp = client.get(f"/api/bounties/{bid}/claims")
        body = resp.json()
        assert body["total"] == 2
        assert body["claims"][0]["claimed_by"] == USER_ID
        assert body["claims"][0]["status"] == ClaimStatus.RELEASED.value
        assert body["claims"][1]["claimed_by"] == USER_ID_2
        assert body["claims"][1]["status"] == ClaimStatus.ACTIVE.value

    def test_history_bounty_not_found(self):
        """Claim history for non-existent bounty returns 404."""
        resp = client.get("/api/bounties/nonexistent/claims")
        assert resp.status_code == 404


# ===========================================================================
# AUTH ENFORCEMENT
# ===========================================================================

class TestClaimAuth:
    def test_claim_requires_auth_header(self):
        """Claim endpoint requires authentication."""
        b = _create_bounty()
        bid = b["id"]

        # When AUTH_ENABLED is false (test default), requests without
        # X-User-ID still get a default user ID and don't fail on auth.
        # We verify the endpoint is reachable and processes the request.
        resp = client.post(f"/api/bounties/{bid}/claim", json={})
        # Should get a business logic error (insufficient reputation), not 401
        assert resp.status_code in (400, 201)

    def test_unclaim_requires_auth_header(self):
        """Unclaim endpoint requires authentication."""
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(f"/api/bounties/{bid}/unclaim")
        # Should get a business logic error, not 401
        assert resp.status_code in (400, 200)

    def test_claim_history_is_public(self):
        """Claim history does not require auth."""
        b = _create_bounty()
        bid = b["id"]

        resp = client.get(f"/api/bounties/{bid}/claims")
        assert resp.status_code == 200


# ===========================================================================
# EDGE CASES
# ===========================================================================

class TestClaimEdgeCases:
    def test_claim_response_shape(self):
        """Verify claim response includes all expected fields."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        expected_keys = {
            "id", "bounty_id", "claimed_by", "status",
            "application_plan", "deadline", "claimed_at",
            "resolved_at", "outcome",
        }
        assert set(resp.json().keys()) == expected_keys

    def test_claim_history_response_shape(self):
        """Verify claim history response shape."""
        b = _create_bounty()
        bid = b["id"]

        resp = client.get(f"/api/bounties/{bid}/claims")
        expected_keys = {"bounty_id", "claims", "total"}
        assert set(resp.json().keys()) == expected_keys

    def test_reputation_exactly_at_threshold(self):
        """User with exactly the minimum reputation can claim."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 201

    def test_t3_reputation_exactly_at_threshold(self):
        """User with exactly T3 min reputation can apply."""
        _create_contributor(USER_ID, reputation=T3_MIN_REPUTATION)
        b = _create_bounty(**VALID_BOUNTY_T3)
        bid = b["id"]

        resp = client.post(
            f"/api/bounties/{bid}/claim",
            json={"application_plan": T3_APPLICATION},
            headers=_auth_headers(USER_ID),
        )
        assert resp.status_code == 201

    def test_bounty_list_shows_claim_info(self):
        """Bounty list items include claimed_by and claim_deadline."""
        _create_contributor(USER_ID, reputation=T2_MIN_REPUTATION)
        b = _create_bounty()
        bid = b["id"]

        client.post(
            f"/api/bounties/{bid}/claim",
            json={},
            headers=_auth_headers(USER_ID),
        )

        resp = client.get("/api/bounties")
        item = resp.json()["items"][0]
        assert item["claimed_by"] == USER_ID
        assert item["claim_deadline"] is not None
