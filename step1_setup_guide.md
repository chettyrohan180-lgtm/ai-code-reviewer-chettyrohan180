# Step 1 — GitHub App Setup & Webhook Listener

## Project Structure Created

```
my 1st git project/
├── ai_code_reviewer/
│   ├── __init__.py
│   ├── config.py          ← Pydantic Settings singleton
│   ├── schemas.py         ← Webhook payload models + ReviewContext
│   ├── github_auth.py     ← JWT generation + installation token
│   ├── webhook.py         ← POST /api/webhook (HMAC + parser)
│   └── main.py            ← FastAPI app factory + entry point
├── secrets/               ← (create manually, add to .gitignore)
├── .env.example
└── requirements.txt
```

---

## Part A — Create the GitHub App

### 1. Navigate to App Creation
Go to: **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**

### 2. Fill in the App Form

| Field | Value |
|---|---|
| **App name** | `ai-code-reviewer-yourname` (must be globally unique) |
| **Homepage URL** | `https://github.com/yourname` (any valid URL) |
| **Webhook URL** | `https://<your-ngrok-url>/api/webhook` (use ngrok for local dev) |
| **Webhook secret** | Generate a strong random string (e.g. `openssl rand -hex 32`) |

### 3. Set Repository Permissions

| Permission | Level |
|---|---|
| Pull requests | **Read & Write** |
| Contents | **Read** |
| Metadata | **Read** |

### 4. Subscribe to Events
Tick: **Pull request**

### 5. Create & Download the Private Key

After creating the app:
- Scroll to **"Private keys"** → click **"Generate a private key"**
- A `.pem` file downloads automatically
- Move it to `./secrets/github_app.pem`

### 6. Note Your App ID
At the top of the App settings page — it looks like `App ID: 123456`

---

## Part B — Local Environment Setup

### 1. Create the secrets directory

```powershell
mkdir secrets
```

### 2. Add to `.gitignore`

```
.env
secrets/
__pycache__/
*.pyc
```

> [!CAUTION]
> Never commit `.env` or `secrets/github_app.pem` to git. They contain credentials that grant full write access to your repositories.

### 3. Create your `.env` file

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```ini
GITHUB_APP_ID=123456              # ← Your actual App ID
GITHUB_PRIVATE_KEY_PATH=./secrets/github_app.pem
GITHUB_WEBHOOK_SECRET=abc123...   # ← The secret you set on GitHub
PORT=8000
APP_ENV=development
```

---

## Part C — Install Dependencies & Run

```powershell
# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn ai_code_reviewer.main:app --reload --port 8000
```

You should see:
```
INFO | ai_code_reviewer.main | AI Code Reviewer starting | env=development | app_id=123456
INFO | uvicorn | Application startup complete.
```

---

## Part D — Expose Locally with ngrok

GitHub needs to reach your local server. Use [ngrok](https://ngrok.com/):

```powershell
# Install ngrok, then:
ngrok http 8000
```

Copy the `https://xxxx.ngrok-free.app` URL and paste it into your GitHub App's Webhook URL field as:
```
https://xxxx.ngrok-free.app/api/webhook
```

---

## Part E — Testing the Webhook

### Using the GitHub App test delivery
1. GitHub App settings → **Advanced** → **Recent Deliveries**
2. Click **Redeliver** on any `pull_request` event
3. Check your FastAPI logs — you should see:

```
INFO  | Webhook delivery abc123 | event=pull_request
DEBUG | Webhook signature verified
INFO  | Queuing review | repo=owner/repo pr=#42 sha=a1b2c3d4 files=5
```

### Using curl (manual test)

```powershell
# Generate a test HMAC signature (PowerShell)
$secret = "your_webhook_secret"
$body = '{"action":"opened","number":1,"pull_request":{},"repository":{},"sender":{}}'
$hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
$sig = "sha256=" + [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($body))).Replace("-","").ToLower()

Invoke-RestMethod -Uri "http://localhost:8000/api/webhook" `
  -Method POST `
  -Headers @{"X-Hub-Signature-256"=$sig; "X-GitHub-Event"="pull_request"} `
  -Body $body `
  -ContentType "application/json"
```

---

## Architecture Summary — Data Flow

```
GitHub PR opened
      │
      ▼
POST /api/webhook
      │
      ├─ _verify_signature()   ← HMAC-SHA256, constant-time compare
      │
      ├─ filter: event == "pull_request" && action in {opened, synchronize, reopened}
      │
      ├─ _parse_pull_request_event()  ← Pydantic validation
      │
      ├─ _build_review_context()      ← Distill to ReviewContext
      │
      └─ TODO: pipeline.run(context)  ← Added in Step 3
```

---

## What's Next — Step 2

> **Step 2: Git Diff Analysis & Tree-sitter AST Parsing Engine**
>
> We'll clone the PR's HEAD commit, run `git diff`, and use Tree-sitter
> to isolate *only the changed AST nodes* (functions, classes, methods)
> for targeted LLM analysis — avoiding token waste on unchanged code.
