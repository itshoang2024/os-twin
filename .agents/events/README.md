# Orchestration Events

`OrchestrationEvents.psm1` owns the orchestration event envelope, validation,
live dashboard delivery, and optional JSONL audit/replay persistence. The module
does not spawn roles, mutate lifecycle projections, or write bot messages.

## Delivery

The default runtime path is live delivery to the dashboard WebSocket. Producers
send this message shape:

```json
{"type":"orchestration.event.ingest","data":{"event_type":"plan.run.started"}}
```

The dashboard validates, stores the event in its bounded in-memory buffer, and
rebroadcasts:

```json
{"type":"orchestration.event","data":{"event_type":"plan.run.started"}}
```

`OSTWIN_DASHBOARD_WS_URL` overrides the ingest endpoint. If unset, the module
uses `ws://127.0.0.1:${DASHBOARD_PORT:-3366}/api/ws`. Set
`OSTWIN_EVENT_WS_DISABLED=1` to disable live delivery in tests.

## Optional JSONL Audit

JSONL persistence is opt-in. Set `OSTWIN_EVENT_FILE_ENABLED=1` and pass a
non-empty `-EventsPath` to `Write-OrchestrationEvent` to append events to:

```text
<warrooms_dir>/events.jsonl
```

New plan and room configs no longer receive `events_path` by default. Legacy
explicit `events_path`, `-EventsPath`, and `OSTWIN_EVENTS_PATH` values are still
accepted so replay tests and older execution directories can be inspected.

## Envelope

Every event is a single compact JSON object per line. Required fields are:

- `v`
- `event_id`
- `event_type`
- `ts`
- `plan_id`
- `severity`
- `summary`
- `payload`

Room-scoped event types require `room_id` and `epic_ref`. Role run and role
assignment events also require `role` and `state`.

## Idempotency and replay

`event_id` is the idempotency key. `Write-OrchestrationEvent` stores a
`payload_hash` calculated from stable event content. Re-appending the same
`event_id` with the same stable payload returns the existing event and does not
append another line. Re-appending the same `event_id` with different content
throws an idempotency conflict.

Projection replayers must keep their own processed `event_id` set and skip IDs
already applied. Because duplicates are rejected at append time and replay code
can key by `event_id`, replaying an event stream twice must not duplicate
projection updates or bot notifications.

## Projection rule

Any caller updating room `status`, `progress.json`, role config JSON, dashboard
state, or bot notification state must append the causal event first. If append
fails, the projection update must not happen.
