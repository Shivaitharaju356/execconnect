"""Security helpers: TOTP MFA, human verification, email/company checks, aliases."""
import base64
import hashlib
import hmac
import os
import random
import re
import secrets
import struct
import time
from urllib.parse import quote

import requests

# ---------------------------------------------------------------- TOTP (RFC 6238)

def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret, counter, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret, at=None, step=30):
    return _hotp(secret, int((at or time.time()) // step))


def verify_totp(secret, code, window=1, step=30):
    """Accept the current code and one step either side (clock drift)."""
    if not secret or not code or not str(code).isdigit():
        return False
    counter = int(time.time() // step)
    return any(hmac.compare_digest(_hotp(secret, counter + d), str(code).strip()) for d in range(-window, window + 1))


def totp_uri(secret, email, issuer="ExecConnect"):
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


# ---------------------------------------------------------------- Human verification

def make_challenge(secret_key):
    """Arithmetic challenge signed with the server key; also records issue time."""
    a, b = random.randint(2, 12), random.randint(2, 12)
    issued = int(time.time())
    payload = f"{a}:{b}:{issued}"
    sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
    return {"question": f"What is {a} + {b}?", "token": f"{payload}:{sig}"}


def check_human(secret_key, token, answer, honeypot, min_seconds=3, max_seconds=1800):
    """Returns (ok, reason). Layers: honeypot field, signed challenge, fill-time check, optional Turnstile."""
    if honeypot:
        return False, "Bot detected (hidden field was filled)."
    try:
        a, b, issued, sig = token.split(":")
        payload = f"{a}:{b}:{issued}"
        good = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(good, sig):
            return False, "Invalid challenge."
        elapsed = time.time() - int(issued)
        if elapsed < min_seconds:
            return False, "Form submitted too fast - looks automated."
        if elapsed > max_seconds:
            return False, "Challenge expired, please reload."
        if str(answer).strip() != str(int(a) + int(b)):
            return False, "Wrong answer to the human check."
    except (ValueError, AttributeError):
        return False, "Invalid challenge."
    return True, ""


def verify_turnstile(token, remote_ip=None):
    """Optional Cloudflare Turnstile check, used only when TURNSTILE_SECRET is set."""
    secret = os.environ.get("TURNSTILE_SECRET")
    if not secret:
        return True
    try:
        r = requests.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                          data={"secret": secret, "response": token, "remoteip": remote_ip}, timeout=5)
        return bool(r.json().get("success"))
    except requests.RequestException:
        return False


# ---------------------------------------------------------------- Email / company verification

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.de", "outlook.com", "hotmail.com", "live.com",
    "msn.com", "aol.com", "icloud.com", "me.com", "gmx.de", "gmx.net", "gmx.com", "web.de", "t-online.de",
    "proton.me", "protonmail.com", "mail.com", "yandex.com", "yandex.ru", "zoho.com", "rediffmail.com",
}
DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "temp-mail.org",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "dispostable.com", "maildrop.cc",
}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
LINKEDIN_RE = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]{3,100}/?$")


def email_domain(email):
    return email.rsplit("@", 1)[-1].lower().strip()


def check_corporate_email(email):
    """Returns (ok, reason). Only work emails are accepted."""
    if not EMAIL_RE.match(email or ""):
        return False, "Please enter a valid email address."
    d = email_domain(email)
    if d in DISPOSABLE_DOMAINS:
        return False, "Disposable email addresses are not allowed."
    if d in FREE_EMAIL_DOMAINS:
        return False, "Please use your corporate email (free providers like Gmail are not accepted)."
    return True, ""


def normalise_domain(website):
    w = (website or "").lower().strip()
    w = re.sub(r"^https?://", "", w)
    w = w.split("/")[0]
    return w[4:] if w.startswith("www.") else w


def company_matches_email(email, company_website):
    """Company verification: the email domain must belong to the company's website domain."""
    d, site = email_domain(email), normalise_domain(company_website)
    return bool(site) and (d == site or d.endswith("." + site))


def valid_linkedin(url):
    return bool(LINKEDIN_RE.match((url or "").strip()))


def new_email_code():
    return f"{secrets.randbelow(10**6):06d}"


# ---------------------------------------------------------------- Pseudonymous aliases

ADJ = ["Bold", "Swift", "Quiet", "Bright", "Steady", "Keen", "Noble", "Clear", "Prime", "Lucid", "Agile", "True"]
NOUN = ["Falcon", "Cedar", "Harbor", "Summit", "Atlas", "Orbit", "Beacon", "Delta", "Granite", "Vector", "Meridian", "Compass"]


def make_alias(seniority="", industry=""):
    base = f"{random.choice(ADJ)} {random.choice(NOUN)}"
    return f"{base} {random.randint(10, 99)}"
