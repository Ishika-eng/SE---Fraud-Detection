# FraudGuard AI — Real-Time Identity Fraud Detection

> A Software Engineering Course Project  
> Vishwakarma Institute of Technology, Pune

---

## What Is This?

FraudGuard AI is a real-time identity fraud detection system that prevents duplicate registrations on online platforms — exam portals, government schemes, insurance platforms, and e-commerce websites.

It works as a **browser extension** that sits invisibly behind any registration form and makes a fraud decision in **under 200 milliseconds** without interrupting legitimate users.

---

## How It Works — Four Detection Layers

| Layer | Method | Catches |
|---|---|---|
| **Layer 1** | SHA-256 composite fingerprint (phone + email + device) | Exact same identity returning |
| **Layer 2** | FAISS semantic similarity (dual-index) | Same person with slightly changed name/email |
| **Layer 3** | Behavioral biometrics (CPS, keystrokes, paste) | Same person even if all fields changed |
| **Layer 4** | Benefit history per fingerprint | Re-claiming an already-used benefit |

Ambiguous cases go to a **human officer** via the admin dashboard. Clear fraud is auto-blocked. Genuine users pass through with no extra steps.

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI (Python) |
| ML / Similarity | FAISS + SentenceTransformer (all-MiniLM-L6-v2) |
| Identity Hashing | SHA-256 |
| Device Fingerprinting | DJB2 hardware hash |
| Database | MongoDB (Motor async) + in-memory fallback |
| LLM Decision | Gemini Flash → Claude Haiku → Heuristic |
| Admin Dashboard | React + Vite + Recharts |
| Browser Extension | Chrome Manifest V3 |
| OTP Verification | 6-digit code, single-use token |

---

## Project Structure

```
SE---Fraud-Detection/
├── backend/          # FastAPI backend + ML service + decision engine
├── admin-dashboard/  # React admin dashboard
├── extension/        # Chrome browser extension
└── test-form/        # Sample HTML registration forms for testing
```

---

## Quick Start

See **[SETUP.md](./SETUP.md)** for the complete step-by-step setup guide including:
- Prerequisites
- Backend setup (Python venv + dependencies)
- Admin dashboard setup (Node.js)
- Browser extension loading in Chrome
- Environment variables reference
- 8 end-to-end test cases
- Troubleshooting guide

---

## Authors

| Name | Contribution |
|---|---|
| Chiranjilal Kumawat | Identity Matching Engine (Layer 1 + Layer 2) |
| Ishika Mahadar | Behavioral Engine + Auto-Decision System (Layer 3) |
| Dhruv Madderlawar | Backend API + OTP Verification |
| Krish Harsola | Database + Admin API + Dashboard (Layer 4) |

**Guide:** Prof. Vidya Gaikwad

---

## Default Credentials (Development Only)

| Component | Username | Password / Key |
|---|---|---|
| Admin Dashboard | `admin` | `admin123` |
| Extension API Key | — | `dev-key-change-in-production` |

> ⚠️ Change all credentials before any production deployment. See `.env.example`.
