"""AI matching engine.

score = 0.40 * semantic similarity of profiles (TF-IDF, or OpenAI embeddings when a key is set)
      + 0.30 * intent complementarity (mentor-seeker <-> mentor, founder raising <-> investor, ...)
      + 0.15 * profile fit (industry, function, seniority gap)
      + 0.15 * trust (verification + peer ratings)

Hard rules: only active users, never yourself, never already-connected users, and
same-country only unless the searcher has Premium (cross-country matching is the paid feature).
"""
import hashlib

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import llm

INTENTS = {
    "seeking_mentor": "Looking for a mentor",
    "offering_mentorship": "Offering mentorship",
    "seeking_advisor": "Looking for an advisor",
    "offering_advice": "Available as an advisor",
    "seeking_board_role": "Looking for a board role",
    "board_seat_open": "Have a board seat to fill",
    "strategic_partner": "Looking for a strategic partner",
    "founder_network": "Looking for a founder network",
    "investment_opportunities": "Looking for investment opportunities",
    "seeking_funding": "Raising funding",
    "cofounder": "Looking for a co-founder / to build a new company",
}

# (my intent, their intent) -> strength. Symmetric pairs are listed once and mirrored below.
_PAIRS = {
    ("seeking_mentor", "offering_mentorship"): 1.0,
    ("seeking_advisor", "offering_advice"): 1.0,
    ("seeking_board_role", "board_seat_open"): 1.0,
    ("seeking_funding", "investment_opportunities"): 1.0,
    ("strategic_partner", "strategic_partner"): 0.9,
    ("founder_network", "founder_network"): 0.8,
    ("cofounder", "cofounder"): 0.9,
    ("seeking_advisor", "offering_mentorship"): 0.6,
    ("seeking_mentor", "offering_advice"): 0.6,
    ("cofounder", "founder_network"): 0.5,
    ("founder_network", "investment_opportunities"): 0.4,
    ("strategic_partner", "cofounder"): 0.5,
}
COMPLEMENT = {}
for (a, b), w in _PAIRS.items():
    COMPLEMENT[(a, b)] = max(COMPLEMENT.get((a, b), 0), w)
    COMPLEMENT[(b, a)] = max(COMPLEMENT.get((b, a), 0), w)

SENIORITY_RANK = {"Director": 1, "VP": 2, "C-suite": 3, "Founder": 3, "Investor": 3, "Advisory board member": 4}
INDUSTRIES = ["Fintech", "HealthTech", "SaaS", "AI & Data", "Cybersecurity", "E-commerce", "Mobility",
              "Energy & Climate", "Manufacturing", "Media", "Logistics", "Real Estate", "Biotech", "Consulting"]
FUNCTIONS = ["Engineering", "Product", "Sales", "Marketing", "Finance", "Operations", "Strategy", "HR / People",
             "Legal", "Data & AI", "General Management", "Investment"]
SENIORITIES = list(SENIORITY_RANK)

W_SEM, W_INTENT, W_FIT, W_TRUST = 0.40, 0.30, 0.15, 0.15


def doc(u):
    interests = u.get("interests", "")
    # interests are repeated so they weigh more than free-text bio
    return " ".join([interests, interests, u.get("headline", ""), u.get("bio", ""), u.get("industry", ""),
                     u.get("function", ""), u.get("investment_focus", "")])


_embed_cache = {}


def semantic_matrix(me, candidates):
    docs = [doc(me)] + [doc(c) for c in candidates]
    keys = [hashlib.sha1(d.encode()).hexdigest() for d in docs]
    if llm.enabled():
        missing = [d for d, k in zip(docs, keys) if k not in _embed_cache]
        vecs = llm.embed(missing) if missing else []
        if vecs is not None:
            for d, v in zip(missing, vecs):
                _embed_cache[hashlib.sha1(d.encode()).hexdigest()] = v
            m = np.array([_embed_cache[k] for k in keys])
            return cosine_similarity(m[:1], m[1:])[0]
    tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    m = tfidf.fit_transform(docs)
    return cosine_similarity(m[0:1], m[1:])[0]


def intent_score(my_intents, their_intents):
    best, pairs = 0.0, []
    for a in my_intents:
        for b in their_intents:
            w = COMPLEMENT.get((a, b), 0)
            if w:
                pairs.append((a, b, w))
                best = max(best, w)
    # small bonus for several complementary pairs
    return min(1.0, best + 0.1 * max(0, len(pairs) - 1)), sorted(pairs, key=lambda p: -p[2])


def fit_score(me, c, top_pair):
    s = 0.0
    if me.get("industry") and me["industry"] == c.get("industry"):
        s += 0.45
    if me.get("function") and me["function"] == c.get("function"):
        s += 0.15
    if me.get("city") and me["city"].lower() == (c.get("city") or "").lower():
        s += 0.15
    gap = SENIORITY_RANK.get(c.get("seniority"), 2) - SENIORITY_RANK.get(me.get("seniority"), 2)
    if top_pair and top_pair[0] in ("seeking_mentor", "seeking_advisor"):
        s += 0.25 if gap > 0 else 0          # mentors should be more senior
    elif top_pair and top_pair[0] in ("offering_mentorship", "offering_advice"):
        s += 0.25 if gap < 0 else 0
    else:
        s += 0.25 if abs(gap) <= 1 else 0.1  # peers
    return min(1.0, s)


def trust_score(c, rating_avg):
    s = 0.0
    s += 0.25 if c.get("email_verified") else 0
    s += 0.25 if c.get("company_verified") else 0
    s += 0.2 if c.get("linkedin_status") == "verified" else 0.05 if c.get("linkedin_status") == "pending" else 0
    s += 0.3 * (rating_avg / 5.0 if rating_avg else 0.6)  # neutral prior for new members
    return min(1.0, s)


def shared_interests(me, c):
    a = {x.strip().lower() for x in (me.get("interests") or "").split(",") if x.strip()}
    b = {x.strip().lower() for x in (c.get("interests") or "").split(",") if x.strip()}
    return sorted(a & b)


def explain(me, c, pairs, shared):
    parts = []
    if pairs:
        a, b, _ = pairs[0]
        parts.append(f"You are {INTENTS[a].lower()} and they are {INTENTS[b].lower()}")
    if shared:
        parts.append("you share interest in " + ", ".join(shared[:3]))
    if me.get("industry") == c.get("industry"):
        parts.append(f"both work in {c['industry']}")
    if me.get("city", "").lower() == (c.get("city") or "").lower() and c.get("city"):
        parts.append(f"both based in {c['city']}")
    if not parts:
        parts.append("your profiles cover related topics")
    s = "; ".join(parts)
    return s[0].upper() + s[1:] + "."


def llm_explain(me, matches):
    """Rewrites the top reasons into one natural sentence each (RAG over the two profiles)."""
    if not llm.enabled() or not matches:
        return
    lines = [f"{i}. THEM: {m['headline']} | {m['industry']} | {m['seniority']} | intents: {', '.join(m['intents'])} "
             f"| interests: {m['interests']}" for i, m in enumerate(matches)]
    prompt = ("You write one-sentence introductions for an executive networking app. Explain concretely why ME should "
              "connect with each person, referring to their intents and interests. Never invent facts.\n"
              f"ME: {me.get('headline')} | {me.get('industry')} | {me.get('seniority')} | intents: "
              f"{', '.join(me.get('intents', []))} | interests: {me.get('interests')}\n" + "\n".join(lines) +
              "\nReturn exactly one line per person in the form '<number>. <sentence>'.")
    out = llm.complete(prompt, max_tokens=60 * len(matches))
    if not out:
        return
    for line in out.splitlines():
        num, _, sent = line.strip().partition(". ")
        if num.isdigit() and int(num) < len(matches) and sent:
            matches[int(num)]["reason"] = sent.strip()
            matches[int(num)]["reason_source"] = "ai"


def rank(me, candidates, ratings, filters=None, limit=20, use_llm=True):
    """me/candidates: dicts with profile fields plus 'intents' list. ratings: {user_id: avg}."""
    filters = filters or {}
    pool = []
    for c in candidates:
        if c["id"] == me["id"] or c.get("status") != "active":
            continue
        if not me.get("is_premium") and c.get("country") != me.get("country"):
            continue
        if filters.get("country") and c.get("country") != filters["country"]:
            continue
        if filters.get("city") and (c.get("city") or "").lower() != filters["city"].lower():
            continue
        if filters.get("industry") and c.get("industry") != filters["industry"]:
            continue
        if filters.get("seniority") and c.get("seniority") != filters["seniority"]:
            continue
        if filters.get("function") and c.get("function") != filters["function"]:
            continue
        if filters.get("hiring") and not c.get("hiring"):
            continue
        if filters.get("board") and not c.get("board_experience"):
            continue
        if filters.get("investment") and not (c.get("investment_focus") or "").strip():
            continue
        if filters.get("intent") and filters["intent"] not in c.get("intents", []):
            continue
        pool.append(c)
    if not pool:
        return []
    sem = semantic_matrix(me, pool)
    results = []
    for c, s in zip(pool, sem):
        i_score, pairs = intent_score(me.get("intents", []), c.get("intents", []))
        f_score = fit_score(me, c, pairs[0] if pairs else None)
        t_score = trust_score(c, ratings.get(c["id"]))
        total = W_SEM * float(s) + W_INTENT * i_score + W_FIT * f_score + W_TRUST * t_score
        shared = shared_interests(me, c)
        results.append({
            "id": c["id"], "alias": c["alias"], "headline": c.get("headline", ""), "industry": c.get("industry", ""),
            "seniority": c.get("seniority", ""), "function": c.get("function", ""), "city": c.get("city", ""),
            "country": c.get("country", ""), "intents": c.get("intents", []), "interests": c.get("interests", ""),
            "hiring": bool(c.get("hiring")), "board_experience": bool(c.get("board_experience")),
            "investment_focus": c.get("investment_focus", ""), "rating": ratings.get(c["id"]),
            "verified": {"email": bool(c.get("email_verified")), "company": bool(c.get("company_verified")),
                         "linkedin": c.get("linkedin_status")},
            "score": round(total * 100, 1),
            "breakdown": {"semantic": round(float(s) * 100), "intent": round(i_score * 100),
                          "fit": round(f_score * 100), "trust": round(t_score * 100)},
            "shared": shared, "reason": explain(me, c, pairs, shared), "reason_source": "rules",
        })
    results.sort(key=lambda r: -r["score"])
    results = results[:limit]
    if use_llm:
        llm_explain(me, results[:5])
    return results
