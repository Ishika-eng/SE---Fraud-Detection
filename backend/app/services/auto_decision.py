import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy-init so missing API key doesn't crash startup
_client = None

def _get_client():
    global _client
    if _client is None and settings.ANTHROPIC_API_KEY:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def apply_rules(ml_result: dict, behavior: dict) -> dict | None:
    """
    Hard rules for obvious extremes. Returns a decision or None (→ send to LLM).
    """
    name_sim  = ml_result.get("name_sim",  0.0)
    email_sim = ml_result.get("email_sim", 0.0)
    cps       = behavior.get("cps", 0)
    risk      = ml_result.get("riskLevel", "LOW")

    # Physically impossible typing speed — definitive bot
    if cps > 60:
        return {
            "decision": "REJECT",
            "reason": f"Bot detected: {cps} CPS is physically impossible for a human (max ~15 CPS).",
            "auto": True,
        }

    # ML already cleared it as LOW — approve immediately
    if risk == "LOW":
        return {
            "decision": "APPROVE",
            "reason": "No similarity detected. Identity is unique.",
            "auto": True,
        }

    # Both signals extremely high — definitive duplicate
    if name_sim > 95 and email_sim > 90:
        return {
            "decision": "REJECT",
            "reason": f"Definitive duplicate: name {name_sim:.1f}% + email {email_sim:.1f}% match.",
            "auto": True,
        }

    # Very low similarity on both — safe despite being flagged (edge threshold case)
    if name_sim < 30 and email_sim < 30:
        return {
            "decision": "APPROVE",
            "reason": "Similarity below meaningful threshold. Different identity confirmed.",
            "auto": True,
        }

    # Similar name but clearly different email — common name, different person
    if name_sim > 80 and email_sim < 25:
        return {
            "decision": "APPROVE",
            "reason": f"Common name ({name_sim:.1f}% match) but email is clearly different. Different person.",
            "auto": True,
        }

    # Middle ground — LLM needed
    return None


async def ask_llm(ml_result: dict, behavior: dict, platform: str) -> dict:
    """
    LLM decision for middle-ground cases.
    Falls back to ESCALATE if API is unavailable or call fails.
    """
    client = _get_client()
    if not client:
        return {
            "decision": "ESCALATE",
            "reason": "LLM unavailable (no API key). Escalated for manual review.",
            "auto": False,
        }

    name_sim  = ml_result.get("name_sim",  0.0)
    email_sim = ml_result.get("email_sim", 0.0)
    cps       = behavior.get("cps", 0)
    pastes    = behavior.get("pastesCount", 0)
    risk      = ml_result.get("riskLevel", "MEDIUM")

    prompt = f"""You are a fraud detection AI for a {platform} platform. Decide if this registration is fraudulent.

Signals detected:
- Name similarity to an existing account: {name_sim:.1f}%
- Email similarity to an existing account: {email_sim:.1f}%
- Typing speed: {cps} CPS  (normal human range: 3–15 CPS)
- Paste events: {pastes}
- ML risk level: {risk}

Platform context:
- Edtech/Job Portal: people share common names — email similarity is the stronger fraud signal.
- E-Commerce/Insurance: duplicate email is almost always fraud.

Decision guide:
- APPROVE: signals are ambiguous or explainable by coincidence (e.g. common name, different email).
- REJECT: strong evidence of same person — high email match, paste + high similarity, etc.
- ESCALATE: genuinely uncertain — officer should decide.

Respond ONLY with valid JSON in this exact format:
{{"decision": "APPROVE", "reason": "one sentence"}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        text  = message.content[0].text.strip()
        start = text.find('{')
        end   = text.rfind('}') + 1
        data  = json.loads(text[start:end])

        if data.get("decision") not in ("APPROVE", "REJECT", "ESCALATE"):
            raise ValueError("Unexpected decision value")

        return {
            "decision": data["decision"],
            "reason":   data.get("reason", "LLM decision."),
            "auto":     data["decision"] != "ESCALATE",
        }
    except Exception as e:
        logger.warning(f"LLM auto-decision failed: {e}")
        return {
            "decision": "ESCALATE",
            "reason":   "LLM could not reach a confident decision. Escalated for manual review.",
            "auto":     False,
        }


async def auto_decide(ml_result: dict, behavior: dict, platform: str) -> dict:
    """
    Combined engine:
      1. Rules handle obvious extremes instantly.
      2. LLM handles the middle ground.
      3. Human officer only sees ESCALATE cases.
    """
    rule = apply_rules(ml_result, behavior)
    if rule:
        logger.info(f"Auto-decision by rules: {rule['decision']} — {rule['reason']}")
        return rule

    llm = await ask_llm(ml_result, behavior, platform)
    logger.info(f"Auto-decision by LLM: {llm['decision']} — {llm['reason']}")
    return llm
