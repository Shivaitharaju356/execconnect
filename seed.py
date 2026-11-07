"""Creates 50 realistic test members (+ 5 scam sign-ups that the screening must catch), an admin and a demo user.

    python seed.py          # reset DB and seed
All seeded accounts use the password  Demo12345!
"""
import os
import random

from werkzeug.security import generate_password_hash

import db
import screening
import security

random.seed(42)
PASSWORD = "Demo12345!"

FIRST = ["Anna", "Lukas", "Sofia", "Jonas", "Mia", "Felix", "Lea", "Noah", "Clara", "Elias", "Priya", "Arjun", "Emma",
         "Liam", "Olivia", "Mateo", "Hannah", "David", "Sara", "Tobias", "Nina", "Kai", "Laura", "Ravi", "Julia", "Max",
         "Elena", "Omar", "Katarina", "Marek", "Ingrid", "Tom", "Aisha", "Pieter", "Grace", "Henrik", "Yuki", "Carlos",
         "Fatima", "Jan", "Meera", "Paul", "Zoe", "Viktor", "Lina", "Stefan", "Ana", "Rahul", "Sophie", "Erik"]
LAST = ["Schmidt", "Müller", "Weber", "Fischer", "Becker", "Wagner", "Hoffmann", "Koch", "Richter", "Klein", "Sharma",
        "Patel", "Novak", "Tamm", "Kask", "de Vries", "Jansen", "Smith", "Brown", "Garcia", "Rossi", "Nilsson", "Larsen",
        "Kowalski", "Ivanova", "Okafor", "Chen", "Tanaka", "Haddad", "Iyer"]

LOCATIONS = [("Germany", "Berlin")] * 14 + [("Germany", "Munich")] * 5 + [("Germany", "Hamburg")] * 3 + \
            [("Germany", "Frankfurt")] * 3 + [("Estonia", "Tallinn")] * 5 + [("Netherlands", "Amsterdam")] * 4 + \
            [("United Kingdom", "London")] * 4 + [("United States", "New York")] * 2 + [("India", "Bangalore")] * 3

INDUSTRY_TOPICS = {
    "Fintech": ["payments", "embedded finance", "open banking", "regtech", "fundraising"],
    "HealthTech": ["digital health", "medical devices", "healthcare regulation", "telemedicine", "AI diagnostics"],
    "SaaS": ["B2B SaaS", "product-led growth", "go-to-market", "pricing strategy", "enterprise sales"],
    "AI & Data": ["generative AI", "LLM applications", "MLOps", "data platforms", "AI governance"],
    "Cybersecurity": ["AI security", "zero trust", "NIS2 compliance", "identity and access", "cloud security"],
    "E-commerce": ["marketplaces", "D2C brands", "quick commerce", "supply chain", "retail media"],
    "Mobility": ["electric vehicles", "fleet management", "autonomous driving", "micromobility", "charging infrastructure"],
    "Energy & Climate": ["renewable energy", "carbon accounting", "climate tech", "battery storage", "ESG"],
    "Manufacturing": ["industry 4.0", "robotics", "predictive maintenance", "supply chain", "IoT"],
    "Logistics": ["last-mile delivery", "warehouse automation", "supply chain", "freight tech", "route optimisation"],
    "Biotech": ["drug discovery", "AI diagnostics", "clinical trials", "life sciences funding", "genomics"],
    "Consulting": ["digital transformation", "M&A", "operating models", "AI strategy", "change management"],
}

ARCHETYPES = [
    # (seniority, function, intents, headline template, bio template, extras)
    ("Founder", "General Management", ["seeking_funding", "seeking_mentor", "founder_network"],
     "Founder & CEO of a {stage} {ind} startup",
     "Building a {ind} company focused on {t0} and {t1}. Raising our {stage} round and looking for experienced "
     "operators who have scaled in {t2}.", {}),
    ("Founder", "Engineering", ["cofounder", "founder_network", "seeking_advisor"],
     "Technical founder exploring a new venture in {t0}",
     "Former engineering lead, now building in {ind}. Looking for a commercial co-founder and advisors with "
     "experience in {t1} and {t2}.", {}),
    ("Investor", "Investment", ["investment_opportunities", "offering_advice", "board_seat_open"],
     "Partner at an early-stage VC fund investing in {ind}",
     "We back pre-seed to Series A teams in {ind}, especially {t0}, {t1} and {t2}. Happy to advise founders on "
     "fundraising and board building.", {"investment_focus": "{ind}, {t0}, pre-seed to Series A"}),
    ("Investor", "Investment", ["investment_opportunities", "founder_network"],
     "Angel investor and former operator in {ind}",
     "Exited founder now writing angel cheques in {t0} and {t1}. I like to stay close to founders as a sparring partner.",
     {"investment_focus": "Angel, {ind}, {t0}"}),
    ("C-suite", "General Management", ["offering_mentorship", "seeking_board_role", "strategic_partner"],
     "CEO of a scale-up in {ind}",
     "Led a {ind} company from 20 to 400 people. Mentoring first-time founders on {t0} and {t1}, and open to "
     "non-executive board roles.", {"hiring": 1, "board_experience": 1}),
    ("C-suite", "Engineering", ["offering_mentorship", "strategic_partner", "offering_advice"],
     "CTO in {ind}, building platforms for {t0}",
     "Technology leader with deep experience in {t0}, {t1} and scaling engineering teams. I mentor new CTOs and "
     "look for strategic technology partners.", {"hiring": 1}),
    ("C-suite", "Finance", ["offering_advice", "seeking_board_role"],
     "CFO with IPO and fundraising experience in {ind}",
     "Finance leader who has raised over 100M in {ind}. Advising on {t0}, fundraising and financial planning. "
     "Looking for an independent board seat.", {"board_experience": 1}),
    ("VP", "Product", ["seeking_mentor", "strategic_partner", "cofounder"],
     "VP Product in {ind}",
     "Product leader working on {t0} and {t1}. Looking for a mentor on the path to CPO and partners to build new "
     "products in {t2}.", {"hiring": 1}),
    ("VP", "Sales", ["strategic_partner", "seeking_mentor"],
     "VP Sales - enterprise {ind}",
     "Built enterprise sales teams selling {t0} solutions across Europe. Interested in partnerships around {t1}.",
     {"hiring": 1}),
    ("Director", "Data & AI", ["seeking_mentor", "cofounder", "strategic_partner"],
     "Director of Data & AI in {ind}",
     "Leading data science and {t0} initiatives. Interested in {t1} and exploring building a new company around {t2}.",
     {}),
    ("Director", "Strategy", ["seeking_advisor", "seeking_mentor"],
     "Director of Strategy, {ind}",
     "Driving {t0} and {t1} programmes. Looking for advisors who have led similar transformations.", {}),
    ("Advisory board member", "General Management", ["offering_advice", "offering_mentorship", "investment_opportunities"],
     "Board member and advisor to {ind} companies",
     "Sits on three boards in {ind}. Advising on governance, {t0} and international expansion; occasional angel "
     "investor in {t1}.", {"board_experience": 1, "investment_focus": "{ind}, growth stage"}),
]

COMPANY_WORDS = ["Nova", "Blue", "Peak", "Bright", "Core", "Flux", "North", "Vertex", "Clear", "Lumen", "Arc", "Pulse",
                 "Zen", "Atlas", "Orbit", "Spark", "Terra", "Quant", "Helix", "Nimbus"]
COMPANY_SUFFIX = ["pay", "health", "labs", "ai", "secure", "logistics", "energy", "ventures", "systems", "capital"]

SCAM_PROFILES = [
    ("Forex Mentor", "Founder", "Investment", "Fintech", "Forex trading mentor | 30% monthly returns guaranteed",
     "Join my VIP forex signals group and double your money! Guaranteed profits every week. WhatsApp me +49 151 2345 6789"),
    ("MLM Leader", "Founder", "Sales", "E-commerce", "Be your own boss - financial freedom coach",
     "Looking for ambitious leaders to join my team. Passive income, residual income, six-figure side hustle from home. DM me!"),
    ("Crypto Guru", "Investor", "Investment", "Fintech", "Crypto mentor - USDT investment plan",
     "Send to my bitcoin wallet bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh and earn daily profit. Telegram @cryptoking"),
    ("Promo Account", "VP", "Marketing", "Media", "FREE webinar - click the link in bio!!!",
     "BUY NOW limited offer!!! discount code EXEC50. Follow me for more. www.promo-deals.example www.cheap-leads.example"),
    ("Soft Spammer", "Director", "Sales", "SaaS", "Growth hacker | lead gen",
     "I help founders get 100 leads a day with outbound automation. DM me and I will share a free webinar recording."),
]


def domain_for(name):
    return f"{name.lower()}.example.com"


def make_profile(i):
    arch = ARCHETYPES[i % len(ARCHETYPES)]
    seniority, function, intents, h, b, extra = arch
    ind = random.choice(list(INDUSTRY_TOPICS))
    topics = random.sample(INDUSTRY_TOPICS[ind], 3)
    # one cross-industry topic makes matching less trivially "same industry"
    cross = random.choice(INDUSTRY_TOPICS[random.choice(list(INDUSTRY_TOPICS))])
    fmt = {"ind": ind, "t0": topics[0], "t1": topics[1], "t2": topics[2], "stage": random.choice(["pre-seed", "seed", "Series A"])}
    country, city = LOCATIONS[i % len(LOCATIONS)]
    first, last = FIRST[i % len(FIRST)], random.choice(LAST)
    company = random.choice(COMPANY_WORDS) + random.choice(COMPANY_SUFFIX)
    p = {
        "real_name": f"{first} {last}", "email": f"{first.lower()}.{i}@{domain_for(company)}",
        "company": company.capitalize(), "company_domain": domain_for(company), "headline": h.format(**fmt),
        "bio": b.format(**fmt), "industry": ind, "seniority": seniority, "function": function,
        "country": country, "city": city, "interests": ", ".join(topics + [cross]),
        "hiring": extra.get("hiring", 0), "board_experience": extra.get("board_experience", 0),
        "investment_focus": extra.get("investment_focus", "").format(**fmt),
        "linkedin_url": f"https://www.linkedin.com/in/{first.lower()}-{last.lower().replace(' ', '')}-{i}",
        "intents": list(intents),
    }
    return p


def insert(conn, p, **flags):
    result = screening.screen_profile(p)
    cols = {k: p.get(k, "") for k in ("email", "real_name", "company", "company_domain", "headline", "bio", "industry",
                                       "seniority", "function", "country", "city", "interests", "investment_focus",
                                       "linkedin_url")}
    cols.update(hiring=p.get("hiring", 0), board_experience=p.get("board_experience", 0),
                password_hash=generate_password_hash(PASSWORD), alias=security.make_alias(),
                email_verified=1, company_verified=1,
                linkedin_status=random.choice(["verified", "verified", "pending"]) if p.get("linkedin_url") else "none",
                status=result["status"], risk_score=result["score"], risk_category=result["category"],
                risk_reasons="; ".join(result["reasons"]))
    cols.update(flags)
    cur = conn.execute(f"INSERT INTO users ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
    for it in p.get("intents", []):
        conn.execute("INSERT INTO intents(user_id,intent) VALUES (?,?)", (cur.lastrowid, it))
    return cur.lastrowid, result


def main():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    conn = db.connect()
    db.init(conn)

    admin_id, _ = insert(conn, {"email": "admin@execconnect.example.com", "real_name": "Platform Admin",
                                "headline": "Trust & Safety", "bio": "Platform administrator", "industry": "Consulting",
                                "seniority": "C-suite", "function": "Operations", "country": "Germany", "city": "Berlin"},
                         is_admin=1, linkedin_status="none")
    demo = {
        "email": "demo@novapay.example.com", "real_name": "Demo Founder", "company": "NovaPay",
        "company_domain": "novapay.example.com", "headline": "Founder & CEO of a seed-stage Fintech startup",
        "bio": "Building embedded finance and payments infrastructure for SMEs in Europe. Raising our seed round and "
               "looking for a mentor who has scaled a fintech, plus investors who know open banking.",
        "industry": "Fintech", "seniority": "Founder", "function": "General Management", "country": "Germany",
        "city": "Berlin", "interests": "payments, embedded finance, open banking, fundraising, generative AI",
        "linkedin_url": "https://www.linkedin.com/in/demo-founder", "intents": ["seeking_funding", "seeking_mentor", "founder_network"],
    }
    demo_id, _ = insert(conn, demo, linkedin_status="verified")

    ids = []
    for i in range(50):
        uid, _ = insert(conn, make_profile(i))
        ids.append(uid)

    print("Scam sign-ups through the screening:")
    for alias, sen, fn, ind, head, bio in SCAM_PROFILES:
        p = {"email": f"{alias.lower().replace(' ', '.')}@spam-{random.randint(100, 999)}.example.com", "real_name": alias,
             "headline": head, "bio": bio, "industry": ind, "seniority": sen, "function": fn, "country": "Germany",
             "city": "Berlin", "interests": "", "intents": ["investment_opportunities"]}
        _, r = insert(conn, p, company_verified=0, linkedin_status="none")
        print(f"  {alias:14s} -> {r['status']:8s} score={r['score']:3d} category={r['category']}")

    # some activity so chat, ratings and the dashboard have data
    berlin = [u for u in ids if conn.execute("SELECT city FROM users WHERE id=?", (u,)).fetchone()[0] == "Berlin"]
    a, b = berlin[0], berlin[1]
    conn.execute("INSERT INTO connections(requester, recipient, status, reason, note) VALUES (?,?,?,?,?)",
                 (demo_id, a, "accepted", "Seeded demo connection", "Hi! Would love to swap notes on fundraising."))
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for sender, text in [(demo_id, "Hi! Thanks for accepting. We're raising a seed round for embedded payments."),
                         (a, "Great to meet you. Happy to share what worked for us - are you free for a call next week?"),
                         (demo_id, "Yes, Tuesday afternoon works. I'll start a call from here.")]:
        conn.execute("INSERT INTO messages(connection_id, sender_id, body) VALUES (?,?,?)", (cid, sender, text))
    conn.execute("INSERT INTO connections(requester, recipient, status, reason, note) VALUES (?,?,?,?,?)",
                 (b, demo_id, "pending", "Seeded incoming request", "Saw you're raising - I invest in fintech, let's talk."))
    for x in ids[:30]:
        y = random.choice([u for u in ids if u != x])
        if conn.execute("SELECT 1 FROM connections WHERE (requester=? AND recipient=?) OR (requester=? AND recipient=?)",
                        (x, y, y, x)).fetchone():
            continue
        conn.execute("INSERT INTO connections(requester, recipient, status) VALUES (?,?,?)",
                     (x, y, random.choice(["accepted", "accepted", "pending"])))
        conn.execute("INSERT OR REPLACE INTO ratings VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                     (x, y, *[random.randint(3, 5) for _ in range(4)]))
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"\nSeeded {n} accounts (50 members, 5 scam attempts, 1 admin, 1 demo user). Password for all: {PASSWORD}")
    print("  Demo user : demo@novapay.example.com")
    print("  Admin     : admin@execconnect.example.com")


if __name__ == "__main__":
    main()
