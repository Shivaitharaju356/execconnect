"""Sign-up screening: blocks scammers, MLM recruiters, forex/crypto sellers and promotional accounts.

Layer 1: transparent rules (always on, explainable).
Layer 2: optional LLM classifier (when an API key is configured) - the higher of the two scores wins.
"""
import json
import re

import llm

RULES = {
    "mlm": [
        r"\bpassive income\b", r"\bbe your own boss\b", r"\bnetwork marketing\b", r"\bdownline\b",
        r"\bjoin my team\b", r"\bfinancial freedom\b", r"\bwork from home\b.*\bearn\b", r"\bside hustle\b",
        r"\b(6|six|7|seven)[ -]figure\b", r"\bresidual income\b", r"\bmlm\b", r"\bunlimited earning",
    ],
    "forex_crypto": [
        r"\bforex\b", r"\bfx signals?\b", r"\btrading signals?\b", r"\bbinary options?\b", r"\bguaranteed (returns?|profits?)\b",
        r"\b\d{2,3}\s?% (monthly|weekly|daily) (returns?|profit)", r"\bcrypto (signals?|mentor|guru)\b",
        r"\bdouble your (money|investment)\b", r"\b(usdt|bitcoin|btc) (wallet|investment plan)\b", r"\bpump\b",
    ],
    "promotional": [
        r"\bdm me\b", r"\bclick (the )?link\b", r"\blink in bio\b", r"\bbuy now\b", r"\blimited offer\b",
        r"\bdiscount code\b", r"\bfollow me\b", r"\bwhats ?app me\b", r"\btelegram\b", r"\bfree (course|webinar|ebook)\b",
    ],
}
WEIGHT = {"mlm": 30, "forex_crypto": 35, "promotional": 20}

URL_RE = re.compile(r"https?://|www\.", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s\-]{8,}\d")
CRYPTO_ADDR_RE = re.compile(r"\b(0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")


def rule_score(text):
    t = (text or "").lower()
    hits, cat_scores = [], {}
    for cat, patterns in RULES.items():
        for p in patterns:
            m = re.search(p, t)
            if m:
                hits.append(f"{cat}: '{m.group(0)}'")
                cat_scores[cat] = cat_scores.get(cat, 0) + WEIGHT[cat]
    extra = 0
    n_urls = len(URL_RE.findall(text or ""))
    if n_urls >= 2:
        extra += 15; hits.append(f"spam: {n_urls} links in profile")
    if PHONE_RE.search(text or ""):
        extra += 15; hits.append("spam: phone number in public profile")
    if CRYPTO_ADDR_RE.search(text or ""):
        extra += 40; hits.append("forex_crypto: crypto wallet address")
        cat_scores["forex_crypto"] = cat_scores.get("forex_crypto", 0) + 40
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) > 40 and sum(c.isupper() for c in letters) / len(letters) > 0.5:
        extra += 10; hits.append("spam: shouting (mostly capitals)")
    if (text or "").count("!") >= 4:
        extra += 10; hits.append("spam: excessive exclamation marks")
    score = min(100, sum(cat_scores.values()) + extra)
    category = max(cat_scores, key=cat_scores.get) if cat_scores else ("promotional" if extra >= 25 else "ok")
    return score, category, hits


LLM_PROMPT = """You screen sign-ups for a private networking platform for executives (directors, VPs, C-suite, founders, investors, advisory board members).
Classify the profile. Flag scammers, MLM recruiters, forex/crypto signal sellers, and promotional/spam accounts. Genuine investors and fintech founders are NOT scams.
Return ONLY JSON: {"risk": <0-100>, "category": "ok|mlm|forex_crypto|promotional|scam|fake_profile", "reason": "<one sentence>"}

Profile:
"""


def llm_score(text):
    raw = llm.complete(LLM_PROMPT + text, max_tokens=150)
    if not raw:
        return None
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        return int(data.get("risk", 0)), data.get("category", "ok"), data.get("reason", "")
    except (ValueError, TypeError):
        return None


def profile_text(p):
    return " \n".join(str(p.get(k, "")) for k in ("headline", "bio", "company", "interests", "investment_focus"))


def screen_profile(p, review_at=30, block_at=70):
    """Returns dict(score, category, reasons, status) where status is active | review | blocked."""
    text = profile_text(p)
    score, category, reasons = rule_score(text)
    ai = llm_score(text)
    if ai:
        ai_score, ai_cat, ai_reason = ai
        reasons.append(f"AI: {ai_reason} ({ai_score})")
        if ai_score > score:
            score, category = ai_score, ai_cat
    status = "blocked" if score >= block_at else "review" if score >= review_at else "active"
    return {"score": score, "category": category, "reasons": reasons, "status": status}


def screen_message(body):
    """Chat messages: flag (not block) promotional/scam content after sign-up, too."""
    score, category, reasons = rule_score(body)
    return score >= 30, reasons
