# EPIC-001

Objective: Build the visual foundation of every level by rendering a grid of dots that snakes live on.

Dot-Grid Board System

Roles: engineer, qa
Objective: Build the visual foundation of every level by rendering a grid of dots that snakes live on.

**Description:** The visual foundation of every level. A grid of dots that snakes live on. As a player, when I open a level I see a clean grid of dots. The dots form the world -- every intersection is a potential snake position. Board size varies from 3x3 to 40x40. `GridView` must render dots for the full content area, validate board dimensions, ensure proper coordinate mapping, and use object pooling to recycle dot GameObjects between level loads, keeping memory stable across hundreds of levels.

**Key files:** `GridView.cs`, `LevelData.cs`

Lifecycle:
```text
pending → engineer → qa ─┬─► passed → signoff
              ▲                     │
              └── engineer ◄───┘ (on fail → fixing)
```

Tasks: Render dots for the full content area, validate board size, and ensure proper coordinate mapping and pooling.

### Definition of Done
- [ ] Board renders dots for the full content area (not just snake-occupied positions)
- [ ] Board size is validated and clamped to 3x3 - 40x40
- [ ] Grid-to-world coordinate mapping works correctly for all board sizes
- [ ] Dots are pooled and recycled between level loads

### Tasks
- [ ] TASK-001 — [engineer] **Grid dot rendering.** The dot grid is the first thing a player sees when opening any level — a clean field of evenly-spaced dots forming the puzzle world. Every intersection is a potential snake position, so ALL positions need dots, not just snake-occupied ones. Create `GridView.cs` MonoBehaviour with `Setup(LevelData levelData)` entry point. Implement `CreateGridDots()` to instantiate a dot prefab at every (x,y) within the board's content rect. Use `UnityEngine.Pool.ObjectPool<GameObject>` pooling to recycle dots between level loads — players blitz through hundreds of levels, so leaked GameObjects cause memory pressure. | requires: EPIC-011/TASK-001 | unlocks: TASK-002, TASK-003, TASK-004
- [ ] TASK-002 — [engineer] **Coordinate mapping.** Snakes live on grid coordinates (row, col) but application renders in world space — every downstream system (snake positioning, tap detection, camera framing) depends on accurate bidirectional translation. Grid row 0 is the top of the board but world Y increases upward, so Y must be inverted. Implement `GridView.GridToWorld(Vector2Int gridPos)` and `WorldToGrid(Vector3 worldPos)`. Add unit tests for boundary positions (corners, edges, center). | requires: TASK-001 | unlocks: EPIC-002/TASK-005, EPIC-010/TASK-001
- [ ] TASK-003 — [engineer] **Content rect calculation.** The camera and snake views need to know the board's physical size in world space — without a content rect, the camera can't auto-frame and snakes can't position themselves. Implement `GridView.CalculateContentRect()` to compute the bounding rect from board dimensions. Handle edge cases: empty snake list, single snake, snake sitting at board boundary. | requires: TASK-001 | unlocks: EPIC-010/TASK-001
- [ ] TASK-004 — [engineer] **Board size validation.** Level designers create boards from JSON data. A board smaller than 3×3 has no room for puzzles; larger than 40×40 would explode memory with thousands of dots. The game must protect itself from bad data gracefully. Implement board size validation in `GridView.Setup()`: clamp `_gridSize` to [3,3]-[40,40] with `Debug.LogWarning` when clamping occurs. | requires: TASK-001 | unlocks: none

### Acceptance criteria:
- A 5x6 board shows 30 dots arranged in a grid
- A 3x3 board shows 9 dots
- Loading a level with invalid board size (1x1 or 50x50) logs a warning and clamps
- `LevelData.IsValid()` rejects boards with dimensions outside 3-40, zero snakes, or snakes placed out of bounds
- Grid-to-world and world-to-grid coordinate translations are mathematically proven via unit tests
- Grid dots are correctly pooled -- loading 3 consecutive levels shows no leaked GameObjects

depends_on: [EPIC-011]



## Working Directory
/Users/paulaan/Downloads/snakie/snakie_project

## Created
2026-04-03T11:04:01Z
