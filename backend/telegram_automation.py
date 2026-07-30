"""
telegram_automation.py
----------------------
Backend Telegram Automation Engine powered by Telethon API and auto_db.
Supports state management, background batch execution, and API endpoint integration.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import logging
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union, Any

try:
    from telethon import TelegramClient
    from telethon.errors import (
        FloodWaitError,
        UserAlreadyParticipantError,
        InviteHashExpiredError,
        InviteHashInvalidError,
        ChannelPrivateError,
        ChatWriteForbiddenError,
    )
    from telethon.sessions import StringSession
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    from telethon.tl.functions.account import UpdateNotifySettingsRequest
    from telethon.tl.types import InputNotifyPeer, PeerNotifySettings
    HAS_TELETHON = True
except ImportError:
    HAS_TELETHON = False
    TelegramClient = None
    StringSession = None
    FloodWaitError = Exception
    UserAlreadyParticipantError = Exception
    InviteHashExpiredError = Exception
    InviteHashInvalidError = Exception
    ChannelPrivateError = Exception
    ChatWriteForbiddenError = Exception

BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import auto_db

try:
    import dm_monitor
except ImportError:
    dm_monitor = None

logger = logging.getLogger(__name__)

# ── GLOBAL STATE & STOP MECHANISM ──────────────────────────────────────────────

TG_STOP_EVENT = threading.Event()

TG_AUTOMATION_STATE = {
    "is_running": False,
    "task_type": "Group Join & Post",
    "progress": 0,
    "status_text": "Idle",
    "logs": [],
    "current_account": "",
    "stop_requested": False
}


def get_tg_automation_state() -> dict:
    return dict(TG_AUTOMATION_STATE)


def request_tg_stop_automation():
    TG_STOP_EVENT.set()
    TG_AUTOMATION_STATE["stop_requested"] = True
    TG_AUTOMATION_STATE["status_text"] = "Stop requested by user..."
    log_msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] STOP signal issued for Telegram Automation Engine."
    TG_AUTOMATION_STATE["logs"].insert(0, log_msg)
    logger.info("Stop requested by user for Telegram Automation Engine.")


def reset_tg_stop_automation():
    TG_STOP_EVENT.clear()
    TG_AUTOMATION_STATE["stop_requested"] = False


def add_tg_state_log(msg: str):
    timestamped = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    TG_AUTOMATION_STATE["logs"].insert(0, timestamped)
    if len(TG_AUTOMATION_STATE["logs"]) > 200:
        TG_AUTOMATION_STATE["logs"] = TG_AUTOMATION_STATE["logs"][:200]


# ── TELETHON HELPERS ─────────────────────────────────────────────────────────

def run_async(corofn, *args, **kwargs):
    """Safely execute an async function inside synchronous execution loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: asyncio.run(corofn(*args, **kwargs))).result()
    else:
        return asyncio.run(corofn(*args, **kwargs))


def parse_tg_link(link: str) -> tuple[str, str]:
    link = link.strip()
    if "joinchat/" in link:
        hash_val = link.split("joinchat/")[-1].split("?")[0].split("/")[0]
        return "private", hash_val
    elif "t.me/+" in link:
        hash_val = link.split("t.me/+")[-1].split("?")[0].split("/")[0]
        return "private", hash_val
    else:
        username = link
        if "t.me/" in username:
            username = username.split("t.me/")[-1].split("?")[0].split("/")[0]
        username = username.replace("@", "").strip()
        return "public", username


def parse_proxy(proxy_str: str):
    if not proxy_str or not proxy_str.strip():
        return None
    try:
        import socks
        parts = proxy_str.strip().split(":")
        if len(parts) == 4:
            ip, port, user, password = parts
            return (socks.SOCKS5, ip, int(port), True, user, password)
        elif len(parts) == 2:
            ip, port = parts
            return (socks.SOCKS5, ip, int(port))
    except Exception:
        return None
    return None


async def _join_group(client: Any, link: str) -> tuple[str, str]:
    link_type, identifier = parse_tg_link(link)
    try:
        if link_type == "private":
            await client(ImportChatInviteRequest(hash=identifier))
            return "joined", "Joined via private invite link"
        else:
            await client(JoinChannelRequest(identifier))
            return "joined", "Joined public group/channel"
    except UserAlreadyParticipantError:
        return "already_joined", "Already a participant"
    except FloodWaitError as flood:
        raise flood
    except (InviteHashExpiredError, InviteHashInvalidError):
        return "failed", "Invite link expired or invalid"
    except ChannelPrivateError:
        return "failed", "Channel is private"
    except Exception as e:
        err_str = str(e).lower()
        if "requested to join" in err_str or "inviterequestsent" in type(e).__name__.lower():
            return "pending", f"Telegram Notice: {e}"
        return "failed", f"Telegram API Error: {type(e).__name__} ({e})"


async def _send_message(client: Any, link: str, message: str) -> tuple[str, str, str]:
    _, identifier = parse_tg_link(link)
    try:
        entity = await client.get_entity(identifier)
        sent_msg = await client.send_message(entity, message)

        msg_link = ""
        msg_id = getattr(sent_msg, "id", None)
        if msg_id:
            username = getattr(entity, "username", None)
            if username:
                msg_link = f"https://t.me/{username}/{msg_id}"
            else:
                chat_id = getattr(entity, "id", None)
                if chat_id:
                    clean_id = str(chat_id).replace("-100", "")
                    msg_link = f"https://t.me/c/{clean_id}/{msg_id}"

        note = f"Message sent successfully | Link: {msg_link}" if msg_link else "Message sent successfully"
        return "posted", note, msg_link
    except ChatWriteForbiddenError as e:
        return "failed", f"Write Permission Denied ({e})", ""
    except FloodWaitError as flood:
        raise flood
    except Exception as e:
        return "failed", f"Telegram Send Error: {type(e).__name__} ({e})", ""


async def _mute_group(client: Any, link: str) -> tuple[bool, str]:
    _, identifier = parse_tg_link(link)
    try:
        entity = await client.get_entity(identifier)
        try:
            input_peer = await client.get_input_entity(entity)
            await client(UpdateNotifySettingsRequest(
                peer=InputNotifyPeer(peer=input_peer),
                settings=PeerNotifySettings(mute_until=2147483647)
            ))
        except Exception:
            await client(UpdateNotifySettingsRequest(
                peer=entity,
                settings=PeerNotifySettings(mute_until=2147483647)
            ))
        return True, "Muted group notifications"
    except Exception as e:
        logger.warning(f"Mute notification notice for {link}: {e}")
        return False, f"Notification settings unchanged ({type(e).__name__})"


# ── ACCOUNT AUTOMATION RUNNER ────────────────────────────────────────────────

def run_account_telegram_automation(
    account_id: str,
    run_join: bool = True,
    run_post: bool = True,
    message: Union[str, Dict, List] = "",
    log_placeholder: Any = None,
    update_step_cb: Any = None,
    force_repost: bool = False,
    group_cap: int = 0,
    run_dm_check: bool = False,
    acc_index: int = 0,
    total_accs: int = 1,
    target_groups: Optional[List[Dict]] = None
) -> bool:
    def log(msg, category="info"):
        if log_placeholder is not None:
            if category == "success" and hasattr(log_placeholder, "success"):
                log_placeholder.success(msg)
            elif category == "error" and hasattr(log_placeholder, "warning"):
                log_placeholder.warning(msg)
            elif hasattr(log_placeholder, "info"):
                log_placeholder.info(msg)
        add_tg_state_log(msg)
        logger.info(f"[{category.upper()}] {msg}")

    def update_step(text):
        if update_step_cb:
            try:
                update_step_cb(text)
            except Exception:
                pass
        TG_AUTOMATION_STATE["status_text"] = text

    if not HAS_TELETHON:
        log("Telethon library is not installed on system. Please run 'pip install telethon PySocks'.", "error")
        return False

    accounts = auto_db.load_accounts()
    acc_doc = next((a for a in accounts if a.get("account_id") == account_id and a.get("platform", "").lower() in ("telegram", "tg")), None)
    if not acc_doc:
        acc_doc = next((a for a in accounts if a.get("account_id") == account_id), None)

    if not acc_doc or acc_doc.get("status") != "active":
        log(f"Account '{account_id}' is not active.", "error")
        return False

    tg_info = acc_doc.get("telegram", {}) if isinstance(acc_doc.get("telegram"), dict) else {}
    api_id = tg_info.get("api_id") or acc_doc.get("api_id") or 39197157
    api_hash = tg_info.get("api_hash") or acc_doc.get("api_hash") or "5de576dd64aae68a18f5114761e539d7"
    session_string = tg_info.get("session_string") or acc_doc.get("session_string") or (acc_doc.get("cookies") if isinstance(acc_doc.get("cookies"), str) else "")

    if not api_id or not api_hash or not session_string:
        log(f"Telegram credentials missing for '{account_id}'.", "error")
        return False

    proxy = parse_proxy(acc_doc.get("proxy", ""))

    async def _async_run():
        if TG_STOP_EVENT.is_set():
            log(f"Stop requested, skipping account '{account_id}'.", "info")
            return False

        update_step(f"[{account_id}] Connecting Telethon Client...")
        client = None
        try:
            client = TelegramClient(StringSession(session_string), api_id, api_hash, proxy=proxy)
            await client.connect()
            if not await client.is_user_authorized():
                log(f"Telegram session unauthorized for '{account_id}'.", "error")
                auto_db.deactivate_account(account_id, platform="telegram")
                return False

            log(f"Connected to Telegram for account '{account_id}'.", "success")

            if target_groups is not None:
                groups = target_groups
            else:
                groups = auto_db.get_pending_group_tasks(account_id, platform="telegram", status="pending")
                if total_accs > 1 and len(groups) > 0:
                    groups = groups[acc_index::total_accs]

            limit_groups = groups if group_cap <= 0 else groups[:group_cap]
            cap_str = "No Limit (ALL)" if group_cap <= 0 else f"Cap limit: {group_cap}"
            log(f"[{account_id}] Processing {len(limit_groups)} group task(s) ({cap_str}).", "info")

            for i, task in enumerate(limit_groups):
                if TG_STOP_EVENT.is_set():
                    log(f"[{account_id}] Batch stop signal received. Halting tasks.", "info")
                    break

                g_url = task["group_url"]
                if isinstance(message, list):
                    if message:
                        global_idx = acc_index + i * total_accs
                        post_text = message[global_idx % len(message)]
                    else:
                        post_text = task.get("post_content", "")
                elif isinstance(message, dict):
                    post_text = message.get(account_id, "") or task.get("post_content", "")
                else:
                    post_text = (message or "").strip() or task.get("post_content", "")

                if not auto_db.claim_specific_group_task(account_id, g_url):
                    continue

                update_step(f"[{account_id}] Processing group ({i+1}/{len(limit_groups)}): {g_url}")
                log(f"[{account_id}] [{i+1}/{len(limit_groups)}] Processing group: {g_url}", "info")
                join_st, join_note = await _join_group(client, g_url)
                log(f"[{account_id}] Join status: {join_st} ({join_note})", "info" if join_st != "failed" else "error")
                auto_db.save_log(account_id, g_url, "Join Group", join_st, join_note)

                if join_st in ("joined", "already_joined"):
                    auto_db.finalize_group_task(account_id, g_url, status="joined", note=join_note)

                    await asyncio.sleep(random.uniform(1.5, 2.5))

                    muted, mute_note = await _mute_group(client, g_url)
                    auto_db.save_log(account_id, g_url, "Mute Notifications", "success" if muted else "skipped", mute_note)
                    if muted:
                        log(f"[{account_id}] Muted notifications for group/channel.", "info")

                    await asyncio.sleep(random.uniform(1.0, 2.0))

                    post_st, post_note, msg_link = await _send_message(client, g_url, post_text)
                    log(f"[{account_id}] Post status: {post_st} ({post_note})", "success" if post_st == "posted" else "error")
                    auto_db.save_log(account_id, g_url, "Post Content", post_st, post_note)

                    final_st = "success" if post_st == "posted" else "failed"
                    try:
                        auto_db.finalize_group_task(account_id, g_url, status=final_st, note=post_note, post_content=post_text, message_link=msg_link)
                    except TypeError:
                        auto_db.finalize_group_task(account_id, g_url, status=final_st, note=post_note, post_content=post_text)

                    await asyncio.sleep(random.uniform(1.5, 2.5))
                elif join_st == "pending":
                    log(f"[{account_id}] {join_note}", "info")
                    auto_db.finalize_group_task(account_id, g_url, status="pending_approval", note=join_note)
                else:
                    auto_db.finalize_group_task(account_id, g_url, status="failed", note=join_note)

                g_delay = random.uniform(2.0, 4.0)
                update_step(f"[{account_id}] Waiting {g_delay:.1f}s before next group...")
                await asyncio.sleep(g_delay)

            if run_dm_check and dm_monitor is not None and hasattr(dm_monitor, "run_telegram_dm_check"):
                cfg = auto_db.load_config() if hasattr(auto_db, "load_config") else {}
                log(f"[{account_id}] Checking Telegram DMs and leads...", "info")
                leads = await dm_monitor.run_telegram_dm_check(acc_doc, account_id, cfg)
                log(f"[{account_id}] DM check complete. Found {len(leads)} lead item(s).", "success")

            return True

        except (KeyboardInterrupt, SystemExit):
            log("Interrupt detected, closing Telegram client.", "info")
            auto_db.release_all_account_locks(account_id)
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            raise
        except Exception as e:
            log(f"[{account_id}] Telegram error: {e}", "error")
            auto_db.release_all_account_locks(account_id)
            return False
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    return run_async(_async_run)


# ── BATCH AUTOMATION RUNNER FOR FASTAPI BACKGROUND TASK ────────────────────

def execute_telegram_automation_batch(payload_dict: dict):
    reset_tg_stop_automation()
    TG_AUTOMATION_STATE["is_running"] = True
    TG_AUTOMATION_STATE["task_type"] = payload_dict.get("task_type", "Group Join & Post")
    TG_AUTOMATION_STATE["progress"] = 5
    TG_AUTOMATION_STATE["status_text"] = f"Running ({TG_AUTOMATION_STATE['task_type']})"
    TG_AUTOMATION_STATE["logs"] = []

    selected_accounts = payload_dict.get("selected_accounts", [])
    group_cap = payload_dict.get("group_cap", 0)
    run_dm_check = payload_dict.get("run_dm_check", False)

    post_content_custom = payload_dict.get("post_content_custom")
    post_content_single = payload_dict.get("post_content_single")
    message_data = post_content_custom if post_content_custom else (post_content_single or "")

    add_tg_state_log(f"Starting Telegram automation batch for {len(selected_accounts)} account(s)...")

    total_accs = len(selected_accounts)
    pending_groups_snapshot = auto_db.get_pending_group_tasks(account_id="", platform="telegram", status="pending")

    for idx, acc_id in enumerate(selected_accounts):
        if TG_AUTOMATION_STATE.get("stop_requested") or TG_STOP_EVENT.is_set():
            add_tg_state_log("Telegram batch aborted by user stop request.")
            break

        TG_AUTOMATION_STATE["current_account"] = acc_id
        TG_AUTOMATION_STATE["progress"] = int((idx / total_accs) * 90) + 5
        TG_AUTOMATION_STATE["status_text"] = f"Executing Telegram account '{acc_id}' ({idx + 1}/{total_accs})..."

        acc_groups = pending_groups_snapshot[idx::total_accs] if pending_groups_snapshot else None

        try:
            run_account_telegram_automation(
                account_id=acc_id,
                run_join=True,
                run_post=True,
                message=message_data,
                group_cap=group_cap,
                run_dm_check=run_dm_check,
                acc_index=idx,
                total_accs=total_accs,
                target_groups=acc_groups
            )
        except Exception as e:
            logger.error(f"Error executing Telegram automation for account {acc_id}: {e}")
            add_tg_state_log(f"Error executing account {acc_id}: {e}")

        if idx < total_accs - 1 and not (TG_AUTOMATION_STATE.get("stop_requested") or TG_STOP_EVENT.is_set()):
            inter_acc_delay = random.uniform(5.0, 10.0)
            add_tg_state_log(f"Waiting {inter_acc_delay:.1f}s before next account...")
            time.sleep(inter_acc_delay)

    TG_AUTOMATION_STATE["is_running"] = False
    TG_AUTOMATION_STATE["current_account"] = ""
    if TG_AUTOMATION_STATE.get("stop_requested") or TG_STOP_EVENT.is_set():
        TG_AUTOMATION_STATE["status_text"] = "Stopped"
        TG_AUTOMATION_STATE["progress"] = 0
        add_tg_state_log("Telegram automation batch stopped.")
    else:
        TG_AUTOMATION_STATE["status_text"] = "Completed"
        TG_AUTOMATION_STATE["progress"] = 100
        add_tg_state_log("Telegram automation batch completed successfully.")
