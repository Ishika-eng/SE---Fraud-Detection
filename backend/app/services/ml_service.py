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
INDEX_DIR = "indices"
MAP_PATH = "identity_registry.json"
GOV_ID_HASH_PATH = "gov_id_hashes.json"  # SHA-256 hashes only — no plaintext GovIDs

class MLEngine:
    def __init__(self):
        logger.info(f"Loading SentenceTransformer: {settings.MODEL_NAME}")
        self.model = SentenceTransformer(settings.MODEL_NAME)
        self.embedding_dimension = self.model.get_sentence_embedding_dimension()
        
        # GovID is excluded from FAISS — handled separately via exact hash matching
        self.categories = ["FullName", "EmailAddress"]
        self.indices = {}
        self.vector_store = {}  # Category -> {ID -> Value}
        self.gov_id_hashes: set = set()  # SHA-256 hashes of registered GovIDs

        # Thresholds loaded from settings — admin-configurable at runtime (FR-20, BR-2)
        self.high_threshold: float = settings.HIGH_RISK_THRESHOLD
        self.medium_threshold: float = settings.MEDIUM_RISK_THRESHOLD
        self.bot_cps_threshold: float = settings.BOT_CPS_THRESHOLD

        # Mutex — FAISS is not thread-safe; all index reads/writes must hold this lock
        self._lock = asyncio.Lock()

        if not os.path.exists(INDEX_DIR):
            os.makedirs(INDEX_DIR)

        # Initialize or Load Indices
        self._load_state()

    def _load_state(self):
        for cat in self.categories:
            idx_path = os.path.join(INDEX_DIR, f"{cat}.bin")
            if os.path.exists(idx_path):
                logger.info(f"Loading FAISS index for {cat}...")
                self.indices[cat] = faiss.read_index(idx_path)
            else:
                logger.info(f"Creating fresh FAISS index for {cat}.")
                self.indices[cat] = faiss.index_factory(self.embedding_dimension, "Flat", faiss.METRIC_INNER_PRODUCT)
        
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

    def update_thresholds(self, high: float, medium: float, bot_cps: float = None):
        self.high_threshold = high
        self.medium_threshold = medium
        if bot_cps is not None:
            self.bot_cps_threshold = bot_cps
        logger.info(f"Thresholds updated — HIGH: {high}%, MEDIUM: {medium}%, BOT_CPS: {self.bot_cps_threshold}")

    def _hash_gov_id(self, gov_id: str) -> str:
        """SHA-256 of normalized GovID — GovID plaintext is never stored."""
        return hashlib.sha256(gov_id.strip().upper().encode()).hexdigest()

    def _check_gov_id_exact(self, gov_id: str) -> bool:
        if not gov_id or len(gov_id.strip()) < 3:
            return False
        return self._hash_gov_id(gov_id) in self.gov_id_hashes

    def save_state(self):
        """Persistent save to disk"""
        for cat, idx in self.indices.items():
            idx_path = os.path.join(INDEX_DIR, f"{cat}.bin")
            faiss.write_index(idx, idx_path)

        with open(MAP_PATH, 'w') as f:
            json.dump(self.vector_store, f)

        with open(GOV_ID_HASH_PATH, 'w') as f:
            json.dump(list(self.gov_id_hashes), f)

        logger.info("Categorized AI State persisted to disk.")

    async def evaluate_composite_risk(self, details: dict) -> dict:
        """
        Multi-factor identity check.

        Decision hierarchy:
        1. GovID provided + hash found   → HIGH (definitive duplicate, stop here)
        2. GovID provided + hash NOT found → LOW (Aadhaar is authoritative; different Aadhaar = different person)
        3. GovID not provided            → fallback to name + email similarity
        """
        gov_id_val = details.get("GovID", "").strip()
        gov_id_provided = bool(gov_id_val and len(gov_id_val) >= 3)

        if gov_id_provided:
            if self._check_gov_id_exact(gov_id_val):
                return {
                    "riskLevel": "HIGH",
                    "similarityScore": 100.0,
                    "name_sim": 100.0,
                    "email_sim": 100.0,
                    "message": "CRITICAL: Government ID is already registered. Submission flagged for officer review.",
                    "matchedValue": None
                }
            return {
                "riskLevel": "LOW",
                "similarityScore": 0.0,
                "name_sim": 0.0,
                "email_sim": 0.0,
                "message": "Identity is unique. Aadhaar verified as new.",
                "matchedValue": None
            }

        # No GovID — use name + email similarity
        async with self._lock:
            name_result  = self.compute_similarity(details.get("FullName", ""),      category="FullName")
            email_result = self.compute_similarity(details.get("EmailAddress", ""),  category="EmailAddress")

        name_sim  = name_result.get("similarityScore", 0.0)
        email_sim = email_result.get("similarityScore", 0.0)

        risk_level  = "LOW"
        explanation = "Identity is unique."

        if name_sim > self.high_threshold and email_sim > self.high_threshold:
            risk_level  = "HIGH"
            explanation = f"FLAGGED: Duplicate identity detected (Name {name_sim:.1f}%, Email {email_sim:.1f}%)."
        elif email_sim > self.high_threshold:
            risk_level  = "HIGH"
            explanation = f"SUSPICIOUS: Email already registered ({email_sim:.1f}% match)."
        elif name_sim > self.high_threshold and email_sim > self.medium_threshold:
            risk_level  = "MEDIUM"
            explanation = f"POSSIBLE DUPLICATE: Similar name ({name_sim:.1f}%) and email ({email_sim:.1f}%)."

        return {
            "riskLevel":       risk_level,
            "similarityScore": max(name_sim, email_sim),
            "name_sim":        name_sim,
            "email_sim":       email_sim,
            "message":         explanation,
            "matchedValue":    None
        }

    async def evaluate_risk(self, input_text: str, behavior: dict, category: str = "FullName") -> dict:
        """
        Standard evaluation for real-time monitoring.
        GovID is never similarity-matched during typing — only checked at submission.
        """
        if category == "GovID":
            # Do not run any matching during typing — prevents registry enumeration
            return {"riskLevel": "LOW", "similarityScore": 0.0, "matchedValue": None,
                    "message": "Government ID will be verified on submission."}

        async with self._lock:
            sim_result = self.compute_similarity(input_text, category=category)
        
        risk_level = sim_result["riskLevel"]
        score = sim_result["similarityScore"]
        matched = sim_result["matchedValue"]
        
        cps = behavior.get('cps', 0)
        pastes = behavior.get('pastesCount', 0)

        explanation = sim_result["message"]

        # Behavioral heuristics — CPS threshold is admin-configurable (not hardcoded)
        if cps > self.bot_cps_threshold:
            risk_level = "HIGH"
            explanation = f"BOT DETECTION: Robotic typing speed ({cps} CPS, threshold: {self.bot_cps_threshold})."
        elif pastes > 0 and risk_level != "LOW":
            explanation = f"SUSPICIOUS: Data pasted + {explanation}"

        return {
            "riskLevel": risk_level,
            "similarityScore": score,
            "matchedValue": None,  # Never expose registry values in API response
            "message": explanation
        }

    def compute_similarity(self, input_text: str, category: str = "FullName") -> dict:
        if not input_text or len(input_text.strip()) < 3:
            return {"riskLevel": "LOW", "similarityScore": 0.0, "message": "Input too short", "matchedValue": None}

        if category not in self.indices:
            category = "FullName"

        vector = self.model.encode([input_text])
        faiss.normalize_L2(vector)

        risk_level = "LOW"
        max_similarity = 0.0
        closest_match = None

        index = self.indices[category]
        if index.ntotal > 0:
            distances, indices = index.search(vector, k=1)
            cosine_sim = float(distances[0][0])
            max_similarity = cosine_sim * 100.0
            
            # Map index back to stored value
            cat_store = self.vector_store.get(category, {})
            closest_match = cat_store.get(str(indices[0][0]))

            if max_similarity > self.high_threshold:
                risk_level = "HIGH"
            elif max_similarity > self.medium_threshold:
                risk_level = "MEDIUM"

        return {
            "riskLevel": risk_level,
            "similarityScore": max_similarity,
            "matchedValue": None,  # Internal only — never surfaced to API callers
            "message": f"{category} match: {max_similarity:.1f}%."
        }

    async def add_identity(self, details: dict):
        """Adds a verified LOW-risk identity to indices.
        GovID is stored as SHA-256 hash only — never in FAISS or plaintext registry.
        MEDIUM/HIGH risk submissions are never committed here (caller responsibility).
        """
        async with self._lock:
            # GovID: hash only
            gov_id = details.get("GovID")
            if gov_id and len(gov_id.strip()) >= 3:
                self.gov_id_hashes.add(self._hash_gov_id(gov_id))

            # FullName + EmailAddress: vector similarity index
            for cat in self.categories:
                val = details.get(cat)
                if not val or len(val.strip()) < 3:
                    continue

                vector = self.model.encode([val])
                faiss.normalize_L2(vector)

                index = self.indices[cat]
                current_count = index.ntotal
                index.add(vector)
                self.vector_store[cat][str(current_count)] = val

            self.save_state()
        logger.info("Composite identity committed to indices.")

# Singleton instantiated upon FastAPI boot
ml_engine = MLEngine()
