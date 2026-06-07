#!/usr/bin/env bash
set -euo pipefail

role="${AGENT_OS_ROLE:-unknown}"
workdir="$(pwd)"
room_dir="${AGENT_OS_ROOM_DIR:-}"

if [[ "$role" == "unknown" ]]; then
  cat <<'JSON'
{
  "nodes": [
    {
      "task_ref": "EPIC-001",
      "title": "Build a static Hello site",
      "role": "engineer",
      "candidate_roles": ["engineer"],
      "depends_on": [],
      "rationale": "Smoke test plan has an explicit engineer implementation role."
    }
  ],
  "topological_order": ["EPIC-001"]
}
JSON
  exit 0
fi

post_signal() {
  local type="$1"
  local body="$2"
  [[ -n "$room_dir" ]] || return 0
  local ref="SMOKE"
  if [[ -f "$room_dir/task-ref" ]]; then
    ref="$(tr -d '\r\n' < "$room_dir/task-ref")"
  fi
  python3 - "$room_dir" "$role" "$type" "$ref" "$body" <<'PY'
import datetime
import json
import pathlib
import sys
import uuid

room_dir = pathlib.Path(sys.argv[1])
role = sys.argv[2]
msg_type = sys.argv[3]
ref = sys.argv[4]
body = sys.argv[5]
message = {
    "v": 1,
    "id": f"{role}-{msg_type}-{uuid.uuid4().hex}",
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "from": role,
    "to": "manager",
    "type": msg_type,
    "ref": ref,
    "body": body,
}
with (room_dir / "channel.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(message, separators=(",", ":")) + "\n")
PY
}

case "$role" in
  architect)
    post_signal "pass" "VERDICT: PASS. APPROVED smoke plan."
    printf '%s\n' "VERDICT: PASS" "APPROVED smoke plan."
    ;;
  engineer)
    cat > "$workdir/index.html" <<'HTML'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Ostwin Smoke Test</title>
  </head>
  <body>
    <main>Hello this is OsTwin</main>
  </body>
</html>
HTML
    cat > "${AGENT_OS_ROOM_DIR}/TASKS.md" <<'TASKS'
- [x] TASK-001 - Create a static HTML smoke page
TASKS
    post_signal "done" "VERDICT: DONE. Created index.html with Hello this is OsTwin."
    printf '%s\n' "VERDICT: DONE" "Created index.html with Hello this is OsTwin."
    ;;
  qa)
    grep -q "Hello this is OsTwin" "$workdir/index.html"
    post_signal "pass" "VERDICT: PASS. QA verified index.html contains Hello this is OsTwin."
    printf '%s\n' "VERDICT: DONE" "QA verified index.html contains Hello this is OsTwin."
    ;;
  *)
    printf '%s\n' "VERDICT: DONE" "Smoke mock no-op for role: $role"
    ;;
esac
