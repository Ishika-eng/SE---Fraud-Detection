"""
Auto-decision engine — decision table:

┌──────────────────────────────────────────┬─────────────────┬──────────────────────────────┐
│ Situation                                │ Who decides     │ Action                       │
├──────────────────────────────────────────┼─────────────────┼──────────────────────────────┤
│ Device velocity limit exceeded           │ Rules           │ Auto-reject (rate limit)     │
│ CPS > 60                                 │ Rules           │ Auto-reject (bot)            │
│ Fingerprint exact match                  │ Rules           │ Auto-reject (returning user) │
│ Both sims < 30% (no approved match)      │ Rules           │ Auto-approve                 │
│ Both sims > 95%                          │ Rules           │ Auto-reject                  │
│ Similar name, different email            │ Rules           │ Auto-approve                 │
│ MEDIUM sim + no approved match           │ Rules           │ Auto-approve (false positive) │
│ Benefit already claimed                  │ Rules           │ Auto-reject                  │
│ Everything else                          │ LLM (Gemini)    │ APPROVE / REJECT / ESCALATE  │
│ LLM says ESCALATE                        │ Human officer   │ Dashboard (AI reason shown)  │
└──────────────────────────────────────────┴─────────────────┴──────────────────────────────┘
"""

import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

_anthropic_client = None
_gemini_client    = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None and settings.ANTHROPIC_API_KEY:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


def _get_gemini():
    global _gemini_client
    if _gemini_client is None and settings.GEMINI_API_KEY:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


def apply_rules(ml_result: dict, behavior: dict, benefit_claimed: bool = False) -> dict | None:
    """
    Hard rules for obvious cases. Returns a decision or None (-> LLM).
    Follows the decision table above.
    """
    name_sim  = ml_result.get("name_sim",  0.0)
    email_sim = ml_result.get("email_sim", 0.0)
    cps       = behavior.get("cps", 0)
    risk      = ml_result.get("riskLevel", "LOW")

    # Device velocity limit exceeded — too many submissions from one device
    if ml_result.get("velocity_exceeded"):
        return {
            "decision": "REJECT",
            "reason":   ml_result.get("message", "Device velocity limit exceeded."),
            "auto":     True,
        }

    # Row 1 — CPS > 60: physically impossible -> auto-reject
    if cps > 60:
        return {
            "decision": "REJECT",
            "reason":   f"Bot detected: {cps} CPS is physically impossible for a human.",
            "auto":     True,
        }

    # Phone exact match — same phone number reused under a different identity
    if ml_result.get("phone_match"):
        return {
            "decision": "REJECT",
            "reason":   "Phone number already registered to another account. Each account must use a unique phone number.",
            "auto":     True,
        }

    # Row 2 — Exact fingerprint match (Layer 1 already resolved to HIGH in ml_result)
    if ml_result.get("fingerprint_match"):
        return {
            "decision": "REJECT",
            "reason":   "Returning user detected: exact identity fingerprint already registered to an approved account.",
            "auto":     True,
        }

    # Layer 4 — Benefit already claimed by this identity
    if benefit_claimed:
        return {
            "decision": "REJECT",
            "reason":   "Benefit already claimed by this identity. Re-application blocked.",
            "auto":     True,
        }

    approved_name_sim  = ml_result.get("approved_name_sim",  0.0)
    approved_email_sim = ml_result.get("approved_email_sim", 0.0)

    # Approved-user: both > 95% -> definitive returning user — check BEFORE low-risk approve
    if approved_name_sim > 95 and approved_email_sim > 95:
        return {
            "decision": "REJECT",
            "reason":   f"Returning user: name {approved_name_sim:.1f}% + email {approved_email_sim:.1f}% match approved registry.",
            "auto":     True,
        }

    # Both sims < 30% and no approved-user match -> clearly new identity
    if name_sim < 30 and email_sim < 30 and approved_name_sim < 30 and approved_email_sim < 30:
        return {
            "decision": "APPROVE",
            "reason":   "All similarity signals below 30%. Clearly a new identity.",
            "auto":     True,
        }

    # ML determined LOW risk overall -> approve (approved-user checks already passed above)
    if risk == "LOW":
        return {
            "decision": "APPROVE",
            "reason":   "Identity is unique. No significant similarity detected.",
            "auto":     True,
        }

    # Both general-registry sims > 95%: definitive duplicate
    if name_sim > 95 and email_sim > 95:
        return {
            "decision": "REJECT",
            "reason":   f"Definitive duplicate: name {name_sim:.1f}% + email {email_sim:.1f}% match.",
            "auto":     True,
        }

    # Email local-part very high alone -> same person, different name
    if email_sim > 92 or approved_email_sim > 92:
        sim = max(email_sim, approved_email_sim)
        return {
            "decision": "REJECT",
            "reason":   f"Email local part already registered ({sim:.1f}% match). Same person, different name.",
            "auto":     True,
        }

    # Similar name, clearly different email -> auto-approve (common name)
    if name_sim > 60 and email_sim < 30 and approved_name_sim < 60:
        return {
            "decision": "APPROVE",
            "reason":   f"Similar name ({name_sim:.1f}%) but email is clearly different. Treated as a different person.",
            "auto":     True,
        }

    # MEDIUM general-registry similarity but NO approved-user match and NO fingerprint match.
    # The general registry includes rejected submissions too — a MEDIUM hit against it alone
    # is insufficient grounds for escalation and produces false positives for new users.
    # Only escalate/reject when the approved registry confirms a returning user.
    if (risk != "HIGH"
            and not ml_result.get("fingerprint_match")
            and approved_name_sim < 60
            and approved_email_sim < 60
            and not benefit_claimed):
        return {
            "decision": "APPROVE",
            "reason":   (
                f"General registry similarity (name {name_sim:.1f}%, email {email_sim:.1f}%) "
                f"is in MEDIUM range only, with no approved-user match. "
                f"Treated as a new identity to avoid false positive escalation."
            ),
            "auto":     True,
        }

    # Everything else -> LLM
    return None


async def ask_llm(ml_result: dict, behavior: dict, platform: str, benefit_claimed: bool = False) -> dict:
    """
    LLM decision for ambiguous cases.
    Sends all 4 layer signals: fingerprint, approved similarity, behavioral, benefit history.
    Priority: Gemini Flash -> Anthropic Haiku -> heuristic fallback.
    """
    gemini    = _get_gemini()
    anthropic = _get_anthropic()

    if not gemini and not anthropic:
        return _heuristic_fallback(ml_result)

    name_sim           = ml_result.get("name_sim",          0.0)
    email_sim          = ml_result.get("email_sim",         0.0)
    approved_name_sim  = ml_result.get("approved_name_sim", 0.0)
    approved_email_sim = ml_result.get("approved_email_sim",0.0)
    fingerprint_match  = ml_result.get("fingerprint_match", False)
    cps                = behavior.get("cps",          0)
    pastes             = behavior.get("pastesCount",  0)
    risk               = ml_result.get("riskLevel",   "MEDIUM")

    # Layer 3: behavioral comparison (only meaningful if fingerprint exists and profile exists)
    behavioral_note = ml_result.get("behavioral_note", "No prior behavioral profile.")
    behavioral_score = ml_result.get("behavioral_match_score")

    prompt = f"""You are a fraud detection AI for a {platform} platform.
This is a Returning User Fraud Detection check — the system tries to detect a legitimate user
who already received a benefit and is now creating a new identity to claim it again.

Signals:
- Exact identity fingerprint match (phone+email+device):  {fingerprint_match}
- Name similarity to existing account (general registry): {name_sim:.1f}%
- Email local-part similarity (general registry):         {email_sim:.1f}%
- Name similarity to APPROVED-USER registry:              {approved_name_sim:.1f}%
- Email similarity to APPROVED-USER registry:             {approved_email_sim:.1f}%
- Behavioral typing match score (0.0=different, 1.0=same): {f"{behavioral_score:.2f}" if behavioral_score is not None else "N/A (no profile)"}
- Behavioral note:                                        {behavioral_note}
- Typing speed: {cps} CPS (normal human: 3-15 CPS)
- Paste events: {pastes}
- ML overall risk level: {risk}
- Benefit previously claimed by this identity: {benefit_claimed}

Decide if this is a returning user attempting to re-claim a benefit, a new duplicate, or a legitimate new user.

APPROVE  = safe new user, let through
REJECT   = block automatically (returning user or clear duplicate)
ESCALATE = genuinely ambiguous, human officer must decide

Respond ONLY with valid JSON:
{{"decision": "APPROVE", "reason": "one sentence"}}"""

    try:
        if gemini:
            try:
                response = gemini.models.generate_content(
                    model="gemini-2.0-flash", contents=prompt
                )
                return _parse_llm_json(response.text.strip())
            except Exception as ge:
                logger.warning(f"Gemini failed: {ge}")
                if not anthropic:
                    raise ge

        if anthropic:
            message = anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_llm_json(message.content[0].text.strip())

    except Exception as e:
        logger.warning(f"All LLMs failed: {e}")
        return _heuristic_fallback(ml_result)


def _parse_llm_json(text: str) -> dict:
    """Extract and parse JSON from LLM response."""
    start = text.find('{')
    end   = text.rfind('}') + 1
    data  = json.loads(text[start:end])

    if data.get("decision") not in ("APPROVE", "REJECT", "ESCALATE"):
        raise ValueError("Invalid decision field in LLM response")

    return {
        "decision": data["decision"],
        "reason":   data.get("reason", "AI Decision"),
        "auto":     data["decision"] != "ESCALATE",
    }


def _heuristic_fallback(ml_result: dict) -> dict:
    """Best-effort heuristic if no LLM is available."""
    name_sim          = ml_result.get("name_sim",          0.0)
    email_sim         = ml_result.get("email_sim",         0.0)
    approved_name_sim = ml_result.get("approved_name_sim", 0.0)
    approved_email_sim= ml_result.get("approved_email_sim",0.0)

    max_sim = max(name_sim, email_sim, approved_name_sim, approved_email_sim)

    if max_sim > 80:
        return {
            "decision": "ESCALATE",
            "reason":   f"High similarity signals (max {max_sim:.1f}%) require human review.",
            "auto":     False,
        }
    return {
        "decision": "APPROVE",
        "reason":   "Similarity below concern threshold. Auto-approved by heuristics.",
        "auto":     True,
    }


async def auto_decide(
    ml_result:       dict,
    behavior:        dict,
    platform:        str,
    benefit_claimed: bool = False,
) -> dict:
    """
    Entry point. Rules first -> LLM for middle ground -> human for ESCALATE only.
    benefit_claimed: True if Layer 4 DB check found a prior benefit claim.
    """
    rule = apply_rules(ml_result, behavior, benefit_claimed=benefit_claimed)
    if rule:
        logger.info(f"Rule decision: {rule['decision']} — {rule['reason']}")
        return rule

    llm = await ask_llm(ml_result, behavior, platform, benefit_claimed=benefit_claimed)
    logger.info(f"LLM decision: {llm['decision']} — {llm['reason']}")
    return llm
