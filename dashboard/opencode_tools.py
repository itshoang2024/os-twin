"""
opencode_tools.py — Generate OpenCode custom tool files for the Ostwin project.

Creates `.opencode/tools/ostwin_*.ts`, `opencode.json`, and
`.opencode/commands/ostwin-plan.md` in the project root so the OpenCode
server discovers them on startup.

Usage:
  python -m dashboard.opencode_tools [--project-root DIR] [--dashboard-port PORT]

Called by:
  - The installer (setup-opencode.sh)
  - Dashboard startup (api.py lifespan)
  - start-opencode-server.sh (before launching opencode serve)

Idempotent: re-running overwrites existing files with fresh content.
"""

from __future__ import annotations

import json
import logging
import os
import textwrap
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DASHBOARD_PORT_DEFAULT = "3366"


def _resolve_project_root() -> Path:
    if env := os.environ.get("OSTWIN_PROJECT_DIR"):
        return Path(env)
    this_file = Path(__file__).resolve()
    for parent in this_file.parents:
        if (parent / ".agents").is_dir():
            return parent
    return this_file.parent.parent


def _api_helpers() -> str:
    return textwrap.dedent("""\
    import { tool } from "@opencode-ai/plugin"

    const PORT = () => process.env.DASHBOARD_PORT || "__PORT__"
    const BASE = () => `http://127.0.0.1:${PORT()}`
    const KEY = () => process.env.OSTWIN_API_KEY || ""
    const DASHBOARD_CURL_TIMEOUT_SECONDS = () => process.env.OSTWIN_TOOL_HTTP_TIMEOUT_SECONDS || "30"
    const OPENCODE_CURL_TIMEOUT_SECONDS = () => process.env.OSTWIN_WORKER_TIMEOUT_SECONDS || "75"

    function curlTimeoutFlags(seconds: string): string[] {
      return ["--connect-timeout", "10", "--max-time", seconds]
    }

    function commandOutput(value: any): string {
      if (!value) return ""
      if (typeof value === "string") return value
      if (value instanceof Uint8Array) return new TextDecoder().decode(value)
      if (typeof value.toString === "function") return value.toString()
      return ""
    }

    function curlErrorMessage(e: any): string {
      const parts = [e?.message, commandOutput(e?.stderr), commandOutput(e?.stdout)]
        .map((p) => (p || "").trim())
        .filter(Boolean)
      return parts.join(": ") || String(e)
    }

    function parseJson(raw: string): any {
      try { return JSON.parse(raw) } catch { return raw }
    }

    function field(obj: any, key: string): any {
      if (!obj) return undefined
      if (typeof obj === "object" && key in obj) return obj[key]
      return undefined
    }

    function parseErrorDetail(raw: any): string {
      if (typeof raw !== "string") return raw ? String(raw) : ""
      try {
        const parsed = JSON.parse(raw)
        if (parsed && typeof parsed === "object") {
          const detail = parsed.error_description || parsed.message || parsed.error
          if (detail && parsed.error && !String(detail).includes(parsed.error))
            return `${parsed.error}: ${detail}`
          return String(detail || raw)
        }
      } catch {}
      return raw
    }

    function formatOpenCodeError(error: any): string {
      if (!error) return ""
      const data = field(error, "data")
      const name = field(error, "name") || field(error, "code") || "error"
      const detail = parseErrorDetail(
        field(data, "message") || field(error, "message") || field(data, "error") || JSON.stringify(error),
      )
      return `OpenCode error (${name}): ${detail}`
    }

    async function api(path: string, method: string = "GET", body?: unknown): Promise<any> {
      const url = `${BASE()}${path}`
      const f = [
        "-sS", "-f",
        ...curlTimeoutFlags(DASHBOARD_CURL_TIMEOUT_SECONDS()),
        "-H", `X-API-Key: ${KEY()}`,
        "-H", "Content-Type: application/json",
      ]
      if (method !== "GET") f.push("-X", method)
      if (body) f.push("-d", JSON.stringify(body))
      try {
        const r = await Bun.$`curl ${f} ${url}`.text()
        return parseJson(r)
      } catch (e: any) {
        throw new Error(`Dashboard request failed (${method} ${path}): ${curlErrorMessage(e)}`)
      }
    }

    async function apiGet(path: string): Promise<any> {
      return api(path)
    }

    // ── OpenCode server helpers ─────────────────────────────────────────────
    //
    // spawnWorker() boots a child OpenCode session under the caller's session
    // (so the worker shows up with parent_id set in the OpenCode DB) and runs
    // the ostwin-worker subagent against a task-specific system override.
    //
    // We hit the local OpenCode HTTP API directly instead of importing the SDK
    // so the tool stays a single self-contained file and dependency-free.
    const OC_BASE = () => process.env.OPENCODE_BASE_URL || "http://127.0.0.1:4096"

    function ocAuthFlags(): string[] {
      const pw = process.env.OPENCODE_SERVER_PASSWORD
      if (!pw) return []
      const user = process.env.OPENCODE_SERVER_USERNAME || "opencode"
      return ["-u", `${user}:${pw}`]
    }

    async function ocFetch(
      path: string,
      method: string,
      body?: unknown,
      timeoutSeconds: string = OPENCODE_CURL_TIMEOUT_SECONDS(),
    ): Promise<any> {
      const url = `${OC_BASE()}${path}`
      const f = [
        "-sS", "-f",
        ...curlTimeoutFlags(timeoutSeconds),
        "-X", method,
        "-H", "Content-Type: application/json",
        ...ocAuthFlags(),
      ]
      if (body !== undefined) f.push("-d", JSON.stringify(body))
      try {
        const r = await Bun.$`curl ${f} ${url}`.text()
        return parseJson(r)
      } catch (e: any) {
        throw new Error(`OpenCode request failed (${method} ${path}): ${curlErrorMessage(e)}`)
      }
    }

    type WorkerResult = { text: string; childSessionId: string }

    async function spawnWorker(
      ctx: { sessionID: string; directory: string },
      systemPrompt: string,
      taskMessage: string,
    ): Promise<WorkerResult> {
      const child = await ocFetch("/session", "POST", { parentID: ctx.sessionID }, "15")
      if (!child || !child.id) {
        throw new Error(`Failed to spawn worker child session: ${JSON.stringify(child)}`)
      }
      let resp: any
      try {
        resp = await ocFetch(`/session/${child.id}/message`, "POST", {
          agent: "ostwin-worker",
          system: systemPrompt,
          parts: [{ type: "text", text: taskMessage }],
        }, OPENCODE_CURL_TIMEOUT_SECONDS())
      } catch (e: any) {
        throw new Error(`Worker session ${child.id} did not finish: ${e.message || e}`)
      }
      const errorText = formatOpenCodeError(resp?.info?.error)
      if (errorText) throw new Error(`Worker session ${child.id} failed: ${errorText}`)
      // Response shape: { info: AssistantMessage, parts: Array<Part> }
      const parts = (resp && resp.parts) || []
      const text = parts
        .filter((p: any) => p && p.type === "text" && typeof p.text === "string")
        .map((p: any) => p.text)
        .join("\\n")
        .trim()
      if (!text) throw new Error(`Worker session ${child.id} finished without text`)
      return { text, childSessionId: child.id }
    }
    """)


def _api_helpers_inlined(port: str) -> str:
    return _api_helpers().replace('"__PORT__"', f'"{port}"')


def _tool_list_plans() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "List all current plans in the Ostwin system with their status, completion %, and epic counts.",
      args: {},
      async execute() {
        try {
          const data = await apiGet("/api/plans")
          const plans = data.plans || []
          if (plans.length === 0) return "No plans found."
          const lines = plans.map(
            (p: any) =>
              `  ${p.plan_id}  |  ${p.title}  |  status: ${p.status}  |  complete: ${p.pct_complete}%  |  epics: ${p.epic_count || 0}`,
          )
          return `Plans (${data.total || data.count || plans.length}):\\n${lines.join("\\n")}`
        } catch (e: any) {
          return `Error listing plans: ${e.message || e}`
        }
      },
    })
    """)


def _tool_get_plan_status() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Get detailed status of a specific plan by its ID, including epics and war-room progress.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID to look up (e.g. my-blog-website)"),
      },
      async execute(args) {
        try {
          const [planRes, epicsRes, roomsRes] = await Promise.all([
            apiGet(`/api/plans/${args.plan_id}`),
            apiGet(`/api/plans/${args.plan_id}/epics`),
            apiGet("/api/rooms"),
          ])
          const plan = planRes.plan || planRes
          if (plan._error || (!plan.plan_id && !plan.title))
            return `Plan "${args.plan_id}" not found: ${JSON.stringify(plan)}`
          const epics = epicsRes.epics || epicsRes || []
          const allRooms = roomsRes.rooms || []
          const planRooms = allRooms.filter(
            (r: any) => r.plan_id === args.plan_id || (r.epic_ref && r.epic_ref.startsWith("EPIC-")),
          )
          let out = `Plan: ${plan.plan_id || args.plan_id}\\n`
          out += `  Title: ${plan.title || "—"}\\n`
          out += `  Status: ${plan.status || "—"}\\n`
          out += `  Complete: ${plan.pct_complete ?? "—"}%\\n`
          out += `  Epics (${epics.length}):\\n`
          for (const ep of epics)
            out += `    ${ep.epic_id || ep.epic_ref || ep.id} — ${ep.title || "—"} [${ep.status || "—"}]\\n`
          out += `  Active War-Rooms (${planRooms.length}):\\n`
          for (const rm of planRooms)
            out += `    ${rm.room_id} — ${rm.epic_ref || "—"} [${rm.status || "—"}]\\n`
          return out
        } catch (e: any) {
          return `Error getting plan status: ${e.message || e}`
        }
      },
    })
    """)


def _tool_register_plan() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Reload a plan's .md file from disk and refresh the dashboard's zvec index. " +
        "Used by the ostwin-worker subagent after it writes a plan file directly to disk, " +
        "so the dashboard UI / search reflects the new content.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID whose file was just written to disk"),
      },
      async execute(args) {
        try {
          const res = await api(`/api/plans/${args.plan_id}/reload`, "POST", {})
          if (res && res.status === "reloaded") return `Plan "${args.plan_id}" re-indexed.`
          return `Reload returned unexpected response: ${JSON.stringify(res)}`
        } catch (e: any) {
          return `Error reloading plan: ${e.message || e}`
        }
      },
    })
    """)


def _tool_create_plan() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Create a new plan from a user idea. Use this when the user asks to build, make, create, or start a new project. " +
        "This will draft a structured plan with epics and tasks using AI, then save it.",
      args: {
        idea: tool.schema.string().describe("Description of what the user wants to build"),
        working_dir: tool.schema.string().describe("Optional working directory for the plan").optional(),
      },
      async execute(args, ctx) {
        try {
          // 1. Allocate plan_id + skeleton + meta.json + roles.json via dashboard.
          const createRes = await api("/api/plans/create", "POST", {
            path: args.working_dir || ".",
            title: args.idea,
            content: "",
            working_dir: args.working_dir || ".",
          })
          if (!createRes.plan_id) return `Error creating plan: ${JSON.stringify(createRes)}`
          const planId = createRes.plan_id
          const workingDir = createRes.working_dir

          // 2. Fetch the plan-architect system prompt (worker mode: writes file directly).
          const promptRes = await apiGet("/api/plan-refine-prompt?mode=worker")
          const systemPrompt = (promptRes && promptRes.system_prompt) || ""
          if (!systemPrompt) return `Plan ${planId} allocated, but failed to fetch system prompt: ${JSON.stringify(promptRes)}`

          // 3. Spawn the ostwin-worker subagent as a child of this session.
          const planFile = `${process.env.HOME}/.ostwin/.agents/plans/${planId}.md`
          const taskMessage = [
            `Draft a new plan for: ${args.idea}`,
            ``,
            `Working directory: ${workingDir}`,
            `Plan ID: ${planId}`,
            ``,
            `INSTRUCTIONS:`,
            `1. Read the current skeleton plan file at: ${planFile}`,
            `2. Write a COMPLETE, properly structured plan to that file (overwriting the skeleton).`,
            `   - Use a SHORT descriptive title (3-8 words), NOT the raw user idea.`,
            `   - Create 3-8 epics with SHORT meaningful names.`,
            `   - Each epic MUST have: Roles, Objective, Lifecycle, Definition of Done, Acceptance Criteria, Tasks.`,
            `   - Include proper depends_on chains between epics.`,
            `3. After writing, call ostwin_register_plan with plan_id="${planId}".`,
            `4. Return a 2-3 sentence summary of what you drafted.`,
          ].join("\\n")

          const worker = await spawnWorker(ctx, systemPrompt, taskMessage)
          const summary = worker.text || "(worker returned no summary)"

          // 4. Re-read the file to count epics for the user-facing reply.
          let epicCount = 0
          try {
            const planRes = await apiGet(`/api/plans/${planId}`)
            const planContent = (planRes && (planRes.plan?.content || planRes.content)) || ""
            epicCount = (planContent.match(/EPIC-\\d{3}/g) || []).length
          } catch {}

          return `{"plan_id":${JSON.stringify(planId)}}\\nPlan created: ${planId}\\n  Title: ${args.idea}\\n  Status: draft\\n  Epic count: ${epicCount}\\n  Worker summary: ${summary}`
        } catch (e: any) {
          return `Error creating plan: ${e.message || e}`
        }
      },
    })
    """)


def _tool_refine_plan() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Refine or modify an existing plan. Use this when the user wants to add features, change epics, " +
        "update tasks, add acceptance criteria, or make any changes to a plan.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID to refine"),
        instruction: tool.schema.string().describe("What changes to make to the plan"),
      },
      async execute(args, ctx) {
        try {
          const planData = await apiGet(`/api/plans/${args.plan_id}`)
          const plan = planData.plan || planData
          if (plan._error || (!plan.plan_id && !plan.content && !plan.title))
            return `Plan "${args.plan_id}" not found: ${JSON.stringify(planData)}`

          const promptRes = await apiGet("/api/plan-refine-prompt?mode=worker")
          const systemPrompt = (promptRes && promptRes.system_prompt) || ""
          if (!systemPrompt) return `Failed to fetch system prompt: ${JSON.stringify(promptRes)}`

          const planFile = `${process.env.HOME}/.ostwin/.agents/plans/${args.plan_id}.md`
          const taskMessage = [
            `Refine the existing plan at ${planFile}.`,
            ``,
            `User instruction: ${args.instruction}`,
            ``,
            `INSTRUCTIONS:`,
            `1. Read the current plan file.`,
            `2. Apply the requested changes while preserving the user's intent and template structure.`,
            `3. Write the updated plan back to the same file path.`,
            `4. After writing, call ostwin_register_plan with plan_id="${args.plan_id}".`,
            `5. Return a 2-3 sentence summary of what changed.`,
          ].join("\\n")

          const worker = await spawnWorker(ctx, systemPrompt, taskMessage)
          const summary = worker.text || "(worker returned no summary)"
          return `Plan "${args.plan_id}" has been refined.\\n  Worker summary: ${summary}`
        } catch (e: any) {
          return `Error refining plan: ${e.message || e}`
        }
      },
    })
    """)


def _tool_launch_plan() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Launch an existing plan into war-rooms so agents start working on it. " +
        "Use this when the user explicitly asks to run, start, launch, or execute a plan.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID to launch"),
      },
      async execute(args) {
        try {
          const planData = await apiGet(`/api/plans/${args.plan_id}`)
          const plan = planData.plan || planData
          if (plan._error || (!plan.plan_id && !plan.title))
            return `Plan "${args.plan_id}" not found: ${JSON.stringify(planData)}`
          const planContent = plan.content || ""
          if (!planContent) return `Plan "${args.plan_id}" has no content to launch.`
          const runRes = await api("/api/run", "POST", { plan_id: args.plan_id, plan: planContent })
          if (runRes._error || runRes.error) return `Error launching plan: ${runRes._error || runRes.error}`
          const n = runRes.rooms?.length || 0
          let out = `{"plan_id":${JSON.stringify(args.plan_id)}}\\nPlan "${args.plan_id}" has been launched. War-rooms are being created for each epic.`
          if (n > 0) {
            out += `\\n  Rooms created: ${n}`
            for (const rm of runRes.rooms)
              out += `\\n    ${rm.room_id || rm.id} — ${rm.epic_ref || "—"} [${rm.status || "—"}]`
          }
          return out
        } catch (e: any) {
          return `Error launching plan: ${e.message || e}`
        }
      },
    })
    """)


def _tool_resume_plan() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Resume a previously failed or stopped plan. Use this when the user asks to resume, retry, or re-run a plan that has failed. " +
        "This re-runs the plan which continues existing war-rooms and picks up from where execution left off.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID to resume"),
      },
      async execute(args) {
        try {
          const planData = await apiGet(`/api/plans/${args.plan_id}`)
          const plan = planData.plan || planData
          if (plan._error || (!plan.plan_id && !plan.title))
            return `Plan "${args.plan_id}" not found: ${JSON.stringify(planData)}`
          const planContent = plan.content || ""
          if (!planContent) return `Plan "${args.plan_id}" has no content to resume.`
          const runRes = await api("/api/run", "POST", { plan_id: args.plan_id, plan: planContent })
          if (runRes._error || runRes.error) return `Error resuming plan: ${runRes._error || runRes.error}`
          const n = runRes.rooms?.length || 0
          let out = `{"plan_id":${JSON.stringify(args.plan_id)}}\\nPlan "${args.plan_id}" is being resumed. Existing war-rooms will continue from where they left off.`
          if (n > 0) {
            out += `\\n  War-rooms continuing: ${n}`
            for (const rm of runRes.rooms)
              out += `\\n    ${rm.room_id || rm.id} — ${rm.epic_ref || "—"} [${rm.status || "—"}]`
          }
          return out
        } catch (e: any) {
          return `Error resuming plan: ${e.message || e}`
        }
      },
    })
    """)


def _tool_get_war_room_status() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Get the current status of all active war-rooms, including which epics are being worked on and their progress.",
      args: {},
      async execute() {
        try {
          const [roomsRes, statsRes] = await Promise.all([apiGet("/api/rooms"), apiGet("/api/stats")])
          const rooms = roomsRes.rooms || []
          const stats = statsRes.stats || statsRes
          let out = "=== War Room Status ===\\n\\nRooms:\\n"
          if (rooms.length === 0) { out += "  (none)\\n" }
          else { for (const r of rooms) out += `  ${r.room_id} | ${r.epic_ref || "N/A"} | ${r.status} | plan: ${r.plan_id || "N/A"}\\n` }
          out += `\\nSummary: ${JSON.stringify(roomsRes.summary || {})}\\n`
          out += "\\nStats:\\n"
          out += `  Total Plans:    ${stats.total_plans?.value ?? stats.total_plans ?? "N/A"}\\n`
          out += `  Active Epics:   ${stats.active_epics?.value ?? stats.active_epics ?? "N/A"}\\n`
          out += `  Completion:     ${stats.completion_rate?.value ?? stats.completion_rate ?? "N/A"}\\n`
          out += `  Escalations:    ${stats.escalations_pending?.value ?? stats.escalations_pending ?? 0}\\n`
          return out
        } catch (e: any) {
          return `Error fetching war room status: ${e.message || e}`
        }
      },
    })
    """)


def _tool_get_logs() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Read the latest messages from a war-room channel. Useful for checking what agents are saying or debugging issues.",
      args: {
        room_id: tool.schema.string().describe("The war-room ID to read logs from (e.g. room-001)"),
        plan_id: tool.schema.string().describe("Optional plan ID — auto-resolved if omitted").optional(),
        limit: tool.schema.number().describe("Number of messages to retrieve (default 10)").optional(),
      },
      async execute(args) {
        try {
          const limit = args.limit ?? 10
          let planId = args.plan_id
          if (!planId) {
            const roomsRes = await apiGet("/api/rooms")
            const rooms = roomsRes.rooms || []
            const match = rooms.find((r: any) => r.room_id === args.room_id)
            if (!match || !match.plan_id)
              return `Room "${args.room_id}" not found or has no plan_id. Pass plan_id explicitly.`
            planId = match.plan_id
          }
          const channelRes = await apiGet(`/api/plans/${planId}/rooms/${args.room_id}/channel`)
          const messages = channelRes.messages || channelRes || []
          const recent = Array.isArray(messages) ? messages.slice(-limit) : []
          let out = `=== Logs for ${args.room_id} (last ${recent.length}) ===\\n\\n`
          if (recent.length === 0) { out += "(no messages)\\n" }
          else {
            for (const m of recent) {
              const body = (m.body || "").slice(0, 300)
              out += `[${m.type || "?"}] ${m.from || "?"}\\n  ${body}${(m.body || "").length > 300 ? "…" : ""}\\n\\n`
            }
          }
          return out
        } catch (e: any) {
          return `Error fetching logs: ${e.message || e}`
        }
      },
    })
    """)


def _tool_get_health() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Check the overall system health: manager status, bot status, and war-room summary.",
      args: {},
      async execute() {
        try {
          const [statusRes, botRes, roomsRes] = await Promise.all([
            apiGet("/api/status"),
            apiGet("/api/bot/status"),
            apiGet("/api/rooms"),
          ])
          const manager = statusRes.manager || statusRes
          const bot = botRes.bot || botRes
          const rooms = roomsRes.rooms || []
          const total = rooms.length
          const passed = rooms.filter((r: any) => r.status === "passed").length
          const failed = rooms.filter((r: any) => r.status === "failed-final" || r.status === "failed").length
          const active = total - passed - failed
          let out = "=== Ostwin Health ===\\n\\n"
          out += "Manager:\\n"
          out += `  Running:  ${manager.running ?? "N/A"}\\n`
          out += `  PID:      ${manager.pid ?? "N/A"}\\n`
          out += "\\nBot:\\n"
          out += `  Running:    ${bot.running ?? "N/A"}\\n`
          out += `  PID:        ${bot.pid ?? "N/A"}\\n`
          out += `  Available:  ${bot.available ?? "N/A"}\\n`
          out += "\\nWar Rooms:\\n"
          out += `  Total:   ${total}\\n  Passed:  ${passed}\\n  Failed:  ${failed}\\n  Active:  ${active}\\n`
          return out
        } catch (e: any) {
          return `Error fetching health: ${e.message || e}`
        }
      },
    })
    """)


def _tool_search_skills() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "Search the ClawHub marketplace for available AI skills that can be installed.",
      args: {
        query: tool.schema.string().describe('Search query (e.g. "web search", "code review", "testing")'),
      },
      async execute(args) {
        try {
          const q = encodeURIComponent(args.query)
          const data = await apiGet(`/api/skills/clawhub-search?q=${q}`)
          const skills = Array.isArray(data) ? data : (data.skills || data.results || [])
          if (skills.length === 0) return `No skills found for "${args.query}".`
          const top = skills.slice(0, 10)
          let out = `Found ${skills.length} skill(s) for "${args.query}" (showing top ${top.length}):\\n\\n`
          for (let i = 0; i < top.length; i++) {
            const s = top[i]
            out += `${i + 1}. ${s.slug || s.name || "unknown"}\\n`
            out += `   ${s.description || "No description"}\\n`
            out += `   Author: ${s.author || "N/A"} | Downloads: ${s.downloads ?? "N/A"}\\n`
            out += `   Install with: /skillinstall ${s.slug || s.name}\\n\\n`
          }
          return out
        } catch (e: any) {
          return `Error searching skills: ${e.message || e}`
        }
      },
    })
    """)


def _tool_get_plan_assets() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "List all assets and artifacts produced by a plan. Use this when the user asks about files, " +
        "artifacts, deliverables, outputs, or the product of a plan.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID"),
      },
      async execute(args) {
        try {
          const data = await apiGet(`/api/plans/${args.plan_id}/assets`)
          const assets = data.assets || []
          const count = data.count ?? assets.length
          if (count === 0) return `No assets found for plan "${args.plan_id}".`
          const lines: string[] = [`Assets for plan "${args.plan_id}" (${count} total):\\n`]
          for (const a of assets) {
            lines.push(`  ${a.original_name || a.filename || "unknown"}`)
            lines.push(`    path: ${a.path || ""}`)
            lines.push(`    type: ${a.asset_type || a.mime_type || "unknown"}`)
            lines.push(`    bound_epics: ${a.bound_epics?.length > 0 ? a.bound_epics.join(", ") : "none"}`)
            lines.push(`    size_bytes: ${a.size_bytes != null ? a.size_bytes : "unknown"}`)
            lines.push("")
          }
          return lines.join("\\n")
        } catch (e: any) {
          return `Error fetching assets: ${e.message || e}`
        }
      },
    })
    """)


def _tool_get_memories() -> str:
    return textwrap.dedent("""\
    export default tool({
      description:
        "List the memories (knowledge notes) saved during a plan's execution. Each memory captures " +
        "architectural decisions, code patterns, lessons learned, and context discovered by agents.",
      args: {
        plan_id: tool.schema.string().describe("The plan ID"),
      },
      async execute(args) {
        const base = `${BASE()}/api/amem/${args.plan_id}`
        const hdr = ["-H", `X-API-Key: ${KEY()}`]
        async function apiGet(path: string): Promise<any> {
          const url = `${base}${path}`
          try {
            const f = ["-sS", "-f", ...curlTimeoutFlags(DASHBOARD_CURL_TIMEOUT_SECONDS()), ...hdr]
            const raw = await Bun.$`curl ${f} ${url}`.text()
            return JSON.parse(raw)
          } catch { return null }
        }
        const [notesData, statsData, treeData] = await Promise.all([
          apiGet("/notes"), apiGet("/stats"), apiGet("/tree"),
        ])
        if (!notesData && !statsData && !treeData)
          return `No memories found for plan "${args.plan_id}".`
        const notes = Array.isArray(notesData) ? notesData : []
        const stats = statsData || {}
        const treeStr = treeData?.tree || "(unavailable)"
        const lines: string[] = [
          `Memories for plan "${args.plan_id}":\\n`,
          `Total notes: ${stats.total_notes ?? notes.length}`,
          `Total tags: ${stats.total_tags ?? 0}`,
          `Total keywords: ${stats.total_keywords ?? 0}`,
          `Categories: ${stats.categories?.length > 0 ? stats.categories.join(", ") : "none"}`,
          "", "Directory tree:", treeStr, "",
        ]
        const maxNotes = Math.min(notes.length, 15)
        if (maxNotes > 0) {
          lines.push(`Memory notes (showing ${maxNotes} of ${notes.length}):\\n`)
          for (let i = 0; i < maxNotes; i++) {
            const n = notes[i]
            lines.push(`  ${i + 1}. ${n.title || "untitled"}`)
            lines.push(`     path: ${n.path || ""}`)
            lines.push(`     tags: ${n.tags?.length > 0 ? n.tags.join(", ") : "none"}`)
            lines.push(`     keywords: ${n.keywords?.length > 0 ? n.keywords.join(", ") : "none"}`)
            lines.push(`     excerpt: ${(n.excerpt || n.body || "").slice(0, 200)}`)
            lines.push("")
          }
        } else { lines.push("No memory notes to display.") }
        const graphTmpPath = `/tmp/ostwin-memgraph-${args.plan_id}.png`
        try {
          const graphUrl = `${base}/graph-image`
          const f = ["-sS", "-f", ...curlTimeoutFlags(DASHBOARD_CURL_TIMEOUT_SECONDS()), ...hdr]
          await Bun.$`curl ${f} -o ${graphTmpPath} ${graphUrl}`.quiet()
          const file = Bun.file(graphTmpPath)
          const exists = await file.exists()
          const size = exists ? (await file.stat())?.size : 0
          if (exists && size && size > 0) {
            lines.push(`Graph image saved to: ${graphTmpPath} (${size} bytes)`)
            lines.push(`Graph also available at: ${graphUrl}`)
          } else { lines.push("Graph image: no graph available.") }
        } catch { lines.push("Graph image: unavailable.") }
        return lines.join("\\n")
      },
    })
    """)


TOOLS: dict[str, str] = {
    "ostwin_list_plans": _tool_list_plans,
    "ostwin_get_plan_status": _tool_get_plan_status,
    "ostwin_create_plan": _tool_create_plan,
    "ostwin_refine_plan": _tool_refine_plan,
    "ostwin_register_plan": _tool_register_plan,
    "ostwin_launch_plan": _tool_launch_plan,
    "ostwin_resume_plan": _tool_resume_plan,
    "ostwin_get_war_room_status": _tool_get_war_room_status,
    "ostwin_get_logs": _tool_get_logs,
    "ostwin_get_health": _tool_get_health,
    "ostwin_search_skills": _tool_search_skills,
    "ostwin_get_plan_assets": _tool_get_plan_assets,
    "ostwin_get_memories": _tool_get_memories,
}


def _agent_ostwin_worker(model: str) -> str:
    """Markdown definition for the generic ostwin-worker subagent.

    The worker runs as a child OpenCode session of the caller's `ostwin`
    session (so it shows up with parent_id set in the OpenCode DB instead of
    creating a sibling root session per tool call). It receives a
    task-specific system prompt at invocation time — typically the plan-
    architect prompt rendered by dashboard.plan_agent.get_system_prompt() —
    so one subagent definition can cover many distinct tasks.

    Tool surface: filesystem + shell so it can read/write plan markdown
    directly under ~/.ostwin/.agents/plans, plus ostwin_register_plan so it
    can ask the dashboard to re-index the file it just wrote. All other
    ostwin_* tools are denied to avoid the worker re-entering its parent's
    behaviour (e.g. a worker recursively calling ostwin_create_plan).

    The ``model`` argument matches whatever the master agent is configured
    with at generation time, so flipping ``--model`` flips both agents in
    lockstep and avoids the worker silently running on a stale default.
    """
    return textwrap.dedent(f"""\
    ---
    description: >-
      Generic Ostwin worker subagent. Runs file-IO work (drafting/refining
      plan markdown, scaffolding, etc.) as a child of the master ostwin
      session, so tool-driven work doesn't create sibling root sessions.
    mode: subagent
    model: {model}
    tools:
      read: true
      write: true
      edit: true
      patch: true
      bash: true
      glob: true
      grep: true
      list: true
      ostwin_register_plan: true
      ostwin_list_plans: false
      ostwin_get_plan_status: false
      ostwin_create_plan: false
      ostwin_refine_plan: false
      ostwin_launch_plan: false
      ostwin_resume_plan: false
      ostwin_get_war_room_status: false
      ostwin_get_logs: false
      ostwin_get_health: false
      ostwin_search_skills: false
      ostwin_get_plan_assets: false
      ostwin_get_memories: false
      task: false
      todowrite: false
      todoread: false
      webfetch: false
    permission:
      external_directory: allow
      bash: allow
      read: allow
      write: allow
      edit: allow
      ostwin_register_plan: allow
    ---

    You are the Ostwin worker subagent. Your job is to carry out a single
    concrete task handed to you by the parent `ostwin` agent through a
    task-specific system override and an initial user message.

    Operating rules:

    1. Trust the task-specific system prompt and the initial user message —
       they tell you exactly what file to read/write and what to register.
    2. Plans live under `~/.ostwin/.agents/plans/<plan_id>.md`. Read the
       current file before refining; write the full updated markdown back to
       the same path. Never invent a different location.
    3. After writing or updating a plan file, call
       `ostwin_register_plan(plan_id=...)` so the dashboard re-indexes the
       file. Do this exactly once per task, at the end.
    4. Keep your final reply to the parent short — 2 to 3 sentences
       describing what you produced. The parent uses this string verbatim
       when summarising to the user.
    5. Do not call `ostwin_create_plan` / `ostwin_refine_plan` / other
       higher-level ostwin_* tools — those are the parent's responsibility,
       and recursing into them would re-spawn another worker.
    """)


AGENTS: dict[str, str] = {
    "ostwin-worker": _agent_ostwin_worker,
}


def _opencode_config(model: str = "google/gemini-2.5-pro") -> dict:
    # The ostwin agent speaks to the dashboard primarily through ostwin_* tools.
    # bash is enabled so that `!` command injections in .opencode/commands/*.md
    # can execute (e.g. curl calls to the dashboard API). The agent's system
    # prompt still forbids arbitrary shell usage — bash is only invoked when
    # a slash command template explicitly uses `!` syntax.
    #
    # Filesystem tools (read/write/edit/patch) remain disabled for the master
    # agent — all plan persistence goes through /api/plans/create so files
    # land in ~/.ostwin/.agents/plans and metadata is indexed in zvec.
    # The ostwin-worker subagent has its own permission block that re-grants
    # filesystem tools. external_directory is pre-approved because the
    # OpenCode server runs from ~/.ostwin/opencode_server while workers read
    # and write ~/.ostwin/.agents/plans.
    return {
        "$schema": "https://opencode.ai/config.json",
        "agent": {
            "ostwin": {
                "model": model,
                "tools": {
                    "ostwin_*": True,
                    "bash": True,
                    "read": False,
                    "write": False,
                    "edit": False,
                    "patch": False,
                    "webfetch": False,
                    "todowrite": False,
                    "todoread": False,
                    "task": False,
                    "glob": False,
                    "grep": False,
                    "list": False,
                },
            },
        },
        "permission": {
            "ostwin_*": "allow",
            "bash": "allow",
            "external_directory": {"*": "allow"},
            "read": "deny",
            "write": "deny",
            "edit": "deny",
        },
    }


def _ostwin_plan_command() -> str:
    return textwrap.dedent("""\
    ---
    description: Create a new Ostwin plan from an idea
    agent: ostwin
    ---

    Create a new plan for: $ARGUMENTS

    Use the ostwin_create_plan tool to create the plan. After creation, summarize the plan structure (epics, key tasks) for the user.
    """)


def _render_command_md(spec: dict[str, str]) -> str:
    """Render an OpenCode command file from a registry entry.

    Frontmatter keys are emitted in a stable order so the generator's output
    is byte-identical across machines and re-runs. Unknown keys (e.g.
    ``subtask``, ``model``) are appended after the canonical block.
    """
    description = spec.get("description", "")
    agent = spec.get("agent", "ostwin")
    body = spec.get("body", "")

    fm_lines = ["---", f"description: {description}", f"agent: {agent}"]
    for key in sorted(spec.keys()):
        if key in {"description", "agent", "body"}:
            continue
        fm_lines.append(f"{key}: {spec[key]}")
    fm_lines.append("---")
    fm = "\n".join(fm_lines) + "\n"

    if not body.endswith("\n"):
        body = body + "\n"
    return f"{fm}\n{body}"


def _write_agents(agents_dir: Path, model: str) -> list[Path]:
    """Write `.opencode/agent/<name>.md` for every entry in AGENTS.

    ``model`` is forwarded to each agent body builder so subagent frontmatter
    stays in sync with whatever model the master is configured with at
    generation time (driven by ``generate_all(model=...)`` / the ``--model``
    CLI flag).
    """
    agents_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    keep = {f"{name}.md" for name in AGENTS}
    for existing in agents_dir.glob("*.md"):
        if existing.name not in keep:
            try:
                existing.unlink()
                logger.debug("[OPENCODE_TOOLS] Removed stale %s", existing)
            except OSError:
                pass

    for name, body_fn in AGENTS.items():
        path = agents_dir / f"{name}.md"
        path.write_text(body_fn(model), encoding="utf-8")
        written.append(path)
        logger.debug("[OPENCODE_TOOLS] Wrote %s", path)

    return written


def _write_commands(commands_dir: Path) -> list[Path]:
    """Write every registered OpenCode command markdown file.

    Always rewrites every file so the on-disk state matches the in-repo
    registry exactly — there's no incremental drift across upgrades.
    """
    from dashboard.opencode_commands_data import COMMANDS

    commands_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Drop any previously-generated `.md` files we no longer ship, so renames
    # and removals from the registry propagate cleanly on every install.
    keep = {f"{name}.md" for name in COMMANDS} | {"ostwin-plan.md"}
    for existing in commands_dir.glob("*.md"):
        if existing.name not in keep:
            try:
                existing.unlink()
                logger.debug("[OPENCODE_TOOLS] Removed stale %s", existing)
            except OSError:
                pass

    for name, spec in COMMANDS.items():
        path = commands_dir / f"{name}.md"
        path.write_text(_render_command_md(spec), encoding="utf-8")
        written.append(path)
        logger.debug("[OPENCODE_TOOLS] Wrote %s", path)

    return written


def generate_all(
    project_root: Optional[Path] = None,
    dashboard_port: str = DASHBOARD_PORT_DEFAULT,
    model: str = "google/gemini-2.5-pro",
) -> list[Path]:
    project_root = project_root or _resolve_project_root()
    helpers = _api_helpers_inlined(dashboard_port)
    written: list[Path] = []

    tools_dir = project_root / ".opencode" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    for name, body_fn in TOOLS.items():
        path = tools_dir / f"{name}.ts"
        path.write_text(helpers + body_fn(), encoding="utf-8")
        written.append(path)
        logger.debug("[OPENCODE_TOOLS] Wrote %s", path)

    config_path = project_root / "opencode.json"
    config_path.write_text(json.dumps(_opencode_config(model), indent=2) + "\n", encoding="utf-8")
    written.append(config_path)
    logger.debug("[OPENCODE_TOOLS] Wrote %s", config_path)

    agents_dir = project_root / ".opencode" / "agent"
    written.extend(_write_agents(agents_dir, model))

    commands_dir = project_root / ".opencode" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    # Legacy hand-written command — kept for back-compat with /ostwin-plan.
    legacy_cmd = commands_dir / "ostwin-plan.md"
    legacy_cmd.write_text(_ostwin_plan_command(), encoding="utf-8")
    written.append(legacy_cmd)

    # Connector-parity slash commands generated from the embedded registry.
    written.extend(_write_commands(commands_dir))

    logger.info("[OPENCODE_TOOLS] Generated %d files in %s", len(written), project_root)
    return written


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate OpenCode tool files for Ostwin")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--dashboard-port", default=DASHBOARD_PORT_DEFAULT)
    parser.add_argument("--model", default="google/gemini-2.5-pro")
    args = parser.parse_args()

    files = generate_all(
        project_root=args.project_root,
        dashboard_port=args.dashboard_port,
        model=args.model,
    )
    for f in files:
        print(f"  wrote {f}")
