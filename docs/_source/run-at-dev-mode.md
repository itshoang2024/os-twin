# Runtime File Writes — 3 Ways to Run

## 1. `.agents/bin/ostwin run plan.md` (dev mode, có pwsh)

**Flow:** bash wrapper → `ps_dispatch` → `Start-Plan.ps1` → downstream chain

### Ghi vào `<project>/.war-rooms/`

| File | Source | Line |
|---|---|---|
| `room-*/config.json` | `New-WarRoom.ps1` | 146 |
| `room-*/channel.jsonl` | `New-WarRoom.ps1` | 98, `Post-Message.ps1` 135-136 |
| `room-*/status` | `New-WarRoom.ps1` 365, `Start-ManagerLoop.ps1` 189, `Start-Plan.ps1` 503/516/824 |
| `room-*/state_changed_at` | `Start-ManagerLoop.ps1` | 191 |
| `room-*/audit.log` | `Start-ManagerLoop.ps1` | 193 |
| `room-*/retries` | `New-WarRoom.ps1` 368, `Start-ManagerLoop.ps1` 301/400 |
| `room-*/done_epoch` | `New-WarRoom.ps1` | 369 |
| `room-*/task-ref` | `New-WarRoom.ps1` | 372 |
| `room-*/brief.md` | `New-WarRoom.ps1` 266, `Start-ManagerLoop.ps1` 318 |
| `room-*/lifecycle.md` | `New-WarRoom.ps1` | 355 |
| `room-*/lifecycle.json` | `New-WarRoom.ps1` | 361 |
| `room-*/crash_count` | `Start-ManagerLoop.ps1` | 576 |
| `room-*/triage-context.md` | `Start-ManagerLoop.ps1` | 592 |
| `room-*/pids/*.pid` | `Invoke-Agent.ps1` wrapper bash | 372 |
| `room-*/pids/spawn.lock` | `Start-ManagerLoop.ps1` | 348 |
| `room-*/artifacts/*-output.txt` | `Invoke-Agent.ps1` wrapper bash | 376 |
| `room-*/artifacts/*-output.txt.wrapper.log` | `Invoke-Agent.ps1` wrapper bash | 375 |
| `room-*/artifacts/run-agent.sh` | `Invoke-Agent.ps1` | 380 |
| `room-*/artifacts/mcp-config-resolved.json` | `Invoke-Agent.ps1` | 329 |
| `room-*/skills/` | `Invoke-Agent.ps1` 212/235, `ManagerLoop-Helpers.psm1` 78/92 |
| `room-*/contexts/` | `New-WarRoom.ps1` | 92 |
| `room-expansion/` | `Expand-Plan.ps1` | 91-93 |
| `DAG.json` | `Build-DependencyGraph.ps1` | 339-340 |

### Ghi vào `.agents/` (project-local, khi chạy từ source)

| File | Source | Line | Giải thích |
|---|---|---|---|
| `manager.pid` | `Start-ManagerLoop.ps1` | 40, 85 | `$agentsDir` = `PSScriptRoot/../..` = `.agents/` |
| `logs/ostwin.log` | `Log.psm1` | 119 | `$agentsDir` = `PSScriptRoot/..` = `.agents/` |
| `logs/ostwin.jsonl` | `Log.psm1` | 161 | same |
| `skills/*/SKILL.md` | `Resolve-RoleSkills.ps1` | 178-192 | Chỉ khi dashboard API đang chạy và trả skill content |

### Ghi cạnh plan file

| File | Source | Line | Điều kiện |
|---|---|---|---|
| `.planning-DAG.json` | `Build-PlanningDAG.ps1` 64, `Expand-Plan.ps1` 413/443/454/466 | Cạnh plan.md | Khi expand/planning |
| `plan.md` (in-place) | `Start-Plan.ps1` 860, `Expand-Plan.ps1` 238/399 | Overwrite input | Khi plan-update qua channel hoặc expand |

### Ghi vào `~/.ostwin/`

| File | Source | Line | Giải thích |
|---|---|---|---|
| `logs/*-prompt.txt` | `Invoke-Agent.ps1` | prompt assembly | Compiled prompt persisted for audit and piped to agent stdin |
| `logs/*-prompt-debug.md` | `Invoke-Agent.ps1` | prompt assembly | Human-readable prompt debug copy |

Ngoài ra, nếu `working_dir` trong plan trỏ tới thư mục chưa có `.agents/` → trigger `ostwin init` → ghi `~/.ostwin/mcp/mcp-config.json` (init.sh:237-241). Trên source repo đã có `.agents/` nên không trigger init path này.

### Có thể tạo thư mục mới

Nếu plan có `working_dir` trỏ tới thư mục chưa tồn tại → `mkdir -p` (ostwin bin:414) + `ostwin init` (ostwin bin:418). Chỉ khi `working_dir` khác project hiện tại.

---

## 2. `.agents/run.sh plan.md`

**Flow:** bash → register plan → `Start-Plan.ps1` → downstream chain (giống #1)

### Giống hệt #1, cộng thêm:

| File | Vị trí | Source | Line |
|---|---|---|---|
| `{plan_id}.md` | `~/.ostwin/plans/` | `run.sh` | 52-67 |
| `{plan_id}.meta.json` | `~/.ostwin/plans/` | `run.sh` | 72-80 |

`run.sh` luôn `mkdir -p ~/.ostwin/plans/` (line 53) và copy plan + write meta, bất kể có install hay không.

### Khác biệt duy nhất so với #1:

- **Không** load `.env` files (ostwin bin load ở line 12-78, run.sh không làm)
- **Không** resolve hex plan ID
- **Không** detect missing roles / auto-create
- **Không** translate flags (`--dry-run` → `-DryRun`)
- **Có** register plan vào `~/.ostwin/plans/`

---

## 3. Sau installation (`ostwin run plan.md`)

**Flow:** giống hệt #1 (cùng script `.agents/bin/ostwin`), nhưng scripts nằm ở `~/.ostwin/.agents/`.

### Khác biệt duy nhất: `$PSScriptRoot` resolve paths khác

Vì scripts nằm ở `~/.ostwin/.agents/`, các relative path thay đổi:

| File | Dev mode (#1) | Installed (#3) |
|---|---|---|
| `manager.pid` | `<project>/.agents/manager.pid` | `~/.ostwin/.agents/manager.pid` |
| `logs/ostwin.log` | `<project>/.agents/logs/ostwin.log` | `~/.ostwin/.agents/logs/ostwin.log` |
| `logs/ostwin.jsonl` | `<project>/.agents/logs/ostwin.jsonl` | `~/.ostwin/.agents/logs/ostwin.jsonl` |
| `skills/*/SKILL.md` | `<project>/.agents/skills/` | `~/.ostwin/.agents/skills/` |

**Lưu ý:** `Start-Plan.ps1` resolve `$agentsDir` (line 62-73): nếu project có `.agents/` với `New-WarRoom.ps1` thì dùng project-local, nếu không thì dùng `~/.ostwin/.agents/`. Tức là khi chạy trên source repo, dù installed, `$agentsDir` vẫn có thể trỏ về project `.agents/`.

Nhưng `Start-ManagerLoop.ps1` và `Log.psm1` **tự resolve bằng `$PSScriptRoot`** — chúng luôn ghi cạnh file script, không theo `$agentsDir` của `Start-Plan.ps1`.

---

## Tóm tắt

| | `.war-rooms/` | `.agents/` (project) | `~/.ostwin/` | Cạnh plan file |
|---|---|---|---|---|
| `ostwin run` (dev) | room state, artifacts | manager.pid, logs/, skills/ | **Không** | .planning-DAG.json, plan.md |
| `run.sh` | room state, artifacts | manager.pid, logs/, skills/ | `plans/*.md` + `.meta.json` | .planning-DAG.json, plan.md |
| `ostwin run` (installed) | room state, artifacts | **Không** (ghi vào `~/.ostwin/.agents/`) | `.agents/manager.pid`, `.agents/logs/`, `.agents/skills/` | .planning-DAG.json, plan.md |

Tất cả files trong `.agents/` đã được gitignore (`*pid`, `.agents/logs/`, `.agents/skills/` không track vì nằm trong runtime).
