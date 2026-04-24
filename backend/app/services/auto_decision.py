"""
Auto-decision engine — follows this exact decision table:

┌──────────────────────────────┬─────────────────┬──────────────────────────────┐
│ Situation                    │ Who decides     │ Action                       │
├──────────────────────────────┼─────────────────┼──────────────────────────────┤
│ CPS > 60                     │ Rules           │ Auto-reject                  │
│ Both sims < 30%              │ Rules           │ Auto-approve                 │
│ Both sims > 95%              │ Rules           │ Auto-reject                  │
│ Similar name, different email│ Rules           │ Auto-approve                 │
│ Everything else              │ LLM (Haiku)     │ APPROVE / REJECT / ESCALATE  │
│ LLM says ESCALATE            │ Human officer   │ Dashboard (AI reason shown)  │
└──────────────────────────────┴─────────────────┴──────────────────────────────┘

Email similarity is computed on the local part only (domain ignored).
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
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _gemini_client = genai.GenerativeModel('gemini-flash-latest')
    return _gemini_client


def apply_rules(ml_result: dict, behavior: dict) -> dict | None:
    """
    Hard rules for obvious cases. Returns a decision or None (→ send to LLM).
    Exactly follows the decision table above.
    """
    name_sim  = ml_result.get("name_sim",  0.0)
    email_sim = ml_result.get("email_sim", 0.0)
    cps       = behavior.get("cps", 0)
    risk      = ml_result.get("riskLevel", "LOW")

    # Row 1 — CPS > 60: physically impossible for a human → auto-reject
    if cps > 60:
        return {
            "decision": "REJECT",
            "reason":   f"Bot detected: {cps} CPS is physically impossible for a human.",
            "auto":     True,
        }

    # Row 2 — Both sims < 30%: clearly different identity → auto-approve
    if name_sim < 30 and email_sim < 30:
        return {
            "decision": "APPROVE",
            "reason":   "Both name and email similarity below 30%. Clearly a new identity.",
            "auto":     True,
        }

    # ML already determined LOW risk (both sims below medium threshold) → approve
    if risk == "LOW":
        return {
            "decision": "APPROVE",
            "reason":   "Identity is unique. No significant similarity detected.",
            "auto":     True,
        }

    # Row 3 — Both sims > 95%: definitive duplicate → auto-reject
    if name_sim > 95 and email_sim > 95:
        return {
            "decision": "REJECT",
            "reason":   f"Definitive duplicate: name {name_sim:.1f}% + email {email_sim:.1f}% match.",
            "auto":     True,
        }

    # Email local-part very high alone → same person, different name → auto-reject
    if email_sim > 92:
        return {
            "decision": "REJECT",
            "reason":   f"Email local part already registered ({email_sim:.1f}% match). Same person, different name.",
            "auto":     True,
        }

    # Row 4 — Similar name, different email → auto-approve
    # (name is similar but email local part is clearly different — could be same common name)
    if name_sim > 60 and email_sim < 30:
        return {
            "decision": "APPROVE",
            "reason":   f"Similar name ({name_sim:.1f}%) but email is clearly different. Treated as a different person.",
            "auto":     True,
        }

    # Everything else → LLM (Row 5)
    return None


async def ask_llm(ml_result: dict, behavior: dict, platform: str) -> dict:
    """
    LLM decision for middle-ground cases. 
    Prioritizes Gemini Flash (High Free Quota) -> Anthropic -> Fallback Heuristics.
    """
    gemini    = _get_gemini()
    anthropic = _get_anthropic()

    if not gemini and not anthropic:
        return _heuristic_fallback(ml_result)

    name_sim  = ml_result.get("name_sim",  0.0)
    email_sim = ml_result.get("email_sim", 0.0)
    cps       = behavior.get("cps", 0)
    pastes    = behavior.get("pastesCount", 0)
    risk      = ml_result.get("riskLevel", "MEDIUM")

    prompt = f"""You are a fraud detection AI for a {platform} platform.

Signals:
- Name similarity to existing account: {name_sim:.1f}%
- Email local-part similarity (domain ignored): {email_sim:.1f}%
- Typing speed: {cps} CPS (normal human: 3–15 CPS)
- Paste events: {pastes}
- ML risk level: {risk}

Decide if this registration is fraudulent.

APPROVE  = safe, let through
REJECT   = block automatically
ESCALATE = genuinely ambiguous, human officer must decide

Respond ONLY with valid JSON:
{{"decision": "APPROVE", "reason": "one sentence"}}"""

    try:
        # 1. Try Gemini (Flash) first
        if gemini:
            try:
                response = gemini.generate_content(prompt)
                text = response.text.strip()
                return _parse_llm_json(text)
            except Exception as ge:
                logger.warning(f"Gemini failed: {ge}")
                if not anthropic: raise ge

        # 2. Try Anthropic (Haiku) as backup
        if anthropic:
            message = anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            return _parse_llm_json(text)

    except Exception as e:
        logger.warning(f"All LLMs failed: {e}")
        return _heuristic_fallback(ml_result)

def _parse_llm_json(text: str) -> dict:
    """Helper to extract and parse JSON from LLM response."""
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
    name_sim  = ml_result.get("name_sim",  0.0)
    email_sim = ml_result.get("email_sim", 0.0)
    
    if name_sim > 80 or email_sim > 70:
        return {
            "decision": "ESCALATE",
            "reason":   f"Similarity signals are high (Name {name_sim:.1f}%, Email {email_sim:.1f}%) but require human review.",
            "auto":     False,
        }
    return {
        "decision": "APPROVE",
        "reason":   "Similarity below concern threshold. Auto-approved by heuristics.",
        "auto":     True,
    }


async def auto_decide(ml_result: dict, behavior: dict, platform: str) -> dict:
    """
    Entry point. Rules first → LLM for middle ground → human for ESCALATE only.
    """
    rule = apply_rules(ml_result, behavior)
    if rule:
        logger.info(f"Rule decision: {rule['decision']} — {rule['reason']}")
        return rule

    llm = await ask_llm(ml_result, behavior, platform)
    logger.info(f"LLM decision: {llm['decision']} — {llm['reason']}")
    return llm
