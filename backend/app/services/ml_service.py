import faiss
import numpy as np
import logging
import os
import re
import json
import hashlib
import asyncio
from sentence_transformers import SentenceTransformer
from app.core.config import settings

logger = logging.getLogger(__name__)

INDEX_DIR        = "indices"
MAP_PATH         = "identity_registry.json"
GOV_ID_HASH_PATH = "gov_id_hashes.json"


class MLEngine:
    def __init__(self):
        logger.info(f"Loading SentenceTransformer: {settings.MODEL_NAME}")
        self.model = SentenceTransformer(settings.MODEL_NAME)
        self.embedding_dimension = self.model.get_sentence_embedding_dimension()

        # FAISS categories:
        #   FullName       — full name, semantic similarity
        #   EmailLocalPart — local part of email (before @), domain stripped + normalised
        #                    so "pranav.mahajan@gmail.com" → "pranav mahajan"
        #                    Prevents @gmail.com inflating similarity scores
        self.categories   = ["FullName", "EmailLocalPart"]
        self.indices      = {}
        self.vector_store = {}

        self.gov_id_hashes: set = set()

        self.high_threshold:    float = settings.HIGH_RISK_THRESHOLD
        self.medium_threshold:  float = settings.MEDIUM_RISK_THRESHOLD
        self.bot_cps_threshold: float = settings.BOT_CPS_THRESHOLD

        self._lock = asyncio.Lock()

        if not os.path.exists(INDEX_DIR):
            os.makedirs(INDEX_DIR)

        self._load_state()

    # ── State persistence ────────────────────────────────────────────────────

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

    def save_state(self):
        for cat, idx in self.indices.items():
            faiss.write_index(idx, os.path.join(INDEX_DIR, f"{cat}.bin"))
        with open(MAP_PATH, 'w') as f:
            json.dump(self.vector_store, f)
        with open(GOV_ID_HASH_PATH, 'w') as f:
            json.dump(list(self.gov_id_hashes), f)
        logger.info("ML state persisted to disk.")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def update_thresholds(self, high: float, medium: float, bot_cps: float = None):
        self.high_threshold   = high
        self.medium_threshold = medium
        if bot_cps is not None:
            self.bot_cps_threshold = bot_cps
        logger.info(f"Thresholds updated — HIGH:{high}% MEDIUM:{medium}% BOT_CPS:{self.bot_cps_threshold}")

    def _hash_gov_id(self, gov_id: str) -> str:
        return hashlib.sha256(gov_id.strip().upper().encode()).hexdigest()

    def _check_gov_id_exact(self, gov_id: str) -> bool:
        if not gov_id or len(gov_id.strip()) < 3:
            return False
        return self._hash_gov_id(gov_id) in self.gov_id_hashes

    def _email_to_local(self, email: str) -> str:
        """
        Extract the local part (before @) and normalise for semantic comparison.
        Dots, underscores, hyphens, plus signs → spaces so the sentence
        transformer gets actual words instead of punctuation noise.
        e.g. "pranav.mahajan@gmail.com" → "pranav mahajan"
             "p_sharma+test@yahoo.in"  → "p sharma test"
        """
        local = email.strip().lower().split('@')[0] if '@' in email else email.strip().lower()
        normalised = re.sub(r'[._+\-]+', ' ', local).strip()
        return normalised if normalised else local

    # ── FAISS similarity ─────────────────────────────────────────────────────

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

    async def evaluate_composite_risk(self, details: dict) -> dict:
        """
        Checks at submission time.
        Email domain is IGNORED — only the local part (before @) is compared.
        Both name_sim and email_sim are real similarity scores (0–100).
        """
        gov_id_val = details.get("GovID", "").strip()
        if gov_id_val and len(gov_id_val) >= 3:
            if self._check_gov_id_exact(gov_id_val):
                return {
                    "riskLevel": "HIGH", "similarityScore": 100.0,
                    "name_sim": 100.0,  "email_sim": 100.0,
                    "message": "CRITICAL: Government ID already registered.",
                    "matchedValue": None,
                }
            return {
                "riskLevel": "LOW", "similarityScore": 0.0,
                "name_sim": 0.0, "email_sim": 0.0,
                "message": "Identity verified as new via GovID.",
                "matchedValue": None,
            }

        email_raw   = details.get("EmailAddress", "")
        email_local = self._email_to_local(email_raw) if email_raw else ""
        name_text   = details.get("FullName", "")

        async with self._lock:
            name_result  = self.compute_similarity(name_text,   category="FullName")
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
        elif name_sim > self.medium_threshold or email_sim > self.medium_threshold:
            risk_level  = "MEDIUM"
            explanation = f"POSSIBLE DUPLICATE: Name {name_sim:.1f}%, Email {email_sim:.1f}%."

        return {
            "riskLevel":       risk_level,
            "similarityScore": max(name_sim, email_sim),
            "name_sim":        name_sim,
            "email_sim":       email_sim,
            "message":         explanation,
            "matchedValue":    None,
        }

    # ── Real-time monitoring (on keyup) ─────────────────────────────────────

    async def evaluate_risk(self, input_text: str, behavior: dict, category: str = "FullName") -> dict:
        """
        Real-time field monitoring.
        EmailAddress: domain stripped before comparison — no @gmail.com noise.
        GovID: not matched during typing.
        """
        if category == "GovID":
            return {"riskLevel": "LOW", "similarityScore": 0.0,
                    "matchedValue": None, "message": "GovID verified on submission."}

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

    async def add_identity(self, details: dict):
        """
        Commits a verified identity.
        Email domain is stripped — only local part stored in FAISS.
        """
        async with self._lock:
            gov_id = details.get("GovID", "").strip()
            if gov_id and len(gov_id) >= 3:
                self.gov_id_hashes.add(self._hash_gov_id(gov_id))

            name = details.get("FullName", "").strip()
            if name and len(name) >= 3:
                self._add_to_index(name, "FullName")

            email_raw = details.get("EmailAddress", "")
            if email_raw:
                local = self._email_to_local(email_raw)
                if local and len(local) >= 2:
                    self._add_to_index(local, "EmailLocalPart")

            self.save_state()
        logger.info("Identity committed to registry.")

    def _add_to_index(self, text: str, category: str):
        vector = self.model.encode([text])
        faiss.normalize_L2(vector)
        idx = self.indices[category]
        pos = idx.ntotal
        idx.add(vector)
        self.vector_store.setdefault(category, {})[str(pos)] = text


# Singleton
ml_engine = MLEngine()
