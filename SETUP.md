# FraudGuard AI — Setup & Execution Guide

> Real-Time Multi-Layer Identity Fraud Detection System  
> Follow this guide step by step after cloning the repository.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Prerequisites](#2-prerequisites)
3. [Backend Setup](#3-backend-setup)
4. [Admin Dashboard Setup](#4-admin-dashboard-setup)
5. [Browser Extension Setup](#5-browser-extension-setup)
6. [Test Form Setup](#6-test-form-setup)
7. [Environment Variables](#7-environment-variables)
8. [Running the Full System](#8-running-the-full-system)
9. [Testing the System](#9-testing-the-system)
10. [Default Credentials](#10-default-credentials)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Project Structure

```
SE---Fraud-Detection/
├── backend/                  # FastAPI backend (Python)
│   ├── app/
│   │   ├── main.py           # Application entry point
│   │   ├── api/routes/       # API endpoints (analyze, submit, admin, otp)
│   │   ├── services/         # ML service, OTP service, auto-decision engine
│   │   ├── core/             # Config, database, auth, rate limiter
│   │   └── models/           # Pydantic schemas
│   ├── indices/              # FAISS index files (auto-created on first run)
│   ├── requirements.txt      # Python dependencies
│   └── .env                  # Environment variables (you create this)
│
├── admin-dashboard/          # React admin dashboard (Node.js)
│   ├── src/
│   ├── package.json
│   └── vite.config.js
│
├── extension/                # Chrome browser extension
│   ├── manifest.json
│   └── src/
│       ├── content.js        # Form monitoring script
│       ├── background.js     # Service worker
│       └── popup/            # Extension popup UI
│
└── test-form/                # Sample registration forms for testing
    ├── index.html            # Main test form (EduVerify / Job / Insurance / E-Commerce)
    └── status.html           # Application status check page
```

---

## 2. Prerequisites

Make sure the following are installed on your system:

| Tool | Version | Check Command |
|---|---|---|
| Python | 3.10 or above | `python3 --version` |
| pip | Latest | `pip3 --version` |
| Node.js | 18 or above | `node --version` |
| npm | 9 or above | `npm --version` |
| Google Chrome | Any recent | Open Chrome |
| MongoDB | Optional (system works without it) | `mongod --version` |

> **MongoDB is optional.** If MongoDB is not running, the system automatically falls back to in-memory storage. All features work — data is just not persisted across server restarts.

---

## 3. Backend Setup

### Step 3.1 — Navigate to the backend folder

```bash
cd backend
```

### Step 3.2 — Create a virtual environment

```bash
python3 -m venv venv
```

### Step 3.3 — Activate the virtual environment

**macOS / Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

You should see `(venv)` appear at the start of your terminal prompt.

### Step 3.4 — Install dependencies

```bash
pip install -r requirements.txt
```

> This installs FastAPI, FAISS, SentenceTransformer, MongoDB driver, LLM SDKs, and all other dependencies. The first install may take 3–5 minutes as it downloads the ML model.

### Step 3.5 — Create the environment file

Create a file named `.env` inside the `backend/` folder:

```bash
touch .env
```

Paste the following into `.env`:

```env
# API Authentication
API_KEY=dev-key-change-in-production

# JWT for Admin Dashboard
JWT_SECRET=my-secret-key-123

# MongoDB (optional — remove if not using)
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=fraud_detection_db

# LLM API Keys (optional — system works without them using heuristic fallback)
GEMINI_API_KEY=your-gemini-api-key-here
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# Admin credentials
ADMIN_USERNAME=admin
# Default password hash for "admin123"
ADMIN_PASSWORD_HASH=$2b$12$02wzWjcbSLjesWzheYTMY.6sGgzouMuugWkL/FQkbUirt.AJ2hDJy
```

> **LLM API keys are optional.** Without them, the decision engine uses a built-in heuristic fallback. The core fraud detection (Layers 1, 2, 3, 4) works fully without any API keys.

### Step 3.6 — Start the backend server

```bash
uvicorn app.main:app --reload --port 8000
```

**Expected output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Successfully connected to MongoDB.   ← (or "Falling back to IN-MEMORY storage")
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Step 3.7 — Verify the backend is running

Open your browser and visit:

```
http://localhost:8000/health
```

You should see:
```json
{"status": "ok"}
```

---

## 4. Admin Dashboard Setup

Open a **new terminal window** (keep the backend running).

### Step 4.1 — Navigate to the dashboard folder

```bash
cd admin-dashboard
```

### Step 4.2 — Install dependencies

```bash
npm install
```

### Step 4.3 — Start the dashboard

```bash
npm run dev
```

**Expected output:**
```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
```

### Step 4.4 — Open the dashboard

Visit in your browser:

```
http://localhost:5173
```

Login with:
- **Username:** `admin`
- **Password:** `admin123`

---

## 5. Browser Extension Setup

The extension must be loaded manually into Chrome as an **unpacked extension**.

### Step 5.1 — Open Chrome Extensions page

Open Chrome and go to:

```
chrome://extensions
```

### Step 5.2 — Enable Developer Mode

Toggle **"Developer mode"** ON (top right corner of the extensions page).

### Step 5.3 — Load the extension

1. Click **"Load unpacked"**
2. Navigate to and select the `extension/` folder from the cloned repository
3. Click **Select / Open**

The **Fraud Detection Monitor** extension should now appear in your extensions list.

### Step 5.4 — Pin the extension (optional but recommended)

Click the puzzle piece icon in Chrome toolbar → click the pin icon next to **Fraud Detection Monitor**.

### Step 5.5 — Set the API key in the extension

1. Click the extension icon in the Chrome toolbar
2. In the popup, enter the API key: `dev-key-change-in-production`
3. Click **Save**

> This must match the `API_KEY` value in your backend `.env` file.

---

## 6. Test Form Setup

The test forms are plain HTML files — no server needed.

### Step 6.1 — Open the test form

Simply open the file directly in Chrome:

```
test-form/index.html
```

**Or** drag and drop `index.html` into a Chrome browser window.

You will see a multi-platform test page with four tabs:
- **Job Portal**
- **E-Commerce**
- **Insurance Claims**
- **EduVerify — Exam Registration** ← recommended for demo

---

## 7. Environment Variables

Full reference for the `.env` file in `backend/`:

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `dev-key-change-in-production` | Key the extension sends with every request |
| `JWT_SECRET` | `jwt-secret-change-in-production` | Secret for signing admin JWT tokens |
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection string |
| `DATABASE_NAME` | `fraud_detection_db` | MongoDB database name |
| `ADMIN_USERNAME` | `admin` | Dashboard login username |
| `ADMIN_PASSWORD_HASH` | (bcrypt hash of `admin123`) | Dashboard login password hash |
| `GEMINI_API_KEY` | _(empty)_ | Gemini Flash API key (optional) |
| `ANTHROPIC_API_KEY` | _(empty)_ | Claude Haiku API key (optional) |
| `HIGH_RISK_THRESHOLD` | `85.0` | Similarity % above which risk is HIGH |
| `MEDIUM_RISK_THRESHOLD` | `60.0` | Similarity % above which risk is MEDIUM |
| `DEVICE_MAX_ATTEMPTS` | `3` | Max submissions per device per hour |
| `DEVICE_WINDOW_MINUTES` | `60` | Velocity check rolling window (minutes) |

---

## 8. Running the Full System

Once all steps above are done, you need **three things running simultaneously:**

| Component | Command | URL |
|---|---|---|
| Backend | `uvicorn app.main:app --reload --port 8000` | http://localhost:8000 |
| Admin Dashboard | `npm run dev` | http://localhost:5173 |
| Extension | Loaded in Chrome (no command needed) | — |

And the test form open in Chrome:

```
test-form/index.html
```

---

## 9. Testing the System

Run these tests in order to verify all layers are working.

### Test 1 — Legitimate New User (should AUTO-APPROVE)

1. Open `test-form/index.html` → go to **EduVerify** tab
2. Fill in:
   - **Full Name:** `Arjun Mehta`
   - **Email:** `arjun.mehta@gmail.com`
   - **Phone:** `9876543210`
   - **Course:** Any
3. Click **Send OTP** → enter the OTP shown → click **Verify**
4. Click **Register for Exam**

**Expected:** Green banner — `"Identity registered successfully"`

---

### Test 2 — Exact Same Person Again (Layer 1 — should AUTO-REJECT)

1. Without refreshing, click **Register for Exam** again
2. Send OTP → Verify → Submit

**Expected:** Red banner — `"Returning user: exact identity fingerprint already registered"`

---

### Test 3 — Same Phone, Different Name (Phone Check — should AUTO-REJECT)

1. Refresh the page
2. Fill in:
   - **Full Name:** `Rahul Verma`
   - **Email:** `rahul.v@outlook.com`
   - **Phone:** `9876543210` ← same phone as Test 1
3. Send OTP → Verify → Submit

**Expected:** Red banner — `"Phone number already registered to another account"`

---

### Test 4 — Similar Name, New Phone (Layer 2 — should ESCALATE or REJECT)

1. Refresh the page
2. Fill in:
   - **Full Name:** `Arjun Mehta` ← watch for orange warning on the field
   - **Email:** `arjun.mehta@yahoo.com`
   - **Phone:** `9123456780` ← new phone
3. Send OTP → Verify → Submit

**Expected:** Yellow banner — `"Your submission is under review"` with a reference number

---

### Test 5 — Check Review Queue

1. Go to `http://localhost:5173`
2. Login with `admin` / `admin123`
3. Click **Review Queue**
4. Find the case from Test 4 → click it to expand
5. See Layer 1, Layer 2, Layer 3 signals
6. Click **Approve** or **Reject**

---

### Test 6 — Velocity Limit (should AUTO-REJECT after 3 attempts)

1. Submit 3 different new identities quickly on the same device
2. On the 4th attempt, submit any new identity

**Expected:** Red banner — `"Device velocity limit exceeded"`

**To reset:** Admin Dashboard → **Thresholds** tab → **Reset Velocity Counters**

---

### Test 7 — Incognito Mode (Device Fingerprint Persists)

1. Note the **Composite Device ID** shown in the extension side panel
2. Open a new **Incognito window** in Chrome
3. Open `test-form/index.html` in the incognito window
4. Check the Device ID in the extension panel

**Expected:** Same Device ID as the normal window — fingerprint survives incognito

---

### Test 8 — Application Status Check

1. Take the reference number from Test 4 (shown in the yellow banner)
2. Open `test-form/status.html`
3. Enter the reference number
4. Click **Check Status**

**Expected:** Shows current status — `pending`, `approved`, or `rejected`

---

## 10. Default Credentials

| Component | Username | Password |
|---|---|---|
| Admin Dashboard | `admin` | `admin123` |
| Extension API Key | — | `dev-key-change-in-production` |
| MongoDB | — | None (local, no auth) |

---

## 11. Troubleshooting

### Backend won't start

```
ModuleNotFoundError: No module named 'fastapi'
```
**Fix:** Make sure the virtual environment is activated:
```bash
source venv/bin/activate   # macOS/Linux
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

---

### Backend starts but FAISS model download is slow

The `all-MiniLM-L6-v2` model (~90MB) is downloaded on first run from HuggingFace. This is a one-time download. Wait for it to complete — subsequent starts are instant.

---

### Extension not detecting the form

- Make sure the backend is running on port 8000
- Make sure the API key in the extension popup matches the `API_KEY` in `.env`
- Check that Developer Mode is ON in `chrome://extensions`
- Try reloading the extension — click the refresh icon on the extension card

---

### Dashboard shows CORS error / won't load

- Make sure the backend is running before opening the dashboard
- The dashboard must be on `localhost` (any port) — it will not work from a different hostname
- Try hard-refreshing: `Ctrl + Shift + R`

---

### MongoDB connection failed

```
MongoDB offline. Falling back to IN-MEMORY storage.
```
This is **not an error** — the system works fully in memory. Data will be lost on server restart but all fraud detection features work normally. To use MongoDB, install and start it:

```bash
brew install mongodb-community   # macOS
brew services start mongodb-community
```

---

### OTP not appearing

The OTP is shown directly in the backend terminal output (simulated SMS). Look for:

```
INFO: OTP for 9876543210: 482913
```

---

### Admin password reset

To change the admin password, generate a new bcrypt hash and update `.env`:

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yournewpassword', bcrypt.gensalt()).decode())"
```

Paste the output as `ADMIN_PASSWORD_HASH` in `.env` and restart the backend.

---

## Quick Start Summary

```bash
# Terminal 1 — Backend
cd backend
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Dashboard
cd admin-dashboard
npm install
npm run dev

# Chrome
# 1. Load extension from chrome://extensions → Load unpacked → select extension/
# 2. Set API key in extension popup: dev-key-change-in-production
# 3. Open test-form/index.html in Chrome
# 4. Open http://localhost:5173 for admin dashboard
```

---

*FraudGuard AI — Vishwakarma Institute of Technology, Pune*
