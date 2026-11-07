"""ExecConnect - verified, pseudonymous networking for executives, founders and investors.

Run:  python seed.py   (creates 50 demo accounts)
      python app.py    (http://localhost:5000)
"""
import os
import secrets
import time
from collections import defaultdict
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import db
import llm
import matching
import screening
import security

BASE = os.path.dirname(os.path.abspath(__file__))
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"   # shows email codes on screen instead of sending email


def load_secret():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


def create_app(db_path=None):
    app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
    app.config.update(SECRET_KEY=load_secret(), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      DB_PATH=db_path or db.DB_PATH, JSON_SORT_KEYS=False)
    conn0 = db.connect(app.config["DB_PATH"])
    db.init(conn0)
    conn0.close()
    failed_logins = defaultdict(list)   # email -> timestamps (simple brute-force lockout)

    # ------------------------------------------------------------ helpers
    def get_db():
        if "db" not in g:
            g.db = db.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        conn = g.pop("db", None)
        if conn:
            conn.close()

    def err(msg, code=400):
        return jsonify({"error": msg}), code

    def body():
        return request.get_json(silent=True) or {}

    @app.before_request
    def csrf_guard():
        # JSON-only API + SameSite cookies: a cross-site form post cannot send application/json.
        if request.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
            if not request.is_json:
                return err("JSON body required", 415)

    def current_user():
        uid = session.get("uid")
        if not uid:
            return None
        return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def login_required(active=True):
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                u = current_user()
                if not u:
                    return err("Please log in.", 401)
                if active:
                    if not u["email_verified"]:
                        return err("Please verify your email first.", 403)
                    if u["status"] != "active":
                        return err("Your account is under review by our trust & safety team.", 403)
                g.user = u
                return fn(*a, **kw)
            return wrapper
        return deco

    def admin_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u or not u["is_admin"]:
                return err("Admins only.", 403)
            g.user = u
            return fn(*a, **kw)
        return wrapper

    def intents_of(uid):
        return [r["intent"] for r in get_db().execute("SELECT intent FROM intents WHERE user_id=?", (uid,))]

    def rating_avgs():
        rows = get_db().execute(
            "SELECT ratee, AVG((responsiveness+intro_quality+mentoring+events)/4.0) a, COUNT(*) n FROM ratings GROUP BY ratee")
        return {r["ratee"]: round(r["a"], 2) for r in rows}

    def as_profile(u):
        d = dict(u)
        d["intents"] = intents_of(u["id"])
        return d

    def public_me(u):
        d = as_profile(u)
        # never expose secrets, and don't show screening details (it would teach scammers to evade it)
        for k in ("password_hash", "email_code", "totp_secret", "risk_score", "risk_category", "risk_reasons"):
            d.pop(k, None)
        d["rating"] = rating_avgs().get(u["id"])
        return d

    def clean_profile_fields(data):
        out = {}
        for k in ("headline", "bio", "company", "industry", "seniority", "function", "country", "city",
                  "investment_focus", "interests", "linkedin_url"):
            if k in data:
                out[k] = str(data[k] or "").strip()[:1200]
        if "hiring" in data:
            out["hiring"] = 1 if data["hiring"] else 0
        if "board_experience" in data:
            out["board_experience"] = 1 if data["board_experience"] else 0
        if "seniority" in out and out["seniority"] not in matching.SENIORITIES:
            out["seniority"] = ""
        return out

    def save_intents(uid, intents):
        conn = get_db()
        conn.execute("DELETE FROM intents WHERE user_id=?", (uid,))
        for i in intents or []:
            if i in matching.INTENTS:
                conn.execute("INSERT OR IGNORE INTO intents(user_id,intent) VALUES (?,?)", (uid, i))

    def connection_for(cid, uid):
        return get_db().execute("SELECT * FROM connections WHERE id=? AND (requester=? OR recipient=?)",
                                (cid, uid, uid)).fetchone()

    # ------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/meta")
    def meta():
        return jsonify({"industries": matching.INDUSTRIES, "functions": matching.FUNCTIONS,
                        "seniorities": matching.SENIORITIES, "intents": matching.INTENTS,
                        "ai_enabled": llm.enabled(), "demo_mode": DEMO_MODE})

    # ------------------------------------------------------------ sign-up & verification
    @app.get("/api/challenge")
    def challenge():
        return jsonify(security.make_challenge(app.config["SECRET_KEY"]))

    @app.post("/api/signup")
    def signup():
        d = body()
        ok, why = security.check_human(app.config["SECRET_KEY"], d.get("challenge_token", ""),
                                       d.get("challenge_answer", ""), d.get("website_url_hp", ""))
        if not ok:
            return err(why)
        if not security.verify_turnstile(d.get("turnstile_token"), request.remote_addr):
            return err("Human verification failed.")
        email = (d.get("email") or "").strip().lower()
        ok, why = security.check_corporate_email(email)
        if not ok:
            return err(why)
        pw = d.get("password") or ""
        if len(pw) < 10 or pw.lower() == pw or not any(c.isdigit() for c in pw):
            return err("Password needs 10+ characters, an uppercase letter and a number.")
        name = (d.get("real_name") or "").strip()
        if len(name) < 3:
            return err("Please enter your full name (kept private).")
        if not d.get("intents"):
            return err("Pick at least one thing you are looking for.")
        if d.get("seniority") not in matching.SENIORITIES:
            return err("This network is for Directors, VPs, C-suite, founders, investors and board members.")
        conn = get_db()
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return err("An account with this email already exists.")
        fields = clean_profile_fields(d)
        if fields.get("linkedin_url") and not security.valid_linkedin(fields["linkedin_url"]):
            return err("LinkedIn URL should look like https://www.linkedin.com/in/your-name")
        result = screening.screen_profile(fields)
        company_ok = security.company_matches_email(email, d.get("company_website", ""))
        code = security.new_email_code()
        cols = dict(fields, email=email, password_hash=generate_password_hash(pw), real_name=name,
                    alias=security.make_alias(), company_domain=security.normalise_domain(d.get("company_website", "")),
                    email_code=code, company_verified=1 if company_ok else 0,
                    linkedin_status="pending" if fields.get("linkedin_url") else "none",
                    status=result["status"], risk_score=result["score"], risk_category=result["category"],
                    risk_reasons="; ".join(result["reasons"]))
        keys = ",".join(cols)
        cur = conn.execute(f"INSERT INTO users ({keys}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        uid = cur.lastrowid
        save_intents(uid, d.get("intents"))
        conn.commit()
        db.log_event(conn, "signup_" + result["status"], uid, result["category"])
        session.clear()
        session["uid"] = uid
        if result["status"] == "blocked":
            session.clear()
            return err("We could not approve this profile. Our network does not allow promotional, MLM, "
                       "trading-signal or similar content.", 403)
        print(f"[email] verification code for {email}: {code}")
        resp = {"ok": True, "status": result["status"], "company_verified": company_ok}
        if DEMO_MODE:
            resp["demo_email_code"] = code
        return jsonify(resp)

    @app.post("/api/verify-email")
    def verify_email():
        u = current_user()
        if not u:
            return err("Please log in.", 401)
        if str(body().get("code", "")).strip() != (u["email_code"] or "-"):
            return err("That code is not correct.")
        conn = get_db()
        conn.execute("UPDATE users SET email_verified=1, email_code=NULL WHERE id=?", (u["id"],))
        conn.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------ login / MFA
    @app.post("/api/login")
    def login():
        d = body()
        email = (d.get("email") or "").strip().lower()
        recent = [t for t in failed_logins[email] if t > time.time() - 300]
        failed_logins[email] = recent
        if len(recent) >= 5:
            return err("Too many failed attempts. Try again in 5 minutes.", 429)
        u = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not u or not check_password_hash(u["password_hash"], d.get("password") or ""):
            failed_logins[email].append(time.time())
            return err("Wrong email or password.", 401)
        if u["status"] == "blocked":
            return err("This account has been blocked.", 403)
        session.clear()
        if u["mfa_enabled"]:
            session["mfa_uid"] = u["id"]
            return jsonify({"mfa_required": True})
        session["uid"] = u["id"]
        failed_logins.pop(email, None)
        return jsonify({"ok": True})

    @app.post("/api/login/mfa")
    def login_mfa():
        uid = session.get("mfa_uid")
        if not uid:
            return err("Start by logging in with your password.", 401)
        u = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not security.verify_totp(u["totp_secret"], body().get("code")):
            return err("Invalid authenticator code.", 401)
        session.clear()
        session["uid"] = uid
        return jsonify({"ok": True})

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.post("/api/mfa/setup")
    @login_required(active=False)
    def mfa_setup():
        secret = security.new_totp_secret()
        session["pending_totp"] = secret
        return jsonify({"secret": secret, "uri": security.totp_uri(secret, g.user["email"])})

    @app.post("/api/mfa/enable")
    @login_required(active=False)
    def mfa_enable():
        secret = session.get("pending_totp")
        if not secret or not security.verify_totp(secret, body().get("code")):
            return err("Code did not match. Check your authenticator app's time and try again.")
        conn = get_db()
        conn.execute("UPDATE users SET totp_secret=?, mfa_enabled=1 WHERE id=?", (secret, g.user["id"]))
        conn.commit()
        session.pop("pending_totp", None)
        return jsonify({"ok": True})

    @app.post("/api/mfa/disable")
    @login_required(active=False)
    def mfa_disable():
        if not security.verify_totp(g.user["totp_secret"], body().get("code")):
            return err("Invalid code.")
        conn = get_db()
        conn.execute("UPDATE users SET totp_secret=NULL, mfa_enabled=0 WHERE id=?", (g.user["id"],))
        conn.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------ profile
    @app.get("/api/me")
    def me():
        u = current_user()
        if not u:
            return jsonify({"user": None})
        return jsonify({"user": public_me(u)})

    @app.put("/api/me")
    @login_required(active=False)
    def update_me():
        d = body()
        fields = clean_profile_fields(d)
        if fields.get("linkedin_url") and not security.valid_linkedin(fields["linkedin_url"]):
            return err("LinkedIn URL should look like https://www.linkedin.com/in/your-name")
        merged = dict(g.user, **fields)
        result = screening.screen_profile(merged)
        status = g.user["status"]
        if status == "active" and not g.user["is_admin"] and result["status"] != "active":
            # edits are re-screened: a clean profile cannot be turned into an ad later
            status = result["status"]
        fields.update(risk_score=result["score"], risk_category=result["category"],
                      risk_reasons="; ".join(result["reasons"]), status=status)
        if "linkedin_url" in fields and fields["linkedin_url"] != g.user["linkedin_url"]:
            fields["linkedin_status"] = "pending" if fields["linkedin_url"] else "none"
        sets = ",".join(f"{k}=?" for k in fields)
        conn = get_db()
        conn.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), g.user["id"]))
        if "intents" in d:
            save_intents(g.user["id"], d["intents"])
        conn.commit()
        return jsonify({"user": public_me(current_user())})

    @app.post("/api/premium")
    @login_required()
    def premium():
        """Demo stand-in for a payment flow: toggles cross-country matching."""
        on = 1 if body().get("enable") else 0
        conn = get_db()
        conn.execute("UPDATE users SET is_premium=? WHERE id=?", (on, g.user["id"]))
        conn.commit()
        db.log_event(conn, "premium_on" if on else "premium_off", g.user["id"])
        return jsonify({"is_premium": bool(on)})

    # ------------------------------------------------------------ matching
    @app.get("/api/matches")
    @login_required()
    def matches():
        conn = get_db()
        me_p = as_profile(g.user)
        filters = {k: request.args.get(k) for k in ("industry", "seniority", "function", "country", "city", "intent")
                   if request.args.get(k)}
        for k in ("hiring", "board", "investment"):
            if request.args.get(k) == "1":
                filters[k] = True
        if filters.get("country") and filters["country"] != g.user["country"] and not g.user["is_premium"]:
            return err("Matching with people in other countries is a Premium feature.", 402)
        taken = {r[0] for r in conn.execute(
            "SELECT CASE WHEN requester=? THEN recipient ELSE requester END FROM connections "
            "WHERE requester=? OR recipient=?", (g.user["id"],) * 3)}
        cands = [as_profile(u) for u in conn.execute("SELECT * FROM users WHERE status='active' AND email_verified=1")
                 if u["id"] not in taken]
        res = matching.rank(me_p, cands, rating_avgs(), filters, limit=int(request.args.get("limit", 20)))
        return jsonify({"matches": res, "premium": bool(g.user["is_premium"]),
                        "ai_explanations": llm.enabled()})

    # ------------------------------------------------------------ connections, chat, calls
    @app.post("/api/connections")
    @login_required()
    def request_connection():
        d = body()
        other = get_db().execute("SELECT * FROM users WHERE id=? AND status='active'", (d.get("user_id"),)).fetchone()
        if not other or other["id"] == g.user["id"]:
            return err("User not found.", 404)
        if other["country"] != g.user["country"] and not g.user["is_premium"]:
            return err("Connecting across countries is a Premium feature.", 402)
        note = (d.get("note") or "").strip()[:500]
        flagged, _ = screening.screen_message(note)
        if flagged:
            return err("Your note looks promotional. Please write a personal note.")
        conn = get_db()
        exists = conn.execute("SELECT 1 FROM connections WHERE (requester=? AND recipient=?) OR (requester=? AND recipient=?)",
                              (g.user["id"], other["id"], other["id"], g.user["id"])).fetchone()
        if exists:
            return err("You already have a connection request with this person.")
        conn.execute("INSERT INTO connections(requester, recipient, score, reason, note) VALUES (?,?,?,?,?)",
                     (g.user["id"], other["id"], d.get("score", 0), d.get("reason", ""), note))
        conn.commit()
        db.log_event(conn, "connect_request", g.user["id"])
        return jsonify({"ok": True})

    def describe(c, uid):
        conn = get_db()
        other_id = c["recipient"] if c["requester"] == uid else c["requester"]
        o = conn.execute("SELECT * FROM users WHERE id=?", (other_id,)).fetchone()
        revealed = bool(c["reveal_requester"] and c["reveal_recipient"])
        i_revealed = bool(c["reveal_requester"] if c["requester"] == uid else c["reveal_recipient"])
        last = conn.execute("SELECT body, created_at FROM messages WHERE connection_id=? ORDER BY id DESC LIMIT 1",
                            (c["id"],)).fetchone()
        rated = conn.execute("SELECT 1 FROM ratings WHERE rater=? AND ratee=?", (uid, other_id)).fetchone()
        return {"id": c["id"], "status": c["status"], "direction": "outgoing" if c["requester"] == uid else "incoming",
                "other": {"id": o["id"], "alias": o["alias"], "headline": o["headline"], "industry": o["industry"],
                          "seniority": o["seniority"], "city": o["city"], "country": o["country"],
                          "real_name": o["real_name"] if revealed else None,
                          "company": o["company"] if revealed else None,
                          "linkedin_url": o["linkedin_url"] if revealed else None},
                "note": c["note"], "reason": c["reason"], "revealed": revealed, "i_revealed": i_revealed,
                "room": c["room"], "last_message": dict(last) if last else None, "rated": bool(rated)}

    @app.get("/api/connections")
    @login_required()
    def list_connections():
        rows = get_db().execute("SELECT * FROM connections WHERE (requester=? OR recipient=?) AND status!='declined' "
                                "ORDER BY id DESC", (g.user["id"], g.user["id"])).fetchall()
        return jsonify({"connections": [describe(c, g.user["id"]) for c in rows]})

    @app.post("/api/connections/<int:cid>/respond")
    @login_required()
    def respond(cid):
        c = connection_for(cid, g.user["id"])
        if not c or c["recipient"] != g.user["id"] or c["status"] != "pending":
            return err("Request not found.", 404)
        status = "accepted" if body().get("accept") else "declined"
        conn = get_db()
        conn.execute("UPDATE connections SET status=? WHERE id=?", (status, cid))
        conn.commit()
        db.log_event(conn, "connect_" + status, g.user["id"])
        return jsonify({"ok": True, "status": status})

    @app.post("/api/connections/<int:cid>/reveal")
    @login_required()
    def reveal(cid):
        c = connection_for(cid, g.user["id"])
        if not c or c["status"] != "accepted":
            return err("Connection not found.", 404)
        col = "reveal_requester" if c["requester"] == g.user["id"] else "reveal_recipient"
        conn = get_db()
        conn.execute(f"UPDATE connections SET {col}=1 WHERE id=?", (cid,))
        conn.commit()
        return jsonify(describe(connection_for(cid, g.user["id"]), g.user["id"]))

    @app.get("/api/connections/<int:cid>/messages")
    @login_required()
    def get_messages(cid):
        c = connection_for(cid, g.user["id"])
        if not c or c["status"] != "accepted":
            return err("Chat is available after the request is accepted.", 403)
        after = int(request.args.get("after", 0))
        rows = get_db().execute("SELECT id, sender_id, body, flagged, created_at FROM messages "
                                "WHERE connection_id=? AND id>? ORDER BY id", (cid, after))
        return jsonify({"messages": [dict(r, mine=r["sender_id"] == g.user["id"]) for r in rows]})

    @app.post("/api/connections/<int:cid>/messages")
    @login_required()
    def send_message(cid):
        c = connection_for(cid, g.user["id"])
        if not c or c["status"] != "accepted":
            return err("Chat is available after the request is accepted.", 403)
        text = (body().get("body") or "").strip()[:2000]
        if not text:
            return err("Empty message.")
        flagged, _ = screening.screen_message(text)
        conn = get_db()
        conn.execute("INSERT INTO messages(connection_id, sender_id, body, flagged) VALUES (?,?,?,?)",
                     (cid, g.user["id"], text, 1 if flagged else 0))
        conn.commit()
        if flagged:
            db.log_event(conn, "message_flagged", g.user["id"], text[:120])
        return jsonify({"ok": True, "flagged": flagged})

    @app.post("/api/connections/<int:cid>/call")
    @login_required()
    def call(cid):
        c = connection_for(cid, g.user["id"])
        if not c or c["status"] != "accepted":
            return err("Calls are available after the request is accepted.", 403)
        room = c["room"]
        if not room:
            room = "ExecConnect-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "")
            conn = get_db()
            conn.execute("UPDATE connections SET room=? WHERE id=?", (room, cid))
            conn.commit()
        # Jitsi: browser video call, no phone numbers or emails exchanged
        return jsonify({"url": f"https://meet.jit.si/{room}"})

    # ------------------------------------------------------------ ratings
    @app.post("/api/ratings")
    @login_required()
    def rate():
        d = body()
        other = d.get("user_id")
        conn = get_db()
        ok = conn.execute("SELECT 1 FROM connections WHERE status='accepted' AND ((requester=? AND recipient=?) OR "
                          "(requester=? AND recipient=?))", (g.user["id"], other, other, g.user["id"])).fetchone()
        if not ok:
            return err("You can only rate people you are connected with.", 403)
        vals = []
        for k in ("responsiveness", "intro_quality", "mentoring", "events"):
            try:
                v = int(d.get(k))
            except (TypeError, ValueError):
                return err("Ratings must be 1-5.")
            if not 1 <= v <= 5:
                return err("Ratings must be 1-5.")
            vals.append(v)
        conn.execute("INSERT OR REPLACE INTO ratings(rater, ratee, responsiveness, intro_quality, mentoring, events) "
                     "VALUES (?,?,?,?,?,?)", (g.user["id"], other, *vals))
        conn.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------ admin dashboard
    @app.get("/api/admin/stats")
    @admin_required
    def stats():
        conn = get_db()
        q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]
        one = lambda sql: conn.execute(sql).fetchone()[0]
        return jsonify({
            "totals": {
                "users": one("SELECT COUNT(*) FROM users"),
                "active": one("SELECT COUNT(*) FROM users WHERE status='active'"),
                "in_review": one("SELECT COUNT(*) FROM users WHERE status='review'"),
                "blocked": one("SELECT COUNT(*) FROM users WHERE status='blocked'"),
                "mfa": one("SELECT COUNT(*) FROM users WHERE mfa_enabled=1"),
                "premium": one("SELECT COUNT(*) FROM users WHERE is_premium=1"),
                "connections": one("SELECT COUNT(*) FROM connections"),
                "accepted": one("SELECT COUNT(*) FROM connections WHERE status='accepted'"),
                "messages": one("SELECT COUNT(*) FROM messages"),
                "flagged_messages": one("SELECT COUNT(*) FROM messages WHERE flagged=1"),
            },
            "by_industry": q("SELECT industry k, COUNT(*) n FROM users WHERE status='active' GROUP BY industry ORDER BY n DESC"),
            "by_seniority": q("SELECT seniority k, COUNT(*) n FROM users WHERE status='active' GROUP BY seniority ORDER BY n DESC"),
            "by_country": q("SELECT country k, COUNT(*) n FROM users WHERE status='active' GROUP BY country ORDER BY n DESC"),
            "by_intent": [{"k": matching.INTENTS.get(r["k"], r["k"]), "n": r["n"]} for r in
                          q("SELECT i.intent k, COUNT(*) n FROM intents i JOIN users u ON u.id=i.user_id "
                            "WHERE u.status='active' GROUP BY i.intent ORDER BY n DESC")],
            "top_interests": top_interests(conn),
            "risk": q("SELECT risk_category k, COUNT(*) n FROM users WHERE risk_category!='ok' GROUP BY risk_category"),
        })

    def top_interests(conn):
        counts = defaultdict(int)
        for r in conn.execute("SELECT interests FROM users WHERE status='active'"):
            for x in (r[0] or "").split(","):
                if x.strip():
                    counts[x.strip().lower()] += 1
        return [{"k": k, "n": n} for k, n in sorted(counts.items(), key=lambda kv: -kv[1])[:12]]

    @app.get("/api/admin/review")
    @admin_required
    def review_queue():
        rows = get_db().execute(
            "SELECT id, alias, real_name, email, headline, bio, status, risk_score, risk_category, risk_reasons, "
            "linkedin_url, linkedin_status, company_verified FROM users "
            "WHERE status IN ('review','blocked') OR linkedin_status='pending' ORDER BY risk_score DESC")
        return jsonify({"users": [dict(r) for r in rows]})

    @app.post("/api/admin/users/<int:uid>")
    @admin_required
    def admin_action(uid):
        action = body().get("action")
        sql = {"approve": "UPDATE users SET status='active' WHERE id=?",
               "block": "UPDATE users SET status='blocked' WHERE id=?",
               "verify_linkedin": "UPDATE users SET linkedin_status='verified' WHERE id=?"}.get(action)
        if not sql:
            return err("Unknown action.")
        conn = get_db()
        conn.execute(sql, (uid,))
        conn.commit()
        db.log_event(conn, "admin_" + action, uid)
        return jsonify({"ok": True})

    return app


app = create_app()

if __name__ == "__main__":
    print("ExecConnect running on http://localhost:5000  (AI features:", "ON" if llm.enabled() else "OFF - rule/TF-IDF mode", ")")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
