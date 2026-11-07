# ExecConnect

A verified, privacy-first networking app for Directors, VPs, C-suite, founders, investors and advisory board members.
It matches people by **intent** (mentor, advisor, board role, strategic partner, founder network, funding) instead of
swiping. Members chat and video-call **without revealing their name, email or phone**.

## Quick start (5 minutes)

```bash
pip install -r requirements.txt
python seed.py        # creates 50 test members, 5 scam sign-ups, an admin and a demo user
python app.py         # open http://localhost:5000
```

| Account | Email | Password |
|---|---|---|
| Demo founder | demo@novapay.example.com | Demo12345! |
| Admin (dashboard) | admin@execconnect.example.com | Demo12345! |
| Any seeded member | see the admin dashboard | Demo12345! |

To switch on the LLM features, set **one** key before starting the app:
`OPENAI_API_KEY=...` (embeddings + AI explanations + AI screening) or `ANTHROPIC_API_KEY=...` (AI explanations + AI screening).
Without a key everything still works with TF-IDF matching and rule-based screening.

Run the tests: `python -m pytest -q` (10 end-to-end tests).

## How each requirement is covered

| Requirement from the brief | Implementation |
|---|---|
| Sign-up website with areas of interest | 3-step sign-up: account → professional profile → intents (`static/app.js`) |
| MFA + secure credential storage | TOTP 2-step verification (RFC 6238, works with Google/Microsoft Authenticator), passwords hashed with scrypt/PBKDF2 (Werkzeug), HttpOnly SameSite cookies, login lockout after 5 failures, JSON-only API as a CSRF guard |
| Human, not a bot | Signed arithmetic challenge, hidden honeypot field, minimum fill time; optional Cloudflare Turnstile (`TURNSTILE_SECRET`) |
| Target audience only | Seniority must be Director, VP, C-suite, Founder, Investor or Advisory board member |
| LinkedIn / corporate email / company verification | Free and disposable email domains are rejected; email OTP; the company is verified when the email domain matches the company website; LinkedIn URL is validated and reviewed by an admin |
| Intent-based matching, not swiping | 11 intents with a complementarity matrix (e.g. *raising funding ↔ looking for investment opportunities*) |
| Visually clean, easy sign-up, smooth navigation | Single-page app, responsive, no page reloads |
| Block scammers, MLM recruiters, forex sellers, promo accounts | `screening.py`: weighted rules (MLM / forex-crypto / promotional phrases, wallet addresses, phone numbers, link spam, shouting) plus an optional LLM classifier. Score ≥ 70 is blocked, 30–69 goes to the admin review queue. Chat messages and connection notes are screened too. |
| 20–50 test accounts | `seed.py` creates 50 realistic members across 12 industries and 9 countries + 5 scam attempts (4 blocked, 1 sent to review) |
| Dashboard of interests | Admin dashboard: KPIs, top interests, intents, industries, seniority, countries, screening flags, trust & safety queue |
| AI matching algorithm | `matching.py` (below) |
| Same area free, other countries paid | Free members only see members in their own country; Premium unlocks cross-country matching (demo toggle, no payment) |
| Filters | Intent, industry, seniority, function, city, country (Premium), hiring, board experience, investment focus |
| Chat / call without disclosing credentials | Members appear under aliases; real-time chat (polling); one-click Jitsi video rooms; real names, company and LinkedIn are shown only when **both** people click "Reveal identity" |
| Rate members | Responsiveness, quality of introductions, mentoring contribution, event participation; only between connected members; averages feed the trust score |

## The matching algorithm

```
score = 0.40 × semantic similarity   (TF-IDF bigrams, or OpenAI embeddings when a key is set)
      + 0.30 × intent complementarity (best complementary intent pair + bonus for extra pairs)
      + 0.15 × profile fit            (same industry/function/city; mentors must be more senior)
      + 0.15 × trust                  (email, company and LinkedIn verification + peer ratings)
```

Hard rules come first: only active, verified members, never people you're already connected with, and same country
unless Premium. Every match shows its score breakdown and a plain-English reason. With an LLM key, the top 5 reasons are
rewritten by the model using only the two profiles (a small retrieval-augmented step, so nothing is invented).

## Project structure

```
app.py          Flask API: auth, MFA, profile, matching, connections, chat, calls, ratings, admin
matching.py     Hybrid AI ranking + explanations
screening.py    Scam / MLM / forex / promo detection (rules + optional LLM)
security.py     TOTP, human check, email & company verification, aliases
llm.py          Optional OpenAI / Anthropic calls (graceful fallback when no key)
db.py           SQLite schema
seed.py         Test data
static/         Front end (HTML, CSS, vanilla JS)
tests/          pytest end-to-end tests
```

## Suggested improvements (production roadmap)

1. **Sign in with LinkedIn (OpenID Connect)** for verified name and email. Job titles still need manual review, because LinkedIn's standard API doesn't share them.
2. **Postgres + pgvector** (e.g. Supabase) instead of SQLite, with WebSockets instead of polling for chat.
3. **Warm introductions**: ask a mutual connection to introduce you instead of messaging cold. This raises acceptance rates.
4. **Learning to rank**: use accepted/declined requests and ratings as labels to tune the weights.
5. **Agentic concierge**: an LLM agent that turns "I need a fintech CFO who has done a Series B in DACH" into filters plus a ranked shortlist.
6. **Trust & safety after sign-up**: detect bursts of identical messages and sudden drops in a member's ratings.
7. **GDPR**: data export and deletion, minimal personal data, an EU hosting region, and a record of consent.
8. **Real payments** (Stripe) for Premium, and email delivery (e.g. Postmark) for verification codes.
