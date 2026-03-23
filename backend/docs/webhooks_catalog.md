# Webhook Event Catalog

This document describes the events and payload schemas for SolFoundry's outbound webhook system.

## Authentication
All webhook POST requests include an `X-SolFoundry-Signature` header.
This is an `HMAC-SHA256` hash of the raw JSON body, signed with your webhook secret.
The header value is prefixed with `sha256=`.

## Payload Structure

### Single Event (Legacy/Standard)
Non-batched deliveries (if any) or internal representations use this structure:
```json
{
  "event": "bounty.claimed",
  "bounty_id": "...",
  "timestamp": "2026-03-23T02:49:33Z",
  "tx_signature": null,
  "slot": null,
  "data": { ... }
}
```

### Batched Delivery (Default)
Outbound webhooks are batched every 5 seconds. The payload is a `WebhookBatchPayload`:
```json
{
  "webhook_id": "...",
  "batch_id": "...",
  "timestamp": "2026-03-23T02:49:33Z",
  "events": [
    {
      "event": "...",
      "bounty_id": "...",
      "timestamp": "...",
      "tx_signature": "...",
      "slot": 123456,
      "data": { ... }
    }
  ]
}
```

## Event Types

### `escrow.locked`
Triggered when funds are transferred to the treasury for a bounty or escrow.
- **Data**:
  - `from`: Sender wallet address.
  - `amount`: Token amount (string).
  - `mint`: Token mint address.
  - `type`: "deposit"

### `escrow.released`
Triggered when funds are released from the treasury to a contributor.
- **Data**:
  - `to`: Recipient wallet address.
  - `amount`: Token amount (string).
  - `mint`: Token mint address.
  - `type`: "release"

### `reputation.updated`
Triggered when a contributor's reputation score changes.
- **Data**:
  - `new_score`: The updated reputation score.
  - `earned`: Points earned in the triggering action.
  - `badge`: New badge/rank name.

### `stake.deposited`
Triggered when a user deposits tokens as a stake.
- **Data**:
  - `staker`: User wallet address.
  - `amount`: Token amount (string).
  - `mint`: Token mint address.

### `stake.withdrawn`
Triggered when a user withdraws their stake.
- **Data**:
  - `staker`: User wallet address.
  - `amount`: Token amount (string).
  - `mint`: Token mint address.

### `bounty.paid`
Triggered when a bounty payout is confirmed on-chain.
- **Data**:
  - `payout_id`: Internal payout ID.
  - `amount`: Amount paid.
  - `tx_hash`: Transaction signature.

### `test.ping`
Sent when using the "Test Webhook" feature.
- **Data**:
  - `message`: "Verification successful!"
