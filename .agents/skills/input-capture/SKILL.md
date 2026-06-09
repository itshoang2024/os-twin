---
name: input-capture
description: Simulate mouse clicks, cursor movement, and keyboard input (text, key codes, combos, hold) on macOS via osascript System Events."
tags: [computer-use, automation, macos, input, keyboard, mouse]

platform: [macos]
requires_permissions: [Accessibility]
shell: bash
---

# input-capture

## Overview

Simulate human input on macOS: mouse clicks at screen coordinates, keyboard text entry, key codes, modifier combos, and key hold. Covers both `click.sh` (mouse) and `type.sh` (keyboard) — combined because both route through `System Events` and require the same Accessibility permission.

**Required TCC permission:** Accessibility (`System Settings > Privacy & Security > Accessibility`)

---

## Mouse Commands

Invoke via `ostwin mac click <cmd> <x> <y>`. Underlying script: `.agents/scripts/macos/click.sh`

| Command | Arguments | Description |
|---------|-----------|-------------|
| `click` | `<x> <y>` | Single left-click at screen pixel coordinates. |
| `double-click` | `<x> <y>` | Double left-click at screen pixel coordinates. |
| `right-click` | `<x> <y>` | Secondary (right) click at screen pixel coordinates. |
| `move` | `<x> <y>` | Move cursor without clicking. Uses `cliclick` if installed; falls back to `CGWarpMouseCursorPosition`. |

**Argument constraints:** `<x>`, `<y>` — non-negative unsigned integer. Origin is top-left of the primary display.

```bash
ostwin mac click click 640 400
ostwin mac click double-click 640 400
ostwin mac click right-click 200 300
ostwin mac click move 960 540
```

### Daemon Dispatch (mouse)

```bash
printf '{"script":"click","cmd":"click","args":"640 400"}' | socat - UNIX-CONNECT:/tmp/ostwin-macos-host.sock
printf '{"script":"click","cmd":"right-click","args":"200 300"}' | socat - UNIX-CONNECT:/tmp/ostwin-macos-host.sock
printf '{"script":"click","cmd":"move","args":"960 540"}' | /usr/bin/nc -U /tmp/ostwin-macos-host.sock
```

---

## Keyboard Commands

Invoke via `ostwin mac type <cmd> [args]`. Underlying script: `.agents/scripts/macos/type.sh`

| Command | Arguments | Description |
|---------|-----------|-------------|
| `text` | `<string>` | Type a string character-by-character via AppleScript `keystroke`. |
| `key` | `<keycode>` | Press a single key by numeric macOS key code. |
| `combo` | `<key> [mod ...]` | Press a key with one or more modifier keys held. |
| `hold` | `<keycode> <ms>` | Hold a key down for `ms` milliseconds, then release. |

**Argument constraints:**
- `<string>` — must not contain newline, carriage return, or tab (use `key` instead); backslash and backtick rejected
- `<keycode>` — non-negative integer (macOS virtual key code)
- `<key>` for `combo` — single character (e.g., `c`, `z`, `s`)
- `[mod ...]` — one or more of: `command` (`cmd`), `option` (`alt`), `control` (`ctrl`), `shift`; space-separated
- `<ms>` — non-negative integer, duration in milliseconds

```bash
# Type text
ostwin mac type text "Hello, World!"

# Press single keys by code
ostwin mac type key 36     # Return/Enter
ostwin mac type key 53     # Escape
ostwin mac type key 49     # Space

# Modifier combos
ostwin mac type combo c command          # Cmd+C (copy)
ostwin mac type combo v command          # Cmd+V (paste)
ostwin mac type combo z command          # Cmd+Z (undo)
ostwin mac type combo a command          # Cmd+A (select all)
ostwin mac type combo s command shift    # Cmd+Shift+S (Save As)
ostwin mac type combo tab control        # Ctrl+Tab

# Hold a key
ostwin mac type hold 49 500  # Hold Space for 500ms
```

### Daemon Dispatch (keyboard)

```bash
printf '{"script":"type","cmd":"text","args":"Hello World"}' | socat - UNIX-CONNECT:/tmp/ostwin-macos-host.sock
printf '{"script":"type","cmd":"key","args":"36"}' | socat - UNIX-CONNECT:/tmp/ostwin-macos-host.sock
printf '{"script":"type","cmd":"combo","args":"c command"}' | socat - UNIX-CONNECT:/tmp/ostwin-macos-host.sock
printf '{"script":"type","cmd":"hold","args":"49 500"}' | /usr/bin/nc -U /tmp/ostwin-macos-host.sock
```

---

## Common Key Codes

| Key | Code | Key | Code |
|-----|------|-----|------|
| Return | 36 | Tab | 48 |
| Space | 49 | Delete (⌫) | 51 |
| Escape | 53 | Forward Delete | 117 |
| Left ← | 123 | Right → | 124 |
| Down ↓ | 125 | Up ↑ | 126 |
| Home | 115 | End | 119 |
| Page Up | 116 | Page Down | 121 |
| F1 | 122 | F5 | 96 |

---

## Direct osascript Patterns

```bash
# Type text
osascript -e 'tell application "System Events" to keystroke "hello world"'

# Press key by code
osascript -e 'tell application "System Events" to key code 36'   # Return
osascript -e 'tell application "System Events" to key code 53'   # Escape

# Modifier combos
osascript -e 'tell application "System Events" to keystroke "c" using {command down}'
osascript -e 'tell application "System Events" to keystroke "s" using {command down, shift down}'
osascript -e 'tell application "System Events" to keystroke "z" using {command down}'

# Mouse clicks
osascript -e 'tell application "System Events" to click at {640, 400}'
osascript -e 'tell application "System Events" to double click at {640, 400}'
osascript -e 'tell application "System Events" to secondary click at {640, 400}'
```

---

## Rules

- Always activate the target app before sending input: `tell application "AppName" to activate`.
- `keystroke` sends the character; `key code` sends the physical key. Use `key code` for special keys (arrows, function keys, Enter).
- Modifier names in `using {...}`: `command down`, `option down`, `control down`, `shift down`.
- If clicks don't register, the process may be sandboxed and not honour System Events. Use app-native AppleScript instead.
- For reliable cursor movement without clicking, install `cliclick`: `brew install cliclick`.
- Special characters in `keystroke` strings: escape double quotes with `\"` and backslashes with `\\`.
