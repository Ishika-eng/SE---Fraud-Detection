import faiss
import numpy as np
import logging
import os
import re
import json
import hashlib
import asyncio
import time
from sentence_transformers import SentenceTransformer
from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_DIR = "indices"

# State persistence files
MAP_PATH              = "identity_registry.json"
PHONE_HASH_PATH       = "phone_hashes.json"
FINGERPRINT_PATH      = "identity_fingerprints.json"   # Layer 1 — composite fingerprints
BEHAVIORAL_PATH       = "behavioral_profiles.json"     # Layer 3 — per-user behavioral signatures


class MLEngine:
    def __init__(self):
        logger.info(f"Loading SentenceTransformer: {settings.MODEL_NAME}")
        self.model = SentenceTransformer(settings.MODEL_NAME)
        self.embedding_dimension = self.model.get_embedding_dimension()

        # FAISS categories (all registered identities — real-time monitoring):
        #   FullName       — full name, semantic similarity
        #   EmailLocalPart — local part of email (before @), domain stripped + normalised
        self.categories   = ["FullName", "EmailLocalPart"]
        self.indices      = {}
        self.vector_store = {}

        # Layer 2 — separate FAISS index for APPROVED users only (returning-user check)
        # Keeps approved vs pending separate so returning-user queries are precise.
        self.approved_categories   = ["ApprovedFullName", "ApprovedEmailLocalPart"]
        self.approved_indices      = {}
        self.approved_vector_store = {}

        self.phone_hashes: set = set()

        # Layer 1 — composite fingerprints: sha256(phone|email_local|device_id) -> user_id
        self.identity_fingerprints: dict = {}

        # Layer 3 — behavioral profiles keyed by fingerprint hash
        # { fingerprint: { avg_cps, cps_samples, paste_count, sessions } }
        self.behavioral_profiles: dict = {}

        self.high_threshold:    float = settings.HIGH_RISK_THRESHOLD
        self.medium_threshold:  float = settings.MEDIUM_RISK_THRESHOLD
        self.bot_cps_threshold: float = settings.BOT_CPS_THRESHOLD

        # Device velocity — in-memory only, intentionally not persisted
        # Tracks submission timestamps per device within a rolling window
        self.device_submission_times: dict = {}   # device_id -> [timestamp, ...]
        self.device_max_attempts:   int   = settings.DEVICE_MAX_ATTEMPTS
        self.device_window_seconds: float = settings.DEVICE_WINDOW_MINUTES * 60

        self._lock = asyncio.Lock()

        if not os.path.exists(INDEX_DIR):
            os.makedirs(INDEX_DIR)

        self._load_state()

    # ── State persistence ────────────────────────────────────────────────────

    def _load_state(self):
        # Load all-users FAISS indices
        for cat in self.categories:
            idx_path = os.path.join(INDEX_DIR, f"{cat}.bin")
            if os.path.exists(idx_path):
                logger.info(f"Loading FAISS index for {cat}...")
                self.indices[cat] = faiss.read_index(idx_path)
            else:
                logger.info(f"Creating fresh FAISS index for {cat}.")
                self.indices[cat] = faiss.index_factory(
                    self.embedding_dimension, "Flat", faiss.METRIC_INNER_PRODUCT
                )

        # Load approved-only FAISS indices (Layer 2)
        for cat in self.approved_categories:
            idx_path = os.path.join(INDEX_DIR, f"{cat}.bin")
            if os.path.exists(idx_path):
                logger.info(f"Loading approved FAISS index for {cat}...")
                self.approved_indices[cat] = faiss.read_index(idx_path)
            else:
                logger.info(f"Creating fresh approved FAISS index for {cat}.")
                self.approved_indices[cat] = faiss.index_factory(
                    self.embedding_dimension, "Flat", faiss.METRIC_INNER_PRODUCT
                )

        if os.path.exists(MAP_PATH):
            with open(MAP_PATH, 'r') as f:
                data = json.load(f)
                # Backwards compat: old files only had FullName/EmailLocalPart
                self.vector_store          = {k: v for k, v in data.items() if k in self.categories}
                self.approved_vector_store = {k: v for k, v in data.items() if k in self.approved_categories}
        else:
            self.vector_store          = {cat: {} for cat in self.categories}
            self.approved_vector_store = {cat: {} for cat in self.approved_categories}

        if os.path.exists(PHONE_HASH_PATH):
            with open(PHONE_HASH_PATH, 'r') as f:
                self.phone_hashes = set(json.load(f))
        else:
            self.phone_hashes = set()


        # Layer 1
        if os.path.exists(FINGERPRINT_PATH):
            with open(FINGERPRINT_PATH, 'r') as f:
                self.identity_fingerprints = json.load(f)
        else:
            self.identity_fingerprints = {}

        # Layer 3
        if os.path.exists(BEHAVIORAL_PATH):
            with open(BEHAVIORAL_PATH, 'r') as f:
                self.behavioral_profiles = json.load(f)
        else:
            self.behavioral_profiles = {}

    def save_state(self):
        for cat, idx in self.indices.items():
            faiss.write_index(idx, os.path.join(INDEX_DIR, f"{cat}.bin"))
        for cat, idx in self.approved_indices.items():
            faiss.write_index(idx, os.path.join(INDEX_DIR, f"{cat}.bin"))

        combined = {**self.vector_store, **self.approved_vector_store}
        with open(MAP_PATH, 'w') as f:
            json.dump(combined, f)

        with open(PHONE_HASH_PATH, 'w') as f:
            json.dump(list(self.phone_hashes), f)


        with open(FINGERPRINT_PATH, 'w') as f:
            json.dump(self.identity_fingerprints, f)

        with open(BEHAVIORAL_PATH, 'w') as f:
            json.dump(self.behavioral_profiles, f)

        logger.info("ML state persisted to disk.")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def update_thresholds(
        self,
        high:              float,
        medium:            float,
        bot_cps:           float = None,
        device_max:        int   = None,
        device_window_min: int   = None,
    ):
        self.high_threshold   = high
        self.medium_threshold = medium
        if bot_cps is not None:
            self.bot_cps_threshold = bot_cps
        if device_max is not None:
            self.device_max_attempts = device_max
        if device_window_min is not None:
            self.device_window_seconds = device_window_min * 60
        logger.info(
            f"Thresholds updated — HIGH:{high}% MEDIUM:{medium}% "
            f"BOT_CPS:{self.bot_cps_threshold} "
            f"DEVICE:{self.device_max_attempts} attempts/{int(self.device_window_seconds/60)}min"
        )

    def check_device_velocity(self, device_id: str) -> dict:
        """
        Record a submission attempt for this device and check against the velocity limit.
        Uses a rolling time window — old attempts outside the window are pruned.
        Returns {exceeded, count, limit, window_minutes}.
        Session-only: device_submission_times resets on server restart.
        """
        normalized = self._normalize_device_id(device_id)
        if not normalized:
            return {"exceeded": False, "count": 0, "limit": self.device_max_attempts,
                    "window_minutes": int(self.device_window_seconds / 60)}

        now          = time.time()
        window_start = now - self.device_window_seconds

        # Prune old timestamps and add current attempt
        times = [t for t in self.device_submission_times.get(normalized, []) if t > window_start]
        times.append(now)
        self.device_submission_times[normalized] = times

        count = len(times)
        return {
            "exceeded":       count > self.device_max_attempts,
            "count":          count,
            "limit":          self.device_max_attempts,
            "window_minutes": int(self.device_window_seconds / 60),
        }

    def _hash_value(self, value: str) -> str:
        """Deterministic SHA-256 hash for private storage."""
        return hashlib.sha256(value.strip().upper().encode()).hexdigest()

    def _normalize_phone(self, phone: str) -> str:
        """Strip non-digits and keep last 10 digits for normalization."""
        digits = re.sub(r'\D', '', phone)
        return digits[-10:] if len(digits) >= 10 else digits

    def phone_hash(self, phone: str) -> str:
        """Public helper: normalize phone and return its SHA-256 hash."""
        return self._hash_value(self._normalize_phone(phone))

    def _check_phone_exact(self, phone: str) -> bool:
        if not phone or len(phone.strip()) < 5:
            return False
        normalized = self._normalize_phone(phone)
        return self._hash_value(normalized) in self.phone_hashes

    def _email_to_local(self, email: str) -> str:
        """
        Extract the local part (before @) and normalise for semantic comparison.
        e.g. "pranav.mahajan@gmail.com" -> "pranav mahajan"
        """
        local = email.strip().lower().split('@')[0] if '@' in email else email.strip().lower()
        normalised = re.sub(r'[._+\-]+', ' ', local).strip()
        return normalised if normalised else local

    # ── Layer 1: Composite identity fingerprint ──────────────────────────────

    # Sentinel values that mean "no device signal collected" — all normalise to ""
    _DEVICE_ID_EMPTY_SENTINELS = {"", "unknown", "undefined", "null", "none"}

    def _normalize_device_id(self, device_id: str) -> str:
        """
        Collapse all 'no signal' sentinels to the empty string so that a user
        submitting via the extension (real DJB2 hash), via the test-form before
        the fingerprinting fix (empty string), or via a canvas-blocked browser
        ('unknown') all resolve to the SAME canonical component when no real
        device signal is available.

        A real device_id (8-char hex like 'a1b2c3d4') is lowercased and kept as-is.
        """
        if not device_id:
            return ""
        cleaned = device_id.strip().lower()
        return "" if cleaned in self._DEVICE_ID_EMPTY_SENTINELS else cleaned

    def generate_identity_fingerprint(self, phone: str, email: str, device_id: str) -> str:
        """
        Deterministic fingerprint from three stable identity signals:
        phone (normalised) + email local-part + device_id -> SHA-256.
        Device ID is the browser fingerprint sent by the extension on submit.

        device_id is normalised via _normalize_device_id() so that missing /
        blocked / sentinel values all produce the same fingerprint, preventing
        the same physical user from generating different fingerprints depending
        on how they accessed the form.
        """
        phone_norm  = self._normalize_phone(phone)      if phone     else ""
        email_local = self._email_to_local(email)       if email     else ""
        device_norm = self._normalize_device_id(device_id)
        canonical   = f"{phone_norm}|{email_local}|{device_norm}"
        return hashlib.sha256(canonical.encode()).hexdigest()

    def check_fingerprint(self, fingerprint: str) -> dict:
        """Exact match check. Returns matched=True + user_id if found."""
        if fingerprint in self.identity_fingerprints:
            return {"matched": True, "user_id": self.identity_fingerprints[fingerprint]}
        return {"matched": False, "user_id": None}

    def store_fingerprint(self, fingerprint: str, user_id: str):
        """Persist fingerprint -> user_id after approval."""
        self.identity_fingerprints[fingerprint] = user_id

    # ── Layer 2: Approved-user semantic similarity ───────────────────────────

    def check_approved_user_similarity(self, name: str = "", email: str = "") -> dict:
        """
        Query ONLY the approved-user FAISS index (not the general pending registry).
        Catches returning users who change name slightly or swap email domain.
        """
        name_sim  = 0.0
        email_sim = 0.0

        if name and len(name.strip()) >= 2:
            name_sim = self._query_approved_index(name, "ApprovedFullName")

        if email:
            local = self._email_to_local(email)
            if len(local) >= 2:
                email_sim = self._query_approved_index(local, "ApprovedEmailLocalPart")

        return {
            "approved_name_sim":  name_sim,
            "approved_email_sim": email_sim,
            "max_approved_sim":   max(name_sim, email_sim),
        }

    def _query_approved_index(self, text: str, category: str) -> float:
        """Inner product similarity against approved-user index (0-100)."""
        index = self.approved_indices.get(category)
        if index is None or index.ntotal == 0:
            return 0.0
        vector = self.model.encode([text])
        faiss.normalize_L2(vector)
        distances, _ = index.search(vector, k=1)
        return float(distances[0][0]) * 100.0

    def _add_to_approved_index(self, text: str, category: str, user_id: str = ""):
        """Add to the approved-only FAISS index."""
        vector = self.model.encode([text])
        faiss.normalize_L2(vector)
        idx = self.approved_indices[category]
        pos = idx.ntotal
        idx.add(vector)
        self.approved_vector_store.setdefault(category, {})[str(pos)] = text

    # ── Layer 3: Behavioral profile ──────────────────────────────────────────

    def update_behavioral_profile(self, fingerprint: str, cps: float, paste_count: int):
        """
        Rolling behavioral profile per approved user.
        Keeps a sliding window of up to 10 CPS samples for a stable average.
        """
        profile = self.behavioral_profiles.get(fingerprint, {
            "cps_samples": [],
            "avg_cps":     0.0,
            "paste_count": 0,
            "sessions":    0,
        })

        samples = profile.get("cps_samples", [])
        if cps > 0:
            samples.append(round(cps, 2))
            samples = samples[-10:]  # sliding window

        profile["cps_samples"]  = samples
        profile["avg_cps"]      = round(sum(samples) / len(samples), 2) if samples else 0.0
        profile["paste_count"]  = profile.get("paste_count", 0) + paste_count
        profile["sessions"]     = profile.get("sessions", 0) + 1

        self.behavioral_profiles[fingerprint] = profile

    def compare_behavioral_signature(self, fingerprint: str, new_cps: float, new_paste: bool) -> dict:
        """
        Compare new-submission behavior against stored profile.
        Returns match_score (0.0-1.0). None if < 2 sessions in profile.
        """
        profile = self.behavioral_profiles.get(fingerprint)
        if not profile or profile.get("sessions", 0) < 2:
            return {"behavioral_match_score": None, "note": "No prior behavioral profile."}

        avg_cps  = profile.get("avg_cps", 0.0)
        cps_diff = abs(new_cps - avg_cps)

        # Score degrades linearly: 0 diff -> 1.0, >=10 diff -> 0.0
        match_score = max(0.0, round(1.0 - cps_diff / 10.0, 3))

        # Paste mismatch: rarely pasted before but pasting now
        paste_ratio    = profile.get("paste_count", 0) / max(profile.get("sessions", 1), 1)
        paste_mismatch = new_paste and paste_ratio < 0.2
        if paste_mismatch:
            match_score = max(0.0, match_score - 0.2)

        note = (
            f"CPS diff {cps_diff:.1f} vs avg {avg_cps:.1f} "
            f"({'paste mismatch' if paste_mismatch else 'paste consistent'})"
        )
        return {"behavioral_match_score": match_score, "note": note}

    # ── FAISS similarity (all-users, for real-time monitoring) ───────────────

    def compute_similarity(self, input_text: str, category: str = "FullName") -> dict:
        if not input_text or len(input_text.strip()) < 2:
            return {"riskLevel": "LOW", "similarityScore": 0.0,
                    "message": "Input too short", "matchedValue": None}

        if category not in self.indices:
            category = "FullName"

        vector = self.model.encode([input_text])
        faiss.normalize_L2(vector)

        risk_level     = "LOW"
        max_similarity = 0.0

        index = self.indices[category]
        if index.ntotal > 0:
            distances, _ = index.search(vector, k=1)
            max_similarity = float(distances[0][0]) * 100.0

            if max_similarity > self.high_threshold:
                risk_level = "HIGH"
            elif max_similarity > self.medium_threshold:
                risk_level = "MEDIUM"

        return {
            "riskLevel":       risk_level,
            "similarityScore": max_similarity,
            "matchedValue":    None,
            "message":         f"{category} similarity: {max_similarity:.1f}%.",
        }

    # ── Composite risk (on submit) ───────────────────────────────────────────

    async def evaluate_composite_risk(self, details: dict, new_ip: str = "") -> dict:
        """
        Full submission-time risk evaluation. Priority order:

          1. Layer 1 — composite fingerprint exact match  (highest priority)
          2. Phone exact match
          3. Layer 2 — approved-user semantic similarity  (returning-user detection)
          4. General registry semantic similarity         (duplicate new application)
        """
        phone_val = details.get("PhoneNumber", "").strip()
        email_val = details.get("EmailAddress", "").strip()
        name_val  = details.get("FullName",     "").strip()
        device_id = details.get("device_id",    "").strip()

        # ── Layer 1: Composite fingerprint ───────────────────────────────────
        fingerprint = ""
        if phone_val or email_val:
            fingerprint = self.generate_identity_fingerprint(phone_val, email_val, device_id)
            fp_result   = self.check_fingerprint(fingerprint)
            if fp_result["matched"]:
                return {
                    "riskLevel":         "HIGH",
                    "similarityScore":   100.0,
                    "name_sim":          100.0,
                    "email_sim":         100.0,
                    "message":           "RETURNING USER: Exact identity fingerprint already registered.",
                    "matchedValue":      None,
                    "fingerprint":       fingerprint,
                    "fingerprint_match": True,
                    "approved_name_sim":  100.0,
                    "approved_email_sim": 100.0,
                }

        # ── Device velocity check ─────────────────────────────────────────────
        velocity = self.check_device_velocity(device_id) if device_id else {"exceeded": False}
        if velocity["exceeded"]:
            return {
                "riskLevel":         "HIGH",
                "similarityScore":   100.0,
                "name_sim":          0.0,
                "email_sim":         0.0,
                "message":           (
                    f"VELOCITY LIMIT: {velocity['count']} submissions from this device "
                    f"in the last {velocity['window_minutes']} minutes "
                    f"(limit: {velocity['limit']})."
                ),
                "matchedValue":      None,
                "fingerprint":       fingerprint,
                "fingerprint_match": False,
                "velocity_exceeded": True,
                "approved_name_sim":  0.0,
                "approved_email_sim": 0.0,
            }

        # ── Phone exact match ─────────────────────────────────────────────────
        if phone_val and len(phone_val) >= 5:
            if self._check_phone_exact(phone_val):
                return {
                    "riskLevel":         "HIGH",
                    "similarityScore":   100.0,
                    "name_sim":          0.0,
                    "email_sim":         0.0,
                    "message":           "Phone number already registered to another account.",
                    "matchedValue":      None,
                    "fingerprint":       fingerprint,
                    "fingerprint_match": False,
                    "phone_match":       True,
                    "approved_name_sim":  0.0,
                    "approved_email_sim": 0.0,
                }

        # ── Layer 2: Approved-user semantic check ────────────────────────────
        async with self._lock:
            approved_result = self.check_approved_user_similarity(name=name_val, email=email_val)

        approved_name_sim  = approved_result["approved_name_sim"]
        approved_email_sim = approved_result["approved_email_sim"]

        if approved_name_sim > self.high_threshold and approved_email_sim > self.high_threshold:
            return {
                "riskLevel":         "HIGH",
                "similarityScore":   max(approved_name_sim, approved_email_sim),
                "name_sim":          approved_name_sim,
                "email_sim":         approved_email_sim,
                "message":           f"RETURNING USER: Name {approved_name_sim:.1f}% + email {approved_email_sim:.1f}% match approved registry.",
                "matchedValue":      None,
                "fingerprint":       fingerprint,
                "fingerprint_match": False,
                "approved_name_sim":  approved_name_sim,
                "approved_email_sim": approved_email_sim,
            }
        if approved_email_sim > self.high_threshold:
            return {
                "riskLevel":         "HIGH",
                "similarityScore":   approved_email_sim,
                "name_sim":          approved_name_sim,
                "email_sim":         approved_email_sim,
                "message":           f"RETURNING USER: Email local-part already in approved registry ({approved_email_sim:.1f}%).",
                "matchedValue":      None,
                "fingerprint":       fingerprint,
                "fingerprint_match": False,
                "approved_name_sim":  approved_name_sim,
                "approved_email_sim": approved_email_sim,
            }

        # ── General registry semantic check ──────────────────────────────────
        email_local = self._email_to_local(email_val) if email_val else ""

        async with self._lock:
            name_result  = self.compute_similarity(name_val,    category="FullName")
            email_result = self.compute_similarity(email_local, category="EmailLocalPart") if email_local else \
                           {"riskLevel": "LOW", "similarityScore": 0.0, "matchedValue": None, "message": ""}

        name_sim  = name_result.get("similarityScore",  0.0)
        email_sim = email_result.get("similarityScore", 0.0)

        risk_level  = "LOW"
        explanation = "Identity is unique."

        if name_sim > self.high_threshold and email_sim > self.high_threshold:
            risk_level  = "HIGH"
            explanation = f"FLAGGED: Name {name_sim:.1f}% + email {email_sim:.1f}% match."
        elif email_sim > self.high_threshold:
            risk_level  = "HIGH"
            explanation = f"SUSPICIOUS: Email already registered ({email_sim:.1f}% local-part match)."
        elif approved_name_sim > self.medium_threshold or approved_email_sim > self.medium_threshold:
            risk_level  = "MEDIUM"
            explanation = f"POSSIBLE RETURNING USER: Approved registry — name {approved_name_sim:.1f}%, email {approved_email_sim:.1f}%."
        elif name_sim > self.medium_threshold or email_sim > self.medium_threshold:
            risk_level  = "MEDIUM"
            explanation = f"POSSIBLE DUPLICATE: Name {name_sim:.1f}%, Email {email_sim:.1f}%."

        return {
            "riskLevel":         risk_level,
            "similarityScore":   max(name_sim, email_sim),
            "name_sim":          name_sim,
            "email_sim":         email_sim,
            "message":           explanation,
            "matchedValue":      None,
            "fingerprint":       fingerprint,
            "fingerprint_match": False,
            "approved_name_sim":  approved_name_sim,
            "approved_email_sim": approved_email_sim,
        }

    # ── Real-time monitoring (on keyup) ─────────────────────────────────────

    async def evaluate_risk(self, input_text: str, behavior: dict, category: str = "FullName") -> dict:
        """Real-time field monitoring. PhoneNumber checked against hash registry as user types."""
        if category == "PhoneNumber":
            normalized = self._normalize_phone(input_text) if input_text else ""
            if len(normalized) >= 10:
                if self._check_phone_exact(input_text):
                    return {
                        "riskLevel":       "HIGH",
                        "similarityScore": 100.0,
                        "matchedValue":    None,
                        "message":         "Phone number already registered to an existing account.",
                    }
            return {"riskLevel": "LOW", "similarityScore": 0.0,
                    "matchedValue": None, "message": ""}

        if category == "EmailAddress":
            local = self._email_to_local(input_text)
            if len(local) < 3:
                return {"riskLevel": "LOW", "similarityScore": 0.0,
                        "matchedValue": None, "message": ""}
            async with self._lock:
                sim_result = self.compute_similarity(local, category="EmailLocalPart")
            return {
                "riskLevel":       sim_result["riskLevel"],
                "similarityScore": sim_result["similarityScore"],
                "matchedValue":    None,
                "message":         f"EmailAddress match: {sim_result['similarityScore']:.1f}%."
                                   if sim_result["similarityScore"] > 0 else "",
            }

        # FullName
        async with self._lock:
            sim_result = self.compute_similarity(input_text, category=category)

        risk_level  = sim_result["riskLevel"]
        score       = sim_result["similarityScore"]
        explanation = sim_result["message"]
        cps         = behavior.get('cps', 0)
        pastes      = behavior.get('pastesCount', 0)

        if cps > self.bot_cps_threshold:
            risk_level  = "HIGH"
            explanation = f"BOT DETECTION: {cps} CPS (threshold: {self.bot_cps_threshold})."
        elif pastes > 0 and risk_level != "LOW":
            explanation = f"SUSPICIOUS: Pasted + {explanation}"

        return {
            "riskLevel":       risk_level,
            "similarityScore": score,
            "matchedValue":    None,
            "message":         explanation,
        }

    # ── Add identity to registry ─────────────────────────────────────────────

    async def add_identity(
        self,
        details:              dict,
        platform:             str  = "web",
        timestamp:            str  = "",
        ip:                   str  = "",
        user_id:              str  = "",
        behavior:             dict = None,
        precomputed_fingerprint: str = "",   # pass ml_result["fingerprint"] to avoid recomputing
    ):
        """
        Commits a verified/approved identity across all 4 layers:
          Layer 1 — composite fingerprint stored
          Layer 2 — added to approved-only FAISS index
          Layer 3 — behavioral profile updated
          (Layer 4 benefit claims are handled in analyze.py)
        """
        async with self._lock:
            phone     = details.get("PhoneNumber",  "").strip()
            email_raw = details.get("EmailAddress", "").strip()
            name      = details.get("FullName",     "").strip()
            device_id = details.get("device_id",    "").strip()

            # Phone hash
            if phone and len(phone) >= 5:
                normalized = self._normalize_phone(phone)
                self.phone_hashes.add(self._hash_value(normalized))


            # General registry (existing behaviour)
            if name and len(name) >= 3:
                self._add_to_index(name, "FullName", platform=platform, timestamp=timestamp, ip=ip)
            if email_raw:
                local = self._email_to_local(email_raw)
                if local and len(local) >= 2:
                    self._add_to_index(local, "EmailLocalPart", platform=platform, timestamp=timestamp, ip=ip)

            # Layer 1: Composite fingerprint — reuse pre-computed value from evaluate_composite_risk
            # to guarantee the stored fingerprint matches exactly what was checked.
            if (phone or email_raw) and user_id:
                fp = precomputed_fingerprint if precomputed_fingerprint else \
                     self.generate_identity_fingerprint(phone, email_raw, device_id)
                self.store_fingerprint(fp, user_id)

            # Layer 2: Approved-only index
            if name and len(name) >= 3:
                self._add_to_approved_index(name, "ApprovedFullName", user_id=user_id)
            if email_raw:
                local = self._email_to_local(email_raw)
                if local and len(local) >= 2:
                    self._add_to_approved_index(local, "ApprovedEmailLocalPart", user_id=user_id)

            # Layer 3: Behavioral profile — key by same fingerprint used in Layer 1
            if behavior and (phone or email_raw):
                fp_key      = precomputed_fingerprint if precomputed_fingerprint else \
                              self.generate_identity_fingerprint(phone, email_raw, device_id)
                cps         = float(behavior.get("cps", 0))
                paste_count = int(behavior.get("pastesCount", 0))
                self.update_behavioral_profile(fp_key, cps, paste_count)

            self.save_state()
        logger.info("Identity committed to registry (all layers).")

    def _add_to_index(self, text: str, category: str, platform: str = "", timestamp: str = "", ip: str = ""):
        vector = self.model.encode([text])
        faiss.normalize_L2(vector)
        idx = self.indices[category]
        pos = idx.ntotal
        idx.add(vector)
        self.vector_store.setdefault(category, {})[str(pos)] = text


# Singleton
ml_engine = MLEngine()
