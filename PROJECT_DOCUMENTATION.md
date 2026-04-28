# FraudGuard AI — Complete Project Documentation

**Version:** 1.0  
**Platform:** Multi-domain (Edtech, Job Portals, E-Commerce, Insurance)  
**Stack:** FastAPI · MongoDB · FAISS · SentenceTransformer · React · Chrome Extension

---

## Table of Contents

1. [What Is This Project?](#1-what-is-this-project)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Directory Structure](#3-directory-structure)
4. [How the System Works — End-to-End Flow](#4-how-the-system-works--end-to-end-flow)
5. [The 4-Layer Fraud Detection Engine](#5-the-4-layer-fraud-detection-engine)
6. [Auto-Decision Engine](#6-auto-decision-engine)
7. [OTP Phone Verification](#7-otp-phone-verification)
8. [Device Fingerprinting](#8-device-fingerprinting)
9. [API Reference](#9-api-reference)
10. [Database Schema](#10-database-schema)
11. [Admin Dashboard](#11-admin-dashboard)
12. [Test Form (Demo)](#12-test-form-demo)
13. [Chrome Extension](#13-chrome-extension)
14. [Configuration & Environment Variables](#14-configuration--environment-variables)
15. [Running the Project](#15-running-the-project)
16. [End-to-End Demo Walkthrough](#16-end-to-end-demo-walkthrough)
17. [Security Design](#17-security-design)
18. [Feature Traceability Matrix](#18-feature-traceability-matrix)

---

## 1. What Is This Project?

FraudGuard AI is a **real-time returning-user fraud detection system**. Its core job is to detect when a person who has already received a benefit (exam slot, job offer, insurance payout, first-purchase discount) tries to register again under a new identity to claim that benefit a second time.

### The Problem It Solves

On government portals, edtech platforms, job sites, and e-commerce stores, fraudsters routinely:

- Create new accounts with slightly different names or emails to claim a benefit twice
- Use a different phone number but keep the same name and device
- Let a family member register with identical device and typing patterns
- Create bot accounts to mass-register for limited slots

Traditional duplicate detection (exact name/email match) fails because fraudsters make small changes. FraudGuard AI uses **semantic similarity, behavioral biometrics, device fingerprinting, and benefit-claim tracking** together to catch these cases.

### What Makes It Different

| Traditional System | FraudGuard AI |
|---|---|
| Exact string match only | Semantic similarity (83% match still flagged) |
| Checks current submission only | Compares against full history |
| Manual review for all suspicious cases | Auto-approves clear cases, escalates only ambiguous ones |
| No behavioral signal | Typing speed + paste events analyzed |
| Single platform | Works across Edtech, Jobs, E-Commerce, Insurance |
| No device tracking | Device fingerprint ties submissions across sessions |

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER'S BROWSER                               │
│                                                                     │
│   ┌──────────────────┐          ┌──────────────────────────────┐   │
│   │  Government /    │          │   Chrome Extension           │   │
│   │  Platform Form   │ ◄──────► │   (content.js + background)  │   │
│   │  (HTML page)     │          │   - Device fingerprint        │   │
│   └──────────────────┘          │   - Field monitoring         │   │
│                                 │   - Submit interception       │   │
│   ┌──────────────────┐          └──────────┬───────────────────┘   │
│   │   Test Form      │                     │                       │
│   │  (index.html)    ├─────────────────────┘                       │
│   │  4 platforms     │   X-API-Key Auth                            │
│   └──────────────────┘                                              │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │ HTTPS
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         FASTAPI BACKEND                             │
│                        (localhost:8000)                             │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ /analyze │  │ /submit  │  │ /otp/*   │  │ /admin/* (JWT)   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘   │
│       │              │              │                 │             │
│       └──────────────┴──────────────┘                │             │
│                       │                              │             │
│              ┌─────────▼──────────┐                  │             │
│              │   ML Engine        │                  │             │
│              │  (ml_service.py)   │                  │             │
│              │                   │                  │             │
│              │  Layer 1: FAISS   │                  │             │
│              │  Layer 2: Approved │                  │             │
│              │  Layer 3: Behavior │                  │             │
│              │  Layer 4: Claims   │                  │             │
│              └─────────┬──────────┘                  │             │
│                        │                             │             │
│              ┌─────────▼──────────┐                  │             │
│              │  Auto-Decision     │                  │             │
│              │  (auto_decision.py)│                  │             │
│              │                   │                  │             │
│              │  Rules → LLM →    │                  │             │
│              │  Human Queue       │                  │             │
│              └─────────┬──────────┘                  │             │
│                        │                             │             │
└────────────────────────┼─────────────────────────────┼─────────────┘
                         │                             │
          ┌──────────────┼─────────────────────┐       │
          │              ▼                     │       │
          │    ┌──────────────────────┐        │       │
          │    │      MongoDB         │        │       │
          │    │  - identities        │        │       │
          │    │  - benefit_claims    │        │       │
          │    │  - alerts            │        │       │
          │    │  - review_queue      │        │       │
          │    │  - audit_logs        │        │       │
          │    │  - phone_hashes      │        │       │
          │    └──────────────────────┘        │       │
          │                                   │       │
          │    ┌──────────────────────┐        │       │
          │    │   Disk Persistence   │        │       │
          │    │  - FAISS .bin files  │        │       │
          │    │  - fingerprints.json │        │       │
          │    │  - behavior.json     │        │       │
          │    │  - phone_hashes.json │        │       │
          │    └──────────────────────┘        │       │
          └────────────────────────────────────┘       │
                                                       │
                              ┌────────────────────────┘
                              ▼
          ┌──────────────────────────────────────┐
          │         REACT ADMIN DASHBOARD        │
          │           (localhost:5173)            │
          │                                      │
          │  - Live Monitor (auto-refresh 3s)    │
          │  - Review Queue (approve/reject)     │
          │  - Threshold Settings                │
          │  - Audit Log                         │
          └──────────────────────────────────────┘
```

### Component Summary

| Component | Technology | Purpose |
|---|---|---|
| Backend API | FastAPI (Python) | Central intelligence layer |
| ML Engine | FAISS + SentenceTransformer | Semantic similarity search |
| Database | MongoDB (+ in-memory fallback) | Persistent storage |
| Chrome Extension | Manifest V3 (JS) | Browser-side signal capture |
| Test Form | Vanilla HTML/JS | Multi-platform demo |
| Admin Dashboard | React + Tailwind CSS | Officer review interface |
| OTP Service | Pure Python (in-memory) | Phone number verification |
| LLM Fallback | Gemini Flash → Claude Haiku | Ambiguous case reasoning |

---

## 3. Directory Structure

```
SE---Fraud-Detection 2/
│
├── backend/                          ← FastAPI server
│   ├── app/
│   │   ├── main.py                   ← App entry point, startup hooks
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── analyze.py        ← /api/analyze and /api/submit
│   │   │       ├── admin.py          ← All /api/admin/* routes
│   │   │       ├── auth_routes.py    ← /api/auth/login
│   │   │       ├── otp.py            ← /api/otp/send and /api/otp/verify
│   │   │       └── status.py         ← /api/status/{case_id} (public)
│   │   ├── core/
│   │   │   ├── config.py             ← All env variables + defaults
│   │   │   ├── db.py                 ← Database manager (MongoDB + fallback)
│   │   │   ├── security.py           ← Bcrypt + JWT generation
│   │   │   └── auth.py               ← API key + JWT verification middlewares
│   │   ├── models/
│   │   │   └── schemas.py            ← Pydantic request/response models
│   │   └── services/
│   │       ├── ml_service.py         ← Core ML fraud engine (4 layers)
│   │       ├── otp_service.py        ← OTP + token lifecycle
│   │       └── auto_decision.py      ← Decision rules + LLM integration
│   ├── indices/                      ← FAISS vector index files (binary)
│   │   ├── FullName.bin
│   │   ├── EmailLocalPart.bin
│   │   ├── ApprovedFullName.bin
│   │   └── ApprovedEmailLocalPart.bin
│   ├── identity_fingerprints.json    ← Layer 1 fingerprint store
│   ├── behavioral_profiles.json      ← Layer 3 behavioral profiles
│   ├── phone_hashes.json             ← Phone hash registry
│   ├── requirements.txt
│   └── .env                          ← Secret configuration (not committed)
│
├── extension/                        ← Chrome extension
│   ├── manifest.json
│   └── src/
│       ├── background.js             ← Service worker (API calls)
│       └── content.js                ← Page injection (monitoring + fingerprint)
│
├── test-form/                        ← Demo UI
│   ├── index.html                    ← Multi-platform test form
│   └── status.html                   ← Applicant status checker
│
├── admin-dashboard/                  ← React dashboard
│   └── src/
│       └── App.jsx                   ← Entire SPA (login + 4 tabs)
│
└── PROJECT_DOCUMENTATION.md          ← This file
```

---

## 4. How the System Works — End-to-End Flow

### 4.1 Real-Time Monitoring Flow (While Typing)

```
User types in a form field
         │
         ▼
Chrome Extension intercepts keyup event
         │
         ▼  (1.2 second debounce)
POST /api/analyze
{
  fieldName: "FullName",
  value: "Pulkit Shah",
  formContext: "EduVerify-Exam",
  behavior: { cps: 4.2, keystrokes: 11, ... }
}
         │
         ▼
Backend checks value against FAISS index
  ├─ If FullName → compare against FullName.bin
  ├─ If EmailAddress → compare email local-part against EmailLocalPart.bin
  ├─ If PhoneNumber → check phone hash against registry
  └─ If GovID → check GovID hash against registry
         │
         ▼
Returns: { riskLevel: "LOW|MEDIUM|HIGH", similarityScore: 0-100 }
         │
         ▼
Extension shows red/orange border + tooltip on field
```

### 4.2 Final Submission Flow

```
User clicks "Submit" / "Register"
         │
         ▼
Chrome Extension intercepts form submit
  (or test-form sends directly to /api/submit)
         │
         ▼
OTP Gate Check ──── No phone / no token ──► REJECT immediately
         │
         │ (phone + valid OTP token present)
         ▼
POST /api/submit  {all identity fields + deviceId + otpToken}
         │
         ▼
╔══════════════════════════════════════════════════════════════╗
║                   ML ENGINE EVALUATION                       ║
║                                                              ║
║  Step 1: Build composite fingerprint                         ║
║     SHA256(phone_normalized | email_local | device_id)       ║
║                                                              ║
║  Step 2: Layer 1 — Exact fingerprint match?                  ║
║     → YES: REJECT (returning user, same device+phone+email)  ║
║                                                              ║
║  Step 3: Velocity check                                      ║
║     → Exceeded: REJECT (rate limit)                          ║
║                                                              ║
║  Step 4: Phone hash check                                    ║
║     → Matches: REJECT (phone already registered)             ║
║                                                              ║
║  Step 5: Layer 2 — Approved-user FAISS similarity            ║
║     → Compare name + email against approved-only index       ║
║     → Scores: approved_name_sim%, approved_email_sim%        ║
║                                                              ║
║  Step 6: General registry FAISS similarity                   ║
║     → Compare name + email against all-submissions index     ║
║     → Scores: name_sim%, email_sim%                          ║
║                                                              ║
║  Step 7: Layer 3 — Behavioral comparison                     ║
║     → Does CPS match prior sessions for this fingerprint?    ║
║                                                              ║
║  Step 8: Layer 4 — Benefit claim check                       ║
║     → Has this fingerprint claimed benefit on this platform? ║
╚══════════════════════════════════════════════════════════════╝
         │
         ▼
Auto-Decision Engine (11 hard rules, in order)
         │
    ┌────┴────┐
    │         │
  Match     No match
    │         │
    ▼         ▼
Decision    LLM (Gemini → Claude → Heuristic)
    │         │
    └────┬────┘
         │
    ┌────┴──────────┐
    │               │
  APPROVE/REJECT  ESCALATE
    │               │
    ▼               ▼
Commit to       Queue for
all 4 layers    human officer
+ record claim
```

---

## 5. The 4-Layer Fraud Detection Engine

The engine is implemented in `backend/app/services/ml_service.py`. All 4 layers run on every final submission. Layers are checked in order — a positive hit on any layer can immediately determine the result.

---

### Layer 1: Composite Identity Fingerprint

**What it does:** Creates a cryptographic fingerprint that uniquely identifies the combination of phone number, email address, and device. If the same combination was seen before (and approved), it's a returning user.

**How the fingerprint is built:**

```
Input:
  phone     = "9823456710"      (as submitted)
  email     = "pulkit.shah@gmail.com"
  device_id = "222d28a5"        (DJB2 hash from browser)

Processing:
  phone_norm  = normalize("9823456710")      → "9823456710"
  email_local = extract_local("pulkit.shah@gmail.com") → "pulkit shah"
  device_norm = normalize("222d28a5")         → "222d28a5"

Canonical string:
  "9823456710|pulkit shah|222d28a5"

Fingerprint:
  SHA256("9823456710|pulkit shah|222d28a5")  → 64-char hex
```

**Normalization rules:**
- Phone: strip non-digits, keep last 10 digits, uppercase
- Email local-part: strip domain, replace `.`, `_`, `+`, `-` with space, lowercase
- Device ID: empty/null/unknown/undefined → collapsed to `""` (same sentinel)

**Why normalization matters:** A user who submits `+91-9823456710` and then `9823456710` should produce the same fingerprint. Similarly, `pulkit.shah` and `pulkit_shah` are the same email user.

**Storage:**
```
identity_fingerprints = {
  "sha256hash1": "approved-case-uuid-1",
  "sha256hash2": "approved-case-uuid-2",
  ...
}
```
Stored in `identity_fingerprints.json` (disk) and synced to MongoDB `identities` collection.

**Decision:** Match → **REJECT** instantly, no further checks needed.

---

### Layer 2: Approved-User Semantic Similarity (FAISS)

**What it does:** Even if the fingerprint doesn't match (because the user changed their phone or used a different device), their name and email might still be semantically identical to an already-approved account. This layer catches that.

**Two separate FAISS indices:**

```
General Registry Index          Approved-User-Only Index
(all submissions including       (only approved submissions)
 rejected ones)
─────────────────────────       ─────────────────────────
FullName.bin                    ApprovedFullName.bin
EmailLocalPart.bin              ApprovedEmailLocalPart.bin
```

The approved-only index is the critical one. A hit against the general index alone might mean the person submitted before and got rejected — that's less meaningful. A hit against the approved-only index means someone with this name+email was already accepted and received a benefit.

**How FAISS works:**

```
Text → SentenceTransformer("all-MiniLM-L6-v2") → 384-dimensional vector
                                                          │
                                                          ▼
                                               FAISS FlatIP Index
                                               (inner product similarity
                                                after L2 normalization)
                                                          │
                                                          ▼
                                               Similarity Score: 0–100%
```

The model (`all-MiniLM-L6-v2`) understands that:
- "Pulkit Shah" and "P. Shah" are similar (abbreviated)
- "pulkit.shah" and "p.shah" are similar email locals
- "John Smith" and "Jon Smyth" are moderately similar (common error patterns)

**Score interpretation:**

```
Approved Name Sim    Approved Email Sim    Interpretation
> 95%                > 95%                Definitive returning user → REJECT
> 95%                60-95%               Likely same person → LLM decides
60-95%               > 95%                Likely same person → LLM decides
60-95%               60-95%               Ambiguous → LLM decides
< 60%                < 60%                Not a match (approved registry) → continue
```

---

### Layer 3: Behavioral Signature

**What it does:** Every person has a unique typing pattern. If someone approved at 4.2 CPS (characters per second) tries to re-register at exactly 4.2 CPS under a different name, that's suspicious. This layer compares behavioral signals against stored profiles.

**Behavioral signals tracked:**
- `cps` — characters per second (typing speed)
- `pastesCount` — number of paste events (Ctrl+V)
- `keystrokesCount` — total keystrokes
- `deletionsCount` — backspace/delete events

**Profile structure (stored per fingerprint):**
```json
{
  "cps_samples": [3.2, 4.1, 4.5, 3.8, 4.2],
  "avg_cps": 3.96,
  "paste_count": 1,
  "sessions": 5
}
```

**Comparison algorithm:**
```
behavioral_score = 1.0

CPS comparison:
  diff = abs(new_cps - profile.avg_cps)
  cps_score = max(0, 1.0 - diff / 10.0)

Paste mismatch penalty:
  prior_paste_ratio = profile.paste_count / profile.sessions
  if new pastes > 0 but prior_paste_ratio < 0.2:
    apply -0.2 penalty (this person didn't paste before)

Final behavioral_score = cps_score with paste penalty applied
```

**Score interpretation:**
- `> 0.7` — Very similar behavior (same person likely)
- `0.4–0.7` — Moderate similarity (same device, different day)
- `< 0.4` — Very different behavior (either new person or deliberate change)

**When it matters:** Behavioral score alone doesn't block anyone. It's fed as a signal to the LLM and shown to officers in the dashboard. If someone is already in the HIGH risk category and behavioral score is very high, it adds weight to a REJECT decision.

---

### Layer 4: Benefit Claim History

**What it does:** Even if all the above layers pass (completely different name, email, phone, device), if this identity's fingerprint has already claimed the benefit, they're blocked.

**Platform-to-benefit mapping:**

```
Form Context String                →  benefit_type        sector
─────────────────────────────────────────────────────────────────
"edtech", "course", "exam"         →  "exam_slot"         "edtech"
"job", "employ", "recruit"         →  "job_application"   "jobs"
"insurance", "claim"               →  "insurance_claim"   "insurance"
"ecommerce", "shop", "order"       →  "first_purchase"    "ecommerce"
"gov", "scheme", "subsidy"         →  "gov_benefit"       "government"
(anything else)                    →  platform-name       platform-name
```

**Check logic:**
```python
existing = await db.check_benefit_claimed(
    identity_fingerprint,
    benefit_type,     # "exam_slot"
    sector            # "edtech"
)
if existing["already_claimed"]:
    → REJECT: "Benefit already claimed by this identity."
```

**Recording:** On every APPROVE (auto or officer), a benefit claim record is written to MongoDB `benefit_claims`:
```json
{
  "id": "uuid",
  "user_id": "case-uuid",
  "identity_fingerprint": "sha256-hash",
  "benefit_type": "exam_slot",
  "sector": "edtech",
  "claimed_at": 1714234567.89
}
```

---

### Layer Summary Diagram

```
SUBMISSION ARRIVES
        │
        ▼
┌───────────────────────────────────────┐
│  LAYER 1: Composite Fingerprint       │
│  SHA256(phone + email_local + device) │
│  Exact match against stored hashes   │
└───────────┬───────────────────────────┘
            │ No match
            ▼
┌───────────────────────────────────────┐
│  Phone Hash Check                     │
│  SHA256(normalized_phone)             │
│  Exact match against phone registry   │
└───────────┬───────────────────────────┘
            │ No match
            ▼
┌───────────────────────────────────────┐
│  LAYER 2: Approved-User FAISS         │
│  Semantic similarity of name + email  │
│  Against approved-only index          │
│  approved_name_sim%, email_sim%       │
└───────────┬───────────────────────────┘
            │ < 95% (no clear match)
            ▼
┌───────────────────────────────────────┐
│  General Registry FAISS               │
│  Semantic similarity of name + email  │
│  Against all-submissions index        │
│  name_sim%, email_sim%               │
└───────────┬───────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│  LAYER 3: Behavioral Comparison       │
│  Compare CPS + paste events to        │
│  stored profile for this fingerprint  │
│  behavioral_score: 0.0 – 1.0          │
└───────────┬───────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│  LAYER 4: Benefit Claim History       │
│  Check if fingerprint already claimed │
│  benefit on this platform/sector      │
└───────────┬───────────────────────────┘
            │
            ▼
    Auto-Decision Engine
  (all signals combined →
   11 rules → LLM → human)
```

---

## 6. Auto-Decision Engine

**File:** `backend/app/services/auto_decision.py`

The engine receives all signals from the 4 layers and applies rules in strict priority order. The first matching rule wins. If no rule matches, the case goes to the LLM.

### 6.1 Rule Priority Table

| Priority | Condition | Decision | Reason Shown |
|---|---|---|---|
| 1 | `velocity_exceeded = True` | REJECT | "VELOCITY LIMIT: N submissions from this device in last X minutes (limit: Y)" |
| 2 | `cps > 60` | REJECT | "Bot detected: N CPS is physically impossible for a human" |
| 3 | `phone_match = True` | REJECT | "Phone number already registered to another account" |
| 4 | `fingerprint_match = True` | REJECT | "Returning user: exact identity fingerprint already registered" |
| 5 | `approved_name_sim > 95% AND approved_email_sim > 95%` | REJECT | "Returning user: name X% + email Y% match approved registry" |
| 6 | `approved_email_sim > 92% OR email_sim > 92%` | REJECT | "Email local part already registered (X% match)" |
| 7 | `all sims < 30%` (name, email, approved name, approved email) | APPROVE | "All similarity signals below 30%. Clearly a new identity" |
| 8 | `risk = LOW` (passed all above checks) | APPROVE | "Identity is unique. No significant similarity detected" |
| 9 | `name_sim > 60% AND email_sim < 30% AND approved_name_sim < 60%` | APPROVE | "Similar name but email clearly different. Treated as different person" |
| 10 | `risk != HIGH AND approved sims < 60% AND no fingerprint AND no benefit` | APPROVE | "General registry similarity only, no approved-user match" |
| 11 | `benefit_claimed = True` | REJECT | "Benefit already claimed by this identity. Re-application blocked" |
| 12 | (none of the above matched) | → LLM | — |

> **Why Rule 10 exists:** The general registry includes rejected submissions too. A MEDIUM similarity against rejected submissions should not trigger escalation — that would produce false positives for new users with common names. Only approved-user similarity is meaningful for returning-user detection.

### 6.2 LLM Decision Flow

When rules don't produce a clear answer, the LLM receives all signals and reasons about the case:

```
Gemini Flash 2.0 (primary, fast, cheap)
       │
       │ (if unavailable or fails)
       ▼
Claude Haiku 4.5 (fallback)
       │
       │ (if unavailable or fails)
       ▼
Heuristic Fallback
  - max(all sims) > 80% → ESCALATE
  - otherwise → APPROVE
```

**What the LLM receives:**

```
Signals sent to LLM:
  - Exact fingerprint match:            false
  - Name similarity (general):          72.3%
  - Email similarity (general):         68.1%
  - Name similarity (approved users):   83.6%
  - Email similarity (approved users):  83.6%
  - Behavioral typing score:            0.71
  - Typing speed:                       4.2 CPS
  - Paste events:                       0
  - ML overall risk:                    MEDIUM
  - Benefit previously claimed:         false
```

**LLM output (JSON only):**
```json
{
  "decision": "ESCALATE",
  "reason": "Approved registry shows 83.6% name and email match — abbreviated name suggests same person."
}
```

**Possible decisions:**
- `APPROVE` → auto-approved, committed to registry
- `REJECT` → auto-rejected, not committed
- `ESCALATE` → sent to human officer queue

### 6.3 Human Officer Review

When LLM says ESCALATE, a case record is created in the `review_queue` collection. Officers see it on the Admin Dashboard Review Queue tab.

Officers can:
1. **View all 4 layer signals** in the expanded case panel
2. **Add a note** ("Abbreviated name — verified manually")
3. **Approve** → triggers `add_identity()` across all 4 layers + benefit claim record
4. **Reject** → identity NOT added to any registry

---

## 7. OTP Phone Verification

**File:** `backend/app/services/otp_service.py`

Every form submission that includes a phone number requires OTP verification before the fraud checks even run. This proves the user owns the phone number they're claiming.

### 7.1 Complete OTP Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                     OTP LIFECYCLE                               │
│                                                                 │
│  1. User enters phone: "9823456710"                             │
│              │                                                  │
│              ▼                                                  │
│  2. User clicks "Send OTP"                                      │
│     → POST /api/otp/send { phone: "9823456710" }               │
│              │                                                  │
│              ▼                                                  │
│  3. Backend:                                                    │
│     phone_hash = SHA256("9823456710")                           │
│     otp = random 6-digit code ("847291")                        │
│     Store: _pending[phone_hash] = {                             │
│       otp: "847291",                                            │
│       expires_at: now + 5 minutes,                              │
│       attempts: 0                                               │
│     }                                                           │
│     Response: { otp: "847291" }  ← demo mode only              │
│              │                                                  │
│              ▼                                                  │
│  4. User sees OTP in demo hint, enters code, clicks "Verify"   │
│     → POST /api/otp/verify { phone: "9823456710", code: "847291" }│
│              │                                                  │
│              ▼                                                  │
│  5. Backend validates:                                          │
│     ✓ Not expired (< 5 min)                                     │
│     ✓ Attempts ≤ 3                                              │
│     ✓ Code matches                                              │
│              │                                                  │
│              ▼                                                  │
│  6. Generates single-use verification token:                    │
│     token = UUID4 ("a1b2c3d4-...")                              │
│     _tokens[token] = {                                          │
│       phone_hash: SHA256("9823456710"),                         │
│       expires_at: now + 10 minutes                              │
│     }                                                           │
│     Response: { token: "a1b2c3d4-..." }                         │
│              │                                                  │
│              ▼                                                  │
│  7. UI stores token, enables submit button                      │
│              │                                                  │
│              ▼                                                  │
│  8. User clicks "Register" → POST /api/submit { otpToken: ... }│
│              │                                                  │
│              ▼                                                  │
│  9. Backend OTP gate:                                           │
│     a. Token exists? ✓                                          │
│     b. Token not expired? ✓                                     │
│     c. SHA256(submitted_phone) == token.phone_hash? ✓          │
│        (prevents using token for a different number)           │
│     d. Consume token (delete it — single use)                   │
│              │                                                  │
│              ▼                                                  │
│  10. Proceed to 4-layer fraud detection                         │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Security Properties

| Property | Value |
|---|---|
| OTP length | 6 digits |
| OTP validity | 5 minutes |
| Max attempts per OTP | 3 wrong codes → OTP invalidated |
| Token validity | 10 minutes |
| Token reuse | Single-use (consumed on submit) |
| Phone-token binding | Cross-check prevents token reuse for different phone |
| After submit | `resetOTPUI()` called → user can re-verify for next attempt |

### 7.3 Production Note

In demo mode, the OTP is returned in the API response for testing convenience. In production, this line should be removed and replaced with an SMS provider call (Twilio, MSG91, AWS SNS) before the response is sent.

---

## 8. Device Fingerprinting

**Files:** `extension/src/content.js`, `test-form/index.html`

Device fingerprinting creates a stable, hardware-based identifier for a browser/device that does not change between sessions, incognito mode, or page refreshes — without storing cookies.

### 8.1 Signals Collected

| Signal | Source | Example |
|---|---|---|
| User Agent | `navigator.userAgent` | "Mozilla/5.0 (Macintosh; Intel Mac OS X...)" |
| Language | `navigator.language` | "en-US" |
| Screen Resolution | `screen.width × screen.height` | "1800×1169" |
| Color Depth | `screen.colorDepth` | "30bit" |
| Timezone | `Intl.DateTimeFormat().resolvedOptions().timeZone` | "Asia/Calcutta" |
| CPU Cores | `navigator.hardwareConcurrency` | "12" |
| Touch Points | `navigator.maxTouchPoints` | "0" |
| Canvas Hash | Render text to canvas, hash data URI | "AAEJREFUAwBmH..." |

### 8.2 Canvas Fingerprinting

Canvas rendering varies by GPU driver and font rendering engine — the same text drawn on a `<canvas>` element produces slightly different pixel values on different hardware:

```javascript
const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');
ctx.textBaseline = 'top';
ctx.font = '14px Arial';
ctx.fillText('FraudGuard🛡', 2, 2);
const dataURL = canvas.toDataURL();
const canvasHash = dataURL.slice(-32);   // Last 32 chars = hardware-unique
```

If the browser blocks canvas (privacy extensions, Firefox Resist Fingerprinting), the value falls back to `"canvas-blocked"`.

### 8.3 DJB2 Hashing

All 8 signals are concatenated and hashed using DJB2:

```javascript
function djb2(str) {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
        hash = ((hash << 5) + hash) ^ str.charCodeAt(i);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

const deviceId = djb2([
    navigator.userAgent,
    navigator.language,
    screen.width + 'x' + screen.height,
    screen.colorDepth,
    timezone,
    navigator.hardwareConcurrency,
    navigator.maxTouchPoints,
    canvasHash
].join('|'));
// Result: "222d28a5" (8-character hex string)
```

### 8.4 Why Incognito Doesn't Help Fraudsters

```
Normal Mode:       Device ID = "222d28a5"
Incognito Mode:    Device ID = "222d28a5"  ← SAME! Hardware doesn't change.
Different Browser: Device ID = "8f3a1b9c"  ← Different canvas rendering
VPN (same PC):     Device ID = "222d28a5"  ← VPN only changes IP, not hardware
```

Incognito clears cookies and history, but hardware signals (GPU, screen, CPU) don't change. A fraudster on the same computer gets the same fingerprint every time.

### 8.5 Composite Fingerprint vs Device ID

```
Device ID (DJB2 hash)    →  Identifies the browser/device
                                    +
Normalized Phone         →  Identifies the person's number
                                    +
Email Local-Part         →  Identifies the person's email handle
                                    │
                                    ▼
             SHA256(phone | email_local | device_id)
                         = Composite Fingerprint

This fingerprint identifies "this specific person on this specific device"
```

---

## 9. API Reference

All routes are prefixed with the base URL `http://localhost:8000`.

### 9.1 Authentication Schemes

```
Extension routes:   X-API-Key: <API_KEY>   (set in .env)
Dashboard routes:   Authorization: Bearer <JWT>
Public routes:      No authentication required
OTP routes:         X-API-Key: <API_KEY>
```

---

### 9.2 POST /api/analyze — Real-Time Field Monitoring

**Auth:** X-API-Key  
**Rate Limit:** 60 requests/minute per IP

**Request:**
```json
{
  "formContext": "EduVerify-Exam-Registration",
  "fieldName": "FullName",
  "value": "Pulkit Shah",
  "behavior": {
    "keystrokesCount": 11,
    "deletionsCount": 0,
    "pastesCount": 0,
    "timeToCompleteMs": 2800.0,
    "cps": 3.9
  }
}
```

**Response:**
```json
{
  "riskLevel": "LOW",
  "similarityScore": 0.0,
  "message": "No match found.",
  "matchedValue": null
}
```

**What happens internally:**
- `FullName` → encode with SentenceTransformer → query FAISS `FullName.bin`
- `EmailAddress` → extract local-part → query `EmailLocalPart.bin`
- `PhoneNumber` → normalize → SHA256 → check `phone_hashes` set
- `GovID` → normalize → SHA256 → check gov_id registry
- Returns highest similarity score found

---

### 9.3 POST /api/submit — Final Identity Submission

**Auth:** X-API-Key  
**Rate Limit:** 10 requests/minute per IP

**Request:**
```json
{
  "formContext": "EduVerify-Exam-Registration",
  "fieldName": "FinalSubmit",
  "value": "Pulkit Shah",
  "identityDetails": {
    "FullName": "Pulkit Shah",
    "EmailAddress": "pulkit.shah@gmail.com",
    "PhoneNumber": "9823456710",
    "GovID": "",
    "device_id": "222d28a5"
  },
  "deviceId": "222d28a5",
  "otpToken": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "behavior": {
    "keystrokesCount": 52,
    "deletionsCount": 3,
    "pastesCount": 0,
    "timeToCompleteMs": 13400.0,
    "cps": 3.9
  }
}
```

**Response — Approved:**
```json
{
  "status": "success",
  "message": "Registration successful. Your exam hall ticket will be sent to your email within 24 hours."
}
```

**Response — Rejected:**
```json
{
  "status": "rejected",
  "message": "RETURNING USER: Exact identity fingerprint already registered.",
  "riskLevel": "HIGH"
}
```

**Response — Escalated:**
```json
{
  "status": "pending_review",
  "message": "Your submission requires additional review. You will be contacted shortly.",
  "riskLevel": "MEDIUM",
  "caseId": "case-uuid-here"
}
```

---

### 9.4 POST /api/otp/send — Send OTP

**Auth:** X-API-Key

**Request:**
```json
{ "phone": "9823456710" }
```

**Response:**
```json
{
  "success": true,
  "otp": "847291",
  "message": "OTP sent to ****3456710 (demo mode — OTP included in response)"
}
```

---

### 9.5 POST /api/otp/verify — Verify OTP

**Auth:** X-API-Key

**Request:**
```json
{
  "phone": "9823456710",
  "code": "847291"
}
```

**Response — Success:**
```json
{
  "success": true,
  "token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Response — Failure:**
```json
{
  "success": false,
  "error": "Incorrect OTP. 2 attempt(s) left."
}
```

---

### 9.6 GET /api/admin/alerts — Alert Feed

**Auth:** JWT  
**Parameters:** `limit=50`, `risk_level=HIGH|MEDIUM|LOW`, `search=string`

**Response:** Array of alert objects with all 4-layer signal fields.

---

### 9.7 GET /api/admin/alerts/export — CSV Export

**Auth:** JWT  
**Returns:** `fraud_alerts.csv` file download

**Columns:** id, fieldName, value, riskLevel, similarityScore, timestamp, status, fingerprintMatch, approvedNameSim, approvedEmailSim, behavioralScore, benefitAlreadyClaimed

---

### 9.8 GET /api/admin/review-queue — Officer Queue

**Auth:** JWT  
**Parameters:** `status=pending|approved|rejected`

---

### 9.9 POST /api/admin/review-queue/{case_id}/approve

**Auth:** JWT  
**Request:** `{ "officer_note": "Abbreviated name — verified manually" }`

**What happens:**
1. `ml_engine.add_identity()` → Layers 1, 2, 3 committed
2. `db.insert_identity()` → fingerprint stored in MongoDB
3. `db.record_benefit_claim()` → Layer 4 claim recorded
4. `db.update_review_case()` → status set to "approved"
5. `db.insert_audit_log()` → immutable trail

---

### 9.10 POST /api/admin/review-queue/{case_id}/reject

**Auth:** JWT  
**Request:** `{ "officer_note": "Confirmed duplicate — different device, same person" }`

**What happens:**
1. `db.update_review_case()` → status set to "rejected"
2. `db.insert_audit_log()` → immutable trail
3. Identity NOT added to any registry

---

### 9.11 GET/PUT /api/admin/thresholds — Risk Thresholds

**GET Response:**
```json
{
  "high_risk_threshold": 85.0,
  "medium_risk_threshold": 60.0,
  "bot_cps_threshold": 35.0,
  "device_max_attempts": 3,
  "device_window_minutes": 60
}
```

**PUT Request:**
```json
{
  "high_risk_threshold": 90.0,
  "medium_risk_threshold": 65.0,
  "bot_cps_threshold": 40.0,
  "device_max_attempts": 5,
  "device_window_minutes": 30
}
```

**Validation:**
- `0 < medium < high ≤ 100`
- `bot_cps > 0`
- `device_max ≥ 1`
- `device_window ≥ 1`

Changes apply immediately to the running ML engine (no restart required).

---

### 9.12 POST /api/admin/velocity/reset — Clear Rate Limits

**Auth:** JWT  
**Purpose:** Clears all in-memory device submission counters (useful during demos and testing)

---

### 9.13 POST /api/admin/import — Bulk Identity Import

**Auth:** JWT  
**Request:**
```json
[
  { "FullName": "Aadhar Holder", "EmailAddress": "a@b.com", "PhoneNumber": "9999999999" },
  { "FullName": "Another Person", "EmailAddress": "c@d.com", "GovID": "XXXX1234" }
]
```

**Use case:** Migrate existing verified identity databases into FraudGuard's registry before going live.

---

### 9.14 GET /api/status/{case_id} — Applicant Status Check (Public)

**No auth required** (intentional — applicants need to check their own status)

**Response:**
```json
{
  "ref": "CCCA59C5",
  "status": "pending",
  "message": "Your application is under review by our compliance team.",
  "submitted_at": 1714234567.89
}
```

---

### 9.15 POST /api/auth/login

**Request:** `{ "username": "admin", "password": "admin123" }`  
**Response:** `{ "access_token": "JWT...", "token_type": "bearer" }`

---

## 10. Database Schema

### 10.1 MongoDB Collections

#### `identities` — Approved Identity Records

```
Field                  Type      Description
─────────────────────────────────────────────────────────────
id                     string    Case UUID (primary key)
name                   string    Full name (for display only)
timestamp              float     Unix epoch (seconds)
identity_fingerprint   string    SHA256 composite hash (Layer 1)
phone_hash             string    SHA256 of normalized phone
```

**Indices:** `identity_fingerprint` (unique), `phone_hash`

---

#### `benefit_claims` — Layer 4 Records

```
Field                  Type      Description
─────────────────────────────────────────────────────────────
id                     string    Claim UUID
user_id                string    Case UUID of the approved identity
identity_fingerprint   string    SHA256 composite hash
benefit_type           string    "exam_slot" | "job_application" | etc.
sector                 string    "edtech" | "jobs" | "insurance" | etc.
claimed_at             float     Unix epoch
```

**Indices:** `identity_fingerprint`, composite `(identity_fingerprint, benefit_type, sector)`

---

#### `phone_hashes` — Phone Number Registry

```
Field     Type      Description
──────────────────────────────────────────────────
hash      string    SHA256 of normalized phone number
```

**Index:** `hash` (unique)  
**Synced to:** `ml_engine.phone_hashes` set in memory on startup

---

#### `alerts` — Real-Time Monitoring Log

```
Field                  Type      Description
─────────────────────────────────────────────────────────────
id                     string    Alert UUID
fieldName              string    "FullName" | "EmailAddress" | etc.
value                  string    Masked value (PII protected)
formContext            string    Platform context string
riskLevel              string    "HIGH" | "MEDIUM" | "LOW"
similarityScore        float     0.0 – 100.0
timestamp              float     Unix epoch
status                 string    "auto_approved" | "auto_rejected" | "escalated_for_review"
explanation            string    Reason string (from ML/rules/LLM)
behavior               object    { cps, keystrokesCount, ... }
fingerprintMatch       bool      Layer 1 signal
approvedNameSim        float     Layer 2 name signal
approvedEmailSim       float     Layer 2 email signal
behavioralScore        float?    Layer 3 signal (null if no prior profile)
benefitAlreadyClaimed  bool      Layer 4 signal
```

**Index:** `timestamp` (descending, for recent-first queries)

---

#### `review_queue` — Human Officer Queue

All fields from `alerts`, plus:

```
Field                  Type      Description
─────────────────────────────────────────────────────────────
status                 string    "pending" | "approved" | "rejected"
identityDetails        object    { FullName, EmailAddress, PhoneNumber, device_id }
aiDecision             string    "APPROVE" | "REJECT" | "ESCALATE"
aiReason               string    LLM explanation text
officerNote            string    Officer comment (on decision)
fingerprint            string    SHA256 composite hash (for Layer 1 storage on approve)
clientIp               string    Submitter's IP address
```

---

#### `audit_logs` — Immutable Action Trail

```
Field        Type      Description
──────────────────────────────────────────────────────────────────
id           string    Log UUID
action       string    "approve" | "reject" | "update_thresholds" | "bulk_import" | "velocity_reset"
case_id      string?   Referenced case (if applicable)
officer      string    Username of officer who acted
note         string?   Officer comment (if applicable)
timestamp    float     Unix epoch
high         float?    New HIGH threshold (if action=update_thresholds)
medium       float?    New MEDIUM threshold (if action=update_thresholds)
bot_cps      float?    New bot CPS threshold
device_max   int?      New device max attempts
device_window_min int? New device window minutes
count        int?      Records imported (if action=bulk_import)
```

> **Note:** Audit logs are insert-only. There is no update or delete path.

---

### 10.2 Disk Persistence Files

These files persist ML state between server restarts:

| File | Contents | Format |
|---|---|---|
| `identity_fingerprints.json` | `{ sha256: case_id, ... }` | JSON object |
| `behavioral_profiles.json` | `{ fingerprint: { cps_samples, avg_cps, ... }, ... }` | JSON object |
| `phone_hashes.json` | `["hash1", "hash2", ...]` | JSON array |
| `indices/FullName.bin` | FAISS flat index | Binary |
| `indices/EmailLocalPart.bin` | FAISS flat index | Binary |
| `indices/ApprovedFullName.bin` | FAISS flat index (approved-only) | Binary |
| `indices/ApprovedEmailLocalPart.bin` | FAISS flat index (approved-only) | Binary |

---

### 10.3 In-Memory Fallback

When MongoDB is not available (not running, wrong URL), the system automatically falls back to Python lists/dicts in memory. All operations work identically — data is just lost on server restart. A warning is logged at startup.

```
Startup log (no MongoDB):
  WARNING: MongoDB unavailable — using in-memory storage.
  Data will not persist across server restarts.
```

---

## 11. Admin Dashboard

**File:** `admin-dashboard/src/App.jsx`  
**URL:** `http://localhost:5173` (Vite dev server)  
**Auth:** JWT (8-hour sessions)

### 11.1 Login Page

Standard username + password form. Authenticates against `/api/auth/login`. JWT stored in `localStorage["fg_token"]`. Username decoded from JWT payload for display.

Default credentials: `admin` / `admin123` ← **change in production**

---

### 11.2 Live Monitor Tab

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │TOTAL SCANNED│  │FLAGGED DETECTIONS│  │AVG RESPONSE TIME  │  │
│  │    247      │  │       31         │  │     142ms         │  │
│  └─────────────┘  └──────────────────┘  └───────────────────┘  │
│                                                                 │
│  [Search...]  [All Risk Levels ▼]  [Export CSV]  Updated 2s ago │
│                                                                 │
│  VALUE          FIELD      RISK     SIMILARITY   SIGNALS  TIME  │
│  ─────────────────────────────────────────────────────────────  │
│  pulkit.shah    Email      HIGH     ████ 91.2%   🔑 FP    12:04 │
│  Rahul Verma    FullName   MEDIUM   ██   63.5%   ~74%appr 12:03 │
│  test@test.com  Email      LOW      █    15.0%            12:01 │
└─────────────────────────────────────────────────────────────────┘
```

- **Auto-refresh:** Every 3 seconds
- **Filters:** Risk level dropdown + keyword search (searches name/email/value)
- **Staleness indicator:** Green → Orange → Red based on last-update age
- **Returning-user signal badges:** 🔑 FP (fingerprint), 🎁 CLAIMED, ~XX% appr. (approved sim), ⌨ XX% (behavioral)
- **Export:** Downloads CSV with all fields including 4-layer signals

---

### 11.3 Review Queue Tab

```
┌─────────────────────────────────────────────────────────────────┐
│  Compliance Review Queue              [Pending ▼]  [↻ Refresh]  │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ MEDIUM  REF: CCCA59C5  4/28/2026  🤖 AI Escalated    ▼    │ │
│  │ Chinmayi K (FinalSubmit)                                   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  [Click to expand ▼]                                            │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ MEDIUM  REF: CCCA59C5  4/28/2026  🤖 AI Escalated    ▲    │ │
│  │ Chinmayi K (FinalSubmit)                                   │ │
│  ├────────────────────────────────────────────────────────────┤ │
│  │ POSSIBLE RETURNING USER: Approved registry                 │ │
│  │ — name 83.6%, email 83.6%.                                 │ │
│  │                                                            │ │
│  │ AI: High similarity signals require human review.          │ │
│  │                                                            │ │
│  │ Name: Chinmayi K  Email: chinmayi.k@gmail.com  Phone: ...  │ │
│  │                                                            │ │
│  │ ┌──────────────────┐  ┌──────────────────────────────────┐ │ │
│  │ │Layer 1 Fingerprint│  │Layer 2 Approved-User Similarity  │ │ │
│  │ │No match          │  │Name 83.6% · Email 83.6%          │ │ │
│  │ └──────────────────┘  └──────────────────────────────────┘ │ │
│  │ ┌──────────────────┐  ┌──────────────────────────────────┐ │ │
│  │ │Layer 3 Behavioral │  │Layer 4 Benefit Claim History     │ │ │
│  │ │No prior profile  │  │No prior claim                    │ │ │
│  │ └──────────────────┘  └──────────────────────────────────┘ │ │
│  │                                                            │ │
│  │ [Officer note: Abbreviated name — verified...]             │ │
│  │                  [✓ Approve]    [✗ Reject]                 │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

- **Click-to-expand:** Each case row is clickable; expands to show full detail panel
- **4-layer grid:** Color-coded (red = danger, yellow = warning, green = clear)
- **Layer 1:** Fingerprint match / no match
- **Layer 2:** Approved-user name% and email% scores
- **Layer 3:** Behavioral score (if prior profile exists)
- **Layer 4:** Benefit claimed / not claimed
- **Officer note:** Free text, stored with audit log entry
- **Approve/Reject:** Triggers full commit flow or rejection with audit trail

---

### 11.4 Thresholds Tab

```
┌─────────────────────────────────────────────────────────────────┐
│  Risk Detection Thresholds                                      │
│                                                                 │
│  HIGH RISK THRESHOLD        85  ████████████████████░░  100    │
│  Flag cases above this level as high-risk duplicates           │
│                                                                 │
│  MEDIUM RISK THRESHOLD      60  █████████████░░░░░░░░░  100    │
│  Flag cases above this level for closer inspection             │
│                                                                 │
│  BOT CPS THRESHOLD          35  ███████░░░░░░░░░░░░░░░   60    │
│  Typing speed above this triggers bot detection                │
│                                                                 │
│  MAX ATTEMPTS PER DEVICE     3  ██░░░░░░░░░░░░░░░░░░░░   20    │
│  Block device submitting more than 3 times in 60 minutes       │
│                                                                 │
│  ROLLING WINDOW            60m  ███░░░░░░░░░░░░░░░░░░░ 1440   │
│  A device submitting attempt #4 within 60 min → blocked        │
│                                                                 │
│  [Save All Settings]  [Reset Velocity Counters]                 │
└─────────────────────────────────────────────────────────────────┘
```

All changes apply instantly — no server restart required. The "Reset Velocity Counters" button clears all in-memory device submission history (useful between demo runs).

---

### 11.5 Audit Log Tab

Immutable chronological log of all officer actions. Cannot be edited or deleted.

```
Timestamp          Action              Officer   Details
───────────────────────────────────────────────────────────────
2026-04-28 12:04   approve             admin     Case CCCA59C5 — Abbreviated name
2026-04-28 11:45   update_thresholds   admin     HIGH:85% MEDIUM:60% Device:3/60min
2026-04-28 11:30   velocity_reset      admin     All counters cleared
2026-04-28 10:15   bulk_import         admin     247 records imported
```

---

## 12. Test Form (Demo)

**File:** `test-form/index.html`  
**URL:** `file:///path/to/test-form/index.html` (opened directly in browser)

The test form is a standalone HTML page that simulates 4 different platform types. It requires no web server — it talks directly to the backend at `localhost:8000`.

### 12.1 Platform Tabs

| Tab | Icon | Platform Name | Fields |
|---|---|---|---|
| Edtech | 🎓 | EduVerify — Exam Registration | Full Name, Phone (OTP), Email, Exam/Course |
| Jobs | 💼 | TalentBridge — Job Portal | Full Name, Email, Phone (OTP), GovID, Position |
| E-Commerce | 🛒 | ShopSwift | Full Name, Email, Phone (OTP), Address |
| Insurance | 🛡️ | SafeShield — Insurance | Full Name, Email, Phone (OTP), Policy Type |

### 12.2 Left Panel — Device Fingerprint

Displays all signals being collected in real-time:

```
● DEVICE FINGERPRINT
USER AGENT (truncated)
  Mozilla/5.0 (Macintosh; Intel Mac OS X...)

SCREEN RES + COLOR DEPTH
  1800×1169 @ 30bit

TIMEZONE
  Asia/Calcutta

CPU CORES / TOUCH POINTS
  12 cores / 0 touch

CANVAS HASH (GPU render)
  AAEJREFUAwBmHie1iHWaqc9QAAAAB...

LANGUAGE / PLATFORM
  en-US / MacIntel

COMPOSITE DEVICE ID (DJB2)
  222d28a5

✓ NEW DEVICE — FINGERPRINT REGISTERED

VELOCITY CHECKS
  Accounts / device       3
  Accounts / IP           1
  Submits this session    4
```

Status badge:
- **Green** `NEW DEVICE — FINGERPRINT REGISTERED` — first time this device is seen
- **Red pulsing** `DEVICE FINGERPRINT MATCHED — DUPLICATE` — exact Layer 1 fingerprint match

### 12.3 Right Panel — Behavioral Telemetry

Live typing analysis while user fills the form:

```
● FRAUDGUARD LIVE SIGNALS

Typing Speed          4.2 CPS   ←  color: green (human)
Keystrokes              52
Deletions                3
Paste Events             0
Time on Field         13.4s

✓ HUMAN-LIKE

Active field: Email Address
```

Pattern badges:
- `IDLE` — no input yet
- `MONITORING` — user is typing, collecting data
- `✓ HUMAN-LIKE` — CPS < 15, no suspicious signals
- `⚠ SUSPICIOUS` — elevated CPS or paste events
- `🤖 BOT DETECTED` — CPS > 35 (configurable threshold)

### 12.4 OTP Flow in the Form

```
Phone field appears
        │
        ▼
"Send OTP" button appears next to phone field
        │
User clicks "Send OTP"
        │  POST /api/otp/send
        ▼
OTP auto-filled in demo hint box
Timer starts: "60s remaining"
        │
User enters code and clicks "Verify"
        │  POST /api/otp/verify
        ▼
✓ Phone verified  (Verify button turns green + disabled)
        │
User fills remaining fields and clicks "Register"
        │  POST /api/submit { otpToken: "..." }
        ▼
Result banner shown
        │
.finally() → resetOTPUI() called
        │
OTP UI resets — user can verify new OTP for next test
```

**Key behavior:** After every submit (success or failure), `resetOTPUI()` is called automatically. This re-enables the "Send OTP" button and hides the OTP row, allowing the user to re-verify without refreshing the page. This is essential for running Test 5 (same details again → fingerprint block) without a page reload.

### 12.5 Field Validation

- Phone: numeric only, max 10 digits, `inputMode="numeric"`, keydown blocker strips non-digits
- If phone is edited after OTP is verified → OTP UI resets, re-verification required
- All required fields checked before submit — missing fields show browser validation

---

## 13. Chrome Extension

**Directory:** `extension/`  
**Type:** Chrome Manifest V3

### 13.1 Architecture

```
User visits a web form
        │
        ▼
content.js injects into page
  - Computes device fingerprint (DJB2)
  - Attaches keyup listeners to all input fields
  - Attaches submit listener to all forms
        │
User types in a field
        │
        ▼
content.js → chrome.runtime.sendMessage(ANALYZE_INPUT)
        │
        ▼
background.js receives message
  - POST /api/analyze with field value + behavior
        │
        ▼
background.js → content.js reply: { riskLevel, similarityScore }
        │
        ▼
content.js shows border color + tooltip on field
  - HIGH: red border + "⚠ High similarity detected" tooltip
  - MEDIUM: orange border + tooltip with similarity %
  - LOW: no visible change
        │
User clicks submit
        │
        ▼
content.js intercepts submit (preventDefault)
  - Collects all fields into identityDetails
  - chrome.runtime.sendMessage(SUBMIT_IDENTITY)
        │
        ▼
background.js → POST /api/submit
        │
        ▼
content.js receives response
  - Shows banner: success / rejected / under review
  - If success: calls form.requestSubmit() to allow actual submit
  - If rejected/escalated: keeps banner, form not submitted
```

### 13.2 Domain Restriction

The extension's content script checks the current domain before activating:

```javascript
const allowedDomains = ['.gov.in', '.nic.in', 'localhost', '127.0.0.1'];
const isAllowed = allowedDomains.some(d => location.hostname.includes(d));
if (!isAllowed) return;  // Exit silently on non-allowed domains
```

This prevents the extension from monitoring personal banking or other sensitive sites.

### 13.3 Field Category Inference

The extension infers field categories from HTML attributes:

```javascript
function inferCategory(element) {
  const hints = [
    element.id,
    element.name,
    element.placeholder,
    element.getAttribute('aria-label'),
    element.closest('label')?.textContent
  ].join(' ').toLowerCase();

  if (hints.match(/full.?name|first.?name|candidate.?name/)) return 'FullName';
  if (hints.match(/email|e-mail/))                            return 'EmailAddress';
  if (hints.match(/phone|mobile|contact.?no/))               return 'PhoneNumber';
  if (hints.match(/gov.?id|aadhaar|pan|passport|voter/))     return 'GovID';
  return null;  // Unknown field — skip monitoring
}
```

---

## 14. Configuration & Environment Variables

**File:** `backend/.env` (copy from `.env.example`, never commit)

### 14.1 All Variables

| Variable | Default | Required? | Description |
|---|---|---|---|
| `PROJECT_NAME` | "FraudGuard AI" | No | Display name |
| `MONGODB_URL` | "mongodb://localhost:27017" | No | MongoDB connection string |
| `DATABASE_NAME` | "fraud_detection_db" | No | MongoDB database name |
| `MODEL_NAME` | "all-MiniLM-L6-v2" | No | SentenceTransformer model ID |
| `API_KEY` | "dev-key-change-in-production" | **Yes** | Shared secret for extension auth |
| `ALLOWED_ORIGINS` | `["http://localhost:3000", "null"]` | No | CORS origins list |
| `ADMIN_USERNAME` | "admin" | **Yes** | Dashboard login username |
| `ADMIN_PASSWORD_HASH` | bcrypt("admin123") | **Yes** | Dashboard login password (bcrypt) |
| `JWT_SECRET` | "jwt-secret-change-in-production" | **Yes** | JWT signing key |
| `JWT_EXPIRE_MINUTES` | 480 | No | Session duration (8 hours) |
| `HIGH_RISK_THRESHOLD` | 85.0 | No | Similarity % for HIGH risk |
| `MEDIUM_RISK_THRESHOLD` | 60.0 | No | Similarity % for MEDIUM risk |
| `BOT_CPS_THRESHOLD` | 35.0 | No | CPS above this = bot |
| `DEVICE_MAX_ATTEMPTS` | 3 | No | Submissions per device per window |
| `DEVICE_WINDOW_MINUTES` | 60 | No | Rolling window for velocity check |
| `ANTHROPIC_API_KEY` | "" | No | Claude API key (LLM fallback) |
| `GEMINI_API_KEY` | "" | No | Gemini API key (primary LLM) |

### 14.2 Minimum Production Changes

```bash
# REQUIRED: Change these before any production deployment
API_KEY=<random 32+ char string>
JWT_SECRET=<random 32+ char string>
ADMIN_USERNAME=<your-chosen-username>
ADMIN_PASSWORD_HASH=<bcrypt-hash-of-your-password>
MONGODB_URL=<your-production-mongodb-uri>
```

To generate a bcrypt hash in Python:
```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"])
print(pwd_context.hash("your-new-password"))
```

---

## 15. Running the Project

### 15.1 Prerequisites

```
Python 3.11+
Node.js 18+
MongoDB (local or Atlas)
Chrome browser (for extension)
```

### 15.2 Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit config
cp .env.example .env
# Edit .env with your API keys

# Start server
uvicorn app.main:app --reload --reload-dir app

# Server runs at: http://localhost:8000
# API docs at:    http://localhost:8000/docs
```

### 15.3 Admin Dashboard Setup

```bash
cd admin-dashboard
npm install
npm run dev
# Dashboard runs at: http://localhost:5173
```

### 15.4 Test Form

Open directly in Chrome:
```
File → Open File → test-form/index.html
```
Or serve via any static server:
```bash
cd test-form
python -m http.server 3000
# Open: http://localhost:3000
```

### 15.5 Chrome Extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer Mode** (top right)
3. Click **Load unpacked**
4. Select the `extension/` directory
5. Extension appears in toolbar

### 15.6 Startup Sequence (Recommended Order)

```
1. Start MongoDB (if local):     mongod
2. Start Backend:                uvicorn app.main:app --reload --reload-dir app
3. Start Admin Dashboard:        cd admin-dashboard && npm run dev
4. Load Extension:               chrome://extensions → Load unpacked
5. Open Test Form:               Open test-form/index.html in Chrome
```

---

## 16. End-to-End Demo Walkthrough

This walkthrough demonstrates all 6 fraud detection scenarios using the name "Pulkit Shah" on the EduVerify (Edtech) platform.

### Before Starting

- Admin Dashboard → Thresholds → click **"Reset Velocity Counters"**
- Restart backend (`Ctrl+C` and re-run) to clear in-memory state if needed
- Open test form, confirm extension shows `● NEW DEVICE — FINGERPRINT REGISTERED`

---

### Test 1 — New Legitimate User (Should Pass)

**What this proves:** Clean new users are approved without friction.

| Field | Value |
|---|---|
| Full Name | `Pulkit Shah` |
| Phone | `9823456710` |
| Email | `pulkit.shah@gmail.com` |
| Course | AWS Certification |

**Steps:**
1. Fill all fields
2. Click **Send OTP** → OTP auto-appears in demo hint
3. Enter OTP code → click **Verify**
4. Click **Register for Exam**

**Expected result:** ✅ Green banner — *"Registration successful!"*

**What happened internally:**
- No fingerprint match (first submission)
- No approved-user similarity (empty index)
- All sims < 30% → auto-approved
- Committed to all 4 layers: fingerprint stored, FAISS updated, behavior profiled, exam_slot benefit recorded

---

### Test 2 — Composite Fingerprint Block (Layer 1)

**What this proves:** Same person, same device, same credentials → blocked instantly.  
**Do NOT refresh the page between Test 1 and Test 2.**

| Field | Value |
|---|---|
| Full Name | `Pulkit Shah` (same) |
| Phone | `9823456710` (same) |
| Email | `pulkit.shah@gmail.com` (same) |

**Steps:**
1. OTP UI resets automatically after Test 1 (thanks to `resetOTPUI()`)
2. Fill same details → Send OTP → Verify → Register

**Expected result:** ❌ Red banner — *"RETURNING USER: Exact identity fingerprint already registered."*

**Extension panel:** Shows `DEVICE FINGERPRINT MATCHED — DUPLICATE` (red pulsing)

**What happened:** SHA256("9823456710|pulkit shah|222d28a5") = same hash as Test 1 → Layer 1 match.

---

### Test 3 — Approved Registry FAISS Block (Layer 2)

**What this proves:** Even with a new phone number, same name+email is caught by semantic similarity.

| Field | Value |
|---|---|
| Full Name | `Pulkit Shah` (same) |
| Phone | `8712345609` **(different!)** |
| Email | `pulkit.shah@gmail.com` (same) |

**Steps:** Send OTP → Verify → Register

**Expected result:** ❌ Red banner — *"Returning user: name 100.0% + email 100.0% match approved registry."*

**What happened:** Different phone → different fingerprint → Layer 1 missed. But FAISS approved-user index found `approved_name_sim = 100%` and `approved_email_sim = 100%` → Rule 5 fires → REJECT.

---

### Test 4 — Phone Hash Block

**What this proves:** Phone number is a unique identity signal — reusing it under a different name is blocked.

| Field | Value |
|---|---|
| Full Name | `Rahul Verma` |
| Phone | `9823456710` **(Pulkit's phone!)** |
| Email | `rahul.verma22@gmail.com` |

**Steps:** Send OTP → Verify → Register

**Expected result:** ❌ Red banner — *"Phone number already registered to another account. Each account must use a unique phone number."*

**What happened:** OTP proved ownership of the phone. Backend hashed it → matched stored hash from Test 1 → phone_match = True → Rule 3 fires → REJECT.

---

### Test 5 — Human Review Escalation + Officer Decision

**What this proves:** Ambiguous cases go to human officers, not auto-decided.

| Field | Value |
|---|---|
| Full Name | `P. Shah` (abbreviated!) |
| Phone | `7612345890` (new) |
| Email | `p.shah@gmail.com` |
| Course | UPSC Prelims |

**Steps:** Send OTP → Verify → Register

**Expected result:** ⏳ Yellow banner — *"Your submission is under review. Reference No: XXXXXXXX"*

**In Admin Dashboard → Review Queue:**
1. Click the case row → panel expands
2. See 4-layer grid:
   - Layer 1: No fingerprint match
   - Layer 2: Name ~83% · Email ~75% (approved registry)
   - Layer 3: No prior behavioral profile
   - Layer 4: No prior claim
3. Type officer note: `Abbreviated name — verified manually`
4. Click **Approve**

**Result:** Green toast — *"Case XXXXXXXX approved."*

---

### Test 6 — Velocity Limit (Device Rate-Limiting)

**What this proves:** Too many submissions from one device in a short time = automated fraud pattern.

Keep submitting with any details. After the 4th submission (limit = 3):

**Expected result:** ❌ Red banner — *"VELOCITY LIMIT: 4 submissions from this device in the last 60 minutes (limit: 3)."*

**Reset for next demo:** Admin Dashboard → Thresholds → **Reset Velocity Counters**

---

### What Each Test Demonstrates

```
Test 1 → Clean user — baseline (auto-approve)
Test 2 → Layer 1 — Composite fingerprint exact match
Test 3 → Layer 2 — FAISS approved-user semantic similarity
Test 4 → Phone hash — unique phone enforcement
Test 5 → LLM escalation → Human officer review → 4-layer transparency
Test 6 → Velocity-based device rate limiting (bot/abuse prevention)
```

---

## 17. Security Design

### 17.1 Authentication

```
Component          Auth Type     Token Lifetime    Notes
─────────────────────────────────────────────────────────────────────
Extension          API Key       Permanent         Shared secret in .env
Admin Dashboard    JWT (Bearer)  8 hours           Officer shift duration
OTP Routes         API Key       —                 Same key as extension
Public Routes      None          —                 Rate-limited (20 req/min)
```

### 17.2 Data Masking

Sensitive values are masked before storage in alerts:

```python
def _mask_sensitive(value: str, field_name: str) -> str:
    if field_name in ("EmailAddress",):
        parts = value.split("@")
        return parts[0][:2] + "***@" + (parts[1] if len(parts)>1 else "")
    if field_name in ("PhoneNumber",):
        return value[:2] + "****" + value[-2:]
    return value  # FullName stored as-is (display name)
```

### 17.3 No PII in Device Fingerprint

The DJB2 hash is one-way — you cannot recover the original device signals from the hash. No personally identifiable information is in the device fingerprint itself.

### 17.4 Phone Hashes (Never Stored Plaintext)

Phone numbers are never stored in plaintext. Only `SHA256(normalize(phone))` is stored. The original phone cannot be recovered from the hash.

### 17.5 Rate Limiting

```
/api/analyze   → 60 req/min per IP (real-time monitoring)
/api/submit    → 10 req/min per IP (final submission)
/api/status/*  → 20 req/min per IP (applicant lookup)
```

### 17.6 Immutable Audit Trail

Audit logs are insert-only. The codebase has no route that updates or deletes audit log records. Officers cannot retroactively modify decision history.

### 17.7 CORS

Only explicitly listed origins can call the API (set via `ALLOWED_ORIGINS` in `.env`). The test form adds `"null"` to allow `file://` origin during development.

---

## 18. Feature Traceability Matrix

| ID | Type | Feature Description | Where Implemented |
|---|---|---|---|
| FR-1 | Feature | Real-time full-name monitoring | `POST /api/analyze` → `ml_service.evaluate_risk()` |
| FR-2 | Feature | Real-time multi-field monitoring | `POST /api/analyze` with field category inference |
| FR-20 | Feature | Configurable risk thresholds | `PUT /api/admin/thresholds` → `ml_engine.update_thresholds()` |
| FR-25 | Feature | Filterable alert list | `GET /api/admin/alerts?risk_level=&search=` |
| FR-27 | Feature | CSV export of alerts | `GET /api/admin/alerts/export` → `StreamingResponse` |
| FR-28 | Feature | Immutable audit logs | `GET /api/admin/audit-log` + insert-only writes |
| SR-1 | Story | Auto-escalation to human queue | `auto_decide()` → ESCALATE → `db.insert_review_case()` |
| SR-2 | Story | Officer approve/reject with note | `POST /api/admin/review-queue/{id}/approve|reject` |
| BR-2 | Bug Fix | Configurable bot CPS threshold | `ThresholdUpdate.bot_cps_threshold` → `ml_engine.bot_cps_threshold` |
| BR-4 | Bug Fix | Review queue survives restart | MongoDB `review_queue` collection (not in-memory only) |
| BR-6 | Bug Fix | Audit trail complete and immutable | Insert-only `audit_logs` collection |
| GAP-1 | Fix | Phone hashes survive restart | Startup: `db.load_phone_hashes()` → `ml_engine.phone_hashes` sync |
| GAP-2 | Fix | Phone hash queryable from DB | Added `phone_hash` field to `identities` collection + index |
| GAP-3 | Addition | OTP phone verification | `otp_service.py` + `/api/otp/send` + `/api/otp/verify` + OTP gate in submit |
| GAP-4 | Fix | Device velocity rate limiting | `ml_engine.check_device_velocity()` + rolling window |
| GAP-5 | Fix | False positive escalation prevention | MEDIUM-only rule in `apply_rules()` → auto-approve |
| GAP-6 | Fix | OTP UI reset after submit | `resetOTPUI()` called in `.finally()` in test form |
| GAP-7 | Fix | Phone hash block message accuracy | `phone_match` flag + dedicated rule before name/email sim rules |
| GAP-8 | Addition | Velocity counter reset endpoint | `POST /api/admin/velocity/reset` |
| GAP-9 | Fix | Review queue click-to-expand | `expanded` state + toggled panel in `ReviewQueueTab` |
| GAP-10 | Fix | Approved-user check before LOW-risk approve | Rule reordering in `apply_rules()` |

---

*End of Documentation*
