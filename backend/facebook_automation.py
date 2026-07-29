"""
facebook_automation.py
----------------------
Playwright Facebook Automation Engine for Group Joining, Posting, and Post Engagement.
Integrated directly into FastAPI Backend with background execution, live state tracking, and stop controls.
"""

import asyncio
import concurrent.futures
import datetime
import json
import logging
import os
import random
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import auto_db
import fingerprint as fp_module

logger = logging.getLogger(__name__)

# ── GLOBAL STATE & STOP MECHANISM ──────────────────────────────────────────────

STOP_EVENT = threading.Event()

AUTOMATION_STATE = {
    "is_running": False,
    "task_type": "",
    "progress": 0,
    "status_text": "Idle",
    "logs": [],
    "current_account": "",
    "stop_requested": False
}


def get_automation_state() -> dict:
    return dict(AUTOMATION_STATE)


def request_stop_automation():
    STOP_EVENT.set()
    AUTOMATION_STATE["stop_requested"] = True
    AUTOMATION_STATE["status_text"] = "Stop requested by user..."
    log_msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] STOP signal issued. Terminating Playwright sessions..."
    AUTOMATION_STATE["logs"].insert(0, log_msg)
    logger.info("Stop requested by user for Facebook Automation Engine.")


def reset_stop_automation():
    STOP_EVENT.clear()
    AUTOMATION_STATE["stop_requested"] = False


def add_state_log(msg: str):
    timestamped = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    AUTOMATION_STATE["logs"].insert(0, timestamped)
    if len(AUTOMATION_STATE["logs"]) > 200:
        AUTOMATION_STATE["logs"] = AUTOMATION_STATE["logs"][:200]


# ── PROXY & COOKIE PARSERS ───────────────────────────────────────────────────

def parse_proxy(proxy_str: str) -> dict | None:
    proxy_str = (proxy_str or "").strip()
    if not proxy_str:
        return None

    # Support Webshare colon format: IP:PORT:USERNAME:PASSWORD
    parts = [p.strip() for p in proxy_str.split(":") if p.strip()]
    if len(parts) == 4 and not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks")):
        ip, port, user, password = parts[0], parts[1], parts[2], parts[3]
        return {
            "server": f"http://{ip}:{port}",
            "username": user,
            "password": password
        }

    # Support IP:PORT
    if len(parts) == 2 and not (proxy_str.startswith("http://") or proxy_str.startswith("https://") or proxy_str.startswith("socks")):
        ip, port = parts[0], parts[1]
        return {
            "server": f"http://{ip}:{port}"
        }

    # Standard URL parsing for http://user:pass@ip:port
    try:
        from urllib.parse import urlparse
        target_str = proxy_str
        if not (target_str.startswith("http://") or target_str.startswith("https://") or target_str.startswith("socks")):
            target_str = "http://" + target_str
        p = urlparse(target_str)
        if not p.hostname or not p.port:
            return None
        proxy_dict = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
        if p.username:
            proxy_dict["username"] = p.username
        if p.password:
            proxy_dict["password"] = p.password
        return proxy_dict
    except Exception:
        return None


def parse_cookies_input(cookies_str: str) -> list[dict]:
    cookies_str = cookies_str.strip()
    if not cookies_str:
        return []
    try:
        data = json.loads(cookies_str)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    parsed = []
    for line in cookies_str.split(";"):
        if "=" in line:
            k, v = line.split("=", 1)
            parsed.append({
                "name": k.strip(),
                "value": v.strip(),
                "domain": ".facebook.com",
                "path": "/"
            })
    return parsed


def is_facebook_logged_in(page) -> tuple[bool, str]:
    page.wait_for_timeout(1500)
    url = page.url.lower()
    for kw in ["/login", "/checkpoint", "/recover", "/login.php", "two_factor_auth"]:
        if kw in url:
            return False, f"Redirected to security checkpoint ({url})"

    if page.locator('input[name="email"]').count() > 0 or page.locator('input[name="pass"]').count() > 0:
        return False, "Login credentials form detected"

    for p in ["Email address or phone number", "Mobile number or email address", "Email or phone"]:
        if page.get_by_placeholder(p, exact=False).count() > 0:
            return False, f"Login placeholder '{p}' detected"

    return True, "Feed visible"


# Selectors & text patterns
JOIN_BUTTON_NAMES = [
    "Join group", "Join Group", "Unirte al grupo", "Unirse al grupo", "Unirte",
    "ग्रुप से जुड़ें", "انضمام إلى المجموعة", "Rejoindre le groupe", "Gruppe beitreten",
    "Participar do grupo", "Bergabung dengan Grup", "Sumali sa Grupo", "Tham gia nhóm"
]
WRITE_TRIGGERS = [
    "Write something", "Create a public post", "Create a post", "Write something...",
    "Escribe algo", "Crear una publicación", "Crear publicación", "Escribe algo...",
    "कुछ लिखें...", "اكتب شيئاً...", "Exprimez-vous...", "Schreibe etwas...",
    "Escreva algo...", "Tulis sesuatu...", "Magsulat ng sesuatu...", "Viết gì đó..."
]
POST_BUTTON_NAMES = [
    "Post", "Publicar", "nشر", "نشر", "Publier", "Posten", "Posting", "I-post", "Đăng", "पोस्ट करें"
]
JOINED_INDICATORS = [
    "Joined", "View group", "Invite", "Unido", "Unida", "Te uniste", "Miembro",
    "जुड़े हैं", "منضم", "Rejoint", "Beigetreten", "Participando", "Bergabung", "Nakasali", "Đã tham gia"
]
UNAVAILABLE_TEXTS = [
    "Content not found", "isn't available", "This content isn't available",
    "Sorry, something went wrong",
    "Contenido no encontrado", "Este contenido no está disponible", "No disponible",
    "सामग्री उपलब्ध नहीं है", "المحتوى غير متوفر"
]
APPROVAL_KEYWORDS = [
    "pending approval", "submitted for approval", "admin approval",
    "pendiente de aprobación", "enviado para aprobación"
]
COMMENT_PLACEHOLDERS = [
    "Write a comment...", "Write a comment", "Write a public comment...",
    "Write an answer...", "Write an answer", "Write a reply...", "Write a reply",
    "Escribe un comentario...", "Escribe un comentario", "Escribe una respuesta...", "Responder..."
]


def find_visible_comment_textbox(page):
    """Find and return the first VISIBLE comment textbox locator on the page."""
    try:
        dialog = page.locator('div[role="dialog"]').filter(has=page.locator('div[role="textbox"]')).first
        if dialog.count() > 0 and dialog.is_visible():
            tb_list = dialog.locator('div[role="textbox"]')
            for i in range(tb_list.count()):
                tb = tb_list.nth(i)
                if tb.is_visible():
                    return tb
    except Exception:
        pass

    for p in COMMENT_PLACEHOLDERS:
        try:
            boxes = page.get_by_placeholder(p, exact=False)
            for i in range(boxes.count()):
                box = boxes.nth(i)
                if box.is_visible():
                    return box
        except Exception:
            pass

    try:
        boxes = page.locator('div[role="textbox"]')
        for i in range(boxes.count()):
            box = boxes.nth(i)
            if box.is_visible():
                return box
    except Exception:
        pass

    try:
        boxes = page.locator('div[contenteditable="true"]')
        for i in range(boxes.count()):
            box = boxes.nth(i)
            if box.is_visible():
                return box
    except Exception:
        pass

    return None


def click_like(page, min_delay: float = 5.0, max_delay: float = 10.0) -> bool:
    """Click the MAIN POST's Like button using multi-stage visibility search."""
    if STOP_EVENT.is_set():
        return False

    page.wait_for_timeout(2000)
    like_btn = None

    # 1. Search inside active visible dialog / modal first
    try:
        dialogs = page.locator('div[role="dialog"]')
        for d in range(dialogs.count()):
            dlg = dialogs.nth(d)
            if dlg.is_visible():
                selectors = [
                    'div[role="button"][aria-label^="React to "]',
                    'div[aria-label^="React to "]',
                    'div[role="button"][aria-label*="React with Like"]',
                    'div[aria-label="Like"]',
                    'button[aria-label="Like"]',
                    'div[aria-label="Me gusta"]',
                    'button[aria-label="Me gusta"]',
                    'div[role="button"]:has-text("Like")',
                    'button:has-text("Like")',
                ]
                for selector in selectors:
                    locs = dlg.locator(selector)
                    for i in range(locs.count()):
                        b = locs.nth(i)
                        if b.is_visible():
                            like_btn = b
                            break
                    if like_btn:
                        break
            if like_btn:
                break
    except Exception:
        pass

    # 2. Search main post's action bar
    if not like_btn:
        try:
            action_bars = page.locator('div[role="group"]').filter(has=page.get_by_text("Comment", exact=False))
            for i in range(action_bars.count()):
                bar = action_bars.nth(i)
                if bar.is_visible():
                    btn = bar.locator('div[aria-label^="React to"], button[aria-label^="React to"], div[aria-label="Like"], button[aria-label="Like"]').first
                    if btn.count() > 0 and btn.is_visible():
                        like_btn = btn
                    else:
                        btn = bar.locator('div[role="button"], button').filter(has_text="Like").first
                        if btn.count() > 0 and btn.is_visible():
                            like_btn = btn
                if like_btn:
                    break
        except Exception:
            pass

    # 3. Search page-wide across ALL matching locators
    if not like_btn:
        selectors = [
            'div[role="button"][aria-label^="React to "]',
            'div[aria-label^="React to "]',
            'button[aria-label^="React to "]',
            'div[role="button"][aria-label*="React with Like"]',
            'div[aria-label*="React with Like"]',
            'div[aria-label="Like"]',
            'button[aria-label="Like"]',
            'div[aria-label="Me gusta"]',
            'button[aria-label="Me gusta"]',
            'div[data-ad-rendering-role="like_button"]',
        ]
        for selector in selectors:
            try:
                locs = page.locator(selector)
                for i in range(locs.count()):
                    b = locs.nth(i)
                    if b.is_visible():
                        like_btn = b
                        break
                if like_btn:
                    break
            except Exception:
                continue

    # 4. Fallback: Role button with exact text "Like" or "Me gusta"
    if not like_btn:
        for text in ["Like", "Me gusta"]:
            try:
                btns = page.get_by_role("button", name=text, exact=True)
                for i in range(btns.count()):
                    b = btns.nth(i)
                    if b.is_visible():
                        like_btn = b
                        break
                if like_btn:
                    break
            except Exception:
                pass

    if not like_btn:
        return False

    # Check if ALREADY LIKED
    try:
        btn_aria = (like_btn.get_attribute("aria-label") or "").lower()
        btn_pressed = (like_btn.get_attribute("aria-pressed") or "").lower()
        if btn_pressed == "true" or any(indicator in btn_aria for indicator in [
            "unlike", "ya no me gusta", "remove reaction", "quitar me gusta"
        ]):
            return True
    except Exception:
        pass

    try:
        try:
            like_btn.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        clicked = False
        try:
            like_btn.click(timeout=5000)
            clicked = True
        except Exception:
            try:
                like_btn.click(force=True, timeout=5000)
                clicked = True
            except Exception:
                try:
                    handle = like_btn.element_handle()
                    if handle:
                        page.evaluate("(el) => el.click()", handle)
                        clicked = True
                except Exception:
                    pass

        if not clicked:
            return False

        page.wait_for_timeout(2000)
        return True
    except Exception as e:
        logger.error(f"Like click error: {e}")
        return False


def post_comment(page, comment_text: str, account_id: str = "", min_delay: float = 5.0, max_delay: float = 10.0) -> bool:
    if STOP_EVENT.is_set() or not comment_text:
        return False

    page.wait_for_timeout(2000)

    # 1. Click Comment button to open/focus comment section if needed
    try:
        ad_comment = page.locator('div[data-ad-rendering-role="comment_button"]').first
        if ad_comment.count() > 0:
            parent_btn = ad_comment.locator('xpath=ancestor::div[@role="button"]').first
            if parent_btn.count() > 0 and parent_btn.is_visible():
                parent_btn.click()
                page.wait_for_timeout(1500)
    except Exception:
        pass

    try:
        action_bars = page.locator('div[role="group"]')
        for i in range(action_bars.count()):
            bar = action_bars.nth(i)
            btns = bar.locator('div[role="button"], button')
            if btns.count() in (2, 3, 4, 5):
                c_btn = btns.nth(1)
                if c_btn.is_visible():
                    c_btn.click()
                    page.wait_for_timeout(1500)
                    break
    except Exception:
        pass

    for name in ["Comment", "Comentar", "Write a comment", "Write an answer", "Comment on"]:
        try:
            btn = page.get_by_role("button", name=name, exact=False).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                break
        except Exception:
            pass

    comment_input = find_visible_comment_textbox(page)
    if comment_input is None:
        try:
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(1500)
            comment_input = find_visible_comment_textbox(page)
        except Exception:
            pass

    if comment_input is None:
        return False

    try:
        try:
            comment_input.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(500)

        try:
            comment_input.click(timeout=5000)
        except Exception:
            comment_input.click(force=True, timeout=5000)
        page.wait_for_timeout(500)

        comment_input.press("Control+A")
        comment_input.press("Backspace")
        page.wait_for_timeout(300)

        comment_input.press_sequentially(comment_text, delay=random.randint(30, 70))
        page.wait_for_timeout(1000)

        comment_input.press("Enter")
        page.wait_for_timeout(2000)

        submit_selectors = [
            'div[aria-label="Comment"]', 'div[aria-label="Comentar"]',
            'button[aria-label="Comment"]', 'button[aria-label="Comentar"]',
            'div[aria-label="Post"]', 'div[aria-label="Publicar"]',
            'div[aria-label="Send"]', 'form button[type="submit"]',
        ]
        for sub_sel in submit_selectors:
            try:
                sub_btn = page.locator(sub_sel).first
                if sub_btn.count() > 0 and sub_btn.is_visible():
                    try:
                        sub_btn.click(timeout=3000)
                    except Exception:
                        sub_btn.click(force=True, timeout=3000)
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                pass

        page.wait_for_timeout(2000)

        box_text = ""
        try:
            box_text = comment_input.inner_text().strip()
        except Exception:
            pass

        posted = False
        if not box_text or comment_text not in box_text:
            posted = True
        elif page.get_by_text(comment_text, exact=False).count() > 0:
            posted = True

        return posted
    except Exception as e:
        logger.error(f"Comment error: {e}")
        return False


def detect_fb_group_state(page) -> str:
    page.wait_for_timeout(2500)
    if page.get_by_text("Your request has been sent", exact=False).count() > 0:
        return "pending"
    for phrase in ["Answer 3 questions", "Answer questions"]:
        if page.get_by_text(phrase, exact=False).count() > 0:
            return "needs_manual"
    for name in JOIN_BUTTON_NAMES:
        if page.get_by_role("button", name=name).count() > 0 or page.locator(f'div[role="button"]:has-text("{name}")').count() > 0:
            return "can_join"
    for text in JOINED_INDICATORS:
        if page.get_by_text(text, exact=False).count() > 0:
            return "already_joined"
    for text in UNAVAILABLE_TEXTS:
        if page.get_by_text(text, exact=False).count() > 0:
            return "unavailable"
    return "unknown"


def join_fb_group(page, log_func=None) -> tuple[str, str]:
    if STOP_EVENT.is_set():
        return "failed", "Stop requested"

    state = detect_fb_group_state(page)
    if state == "can_join":
        for name in JOIN_BUTTON_NAMES:
            try:
                btn = page.get_by_role("button", name=name).first
                if btn.count() == 0:
                    btn = page.locator(f'div[role="button"]:has-text("{name}")').first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=5000)
                    page.wait_for_timeout(3000)
                    break
            except Exception:
                continue

        after_state = detect_fb_group_state(page)
        if after_state in ("already_joined", "pending"):
            return after_state, "Clicked join button, state confirmed"
        return "joined", "Clicked join button"

    if state == "already_joined":
        return "already_joined", "Already a member of group"
    if state == "pending":
        return "already_joined", "Join request pending approval"
    if state == "unavailable":
        return "failed", "Group content unavailable"
    return "already_joined", "Group accessible"


def mute_fb_group(page, log_func=None) -> bool:
    if STOP_EVENT.is_set():
        return False
    try:
        page.wait_for_timeout(1500)
        joined_btn = None
        for name in ["Joined", "Unido", "Miembro", "View group", "Invite"]:
            try:
                btn = page.get_by_role("button", name=name, exact=False).first
                if btn.count() == 0:
                    btn = page.locator(f'div[role="button"]:has-text("{name}")').first
                if btn.count() > 0 and btn.is_visible():
                    joined_btn = btn
                    break
            except Exception:
                continue

        if not joined_btn:
            return False

        joined_btn.click(timeout=4000)
        page.wait_for_timeout(2000)

        manage_btn = None
        for name in ["Manage notifications", "Administrar notificaciones", "Notifications"]:
            try:
                btn = page.get_by_text(name, exact=False).first
                if btn.count() > 0 and btn.is_visible():
                    manage_btn = btn
                    break
            except Exception:
                continue

        if not manage_btn:
            return False

        manage_btn.click(timeout=4000)
        page.wait_for_timeout(3000)

        dialog = page.locator('div[role="dialog"]:visible').first
        if dialog.count() == 0:
            return False

        radios = dialog.get_by_role("radio")
        if radios.count() >= 6:
            try:
                radios.nth(3).click(timeout=2000)
                radios.nth(5).click(timeout=2000)
            except Exception:
                pass

        save_btn = dialog.get_by_role("button", name="Save").first
        if save_btn.count() > 0 and save_btn.is_visible():
            save_btn.click(timeout=4000)
            page.wait_for_timeout(3000)
            return True
        return True
    except Exception as e:
        logger.info(f"Mute notifications notice: {e}")
        return False


def post_to_fb_group(page, post_text: str, log_func=None) -> tuple[str, str]:
    if STOP_EVENT.is_set() or not post_text or not post_text.strip():
        return "skipped", "No post content specified or stop requested"

    page.wait_for_timeout(2000)
    dialog_locator = page.locator('div[role="dialog"]').filter(has=page.locator('div[role="textbox"]'))

    def is_dialog_open() -> bool:
        try:
            return dialog_locator.count() > 0 and dialog_locator.first.is_visible()
        except Exception:
            return False

    clicked = False
    if is_dialog_open():
        clicked = True
    else:
        for text in WRITE_TRIGGERS:
            try:
                loc = page.get_by_role("button", name=text, exact=False).first
                if loc.count() == 0:
                    loc = page.locator(f'div[role="button"]:has-text("{text}")').first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=4000)
                    page.wait_for_timeout(2000)
                    if is_dialog_open():
                        clicked = True
                        break
            except Exception:
                continue

    if not clicked:
        return "failed", "Could not locate post write-box trigger"

    try:
        dialog = dialog_locator.first
        dialog.wait_for(state="visible", timeout=10000)

        textbox = dialog.locator('div[role="textbox"]').first
        textbox.wait_for(state="visible", timeout=10000)

        textbox.click()
        textbox.press("Control+A")
        textbox.press("Backspace")
        textbox.press_sequentially(post_text, delay=random.randint(30, 70))
        page.wait_for_timeout(1000)
    except Exception as e:
        return "failed", f"Failed to type post content: {e}"

    post_btn = None
    for name in POST_BUTTON_NAMES:
        try:
            btn = dialog.get_by_role("button", name=name, exact=True).first
            if btn.count() == 0:
                btn = dialog.locator(f'div[aria-label="{name}"]').first
            if btn.count() > 0 and btn.is_visible():
                post_btn = btn
                break
        except Exception:
            continue

    if not post_btn:
        return "failed", "Could not find Post submit button"

    try:
        post_btn.click(timeout=5000)
        page.wait_for_timeout(5000)
    except Exception as e:
        return "failed", f"Post submit click error: {e}"

    for kw in APPROVAL_KEYWORDS:
        if page.get_by_text(kw, exact=False).count() > 0:
            return "submitted", "Submitted — pending admin approval"

    return "posted", "Posted successfully"


def verify_post_not_deleted(page, group_url: str, post_content: str) -> bool:
    if STOP_EVENT.is_set():
        return True
    delay = random.uniform(8.0, 10.0)
    page.wait_for_timeout(int(delay * 1000))
    try:
        page.reload(wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        count = page.get_by_text(post_content, exact=False).count()
        return count > 0
    except Exception:
        return True


class FacebookBot:
    def __init__(self, account_id, page_instance=None, context_instance=None):
        self.account_id = account_id
        self.page = page_instance
        self.context = context_instance

    def like_and_comment_post(self, post_url, comment_text, min_delay=5.0, max_delay=10.0):
        if STOP_EVENT.is_set():
            return False, False

        add_state_log(f"[{self.account_id}] Navigating to post target: {post_url}")
        try:
            self.page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(2500)
        except Exception as goto_e:
            add_state_log(f"[{self.account_id}] Navigation notice: {goto_e}")

        is_login, reason = is_facebook_logged_in(self.page)
        if not is_login:
            add_state_log(f"[{self.account_id}] Login checkpoint detected: {reason}")
            logger.warning(f"[FacebookBot] Login wall detected for {self.account_id}: {reason}")
            auto_db.deactivate_account(self.account_id)
            return False, False

        add_state_log(f"[{self.account_id}] Page loaded. Attempting to LIKE post...")
        liked = click_like(self.page, min_delay=min_delay, max_delay=max_delay)
        add_state_log(f"[{self.account_id}] Like result: {'Success' if liked else 'Could not locate Like button'}")

        if liked and comment_text and not STOP_EVENT.is_set():
            delay = random.uniform(min_delay, max_delay)
            add_state_log(f"[{self.account_id}] Safe human pause: waiting {int(delay)}s before commenting...")
            time.sleep(delay)

        commented = False
        if comment_text and not STOP_EVENT.is_set():
            add_state_log(f"[{self.account_id}] Attempting to COMMENT on post...")
            commented = post_comment(self.page, comment_text, account_id=self.account_id, min_delay=min_delay, max_delay=max_delay)
            add_state_log(f"[{self.account_id}] Comment result: {'Success' if commented else 'Could not place comment'}")

        return liked, commented


def run_account_automation(
    account_id: str,
    task_type: str = "Group Join & Post",
    post_url: str = "",
    comment_text: str = "",
    message: any = "",
    group_cap: int = 0,
    is_headless: bool = True,
    acc_index: int = 0,
    total_accs: int = 1,
    target_groups: list = None,
    min_delay: float = 10.0,
    max_delay: float = 25.0
):
    if STOP_EVENT.is_set():
        logger.info(f"[{account_id}] Skipping execution: STOP_EVENT is set.")
        return False

    accounts = auto_db.load_accounts()
    acc_doc = next((a for a in accounts if a.get("account_id") == account_id and a.get("platform", "facebook").lower() == "facebook"), None)
    if not acc_doc:
        acc_doc = next((a for a in accounts if a.get("account_id") == account_id), None)

    if not acc_doc or acc_doc.get("status") != "active":
        logger.error(f"Account '{account_id}' is not active.")
        add_state_log(f"Account '{account_id}' is not active.")
        return False

    import tempfile

    with tempfile.TemporaryDirectory(prefix=f"fb_session_{account_id}_") as temp_dir_str:
        session_dir = Path(temp_dir_str)

        fp = fp_module.get_or_create_fingerprint(account_id, session_dir)
        fp_launch = fp_module.get_launch_args(fp)
        proxy_dict = parse_proxy(acc_doc.get("proxy", ""))

        launch_kwargs = dict(
            user_data_dir=str(session_dir),
            headless=is_headless,
            slow_mo=50,
            **fp_launch
        )
        if proxy_dict:
            launch_kwargs["proxy"] = proxy_dict

        # Load session state from MongoDB Atlas
        db_session = auto_db.load_account_session_state(account_id)
        saved_cookies = db_session.get("cookies") or acc_doc.get("cookies", [])

        with sync_playwright() as p:
            context = None
            try:
                context = p.chromium.launch_persistent_context(**launch_kwargs)
                if saved_cookies:
                    context.add_cookies(saved_cookies)

                page = context.new_page()
                fp_module.apply_stealth_sync(page, fp)

                add_state_log(f"[{account_id}] Navigating to Facebook...")
                page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)

                if STOP_EVENT.is_set():
                    context.close()
                    auto_db.release_all_account_locks(account_id)
                    return False

                is_logged_in, reason = is_facebook_logged_in(page)
                if not is_logged_in:
                    auto_db.deactivate_account(account_id)
                    auto_db.save_log(account_id, "https://www.facebook.com", "Login Check", "failed", reason)
                    add_state_log(f"[{account_id}] Login check failed: {reason}")
                    return False

                bot = FacebookBot(account_id, page_instance=page, context_instance=context)

                if task_type == "Post Engagement (Like & Comment)":
                    if post_url.strip():
                        raw_urls = post_url.replace("\n", ",").split(",")
                        post_targets = [{"post_url": u.strip(), "comment_text": comment_text} for u in raw_urls if u.strip()]
                    else:
                        db_posts = auto_db.load_posts()
                        post_targets = [p for p in db_posts if p.get("platform", "facebook").lower() == "facebook" and p.get("status", "pending") in ("pending", "active")]

                    if total_accs > 1 and len(post_targets) > 0:
                        post_targets = post_targets[acc_index::total_accs]

                    limit_posts = post_targets if group_cap <= 0 else post_targets[:group_cap]
                    if not limit_posts:
                        add_state_log(f"[{account_id}] No pending post engagement targets found in queue.")

                    for target in limit_posts:
                        if STOP_EVENT.is_set():
                            add_state_log(f"[{account_id}] Stopping execution as requested.")
                            break

                        u = target.get("post_url", "")
                        c_text = comment_text.strip() or target.get("comment_text", "")
                        add_state_log(f"[{account_id}] Engagement target: {u}")
                        liked, commented = bot.like_and_comment_post(u, c_text, min_delay=min_delay, max_delay=max_delay)
                        auto_db.save_post_engagement_result(account_id, u, liked, commented, comment_text=c_text, note=f"Liked={liked}, Commented={commented}")
                        auto_db.save_log(account_id, u, "Post Engagement", "success" if (liked or commented) else "failed", f"Liked={liked}, Commented={commented}")

                        # Anti-ban human delay between post targets
                        if not STOP_EVENT.is_set():
                            sleep_time = random.uniform(min_delay, max_delay)
                            add_state_log(f"[{account_id}] Safe human pause ({int(sleep_time)}s)...")
                            time.sleep(sleep_time)

                elif task_type in ("Group Join & Post", "Group Join & Hello Post"):
                    if target_groups is not None:
                        groups = target_groups
                    else:
                        groups = auto_db.get_pending_group_tasks(account_id, platform="facebook", status="pending")
                        if total_accs > 1 and len(groups) > 0:
                            groups = groups[acc_index::total_accs]

                    limit_groups = groups if group_cap <= 0 else groups[:group_cap]
                    if not limit_groups:
                        add_state_log(f"[{account_id}] No pending group tasks found in queue.")

                    for g_idx, g in enumerate(limit_groups, 1):
                        if STOP_EVENT.is_set():
                            add_state_log(f"[{account_id}] Stopping execution as requested.")
                            break

                        g_url = g["group_url"]
                        if isinstance(message, dict):
                            post_text = message.get(account_id, "") or g.get("post_content", "")
                        else:
                            post_text = (message or "").strip() or g.get("post_content", "")

                        if not auto_db.claim_specific_group_task(account_id, g_url):
                            continue

                        add_state_log(f"[{account_id}] Processing group ({g_idx}/{len(limit_groups)}): {g_url}")

                        try:
                            page.goto(g_url, wait_until="domcontentloaded", timeout=45000)
                            page.wait_for_timeout(3000)
                        except Exception as goto_err:
                            auto_db.finalize_group_task(account_id, g_url, status="failed", note=str(goto_err))
                            auto_db.save_log(account_id, g_url, "Navigate Group", "failed", str(goto_err))
                            continue

                        if STOP_EVENT.is_set():
                            auto_db.release_all_account_locks(account_id)
                            break

                        join_st, join_note = join_fb_group(page)
                        auto_db.save_log(account_id, g_url, "Join Group", join_st, join_note)
                        add_state_log(f"[{account_id}] Join status: {join_st}")
                        page.wait_for_timeout(3000)

                        if join_st in ("joined", "already_joined") and not STOP_EVENT.is_set():
                            muted = mute_fb_group(page)
                            auto_db.save_log(account_id, g_url, "Mute Notifications", "success" if muted else "skipped", "")
                            page.wait_for_timeout(2000)

                            if not STOP_EVENT.is_set():
                                post_st, post_note = post_to_fb_group(page, post_text)
                                auto_db.save_log(account_id, g_url, "Post Content", post_st, post_note)
                                add_state_log(f"[{account_id}] Post status: {post_st}")

                                if post_st == "posted":
                                    still_visible = verify_post_not_deleted(page, g_url, post_text)
                                    final_st = "success" if still_visible else "auto_deleted"
                                    auto_db.finalize_group_task(account_id, g_url, status=final_st, note=post_note, post_content=post_text)
                                elif post_st == "submitted":
                                    auto_db.finalize_group_task(account_id, g_url, status="submitted", note=post_note, post_content=post_text)
                                else:
                                    auto_db.finalize_group_task(account_id, g_url, status="failed", note=post_note or join_note, post_content=post_text)

                        # Anti-ban human delay between group tasks
                        if not STOP_EVENT.is_set():
                            sleep_time = random.uniform(min_delay, max_delay)
                            add_state_log(f"[{account_id}] Safe human pause ({int(sleep_time)}s)...")
                            time.sleep(sleep_time)

                return True

            except Exception as e:
                logger.error(f"[{account_id}] Automation error: {e}")
                add_state_log(f"[{account_id}] Automation error: {e}")
                auto_db.release_all_account_locks(account_id)
                return False
            finally:
                auto_db.release_all_account_locks(account_id)
                if context:
                    try:
                        updated_cookies = context.cookies()
                        auto_db.save_account_session_state(account_id, cookies=updated_cookies)
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
