#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mostaql.com Mobile Project Scraper
Scrapes mostaql.com for new mobile/Flutter/Android/iOS projects and notifies via Telegram.
"""

import json
import logging
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = "https://mostaql.com/projects"
PARAMS = {"category": "development", "sort": "latest"}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SEEN_IDS_FILE = "seen_ids.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://mostaql.com/",
}

# ── Arabic + English mobile keywords ─────────────────────────────────────────
MOBILE_KEYWORDS = [
    # Mobile (Arabic)
    "تطبيق موبايل",
    "تطبيق جوال",
    "تطبيق للجوال",
    "تطبيق للموبايل",
    "موبايل",
    "جوال",
    # Android (Arabic + English)
    "أندرويد",
    "اندرويد",
    "android",
    # Flutter (Arabic + English)
    "فلاتر",
    "flutter",
    # iOS (Arabic + English)
    "ios",
    "آيفون",
    "ايفون",
    "ايوس",
    # React Native (Arabic + English)
    "react native",
    "ريأكت نيتف",
    "ريأكت نيتيف",
    # Other frameworks
    "kotlin",
    "swift",
    "xamarin",
]


# ── Seen IDs persistence ──────────────────────────────────────────────────────
def load_seen_ids() -> set:
    try:
        with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen_ids(seen_ids: set) -> None:
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


# ── Scraping ──────────────────────────────────────────────────────────────────
def fetch_projects(session: requests.Session) -> list:
    try:
        resp = session.get(BASE_URL, params=PARAMS, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch Mostaql page: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Primary selector: confirmed from Mostaql's HTML structure
    rows = soup.find_all("tr", class_="project-row")

    # Fallback: card-style layout
    if not rows:
        rows = soup.find_all("div", class_=re.compile(r"project", re.I))

    projects = []
    for row in rows:
        project = _parse_project_row(row)
        if project:
            projects.append(project)

    logging.info(f"Fetched {len(projects)} projects from Mostaql")
    return projects


def _parse_project_row(row) -> dict:
    try:
        # Project URL & ID — URLs are absolute: https://mostaql.com/project/1219203-slug
        title_tag = row.find("a", href=re.compile(r"/project/\d+"))
        if not title_tag:
            return None

        url = title_tag["href"].split("?")[0]

        match = re.search(r"/project/(\d+)", url)
        if not match:
            return None
        project_id = match.group(1)

        # Title
        title = title_tag.get_text(strip=True)

        # Description — inside <p class="project__brief"> → <a class="details-url">
        brief_tag = row.find("p", class_=re.compile(r"project__brief", re.I))
        if brief_tag:
            inner_a = brief_tag.find("a")
            description = (inner_a or brief_tag).get_text(strip=True)[:300]
        else:
            description = ""

        # Bids — 3rd <li class="text-muted"> in <ul class="project__meta">
        # Text looks like "14 عرض" or "8 عروض"
        meta_ul = row.find("ul", class_=re.compile(r"project__meta", re.I))
        bids = "0"
        if meta_ul:
            lis = meta_ul.find_all("li")
            if len(lis) >= 3:
                bids_text = lis[2].get_text(strip=True)
                bids_match = re.search(r"\d+", bids_text)
                bids = bids_match.group() if bids_match else "0"

        return {
            "id": project_id,
            "title": title,
            "description": description,
            "bids": bids,
            "url": url,
        }
    except Exception as e:
        logging.warning(f"Failed to parse project row: {e}")
        return None


# ── Keyword filtering ─────────────────────────────────────────────────────────
def is_mobile_project(project: dict) -> bool:
    haystack = (project["title"] + " " + project["description"]).lower()
    return any(kw.lower() in haystack for kw in MOBILE_KEYWORDS)


# ── Telegram notification ─────────────────────────────────────────────────────
def send_telegram(project: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Telegram credentials not set in environment variables.")
        return False

    text = (
        f"🆕 مشروع جديد على مستقل\n\n"
        f"📌 العنوان: {project['title']}\n"
        f"🏷️ عدد العروض: {project['bids']}\n"
        f"📝 {project['description']}\n"
        f"🔗 {project['url']}"
    )
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(api_url, json=payload, timeout=15)
        resp.raise_for_status()
        logging.info(f"Telegram notification sent for project {project['id']}")
        return True
    except requests.RequestException as e:
        logging.error(f"Telegram send failed for project {project['id']}: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    seen_ids = load_seen_ids()
    logging.info(f"Loaded {len(seen_ids)} previously seen project IDs")

    session = requests.Session()
    projects = fetch_projects(session)

    if not projects:
        logging.warning("No projects fetched. Exiting without changes.")
        sys.exit(0)

    new_matches = 0
    ids_changed = False

    for project in projects:
        pid = project["id"]

        if pid in seen_ids:
            continue  # Already processed

        # Mark ALL new projects as seen to avoid re-evaluating on next run
        seen_ids.add(pid)
        ids_changed = True

        if not is_mobile_project(project):
            logging.info(f"Skipped (no mobile keywords): [{pid}] {project['title'][:60]}")
            continue

        logging.info(f"New mobile project: [{pid}] {project['title'][:60]}")
        send_telegram(project)
        new_matches += 1
        time.sleep(1)  # Avoid Telegram rate limiting

    if ids_changed:
        save_seen_ids(seen_ids)
        logging.info(f"seen_ids.json updated ({len(seen_ids)} total IDs)")

    logging.info(f"Done. {new_matches} new mobile project(s) notified.")


if __name__ == "__main__":
    main()
