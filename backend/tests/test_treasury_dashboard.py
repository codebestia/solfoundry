"""Tests for the Treasury Dashboard API endpoints.

Covers: auth gating (401/403/503), overview, flow series,
transactions, tier spending, and CSV export.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

ADMIN_KEY = "test-treasury-admin-key"
HEADERS = {"Authorization": f"Bearer {ADMIN_KEY}"}

# Patch target for the module-level key variable
_KEY_PATCH = "app.api.treasury_dashboard._ADMIN_API_KEY"

client = TestClient(app)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_no_token_returns_401(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            r = client.get("/api/treasury-dashboard/overview")
        assert r.status_code == 401

    def test_wrong_token_returns_403(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            r = client.get(
                "/api/treasury-dashboard/overview",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert r.status_code == 403

    def test_missing_env_key_returns_503(self):
        with patch(_KEY_PATCH, ""):
            r = client.get(
                "/api/treasury-dashboard/overview",
                headers={"Authorization": "Bearer anything"},
            )
        assert r.status_code == 503

    def test_valid_token_not_401_403(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            with patch("app.api.treasury_dashboard.get_treasury_stats", new=AsyncMock(return_value=MagicMock(
                fndry_balance=0.0, sol_balance=0.0, total_paid_out_fndry=0.0,
                total_paid_out_sol=0.0, total_payouts=0, total_buybacks=0,
            ))):
                with _mock_db_session(0.0):
                    r = client.get("/api/treasury-dashboard/overview", headers=HEADERS)
        assert r.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# DB session mock helpers
# ---------------------------------------------------------------------------


def _mock_db_session(scalar_value=0.0):
    """Return a context manager patch for get_db_session returning scalar_value."""
    mock_ctx = MagicMock()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one = MagicMock(return_value=scalar_value)
    mock_result.fetchall.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("app.api.treasury_dashboard.get_db_session", return_value=mock_ctx)


def _mock_db_session_multi(*results):
    """Return a patch where successive execute() calls return successive results."""
    mock_ctx = MagicMock()
    mock_session = AsyncMock()
    call_count = [0]

    async def side_effect(*args, **kwargs):
        idx = min(call_count[0], len(results) - 1)
        call_count[0] += 1
        return results[idx]

    mock_session.execute = side_effect
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("app.api.treasury_dashboard.get_db_session", return_value=mock_ctx)


# ---------------------------------------------------------------------------
# GET /overview
# ---------------------------------------------------------------------------


class TestOverview:
    def test_returns_all_fields(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            with patch("app.api.treasury_dashboard.get_treasury_stats", new=AsyncMock(return_value=MagicMock(
                fndry_balance=1_000_000.0, sol_balance=42.5,
                total_paid_out_fndry=250_000.0, total_paid_out_sol=10.0,
                total_payouts=120, total_buybacks=5,
            ))):
                with _mock_db_session(25_000.0):
                    r = client.get("/api/treasury-dashboard/overview", headers=HEADERS)

        assert r.status_code == 200
        data = r.json()
        assert "fndry_balance" in data
        assert "runway_days" in data
        assert "burn_rate_daily" in data
        assert "burn_rate_weekly" in data
        assert "burn_rate_monthly" in data

    def test_runway_present_when_burning(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            with patch("app.api.treasury_dashboard.get_treasury_stats", new=AsyncMock(return_value=MagicMock(
                fndry_balance=1_000_000.0, sol_balance=0.0,
                total_paid_out_fndry=0.0, total_paid_out_sol=0.0,
                total_payouts=0, total_buybacks=0,
            ))):
                with _mock_db_session(30_000.0):  # 30k burned in 30 days = 1k/day
                    r = client.get("/api/treasury-dashboard/overview", headers=HEADERS)

        assert r.status_code == 200
        assert r.json()["runway_days"] is not None

    def test_runway_is_none_when_no_burn(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            with patch("app.api.treasury_dashboard.get_treasury_stats", new=AsyncMock(return_value=MagicMock(
                fndry_balance=500_000.0, sol_balance=0.0,
                total_paid_out_fndry=0.0, total_paid_out_sol=0.0,
                total_payouts=0, total_buybacks=0,
            ))):
                with _mock_db_session(0.0):
                    r = client.get("/api/treasury-dashboard/overview", headers=HEADERS)

        assert r.status_code == 200
        assert r.json()["runway_days"] is None


# ---------------------------------------------------------------------------
# GET /flow
# ---------------------------------------------------------------------------


class TestFlow:
    def _db(self):
        mock_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return patch("app.api.treasury_dashboard.get_db_session", return_value=mock_ctx)

    def test_daily_view(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/flow?view=daily", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["view"] == "daily"
        assert "points" in r.json()

    def test_weekly_view(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/flow?view=weekly", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["view"] == "weekly"

    def test_monthly_view(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/flow?view=monthly", headers=HEADERS)
        assert r.status_code == 200

    def test_invalid_view_returns_422(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            r = client.get("/api/treasury-dashboard/flow?view=yearly", headers=HEADERS)
        assert r.status_code == 422

    def test_no_token_returns_401(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            r = client.get("/api/treasury-dashboard/flow?view=daily")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /transactions
# ---------------------------------------------------------------------------


class TestTransactions:
    def _db(self, payout_rows=None, buyback_rows=None):
        payout_rows = payout_rows or []
        buyback_rows = buyback_rows or []

        mock_ctx = MagicMock()
        mock_session = AsyncMock()
        call_count = [0]

        count_result = MagicMock()
        count_result.fetchall.return_value = [(10,), (5,)]

        payout_result = MagicMock()
        payout_result.scalars.return_value.all.return_value = payout_rows

        buyback_result = MagicMock()
        buyback_result.scalars.return_value.all.return_value = buyback_rows

        async def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return count_result
            elif call_count[0] == 2:
                return payout_result
            return buyback_result

        mock_session.execute = side_effect
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return patch("app.api.treasury_dashboard.get_db_session", return_value=mock_ctx)

    def test_returns_transactions_and_total(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/transactions", headers=HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data

    def test_includes_payout_record(self):
        mock_payout = MagicMock()
        mock_payout.id = "payout-uuid"
        mock_payout.amount = 1000
        mock_payout.token = "FNDRY"
        mock_payout.recipient = "alice"
        mock_payout.tx_hash = "sig_abc"
        mock_payout.solscan_url = "https://solscan.io/tx/sig_abc"
        mock_payout.status = "confirmed"
        mock_payout.created_at = MagicMock(isoformat=lambda: "2026-03-21T00:00:00+00:00")

        with patch(_KEY_PATCH, ADMIN_KEY), self._db([mock_payout]):
            r = client.get("/api/treasury-dashboard/transactions", headers=HEADERS)
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1
        assert r.json()["items"][0]["type"] == "payout"

    def test_limit_param_accepted(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/transactions?limit=10", headers=HEADERS)
        assert r.status_code == 200

    def test_limit_over_200_returns_422(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            r = client.get("/api/treasury-dashboard/transactions?limit=999", headers=HEADERS)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /spending/tier
# ---------------------------------------------------------------------------


class TestSpendingTier:
    def _db(self, rows=None):
        rows = rows or []
        mock_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return patch("app.api.treasury_dashboard.get_db_session", return_value=mock_ctx)

    def test_returns_tier_breakdown(self):
        mock_row = MagicMock()
        mock_row.tier = "3"
        mock_row.total_fndry = 30000
        mock_row.payout_count = 10

        with patch(_KEY_PATCH, ADMIN_KEY), self._db([mock_row]):
            r = client.get("/api/treasury-dashboard/spending/tier", headers=HEADERS)

        assert r.status_code == 200
        data = r.json()
        assert "tiers" in data
        assert "total_fndry" in data
        assert len(data["tiers"]) == 1

    def test_period_days_default_30(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/spending/tier", headers=HEADERS)
        assert r.json()["period_days"] == 30

    def test_custom_period_days(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/spending/tier?period_days=7", headers=HEADERS)
        assert r.json()["period_days"] == 7

    def test_empty_results(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/spending/tier", headers=HEADERS)
        assert r.json()["total_fndry"] == 0.0
        assert r.json()["tiers"] == []


# ---------------------------------------------------------------------------
# GET /export.csv
# ---------------------------------------------------------------------------


class TestExportCsv:
    def _db(self):
        mock_ctx = MagicMock()
        mock_session = AsyncMock()
        call_count = [0]

        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []

        async def side_effect(*args, **kwargs):
            return empty

        mock_session.execute = side_effect
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return patch("app.api.treasury_dashboard.get_db_session", return_value=mock_ctx)

    def test_returns_csv_content_type(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/export.csv", headers=HEADERS)
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_csv_has_header_row(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/export.csv", headers=HEADERS)
        assert "id,type,amount" in r.text

    def test_csv_requires_auth(self):
        with patch(_KEY_PATCH, ADMIN_KEY):
            r = client.get("/api/treasury-dashboard/export.csv")
        assert r.status_code == 401

    def test_content_disposition_header(self):
        with patch(_KEY_PATCH, ADMIN_KEY), self._db():
            r = client.get("/api/treasury-dashboard/export.csv", headers=HEADERS)
        assert "attachment" in r.headers.get("content-disposition", "")
        assert ".csv" in r.headers.get("content-disposition", "")
