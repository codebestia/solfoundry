"""Solana (Helius) webhook receiver.

Processes enriched transaction webhooks from Helius/Shyft to trigger
on-chain event webhooks for contributors.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.contributor_webhook_service import ContributorWebhookService
from app.services.solana_client import TREASURY_WALLET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/solana", tags=["webhooks"])


@router.post("/helius")
async def helius_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Handle enriched transaction webhooks from Helius.

    Maps on-chain transfers to/from the treasury to SolFoundry events:
    - Transfer to treasury -> escrow.locked or stake.deposited
    - Transfer from treasury -> escrow.released or stake.withdrawn
    """
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("Failed to parse Helius webhook JSON: %s", exc)
        return {"status": "error", "message": "Invalid JSON"}

    if not isinstance(payload, list):
        payload = [payload]

    wh_service = ContributorWebhookService(db)

    for tx in payload:
        signature = tx.get("signature")
        slot = tx.get("slot")
        # Enriched Transactions include tokenTransfers
        token_transfers: List[Dict[str, Any]] = tx.get("tokenTransfers", [])

        for transfer in token_transfers:
            mint = transfer.get("mint")
            from_user = transfer.get("fromUserAccount")
            to_user = transfer.get("toUserAccount")
            amount = transfer.get("tokenAmount")

            # 1. Escrow Lock / Stake Deposit
            if to_user == TREASURY_WALLET:
                # We record both events if applicable, or logic to distinguish them
                await wh_service.dispatch_event(
                    event="escrow.locked",
                    bounty_id=None,  # Mapping back to bounty_id would require DB lookup by amount/creator
                    data={
                        "from": from_user,
                        "amount": amount,
                        "mint": mint,
                        "type": "deposit",
                    },
                    tx_signature=signature,
                    slot=slot,
                )
                await wh_service.dispatch_event(
                    event="stake.deposited",
                    bounty_id=None,
                    data={
                        "staker": from_user,
                        "amount": amount,
                        "mint": mint,
                    },
                    tx_signature=signature,
                    slot=slot,
                )

            # 2. Escrow Release / Stake Withdrawal
            elif from_user == TREASURY_WALLET:
                await wh_service.dispatch_event(
                    event="escrow.released",
                    bounty_id=None,
                    data={
                        "to": to_user,
                        "amount": amount,
                        "mint": mint,
                        "type": "release",
                    },
                    tx_signature=signature,
                    slot=slot,
                )
                await wh_service.dispatch_event(
                    event="stake.withdrawn",
                    bounty_id=None,
                    data={
                        "staker": to_user,
                        "amount": amount,
                        "mint": mint,
                    },
                    tx_signature=signature,
                    slot=slot,
                )

    return {"status": "ok"}
