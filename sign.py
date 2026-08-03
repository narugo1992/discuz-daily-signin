#!/usr/bin/env python3
"""Daily check-in bot for a Discuz! forum running the dsu_paulsign plugin.

Authenticates with a username and password, then submits the daily check-in
with a randomly picked mood. The target site, credentials and everything else
site-specific come from environment variables, so nothing about the forum is
hard-coded here.

Environment variables:
    DZ_BASE_URL  Forum base URL, trailing slash included (required)
    DZ_USER      Username (required)
    DZ_PASS      Password (required)
    DZ_QUESTION  Security question id, "0" when unset (default: "0")
    DZ_ANSWER    Security question answer (default: empty)
    DZ_MOOD      Force a specific mood code instead of picking one at random
    DZ_DRY_RUN   When set to "1", log in and report status without checking in

Exit codes: 0 on success or already-checked-in, 1 on failure.
"""

from __future__ import annotations

import os
import random
import re
import sys
import time
from typing import NoReturn, Optional

import requests

# Mood codes offered by dsu_paulsign, with their upstream labels for logging.
MOODS = {
    "kx": "happy",
    "ng": "sad",
    "ym": "gloomy",
    "wl": "bored",
    "nu": "angry",
    "ch": "sweating",
    "fd": "striving",
    "yl": "lazy",
    "shuai": "unlucky",
}

# Discuz! and dsu_paulsign emit these markers. They are properties of the
# software, not of any particular forum, so matching on them is portable.
MARKER_LOGIN_OK = "欢迎您回来"  # "welcome back"
MARKER_ALREADY = "您今天已经签到过了"  # "already checked in today"
MARKER_ALREADY_SHORT = "已经签到"  # "already checked in"
MARKER_SIGN_OK = "签到成功"  # "check-in succeeded"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

TIMEOUT = 30
RETRIES = 3
RETRY_WAIT = 20


def env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        fail(f"missing required environment variable {name}")
    return value


def log(message: str) -> None:
    print(message, flush=True)


def summary(message: str) -> None:
    """Append a line to the workflow run summary when running under Actions."""
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")


def fail(message: str) -> NoReturn:
    log(f"::error::{message}")
    summary(f"- Failed: {message}")
    sys.exit(1)


def decode(response: requests.Response) -> str:
    """Decode a response body, honouring the charset the forum declares.

    Older Discuz! installations are frequently GBK rather than UTF-8, and they
    do not always advertise the charset in the Content-Type header, so fall
    back to the meta tag and then to a short list of candidates.
    """
    raw = response.content
    candidates = []

    declared = response.encoding if "charset=" in response.headers.get("content-type", "") else None
    if declared:
        candidates.append(declared)

    match = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
    if match:
        candidates.append(match.group(1).decode("ascii", "ignore"))

    candidates += ["utf-8", "gbk"]

    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def extract(pattern: str, html: str, what: str) -> str:
    match = re.search(pattern, html, re.I)
    if not match:
        fail(f"could not extract {what}; the page layout may have changed")
    return match.group(1)


def plain(html: str) -> str:
    """Flatten an HTML or Discuz! ajax fragment into a single log-safe line."""
    text = re.sub(r"<!\[CDATA\[|\]\]>", " ", html)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Forum:
    def __init__(self, base_url: str) -> None:
        self.base = base_url if base_url.endswith("/") else base_url + "/"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                # A Referer is mandatory, not cosmetic. Some installations sit
                # behind a scraper filter that answers refererless requests with
                # HTTP 200 and a zero-length body, which looks like a layout
                # change rather than a block. Defaulting it here means every
                # request carries one.
                "Referer": self.base,
            }
        )

    def get(self, path: str, referer: Optional[str] = None) -> str:
        headers = {"Referer": self.base + referer} if referer else {}
        return decode(
            self.session.get(self.base + path, headers=headers, timeout=TIMEOUT)
        )

    def post(self, path: str, data: dict, referer: Optional[str] = None) -> str:
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if referer:
            headers["Referer"] = self.base + referer
        response = self.session.post(
            self.base + path, data=data, headers=headers, timeout=TIMEOUT
        )
        return decode(response)

    def login(self, username: str, password: str, question: str, answer: str) -> None:
        """Log in through the standard Discuz! member.php login form.

        Both a per-page formhash and a per-form loginhash are required, and
        both are only obtainable from the freshly fetched login page.
        """
        page = self.get("member.php?mod=logging&action=login")
        if not page.strip():
            fail(
                "the login page came back empty; the site answered but sent no "
                "body, which usually means a scraper filter rejected the request"
            )
        formhash = extract(r'name="formhash" value="(\w+)"', page, "login formhash")
        loginhash = extract(r"loginhash=(\w+)", page, "loginhash")

        body = self.post(
            "member.php?mod=logging&action=login"
            f"&loginsubmit=yes&loginhash={loginhash}&inajax=1",
            data={
                "formhash": formhash,
                "referer": self.base,
                "loginfield": "username",
                "username": username,
                "password": password,
                "questionid": question,
                "answer": answer,
                "cookietime": "2592000",
            },
            referer="member.php?mod=logging&action=login",
        )

        if MARKER_LOGIN_OK not in body:
            detail = plain(body)[:300] or "empty response"
            fail(
                "login rejected -- check the credentials, or the account may be "
                f"rate limited or require a security question. Response: {detail}"
            )
        log("Logged in.")

    def check_in(self, mood: str) -> str:
        """Fetch the check-in page, then submit unless today is already done.

        The GET is unavoidable because the formhash lives on that page, so
        using it to short-circuit an already-completed day is free. That makes
        the whole run idempotent and safe to repeat.
        """
        page = self.get("plugin.php?id=dsu_paulsign:sign")
        if MARKER_ALREADY in page:
            return "Already checked in today; nothing to do."

        formhash = extract(r'name="formhash" value="(\w+)"', page, "check-in formhash")
        body = self.post(
            "plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&inajax=1",
            data={"formhash": formhash, "qdxq": mood, "qdmode": "1"},
            referer="plugin.php?id=dsu_paulsign:sign",
        )
        text = plain(body)

        if MARKER_SIGN_OK in text:
            return f"Checked in: {text}"
        if MARKER_ALREADY_SHORT in text:
            return "Already checked in today; nothing to do."
        raise RuntimeError(f"unrecognised response: {text[:300] or 'empty response'}")


def main() -> None:
    base_url = env("DZ_BASE_URL")
    username = env("DZ_USER")
    password = env("DZ_PASS")
    # Treat an unset and an empty variable alike: CI passes absent secrets
    # through as empty strings, and "0" is what the form needs when no security
    # question is configured on the account.
    question = os.getenv("DZ_QUESTION") or "0"
    answer = os.getenv("DZ_ANSWER") or ""

    forced = os.getenv("DZ_MOOD", "").strip()
    if forced and forced not in MOODS:
        fail(f"DZ_MOOD must be one of: {', '.join(sorted(MOODS))}")
    mood = forced or random.choice(list(MOODS))
    log(f"Mood for this run: {mood} ({MOODS[mood]})")

    forum = Forum(base_url)

    last_error: Optional[Exception] = None
    for attempt in range(1, RETRIES + 1):
        try:
            forum.login(username, password, question, answer)
            if os.getenv("DZ_DRY_RUN") == "1":
                log("Dry run requested; skipping the check-in submission.")
                summary("- Dry run: login succeeded, check-in skipped.")
                return
            result = forum.check_in(mood)
            log(result)
            summary(f"- {result} (mood: {mood}/{MOODS[mood]})")
            return
        except (requests.RequestException, RuntimeError) as error:
            last_error = error
            log(f"Attempt {attempt}/{RETRIES} failed: {error}")
            if attempt < RETRIES:
                time.sleep(RETRY_WAIT)

    fail(f"giving up after {RETRIES} attempts: {last_error}")


if __name__ == "__main__":
    main()
