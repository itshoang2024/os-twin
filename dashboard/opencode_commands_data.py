"""
opencode_commands_data.py — Embedded markdown bodies for OpenCode slash commands.

Each entry maps a command name to its frontmatter fields and markdown body.
Consumed by `dashboard.opencode_tools.generate_all()` to write
`.opencode/commands/<name>.md` files into the project root.

This file is the single source of truth for Ostwin's OpenCode commands.
Re-running the generator on any machine produces an identical command set.
"""

from __future__ import annotations

COMMANDS: dict[str, dict[str, str]] = {
    'menu': {
        "description": 'Main control center: list available slash commands',
        "agent": 'ostwin',
        "body": 'Print the Ostwin command menu, grouped by category. Do not call any tool.\n\nPlans:\n- /draft <idea> - Draft a new Plan with AI\n- /edit [plan_id] [instruction] - Refine an existing plan\n- /viewplan <plan_id> - View plan content\n- /startplan <plan_id> - Launch a plan into war-rooms\n- /resume <plan_id> - Resume a failed or stopped plan\n- /assets <plan_id> - List assets for a plan\n- /plans - List all plans\n\nMonitoring: /rooms, /logs, /health (see /help)\nSkills: /skills <query>\nSystem: /setdir, /cancel, /clear, /feedback, /help, /menu\n\nTip: run /help for the full reference.\n',
    },
    'help': {
        "description": 'Detailed Ostwin user guide',
        "agent": 'ostwin',
        "body": 'Print the Ostwin help reference. Do not call any tool.\n\nPlans:\n- /draft <idea> - AI drafts a new plan from your idea.\n- /edit [plan_id] [instruction] - Refine a plan; lists plans if args are empty.\n- /viewplan <plan_id> - Show plan markdown content and status.\n- /startplan <plan_id> - Launch the plan; spawns war-room agents.\n- /resume <plan_id> - Resume a failed or stopped plan.\n- /plans - List all plans.\n- /assets <plan_id> - List output assets produced by a plan.\n\nSystem:\n- /setdir <path>, /cancel, /clear, /feedback <text>.\n',
    },
    'draft': {
        "description": 'Draft a new Plan with AI',
        "agent": 'ostwin',
        "body": 'Draft a new Ostwin plan from this idea: $ARGUMENTS\n\nIf $ARGUMENTS is empty, ask the user for a one-paragraph idea and stop.\nOtherwise, call the `ostwin_create_plan` tool with `{"idea": "$ARGUMENTS"}`.\nAfter it returns, summarize the resulting plan structure (title, epics, key tasks) in 1-2 short paragraphs and print the plan_id so the user can /viewplan or /startplan it.\n',
    },
    'edit': {
        "description": 'Select and refine an existing plan',
        "agent": 'ostwin',
        "body": 'Refine an Ostwin plan. Raw args: $ARGUMENTS\n\nIf $ARGUMENTS is empty, call `ostwin_list_plans` and ask the user which plan_id to edit and what change to apply.\nIf $1 is a plan_id and $2.. is an instruction, call `ostwin_refine_plan` with `{"plan_id": "$1", "instruction": "...rest of $ARGUMENTS..."}`.\nReport the refined plan summary in 1-2 sentences.\n',
    },
    'viewplan': {
        "description": "View a plan's content and status",
        "agent": 'ostwin',
        "body": 'Show the plan whose id is: $ARGUMENTS\n\nIf $ARGUMENTS is empty, call `ostwin_list_plans` and ask which plan to view.\nOtherwise:\n1. Call `ostwin_get_plan_status` with `{"plan_id": "$ARGUMENTS"}` for epics and war-room info.\n2. Fetch the plan markdown via:\n   !`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/plans/$ARGUMENTS`\n3. Present the plan title, status, and a condensed view of epics plus the first ~30 lines of content.\n',
    },
    'startplan': {
        "description": 'Launch a plan into war-rooms',
        "agent": 'ostwin',
        "body": 'Launch the plan: $ARGUMENTS\n\nIf $ARGUMENTS is empty, call `ostwin_list_plans` and ask which plan_id to launch.\nOtherwise call `ostwin_launch_plan` with `{"plan_id": "$ARGUMENTS"}`.\nReport which war-rooms were created and remind the user they can run /rooms or /logs to monitor progress.\n',
    },
    'resume': {
        "description": 'Resume a failed or stopped plan',
        "agent": 'ostwin',
        "body": 'Resume the plan: $ARGUMENTS\n\nIf $ARGUMENTS is empty, call `ostwin_list_plans` and ask which plan_id to resume (typically one in a failed or stopped state).\nOtherwise call `ostwin_resume_plan` with `{"plan_id": "$ARGUMENTS"}`.\nReport the resume outcome and next-step war-rooms in 1-2 sentences.\n',
    },
    'assets': {
        "description": 'List assets produced by a plan',
        "agent": 'ostwin',
        "body": 'List assets for plan: $ARGUMENTS\n\nIf $ARGUMENTS is empty, call `ostwin_list_plans` and ask which plan_id to inspect.\nOtherwise call `ostwin_get_plan_assets` with `{"plan_id": "$ARGUMENTS"}`.\nGroup the output by asset type and show name, path, and size where available.\n',
    },
    'setdir': {
        "description": 'Set target project directory (env hint)',
        "agent": 'ostwin',
        "body": 'Requested project directory: $ARGUMENTS\n\nOpenCode commands cannot mutate connector-side session state. To target this directory for new plans, export it in the shell that runs OpenCode and the Ostwin manager:\n\n    export OSTWIN_PROJECT_DIR="$ARGUMENTS"\n\nThen rerun /draft. Confirm to the user that nothing was changed server-side and that the env var must be set before relaunching.\n',
    },
    'cancel': {
        "description": 'Exit the current editing session',
        "agent": 'ostwin',
        "body": "Print this acknowledgment and do not call any tool:\n\nThere is no per-message editing session in OpenCode the way the Discord/Telegram bots track one. Any in-flight /edit prompt is simply dropped if you move on. If you want a fully fresh conversation, use OpenCode's /new command.\n",
    },
    'clear': {
        "description": 'Clear conversation history (OpenCode hint)',
        "agent": 'ostwin',
        "body": "Print this notice and do not call any tool:\n\nOstwin does not manage your OpenCode session memory. To clear conversation history, use OpenCode's built-in /new command to start a fresh session, or /share to fork it. Server-side plans, war-rooms, and assets are unaffected.\n",
    },
    'feedback': {
        "description": 'Send feedback to the Ostwin team',
        "agent": 'ostwin',
        "body": 'Submit user feedback: $ARGUMENTS\n\nIf $ARGUMENTS is empty, ask the user what feedback to send and stop.\nOtherwise POST it to the dashboard:\n\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" -H "Content-Type: application/json" -d "{\\"text\\": \\"$ARGUMENTS\\"}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/feedback`\n\nConfirm to the user whether the request succeeded based on the response.\n',
    },
    'plans': {
        "description": 'List all project plans',
        "agent": 'ostwin',
        "body": 'Call the `ostwin_list_plans` tool with no arguments and print a compact table of plan_id, title, status, and last-updated time. Suggest /viewplan <id> or /startplan <id> as follow-ups.\n',
    },
    'dashboard': {
        "description": 'Real-time War-Room dashboard',
        "agent": 'ostwin',
        "body": 'Show the real-time War-Room dashboard.\n\nCall `ostwin_get_war_room_status` and render a concise table of rooms (room_id, epic_ref, status, message_count) plus the summary counts.\n\nDashboard tunnel: !`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/tunnel/status`\n\nIf the tunnel is active, surface the URL prominently so the user can open it.\n',
    },
    'status': {
        "description": 'List running War-Rooms',
        "agent": 'ostwin',
        "body": 'Show the current War-Room status (short form).\n\nCall `ostwin_get_war_room_status` and present a concise list of room_id, epic_ref, status. Append the summary counts (total, running, completed, failed) on the last line.\n\nKeep the output compact - one row per room, no per-message detail.\n',
    },
    'errors': {
        "description": 'Error summary with root causes',
        "agent": 'ostwin',
        "body": 'Summarize war-room errors with root causes.\n\nSteps:\n1. Call `ostwin_get_war_room_status` and filter rooms whose status is `failed-final` or `failed`.\n2. For each failed room, call `ostwin_get_logs` with `{room_id, limit: 5}`.\n3. For each, report: room_id, epic_ref, status, and a one-line root-cause summary inferred from the recent logs.\n\nIf no failures, say so explicitly.\n',
    },
    'logs': {
        "description": 'View war-room channel messages',
        "agent": 'ostwin',
        "body": 'Show recent channel messages for a war-room.\n\nArgs: `$ARGUMENTS` is the room_id (for example `room-001`). If empty, ask the user for a room_id.\n\nCall `ostwin_get_logs` with `{room_id: $ARGUMENTS, limit: 10}` and render the messages in chronological order with sender, timestamp, and message text.\n',
    },
    'health': {
        "description": 'System health check',
        "agent": 'ostwin',
        "body": 'Run a system health check.\n\nCall `ostwin_get_health` and report manager status, bot status, and per-room health. Flag any component that is not healthy and suggest the next step (restart, inspect logs, etc.).\n',
    },
    'progress': {
        "description": 'Plan progress bars',
        "agent": 'ostwin',
        "body": 'Show progress bars for all plans.\n\nCall `ostwin_list_plans`. For each plan, render an ASCII progress bar 12 characters wide using `pct_complete`:\n\n`plan_id  [####--------]  33%  title`\n\nFilled cells use `#`, empty cells use `-`. Sort by `pct_complete` descending. If no plans exist, say so.\n',
    },
    'skills': {
        "description": 'View installed AI skills',
        "agent": 'ostwin',
        "body": 'List the installed Ostwin skills.\n\nHere is the current skills list:\n!`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/skills`\n\nPresent each skill tersely: name, category, and a one-line description. If the list is empty, say so plainly.\n',
    },
    'skillsearch': {
        "description": 'Search the ClawHub skill marketplace',
        "agent": 'ostwin',
        "body": 'Search ClawHub for skills matching the user\'s query.\n\nQuery: $ARGUMENTS\n\nCall the `ostwin_search_skills` tool with `{"query": "$ARGUMENTS"}`. Present results as a short list with slug, title, and a one-line summary. If nothing matches, suggest refining the query.\n',
    },
    'skillinstall': {
        "description": 'Install a skill from ClawHub by slug',
        "agent": 'ostwin',
        "body": 'Install the ClawHub skill specified by the user.\n\nSlug: $ARGUMENTS\n\nIf $ARGUMENTS is empty, ask for a slug and stop. Otherwise install via:\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" -H "X-Confirm-Install: true" -H "Content-Type: application/json" -d "{\\"skill_name\\": \\"$ARGUMENTS\\"}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/skills/clawhub-install`\n\nReport success or the error message returned.\n',
    },
    'skillremove': {
        "description": 'Remove an installed skill',
        "agent": 'ostwin',
        "body": 'Remove the installed skill named by the user.\n\nSkill: $ARGUMENTS\n\nIf $ARGUMENTS is empty, ask for the skill name and stop. Otherwise call:\n!`curl -sf -X DELETE -H "X-API-Key: ${OSTWIN_API_KEY}" "http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/skills/$ARGUMENTS?force=false"`\n\nReport whether removal succeeded.\n',
    },
    'skillsync': {
        "description": 'Sync skills with the dashboard',
        "agent": 'ostwin',
        "body": 'Sync the installed skills with the dashboard.\n\nResult:\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/skills/sync`\n\nSummarize what was added, removed, or updated.\n',
    },
    'roles': {
        "description": 'List all agent roles',
        "agent": 'ostwin',
        "body": 'List configured agent roles.\n\nRoles:\n!`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/roles`\n\nPresent each role\'s name and a one-line description.\n',
    },
    'triage': {
        "description": 'Triage a failed war-room',
        "agent": 'ostwin',
        "body": 'Triage a failed war-room.\n\nRoom ID: $ARGUMENTS\n\nIf $ARGUMENTS is empty, ask for the room_id and stop. Otherwise call:\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" "http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/rooms/$ARGUMENTS/action?action=triage"`\n\nReport the triage outcome and any recommended next steps.\n',
    },
    'clearplans': {
        "description": 'Wipe all plan data (destructive)',
        "agent": 'ostwin',
        "body": 'This permanently wipes ALL plan data. Confirmation required.\n\nUser input: $ARGUMENTS\n\nIf $ARGUMENTS is not exactly `YES`, print: "Destructive action. Re-run `/clearplans YES` to confirm." and stop. Otherwise call:\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/plans/clear`\n\nReport success or the error returned.\n',
    },
    'new': {
        "description": 'Wipe old War-Room data to start fresh (destructive)',
        "agent": 'ostwin',
        "body": 'This permanently wipes ALL war-room data. Confirmation required.\n\nUser input: $ARGUMENTS\n\nIf $ARGUMENTS is not exactly `YES`, print: "Destructive action. Re-run `/new YES` to confirm." and stop. Otherwise call:\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/rooms/clear`\n\nReport success or the error returned.\n',
    },
    'restart': {
        "description": 'Reboot the Command Center background process (destructive)',
        "agent": 'ostwin',
        "body": 'This restarts the Ostwin manager process. Confirmation required.\n\nUser input: $ARGUMENTS\n\nIf $ARGUMENTS is not exactly `YES`, print: "Destructive action. Re-run `/restart YES` to confirm." and stop. Otherwise call:\n!`curl -sf -X POST -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/manager/restart`\n\nReport whether the restart was accepted.\n',
    },
    'launchdashboard': {
        "description": 'Show dashboard access info / URL',
        "agent": 'ostwin',
        "body": 'Provide the dashboard access URL.\n\nTunnel status:\n!`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/tunnel/status`\n\nIf the tunnel is active, present its public URL. Otherwise fall back to `http://localhost:${DASHBOARD_PORT:-3366}`.\n',
    },
    'preferences': {
        "description": 'View notification preferences',
        "agent": 'ostwin',
        "body": 'Show current notification preferences.\n\nSettings:\n!`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/settings`\n\nExtract notification-related fields (channels, quiet hours, severity filters, etc.) and present them as a short list. Mention how to change them via the dashboard.\n',
    },
    'subscriptions': {
        "description": 'View event subscription toggles',
        "agent": 'ostwin',
        "body": 'Show current event subscription toggles.\n\nSettings:\n!`curl -sf -H "X-API-Key: ${OSTWIN_API_KEY}" http://127.0.0.1:${DASHBOARD_PORT:-3366}/api/settings`\n\nExtract subscription-related fields (event types the user is subscribed to and their on/off state) and present them as a short list. Mention how to toggle them via the dashboard or settings API.\n',
    },
}
