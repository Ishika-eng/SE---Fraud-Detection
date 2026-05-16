# Person 1 — Identity Matching Engine
## Role: ML Engineer — Similarity & Fingerprinting

---

## What Is My Part About?

My job in this project is to answer one question:

> **"Has this person registered before — even if they changed their name, email, or phone?"**

To answer that, I built two systems that work together:

- **Layer 1** — Exact fingerprint matching (phone + email + device = unique ID)
- **Layer 2** — Semantic similarity search (does this name/email *sound like* someone already approved?)

Together, these two layers catch the most common fraud pattern: a person who already registered and got a benefit, now trying to register again with slightly different details.

---

## The Big Picture — What Happens When Someone Submits a Form

```
User fills form and clicks Submit
              │
              ▼
      Is the fingerprint already stored?  ──YES──► BLOCK (returning user)
              │ NO
              ▼
      Is the phone number already used?  ──YES──► BLOCK (phone reuse)
              │ NO
              ▼
      Does name/email match an approved user?  ──YES (>95%)──► BLOCK
              │ NO (or partial match)
              ▼
      Does name/email match anyone in general registry?
              │
              ▼
      Assign risk level: LOW / MEDIUM / HIGH
              │
              ▼
      Pass to decision engine for final call
```

---

## Part 1 — Layer 1: Composite Identity Fingerprint

### What Is a Fingerprint?

A fingerprint in this system is not a physical fingerprint. It is a **unique code** generated from three pieces of information the user provides:

1. Their **phone number**
2. Their **email address**
3. Their **device ID** (a code representing the browser/computer they used)

These three are combined and passed through a mathematical function called **SHA-256**, which produces a fixed 64-character code. This code is the fingerprint.

```
Phone:    9823456710
Email:    pulkit.shah@gmail.com
Device:   222d28a5

Combined: "9823456710|pulkit shah|222d28a5"
                        │
                   SHA-256 hash
                        │
Fingerprint: "a3f9c2b1d4e7f8a2c3b4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6"
```

### Why SHA-256?

SHA-256 is a one-way function — you can go from the data to the fingerprint, but you **cannot go backwards**. This means:
- We never store the actual phone number or email in plaintext inside the fingerprint system
- If someone hacks the fingerprint file, they still cannot recover the original data
- Privacy is protected

### How Normalization Works

Before creating the fingerprint, each value is **cleaned up** (normalized) so that small variations produce the same result.

**Phone normalization:**
```
"+91-9823456710"  →  "9823456710"   (remove country code, dashes)
"09823456710"     →  "9823456710"   (remove leading 0)
"9823456710"      →  "9823456710"   (already clean)
```
All three produce the same fingerprint — they are the same number.

**Email normalization:**
```
"pulkit.shah@gmail.com"    →  "pulkit shah"   (take part before @, replace dots/dashes with space)
"pulkit_shah@yahoo.com"    →  "pulkit shah"   (same result — same fingerprint)
"PULKIT.SHAH@outlook.com"  →  "pulkit shah"   (lowercase too)
```
Only the local part (before @) is used because people often change email providers.

**Device ID normalization:**
```
"222d28a5"    →  "222d28a5"   (real device hash — kept as-is)
""            →  ""           (empty — collapsed to empty string)
"unknown"     →  ""           (browser blocked canvas — same as empty)
"undefined"   →  ""           (missing value — same as empty)
```
All "no signal" values collapse to the same empty string so a user doesn't get a different fingerprint just because they blocked canvas rendering.

**Why normalization is important:**

Without normalization, a fraudster could write their phone as `+91-9823456710` instead of `9823456710` and get a completely different fingerprint, bypassing the check. Normalization closes this loophole.

### How Fingerprints Are Stored

When a user gets approved, their fingerprint is saved in two places:

1. **In memory** — a Python dictionary: `{ fingerprint_hash: case_id }`
2. **On disk** — `identity_fingerprints.json`
3. **In MongoDB** — `identities` collection (synced on server startup)

```json
{
  "a3f9c2b1...": "case-uuid-1",
  "b4e8d3c2...": "case-uuid-2"
}
```

### How Fingerprint Checking Works

When a new submission arrives:
1. Generate the fingerprint from the submitted phone + email + device
2. Check if this fingerprint already exists in the stored dictionary
3. If **YES** → block immediately with message "RETURNING USER: Exact identity fingerprint already registered"
4. If **NO** → continue to next checks

```python
def check_fingerprint(self, fingerprint: str) -> dict:
    if fingerprint in self.identity_fingerprints:
        return {"matched": True, "user_id": self.identity_fingerprints[fingerprint]}
    return {"matched": False, "user_id": None}
```

This check happens **before** everything else — it is the fastest and most certain check in the system.

### Phone Hash Registry (Bonus Check)

The phone number is also independently checked as a separate signal. Even if the fingerprint doesn't match (because the user changed their device or email), the phone number alone is enough to flag them.

```
Phone "9823456710"
        │
   normalize → "9823456710"
        │
   SHA-256 → "hash_abc123..."
        │
   Is this hash in phone_hashes set?
        │
   YES → Block: "Phone number already registered to another account"
   NO  → Continue
```

Phone hashes are stored in:
- `phone_hashes` — a Python `set()` in memory (fast O(1) lookup)
- `phone_hashes.json` — disk backup
- MongoDB `phone_hashes` collection — persistent backup

On every server restart, MongoDB phone hashes are loaded into memory so no approved phone is ever "forgotten."

---

## Part 2 — Layer 2: FAISS Semantic Similarity

### What Is FAISS?

FAISS stands for **Facebook AI Similarity Search**. It is a library that can very quickly find the most similar item in a large database.

Think of it like a smart search engine — instead of searching for exact matches, it searches for items that are **close in meaning**.

### What Is a SentenceTransformer?

Before we can put text into FAISS, we need to convert text into numbers. We use a model called **all-MiniLM-L6-v2** (a lightweight version of BERT) to do this.

This model reads a name or email and produces a list of **384 numbers** (called a vector or embedding). These numbers capture the *meaning* of the text.

```
"Pulkit Shah"   →  [0.12, -0.34, 0.87, 0.23, ..., 0.45]  (384 numbers)
"Pulkit Sah"    →  [0.11, -0.33, 0.86, 0.22, ..., 0.44]  (very similar numbers)
"Rahul Verma"   →  [0.78,  0.21, -0.12, 0.67, ..., -0.31] (very different numbers)
```

Because "Pulkit Shah" and "Pulkit Sah" have similar meanings, their vectors are close to each other. FAISS finds this closeness instantly.

### Two Separate Indices — Why?

This is one of the most important design decisions in the system.

There are **two separate FAISS databases**:

| Index | Contains | Used For |
|---|---|---|
| General Registry | Everyone who ever submitted (approved + rejected + pending) | Real-time field monitoring |
| Approved-Only Registry | Only people who were approved and committed | Returning-user fraud detection |

**Why keep them separate?**

Imagine a fraudster "Rahul Sharma" submits and gets **rejected** (caught as fraud). His name goes into the general registry.

Now a **genuine new user** named "Rahul Sharma" tries to register. If we only had one index, the new user's name would match the rejected fraudster's name — and we might wrongly flag the new user.

By keeping a separate approved-only index, we ensure that only **verified, committed identities** are used for returning-user detection. A hit against the general registry alone is not enough to block someone.

```
General Registry           Approved-Only Registry
─────────────────          ──────────────────────
Pulkit Shah  ✓             Pulkit Shah  ✓
Rahul Verma  ✗ (rejected)  (Rahul not here — rejected)
Chinmayi K   → pending     (Chinmayi not here — not yet approved)
```

### How Similarity Is Calculated

When a new name like "P. Shah" is submitted:

1. Convert "P. Shah" to a 384-number vector using SentenceTransformer
2. Normalize the vector (L2 normalization — makes all vectors the same length)
3. Search the approved-only FAISS index for the closest match
4. The closeness is measured using **inner product** (dot product) — higher = more similar
5. Multiply by 100 to get a percentage: **83.6%**

```python
def _query_approved_index(self, text: str, category: str) -> float:
    vector = self.model.encode([text])
    faiss.normalize_L2(vector)
    distances, _ = index.search(vector, k=1)
    return float(distances[0][0]) * 100.0   # → 83.6%
```

### What Similarity Scores Mean

| Score | Meaning | Action |
|---|---|---|
| 0–30% | Completely different person | Allow through |
| 30–60% | Slightly similar (common names) | Low concern |
| 60–85% | Possibly the same person | Medium risk — LLM decides |
| 85–95% | Very likely the same person | High risk — escalate |
| > 95% | Almost certainly the same person | Auto-block |

Both name AND email must exceed the threshold for an auto-block. A high name match alone (common name) is not enough.

### Real-Time Field Monitoring vs. Submit-Time Check

Layer 2 is used in two different ways:

**While typing (real-time):**
- After each keystroke (with 1.2 second delay), the typed name/email is checked against the **general registry**
- If similarity > 85% → show orange/red border on the field with a warning tooltip
- This alerts the system early but does NOT block yet

**On final submit:**
- The submitted name + email are checked against the **approved-only registry**
- This is the definitive check that determines the fraud decision

### How Items Are Added to the Index

When a user is approved (either automatically or by an officer), their name and email are added to both indices:

```
"Pulkit Shah" submitted and approved
         │
         ├── Add to General Registry (FullName index)
         │   → for future real-time monitoring
         │
         └── Add to Approved-Only Registry (ApprovedFullName index)
             → for future returning-user detection
```

The email local-part is also stored separately:

```
"pulkit.shah@gmail.com"  →  extract "pulkit shah"  →  add to ApprovedEmailLocalPart index
```

### How FAISS Indices Are Saved and Loaded

FAISS indices are saved as **binary files** on disk:

```
indices/
├── FullName.bin                ← general name index
├── EmailLocalPart.bin          ← general email index
├── ApprovedFullName.bin        ← approved-only name index
└── ApprovedEmailLocalPart.bin  ← approved-only email index
```

A separate JSON file maps vector positions back to original text:

```json
{
  "FullName":            {"0": "Pulkit Shah", "1": "Rahul Verma", ...},
  "EmailLocalPart":      {"0": "pulkit shah", "1": "rahul verma", ...},
  "ApprovedFullName":    {"0": "Pulkit Shah", ...},
  "ApprovedEmailLocalPart": {"0": "pulkit shah", ...}
}
```

On server startup, both the FAISS `.bin` files and this JSON are loaded back into memory, restoring the full index exactly as it was.

### Why FlatIP Index (Not Approximate)?

FAISS offers two types of indices:

| Type | Speed | Accuracy | Use Case |
|---|---|---|---|
| FlatIP (what we use) | Slower | 100% exact | Fraud detection |
| IVF / HNSW | Much faster | 95-99% (may miss some) | Large-scale search |

For fraud detection, **missing even 1% of matches is not acceptable**. If a returning fraudster slips through because the approximate index missed them, the entire system fails. So we chose FlatIP — guaranteed exact results, every time.

---

## Complete Flow — Putting It All Together

Here is the exact order of checks when someone clicks submit:

```
Step 1: Extract details from form
        phone = "9823456710"
        email = "pulkit.shah@gmail.com"
        device = "222d28a5"
        name = "Pulkit Shah"

Step 2: Build composite fingerprint
        → SHA256("9823456710|pulkit shah|222d28a5")
        → "a3f9c2b1d4e7..."

Step 3: Check fingerprint against stored fingerprints
        → Found? → BLOCK immediately (Layer 1 match)
        → Not found? → Continue

Step 4: Check phone hash
        → SHA256("9823456710") in phone_hashes?
        → Found? → BLOCK (phone reuse)
        → Not found? → Continue

Step 5: Check approved-only FAISS (Layer 2)
        → Encode "Pulkit Shah" → vector → search ApprovedFullName index
        → Encode "pulkit shah" → vector → search ApprovedEmailLocalPart index
        → Both > 95%? → BLOCK (returning user)
        → Email alone > 85%? → BLOCK (same email, different name)
        → Partial match? → Continue with scores for decision engine

Step 6: Check general registry FAISS
        → Encode name/email → search FullName and EmailLocalPart indices
        → High both? → HIGH risk
        → Medium? → MEDIUM risk
        → Low? → LOW risk

Step 7: Return all signals to decision engine
        {
          riskLevel: "MEDIUM",
          fingerprint_match: false,
          approved_name_sim: 83.6,
          approved_email_sim: 75.5,
          name_sim: 72.1,
          email_sim: 68.4
        }
```

---

## Key Design Decisions and Why

### 1. Two FAISS Indices Instead of One
Keeping approved and general indices separate prevents false positives from rejected submissions contaminating the returning-user detection.

### 2. SHA-256 for Phone and Fingerprint
One-way hash — original data cannot be recovered. Privacy-safe storage.

### 3. Normalization Before Hashing
Without normalization, `+91-9823456710` and `9823456710` would look like different numbers. Normalization ensures the same person always gets the same fingerprint regardless of formatting.

### 4. Email Local-Part Only (Not Full Email)
People frequently change email providers (Gmail → Outlook → Yahoo). The username part (`pulkit.shah`) is the stable identifier. Using the full email would miss these cases.

### 5. FlatIP (Exact) Index Over Approximate
100% recall is required. Missing a match in fraud detection has real consequences — a fraudster gets through. Speed is sacrificed for accuracy.

### 6. MongoDB Startup Sync
On every server restart, phone hashes AND identity fingerprints are reloaded from MongoDB. This ensures no approved identity is "forgotten" even if the local JSON files are lost or corrupted.

---

## Files I Own

| File | What It Does |
|---|---|
| `backend/app/services/ml_service.py` | Core engine — all Layer 1 and Layer 2 logic |
| `indices/FullName.bin` | FAISS index of all submitted names |
| `indices/EmailLocalPart.bin` | FAISS index of all submitted email local-parts |
| `indices/ApprovedFullName.bin` | FAISS index of approved names only |
| `indices/ApprovedEmailLocalPart.bin` | FAISS index of approved email local-parts only |
| `identity_fingerprints.json` | Stored composite fingerprints |
| `phone_hashes.json` | Stored phone number hashes |

---

## Summary

| Layer | Method | Catches |
|---|---|---|
| Layer 1 | SHA-256 fingerprint (exact match) | Same person, same phone + email + device |
| Phone Check | SHA-256 hash lookup | Same phone number reused under new identity |
| Layer 2 | FAISS semantic similarity | Same person with slightly different name/email |

These three checks together ensure that even if a fraudster changes their name slightly, swaps their email, or uses a different phone — at least one layer will catch them. Only a person with a genuinely new identity on a new device with a new phone number passes through cleanly.
