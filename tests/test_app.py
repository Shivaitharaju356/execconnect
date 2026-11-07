"""End-to-end API tests:  python -m pytest -q"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module  # noqa: E402
import matching  # noqa: E402
import screening  # noqa: E402
import security  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = app_module.create_app(str(tmp_path / "t.db"))
    a.testing = True
    return a.test_client()


def human(c, monkeypatch):
    ch = c.get("/api/challenge").get_json()
    a, b, issued, sig = ch["token"].split(":")
    # pretend the form took 5 seconds to fill in
    monkeypatch.setattr(security.time, "time", lambda: int(issued) + 5)
    return {"challenge_token": ch["token"], "challenge_answer": str(int(a) + int(b))}


def signup(c, monkeypatch, **over):
    d = {"real_name": "Jane Doe", "email": "jane@acme-corp.com", "password": "Sup3rSecret!",
         "company_website": "https://www.acme-corp.com", "headline": "VP Product at a SaaS scale-up",
         "seniority": "VP", "function": "Product", "industry": "SaaS", "country": "Germany", "city": "Berlin",
         "interests": "product-led growth, B2B SaaS, generative AI", "bio": "Building B2B products.",
         "intents": ["seeking_mentor", "strategic_partner"]}
    d.update(human(c, monkeypatch))
    d.update(over)
    return c.post("/api/signup", json=d)


def test_rejects_free_email_and_bots(client, monkeypatch):
    r = signup(client, monkeypatch, email="jane@gmail.com")
    assert r.status_code == 400 and "corporate" in r.get_json()["error"]
    r = signup(client, monkeypatch, website_url_hp="http://spam")
    assert "Bot" in r.get_json()["error"]
    r = signup(client, monkeypatch, challenge_answer="999")
    assert "human check" in r.get_json()["error"]


def test_too_fast_submission_is_rejected(client):
    ch = client.get("/api/challenge").get_json()
    ok, why = security.check_human(client.application.config["SECRET_KEY"], ch["token"], "0", "")
    assert not ok


def test_full_flow_signup_verify_mfa_login(client, monkeypatch):
    r = signup(client, monkeypatch)
    j = r.get_json()
    assert r.status_code == 200 and j["company_verified"] is True
    assert client.get("/api/matches").status_code == 403          # must verify email first
    assert client.post("/api/verify-email", json={"code": "000000" if j["demo_email_code"] != "000000" else "1"}).status_code == 400
    assert client.post("/api/verify-email", json={"code": j["demo_email_code"]}).status_code == 200
    me = client.get("/api/me").get_json()["user"]
    assert "password_hash" not in me and "totp_secret" not in me and "risk_score" not in me
    setup = client.post("/api/mfa/setup", json={}).get_json()
    assert client.post("/api/mfa/enable", json={"code": security.totp_now(setup["secret"])}).status_code == 200
    client.post("/api/logout", json={})
    r = client.post("/api/login", json={"email": "jane@acme-corp.com", "password": "Sup3rSecret!"})
    assert r.get_json() == {"mfa_required": True}
    assert client.get("/api/matches").status_code == 401          # password alone is not enough
    assert client.post("/api/login/mfa", json={"code": "123456"}).status_code in (200, 401)
    client.post("/api/logout", json={})
    client.post("/api/login", json={"email": "jane@acme-corp.com", "password": "Sup3rSecret!"})
    assert client.post("/api/login/mfa", json={"code": security.totp_now(setup["secret"])}).status_code == 200
    assert client.get("/api/matches").status_code == 200


def test_scam_signup_blocked(client, monkeypatch):
    r = signup(client, monkeypatch, email="boss@fx-kings.com",
               bio="Forex signals with guaranteed profits, double your money. WhatsApp me +49 151 2345 6789")
    assert r.status_code == 403


def test_bruteforce_lockout(client, monkeypatch):
    signup(client, monkeypatch)
    for _ in range(5):
        client.post("/api/login", json={"email": "jane@acme-corp.com", "password": "wrong"})
    r = client.post("/api/login", json={"email": "jane@acme-corp.com", "password": "Sup3rSecret!"})
    assert r.status_code == 429


def test_csrf_guard_requires_json(client):
    r = client.post("/api/login", data={"email": "x", "password": "y"})
    assert r.status_code == 415


def test_screening_examples():
    assert screening.screen_profile({"bio": "CFO advising fintech founders on fundraising"})["status"] == "active"
    assert screening.screen_profile({"bio": "Join my team! passive income, be your own boss"})["status"] != "active"
    assert screening.screen_profile({"bio": "send to 0x52908400098527886E0F7030069857D2E4169EE7 for daily profit"})["status"] != "active"


def test_matching_prefers_complementary_intent_and_respects_country():
    me = {"id": 1, "intents": ["seeking_funding"], "interests": "payments, fintech", "industry": "Fintech",
          "seniority": "Founder", "country": "Germany", "city": "Berlin", "is_premium": 0}
    base = {"status": "active", "industry": "Fintech", "interests": "payments, fintech", "country": "Germany",
            "city": "Berlin", "seniority": "Investor", "alias": "x"}
    investor = dict(base, id=2, intents=["investment_opportunities"])
    peer = dict(base, id=3, intents=["strategic_partner"])
    abroad = dict(base, id=4, intents=["investment_opportunities"], country="India")
    res = matching.rank(me, [investor, peer, abroad], {}, use_llm=False)
    assert [r["id"] for r in res] == [2, 3]                      # India hidden for free users
    res = matching.rank(dict(me, is_premium=1), [investor, peer, abroad], {}, use_llm=False)
    assert 4 in [r["id"] for r in res]


def test_connection_chat_reveal_and_rating(client, monkeypatch):
    def make(email, name):
        client.post("/api/logout", json={})
        j = signup(client, monkeypatch, email=email, real_name=name).get_json()
        client.post("/api/verify-email", json={"code": j["demo_email_code"]})
        return client.get("/api/me").get_json()["user"]["id"]
    a = make("a@alpha-co.com", "Alice Alpha")
    b = make("b@beta-co.com", "Bob Beta")          # logged in as Bob
    assert client.post("/api/connections", json={"user_id": a, "note": "Hi Alice"}).status_code == 200
    assert client.post("/api/connections", json={"user_id": a, "note": "Again"}).status_code == 400
    client.post("/api/logout", json={})
    client.post("/api/login", json={"email": "a@alpha-co.com", "password": "Sup3rSecret!"})
    cid = client.get("/api/connections").get_json()["connections"][0]["id"]
    assert client.get(f"/api/connections/{cid}/messages").status_code == 403   # not accepted yet
    client.post(f"/api/connections/{cid}/respond", json={"accept": True})
    assert client.post(f"/api/connections/{cid}/messages", json={"body": "Hello Bob"}).get_json()["flagged"] is False
    assert client.post(f"/api/connections/{cid}/messages", json={"body": "DM me for my forex signals, guaranteed profits"}).get_json()["flagged"]
    conn = client.get("/api/connections").get_json()["connections"][0]
    assert conn["other"]["real_name"] is None                 # still private
    client.post(f"/api/connections/{cid}/reveal", json={})
    assert client.post(f"/api/connections/{cid}/call", json={}).get_json()["url"].startswith("https://meet.jit.si/")
    assert client.post("/api/ratings", json={"user_id": b, "responsiveness": 5, "intro_quality": 4, "mentoring": 4, "events": 3}).status_code == 200
    assert client.post("/api/ratings", json={"user_id": b, "responsiveness": 9, "intro_quality": 4, "mentoring": 4, "events": 3}).status_code == 400
    client.post("/api/logout", json={})
    client.post("/api/login", json={"email": "b@beta-co.com", "password": "Sup3rSecret!"})
    client.post(f"/api/connections/{cid}/reveal", json={})
    conn = client.get("/api/connections").get_json()["connections"][0]
    assert conn["revealed"] and conn["other"]["real_name"] == "Alice Alpha"


def test_totp_matches_rfc6238_vector():
    # RFC 6238 test secret "12345678901234567890", T=59 -> 94287082 (8 digits) -> last 6 = 287082
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert security.totp_now(secret, at=59) == "287082"
