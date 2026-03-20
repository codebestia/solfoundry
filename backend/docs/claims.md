# Bounty Claim API

Endpoints for claiming, releasing, and managing T2/T3 bounty claims.

## Tier Rules

| Tier | Claimable? | Min Reputation | Deadline | Approval |
|------|-----------|---------------|----------|----------|
| T1   | ❌ No      | —             | —        | —        |
| T2   | ✅ Yes     | 10            | 7 days   | Auto     |
| T3   | ✅ Yes     | 50            | 14 days  | Admin    |

---

## Endpoints

### `POST /api/bounties/{id}/claim`

Claim a bounty. **Auth required.**

**Request body:**

```json
{
  "application_plan": "string (required for T3, optional for T2)"
}
```

**T2 behavior:**
- Claim is immediately `active` with a 7-day deadline
- Bounty status → `in_progress`

**T3 behavior:**
- Claim enters `pending_approval` — no deadline yet
- Bounty stays `open` until admin approves

**Errors:**

| Status | Condition |
|--------|-----------|
| 400    | T1 bounty (not claimable) |
| 400    | Insufficient reputation |
| 400    | Bounty already claimed |
| 400    | T3 missing `application_plan` |
| 400    | Bounty not in `open` status |
| 404    | Bounty not found |

---

### `POST /api/bounties/{id}/unclaim`

Release your active claim. **Auth required.**

Resets bounty to `open` status. The claim is recorded with outcome `"released"`.

**Errors:**

| Status | Condition |
|--------|-----------|
| 400    | Not the claimer |
| 400    | No active claim |
| 404    | Bounty not found |

---

### `GET /api/bounties/{id}/claims`

View claim history. **Public.**

Returns all claims (active, released, expired, completed).

```json
{
  "bounty_id": "uuid",
  "claims": [
    {
      "id": "uuid",
      "bounty_id": "uuid",
      "claimed_by": "username",
      "status": "active | pending_approval | released | expired | completed",
      "application_plan": "string | null",
      "deadline": "ISO 8601 | null",
      "claimed_at": "ISO 8601",
      "resolved_at": "ISO 8601 | null",
      "outcome": "released | expired | completed | null"
    }
  ],
  "total": 1
}
```

---

### `POST /api/bounties/{id}/claims/{claim_id}/approve`

Admin approves a T3 application. **Auth required.**

Moves claim `pending_approval → active`, sets 14-day deadline, bounty → `in_progress`.

**Errors:**

| Status | Condition |
|--------|-----------|
| 400    | Claim not in `pending_approval` |
| 404    | Bounty or claim not found |

---

## Deadline Watcher

A Celery beat task runs every hour to scan active claims. Claims past their deadline are auto-released with outcome `"expired"`, and the bounty resets to `open`.

**Start the worker:**

```bash
celery -A app.celery_app worker --loglevel=info --beat
```

---

## GitHub Integration

When `GITHUB_TOKEN` is set, the system posts comments on the linked GitHub issue:

- **On claim:** `🔒 Claimed by @user — deadline: DATE`
- **On release:** `🔓 Released by @user (reason)`

Set the token: `export GITHUB_TOKEN=ghp_...`
