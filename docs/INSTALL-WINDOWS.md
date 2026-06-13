# Cài đặt Ostwin (Agent OS) trên Windows

Hướng dẫn cài đặt Ostwin trên **Windows 10 (build 10240+) / Windows 11**, dùng
trình cài đặt PowerShell gốc — **không cần WSL, Cygwin hay Git Bash**.

> `install.sh` ở thư mục gốc chỉ dành cho macOS/Linux (nó tải Go installer rồi
> ủy quyền cho `.agents/install.sh`). Trên Windows bạn chạy **`.agents/install.ps1`**.

---

## 1. Yêu cầu trước khi cài

Trình cài đặt sẽ tự lo phần lớn dependency (qua `winget`/`choco`/tải trực tiếp),
nhưng tối thiểu bạn cần:

| Thành phần | Ghi chú |
|---|---|
| Windows 10 build 10240+ hoặc Windows 11 | Khuyến nghị bật **Developer Mode** để tạo symlink không cần quyền admin |
| PowerShell 7+ (`pwsh`) | Installer có thể tự cài, nhưng nên cài sẵn để chạy mượt |
| Quyền chạy script | Xem mục [Execution Policy](#execution-policy) bên dưới |
| Kết nối Internet | Để tải Python, Node.js, opencode, uv… |

Installer sẽ tự cài: **Python 3.10+**, **PowerShell 7+**, **uv**, **Node.js**,
**opencode** (engine chạy agent), **Chrome DevTools** (browser MCP), **Pester 5+**,
và các dependency MCP (fastapi, uvicorn…).

### Execution Policy

Script PowerShell cần được phép chạy. Mở **PowerShell 7 (pwsh)** và dùng một
trong hai cách:

```powershell
# Cách A — chỉ nới lỏng cho tiến trình hiện tại (an toàn, khuyến nghị)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# Cách B — nới lỏng cho user (giữ qua các phiên)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## 2. Cài đặt

```powershell
# 1. Lấy mã nguồn (clone hoặc giải nén archive)
git clone https://github.com/igot-ai/os-twin.git
cd os-twin

# 2. Chạy trình cài đặt Windows
.\.agents\install.ps1
```

Chạy không tham số sẽ là chế độ tương tác (hỏi chọn AI provider, ngrok token…).
Một số cờ hữu ích:

| Cờ | Ý nghĩa |
|---|---|
| `-Yes` (alias `-y`) | Chế độ không tương tác, tự đồng ý mọi bước |
| `-DashboardOnly` | Chỉ cài dashboard API + frontend (ngầm bật `-Yes`) |
| `-Dir C:\MyOstwin` | Cài vào thư mục khác (mặc định `%USERPROFILE%\.ostwin`) |
| `-Port 8080` | Đổi cổng dashboard (mặc định `3366`) |
| `-NoStart` | Cài nhưng không khởi động dịch vụ (vẫn đăng ký auto-start) |
| `-Channel` | Cài & khởi động connector Telegram/Discord/Slack |
| `-SkipOptional` | Bỏ qua thành phần tùy chọn (Pester…) |

Ví dụ cài nhanh:

```powershell
.\.agents\install.ps1 -Yes
```

### Trình cài đặt làm gì (tóm tắt)

1. Phát hiện nền tảng & package manager.
2. Cài dependency.
3. Build frontend dashboard.
4. Copy file vào `%USERPROFILE%\.ostwin`.
5. Tạo Python venv + vá cấu hình MCP, đồng bộ định nghĩa agent của opencode.
6. **Tạo `~/.ostwin/.env`** với `OSTWIN_API_KEY` và **`OSTWIN_VAULT_KEY`** sinh tự động.
7. Khởi tạo catalog model, cấu hình quyền opencode.
8. Cấu hình PATH, verify, khởi động dashboard, đăng ký auto-start.

> 🔑 **Quan trọng:** `OSTWIN_VAULT_KEY` là khóa mã hóa kho secret (vault). Nó được
> sinh tự động **một lần** khi tạo `.env`. **Đừng đổi** khóa này về sau — đổi khóa
> sẽ khiến mọi secret đã lưu (API key provider…) không giải mã được nữa.

---

## 3. Kiểm tra sau khi cài

```powershell
# 3.1 — .env tồn tại và có ĐỦ cả hai khóa
Get-Content "$env:USERPROFILE\.ostwin\.env" | Select-String 'OSTWIN_API_KEY|OSTWIN_VAULT_KEY'
# → phải thấy CẢ HAI dòng. Thiếu OSTWIN_VAULT_KEY = vault sẽ lỗi (xem Troubleshooting).

# 3.2 — Dashboard đang chạy
Invoke-RestMethod http://localhost:3366/api/health   # hoặc cổng bạn đã chọn

# 3.3 — Vault khỏe (sau khi dashboard đã chạy với OSTWIN_VAULT_KEY)
Invoke-RestMethod http://localhost:3366/api/settings/vault/health
# → "healthy": true, "key_configured": "True"
```

Mở dashboard: **http://localhost:3366**

---

## 4. Cấu hình AI Provider (BẮT BUỘC trước khi chạy plan)

Mặc định một số role (manager, qa, engineer, principal-engineer,
qa-automation-engineer, staff-manager) trỏ tới model `openai/gpt-5.5`. Nếu bạn
**chưa cấu hình provider tương ứng**, plan sẽ chạy được phần đầu rồi **chết ở bước
QA/triage** với lỗi `ProviderModelNotFoundError` (agent "Unexpected server error").

Cách đúng để khai báo credentials:

1. Mở **Dashboard → Settings → Providers**.
2. Nhập API key cho provider bạn dùng (OpenAI, Anthropic, Google/Vertex…).
3. Lưu — key được ghi vào **vault mã hóa** và tự đồng bộ sang
   `~/.local/share/opencode/auth.json` để opencode dùng.

> ⚠️ Đặt `OPENAI_API_KEY=...` vào file `.env` của **repo source** **KHÔNG** có tác
> dụng. Runtime của Ostwin đọc `~/.ostwin/.env` + vault mã hóa, không đọc `.env`
> của repo. Hãy nhập key qua dashboard (hoặc xem mục [nâng cao](#dùng-biến-môi-trường-thay-vault) bên dưới).

Nếu chỉ có credentials Google/Vertex, hãy đảm bảo model của các role trỏ về
provider Google/Vertex (sửa trong **Settings → Roles** hoặc `~/.ostwin/.agents/config.json`),
thay vì `openai/gpt-5.5`.

---

## 5. Troubleshooting

### Lỗi: `OSTWIN_VAULT_KEY is not set` (HTTP 500 khi lưu secret)

```
RuntimeError: Cannot read encrypted vault: OSTWIN_VAULT_KEY is not set.
Set it in ~/.ostwin/.env or in the process environment before starting the dashboard.
```

**Nguyên nhân:** `~/.ostwin/.env` thiếu `OSTWIN_VAULT_KEY` (các bản installer cũ
trên Windows không sinh khóa này).

**Cách khắc phục (chọn 1):**

**A. Chạy lại installer** (đã được vá để tự backfill khóa):
```powershell
.\.agents\install.ps1 -NoStart
```
Bước `Setup-Env` sẽ phát hiện thiếu và tự thêm `OSTWIN_VAULT_KEY` vào `.env`.

**B. Thêm khóa thủ công:**
```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$key = [Convert]::ToBase64String($bytes)
Add-Content "$env:USERPROFILE\.ostwin\.env" "`nOSTWIN_VAULT_KEY=$key"
```

Sau đó **khởi động lại dashboard** (biến env chỉ nạp lúc start):
```powershell
ostwin stop; ostwin start    # hoặc: ostwin dashboard restart
```

> Nếu trước đó đã có file vault cũ `~/.ostwin/vault/.vault.enc` (được mã hóa bằng
> một khóa khác/đã mất), nó sẽ không giải mã được bằng khóa mới. Sao lưu rồi xóa
> để tạo lại sạch:
> ```powershell
> Move-Item "$env:USERPROFILE\.ostwin\vault\.vault.enc" "$env:USERPROFILE\.ostwin\vault\.vault.enc.bak"
> ```
> Sau đó nhập lại các API key qua dashboard.

### Plan kẹt ở trạng thái `triage` / chạy mãi không xong

Thường do agent ở bước review/triage dùng model thuộc provider **chưa cấu hình
credentials** → opencode báo `ProviderModelNotFoundError`. Kiểm tra:

```powershell
# auth.json có entry provider chưa?
Get-Content "$env:USERPROFILE\.local\share\opencode\auth.json"
# {} rỗng = chưa có provider nào → xem Mục 4 để cấu hình
```

Khắc phục: cấu hình provider tương ứng (Mục 4), hoặc đổi model của role sang
provider đã có credentials.

### Symlink fallback / cảnh báo Developer Mode

Nếu thấy cảnh báo "Developer Mode not enabled — symlinks may fall back to
junctions": vào **Settings → For developers → Developer Mode** bật lên, rồi chạy
lại installer. Không bắt buộc nhưng giúp tránh một số vấn đề về symlink.

---

## 6. (Nâng cao) Dùng biến môi trường thay vault {#dùng-biến-môi-trường-thay-vault}

Mặc định trên Windows, vault backend là `encrypted_file` (đọc/ghi
`~/.ostwin/vault/.vault.enc`, dùng `OSTWIN_VAULT_KEY`). Nó **không** tự đọc các
biến như `OPENAI_API_KEY` từ môi trường.

Nếu muốn cấp credentials qua biến môi trường thay vì nhập qua dashboard:

1. Thêm key vào `~/.ostwin/.env` (file mà dashboard nạp lúc start), ví dụ:
   ```
   OPENAI_API_KEY=sk-...
   ```
2. Đặt backend vault sang chế độ env:
   ```
   OSTWIN_VAULT_BACKEND=env
   ```
3. Khởi động lại dashboard, rồi trigger đồng bộ:
   ```powershell
   Invoke-RestMethod -Method Post http://localhost:3366/api/settings/opencode/sync
   ```

Hoặc đơn giản hơn cho riêng opencode: thêm trực tiếp vào
`~/.local/share/opencode/auth.json`:
```json
{ "openai": { "type": "api", "key": "sk-..." } }
```

---

## 7. Lệnh thường dùng

```powershell
ostwin start            # khởi động dashboard + dịch vụ
ostwin stop             # dừng
ostwin dashboard restart
ostwin --help
```

Thư mục cài: `%USERPROFILE%\.ostwin`
Cấu hình runtime: `%USERPROFILE%\.ostwin\.env`
Vault: `%USERPROFILE%\.ostwin\vault\.vault.enc`
Auth opencode: `%USERPROFILE%\.local\share\opencode\auth.json`
