"""
fingerprint.py
--------------
Per-account browser fingerprint manager.

Behaviour
---------
- First run for an account  → generates a unique fingerprint, saves it to
  <session_dir>/fingerprint.json
- Every subsequent run      → loads the SAVED fingerprint from that file.
  The browser looks identical across all sessions for that account.

Each account gets a DIFFERENT fingerprint (seeded by account_id hash), but
all fingerprints stay within your team's base profile family:
  Linux x86_64 · Chrome 120-124 · Intel WebGL · en-GB · Asia/Singapore
  1920 × 1080 · colorDepth 24

What gets spoofed per page (via playwright-stealth + add_init_script)
----------------------------------------------------------------------
1.  navigator.webdriver          → undefined
2.  navigator.userAgent          → per-account Chrome UA
3.  navigator.platform           → "Linux x86_64"
4.  navigator.language           → "en-GB"
5.  navigator.languages          → ["en-GB", "en", "en-US"]
6.  navigator.hardwareConcurrency → 4 or 8 (per account)
7.  navigator.deviceMemory       → 4 or 8 (per account)
8.  navigator.cookieEnabled      → true
9.  navigator.plugins            → realistic Chrome plugin list
10. screen.width/height          → 1920 × 1080
11. screen.colorDepth/pixelDepth → 24
12. window.devicePixelRatio      → 1
13. Date.getTimezoneOffset()     → -480 (Asia/Singapore)
14. WebGL vendor / renderer      → per-account Intel GPU string
15. window.chrome runtime object → full object (absent in headless bots)
16. Canvas fingerprint           → tiny per-account pixel offset
17. AudioContext fingerprint     → tiny per-account channel noise
18. Permissions API              → reports 'granted' properly
19. outerWidth / outerHeight     → match viewport
"""

import hashlib
import json
import random
from pathlib import Path


# ── Team base profile (constants that every account shares) ──────────────────
_BASE = {
    "platform":                "Linux x86_64",
    "language":                "en-GB",
    "languages":               ["en-GB", "en", "en-US"],
    "accept_language":         "en-GB,en,en-US",
    "timezone":                "Asia/Singapore",
    "timezone_offset_minutes": -480,
    "viewport":                {"width": 1920, "height": 1080},
    "screen": {
        "width":               1920,
        "height":              1080,
        "device_scale_factor": 1,
        "color_depth":         24,
        "pixel_depth":         24,
    },
    "device_scale_factor":     1,
    "color_scheme":            "light",
    "is_mobile":               False,
    "has_touch":               False,
    # Team fingerprint identity
    "fp_hashed":  "e1efefc40f80b2c7e4880297f4e3b2c1a4101e09",
    "cookie_id":  "591f5656-2f91-4efb-8324-541d7d45380e",
}

# ── Per-account variable pools (picked deterministically by account_id hash) ──
_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_WEBGL_PROFILES = [
    ("Intel Inc.", "Intel Iris OpenGL Engine"),
    ("Intel Inc.", "Intel(R) UHD Graphics 620"),
    ("Intel Inc.", "Intel(R) UHD Graphics 630"),
    ("Intel Inc.", "Intel(R) Iris(R) Xe Graphics"),
    ("Intel Inc.", "Intel(R) HD Graphics 520"),
]

_HW_CONCURRENCY = [4, 4, 8, 8, 8]
_DEVICE_MEMORY  = [4, 4, 8]


# ── Fingerprint file name inside each account's session directory ─────────────
FP_FILENAME = "fingerprint.json"


def _seed_rng(account_id: str) -> random.Random:
    """Deterministic RNG seeded by account_id SHA-256 hash."""
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _generate_new(account_id: str) -> dict:
    """
    Create a brand-new unique fingerprint for *account_id*.
    Values are deterministic — same account_id always produces the same result.
    """
    rng = _seed_rng(account_id)

    webgl_vendor, webgl_renderer = rng.choice(_WEBGL_PROFILES)

    fp = dict(_BASE)  # start from team base
    fp.update({
        "account_id":           account_id,
        "user_agent":           rng.choice(_USER_AGENTS),
        "webgl_vendor":         webgl_vendor,
        "webgl_renderer":       webgl_renderer,
        "hardware_concurrency": rng.choice(_HW_CONCURRENCY),
        "device_memory":        rng.choice(_DEVICE_MEMORY),
        # Tiny unique offsets so canvas/audio hashes differ between accounts
        "canvas_noise":         rng.randint(1, 9),
        "audio_noise":          round(rng.uniform(0.0000005, 0.000005), 10),
    })
    return fp


def get_or_create_fingerprint(account_id: str, session_dir: str | Path) -> dict:
    """
    Load an existing fingerprint for *account_id* from <session_dir>/fingerprint.json.
    If the file does not exist, generate a new one and save it.

    Parameters
    ----------
    account_id  : unique account identifier (used as seed if generating)
    session_dir : the account's persistent session directory

    Returns
    -------
    dict  — the fingerprint that will be applied to the browser.
    """
    session_path = Path(session_dir)
    session_path.mkdir(parents=True, exist_ok=True)
    fp_path = session_path / FP_FILENAME

    if fp_path.exists():
        with open(fp_path, "r", encoding="utf-8") as f:
            fp = json.load(f)
        print(f"  [fingerprint] Loaded saved fingerprint for {account_id}  ({fp_path})")
        print(f"  [fingerprint] UA       : {fp['user_agent'][:70]}")
        print(f"  [fingerprint] WebGL    : {fp['webgl_vendor']} / {fp['webgl_renderer']}")
        print(f"  [fingerprint] HW cores : {fp['hardware_concurrency']}  |  RAM: {fp['device_memory']} GB")
        return fp

    # First time — generate and persist
    fp = _generate_new(account_id)
    with open(fp_path, "w", encoding="utf-8") as f:
        json.dump(fp, f, indent=2, ensure_ascii=False)

    print(f"  [fingerprint] Generated NEW fingerprint for {account_id}")
    print(f"  [fingerprint] Saved to : {fp_path}")
    print(f"  [fingerprint] UA       : {fp['user_agent'][:70]}")
    print(f"  [fingerprint] WebGL    : {fp['webgl_vendor']} / {fp['webgl_renderer']}")
    print(f"  [fingerprint] HW cores : {fp['hardware_concurrency']}  |  RAM: {fp['device_memory']} GB")
    return fp


def get_launch_args(fp: dict) -> dict:
    """
    Build the kwargs to merge into playwright.chromium.launch_persistent_context().
    Context-level settings applied before any page loads.
    """
    screen = fp["screen"]
    return {
        "user_agent":          fp["user_agent"],
        "locale":              fp["language"],
        "timezone_id":         fp["timezone"],
        "viewport":            fp["viewport"],
        "screen":              {"width": screen["width"], "height": screen["height"]},
        "device_scale_factor": fp["device_scale_factor"],
        "color_scheme":        fp["color_scheme"],
        "is_mobile":           fp["is_mobile"],
        "has_touch":           fp["has_touch"],
        "extra_http_headers": {
            "Accept-Language": fp["accept_language"],
        },
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-ipc-flooding-protection",
            "--disable-client-side-phishing-detection",
            "--password-store=basic",
            "--use-mock-keychain",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
        "ignore_default_args": ["--enable-automation"],
    }


def _build_stealth_js(fp: dict) -> str:
    """
    JavaScript injected via add_init_script().
    Fires BEFORE any page script — overrides cannot be detected.
    Uses the account's unique saved fingerprint values.
    """
    platform       = fp["platform"]
    hw_concurrency = fp["hardware_concurrency"]
    dev_memory     = fp["device_memory"]
    languages      = json.dumps(fp["languages"])
    language       = fp["language"]
    tz_offset      = fp["timezone_offset_minutes"]
    screen         = fp["screen"]
    webgl_vendor   = fp["webgl_vendor"]
    webgl_renderer = fp["webgl_renderer"]
    canvas_noise   = fp.get("canvas_noise", 1)
    audio_noise    = fp.get("audio_noise", 0.0000012345)

    return f"""
// ─── 1. Remove webdriver flag ─────────────────────────────────────────────
Object.defineProperty(navigator, 'webdriver', {{
    get: () => undefined, configurable: true
}});

// ─── 2. Platform ──────────────────────────────────────────────────────────
Object.defineProperty(navigator, 'platform', {{
    get: () => '{platform}', configurable: true
}});

// ─── 3. Language / locale ─────────────────────────────────────────────────
Object.defineProperty(navigator, 'language', {{
    get: () => '{language}', configurable: true
}});
Object.defineProperty(navigator, 'languages', {{
    get: () => {languages}, configurable: true
}});

// ─── 4. Hardware ──────────────────────────────────────────────────────────
Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => {hw_concurrency}, configurable: true
}});
Object.defineProperty(navigator, 'deviceMemory', {{
    get: () => {dev_memory}, configurable: true
}});
Object.defineProperty(navigator, 'cookieEnabled', {{
    get: () => true, configurable: true
}});

// ─── 5. Screen ────────────────────────────────────────────────────────────
Object.defineProperty(screen, 'width',       {{ get: () => {screen["width"]},        configurable: true }});
Object.defineProperty(screen, 'height',      {{ get: () => {screen["height"]},       configurable: true }});
Object.defineProperty(screen, 'availWidth',  {{ get: () => {screen["width"]},        configurable: true }});
Object.defineProperty(screen, 'availHeight', {{ get: () => {screen["height"] - 40},  configurable: true }});
Object.defineProperty(screen, 'colorDepth',  {{ get: () => {screen["color_depth"]},  configurable: true }});
Object.defineProperty(screen, 'pixelDepth',  {{ get: () => {screen["pixel_depth"]},  configurable: true }});
Object.defineProperty(window, 'devicePixelRatio', {{ get: () => {screen["device_scale_factor"]}, configurable: true }});
Object.defineProperty(window, 'outerWidth',  {{ get: () => {screen["width"]},  configurable: true }});
Object.defineProperty(window, 'outerHeight', {{ get: () => {screen["height"]}, configurable: true }});

// ─── 6. Timezone offset ───────────────────────────────────────────────────
Date.prototype.getTimezoneOffset = function() {{ return {tz_offset}; }};

// ─── 7. Plugin list ───────────────────────────────────────────────────────
try {{
    const makePlugin = (name, desc, filename) => Object.create(Plugin.prototype, {{
        name:        {{ value: name,     enumerable: true }},
        description: {{ value: desc,     enumerable: true }},
        filename:    {{ value: filename, enumerable: true }},
        length:      {{ value: 1,        enumerable: true }},
    }});
    const fakePlugins = [
        ['PDF Viewer',               'Portable Document Format', 'internal-pdf-viewer'],
        ['Chrome PDF Viewer',        'Portable Document Format', 'internal-pdf-viewer'],
        ['Chromium PDF Viewer',      'Portable Document Format', 'internal-pdf-viewer'],
        ['Microsoft Edge PDF Viewer','Portable Document Format', 'internal-pdf-viewer'],
        ['WebKit built-in PDF',      'Portable Document Format', 'internal-pdf-viewer'],
    ].map(([n,d,f]) => makePlugin(n,d,f));
    Object.defineProperty(navigator, 'plugins', {{
        get: () => Object.assign(Object.create(PluginArray.prototype), fakePlugins, {{ length: fakePlugins.length }}),
        configurable: true
    }});
}} catch(e) {{}}

// ─── 8. window.chrome runtime object ─────────────────────────────────────
if (!window.chrome) {{
    window.chrome = {{
        app: {{
            isInstalled: false,
            InstallState: {{ DISABLED:'disabled', INSTALLED:'installed', NOT_INSTALLED:'not_installed' }},
            RunningState: {{ CANNOT_RUN:'cannot_run', READY_TO_RUN:'ready_to_run', RUNNING:'running' }},
        }},
        runtime: {{
            connect: () => {{}},
            sendMessage: () => {{}},
        }},
        csi: () => {{}},
        loadTimes: () => {{}}
    }};
}}

// ─── 9. WebGL vendor & renderer ───────────────────────────────────────────
try {{
    [WebGLRenderingContext, WebGL2RenderingContext].forEach(ctx => {{
        const _orig = ctx.prototype.getParameter;
        ctx.prototype.getParameter = function(p) {{
            if (p === 37445) return '{webgl_vendor}';
            if (p === 37446) return '{webgl_renderer}';
            return _orig.call(this, p);
        }};
    }});
}} catch(e) {{}}

// ─── 10. Canvas noise (unique per account: offset = {canvas_noise}) ────────
try {{
    const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, ...args) {{
        const ctx = this.getContext('2d');
        if (ctx && this.width > 0 && this.height > 0) {{
            const d = ctx.getImageData(0, 0, 1, 1);
            d.data[0] = Math.min(255, d.data[0] + {canvas_noise});
            ctx.putImageData(d, 0, 0);
        }}
        return _toDataURL.call(this, type, ...args);
    }};
}} catch(e) {{}}

// ─── 11. Audio noise (unique per account) ────────────────────────────────
try {{
    const _proto = typeof BaseAudioContext !== 'undefined'
        ? BaseAudioContext.prototype : AudioContext.prototype;
    const _orig = _proto.createBuffer;
    _proto.createBuffer = function(...args) {{
        const buf = _orig.apply(this, args);
        const origGet = buf.getChannelData.bind(buf);
        buf.getChannelData = function(ch) {{
            const data = origGet(ch);
            data[0] += {audio_noise:.10f};
            return data;
        }};
        return buf;
    }};
}} catch(e) {{}}

// ─── 12. Permissions API ──────────────────────────────────────────────────
try {{
    const _q = Permissions.prototype.query;
    Permissions.prototype.query = function(p) {{
        if (p.name === 'notifications')
            return Promise.resolve({{ state: Notification.permission, onchange: null }});
        return _q.call(this, p);
    }};
}} catch(e) {{}}
"""


def apply_stealth_sync(page, fp: dict) -> None:
    """
    Apply full fingerprint spoofing synchronously to *page*.
    Must be called on the thread executing sync_playwright().
    """
    try:
        from playwright_stealth import Stealth
        stealth = Stealth(
            navigator_user_agent_override=fp["user_agent"],
            navigator_platform_override=fp["platform"],
            navigator_languages_override=tuple(fp["languages"][:2]),
            webgl_vendor_override=fp["webgl_vendor"],
            webgl_renderer_override=fp["webgl_renderer"],
            chrome_runtime=False,
        )
        stealth.apply_stealth_sync(page)
    except Exception as e:
        print(f"  [fingerprint] Stealth sync warning: {e}")

    page.add_init_script(_build_stealth_js(fp))


async def apply_stealth(page, fp: dict) -> None:
    """
    Apply full fingerprint spoofing to *page*.
    Call immediately after page creation, before any navigation.
    """
    try:
        from playwright_stealth import Stealth
        stealth = Stealth(
            navigator_user_agent_override=fp["user_agent"],
            navigator_platform_override=fp["platform"],
            navigator_languages_override=tuple(fp["languages"][:2]),
            webgl_vendor_override=fp["webgl_vendor"],
            webgl_renderer_override=fp["webgl_renderer"],
            chrome_runtime=False,
        )
        await stealth.apply_stealth_async(page)
    except Exception as e:
        print(f"  [fingerprint] Stealth async warning: {e}")

    await page.add_init_script(_build_stealth_js(fp))
