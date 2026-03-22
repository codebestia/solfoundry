"""Tests for the staking API endpoints and tier/reward unit logic."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.models.staking import (
    StakingPositionResponse, StakingHistoryResponse,
    StakingEventResponse, StakingStats,
)

client = TestClient(app)

WALLET = "Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SIG = "sig_abc123"


def _position(staked=0.0, tier="none", cooldown_active=False,
               unstake_ready=False, unstake_amount=0.0, rewards_available=0.0):
    return StakingPositionResponse(
        wallet_address=WALLET, staked_amount=staked, tier=tier,
        apy=0.05 if tier == "bronze" else 0.0, rep_boost=1.0,
        staked_at=None, last_reward_claim=None, rewards_earned=0.0,
        rewards_available=rewards_available, cooldown_started_at=None,
        cooldown_ends_at=None, cooldown_active=cooldown_active,
        unstake_ready=unstake_ready, unstake_amount=unstake_amount,
    )


def _history(items=None):
    items = items or []
    return StakingHistoryResponse(items=items, total=len(items))


def _event(event_type="stake"):
    return StakingEventResponse(
        id="evt-001", wallet_address=WALLET, event_type=event_type,
        amount=1000.0, rewards_amount=None, signature=SIG,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class TestGetPosition:
    def test_returns_zero_state_for_unknown_wallet(self):
        with patch("app.services.staking_service.get_position", new=AsyncMock(return_value=_position())):
            r = client.get(f"/api/staking/position/{WALLET}")
        assert r.status_code == 200
        assert r.json()["staked_amount"] == 0.0
        assert r.json()["tier"] == "none"

    def test_returns_active_position(self):
        with patch("app.services.staking_service.get_position",
                   new=AsyncMock(return_value=_position(staked=5000.0, tier="bronze"))):
            r = client.get(f"/api/staking/position/{WALLET}")
        assert r.status_code == 200
        assert r.json()["tier"] == "bronze"

    def test_returns_diamond_tier(self):
        with patch("app.services.staking_service.get_position",
                   new=AsyncMock(return_value=_position(staked=100_000.0, tier="diamond"))):
            r = client.get(f"/api/staking/position/{WALLET}")
        assert r.json()["tier"] == "diamond"

    def test_cooldown_fields_present(self):
        pos = _position(staked=1000.0, tier="bronze", cooldown_active=True, unstake_amount=500.0)
        with patch("app.services.staking_service.get_position", new=AsyncMock(return_value=pos)):
            r = client.get(f"/api/staking/position/{WALLET}")
        assert r.json()["cooldown_active"] is True
        assert r.json()["unstake_amount"] == 500.0


class TestRecordStake:
    def test_valid_stake_returns_position(self):
        with patch("app.services.staking_service.record_stake",
                   new=AsyncMock(return_value=_position(staked=1000.0, tier="bronze"))):
            r = client.post("/api/staking/stake",
                            json={"wallet_address": WALLET, "amount": 1000.0, "signature": SIG})
        assert r.status_code == 200
        assert r.json()["staked_amount"] == 1000.0

    def test_missing_signature_returns_422(self):
        r = client.post("/api/staking/stake", json={"wallet_address": WALLET, "amount": 1000.0})
        assert r.status_code == 422

    def test_zero_amount_returns_422(self):
        r = client.post("/api/staking/stake",
                        json={"wallet_address": WALLET, "amount": 0.0, "signature": SIG})
        assert r.status_code == 422

    def test_service_valueerror_returns_400(self):
        with patch("app.services.staking_service.record_stake",
                   new=AsyncMock(side_effect=ValueError("duplicate signature"))):
            r = client.post("/api/staking/stake",
                            json={"wallet_address": WALLET, "amount": 100.0, "signature": SIG})
        assert r.status_code == 400
        body = r.json()
        assert "duplicate signature" in (body.get("detail") or body.get("message", ""))


class TestInitiateUnstake:
    def test_initiates_cooldown(self):
        pos = _position(staked=1000.0, tier="bronze", cooldown_active=True, unstake_amount=500.0)
        with patch("app.services.staking_service.initiate_unstake", new=AsyncMock(return_value=pos)):
            r = client.post("/api/staking/unstake/initiate",
                            json={"wallet_address": WALLET, "amount": 500.0})
        assert r.status_code == 200
        assert r.json()["cooldown_active"] is True

    def test_no_position_returns_400(self):
        with patch("app.services.staking_service.initiate_unstake",
                   new=AsyncMock(side_effect=ValueError("No staked position found"))):
            r = client.post("/api/staking/unstake/initiate",
                            json={"wallet_address": WALLET, "amount": 100.0})
        assert r.status_code == 400

    def test_amount_exceeds_stake_returns_400(self):
        with patch("app.services.staking_service.initiate_unstake",
                   new=AsyncMock(side_effect=ValueError("Cannot unstake"))):
            r = client.post("/api/staking/unstake/initiate",
                            json={"wallet_address": WALLET, "amount": 9999.0})
        assert r.status_code == 400


class TestCompleteUnstake:
    def test_completes_after_cooldown(self):
        with patch("app.services.staking_service.complete_unstake",
                   new=AsyncMock(return_value=_position(staked=500.0, unstake_ready=True))):
            r = client.post("/api/staking/unstake/complete",
                            json={"wallet_address": WALLET, "signature": SIG})
        assert r.status_code == 200

    def test_cooldown_not_done_returns_400(self):
        with patch("app.services.staking_service.complete_unstake",
                   new=AsyncMock(side_effect=ValueError("Cooldown not complete"))):
            r = client.post("/api/staking/unstake/complete",
                            json={"wallet_address": WALLET, "signature": SIG})
        assert r.status_code == 400
        body = r.json()
        assert "Cooldown" in (body.get("detail") or body.get("message", ""))

    def test_no_unstake_in_progress_returns_400(self):
        with patch("app.services.staking_service.complete_unstake",
                   new=AsyncMock(side_effect=ValueError("No unstake in progress"))):
            r = client.post("/api/staking/unstake/complete",
                            json={"wallet_address": WALLET, "signature": SIG})
        assert r.status_code == 400


class TestClaimRewards:
    def test_claim_returns_amount(self):
        with patch("app.services.staking_service.claim_rewards",
                   new=AsyncMock(return_value=(_position(staked=1000.0, tier="bronze"), 12.34))):
            r = client.post("/api/staking/claim", json={"wallet_address": WALLET})
        assert r.status_code == 200
        assert r.json()["amount_claimed"] == pytest.approx(12.34)

    def test_no_rewards_returns_400(self):
        with patch("app.services.staking_service.claim_rewards",
                   new=AsyncMock(side_effect=ValueError("No rewards available"))):
            r = client.post("/api/staking/claim", json={"wallet_address": WALLET})
        assert r.status_code == 400

    def test_no_position_returns_400(self):
        with patch("app.services.staking_service.claim_rewards",
                   new=AsyncMock(side_effect=ValueError("No active staking position"))):
            r = client.post("/api/staking/claim", json={"wallet_address": WALLET})
        assert r.status_code == 400


class TestGetHistory:
    def test_returns_paginated_events(self):
        history = _history([_event("stake"), _event("reward_claimed")])
        with patch("app.services.staking_service.get_history", new=AsyncMock(return_value=history)):
            r = client.get(f"/api/staking/history/{WALLET}")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_empty_history(self):
        with patch("app.services.staking_service.get_history", new=AsyncMock(return_value=_history())):
            r = client.get(f"/api/staking/history/{WALLET}")
        assert r.json()["total"] == 0

    def test_limit_capped_at_100(self):
        with patch("app.services.staking_service.get_history",
                   new=AsyncMock(return_value=_history())) as mock_fn:
            client.get(f"/api/staking/history/{WALLET}?limit=999")
            mock_fn.assert_called_once_with(WALLET, 100, 0)

    def test_offset_applied(self):
        with patch("app.services.staking_service.get_history",
                   new=AsyncMock(return_value=_history())) as mock_fn:
            client.get(f"/api/staking/history/{WALLET}?limit=10&offset=20")
            mock_fn.assert_called_once_with(WALLET, 10, 20)


class TestGetStats:
    def test_returns_global_stats(self):
        stats = StakingStats(
            total_staked=500_000.0, total_stakers=42, total_rewards_paid=1234.5,
            avg_apy=0.09,
            tier_distribution={"bronze": 20, "silver": 15, "gold": 5, "diamond": 2, "none": 0},
        )
        with patch("app.services.staking_service.get_platform_stats", new=AsyncMock(return_value=stats)):
            r = client.get("/api/staking/stats")
        assert r.status_code == 200
        assert r.json()["total_stakers"] == 42

    def test_empty_stats(self):
        stats = StakingStats(
            total_staked=0.0, total_stakers=0, total_rewards_paid=0.0, avg_apy=0.0,
            tier_distribution={"bronze": 0, "silver": 0, "gold": 0, "diamond": 0, "none": 0},
        )
        with patch("app.services.staking_service.get_platform_stats", new=AsyncMock(return_value=stats)):
            r = client.get("/api/staking/stats")
        assert r.json()["total_stakers"] == 0


class TestTierLogic:
    def test_no_tier_below_minimum(self):
        from app.models.staking import get_tier
        assert get_tier(Decimal("999"))["tier"] == "none"

    def test_bronze_tier(self):
        from app.models.staking import get_tier
        assert get_tier(Decimal("1000"))["tier"] == "bronze"

    def test_silver_tier(self):
        from app.models.staking import get_tier
        assert get_tier(Decimal("10000"))["tier"] == "silver"

    def test_gold_tier(self):
        from app.models.staking import get_tier
        assert get_tier(Decimal("50000"))["tier"] == "gold"

    def test_diamond_tier(self):
        from app.models.staking import get_tier
        result = get_tier(Decimal("100000"))
        assert result["tier"] == "diamond"
        assert result["rep_boost"] == 2.0

    def test_rewards_zero_for_zero_staked(self):
        from app.models.staking import calculate_rewards
        now = datetime.now(timezone.utc)
        assert calculate_rewards(Decimal("0"), 0.05, now - timedelta(days=30), now) == Decimal("0")

    def test_rewards_accrue_over_year(self):
        from app.models.staking import calculate_rewards
        now = datetime.now(timezone.utc)
        result = calculate_rewards(Decimal("10000"), 0.08, now - timedelta(days=365), now)
        assert 790 < float(result) < 810
