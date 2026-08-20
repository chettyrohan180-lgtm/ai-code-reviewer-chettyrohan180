# Autonomous AI Code Reviewer

An event-driven, multi-agent automated code review system built with **FastAPI**, **Tree-sitter AST parsing**, and **LLMs** (OpenAI, Gemini, Anthropic Claude, Ollama). It listens for GitHub Pull Request events, isolates modified code structures (functions, classes, methods), executes specialized review agents in parallel, and submits line-accurate inline review comments with clickable **GitHub Suggestion Blocks** alongside an executive review verdict (`APPROVE`, `REQUEST_CHANGES`, `COMMENT`).

---

## Table of Contents

- [Overview & Architecture](#-overview--architecture)
- [How It Works (Step-by-Step Pipeline)](#-how-it-works-step-by-step-pipeline)
- [Prerequisites](#-prerequisites)
- [Installation & Setup Guide](#-installation--setup-guide)
  - [Step 1: Download or Clone the Repository](#step-1-download-or-clone-the-repository)
  - [Step 2: Create & Activate Virtual Environment](#step-2-create--activate-virtual-environment)
  - [Step 3: Install Project Dependencies](#step-3-install-project-dependencies)
  - [Step 4: Configure Local Secrets & Environment Variables](#step-4-configure-local-secrets--environment-variables)
- [GitHub App Setup Walkthrough](#-github-app-setup-walkthrough)
- [Webhook Tunneling Setup (ngrok)](#-webhook-tunneling-setup-ngrok)
- [Running & Testing the System](#-running--testing-the-system)
  - [1. Running the FastAPI Local Webhook Server](#1-running-the-fastapi-local-webhook-server)
  - [2. Testing Webhook Ingestion (3 Methods)](#2-testing-webhook-ingestion-3-methods)
  - [3. Offline Local Review Simulation (CLI Tool)](#3-offline-local-review-simulation-cli-tool)
  - [4. Running the Automated Test Suite](#4-running-the-automated-test-suite)
- [Method B: Docker & Docker Compose (Production Deployment)](#-method-b-docker--docker-compose-production-deployment)
- [ Project Directory Structure](#-project-directory-structure)
- [ Troubleshooting & FAQs](#-troubleshooting--faqs)
- [ License](#-license)

---

##  Overview & Architecture

Modern AI code reviewers often suffer from token waste, hallucinated line numbers, and superficial reviews because they pass entire raw files or unstructured diff snippets to an LLM.

**Autonomous AI Code Reviewer** solves this with a **6-stage modular pipeline**:

```
GitHub Pull Request Event (opened / synchronize / reopened)
                         │
                         ▼
             [Step 1: Webhook Ingestion]
   • HMAC-SHA256 constant-time signature verification
   • GitHub App JWT & Installation Access Token generation
   • Immediate 202 Accepted response; background worker dispatch
                         │
                         ▼
       [Step 2: Diff & Tree-sitter AST Engine]
   • Git patch parser calculating 1-indexed added/modified line numbers
   • Automatic filtering (lockfiles, minified bundles, binaries)
   • Tree-sitter AST extraction: isolates only modified functions & classes
                         │
                         ▼
          [Step 3 & 4: Multi-Agent LLM Review]
   ┌─────────────────────┬─────────────────────┬─────────────────────┐
   ▼                     ▼                     ▼                     ▼
Security Agent    Performance Agent     Logic Bug Hunter      Quality Agent
 (Dual-Layer: AST & Regex Rules + Semantic LLM Reasoning via OpenAI/Gemini/Claude)
   └─────────────────────┴─────────────────────┴─────────────────────┘
                         │
                         ▼
        [Deduplication & Verdict Calculation]
   • Merges rule-based & LLM findings (confidence threshold >= 70%)
   • Determines verdict: APPROVE | COMMENT | REQUEST_CHANGES
                         │
                         ▼
            [Step 5: GitHub Review Bot]
   • Submits atomic GitHub Pull Request Review
   • Posts line-accurate inline comments with ```suggestion``` blocks
   • Renders structured Markdown summary table
```

---

## How It Works (Step-by-Step Pipeline)

### Step 1: GitHub App & Webhook Ingestion
- **Modules:** `ai_code_reviewer/webhook.py`, `ai_code_reviewer/github_auth.py`
- **Security:** Incoming requests at `POST /api/webhook` are checked against the `X-Hub-Signature-256` header using an HMAC-SHA256 hash computed with your secret.
- **Authentication:** Generates a short-lived RSA-256 JWT signed with your GitHub App private key (`.pem`), which is exchanged for an Installation Access Token scoped to the repository.
- **Asynchronous Execution:** Fast response (`202 Accepted`) prevents GitHub webhook timeouts (10s limit) while heavy AST parsing and AI analysis run in FastAPI `BackgroundTasks`.

### Step 2: Git Diff Analysis & Tree-sitter AST Engine
- **Modules:** `ai_code_reviewer/diff_parser.py`, `ai_code_reviewer/ast_parser.py`, `ai_code_reviewer/github_diff_fetcher.py`
- **Diff Parsing:** Extracts 1-indexed target line numbers for additions (`+`) and modifications from unified diff hunks (`@@ -old,count +new,count @@`).
- **File Filtering:** Automatically ignores non-code files (`package-lock.json`, `poetry.lock`, `.min.js`, `.png`, `.map`, vendor directories).
- **AST Parsing:** Uses **Tree-sitter** (Python and JavaScript/TypeScript grammars) to find exact function, method, class, and arrow function syntax nodes that enclose the changed lines. Only modified code blocks are passed to the AI, saving tokens and providing rich enclosing scope.

### Step 3: Multi-Agent Review Pipeline
- **Modules:** `ai_code_reviewer/agents/`, `ai_code_reviewer/pipeline.py`
- **Concurrent Execution:** Dispatches 4 specialized agents in parallel via Python `asyncio.gather`:
  1. **Security Agent (`SecurityAgent`)**: Audits for OWASP Top 10, SQL injection, hardcoded secrets/tokens, `eval`/`exec`, unsafe `shell=True`, and insecure deserialization.
  2. **Performance Agent (`PerformanceAgent`)**: Detects $O(N^2)$ loops, N+1 database query patterns, memory leaks, and blocking calls (`time.sleep`) in async routines.
  3. **Logic Bug Hunter (`LogicBugAgent`)**: Identifies mutable default arguments (`def f(x=[])`), unhandled `None` values, bare exception catches (`except:`), and broken boolean logic.
  4.**Code Quality Agent (`QualityAgent`)**: Enforces type safety, docstrings on public APIs, clean code hygiene, and removes leftover debug `print` statements.

### Step 4: LLM Integration & Prompt Orchestrator
- **Modules:** `ai_code_reviewer/llm/client.py`, `ai_code_reviewer/llm/prompts.py`
- **Multi-Provider Support:** Supports OpenAI (GPT-4o, GPT-4o-mini), Google Gemini, Anthropic Claude, OpenRouter, local Ollama endpoints, and offline mock mode.
- **Structured JSON Schema:** Enforces strict JSON output format containing `file`, `line_start`, `line_end`, `symbol_name`, `severity`, `title`, `message`, `suggested_fix`, and `confidence_score`.
- **Dual-Layer Analysis:** Agents run instant deterministic rules first, followed by deep LLM reasoning, deduplicating findings and discarding low-confidence entries (`< 0.70`).

### Step 5: GitHub PR Commenting & Bot Integration
- **Module:** `ai_code_reviewer/github_commenter.py`
- **Inline Comments:** Submits granular comments placed directly on the affected lines in the PR diff.
- **GitHub Suggestion Blocks:** Generates clickable suggestion blocks:
  ````markdown
  ```suggestion
  new_fixed_code_here()
  ```
  ````
  Developers can click **"Commit suggestion"** directly inside the GitHub PR interface!
- **Review Verdict:** Submits official PR status (`APPROVE` for clean code, `REQUEST_CHANGES` for critical/high vulnerabilities, `COMMENT` for non-blocking advice).
- **Error Fallback:** If an inline comment's line is outside diff hunk boundaries, falls back to submitting the review summary body to ensure feedback is never lost.

### Step 6: Production Deployment & CLI Simulator
- **Modules:** `Dockerfile`, `docker-compose.yml`, `scripts/simulate_review.py`, `.github/workflows/test.yml`
- **Dockerization:** Multi-stage production build with non-root security compliance (`appuser`).
- **Local CLI Tester:** Allows testing reviews on local files or git diffs offline without active webhooks.
- **CI/CD:** Automated GitHub Actions matrix testing across Python 3.11, 3.12, and 3.13.

---

## Prerequisites

Before setting up, ensure you have:
1. **Python 3.11+**: Check version by running:
   ```bash
   python --version
   # or
   python3 --version
   ```
   If not installed, download it from [python.org](https://www.python.org/downloads/).
2. **Git**: Check version by running:
   ```bash
   git --version
   ```
   If not installed, download it from [git-scm.com](https://git-scm.com/).
3. **ngrok**: Required for exposing your local FastAPI webhook port to the internet. Download it from [ngrok.com](https://ngrok.com/).
4. **LLM API Key**: OpenAI, Gemini, or Anthropic. (You can also run offline using the built-in **Mock** provider without any keys).
5. *(Optional)* **Docker & Docker Compose**: Needed if you plan to run the server in containers.

---

## Installation & Setup Guide

Follow these steps to set up the project locally on your machine.

### Step 1: Download or Clone the Repository

You can get the project code in two ways:

#### Option A: Clone using Git (Recommended)
Open your terminal (PowerShell, Command Prompt, or Bash) and run one of the following commands:
* **HTTPS**:
  ```bash
  git clone https://github.com/chettyrohan180-lgtm/ai-code-reviewer-chettyrohan180.git
  ```
* **SSH**:
  ```bash
  git clone git@github.com:chettyrohan180-lgtm/ai-code-reviewer-chettyrohan180.git
  ```
* **GitHub CLI**:
  ```bash
  git clone gh repo clone chettyrohan180-lgtm/ai-code-reviewer-chettyrohan180
  ```

#### Option B: Download as a ZIP File
1. Visit the repository page on GitHub: [github.com/Rohanchetty-25/Rohanchetty-25](https://github.com/Rohanchetty-25/Rohanchetty-25).
2. Click the green **Code** button at the top right of the file explorer.
3. Click **Download ZIP** in the dropdown menu.
4. Locate the downloaded file (`Rohanchetty-25-main.zip` or similar) in your downloads folder.
5. Extract it to a folder of your choice (e.g. Desktop).
6. Open your terminal or Command Prompt.
7. Navigate to the extracted folder:
   ```powershell
   cd "C:\Users\Rohan chetty\OneDrive\Desktop\my 1st git project"
   ```

---

### Step 2: Create & Activate Virtual Environment

A virtual environment isolates this project's dependencies from your global system environment.

* **On Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
* **On Windows (Command Prompt):**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate.bat
  ```
* **On macOS / Linux (Bash/Zsh):**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

> [!TIP]
> When active, your terminal prompt will be prefixed with `(.venv)`. To exit the virtual environment at any time, simply run the command `deactivate`.

---

### Step 3: Install Project Dependencies

Make sure your virtual environment is active, then upgrade `pip` and install all required modules:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This will automatically fetch and install FastAPI, Uvicorn, Pydantic, PyGithub, cryptography, and the Tree-sitter parsers for Python and JavaScript.

---

### Step 4: Configure Local Secrets & Environment Variables

Copy the `.env.example` file to create a working `.env` configuration file:

* **On Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
* **On Windows (Command Prompt):**
  ```cmd
  copy .env.example .env
  ```
* **On macOS / Linux:**
  ```bash
  cp .env.example .env
  ```

#### Setup Secrets Directory
Create a directory to store your private credentials. This directory is already configured in `.gitignore` so that keys will never be checked into your git history.
```bash
mkdir secrets
```

#### Edit Your Environment File
Open the new `.env` file in a text editor (such as VS Code, Notepad, or nano). Modify the parameters as shown below:

```ini
# ==============================================================================
# GitHub App Authentication
# ==============================================================================
GITHUB_APP_ID=123456                        # Found on your GitHub App General settings page
GITHUB_PRIVATE_KEY_PATH=./secrets/github_app.pem
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here  # Shared secret key set on GitHub

# ==============================================================================
# Server Settings
# ==============================================================================
PORT=8000
APP_ENV=development

# ==============================================================================
# LLM Provider Configuration
# Choose your active profile: "openai", "gemini", "anthropic", "custom", or "mock"
# ==============================================================================
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=4096
```

#### LLM Provider Settings Profiles

Configure the LLM settings in your `.env` according to the provider you wish to use:

##### Profile 1: OpenAI (Default)
```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-openai-key-here
LLM_MODEL=gpt-4o-mini
```

##### Profile 2: Google Gemini
```ini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaSyYourGeminiKeyHere
LLM_MODEL=gemini-2.5-flash
```

##### Profile 3: Anthropic Claude
```ini
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-claude-key-here
LLM_MODEL=claude-3-5-sonnet-latest
```

##### Profile 4: Local Ollama (or custom OpenAI-compatible proxies)
Ensure Ollama is running locally on your machine first.
```ini
LLM_PROVIDER=custom
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.1
```

##### Profile 5: Offline Mock Mode (No Keys Required)
Use this profile to run tests and simulation scripts locally without making API calls or spending credits.
```ini
LLM_PROVIDER=mock
```

> [!CAUTION]
> Never commit your `.env` file or files inside `./secrets/` to a public repository. They contain sensitive credentials that grant read/write access to your code and your paid LLM accounts.

---

## GitHub App Setup Walkthrough

The bot authenticates with GitHub using a **GitHub App**. Follow these steps to register your own:

### 1. Register the Application on GitHub
1. Sign in to GitHub and navigate to: **Settings → Developer Settings → GitHub Apps → New GitHub App**.
2. Fill out the application profile:
   * **GitHub App name**: Give it a unique, personalized name (e.g. `ai-reviewer-rohan-2026`).
   * **Homepage URL**: Input a temporary placeholder, such as `https://github.com`.
   * **Webhook URL**: Input a temporary placeholder, e.g. `http://localhost:8000/api/webhook`. (We will update this in the next section with an `ngrok` URL).
   * **Webhook secret**: Type a strong random password (e.g. `openssl rand -hex 32` or similar random string). Copy this value and save it in `.env` as `GITHUB_WEBHOOK_SECRET`.

### 2. Configure Scopes and Permissions
Scroll down to the **Permissions** panel, click **Repository permissions**, and set:
* **Pull requests**: `Read & Write` *(needed to post inline comments and review approvals/rejections)*
* **Contents**: `Read-only` *(needed to fetch the raw source code files and pull patches)*
* **Metadata**: `Read-only` *(mandatory minimum scope)*

### 3. Subscribe to Events
Navigate to the **Subscribe to events** section and check:
* **Pull request**

Click **Create GitHub App** at the bottom of the page to save.

### 4. Create and Install the Private Key
1. After the app creation page reloads, look at the top left to find your numeric **App ID** (e.g. `987654`). Copy this ID and save it in your `.env` file as `GITHUB_APP_ID`.
2. Scroll to the bottom of the page to find the **Private keys** section.
3. Click **Generate a private key**. A `.pem` authentication file will be downloaded to your computer automatically.
4. Rename the downloaded file to `github_app.pem` and move it to the `./secrets/` folder in your project repository:
   `c:\Users\Rohan chetty\OneDrive\Desktop\my 1st git project\secrets\github_app.pem`
5. On the left sidebar, click **Install App**.
6. Select your GitHub user account or organization, click **Install**, and choose whether to grant access to **All repositories** or **Only select repositories**.

---

## Webhook Tunneling Setup (ngrok)

Because GitHub is on the public web, it cannot send webhook events to a local address like `localhost:8000`. You must create a secure public tunnel to route GitHub traffic to your local server.

### 1. Install & Configure ngrok
1. Sign up for a free account at [ngrok.com](https://ngrok.com/).
2. Down and extract the ngrok client.
3. Connect your account by copying the auth token command from your ngrok dashboard:
   ```bash
   ngrok config add-authtoken <your-auth-token>
   ```

### 2. Start the ngrok Tunnel
In a new, separate terminal window (leave this terminal running in the background), execute:
```bash
ngrok http 8000
```
Your terminal will output status details along with a public forwarding address:
```
Forwarding                    https://a1b2-c3d4-e5f6.ngrok-free.app -> http://localhost:8000
```
Copy this generated `https://...` address.

### 3. Update Webhook settings on GitHub
1. Return to your **GitHub Settings → Developer Settings → GitHub Apps**.
2. Click **Edit** next to your registered App.
3. Scroll to the **Webhook URL** field.
4. Replace the placeholder URL with your ngrok forwarding address, appending `/api/webhook` at the end:
   `https://a1b2-c3d4-e5f6.ngrok-free.app/api/webhook`
5. Click **Save changes**.

---

## Running & Testing the System

### 1. Running the FastAPI Local Webhook Server

Open a terminal in your project workspace directory (ensure your virtual environment is active) and start the local FastAPI web server:

```bash
uvicorn ai_code_reviewer.main:app --reload --port 8000
```

#### Verify Server Liveness
Verify that your server started successfully by querying the `/health` endpoint:
* **Via Web Browser**: Go to `http://localhost:8000/health`
* **Via Terminal (PowerShell)**:
  ```powershell
  Invoke-RestMethod -Uri "http://localhost:8000/health"
  ```
* **Via Terminal (cURL)**:
  ```bash
  curl http://localhost:8000/health
  ```
**Expected Response:**
```json
{
  "status": "healthy",
  "env": "development",
  "app_id": 123456
}
```

---

### 2. Testing Webhook Ingestion (3 Methods)

You can trigger and test incoming webhook processing using any of these methods:

#### Method A: Simulated payload via PowerShell Script (Windows)
Create and run a local webhook request manually from your terminal. Replace `your_webhook_secret_here` with the secret defined in your `.env`:

```powershell
$secret = "your_webhook_secret_here"
$body = '{"action":"opened","number":1,"pull_request":{"number":1,"title":"Test PR","head":{"sha":"abc123sha","ref":"feature-test"},"base":{"ref":"main"},"additions":10,"deletions":2,"changed_files":1},"repository":{"full_name":"local/test-repo","clone_url":"https://github.com/local/test-repo.git"},"sender":{"login":"test-user"}}'
$hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($secret))
$sig = "sha256=" + [BitConverter]::ToString($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($body))).Replace("-","").ToLower()

Invoke-RestMethod -Uri "http://localhost:8000/api/webhook" `
  -Method POST `
  -Headers @{"X-Hub-Signature-256"=$sig; "X-GitHub-Event"="pull_request"} `
  -Body $body `
  -ContentType "application/json"
```

#### Method B: Simulated payload via curl (macOS / Linux)
```bash
SECRET="your_webhook_secret_here"
BODY='{"action":"opened","number":1,"pull_request":{"number":1,"title":"Test PR","head":{"sha":"abc123sha","ref":"feature-test"},"base":{"ref":"main"},"additions":10,"deletions":2,"changed_files":1},"repository":{"full_name":"local/test-repo","clone_url":"https://github.com/local/test-repo.git"},"sender":{"login":"test-user"}}'
SIG="sha256=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)"

curl -X POST http://localhost:8000/api/webhook \
  -H "X-Hub-Signature-256: $SIG" \
  -H "X-GitHub-Event: pull_request" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

#### Method C: Redeliver Webhooks from the GitHub UI
1. Go to your **GitHub App settings → Advanced → Recent Deliveries**.
2. Choose any previous payload delivery from the log list.
3. Click the **Redeliver** button to replay the event payload directly to your ngrok tunnel endpoint.
4. Verify your local server terminal output for incoming pipeline traces!

---

### 3. Offline Local Review Simulation (CLI Tool)

You can run the full multi-agent code analysis suite offline on your local computer. This is extremely useful for checking security and code syntax vulnerabilities before pushing to GitHub.

Use the custom offline script `scripts/simulate_review.py`:

#### Option 1: Run the Demo (Analyzes the project's security agent)
```bash
python scripts/simulate_review.py
```

#### Option 2: Analyze a specific file
```bash
python scripts/simulate_review.py --file ai_code_reviewer/config.py
```

#### Option 3: Analyze specific lines of a file
```bash
python scripts/simulate_review.py --file ai_code_reviewer/config.py --lines 10,11,12,13
```

#### Option 4: Analyze your current unstaged Git changes against HEAD
```bash
python scripts/simulate_review.py --git
```

##### Sample Terminal Output:
```
[AST Parser] Analyzing 'src/auth.py' (python, 3 target line(s))...
   Extracted 1 enclosing AST symbol(s), 0 unscoped line(s)
     • AuthService.login (function_definition) lines 10-25

[Multi-Agent Pipeline] Running Security, Performance, Logic, and Quality Agents...

======================================================================
## Autonomous AI Code Review — **CHANGES REQUESTED**

**PR #1:** Local Simulation Review of auth.py  
**Author:** @local-developer | **Commit:** `00000000` | **Analysis Time:** `412.3 ms`

### Review Overview
| Agent | Category | Findings | Status |
|---|---|:---:|:---:|
| **SecurityAgent** | Security | 1 | Issues Found |
| **PerformanceAgent** | Performance | 0 | Pass |
| **LogicBugAgent** | Bug Risk | 0 | Pass |
| **QualityAgent** | Quality | 0 | Pass |

### Detailed Findings

#### 1. `CRITICAL` **Hardcoded Secret / API Token Detected** (Security)
- **Location:** `src/auth.py:12` in `AuthService.login`
- **Details:** Potential hardcoded secret or credential found in source code. Credentials must be loaded via environment variables.
- **Recommendation:**
  ```suggestion
  api_key = os.getenv("API_KEY")
  ```

---
*Generated autonomously by AI Code Reviewer Agent Pipeline.*
======================================================================
```

---

### 4. Running the Automated Test Suite

The project comes with a comprehensive testing suite comprising **34 tests** checking payload signatures, Tree-sitter symbol extractors, diff patch parses, LLM parser handlers, and GitHub commenters.

Ensure your virtual environment is active, then run:

```bash
# Run all tests
pytest tests/ -v

# Run with stdout printing active
pytest tests/ -v -s
```

---

## Method B: Docker & Docker Compose (Production Deployment)

For hosting in production environments, use the included Docker deployment configuration.

### 1. Build and run containers in the background
```bash
docker compose up -d --build
```

### 2. Monitor Container Status
```bash
# Verify container is running
docker compose ps

# Watch real-time log traces
docker compose logs -f ai-code-reviewer
```

### 3. Stop and remove containers
```bash
docker compose down
```

---

## Project Directory Structure

```
my 1st git project/
├── ai_code_reviewer/               # Core Application Package
│   ├── agents/                     # Specialized Review Agents
│   │   ├── __init__.py
│   │   ├── base.py                 # Base agent class & prompt context builder
│   │   ├── security_agent.py       # OWASP, secrets, injection analyzer
│   │   ├── performance_agent.py    # N+1 queries, loops, async blocking
│   │   ├── logic_agent.py          # Mutable defaults, bare except, logic bugs
│   │   └── quality_agent.py        # Type hints, docstrings, debug prints
│   ├── llm/                        # Multi-Provider LLM Integration
│   │   ├── __init__.py
│   │   ├── client.py               # Async HTTP client with structured JSON
│   │   └── prompts.py              # Domain system prompts & JSON schemas
│   ├── __init__.py
│   ├── ast_parser.py               # Tree-sitter AST symbol extractor
│   ├── config.py                   # Pydantic BaseSettings configuration
│   ├── diff_parser.py              # Git unified diff parser & file filter
│   ├── github_auth.py              # GitHub App JWT & Installation Token generator
│   ├── github_commenter.py         # PR review & inline comment submitter
│   ├── github_diff_fetcher.py      # PR diff & raw file content orchestrator
│   ├── main.py                     # FastAPI application entrypoint
│   ├── pipeline.py                 # Multi-agent concurrent review pipeline
│   ├── schemas.py                  # Pydantic schemas, models, and enums
│   └── webhook.py                  # HMAC verification & webhook endpoint
├── scripts/
│   └── simulate_review.py          # Local review simulator CLI tool
├── tests/                          # Automated Pytest Suite (34 tests)
│   ├── __init__.py
│   ├── test_agents.py              # Unit tests for specialized agents
│   ├── test_ast_parser.py          # Unit tests for Tree-sitter AST extraction
│   ├── test_diff_fetcher.py        # Unit tests for PR diff fetcher
│   ├── test_diff_parser.py         # Unit tests for git patch parser
│   ├── test_github_commenter.py    # Unit tests for PR review posting
│   ├── test_llm_agents.py          # Unit tests for dual-layer agent reasoning
│   ├── test_llm_client.py          # Unit tests for async LLM client & retries
│   ├── test_pipeline.py            # Integration tests for review pipeline
│   ├── test_prompts.py             # Unit tests for prompt formatting
│   └── test_webhook.py             # Integration tests for webhook HMAC verification
├── .github/
│   └── workflows/
│       └── test.yml                # GitHub Actions CI matrix testing workflow
├── secrets/                        # Directory for private keys (gitignored)
│   └── github_app.pem              # GitHub App RSA private key (PEM)
├── .dockerignore                   # Files to ignore in Docker builds
├── .env.example                    # Template environment variables
├── .gitignore                      # Files excluded from git tracking
├── docker-compose.yml              # Production Docker Compose config
├── Dockerfile                      # Multi-stage production container definition
├── requirements.txt                # Python package dependencies
├── step1_setup_guide.md            # Reference guide for Step 1 App creation
└── README.md                       # Main project documentation
```

---

## Troubleshooting & FAQs

### 1. `401 Unauthorized: Invalid webhook signature`
* **Cause**: The `GITHUB_WEBHOOK_SECRET` in your local `.env` does not match the Webhook Secret key string configured in your GitHub App settings page.
* **Solution**: Copy the exact webhook secret string from GitHub developer dashboard and paste it into `.env`, then restart your FastAPI server.

### 2. `FileNotFoundError: GitHub App private key not found at: ./secrets/github_app.pem`
* **Cause**: Your RSA `.pem` private key file is missing, misnamed, or in the wrong directory.
* **Solution**:
  1. Download a new key from your App settings page.
  2. Create a folder named `secrets` in the root folder of the project.
  3. Save the key file as `github_app.pem` inside that folder.

### 3. `422 Unprocessable Entity when posting comments`
* **Cause**: Occurs if an inline review comment is submitted on a line number that does not exist in the PR's unified diff patch hunks.
* **Solution**: You don't need to change anything! The system includes an automatic fallback handler inside `github_commenter.py` that intercepts this and appends findings to the top-level PR review summary so no comments are lost.

### 4. `LLM Client Request Failures or Rate Limits`
* **Cause**: Incorrect API keys or network restrictions.
* **Solution**: Verify your target provider and API keys in `.env`. Alternatively, configure `LLM_PROVIDER=mock` to run without API requirements.

---

## License

This project is licensed under the **MIT License**. Feel free to use, modify, and distribute it for personal and commercial projects.
