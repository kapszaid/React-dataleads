from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Union
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
GROUPS_FILE = DATA_DIR / "groups.json"
POSTS_FILE = DATA_DIR / "posts.json"
LOGS_FILE = DATA_DIR / "logs.json"

_file_lock = threading.Lock()

# ── MONGODB & LOCAL STORAGE SETUP ─────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "DataLeads")

mongo_db = None
if MONGO_URI and not MONGO_URI.startswith("your_"):
    try:
        from pymongo import MongoClient
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        mongo_db = _client[MONGO_DB_NAME]
    except Exception:
        mongo_db = None


def _read_json(filepath: Path, default_val=None):
    if default_val is None:
        default_val = []
    if not filepath.exists():
        return default_val
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_val


def _write_json(filepath: Path, data):
    # Only write to disk if MongoDB Atlas is NOT connected
    if mongo_db is not None:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _file_lock:
        temp_file = filepath.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_file.replace(filepath)


# ── SESSIONS IN MONGODB ──────────────────────────────────────────────────────

def save_account_session_state(account_id: str, cookies: list[dict] = None, storage_state: dict = None):
    if mongo_db is not None:
        try:
            update_fields = {"updated_at": datetime.now().isoformat()}
            if cookies is not None:
                update_fields["cookies"] = cookies
            if storage_state is not None:
                update_fields["storage_state"] = storage_state

            mongo_db.fb_sessions.update_one(
                {"account_id": account_id},
                {"$set": update_fields},
                upsert=True
            )
        except Exception as e:
            pass


def load_account_session_state(account_id: str) -> dict:
    if mongo_db is not None:
        try:
            doc = mongo_db.fb_sessions.find_one({"account_id": account_id}, {"_id": 0})
            if doc:
                return doc
        except Exception:
            pass
    return {}


# ── ACCOUNTS ─────────────────────────────────────────────────────────────────

def load_accounts() -> list[dict]:
    if mongo_db is not None:
        try:
            return list(mongo_db.fb_accounts.find({}, {"_id": 0}))
        except Exception:
            pass
    return _read_json(ACCOUNTS_FILE, [])


def save_accounts(accounts: list[dict]):
    if mongo_db is not None:
        try:
            mongo_db.fb_accounts.delete_many({})
            if accounts:
                mongo_db.fb_accounts.insert_many(accounts)
            return
        except Exception:
            pass
    _write_json(ACCOUNTS_FILE, accounts)


def add_account(account_id: str, platform: str = "facebook", cookies: list[dict] = None, proxy: str = "", status: str = "active", session_dir: str = "") -> bool:
    account_id = account_id.strip()
    if not account_id:
        return False
    accounts = load_accounts()
    for acc in accounts:
        if acc.get("account_id") == account_id and acc.get("platform", "facebook").lower() == platform.lower():
            acc["cookies"] = cookies or acc.get("cookies", [])
            acc["proxy"] = proxy or acc.get("proxy", "")
            acc["status"] = status
            save_accounts(accounts)
            if cookies:
                save_account_session_state(account_id, cookies=cookies)
            return True

    new_acc = {
        "account_id": account_id,
        "platform": platform.lower(),
        "cookies": cookies or [],
        "proxy": proxy,
        "status": status,
        "created_at": datetime.now().isoformat()
    }
    accounts.append(new_acc)
    save_accounts(accounts)
    if cookies:
        save_account_session_state(account_id, cookies=cookies)
    return True


def deactivate_account(account_id: str, platform: str = "facebook"):
    accounts = load_accounts()
    for acc in accounts:
        if acc.get("account_id") == account_id and acc.get("platform", "facebook").lower() == platform.lower():
            acc["status"] = "inactive"
            acc["deactivated_at"] = datetime.now().isoformat()
            break
    save_accounts(accounts)


def delete_account(account_id: str, platform: str = "facebook") -> bool:
    accounts = load_accounts()
    new_accs = [a for a in accounts if not (a.get("account_id") == account_id and a.get("platform", "facebook").lower() == platform.lower())]
    if len(new_accs) != len(accounts):
        save_accounts(new_accs)
        if mongo_db is not None:
            try:
                mongo_db.fb_sessions.delete_one({"account_id": account_id})
            except Exception:
                pass
        return True
    return False


def release_all_account_locks(account_id: str):
    groups = load_groups()
    modified = False
    for g in groups:
        if g.get("locked_by") == account_id:
            g["locked_by"] = None
            g["status"] = "pending"
            modified = True
    if modified:
        save_groups(groups)


# ── GROUPS QUEUE ─────────────────────────────────────────────────────────────

def load_groups() -> list[dict]:
    if mongo_db is not None:
        try:
            return list(mongo_db.fb_groups.find({}, {"_id": 0}))
        except Exception:
            pass
    return _read_json(GROUPS_FILE, [])


def save_groups(groups: list[dict]):
    if mongo_db is not None:
        try:
            mongo_db.fb_groups.delete_many({})
            if groups:
                mongo_db.fb_groups.insert_many(groups)
            return
        except Exception:
            pass
    _write_json(GROUPS_FILE, groups)


def import_groups(group_urls: list[str], platform: str = "facebook", post_content: str = "") -> int:
    groups = load_groups()
    existing_urls = {g.get("group_url", "").strip().lower() for g in groups}
    added_count = 0

    for url in group_urls:
        clean_url = url.strip()
        if not clean_url or clean_url.lower() in existing_urls:
            continue

        groups.append({
            "group_url": clean_url,
            "platform": platform.lower(),
            "status": "pending",
            "post_content": post_content,
            "attempted_by_accounts": [],
            "accounts": {},
            "locked_by": None,
            "created_at": datetime.now().isoformat()
        })
        existing_urls.add(clean_url.lower())
        added_count += 1

    if added_count > 0:
        save_groups(groups)
    return added_count


def get_pending_group_tasks(account_id: str = "", platform: str = "facebook", status: str = "pending") -> list[dict]:
    groups = load_groups()
    pending = []
    for g in groups:
        if g.get("platform", "facebook").lower() == platform.lower() and g.get("status", "pending") == status:
            if account_id:
                attempted = g.get("attempted_by_accounts", [])
                if account_id in attempted:
                    continue
            pending.append(g)
    return pending


def claim_specific_group_task(account_id: str, group_url: str) -> bool:
    groups = load_groups()
    for g in groups:
        if g.get("group_url", "").strip().lower() == group_url.strip().lower():
            if g.get("locked_by") and g.get("locked_by") != account_id:
                return False
            g["locked_by"] = account_id
            g["status"] = "in_progress"
            save_groups(groups)
            return True
    return False


def finalize_group_task(account_id: str, group_url: str, status: str, note: str = "", post_content: str = ""):
    groups = load_groups()
    for g in groups:
        if g.get("group_url", "").strip().lower() == group_url.strip().lower():
            g["locked_by"] = None
            g["status"] = status
            g["note"] = note
            if post_content:
                g["post_content"] = post_content
            attempted = g.get("attempted_by_accounts", [])
            if account_id and account_id not in attempted:
                attempted.append(account_id)
            g["attempted_by_accounts"] = attempted
            break
    save_groups(groups)


# ── POSTS ENGAGEMENT QUEUE ───────────────────────────────────────────────────

def load_posts() -> list[dict]:
    if mongo_db is not None:
        try:
            return list(mongo_db.fb_posts.find({}, {"_id": 0}))
        except Exception:
            pass
    return _read_json(POSTS_FILE, [])


def save_posts(posts: list[dict]):
    if mongo_db is not None:
        try:
            mongo_db.fb_posts.delete_many({})
            if posts:
                mongo_db.fb_posts.insert_many(posts)
            return
        except Exception:
            pass
    _write_json(POSTS_FILE, posts)


def import_posts(post_urls: list[str], comment_text: str = "", platform: str = "facebook") -> int:
    posts = load_posts()
    existing_urls = {p.get("post_url", "").strip().lower() for p in posts}
    added_count = 0

    for url in post_urls:
        clean_url = url.strip()
        if not clean_url or clean_url.lower() in existing_urls:
            continue

        posts.append({
            "post_url": clean_url,
            "platform": platform.lower(),
            "comment_text": comment_text,
            "status": "pending",
            "likes": {"liked_by": []},
            "comments": {"commented_by": []},
            "created_at": datetime.now().isoformat()
        })
        existing_urls.add(clean_url.lower())
        added_count += 1

    if added_count > 0:
        save_posts(posts)
    return added_count


def save_post_engagement_result(account_id: str, post_url: str, liked: bool, commented: bool, comment_text: str = "", note: str = ""):
    posts = load_posts()
    found = False
    for p in posts:
        if p.get("post_url", "").strip().lower() == post_url.strip().lower():
            found = True
            likes_dict = p.setdefault("likes", {})
            liked_by = likes_dict.setdefault("liked_by", [])
            if liked and account_id not in liked_by:
                liked_by.append(account_id)

            comments_dict = p.setdefault("comments", {})
            commented_by = comments_dict.setdefault("commented_by", [])
            if commented and account_id not in commented_by:
                commented_by.append(account_id)

            if comment_text:
                p["comment_text"] = comment_text

            if liked and (commented or not comment_text):
                p["status"] = "success"
            elif liked or commented:
                p["status"] = "active"
            p["last_action_at"] = datetime.now().isoformat()
            break

    if not found:
        posts.append({
            "post_url": post_url,
            "platform": "facebook",
            "comment_text": comment_text,
            "status": "success" if (liked and (commented or not comment_text)) else ("active" if (liked or commented) else "pending"),
            "likes": {"liked_by": [account_id] if liked else []},
            "comments": {"commented_by": [account_id] if commented else []},
            "last_action_at": datetime.now().isoformat()
        })
    save_posts(posts)


# ── LOGS ─────────────────────────────────────────────────────────────────────

def load_logs() -> list[dict]:
    if mongo_db is not None:
        try:
            return list(mongo_db.fb_logs.find({}, {"_id": 0}).sort("timestamp", -1))
        except Exception:
            pass
    return _read_json(LOGS_FILE, [])


def save_logs(logs: list[dict]):
    if mongo_db is not None:
        try:
            mongo_db.fb_logs.delete_many({})
            if logs:
                mongo_db.fb_logs.insert_many(logs)
            return
        except Exception:
            pass
    _write_json(LOGS_FILE, logs)


def save_log(account_id: str, target_url: str, action: str, status: str, note: str = ""):
    logs = load_logs()
    logs.insert(0, {
        "account_id": account_id,
        "target_url": target_url,
        "action": action,
        "status": status,
        "note": note,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    save_logs(logs[:1000])


def clear_logs():
    save_logs([])
