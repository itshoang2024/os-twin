---
name: dashboard-api
description: Use this skill to query the Ostwin dashboard REST API for plan status, war-room state, semantic search, and aggregate stats. Essential for answering user questions about project progress.
tags: [global, api, dashboard, context]

---

# dashboard-api

## Overview

The Ostwin dashboard exposes a REST API at `http://localhost:3366` (or `$DASHBOARD_URL`). All endpoints require an API key via the `X-API-Key` header (value from `$OSTWIN_API_KEY`).

This skill teaches agents how to query these endpoints to gather context about plans, war-rooms, and message history.

## When to Use

- When answering questions about project status, progress, or history
- When looking up what plans exist and their completion percentage
- When searching for specific topics across war-room messages
- When building context for user-facing summaries

## Authentication

All requests must include:
```
X-API-Key: <OSTWIN_API_KEY>
```

## Endpoints Reference

### 1. List Plans — `GET /api/plans`

Returns all plans with status, epic count, and progress.

**Response fields:**
| Field | Description |
|-------|-------------|
| `plan_id` | Unique plan identifier (hex string) |
| `title` | Plan title |
| `status` | `draft`, `launched`, `completed` |
| `epic_count` | Number of epics |
| `pct_complete` | Completion percentage (0–100) |
| `active_epics` | Currently active epic count |
| `completed_epics` | Finished epic count |

**Example:**
```bash
curl -H "X-API-Key: $OSTWIN_API_KEY" http://localhost:3366/api/plans
```

### 2. Get Plan Detail — `GET /api/plans/{plan_id}`

Returns full plan content, epics, and metadata.

**Response:** `{ "plan": {...}, "epics": [...] }`

### 3. List War-Rooms — `GET /api/rooms`

Returns all active war-rooms with current lifecycle state.

**Response fields per room:**
| Field | Description |
|-------|-------------|
| `room_id` | e.g. `room-001` |
| `epic_ref` | e.g. `EPIC-001` |
| `status` | Current lifecycle state |

### 4. Room Channel Messages — `GET /api/rooms/{room_id}/channel`

Returns messages in a war-room. Supports query params:
- `?from=engineer` — filter by sender role
- `?type=done` — filter by message type
- `?q=search+term` — text search
- `?limit=10` — max results

### 5. Room Analysis — `GET /api/rooms/{room_id}/analyze`

Returns stats and summary of a room's messages (counts by type, role, latest milestones).

### 6. Semantic Search — `GET /api/search`

Vector search across all indexed messages.

**Params:**
- `q` (required) — search query
- `room_id` — scope to a specific room
- `type` — filter by message type
- `limit` — max results (default 20)

**Example:**
```bash
curl -H "X-API-Key: $OSTWIN_API_KEY" \
  "http://localhost:3366/api/search?q=authentication+module&limit=5"
```

### 7. Aggregate Stats — `GET /api/stats`

Returns dashboard-wide statistics:
- `total_plans` — count with trend
- `active_epics` — count with sparkline
- `completion_rate` — percentage with trend
- `escalations_pending` — count of manager-triage rooms

### 8. Plan Epics — `GET /api/plans/{plan_id}/epics`

Returns epics for a specific plan with room status.

## Usage Pattern

To answer a user question about project status:

1. **Get stats** for high-level overview: `GET /api/stats`
2. **List plans** for specific plan data: `GET /api/plans`
3. **Semantic search** for relevant messages: `GET /api/search?q=<keywords>`
4. **Drill into rooms** for details: `GET /api/rooms/{room_id}/channel`

## Error Handling

- `401` — Missing or invalid API key
- `404` — Plan or room not found
- `503` — Vector search not available (dashboard not fully started)
