import faiss
import numpy as np
import logging
import os
import json
import hashlib
import asyncio
from sentence_transformers import SentenceTransformer
from app.core.config import settings

logger = logging.getLogger(__name__)

# Paths for persistence
INDEX_DIR       = "indices"
MAP_PATH        = "identity_registry.json"
GOV_ID_HASH_PATH = "gov_id_hashes.json"
EMAIL_HASH_PATH  = "email_hashes.json"   # SHA-256 hashes — email is exact-matched, never fuzzy


class MLEngine:
    def __init__(self):
        logger.info(f"Loading SentenceTransformer: {settings.MODEL_NAME}")
        self.model = SentenceTransformer(settings.MODEL_NAME)
        self.embedding_dimension = self.model.get_sentence_embedding_dimension()

        # FAISS is ONLY used for FullName — semantic fuzzy matching
        # Email and GovID are structured identifiers → exact SHA-256 hash matching
        self.categories  = ["FullName"]
        self.indices     = {}
        self.vector_store = {}

        self.gov_id_hashes: set = set()
        self.email_hashes:  set = set()

        # Thresholds — admin-configurable at runtime
        self.high_threshold:   float = settings.HIGH_RISK_THRESHOLD
        self.medium_threshold: float = settings.MEDIUM_RISK_THRESHOLD
        self.bot_cps_threshold: float = settings.BOT_CPS_THRESHOLD

        # Mutex — FAISS is not thread-safe
        self._lock = asyncio.Lock()

        if not os.path.exists(INDEX_DIR):
            os.makedirs(INDEX_DIR)

        self._load_state()

    def _load_state(self):
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

        if os.path.exists(MAP_PATH):
            with open(MAP_PATH, 'r') as f:
                self.vector_store = json.load(f)
        else:
            self.vector_store = {cat: {} for cat in self.categories}

        if os.path.exists(GOV_ID_HASH_PATH):
            with open(GOV_ID_HASH_PATH, 'r') as f:
                self.gov_id_hashes = set(json.load(f))
        else:
            self.gov_id_hashes = set()

        if os.path.exists(EMAIL_HASH_PATH):
            with open(EMAIL_HASH_PATH, 'r') as f:
                self.email_hashes = set(json.load(f))
        else:
            self.email_hashes = set()

    def update_thresholds(self, high: float, medium: float, bot_cps: float = None):
        self.high_threshold   = high
        self.medium_threshold = medium
        if bot_cps is not None:
            self.bot_cps_threshold = bot_cps
        logger.info(f"Thresholds updated — HIGH: {high}%, MEDIUM: {medium}%, BOT_CPS: {self.bot_cps_threshold}")

    # ── Hashing helpers ──────────────────────────────────────────────────────

    def _hash_gov_id(self, gov_id: str) -> str:
        return hashlib.sha256(gov_id.strip().upper().encode()).hexdigest()

    def _hash_email(self, email: str) -> str:
        """SHA-256 of lowercase-normalised email."""
        return hashlib.sha256(email.strip().lower().encode()).hexdigest()

    def _check_gov_id_exact(self, gov_id: str) -> bool:
        if not gov_id or len(gov_id.strip()) < 3:
            return False
        return self._hash_gov_id(gov_id) in self.gov_id_hashes

    def _check_email_exact(self, email: str) -> bool:
        if not email or len(email.strip()) < 5:
            return False
        return self._hash_email(email) in self.email_hashes

    # ── Persistence ──────────────────────────────────────────────────────────

    def save_state(self):
        for cat, idx in self.indices.items():
            faiss.write_index(idx, os.path.join(INDEX_DIR, f"{cat}.bin"))

        with open(MAP_PATH, 'w') as f:
            json.dump(self.vector_store, f)
        with open(GOV_ID_HASH_PATH, 'w') as f:
            json.dump(list(self.gov_id_hashes), f)
        with open(EMAIL_HASH_PATH, 'w') as f:
            json.dump(list(self.email_hashes), f)

        logger.info("ML state persisted to disk.")

    # ── Composite risk (on submit) ───────────────────────────────────────────

    async def evaluate_composite_risk(self, details: dict) -> dict:
        """
        Multi-factor check at submission time.

        Email   → exact SHA-256 hash match (not fuzzy — email is a unique identifier)
        GovID   → exact SHA-256 hash match
        FullName → semantic vector similarity via FAISS

        Decision hierarchy:
        1. Exact email match  → HIGH (definitive duplicate)
        2. Exact GovID match  → HIGH (definitive duplicate)
        3. GovID provided but not found → LOW (authoritative, skip name check)
        4. Name similarity only → MEDIUM if suspicious, LOW if safe
        """
        email_val = details.get("EmailAddress", "").strip()
        gov_id_val = details.get("GovID", "").strip()

        # 1. Exact email match — most reliable signal across all 4 platforms
        if email_val and self._check_email_exact(email_val):
            return {
                "riskLevel":       "HIGH",
                "similarityScore": 100.0,
                "name_sim":        0.0,
                "email_sim":       100.0,
                "message":         "DUPLICATE: This email address is already registered.",
                "matchedValue":    None,
            }

        # 2. Exact GovID match
        if gov_id_val and self._check_gov_id_exact(gov_id_val):
            return {
                "riskLevel":       "HIGH",
                "similarityScore": 100.0,
                "name_sim":        100.0,
                "email_sim":       0.0,
                "message":         "CRITICAL: Government ID is already registered.",
                "matchedValue":    None,
            }

        # 3. GovID provided but not found — different person, skip name check
        if gov_id_val and len(gov_id_val) >= 3:
            return {
                "riskLevel":       "LOW",
                "similarityScore": 0.0,
                "name_sim":        0.0,
                "email_sim":       0.0,
                "message":         "Identity is unique. Verified as new.",
                "matchedValue":    None,
            }

        # 4. Name similarity (FAISS) — fallback when no exact identifiers match
        async with self._lock:
            name_result = self.compute_similarity(details.get("FullName", ""), category="FullName")

        name_sim   = name_result.get("similarityScore", 0.0)
        risk_level = "LOW"
        explanation = "Identity is unique."

        if name_sim > self.high_threshold:
            risk_level  = "MEDIUM"
            explanation = f"SIMILAR NAME: Name matches {name_sim:.1f}% to an existing account. Email is new — possible coincidence or different person."
        elif name_sim > self.medium_threshold:
            risk_level  = "LOW"
            explanation = f"Weak name similarity ({name_sim:.1f}%). Email is new. Treated as new identity."

        return {
            "riskLevel":       risk_level,
            "similarityScore": name_sim,
            "name_sim":        name_sim,
            "email_sim":       0.0,
            "message":         explanation,
            "matchedValue":    None,
        }

    # ── Real-time monitoring (on keyup) ─────────────────────────────────────

    async def evaluate_risk(self, input_text: str, behavior: dict, category: str = "FullName") -> dict:
        """
        Real-time per-field monitoring.
        - EmailAddress: exact hash check (no fuzzy — prevents @gmail.com false positives)
        - GovID: not checked during typing (prevents registry enumeration)
        - FullName: semantic FAISS similarity
        """
        if category == "GovID":
            return {
                "riskLevel": "LOW", "similarityScore": 0.0,
                "matchedValue": None,
                "message": "Government ID will be verified on submission."
            }

        if category == "EmailAddress":
            if self._check_email_exact(input_text):
                return {
                    "riskLevel":       "HIGH",
                    "similarityScore": 100.0,
                    "matchedValue":    None,
                    "message":         "Email already registered on this platform.",
                }
            return {
                "riskLevel": "LOW", "similarityScore": 0.0,
                "matchedValue": None, "message": "Email is available."
            }

        # FullName — semantic similarity
        async with self._lock:
            sim_result = self.compute_similarity(input_text, category=category)

        risk_level  = sim_result["riskLevel"]
        score       = sim_result["similarityScore"]
        explanation = sim_result["message"]
        cps         = behavior.get('cps', 0)
        pastes      = behavior.get('pastesCount', 0)

        if cps > self.bot_cps_threshold:
            risk_level  = "HIGH"
            explanation = f"BOT DETECTION: Robotic typing speed ({cps} CPS, threshold: {self.bot_cps_threshold})."
        elif pastes > 0 and risk_level != "LOW":
            explanation = f"SUSPICIOUS: Data pasted + {explanation}"

        return {
            "riskLevel":       risk_level,
            "similarityScore": score,
            "matchedValue":    None,
            "message":         explanation,
        }

    # ── FAISS similarity (FullName only) ─────────────────────────────────────

    def compute_similarity(self, input_text: str, category: str = "FullName") -> dict:
        if not input_text or len(input_text.strip()) < 3:
            return {"riskLevel": "LOW", "similarityScore": 0.0, "message": "Input too short", "matchedValue": None}

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

    # ── Add identity to registry ─────────────────────────────────────────────

    async def add_identity(self, details: dict):
        """
        Commits a verified LOW-risk identity to the registry.
        - Email  → SHA-256 hash (exact match store)
        - GovID  → SHA-256 hash (exact match store)
        - FullName → FAISS vector index (semantic similarity)
        """
        async with self._lock:
            gov_id = details.get("GovID", "").strip()
            if gov_id and len(gov_id) >= 3:
                self.gov_id_hashes.add(self._hash_gov_id(gov_id))

            email = details.get("EmailAddress", "").strip()
            if email and len(email) >= 5:
                self.email_hashes.add(self._hash_email(email))

            name = details.get("FullName", "").strip()
            if name and len(name) >= 3:
                vector = self.model.encode([name])
                faiss.normalize_L2(vector)
                idx = self.indices["FullName"]
                current_count = idx.ntotal
                idx.add(vector)
                self.vector_store.setdefault("FullName", {})[str(current_count)] = name

            self.save_state()
        logger.info("Identity committed to registry.")


# Singleton instantiated upon FastAPI boot
ml_engine = MLEngine()
