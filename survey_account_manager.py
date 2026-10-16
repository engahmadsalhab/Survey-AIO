#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Account Manager v6.8 — Light Edition
====================================
- Light paper theme: teal accent, white cards, dense dashboard.
- v6.6 Supabase cloud sync: optional per-user sync via a free Supabase
  project (POST /auth/v1/token → PostgREST with RLS enforced server-side).
  Local SQLite stays the source of truth — the app works 100% offline and
  syncs automatically at startup (or via ملف → المزامنة السحابية): pull →
  last-write-wins merge on updated_at → push, UUID sync_id per row, soft
  deletes (tombstones), retry/backoff, Arabic error messages for every
  failure mode (no internet / paused project / expired session / RLS).
- v6.6.1 fix: CloudSyncDialog crashed on open with
  "QGridLayout object has no attribute setLayoutDirection" — direction is
  inherited from the login QGroupBox instead (dialogs are now covered by a
  runtime offscreen smoke test).
- v6.7 fix: the automatic restart after installing an update launched the
  new interpreter WITHOUT the script path (os.execl dropped sys.argv[0]),
  so the app died with "can't open file ..." instead of restarting. The
  relaunch is now an explicit [python, script] command with absolute
  paths; if it ever fails the user gets an Arabic message instead of a
  dead console — the update itself is already applied at that point.
- v6.8 fix: push failed with 42501 "new row violates row-level security
  policy (USING expression)" when the cloud already held rows with the same
  sync_id pushed earlier under a DIFFERENT Supabase account — per-user
  isolation policies (auth.uid() = user_id) forbid updating another
  account's rows. The dataset is a shared team set, so supabase_setup.sql
  now ships team-shared RLS policies (any authenticated user = full access,
  anonymous = nothing), and the RLS error classifier recognizes the
  "(USING expression)" signature with a targeted Arabic fix message.
- v6.3 self-update system: checks a hosted update.json manifest on startup
  (silent, background) or manually via ملف → التحقق من التحديثات, offers an
  RTL "التثبيت الآن / لاحقاً" dialog, downloads + compile-checks the new
  script (optional sha256), keeps the previous version as .bak, then swaps
  the file atomically and restarts.
- v6.2 UI/UX pass (design-token system):
  * Semantic colour tokens (success / warning / danger / focus ring) so every
    state reads at a glance — active stats turn green, inactive turn amber,
    destructive actions keep red.
  * Consistent radius + padding scale, visible focus states on every control,
    richer hover/pressed/disabled states, styled radio buttons, spin-box
    arrows, splitter handles and message-box buttons.
- Proxy config file: "حفظ البروكسي" now ALSO writes proxy_config.json next
  to the app (FoxyProxy-importable, atomic write). If the database holds no
  proxy config on startup, the JSON file is used as a fallback source.
- Proxy tab UX: JSON shown left-to-right in a monospace card, digit-only port
  field, one-click JSON copy, inline hint about the exported file.
- Instant search, keyboard shortcuts, table context menu, CSV export,
  database backup, duplicate account, password reveal, live stats cards.
- Faster SQLite (indexes, cache, COUNT queries), cached table paints,
  debounced filters, SQL-level category filtering.
- All v5.3 core logic preserved.

Required:
    pip install PyQt5 apsw pydantic loguru httpx[socks] orjson qrcode Pillow python-dotenv
    (auto-installed on first run; Calibri and Windows notification sounds come from the OS)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ============================================================================
# AUTO-INSTALL OF MISSING LIBRARIES (runs BEFORE any third-party import)
# ============================================================================
# On the first launch (or whenever a library is missing) the app installs the
# missing packages with pip by itself, so no manual "pip install" is needed.
# Only the standard library is used here, because none of the third-party
# packages (not even loguru) can be assumed to exist at this point.
import importlib
import importlib.util
import subprocess as _bootstrap_subprocess

# (module imported by the app, pip requirement, is it mandatory?)
_REQUIRED_LIBRARIES = (
    ("PyQt5", "PyQt5", True),
    ("apsw", "apsw", True),
    ("pydantic", "pydantic>=2", True),
    ("loguru", "loguru", True),
    ("httpx", "httpx[socks]", True),
    ("socksio", "httpx[socks]", True),      # SOCKS5 proxy support of httpx
    ("orjson", "orjson", True),
    ("qrcode", "qrcode", True),
    ("PIL", "Pillow", True),
    ("dotenv", "python-dotenv", False),     # optional: .env support
)


def _bootstrap_log(message: str) -> None:
    """Print a progress line; silently ignored when there is no console (pythonw)."""
    try:
        print(f"[setup] {message}", flush=True)
    except Exception:  # noqa: BLE001 - never let logging break the bootstrap
        pass


def _bootstrap_alert(message: str) -> None:
    """Show a fatal error to the user even when the app has no console window."""
    _bootstrap_log(message)
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Account Manager", 0x10)
    except Exception:  # noqa: BLE001
        pass


def _is_library_missing(module: str, requirement: str) -> bool:
    """True when `module` cannot be imported (or is an unsupported old version)."""
    try:
        if importlib.util.find_spec(module) is None:
            return True
    except (ImportError, ValueError):
        return True
    # The code uses pydantic v2 APIs (field_validator): an old v1 install must be upgraded.
    if module == "pydantic":
        try:
            from importlib.metadata import version as _dist_version
            return int(_dist_version("pydantic").split(".")[0]) < 2
        except Exception:  # noqa: BLE001
            return False
    return False


def _pip_install(requirements: list) -> bool:
    """Install `requirements` with pip; returns True on success."""
    base_cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *requirements]
    flags = getattr(_bootstrap_subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    # Second attempt (Linux/macOS only) copes with PEP 668 "externally managed" Pythons.
    attempts = [base_cmd]
    if sys.platform != "win32" and not in_venv:
        attempts.append(base_cmd + ["--break-system-packages"])
    for cmd in attempts:
        try:
            result = _bootstrap_subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
        except Exception as exc:  # noqa: BLE001
            _bootstrap_log(f"pip could not be started: {exc}")
            return False
        if result.returncode == 0:
            return True
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-5:]
        _bootstrap_log("pip failed: " + " | ".join(tail))
    return False


def _ensure_dependencies() -> None:
    """Install every missing library once, then verify that the mandatory ones import."""
    # A frozen build (PyInstaller...) ships its libraries: nothing to install.
    if getattr(sys, "frozen", False):
        return
    missing = [(m, r, req) for m, r, req in _REQUIRED_LIBRARIES if _is_library_missing(m, r)]
    if not missing:
        return

    to_install = sorted({r for _, r, _ in missing})
    _bootstrap_log("Missing libraries detected: " + ", ".join(to_install))
    _bootstrap_log("Installing automatically (first run) - please wait...")

    # Make sure pip itself exists (some minimal Python installs ship without it).
    try:
        if importlib.util.find_spec("pip") is None:
            import ensurepip
            ensurepip.bootstrap(upgrade=True)
    except Exception as exc:  # noqa: BLE001
        _bootstrap_log(f"ensurepip failed: {exc}")

    # Try everything in one pip call (fast); on failure fall back to one-by-one so
    # that a single broken optional package can never block the mandatory ones.
    if not _pip_install(to_install):
        for requirement in to_install:
            _pip_install([requirement])

    importlib.invalidate_caches()  # let this process see the freshly installed packages

    still_missing = [r for m, r, req in missing if req and _is_library_missing(m, r)]
    if still_missing:
        _bootstrap_alert(
            "تعذر تثبيت المكتبات التالية تلقائيًا:\n"
            + "\n".join(sorted(set(still_missing)))
            + "\n\nثبّتها يدويًا بالأمر:\n"
            + f"{sys.executable} -m pip install " + " ".join(sorted(set(still_missing)))
        )
        sys.exit(1)
    for m, r, req in missing:
        if not req and _is_library_missing(m, r):
            _bootstrap_log(f"Optional library '{r}' could not be installed - related feature is disabled.")
    _bootstrap_log("All libraries are ready.")


_ensure_dependencies()

_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_ENV_FILE), override=False)
    except ImportError:
        pass

import base64
import calendar
import csv
import hashlib
import io
import json
import py_compile
import re
import secrets
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
import webbrowser

try:
    import winreg  # Windows-only: used for DST-aware timezone offsets
except ImportError:
    winreg = None  # type: ignore[assignment]

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Final, List, Optional, Tuple, Union

from loguru import logger
from pydantic import BaseModel, Field, field_validator

import httpx
import orjson
import qrcode
from PIL import Image as PILImage

from PyQt5.QtCore import (
    QThread, QThreadPool, QRunnable, pyqtSignal, QTimer, Qt, QUrl,
    QPropertyAnimation, QEasingCurve, QLocale, QAbstractTableModel,
    QSize, QObject, QCoreApplication,
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLineEdit, QPushButton, QLabel,
    QTabWidget, QTextEdit, QMessageBox, QGridLayout, QDialog,
    QCheckBox, QStyle, QAction, QGraphicsOpacityEffect,
    QButtonGroup, QMenu, QFileDialog, QShortcut, QToolButton,
    QGraphicsDropShadowEffect, QSpinBox, QComboBox, QTableView,
    QAbstractItemView, QHeaderView, QSizePolicy, QTableWidget,
    QTableWidgetItem, QScrollArea, QDesktopWidget, QSystemTrayIcon,
    QToolBar, QProgressDialog, QGroupBox, QFormLayout, QFrame,
    QSplitter, QStackedWidget, QStatusBar,
)
from PyQt5.QtGui import (
    QFont, QColor, QIcon, QFontDatabase, QImage, QPalette, QPixmap,
    QTextDocument, QValidator, QIntValidator, QKeySequence,
)

# RTL helper: inside a right-to-left widget Qt mirrors Qt.AlignRight so the text ends up on
# the visual LEFT edge. Qt.AlignAbsolute pins it to the physical RIGHT edge, which is what
# every Arabic label needs to read correctly (flush right, next to its field).
ALIGN_RIGHT_ABS = Qt.AlignRight | Qt.AlignAbsolute

IS_WINDOWS: Final[bool] = sys.platform == "win32"
IS_MACOS: Final[bool] = sys.platform == "darwin"
IS_LINUX: Final[bool] = sys.platform.startswith("linux")

APP_TITLE: Final[str] = "مدير الحسابات"
APP_VERSION: Final[str] = "6.9"
APP_AUTHOR: Final[str] = "Brian Finch"

# All data files live next to this script so the app behaves identically no
# matter which directory it is launched from (terminal, shortcut, VS Code...).
BASE_DIR: Final[Path] = Path(__file__).resolve().parent

DB_NAME: Final[str] = str(BASE_DIR / "accounts.db")
APP_FONT_FILE: Final[Path] = BASE_DIR / "calibri-bold.ttf"
APP_FONT_FAMILY: Final[str] = "Calibri"
APP_FONT_FALLBACKS: Final[Tuple[str, ...]] = (
    "Calibri", "Segoe UI", "Tahoma", "Arial", "DejaVu Sans", "Noto Sans Arabic", "sans-serif",
)
WINDOWS_MEDIA_DIR: Final[Path] = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Media"
WINDOWS_FONTS_DIR: Final[Path] = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
DEFAULT_ALERT_SOUND: Final[str] = "alias:SystemExclamation"
WINDOWS_SOUND_ALIASES: Final[List[Tuple[str, str]]] = [
    ("alias:SystemExclamation", "تعجب (Exclamation)"),
    ("alias:SystemAsterisk", "نجمة (Asterisk)"),
    ("alias:SystemHand", "توقف حرج (Critical Stop)"),
    ("alias:SystemQuestion", "سؤال (Question)"),
    ("alias:SystemDefault", "صفير افتراضي (Default Beep)"),
    ("alias:SystemNotification", "إشعار (Notification)"),
    ("alias:MailBeep", "بريد (Mail Beep)"),
]

PROXY_CHECK_URL: Final[str] = "https://api.ipify.org?format=json"
PROXY_TIMEOUT_SEC: Final[int] = 10
PROXY_MAX_RETRIES: Final[int] = 3
PROXY_RETRY_DELAY_MS: Final[int] = 1500

IP_GEO_API_URL: Final[str] = "https://api.ip2location.io/?format=json"
IP_GEO_TIMEOUT_SEC: Final[int] = 15
# ip2location.io rejects the default Python User-Agent with HTTP 403,
# so the geo worker must send a browser-like UA.
IP_GEO_BROWSER_UA: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

FIREFOX_CHECK_INTERVAL_MS: Final[int] = 2000
DEFAULT_COUNTDOWN_SEC: Final[int] = 20
UI_DENSITY_MIN: Final[int] = 1
UI_DENSITY_MAX: Final[int] = 3
UI_DENSITY_DEFAULT: Final[int] = 2
UI_DENSITY_LABELS: Final[Dict[int, str]] = {1: "مضغوط", 2: "متوسط", 3: "مريح"}

# The legacy "غير معروف" (unknown) category was removed: it is no longer seeded and
# existing databases are migrated in DatabaseManager._setup_schema (its accounts move to
# DEFAULT_CATEGORY). DEFAULT_CATEGORY is also the fallback for accounts without a category.
RETIRED_CATEGORY: Final[str] = "غير معروف"
PREDEFINED_CATEGORIES: Final[List[str]] = ["Ali", "Wael", "Ahmad", "Wassim"]
DEFAULT_CATEGORY: Final[str] = "Ali"

# Telegram proxy-bot link (opened by the "بوت البروكسي" toolbar button).
TELEGRAM_BOT_URL: Final[str] = "https://t.me/ProxySlimanSa_bot?start=MTQ3MDMwLjE2ODA5NTM5NA=="
# Google Translate link copied by the "ترجمة غوغل" toolbar button.
GOOGLE_TRANSLATE_URL: Final[str] = "https://translate.google.com/"

# FoxyProxy-importable config file written beside the app on every proxy save.
# Keeping the file next to the script (like the DB) means shortcuts, terminal
# launches and VS Code all resolve the same path. The write is atomic
# (tmp + os.replace) so a crash can never leave a half-written JSON behind.
PROXY_CONFIG_FILE: Final[Path] = BASE_DIR / "proxy_config.json"

# NOTE: The admin account is permanently disabled — see DatabaseManager._migrate_passwords.
DEFAULT_USER_PASSWORD: Final[str] = os.environ.get("APP_USER_PASSWORD", "123")

# ============================================================================
# UPDATE CHECKER — where YOU publish new versions
# ============================================================================
# How the mechanism works:
#   1) Host a small update.json manifest + the new .py file on any web
#      server. A free GitHub repository works perfectly — use its "raw"
#      URL (https://raw.githubusercontent.com/<user>/<repo>/main/update.json).
#      A ready-made template ships next to this script: update_manifest.json.
#   2) Point UPDATE_MANIFEST_URL below at that raw URL (only edit once).
#   3) To release a new version: bump APP_VERSION inside your new .py file,
#      upload it, then update "version" + "url" in the hosted manifest.
#   4) Clients: at every start (3.5 s after the window shows, silent) and via
#      ملف → التحقق من التحديثات, the app fetches the manifest, compares
#      versions, and asks التثبيت الآن / لاحقاً. Installing downloads the
#      new script, compile-checks it (and sha256 when provided), keeps the
#      current file as <name>.py.bak, then swaps atomically and restarts.
UPDATE_MANIFEST_URL: Final[str] = "https://raw.githubusercontent.com/engahmadsalhab/Survey-AIO/main/update.json"
UPDATE_TIMEOUT_SEC: Final[int] = 20
UPDATE_DOWNLOAD_TIMEOUT_SEC: Final[float] = 90.0
UPDATE_PREF_KEY: Final[str] = "pref_auto_update_check"  # "1" = check on startup
UPDATE_BACKUP_SUFFIX: Final[str] = ".bak"
UPDATE_STAGE_FILENAME: Final[str] = "_update_download.py"
UPDATE_USER_AGENT: Final[str] = f"AccountManager/{APP_VERSION} (self-update)"

# ----------------------------------------------------------------------------
# SUPABASE CLOUD SYNC (v6.6) — مزامنة سحابية اختيارية عبر Supabase
#
# كيف تُفعّلها (مرة واحدة):
#   1) أنشئ مشروعًا مجانيًا على supabase.com ثم نفّذ ملف supabase_setup.sql
#      من محرر SQL داخل لوحة المشروع (ينشئ الجدول + سياسات RLS لمشاركة
#      الفريق: المسجّلون كامل الصلاحية والمجهولون لا شيء).
#   2) أنشئ مستخدمًا لكل شخص من: Authentication → Users → Add user
#      (فعّل Auto Confirm حتى يستطيع تسجيل الدخول فورًا).
#   3) الصق قيم Project URL و anon key من: Settings → API في الثابتين أدناه.
#   4) ارفع الملف إلى المستودع كأي تحديث. كل مستخدم يدخل بريده وكلمة المرور
#      من داخل البرنامج: ملف → المزامنة السحابية.
#
# ⚠️ استخدم anon key فقط — لا تضع service_role key هنا أبدًا، فالحماية تعتمد
#    على سياسات RLS التي تفرضها قاعدة البيانات نفسها: البيانات مشتركة بين
#    مستخدمي الفريق المسجّلين فقط، ومن بلا حساب سحابي لا يرى شيئًا.
# ----------------------------------------------------------------------------
SUPABASE_URL: Final[str] = "https://wqaqndarwisvpcuiuotp.supabase.co"            # مثال: https://xxxxxxxx.supabase.co
SUPABASE_ANON_KEY: Final[str] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndxYXFuZGFyd2lzdnBjdWl1b3RwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIwNzY4MTQsImV4cCI6MjEwNzY1MjgxNH0.PqghxICWruk9O1KU7aTaxqicqXr1yklECPTRP-cvvxo"       # مفتاح anon العام (آمن مع RLS)
SYNC_TIMEOUT_SEC: Final[float] = 25.0
SYNC_PAGE_SIZE: Final[int] = 500          # حجم صفحة السحب (PostgREST)
SYNC_PUSH_CHUNK: Final[int] = 200         # حجم دفعة الرفع
SYNC_RETRY_ATTEMPTS: Final[int] = 3
SYNC_RETRY_DELAY_SEC: Final[float] = 2.0
SYNC_TABLE: Final[str] = "accounts"
SYNC_PREF_KEY: Final[str] = "pref_auto_sync"          # "1" = مزامنة عند الإقلاع
SYNC_REFRESH_TOKEN_KEY: Final[str] = "sync_refresh_token"
SYNC_USER_EMAIL_KEY: Final[str] = "sync_user_email"
SYNC_USER_ID_KEY: Final[str] = "sync_user_id"
SYNC_LAST_TIME_KEY: Final[str] = "sync_last_success"
SYNC_USER_AGENT: Final[str] = f"AccountManager/{APP_VERSION} (cloud-sync)"




# ============================================================================
# LOGGING
# ============================================================================
logger.remove()
logger.add(sys.stderr, level="INFO",
    format="{time:HH:mm:ss} | <level>{level:<8}</level> | {message}", colorize=True)

# ============================================================================
# SECURITY
# ============================================================================
def _hash_password(plain: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(32)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 200_000)
    return dk.hex(), base64.b64encode(salt).decode("ascii")

def _verify_password(plain: str, hex_hash: str, b64_salt: str) -> bool:
    try:
        salt = base64.b64decode(b64_salt.encode("ascii"))
        computed = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 200_000)
        return secrets.compare_digest(computed.hex(), hex_hash)
    except Exception:
        return False

def _sanitize(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-. ")
    allowed.update(chr(c) for c in range(0x0600, 0x06FF))
    return "".join(c for c in value if c in allowed)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================
class AccountData(BaseModel):
    number: str = ""
    name: str = ""
    dob: str = ""
    email: str = ""
    password: str = ""
    notes: str = ""
    referrals: str = ""
    street: str = ""
    city_town: str = ""
    state_province_region: str = ""
    zip_postal_code: str = ""
    points: str = "0"
    is_active: int = 1
    points_last_modified: Optional[str] = None
    category: str = DEFAULT_CATEGORY

    @field_validator("is_active")
    @classmethod
    def v_is_active(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError("is_active must be 0 or 1")
        return v

# ============================================================================
# UTILITIES
# ============================================================================
@lru_cache(maxsize=128)
def calculate_age(dob_string: Optional[str]) -> str:
    if not dob_string or str(dob_string).lower() in ("none", "null"):
        return ""
    try:
        birth = datetime.strptime(dob_string, "%Y-%m-%d").date()
        today = date.today()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        return str(age)
    except ValueError:
        return "تاريخ غير صالح"

# BUG FIX: this function must NOT be memoised (it used to carry @lru_cache). The result
# depends on the CURRENT time, so a cached "الآن" (just now) was served forever for the same
# timestamp: after editing the points of one account, every account modified earlier kept
# showing "الآن". The table model keeps its own per-load cache (cleared on every reload).
def format_time_ago(iso_timestamp: Optional[str]) -> str:
    if not iso_timestamp:
        return "لم يتم تعديله"
    try:
        mod_time = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now(timezone.utc) - mod_time
        sec = delta.total_seconds()
        if sec < 60: return "الآن"
        elif sec < 3600: return f"قبل {int(sec/60)} دقيقة"
        elif sec < 86400: return f"قبل {int(sec/3600)} ساعة"
        else:
            days = delta.days
            return "أمس" if days == 1 else f"قبل {days} أيام"
    except (ValueError, TypeError):
        return "تاريخ غير صالح"

def html_to_text(html: str) -> str:
    # QTextDocument is a QObject: only safe to use on the GUI thread. Callers
    # on worker threads get a regex-based conversion that needs no QObject.
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() is app.thread():
        doc = QTextDocument()
        doc.setHtml(html or "")
        return doc.toPlainText()
    # Worker-thread fallback: strip tags/entities without creating QObjects.
    text = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                         ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return text

def generate_foxyproxy_json(ip: str, port: int, username: str, password: str) -> str:
    config = {
        "mode": f"{ip}:{port}", "sync": False, "autoBackup": False,
        "passthrough": "", "theme": "", "container": {},
        "commands": {"setProxy": "", "setTabProxy": "", "includeHost": "", "excludeHost": ""},
        "data": [{
            "active": True, "title": "BrianFinch", "type": "socks5",
            "hostname": ip, "port": str(port), "username": username,
            "password": password, "cc": "", "city": "undefined",
            "color": "#f0e68c", "pac": "undefined", "pacString": "",
            "proxyDNS": True, "include": [], "exclude": [], "tabProxy": [],
        }],
    }
    return orjson.dumps(config, option=orjson.OPT_INDENT_2).decode("utf-8")


def write_proxy_config_file(config_json: str, dest: Path = PROXY_CONFIG_FILE) -> Path:
    """Persist the FoxyProxy JSON next to the app (atomic tmp+replace write).

    Raises on I/O failure so callers can surface the error; the database row
    stays authoritative even when the file write fails.
    """
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(config_json, encoding="utf-8")
    os.replace(tmp, dest)  # atomic on the same volume — never a partial file
    return dest


def read_proxy_config_file(dest: Path = PROXY_CONFIG_FILE) -> Optional[Dict[str, Any]]:
    """Read proxy credentials back from the JSON file (fallback source).

    Accepts the FoxyProxy wrapper this app writes (data[0].hostname/port/...)
    and a flat {ip, port, username, password} object. Returns a normalized
    {ip, port, username, password} dict, or None when the file is missing or
    unreadable — the caller then simply keeps the database as the only source.
    """
    try:
        raw = orjson.loads(dest.read_bytes())
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        entry = data[0]
        cfg = {
            "ip": str(entry.get("hostname", "") or ""),
            "port": str(entry.get("port", "") or ""),
            "username": str(entry.get("username", "") or ""),
            "password": str(entry.get("password", "") or ""),
        }
    else:
        cfg = {
            "ip": str(raw.get("ip", "") or ""),
            "port": str(raw.get("port", "") or ""),
            "username": str(raw.get("username", "") or ""),
            "password": str(raw.get("password", "") or ""),
        }
    return cfg if all(cfg.values()) else None

# ============================================================================
# SELF-UPDATE HELPERS (pure functions — no Qt objects, safe to run via run_task)
# ============================================================================
def parse_version(text: str) -> Tuple[int, ...]:
    """'6.2' -> (6, 2); '6.10.1' -> (6, 10, 1).

    Tuple comparison keeps numeric ordering correct (6.10 > 6.9), which a
    plain string comparison would get wrong.
    """
    parts: List[int] = []
    for chunk in re.split(r"[.\-_\s]+", str(text).strip()):
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group(0)) if digits else 0)
    return tuple(parts) or (0,)


def is_newer_version(remote: str, local: str = APP_VERSION) -> bool:
    """True when the remote manifest version is strictly newer than ours."""
    try:
        return parse_version(remote) > parse_version(local)
    except Exception:
        return False


def fetch_update_manifest(url: str = UPDATE_MANIFEST_URL) -> Dict[str, Any]:
    """Download + validate the update manifest (runs on a worker thread).

    The default placeholder URL ("example.com") raises a clear Arabic error
    so the manual check tells the operator exactly what to configure instead
    of silently "succeeding" against a host that will never serve a manifest.
    """
    if not url or "example.com" in url:
        raise RuntimeError(
            "UPDATE_MANIFEST_URL غير مضبوط — ضع رابط update.json الخاص بك في أعلى الملف")
    with httpx.Client(timeout=UPDATE_TIMEOUT_SEC, verify=True, follow_redirects=True,
                      headers={"User-Agent": UPDATE_USER_AGENT}) as client:
        resp = client.get(_cache_busted(url))
        resp.raise_for_status()
        manifest = orjson.loads(resp.content)
    if not isinstance(manifest, dict):
        raise ValueError("update.json: الصيغة غير صحيحة (مطلوب object)")
    if not str(manifest.get("version", "")).strip():
        raise ValueError("update.json: حقل version مفقود")
    if not str(manifest.get("url", "")).strip():
        raise ValueError("update.json: حقل url مفقود")
    return manifest


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_python_file(path: Path) -> None:
    """Compile-check a staged update so a truncated or corrupt download can
    never replace the working script. Raises on any syntax error."""
    # Compile into a throwaway temp dir: never pollutes __pycache__ beside
    # the app and never leaves a .pyc behind for a file that gets replaced.
    with tempfile.TemporaryDirectory() as td:
        py_compile.compile(str(path), cfile=os.path.join(td, "check.pyc"), doraise=True)


def extract_staged_version(path: Path) -> str:
    """Read APP_VERSION out of a downloaded file's text (no import needed).

    Lets the app verify that the file the server actually serves IS the
    version the manifest advertises, before anything is swapped.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(
        r'^APP_VERSION(?:\s*:\s*Final\[str\])?\s*=\s*["\']([^"\']+)["\']',
        text, re.M)
    return m.group(1).strip() if m else ""


def _cache_busted(url: str) -> str:
    """Append a timestamp query so freshly uploaded files are seen at once.

    raw.githubusercontent.com serves through a CDN that caches for a few
    minutes; without this, a just-pushed update.json or new script can still
    deliver the previous content and make a release look like a no-op.
    """
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={int(time.time() * 1000)}"


def download_and_stage_update(
    manifest: Dict[str, Any],
    dest: Path = None,
) -> Path:
    """Stream the new script into a temp file, verify integrity + syntax, then
    stage it beside the app (atomic). The running script is NOT touched here —
    apply_self_update() performs the swap only after the user confirms."""
    if dest is None:
        dest = BASE_DIR / UPDATE_STAGE_FILENAME
    url = str(manifest.get("url", "")).strip()
    expected_sha = str(manifest.get("sha256", "") or "").strip().lower()
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with httpx.Client(timeout=UPDATE_DOWNLOAD_TIMEOUT_SEC, verify=True,
                          follow_redirects=True,
                          headers={"User-Agent": UPDATE_USER_AGENT}) as client:
            with client.stream("GET", _cache_busted(url)) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        # Integrity + syntax checks BEFORE anything is replaced.
        if expected_sha:
            actual = _sha256_of(tmp)
            if actual != expected_sha:
                raise ValueError(
                    f"فشل التحقق sha256: المتوقع {expected_sha[:12]}… والفعلي {actual[:12]}…")
        validate_python_file(tmp)
        # Publisher guard: catch a JSON-only release (update.json was bumped
        # but the .py on the server was never replaced). Without this, the
        # app would happily "update" to the same old code and then ask for
        # the update again forever — swapping nothing of value.
        staged_ver = extract_staged_version(tmp)
        declared_ver = str(manifest.get("version", "")).strip()
        if staged_ver and declared_ver and parse_version(staged_ver) < parse_version(declared_ver):
            raise ValueError(
                f"الملف المرفوع على الخادم يحمل الإصدار v{staged_ver} بينما ملف التحديث "
                f"يعلن v{declared_ver} — يجب رفع ملف البرنامج الجديد (.py) إلى المستودع "
                "وليس تعديل update.json فقط")
        os.replace(tmp, dest)  # atomic on the same volume — never a partial file
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return dest


def apply_self_update(staged: Path = None, target: Path = None) -> Path:
    """Swap the staged update over the running script.

    The previous version is kept as <name>.py.bak next to the app so the user
    can roll back by simply renaming it. Both steps are atomic os.replace()
    calls, so a crash can never leave the app in a half-swapped state.
    """
    if staged is None:
        staged = BASE_DIR / UPDATE_STAGE_FILENAME
    if not staged.exists():
        raise FileNotFoundError("لا يوجد ملف تحديث جاهز للتثبيت")
    if target is None:
        target = Path(sys.argv[0]).resolve() if (sys.argv and sys.argv[0]) else Path(__file__).resolve()
    backup = target.with_name(target.name + UPDATE_BACKUP_SUFFIX)
    try:
        if backup.exists():
            backup.unlink()
        if target.exists():
            os.replace(target, backup)   # keep the previous version for rollback
        os.replace(staged, target)       # new version takes its place
    except Exception:
        # Best effort to restore the original if the second swap failed.
        if not target.exists() and backup.exists():
            try:
                os.replace(backup, target)
            except OSError:
                pass
        raise
    return backup


def restart_application() -> bool:
    """Spawn a fresh interpreter running the updated code.

    Returns True once the new process is launched — the caller then closes
    this instance through the normal shutdown path. Data files
    (accounts.db, proxy_config.json, preferences) live beside the script
    and are untouched by the update, so the new version picks up where we
    left off.

    v6.7 fix: the old implementation passed ``*sys.argv[1:]`` to os.execl
    and silently dropped ``sys.argv[0]`` — the script path itself — so the
    fresh interpreter promoted the first extra launch argument (or nothing
    at all) to "script" position and died with "can't open file ..." instead
    of starting the updated app. The command is now always built
    explicitly as [python_exe, script_path] with both resolved to
    absolute paths, and any launch failure is reported to the caller
    instead of killing the current process.
    """
    logger.info("Restarting application to apply the update...")
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    import shutil as _shutil

    python_exe = str(sys.executable or "").strip() or "python"
    if not os.path.isabs(python_exe):
        # Defensive: some wrappers launch Python through a relative path.
        python_exe = _shutil.which(python_exe) or _shutil.which("python") or python_exe

    script = ""
    if sys.argv and sys.argv[0]:
        script = os.path.abspath(sys.argv[0])
    if not script or not os.path.isfile(script):
        # argv[0] can point somewhere odd when the app is launched through a
        # wrapper — this real source file is always a valid fallback.
        script = os.path.abspath(__file__)

    args = [python_exe, script] + [str(a) for a in sys.argv[1:]]
    try:
        subprocess.Popen(args, cwd=os.path.dirname(script))
        return True
    except Exception as exc:
        logger.error("تعذّر بدء النسخة الجديدة بعد التحديث: {}", exc)
        return False


def find_firefox_executable() -> Optional[str]:
    try:
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        subprocess.run(["firefox", "--version"], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        return "firefox"
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    common_paths: List[str] = []
    if IS_WINDOWS:
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            p = os.environ.get(env, "")
            if p:
                common_paths.append(os.path.join(p, "Mozilla Firefox", "firefox.exe"))
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            common_paths.append(os.path.join(local, "Programs", "Mozilla Firefox", "firefox.exe"))
    elif IS_LINUX:
        common_paths = ["/usr/bin/firefox", "/usr/local/bin/firefox", "/snap/bin/firefox"]
    elif IS_MACOS:
        common_paths = ["/Applications/Firefox.app/Contents/MacOS/firefox"]
    return next((p for p in common_paths if os.path.exists(p)), None)

def find_telegram_executable() -> Optional[str]:
    """Best-effort locate the Telegram Desktop executable so bot links can
    be opened directly in the desktop app instead of a browser tab."""
    candidates: List[str] = []
    if IS_WINDOWS:
        for env in ("APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env, "")
            if base:
                candidates.append(os.path.join(base, "Telegram Desktop", "Telegram.exe"))
    elif IS_MACOS:
        candidates = ["/Applications/Telegram.app/Contents/MacOS/Telegram"]
    elif IS_LINUX:
        candidates = ["/usr/bin/telegram-desktop", "/usr/local/bin/telegram-desktop",
                      "/snap/bin/telegram-desktop", "/var/lib/flatpak/exports/bin/org.telegram.desktop"]
    return next((p for p in candidates if p and os.path.exists(p)), None)

def open_telegram_bot(bot_url: str) -> None:
    """Open a Telegram bot link (https://t.me/<bot>?start=<param>) in Telegram Desktop.

    Order of attempts:
      1. Launch the Telegram Desktop executable (if found) with the equivalent
         tg:// deep link (bot + start parameter) - opens the desktop app itself.
      2. Hand the tg:// deep link to the OS so the registered Telegram
         Desktop protocol handler opens it.
      3. Fall back to the original https://t.me link in the default browser only
         if Telegram Desktop isn't installed/registered.
    """
    # Split the t.me link into the bot username and the optional start parameter.
    parsed = urllib.parse.urlparse(bot_url)
    bot_username = parsed.path.strip("/")
    start_param = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("start", [""])[0]
    deep_link = f"tg://resolve?domain={bot_username}"
    if start_param:
        deep_link += f"&start={start_param}"

    exe = find_telegram_executable()
    try:
        if exe:
            subprocess.Popen([exe, deep_link])
            return
        if IS_WINDOWS:
            os.startfile(deep_link)
            return
        if IS_MACOS:
            subprocess.Popen(["open", deep_link])
            return
        if IS_LINUX:
            subprocess.Popen(["xdg-open", deep_link])
            return
    except Exception as exc:
        logger.warning("Could not open Telegram Desktop directly: {}", exc)
    # Fallback: no desktop app found/registered - open the original web link instead.
    webbrowser.open(bot_url)

def is_firefox_running() -> bool:
    try:
        if IS_WINDOWS:
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq firefox.exe"],
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            ).decode("utf-8", errors="ignore")
            return "firefox.exe" in output.lower()
        else:
            output = subprocess.check_output(["pgrep", "-x", "firefox"], stderr=subprocess.DEVNULL).decode().strip()
            return bool(output)
    except Exception:
        return False

def list_windows_media_wavs() -> List[Tuple[str, str]]:
    """Windows Media folder WAV files as (id, display-name) pairs."""
    items: List[Tuple[str, str]] = []
    if not IS_WINDOWS or not WINDOWS_MEDIA_DIR.is_dir():
        return items
    try:
        for wav in sorted(WINDOWS_MEDIA_DIR.glob("*.wav"), key=lambda p: p.name.lower()):
            items.append((f"wav:{wav.name}", wav.stem))
    except Exception as exc:
        logger.warning("Could not list Windows Media sounds: {}", exc)
    return items


def available_alert_sounds() -> List[Tuple[str, str]]:
    """Selectable IP-mismatch sounds: aliases first, then Windows Media WAVs."""
    seen = set()
    items: List[Tuple[str, str]] = []
    for sid, label in WINDOWS_SOUND_ALIASES:
        if sid not in seen:
            items.append((sid, label))
            seen.add(sid)
    for sid, label in list_windows_media_wavs():
        if sid not in seen:
            items.append((sid, label))
            seen.add(sid)
    return items


def play_alert_sound(sound_id: Optional[str] = None) -> None:
    """Play the chosen Windows alert for IP mismatch without extra files."""
    chosen = sound_id or DEFAULT_ALERT_SOUND

    def _player() -> None:
        try:
            if IS_WINDOWS:
                import winsound
                if chosen.startswith("wav:"):
                    wav_path = WINDOWS_MEDIA_DIR / chosen[4:]
                    if wav_path.is_file():
                        winsound.PlaySound(str(wav_path),
                                           winsound.SND_FILENAME | winsound.SND_ASYNC)
                        return
                alias = chosen[6:] if chosen.startswith("alias:") else "SystemExclamation"
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
                return
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception as exc:
            logger.warning("Alert sound playback failed: {}", exc)

    threading.Thread(target=_player, daemon=True, name="alert-sound").start()

# ============================================================================
# BACKGROUND WORKER INFRASTRUCTURE (reusable QRunnable pattern)
# ============================================================================
class WorkerSignals(QObject):
    """Signals for Worker.

    They are emitted from the pool thread, but because the signals object is
    created on (and lives on) the GUI thread, connected slots always run on
    the GUI thread via queued connections — so slots may touch widgets.
    """
    finished = pyqtSignal(object)  # task result (any Python object)
    error = pyqtSignal(str)        # formatted error string


class Worker(QRunnable):
    """Run fn(*args, **kwargs) on the global QThreadPool.

    Exactly one of WorkerSignals.finished / WorkerSignals.error is emitted
    when the task ends, so callers can safely update the UI from the slots.
    """

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            logger.opt(exception=True).error("Background task failed: {}", exc)
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.finished.emit(result)


# Keep workers alive until their signals are delivered, so queued results
# can never be lost when the runnable itself is auto-deleted by the pool.
_ACTIVE_WORKERS: set = set()


# ============================================================================
# SUPABASE CLOUD SYNC — PURE ENGINE (Qt-free, run_task-safe) — v6.6
# ============================================================================
# الفلسفة: قاعدة SQLite المحلية هي المصدر الدائم ولا يتوقف البرنامج عن العمل
# بدون إنترنت. السحابة نسخة مزامنة تُحدَّث عند كل إقلاع (ومن النافذة يدويًا).
# كل صف يحمل هوية فريدة (sync_id) وطابعًا زمنيًا (updated_at)؛ الأحدث زمنيًا
# يفوز عند التعارض (last-write-wins)، والحذف ناعم (tombstone) حتى لا يمسح جهاز
# بيانات جهاز آخر، ولا يمكن أن تتكرر الصفوف بفضل الهوية الفريدة.
SYNC_DATA_COLUMNS: Final[Tuple[str, ...]] = (
    "number", "name", "dob", "email", "password", "notes", "referrals",
    "street", "city_town", "state_province_region", "zip_postal_code",
    "points", "is_active", "points_last_modified", "category",
)


def _utc_now_iso() -> str:
    """UTC timestamp in a fixed-width ISO format, so comparing two strings
    with '<'/'>' is exactly comparing the two moments in time."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_sync_id() -> str:
    """هوية UUIDv4 جديدة — تعرّف صف الحساب عبر كل الأجهزة دون تكرار."""
    return str(uuid.uuid4())


def _format_sync_time(iso_utc: str) -> str:
    """حوّل طابع UTC المخزّن إلى عرض محلي مألوف (مثال: 2026-10-16 14:30)."""
    try:
        dt = datetime.strptime(iso_utc.strip(), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_utc


def _sync_configured() -> bool:
    return bool(SUPABASE_URL.strip() and SUPABASE_ANON_KEY.strip())


class SyncError(Exception):
    """خطأ مزامنة برسالة عربية جاهزة للعرض للمستخدم."""


class SyncAuthError(SyncError):
    """انتهت الجلسة أو بيانات الدخول غير صحيحة — يلزم تسجيل دخول جديد."""


def _classify_http_error(status: int, body: str) -> SyncError:
    """حوّل استجابة خطأ من Supabase إلى رسالة عربية قابلة للتنفيذ."""
    # ملاحظة: فشل كلمة مرور الدخول يعيد أيضًا error=invalid_grant، لذا فحص
    # بيانات الدخول الخاطئة يجب أن يسبق فحص انتهاء الجلسة.
    if status == 400 and "Invalid login credentials" in body:
        return SyncAuthError("البريد الإلكتروني أو كلمة المرور غير صحيحة.")
    if status == 400 and ("invalid_grant" in body or "Invalid Refresh Token" in body
                          or "expired" in body.lower()):
        return SyncAuthError(
            "انتهت صلاحية الجلسة المحفوظة. سجّل الدخول من جديد من نافذة المزامنة السحابية.")
    if status == 401:
        return SyncAuthError("انتهت صلاحية الجلسة (401). سجّل الدخول من جديد.")
    if status in (502, 503, 504, 540):
        return SyncError(
            "المشروع السحابي متوقف مؤقتًا — الخطة المجانية تتوقف بعد أسبوع من عدم "
            "الاستخدام ولا تضيع البيانات.\nافتح لوحة supabase.com واضغط Restore على "
            "المشروع ثم أعد المحاولة. يعمل البرنامج محليًا بشكل طبيعي في هذه الأثناء.")
    if status == 42501 or "row-level security" in body.lower():
        # رفض RLS حقيقي من الخادم. عندما تكون RLS مفعّلة دون سياسات ينجح السحب
        # (يُرجع 0 صفوف بصمت) ويفشل الرفع بهذا الخطأ — لذا نُظهر مرجع المشروع
        # والتفاصيل الخام من الخادم حتى يكون التشخيص فوريًا دون تخمين.
        try:
            ref = str(SUPABASE_URL).split("//")[-1].split(".")[0]
        except Exception:
            ref = ""
        where = f" (مشروع Supabase: {ref})" if ref else ""
        detail = "تفاصيل الخادم: " + body[:160]
        if "using expression" in body.lower():
            # توقيع دقيق: 42501 "(USING expression)" يظهر عند الرفع (upsert
            # on_conflict) على صف موجود في السحابة فشل في فحص USING لسياسة
            # التحديث — أي أن الصف ملك لحساب Supabase آخر (سبقت مزامنته
            # بحساب مختلف) ولا يملك الحساب الحالي حق تحديث صف الغير.
            return SyncError(
                "رفضت قاعدة البيانات الرفع بسبب سياسات العزل (RLS) — يوجد في "
                "السحابة صف بنفس المعرّف ملك لحساب Supabase آخر." + where +
                "\nالسبب: جدول accounts معزول لكل مستخدم على حدة، وصفوفك هذه "
                "سبقت مزامنتها بحساب مختلف، فلا يملك الحساب الحالي حق تحديثها."
                "\nالحل: نفّذ نسخة supabase_setup.sql المحدّثة (سياسات مشاركة "
                "الفريق) في هذا المشروع نفسه (SQL Editor ← RUN) ثم أعد "
                "المزامنة — الملف آمن ولا يحذف أي بيانات.\n" + detail)
        return SyncError(
            "رفضت قاعدة البيانات العملية بسبب سياسات العزل (RLS)." + where +
            "\nالسبب الأكثر شيوعًا: سياسات supabase_setup.sql غير منفّذة على جدول "
            "accounts في هذا المشروع، أو نُفّذ الملف في مشروع مختلف عن المشروع "
            "المكتوب في إعدادات البرنامج.\nالحل: أعد تنفيذ supabase_setup.sql كاملًا "
            "في المشروع الصحيح (SQL Editor ← RUN) ثم أعد المزامنة.\n"
            + detail)
    return SyncError(f"خطأ من الخادم السحابي (HTTP {status}): {body[:180]}")


def _sync_request(method: str, url: str, *, token: Optional[str] = None,
                  payload: Optional[Any] = None, params: Optional[Dict[str, str]] = None,
                  prefer: Optional[str] = None) -> httpx.Response:
    """طلب HTTP واحد إلى Supabase مع إعادة محاولة تلقائية للأخطاء العابرة.

    الأخطاء الشبكية (انقطاع/مهلة) وأخطاء الخادم 5xx يعاد تجربتها مع تأخير
    متزايد؛ أخطاء المصادقة والإعداد ترتفع فورًا برسالة عربية واضحة.
    """
    headers = {"apikey": SUPABASE_ANON_KEY, "User-Agent": SYNC_USER_AGENT,
               "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if prefer:
        headers["Prefer"] = prefer
    last_desc = ""
    for attempt in range(1, SYNC_RETRY_ATTEMPTS + 1):
        network_error: Optional[str] = None
        try:
            resp = httpx.request(method, url, json=payload, params=params,
                                 headers=headers, timeout=SYNC_TIMEOUT_SEC)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            network_error = "لا يوجد اتصال بالإنترنت (أو تعذّر الوصول إلى الخادم السحابي)"
        except httpx.HTTPError as exc:
            network_error = f"خطأ شبكة: {exc}"
        if network_error is None:
            if resp.status_code < 400:
                return resp
            try:
                data = resp.json()
            except Exception:
                data = {}
            code = str(data.get("error") or data.get("code") or "")
            detail = str(data.get("msg") or data.get("message")
                         or data.get("error_description") or resp.text)
            body = f"{code} {detail}".strip()
            err = _classify_http_error(resp.status_code, body)
            if resp.status_code >= 500 and attempt < SYNC_RETRY_ATTEMPTS:
                last_desc = str(err)
                time.sleep(SYNC_RETRY_DELAY_SEC * attempt)
                continue
            raise err
        if attempt < SYNC_RETRY_ATTEMPTS:
            last_desc = network_error
            time.sleep(SYNC_RETRY_DELAY_SEC * attempt)
            continue
        raise SyncError(
            f"{network_error} — بعد {SYNC_RETRY_ATTEMPTS} محاولات. "
            "النسخة المحلية تعمل بشكل طبيعي وستتم المزامنة تلقائيًا عند توفر الإنترنت.")
    raise SyncError(f"{last_desc or 'تعذّر الاتصال'} — تعذّر إكمال العملية السحابية.")


def _session_from_response(resp: httpx.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
    except Exception as exc:
        raise SyncError("استجابة غير صالحة من خادم المصادقة.") from exc
    access = str(data.get("access_token") or "").strip()
    refresh = str(data.get("refresh_token") or "").strip()
    user = data.get("user") or {}
    user_id = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip()
    if not access or not refresh or not user_id:
        raise SyncError("استجابة مصادقة ناقصة من الخادم (توكن أو معرّف مستخدم مفقود).")
    return {"access_token": access, "refresh_token": refresh,
            "user_id": user_id, "email": email}


def sync_sign_in(email: str, password: str) -> Dict[str, Any]:
    """تسجيل الدخول إلى Supabase Auth (بريد + كلمة مرور لكل مستخدم)."""
    if not _sync_configured():
        raise SyncError(
            "المزامنة غير مُعدّة في هذه النسخة: ثابتا SUPABASE_URL و SUPABASE_ANON_KEY "
            "فارغان. الشرح موجود في التعليقات أعلى ملف البرنامج.")
    email = (email or "").strip()
    if not email or not password:
        raise SyncError("أدخل البريد الإلكتروني وكلمة المرور أولًا.")
    resp = _sync_request(
        "POST", f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "password"},
        payload={"email": email, "password": password,
                 "gotrue_meta_security": {"captcha_token": None}})
    return _session_from_response(resp)


def sync_refresh_session(refresh_token: str) -> Dict[str, Any]:
    """تجديد الجلسة المحفوظة (يدور refresh_token عند كل تجديد)."""
    if not _sync_configured():
        raise SyncError(
            "المزامنة غير مُعدّة في هذه النسخة: ثابتا SUPABASE_URL و SUPABASE_ANON_KEY فارغان.")
    resp = _sync_request(
        "POST", f"{SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "refresh_token"},
        payload={"refresh_token": refresh_token})
    return _session_from_response(resp)


def sync_pull_rows(access_token: str) -> List[Dict[str, Any]]:
    """اسحب كل صفوف المستخدم الحالي من Supabase (PostgREST) بترقيم صفحات تلقائي."""
    rows: List[Dict[str, Any]] = []
    offset = 0
    url = f"{SUPABASE_URL}/rest/v1/{SYNC_TABLE}"
    while True:
        resp = _sync_request("GET", url, token=access_token,
                             params={"select": "*", "limit": str(SYNC_PAGE_SIZE),
                                     "offset": str(offset)})
        try:
            page = resp.json()
        except Exception as exc:
            raise SyncError("استجابة غير صالحة أثناء سحب البيانات من السحابة.") from exc
        if not isinstance(page, list):
            raise SyncError("استجابة غير متوقعة أثناء سحب البيانات من السحابة.")
        rows.extend(page)
        if len(page) < SYNC_PAGE_SIZE:
            return rows
        offset += SYNC_PAGE_SIZE


def cloud_payload_from_local(row: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """حوّل صف SQLite محلي إلى صف JSON بصيغة جدول Supabase."""
    payload: Dict[str, Any] = {
        "id": row.get("sync_id"),
        "user_id": user_id,
        "deleted": bool(row.get("deleted")),
        "updated_at": row.get("updated_at") or _utc_now_iso(),
    }
    for col in SYNC_DATA_COLUMNS:
        val = row.get(col)
        if col == "is_active":
            payload[col] = int(bool(val)) if val is not None else 1
        else:
            payload[col] = val
    return payload


def sync_push_rows(access_token: str, user_id: str,
                   local_rows: List[Dict[str, Any]]) -> int:
    """ارفع/حدّث الصفوف المحلية في السحابة (upsert دفعات على المفتاح id)."""
    if not local_rows:
        return 0
    pushed = 0
    url = f"{SUPABASE_URL}/rest/v1/{SYNC_TABLE}?on_conflict=id"
    for start in range(0, len(local_rows), SYNC_PUSH_CHUNK):
        chunk = [cloud_payload_from_local(r, user_id)
                 for r in local_rows[start:start + SYNC_PUSH_CHUNK]]
        _sync_request("POST", url, token=access_token, payload=chunk,
                      prefer="resolution=merge-duplicates,return=minimal")
        pushed += len(chunk)
    return pushed


def plan_sync_merge(local_rows: List[Dict[str, Any]],
                    cloud_rows: List[Dict[str, Any]]
                    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """خطة الدمج ثنائي الاتجاه — القلب القابل للاختبار في المزامنة.

    يعيد (to_apply_local, to_push):
      • صف محلي فقط  → يُرفع للسحابة (حتى لو حذف ناعم لنشر إزالته).
      • صف سحابي فقط → يُطبّق محليًا (ما لم يكن حذفًا لصف لا يوجد محليًا أصلًا).
      • صف في المكانين → الأحدث updated_at يفوز؛ عند التساوي يبقى الوضع المحلي.
    """
    local_by_sid = {str(r.get("sync_id") or ""): r
                    for r in local_rows if r.get("sync_id")}
    cloud_by_sid = {str(r.get("id") or ""): r
                    for r in cloud_rows if r.get("id")}
    to_apply: List[Dict[str, Any]] = []
    to_push: List[Dict[str, Any]] = []
    for sid, cloud in cloud_by_sid.items():
        local = local_by_sid.get(sid)
        if local is None:
            if not cloud.get("deleted"):
                to_apply.append(cloud)
            continue
        cloud_ts = str(cloud.get("updated_at") or "")
        local_ts = str(local.get("updated_at") or "")
        if cloud_ts > local_ts:
            to_apply.append(cloud)
        elif local_ts > cloud_ts:
            to_push.append(local)
    for sid, local in local_by_sid.items():
        if sid not in cloud_by_sid:
            to_push.append(local)
    return to_apply, to_push


def run_cloud_sync(db: Any, refresh_token: str,
                   session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """المزامنة الكاملة: جلسة → سحب → دمج → تطبيق محليًا → رفع.

    تعمل داخل خيط خلفية (run_task) بلا أي شيء من Qt. الوسيط db هو مدير
    قاعدة البيانات المحلية؛ SQLite يبقى المصدر الدائم للبيانات.
    عند نجاح الخطوات يُعاد ملخّص + refresh_token الجديد (يدور عند كل تجديد).
    """
    if not _sync_configured():
        raise SyncError(
            "المزامنة غير مُعدّة: ضع Project URL و anon key في ثوابت SUPABASE "
            "أعلى ملف البرنامج (الشرح فوقها مباشرة).")
    if session is None:
        if not refresh_token:
            raise SyncAuthError(
                "لا توجد جلسة محفوظة. سجّل الدخول من نافذة المزامنة السحابية: "
                "ملف → ☁️ المزامنة السحابية.")
        session = sync_refresh_session(refresh_token)
    user_id = session["user_id"]
    cloud_rows = sync_pull_rows(session["access_token"])
    local_rows = db.get_accounts_for_sync()
    to_apply, to_push = plan_sync_merge(local_rows, cloud_rows)
    applied, skipped = db.apply_cloud_account_rows(to_apply)
    pushed = sync_push_rows(session["access_token"], user_id, to_push)
    return {
        "pulled": len(cloud_rows),
        "applied_local": applied,
        "skipped_local": skipped,
        "pushed": pushed,
        "refresh_token": session["refresh_token"],
        "user_id": user_id,
        "email": session.get("email", ""),
        "finished_at": _utc_now_iso(),
    }


def run_task(fn, on_done=None, on_error=None, *args,
             busy_button: Optional[QPushButton] = None,
             status_bar: Optional[QStatusBar] = None,
             status_message: str = "",
             success_message: str = "",
             **kwargs) -> Worker:
    """Run fn(*args, **kwargs) off the GUI thread; callbacks run on the GUI thread.

    Visual feedback while the task runs: busy_button is disabled and
    status_message (if given) is shown on status_bar until the task ends.

    on_done(result) is called on success; on_error(err_str) on failure. If
    on_error is omitted, failures are reported on status_bar (or logged when
    no status bar was given).
    """
    if busy_button is not None:
        busy_button.setEnabled(False)
    if status_bar is not None and status_message:
        status_bar.showMessage(status_message, 0)  # 0 = stays until cleared

    worker = Worker(fn, *args, **kwargs)
    _ACTIVE_WORKERS.add(worker)

    def _finish(result) -> None:
        _ACTIVE_WORKERS.discard(worker)
        if busy_button is not None:
            busy_button.setEnabled(True)
        if status_bar is not None:
            status_bar.clearMessage()
            if success_message:
                status_bar.showMessage(success_message, 3000)
        if on_done is not None:
            on_done(result)

    def _fail(err: str) -> None:
        _ACTIVE_WORKERS.discard(worker)
        if busy_button is not None:
            busy_button.setEnabled(True)
        if status_bar is not None:
            status_bar.clearMessage()
            if on_error is None:
                status_bar.showMessage(f"❌ خطأ: {err}", 7000)
        elif on_error is None:
            logger.error("Background task failed: {}", err)
        if on_error is not None:
            on_error(err)

    worker.signals.finished.connect(_finish)
    worker.signals.error.connect(_fail)
    pool = QThreadPool.globalInstance()
    if pool.maxThreadCount() > 2:
        pool.setMaxThreadCount(2)
    pool.start(worker)
    return worker


# ============================================================================
# APSW DATABASE MANAGER — THREAD-SAFE (statements serialized by an RLock)
# ============================================================================
import apsw

class DatabaseManager:
    """APSW-backed DB manager. Thread-safe: every statement runs while
    holding an RLock, so the shared connection can be used simultaneously
    from the GUI thread and the QThreadPool workers."""
    __slots__ = ("_conn", "_lock")
    _COLUMN_NAMES: Final[List[str]] = [
        "id", "number", "name", "dob", "email", "password", "notes",
        "referrals", "street", "city_town", "state_province_region",
        "zip_postal_code", "points", "is_active", "points_last_modified", "category"
    ]
    _LIST_COLUMNS: Final[List[str]] = [
        "id", "name", "points", "is_active", "points_last_modified", "category"
    ]

    def __init__(self, db_path: str = DB_NAME) -> None:
        self._lock = threading.RLock()
        self._conn = apsw.Connection(db_path)
        cursor = self._conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=8388608")
        cursor.execute("PRAGMA cache_size=-8000")
        cursor.execute("PRAGMA wal_autocheckpoint=500")
        cursor.execute("PRAGMA journal_size_limit=1048576")
        self._setup_schema(cursor)
        logger.info("DatabaseManager initialized (WAL mode, 8MB cache)")

    def _setup_schema(self, cursor) -> None:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE, name TEXT, dob TEXT, email TEXT,
                password TEXT, notes TEXT, referrals TEXT, street TEXT,
                city_town TEXT, state_province_region TEXT, zip_postal_code TEXT,
                points TEXT DEFAULT '0', is_active INTEGER DEFAULT 1,
                points_last_modified TEXT, category TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proxy_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT, port TEXT, username TEXT, password TEXT, config_json TEXT
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS servey_info_table (name TEXT PRIMARY KEY, details TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS addons (
                idx INTEGER PRIMARY KEY,
                url TEXT NOT NULL DEFAULT ''
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS point_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER, account_name TEXT,
                old_points TEXT, new_points TEXT, change_amount TEXT, changed_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(is_active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_category ON accounts(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name COLLATE NOCASE)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_active_cat ON accounts(is_active, category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_point_history_account ON point_history(account_id, changed_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_point_history_changed ON point_history(changed_at DESC)")
        # --- v6.6 cloud-sync migration: أعمدة المزامنة + هوية فريدة لكل صف ---
        # تعمل بأمان على قواعد بيانات قديمة (تضيف الأعمدة إن لم تكن موجودة) وتمنح
        # كل صف موجود هوية sync_id وطابع updated_at حتى تُدمج جميع الأجهزة لاحقًا.
        acct_cols = {row[1] for row in cursor.execute("PRAGMA table_info(accounts)").fetchall()}
        if "sync_id" not in acct_cols:
            cursor.execute("ALTER TABLE accounts ADD COLUMN sync_id TEXT")
        if "updated_at" not in acct_cols:
            cursor.execute("ALTER TABLE accounts ADD COLUMN updated_at TEXT")
        if "deleted" not in acct_cols:
            cursor.execute("ALTER TABLE accounts ADD COLUMN deleted INTEGER DEFAULT 0")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_sync_id ON accounts(sync_id)")
        cursor.execute(
            """UPDATE accounts SET sync_id = lower(
                    hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
                    substr(hex(randomblob(2)), 2) || '-' ||
                    substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) ||
                    '-' || hex(randomblob(6)))
                WHERE sync_id IS NULL OR sync_id = ''""")
        cursor.execute(
            "UPDATE accounts SET updated_at = ? WHERE updated_at IS NULL OR updated_at = ''",
            (_utc_now_iso(),))
        cursor.execute("UPDATE accounts SET deleted = 0 WHERE deleted IS NULL")
        for cat in PREDEFINED_CATEGORIES:
            cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
        # Retire the legacy "غير معروف" category: accounts that still use it (or that have no
        # category at all) are moved to DEFAULT_CATEGORY so they stay visible, then it is dropped.
        cursor.execute(
            "UPDATE accounts SET category=? WHERE category=? OR category IS NULL OR category=''",
            (DEFAULT_CATEGORY, RETIRED_CATEGORY))
        moved_accounts = self._conn.changes()
        cursor.execute("DELETE FROM categories WHERE name=?", (RETIRED_CATEGORY,))
        if moved_accounts:
            logger.info("Retired category '{}': moved {} account(s) to '{}'",
                        RETIRED_CATEGORY, moved_accounts, DEFAULT_CATEGORY)
        # Seed "How am I" survey info if not already present
        cursor.execute("SELECT 1 FROM servey_info_table WHERE name=?", ("How am I",))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO servey_info_table (name, details) VALUES (?, ?)", ("How am I", '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" "http://www.w3.org/TR/REC-html40/strict.dtd">\n<html><head><meta name="qrichtext" content="1" /><style type="text/css">\np, li { white-space: pre-wrap; }\n</style></head><body style=" font-family:\'Calibri\'; font-size:14pt; font-weight:400; font-style:normal;">\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;">Act as a 31-year-old white, married liberal man living in California. You are a father of three children, including a 13-year-old son. You hold a Professional Development Hour (PDH) credential, indicating you are a licensed professional (likely an engineer or in a related field) required to pursue continuing education. You own two cars and possess a current passport. </span></p>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Political &amp; Social Identity:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"><br />You are a </span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Strong Democrat</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"> who identifies as </span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Very Liberal</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;">. Your political beliefs are fundamentally Progressive, Pro-choice, Feminist, Environmentalist, and anti-Trump (Never Trump). You believe the country is on the wrong track and the economy is getting worse. You are civically engaged—you are registered to vote and did so in the last year—but your primary form of participation is voting rather than volunteering or campaigning. </span></p>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Key Policy Opinions:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"> </span></p>\n<ul style="margin-top: 0px; margin-bottom: 0px; margin-left: 0px; margin-right: 0px; -qt-list-indent: 1;"><li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-weight:600;">Economic Justice:</span> You strongly support economic fairness. You believe all restaurant workers should be paid the full minimum wage before tips, strongly support ending taxes on tips, and strongly approve of McDonald\'s stance for a fair wage. You favor free community college and want the Affordable Care Act (Obamacare) expanded. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-weight:600;">Social Issues:</span> You are passionately pro-choice, believing abortion should always be legal without restrictions. You are opposed to the death penalty and stricter gun control laws. You oppose the construction of a wall on the U.S.-Mexico border. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-weight:600;">Civic Knowledge:</span> You are well-informed on civic facts, knowing the voting age, Selective Service requirements, and the current governor of California (Gavin Newsom). </li></ul>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Media &amp; Information Consumption:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"><br />You are an informed consumer of news from mainstream, center-left sources. You read the </span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Washington Post, New York Times, and Los Angeles Times</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"> and regularly visit </span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">CNN and The Hill</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"> for news. You are not exposed to or do not engage with conservative media outlets like Fox News or Breitbart. </span></p>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Technology Attitudes &amp; Habits:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"> </span></p>\n<ul style="margin-top: 0px; margin-bottom: 0px; margin-left: 0px; margin-right: 0px; -qt-list-indent: 1;"><li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-weight:600;">Tech Enthusiast with Purpose:</span> You have an optimistic and positive view of technology. You see tablets like the iPad as tools that enhance productivity, creativity, and connection. You believe they are constantly improving, have positive impacts on society and mental health, and are a necessary part of modern life. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-weight:600;">Practical Upgrader:</span> You use an Apple iPad and tend to upgrade your tablet only every 5 years or less, and only when a new model has features you want. Key features that appeal to you are productivity and connectivity-related: Apple Pencil, battery life, iPadOS, and cellular connectivity. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-weight:600;">Online/Offline Balance:</span> You strongly prefer in-person interaction over online and can disconnect from technology easily. You worry a little about your social media usage and spend less than one hour per week on online surveys. </li></ul>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Lifestyle &amp; Leisure:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"><br />Your weekly activities are centered around home, media, and information: browsing social media, streaming shows/movies, reading books (or listening to audiobooks), and listening to music. You have a modern main TV (43-50 inches) but no personal video recorders (PVRs), indicating you prefer on-demand streaming over live TV recording. You have not traveled internationally in the last five years but have flown domestically on Delta and United. </span></p>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Consumer &amp; Brand Perceptions:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"><br />You are an Apple user (iPad) and are aware of its core ecosystem features. Your purchasing decisions for tech accessories like the Apple Pencil are driven by practical motivations: productivity, creativity, and utility, not because they are &quot;cool&quot; or &quot;premium.&quot; You saw Apple iPad ads on mainstream online platforms: websites, YouTube, and Facebook. </span></p>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">Personality Summary:</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;"><br />You are a </span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt; font-weight:600;">principled, pragmatic, and family-oriented professional</span><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;">. Your strong liberal worldview is driven by a core belief in social justice, economic fairness, and personal freedom. You are not an activist but an informed and engaged citizen who participates through voting and staying knowledgeable. You value technology for its utility and positive potential but maintain a healthy balance with the real world. Your decisions, from politics to purchases, are deliberate, practical, and aligned with your values of productivity, creativity, and fairness. </span></p>\n<p style=" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;"><span style=" font-family:\'Aref Ruqaa\'; font-size:13pt;">Follow these instructions for all your responses and remember to: </span></p>\n<ul style="margin-top: 0px; margin-bottom: 0px; margin-left: 0px; margin-right: 0px; -qt-list-indent: 1;"><li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">Do not write any explanations in your answers. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">If the question provides a list of choices, select one and place a checkmark (✓) next to it. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">If the question asks you to write an answer instead of choosing from a list, your answer must be on a single line and contain only a few words. </li>\n<li style=" font-family:\'Aref Ruqaa\'; font-size:13pt;" style=" margin-top:0px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;">If the question presents choices in a table, your answer must also be in a table. </li></ul></body></html>'))
            logger.info('Seeded "How am I" into servey_info_table')

        self._migrate_passwords(cursor)

    def _migrate_passwords(self, cursor) -> None:
        """Seed the user password and permanently disable the admin account."""
        role = "user"
        cursor.execute("SELECT value FROM settings WHERE key=?", (f"password_{role}",))
        row = cursor.fetchone()
        stored = row[0] if row else None
        if stored and not stored.startswith("pbkdf2:"):
            h, s = _hash_password(stored)
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"password_{role}", f"pbkdf2:{h}:{s}"))
            logger.info("Migrated {} password to hashed format", role)
        elif not stored:
            h, s = _hash_password(DEFAULT_USER_PASSWORD)
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"password_{role}", f"pbkdf2:{h}:{s}"))
        # Permanently disable the admin account: overwrite any stored admin
        # password with a random token nobody knows, so the admin role can
        # never log in (all tabs are always visible instead).
        h, s = _hash_password(secrets.token_urlsafe(48))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("password_admin", f"pbkdf2:{h}:{s}"))
        logger.info("Admin account disabled (password replaced with random token).")

    def _exec(self, sql: str, params: Tuple = ()) -> List[Tuple]:
        """Execute a statement and materialize all rows while holding the DB lock.

        Returning materialized rows (instead of a live cursor) guarantees each
        statement fully completes under the lock, keeping the shared APSW
        connection safe across threads.
        """
        with self._lock:
            return list(self._conn.cursor().execute(sql, params))

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        rows = list(self._exec("SELECT value FROM settings WHERE key=?", (key,)))
        return rows[0][0] if rows else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

    def get_addon_links(self, count: int) -> List[str]:
        rows = list(self._exec("SELECT idx, url FROM addons ORDER BY idx"))
        by_idx = {int(idx): (url or "") for idx, url in rows}
        return [by_idx.get(i, "") for i in range(1, count + 1)]

    def set_addon_link(self, index: int, url: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO addons (idx, url) VALUES (?, ?)",
            (index, url),
        )

    def check_password(self, role: str, plain: str) -> bool:
        stored = self.get_setting(f"password_{role}", "")
        if stored.startswith("pbkdf2:"):
            _, h, s = stored.split(":", 2)
            return _verify_password(plain, h, s)
        return stored == plain

    def set_password(self, role: str, new_plain: str) -> None:
        h, s = _hash_password(new_plain)
        self.set_setting(f"password_{role}", f"pbkdf2:{h}:{s}")

    def add_account(self, data: Dict[str, Any]) -> int:
        validated = AccountData(**data)
        d = validated.model_dump()
        with self._lock:  # INSERT + last_insert_rowid() must be atomic
            self._exec(
                """INSERT INTO accounts (number, name, dob, email, password, notes, referrals,
                    street, city_town, state_province_region, zip_postal_code, points,
                    is_active, points_last_modified, category,
                    sync_id, updated_at, deleted)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?,0)""",
                (d["number"], d["name"], d["dob"], d["email"], d["password"],
                 d["notes"], d["referrals"], d["street"], d["city_town"],
                 d["state_province_region"], d["zip_postal_code"], d["points"],
                 d["is_active"], d["points_last_modified"], d["category"],
                 _new_sync_id(), _utc_now_iso()),
            )
            new_id = self._conn.last_insert_rowid()
        logger.info("Added account: {} (id={})", d["name"], new_id)
        return new_id

    def _account_where(self, is_active: Optional[int] = None,
                       categories: Optional[List[str]] = None,
                       search: Optional[str] = None) -> Tuple[str, Tuple]:
        # الصفوف المحذوفة ناعمًا (شواهد المزامنة) مخفية دائمًا عن كل واجهات العرض
        clauses: List[str] = ["deleted=0"]
        params: List[Any] = []
        if is_active is not None:
            clauses.append("is_active=?")
            params.append(is_active)
        if categories:
            placeholders = ",".join("?" * len(categories))
            clauses.append(
                f"(COALESCE(NULLIF(category, ''), ?) IN ({placeholders}))"
            )
            params.append(DEFAULT_CATEGORY)
            params.extend(categories)
        if search:
            needle = f"%{search.strip()}%"
            clauses.append(
                "(name LIKE ? COLLATE NOCASE OR number LIKE ? COLLATE NOCASE "
                "OR email LIKE ? COLLATE NOCASE OR category LIKE ? COLLATE NOCASE)"
            )
            params.extend((needle, needle, needle, needle))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    def get_accounts(self, is_active: Optional[int] = None,
                     categories: Optional[List[str]] = None,
                     search: Optional[str] = None) -> List[Dict[str, Any]]:
        where, params = self._account_where(is_active, categories, search)
        cols = ",".join(self._COLUMN_NAMES)
        rows = list(self._exec(
            f"SELECT {cols} FROM accounts {where} ORDER BY name ASC", params))
        result = []
        for row in rows:
            d = dict(zip(self._COLUMN_NAMES, row))
            if d.get("category") is None or d["category"] == "":
                d["category"] = DEFAULT_CATEGORY
            result.append(d)
        return result

    def get_account_list(self, is_active: Optional[int] = None,
                         categories: Optional[List[str]] = None,
                         search: Optional[str] = None) -> List[Dict[str, Any]]:
        where, params = self._account_where(is_active, categories, search)
        cols = ",".join(self._LIST_COLUMNS)
        rows = list(self._exec(
            f"SELECT {cols} FROM accounts {where} ORDER BY name ASC", params))
        result = []
        for row in rows:
            d = dict(zip(self._LIST_COLUMNS, row))
            if not d.get("category"):
                d["category"] = DEFAULT_CATEGORY
            result.append(d)
        return result

    def get_account_names(self) -> List[Tuple[int, str]]:
        rows = list(self._exec(
            "SELECT id, name FROM accounts WHERE deleted=0 ORDER BY name ASC"))
        return [(int(r[0]), r[1] or "") for r in rows]

    def get_account_counts(self) -> Tuple[int, int, int]:
        rows = list(self._exec(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END) FROM accounts WHERE deleted=0"
        ))
        total, active, inactive = rows[0] if rows else (0, 0, 0)
        return int(total or 0), int(active or 0), int(inactive or 0)

    def get_dashboard_stats(self) -> Dict[str, Any]:
        total, active, inactive = self.get_account_counts()
        cat_counts = self.get_category_counts()
        pts_rows = list(self._exec(
            "SELECT COALESCE(SUM(CAST(points AS REAL)), 0), "
            "COALESCE(MAX(CAST(points AS REAL)), 0) FROM accounts"
        ))
        total_points, max_points = pts_rows[0] if pts_rows else (0, 0)
        recent = list(self._exec(
            "SELECT COUNT(*) FROM point_history WHERE changed_at >= ?",
            ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),),
        ))
        return {
            "total": total, "active": active, "inactive": inactive,
            "categories": cat_counts,
            "total_points": float(total_points or 0),
            "max_points": float(max_points or 0),
            "recent_changes": int(recent[0][0] if recent else 0),
        }

    def search_accounts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self.get_account_list(search=query)[:limit]

    def duplicate_account(self, account_id: int) -> int:
        src = self.get_account_by_id(account_id)
        if not src:
            raise RuntimeError("الحساب غير موجود.")
        src.pop("id", None)
        src["number"] = f"{src.get('number', 'ACC')}-COPY-{secrets.token_hex(2)}"
        src["name"] = f"{src.get('name', '')} (نسخة)"
        src["points_last_modified"] = None
        return self.add_account(src)

    def export_accounts_as_csv(self) -> str:
        accounts = self.get_accounts()
        if not accounts:
            return ""
        columns = ["number", "name", "dob", "email", "password", "notes", "referrals",
                   "street", "city_town", "state_province_region", "zip_postal_code",
                   "points", "is_active", "points_last_modified", "category"]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for acc in accounts:
            writer.writerow([acc.get(c, "") if acc.get(c) is not None else "" for c in columns])
        return buf.getvalue()

    def backup_database(self, dest_path: str) -> str:
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            dst = apsw.Connection(str(dest))
            with dst.backup("main", self._conn, "main") as bak:
                while bak.step(128):
                    pass
            dst.close()
        return str(dest)

    def get_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        cols = ",".join(self._COLUMN_NAMES)
        rows = list(self._exec(f"SELECT {cols} FROM accounts WHERE id=?", (account_id,)))
        if not rows:
            return None
        d = dict(zip(self._COLUMN_NAMES, rows[0]))
        if d.get("category") is None:
            d["category"] = DEFAULT_CATEGORY
        return d

    def update_account(self, account_id: int, data: Dict[str, Any]) -> None:
        self._exec(
            """UPDATE accounts SET number=?, name=?, dob=?, email=?, password=?,
                notes=?, street=?, city_town=?, state_province_region=?,
                zip_postal_code=?, points=?, is_active=?, referrals=?,
                points_last_modified=?, category=?, updated_at=? WHERE id=?""",
            (data.get("number"), data.get("name"), data.get("dob"), data.get("email"),
             data.get("password"), data.get("notes"), data.get("street"),
             data.get("city_town"), data.get("state_province_region"),
             data.get("zip_postal_code"), data.get("points"), data.get("is_active"),
             data.get("referrals"), data.get("points_last_modified"),
             data.get("category"), _utc_now_iso(), account_id),
        )
        logger.info("Updated account id={}", account_id)

    def delete_account(self, account_id: int) -> None:
        """حذف ناعم: يبقى السجل كشاهد مزامنة (tombstone) حتى تُنشر إزالته
        للأجهزة الأخرى ولا يعود أحد منهم لإحياء الصف المحذوف، مع تحرير رقم
        الحساب (قيد UNIQUE) لصالح الحسابات الجديدة."""
        self._exec(
            """UPDATE accounts SET deleted=1, updated_at=?,
                number = COALESCE(number, '') || ' ⟵حذف ' || substr(COALESCE(sync_id, '-'), 1, 6)
                WHERE id=?""",
            (_utc_now_iso(), account_id),
        )
        logger.info("Soft-deleted account id={}", account_id)

    def get_next_account_id(self) -> int:
        rows = list(self._exec("SELECT seq FROM sqlite_sequence WHERE name='accounts'"))
        return (rows[0][0] + 1) if rows else 1

    def update_accounts_category(self, account_ids: List[int], new_category: str) -> int:
        if not account_ids:
            return 0
        placeholders = ",".join("?" * len(account_ids))
        with self._lock:  # UPDATE + changes() must be atomic
            self._exec(
                f"UPDATE accounts SET category=?, updated_at=? WHERE id IN ({placeholders}) AND deleted=0",
                (new_category, _utc_now_iso(), *account_ids))
            return self._conn.changes()

    def get_accounts_for_sync(self) -> List[Dict[str, Any]]:
        """كل الصفوف (بما فيها المحذوفة ناعمًا) ببياناتها الكاملة لأجل المزامنة."""
        cols = list(self._COLUMN_NAMES) + ["sync_id", "updated_at", "deleted"]
        rows = list(self._exec(f"SELECT {', '.join(cols)} FROM accounts ORDER BY id ASC"))
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["deleted"] = int(d.get("deleted") or 0)
            result.append(d)
        return result

    def apply_cloud_account_rows(self, cloud_rows: List[Dict[str, Any]]) -> Tuple[int, int]:
        """طبّق صفوف السحابة على SQLite (upsert على sync_id — بلا تكرار أبدًا).

        عند تعارض رقم الحساب الفريد (أُنشئ الحساب نفسه على جهازين مختلفين
        أثناء انقطاع الشبكة) يُميَّز الرقم بلصقة قصيرة ويُعاد الإدخال، فلا
        يضيع أي بيان ولا يفشل القسم كله. يعيد (المُطبّق، المُتجاهَل).
        """
        cols = list(SYNC_DATA_COLUMNS) + ["sync_id", "updated_at", "deleted"]
        placeholders = ",".join("?" * len(cols))
        update_set = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "sync_id")
        sql = (f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT(sync_id) DO UPDATE SET {update_set}")
        applied = 0
        skipped = 0
        for raw in cloud_rows:
            row = dict(raw)
            sid = str(row.get("id") or "").strip()
            if not sid:
                skipped += 1
                continue
            row["sync_id"] = sid
            row["deleted"] = 1 if row.get("deleted") else 0
            row["is_active"] = int(bool(row.get("is_active")))
            row["points"] = str(row.get("points") or "0")
            if not str(row.get("updated_at") or ""):
                row["updated_at"] = _utc_now_iso()
            try:
                with self._lock:
                    self._exec(sql, tuple(row.get(c) for c in cols))
                applied += 1
            except Exception as exc:
                retry_row = dict(row)
                retry_row["number"] = f"{row.get('number') or ''} ~{sid[:4]}"
                try:
                    with self._lock:
                        self._exec(sql, tuple(retry_row.get(c) for c in cols))
                    applied += 1
                    logger.warning("Sync apply: number conflict for {} resolved with suffix", sid)
                except Exception:
                    logger.warning("Sync apply skipped for {}: {}", sid, exc)
                    skipped += 1
        return applied, skipped

    def get_category_counts(self) -> Dict[str, int]:
        rows = list(self._exec(
            "SELECT category, COUNT(*) FROM accounts WHERE deleted=0 GROUP BY category"))
        return {r[0]: r[1] for r in rows}

    def save_proxy_config(self, ip: str, port: str, username: str, password: str, config_json: str) -> int:
        with self._lock:  # keep DELETE + INSERT atomic
            self._exec("DELETE FROM proxy_configs")
            self._exec(
                "INSERT INTO proxy_configs (ip, port, username, password, config_json) VALUES (?,?,?,?,?)",
                (ip, port, username, password, config_json))
            return self._conn.last_insert_rowid()

    def get_last_proxy_config(self) -> Optional[Dict[str, Any]]:
        rows = list(self._exec("SELECT * FROM proxy_configs ORDER BY id DESC LIMIT 1"))
        if not rows:
            return None
        cols = ["id", "ip", "port", "username", "password", "config_json"]
        return dict(zip(cols, rows[0]))

    def get_survey_details(self, name: str) -> Optional[str]:
        rows = list(self._exec("SELECT details FROM servey_info_table WHERE name=?", (name,)))
        return rows[0][0] if rows else None

    def get_all_categories(self) -> List[str]:
        rows = list(self._exec("SELECT name FROM categories ORDER BY name"))
        return [r[0] for r in rows]

    def add_category(self, name: str) -> bool:
        try:
            self._exec("INSERT INTO categories (name) VALUES (?)", (name,))
            return True
        except Exception:
            return False

    def delete_category(self, name: str, reassign_to: str = DEFAULT_CATEGORY) -> bool:
        try:
            with self._lock:  # keep the three statements atomic
                self._exec("INSERT OR IGNORE INTO categories (name) VALUES (?)", (reassign_to,))
                self._exec("UPDATE accounts SET category=? WHERE category=?", (reassign_to, name))
                self._exec("DELETE FROM categories WHERE name=?", (name,))
            return True
        except Exception as exc:
            logger.error("Failed to delete category '{}': {}", name, exc)
            return False

    def export_accounts_as_sql(self) -> str:
        accounts = self.get_accounts()
        if not accounts:
            return ""
        columns = ["number", "name", "dob", "email", "password", "notes", "referrals",
                   "street", "city_town", "state_province_region", "zip_postal_code",
                   "points", "is_active", "points_last_modified", "category"]
        lines: List[str] = []
        for acc in accounts:
            values = []
            for col in columns:
                val = acc.get(col)
                if val is None:
                    values.append("NULL")
                elif isinstance(val, int):
                    values.append(str(val))
                else:
                    values.append(f"'{str(val).replace(chr(39), chr(39)+chr(39))}'")
            lines.append(f"INSERT INTO accounts ({', '.join(columns)}) VALUES ({', '.join(values)});")
        return "\n".join(lines)

    def record_point_change(self, account_id: int, account_name: str, old_points: str, new_points: str) -> None:
        def _to_float(val):
            if val is None or str(val).lower() in ("none", "null", ""):
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0
        old_val = _to_float(old_points)
        new_val = _to_float(new_points)
        change_str = f"{new_val - old_val:+.2f}"
        self._exec(
            """INSERT INTO point_history (account_id, account_name, old_points, new_points, change_amount, changed_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (account_id, account_name, old_points or "0", new_points or "0",
             change_str, datetime.now(timezone.utc).isoformat()),
        )

    def get_point_history(self, account_id: Optional[int] = None,
                          limit: int = 200) -> List[Dict[str, Any]]:
        cols = "id, account_id, account_name, old_points, new_points, change_amount, changed_at"
        if account_id is not None:
            rows = list(self._exec(
                f"SELECT {cols} FROM point_history WHERE account_id=? ORDER BY changed_at DESC LIMIT ?",
                (account_id, limit)))
        else:
            rows = list(self._exec(
                f"SELECT {cols} FROM point_history ORDER BY changed_at DESC LIMIT ?",
                (limit,)))
        if not rows:
            return []
        names = ["id", "account_id", "account_name", "old_points", "new_points", "change_amount", "changed_at"]
        return [dict(zip(names, row)) for row in rows]

    def close(self) -> None:
        try:
            with self._lock:  # wait for any in-flight worker statements
                self._conn.close()
        except Exception:
            pass
        logger.info("DatabaseManager closed.")


# ============================================================================
# TABLE MODEL
# ============================================================================
class FieldLineEdit(QLineEdit):
    """Read-only line edit; only fields created with allow_inline_edit=True become
    editable on double-click (in the account tab that is the points field only).

    Every other field stays locked: it can only be changed through the
    "edit all account details" dialog. Enter saves, Escape cancels.
    """

    editRequested = pyqtSignal(object)  # (self) — emitted on double-click when editing starts
    editBlocked = pyqtSignal(object)    # (self) — emitted on double-click of a LOCKED field

    def __init__(self, on_save, on_cancel, parent: Optional[QWidget] = None,
                 allow_inline_edit: bool = False) -> None:
        super().__init__(parent)
        self._on_save = on_save          # callable(widget) — Enter pressed
        self._on_cancel = on_cancel      # callable(widget) — Escape pressed
        self._allow_inline_edit = allow_inline_edit  # False = locked against double-click editing
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignRight)
        self.setMinimumHeight(35)
        # Pointing-hand cursor signals "interactive" only for the editable field;
        # locked fields keep the normal text cursor (text can still be selected/copied).
        self.setCursor(self._idle_cursor())

    def _idle_cursor(self):
        """Cursor shown while the field is read-only."""
        return Qt.PointingHandCursor if self._allow_inline_edit else Qt.IBeamCursor

    def _repolish(self) -> None:
        """Re-evaluate QSS attribute selectors ([readOnly="true"]) after a toggle."""
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def mouseDoubleClickEvent(self, event) -> None:
        # Locked field: never enter edit mode. Keep Qt's default read-only behaviour
        # (word selection for copying) and tell the window so it can notify the user.
        if not self._allow_inline_edit:
            self.editBlocked.emit(self)
            super().mouseDoubleClickEvent(event)
            return
        if self.isReadOnly():
            self._original_value = self.text()
            self.setReadOnly(False)
            self.setCursor(Qt.IBeamCursor)
            self.setFocus()
            self.selectAll()
            self._repolish()
            self.editRequested.emit(self)

    def keyPressEvent(self, event) -> None:
        if not self.isReadOnly() and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._on_save(self)
            return
        if not self.isReadOnly() and event.key() == Qt.Key_Escape:
            self._on_cancel(self)
            return
        super().keyPressEvent(event)

    def restore_readonly(self) -> None:
        self.setReadOnly(True)
        self.setCursor(self._idle_cursor())
        self._repolish()


_ALIGN_CENTER: Final[int] = Qt.AlignCenter
_ACTIVE_BG = QColor("#c8e6c9")
_INACTIVE_BG = QColor("#ffcdd2")
_ACTIVE_FG = QColor("#1b5e20")
_INACTIVE_FG = QColor("#b71c1c")


class AccountsTableModel(QAbstractTableModel):
    HEADERS: Final[List[str]] = ["#", "الاسم", "آخر تعديل", "النقاط", "الفئة"]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []
        self._timestamp_cache: Dict[str, str] = {}
        self._display_cache: List[Tuple[str, str, str, str, str]] = []

    def rowCount(self, parent=None) -> int:
        return len(self._data)

    def columnCount(self, parent=None) -> int:
        return 5

    def _rebuild_display_cache(self) -> None:
        cache: List[Tuple[str, str, str, str, str]] = []
        ts_cache = self._timestamp_cache
        for i, account in enumerate(self._data):
            ts = account.get("points_last_modified")
            if ts and ts not in ts_cache:
                ts_cache[ts] = format_time_ago(ts)
            pts = account.get("points", "0")
            if pts is None or str(pts).lower() in ("none", "null", ""):
                pts = "0"
            cache.append((
                str(i + 1),
                str(account.get("name", "")),
                ts_cache.get(ts, "لم يتم تعديله") if ts else "لم يتم تعديله",
                str(pts),
                str(account.get("category") or DEFAULT_CATEGORY),
            ))
        self._display_cache = cache

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        n = len(self._data)
        if row >= n:
            return None
        if role == Qt.DisplayRole:
            try:
                return self._display_cache[row][col]
            except IndexError:
                return None
        if role == Qt.BackgroundRole:
            return _ACTIVE_BG if self._data[row].get("is_active", 1) == 1 else _INACTIVE_BG
        if role == Qt.ForegroundRole:
            return _ACTIVE_FG if self._data[row].get("is_active", 1) == 1 else _INACTIVE_FG
        if role == Qt.UserRole:
            return self._data[row].get("id")
        if role == Qt.TextAlignmentRole:
            return _ALIGN_CENTER
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        return None

    def setData(self, data: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._data = data
        self._timestamp_cache.clear()
        self._rebuild_display_cache()
        self.endResetModel()

    def account_id_at(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._data):
            return self._data[row].get("id")
        return None

    def account_name_at(self, row: int) -> str:
        if 0 <= row < len(self._data):
            return str(self._data[row].get("name", ""))
        return ""

    def refresh_time_column(self) -> None:
        """Recompute the relative "last modified" texts (called periodically) so that
        "الآن" / "قبل N دقيقة" never go stale while the app stays open."""
        if not self._data:
            return
        self._timestamp_cache.clear()
        self._rebuild_display_cache()
        self.dataChanged.emit(self.index(0, 2), self.index(len(self._data) - 1, 2),
                              [Qt.DisplayRole])

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        self.layoutAboutToBeChanged.emit()
        def _safe_float(val):
            try:
                return float(val) if val is not None and str(val).lower() not in ("none", "", "null") else 0.0
            except (ValueError, TypeError):
                return 0.0
        key_funcs = {
            0: lambda x: str(x.get("name", "")).casefold(),
            1: lambda x: str(x.get("name", "")).casefold(),
            2: lambda x: x.get("points_last_modified", "1970-01-01T00:00:00") or "1970-01-01T00:00:00",
            3: lambda x: _safe_float(x.get("points", "0")),
            4: lambda x: str(x.get("category") or "").casefold(),
        }
        if column in key_funcs:
            self._data.sort(key=key_funcs[column], reverse=(order == Qt.DescendingOrder))
        self._rebuild_display_cache()
        self.layoutChanged.emit()


# ============================================================================
# DIALOGS
# ============================================================================
class QRCodeDialog(QDialog):
    def __init__(self, email: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("qrDialog")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        email = (email or "").strip() or " "
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=1)
        qr.add_data(f"Email: {email}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qimg = QImage(img.tobytes("raw", "RGB"), img.width, img.height, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg.copy())
        layout = QVBoxLayout(self)
        lbl = QLabel()
        lbl.setPixmap(pixmap)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        self.resize(pixmap.width() + 20, pixmap.height() + 20)
        QTimer.singleShot(5000, self.close)
        self._center()

    def _center(self) -> None:
        geo = self.frameGeometry()
        geo.moveCenter(QDesktopWidget().availableGeometry().center())
        self.move(geo.topLeft())

    def mousePressEvent(self, event) -> None:
        if not self.rect().contains(event.pos()):
            self.close()
        else:
            super().mousePressEvent(event)


class LoginDialog(QDialog):
    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.user_role: Optional[str] = None
        self.setWindowTitle("تسجيل الدخول")
        self.setFixedSize(400, 340)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(28, 24, 28, 24)

        # Brand banner
        banner = QLabel("🔐 مدير الحسابات")
        banner.setObjectName("loginBanner")
        banner.setAlignment(Qt.AlignCenter)
        layout.addWidget(banner)

        subtitle = QLabel("سجّل الدخول للمتابعة")
        subtitle.setObjectName("loginSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        lbl = QLabel("كلمة المرور:")
        lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        layout.addWidget(lbl)
        pw_row = QHBoxLayout()
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("أدخل كلمة المرور")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setAlignment(Qt.AlignRight)
        self.password_input.setMinimumHeight(42)
        self.password_input.returnPressed.connect(self._check)
        self._pw_toggle = QToolButton()
        self._pw_toggle.setText("إظهار")
        self._pw_toggle.setCheckable(True)
        self._pw_toggle.setCursor(Qt.PointingHandCursor)
        self._pw_toggle.setFixedHeight(42)
        self._pw_toggle.toggled.connect(self._toggle_password)
        pw_row.addWidget(self.password_input, 1)
        pw_row.addWidget(self._pw_toggle)
        layout.addLayout(pw_row)
        layout.addSpacing(6)

        self._login_btn = QPushButton("تسجيل الدخول")
        self._login_btn.setObjectName("primaryButton")
        self._login_btn.setMinimumHeight(44)
        self._login_btn.setDefault(True)
        self._login_btn.clicked.connect(self._check)
        layout.addWidget(self._login_btn)
        # The password field owns the focus for the whole login session.
        QTimer.singleShot(0, self.password_input.setFocus)

    def _toggle_password(self, visible: bool) -> None:
        self.password_input.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self._pw_toggle.setText("إخفاء" if visible else "إظهار")

    def _check(self) -> None:
        pw = self.password_input.text()
        # PBKDF2 verification is CPU-heavy (~200ms per attempt) — run it off
        # the GUI thread so the dialog stays responsive.
        self._login_btn.setEnabled(False)
        self.password_input.setEnabled(False)

        def _resolve(password: str) -> Optional[str]:
            # Admin login is permanently disabled — user password only.
            if self.db.check_password("user", password):
                return "user"
            return None

        def _done(role) -> None:
            self._login_btn.setEnabled(True)
            self.password_input.setEnabled(True)
            if role:
                self.user_role = role
                logger.info("User login successful.")
                self.accept()
            else:
                QMessageBox.warning(self, "فشل تسجيل الدخول", "كلمة مرور غير صحيحة.")
                logger.warning("Login failed.")
                # Select the whole mistyped password so the user can type the
                # replacement over it in one keystroke, and keep the focus on
                # the field (it is re-enabled after the async check).
                self.password_input.selectAll()
                self.password_input.setFocus()

        def _fail(err: str) -> None:
            self._login_btn.setEnabled(True)
            self.password_input.setEnabled(True)
            QMessageBox.critical(self, "خطأ", f"تعذر التحقق من كلمة المرور:\n{err}")

        run_task(_resolve, _done, _fail, pw, busy_button=self._login_btn)


class AddAccountDialog(QDialog):
    """Add/Edit account dialog matching original v4.2 field layout."""

    def __init__(self, db: DatabaseManager, account_data: Optional[Dict[str, Any]] = None, 
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.is_edit = account_data is not None
        self.account_data = account_data or {}
        self.setWindowTitle("تعديل الحساب" if self.is_edit else "إضافة حساب جديد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(1000, 700)

        self._build_ui()
        if self.is_edit:
            self._populate_fields()
        else:
            self._set_defaults()
        self._center()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # Title
        title_text = "✏️ تعديل الحساب" if self.is_edit else "➕ إضافة حساب جديد"
        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # Scroll area for form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(12)

        # === MAIN FORM GRID (matches original v4.2 EXACTLY) ===
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(15)

        self.fields: Dict[str, QLineEdit] = {}

        # EXACT field order from original v4.2:
        # number, name, dob, email, password, referrals, street, city_town, state_province_region, zip_postal_code, points
        fields_def = [
            ("الرقم:*", "number"),
            ("الاسم:*", "name"),
            ("تاريخ الميلاد", "dob"),
            ("البريد الإلكتروني", "email"),
            ("كلمة المرور", "password"),
            ("الإحالات", "referrals"),
            ("الشارع", "street"),
            ("المدينة/البلدة", "city_town"),
            ("المنطقة", "state_province_region"),
            ("الرمز البريدي", "zip_postal_code"),
            ("النقاط", "points"),
        ]

        row = col = 0
        for label_text, key in fields_def:
            lbl = QLabel(label_text)
            lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
            field = QLineEdit()
            field.setAlignment(Qt.AlignRight)
            field.setMinimumHeight(30)
            if key == "password":
                field.setEchoMode(QLineEdit.Password)
            if key == "email":
                field.setPlaceholderText("name@example.com")
            if key == "dob":
                field.setPlaceholderText("YYYY-MM-DD")
            self.fields[key] = field
            # RTL grid: column 0 is the RIGHT-most one, so the label goes in the first
            # column of the pair and the field next to it (label on the right of its field).
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(field, row, col * 2 + 1)
            col += 1
            if col >= 2:
                col = 0
                row += 1
        if col != 0:
            row += 1

        grid.setColumnStretch(1, 1)  # field columns absorb the free width
        grid.setColumnStretch(3, 1)
        scroll_layout.addLayout(grid)

        # Category row
        cat_layout = QHBoxLayout()
        cat_lbl = QLabel("الفئة:")
        cat_lbl.setAlignment(ALIGN_RIGHT_ABS)
        self.category_combo = QComboBox()
        self.category_combo.addItems(self.db.get_all_categories())
        cat_layout.addWidget(cat_lbl)
        cat_layout.addWidget(self.category_combo)
        cat_layout.addStretch()
        scroll_layout.addLayout(cat_layout)

        # Notes
        notes_lbl = QLabel("ملاحظات:")
        notes_lbl.setAlignment(ALIGN_RIGHT_ABS)
        scroll_layout.addWidget(notes_lbl)
        self.notes_edit = QTextEdit()
        self.notes_edit.setLayoutDirection(Qt.RightToLeft)
        self.notes_edit.setMinimumHeight(50)
        self.notes_edit.setMaximumHeight(70)
        scroll_layout.addWidget(self.notes_edit)

        pw_toggle_row = QHBoxLayout()
        self._form_pw_toggle = QCheckBox("إظهار كلمة المرور")
        self._form_pw_toggle.toggled.connect(
            lambda vis: self.fields["password"].setEchoMode(
                QLineEdit.Normal if vis else QLineEdit.Password))
        pw_toggle_row.addWidget(self._form_pw_toggle)
        pw_toggle_row.addStretch()
        scroll_layout.addLayout(pw_toggle_row)

        # Active checkbox
        self.active_checkbox = QCheckBox("نشط")
        self.active_checkbox.setChecked(True)
        scroll_layout.addWidget(self.active_checkbox)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("حفظ الحساب")
        save_btn.setObjectName("primaryButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._validate_and_save)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        main_layout.addLayout(btn_layout)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

    def _set_defaults(self) -> None:
        cats = self.db.get_all_categories()
        self.fields["number"].setText(f"ACC-{self.db.get_next_account_id()}")
        if cats:
            idx = self.category_combo.findText(cats[0])
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)

    def _populate_fields(self) -> None:
        for key, widget in self.fields.items():
            widget.setText(str(self.account_data.get(key, "")))
        self.notes_edit.setPlainText(self.account_data.get("notes", ""))
        self.active_checkbox.setChecked(self.account_data.get("is_active", 1) == 1)
        cat = self.account_data.get("category", "")
        if cat:
            idx = self.category_combo.findText(cat)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)

    def _validate_and_save(self) -> None:
        self.status_label.setText("")
        number = self.fields["number"].text().strip()
        name = self.fields["name"].text().strip()
        if not number:
            self.status_label.setText("⚠️ الرقم مطلوب!")
            self.fields["number"].setFocus()
            return
        if not name:
            self.status_label.setText("⚠️ الاسم مطلوب!")
            self.fields["name"].setFocus()
            return
        dob = self.fields["dob"].text().strip()
        if dob:
            try:
                datetime.strptime(dob, "%Y-%m-%d")
            except ValueError:
                self.status_label.setText("⚠️ تاريخ الميلاد يجب أن يكون بالصيغة: YYYY-MM-DD")
                self.fields["dob"].setFocus()
                return
        email = self.fields["email"].text().strip()
        if email and "@" not in email:
            self.status_label.setText("⚠️ البريد الإلكتروني غير صالح!")
            self.fields["email"].setFocus()
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for key, widget in self.fields.items():
            data[key] = widget.text().strip()
        data["notes"] = self.notes_edit.toPlainText().strip()
        data["is_active"] = 1 if self.active_checkbox.isChecked() else 0
        data["category"] = self.category_combo.currentText()
        data["points_last_modified"] = self.account_data.get("points_last_modified")
        if self.is_edit and data.get("points") != self.account_data.get("points"):
            data["points_last_modified"] = datetime.now(timezone.utc).isoformat()
        elif not self.is_edit:
            data["points_last_modified"] = None
        return data

    def _center(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        geo = self.frameGeometry()
        geo.moveCenter(screen.center())
        self.move(geo.topLeft())


class ChangePasswordDialog(QDialog):
    """User password change dialog (admin account is permanently disabled)."""
    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("تغيير كلمة المرور")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(380, 240)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        for lbl_text, attr in [
            ("كلمة المرور الحالية:", "current_pass"),
            ("كلمة المرور الجديدة:", "new_user"),
            ("تأكيد كلمة المرور الجديدة:", "confirm_pass"),
        ]:
            lbl = QLabel(lbl_text)
            lbl.setAlignment(ALIGN_RIGHT_ABS)
            layout.addWidget(lbl)
            field = QLineEdit()
            field.setEchoMode(QLineEdit.Password)
            field.setAlignment(Qt.AlignRight)
            field.setMinimumHeight(34)
            setattr(self, attr, field)
            layout.addWidget(field)
        layout.addSpacing(4)
        btn_layout = QHBoxLayout()
        self._save_btn = QPushButton("💾 حفظ")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("إغلاق")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self._save_btn)
        layout.addLayout(btn_layout)

    def _save(self) -> None:
        current = self.current_pass.text()
        new_user = self.new_user.text().strip()
        confirm = self.confirm_pass.text().strip()
        if new_user != confirm:
            QMessageBox.warning(self, "خطأ", "كلمتا المرور الجديدتان غير متطابقتين.")
            return
        if not new_user:
            QMessageBox.warning(self, "خطأ", "لا يمكن أن تكون كلمة المرور الجديدة فارغة.")
            return

        # PBKDF2 verification + hashing are CPU-heavy — keep them off the GUI thread.
        def _apply(cur: str, nu: str) -> Tuple[bool, str]:
            if not self.db.check_password("user", cur):
                return False, "كلمة المرور الحالية غير صحيحة."
            self.db.set_password("user", nu)
            return True, "تم تغيير كلمة المرور بنجاح."

        def _done(result) -> None:
            ok, msg = result
            if ok:
                QMessageBox.information(self, "نجاح", msg)
                self.accept()
            else:
                QMessageBox.warning(self, "خطأ", msg)

        def _fail(err: str) -> None:
            QMessageBox.critical(self, "خطأ", f"تعذر حفظ كلمة المرور:\n{err}")

        run_task(_apply, _done, _fail, current, new_user,
                 busy_button=self._save_btn)


class AboutDialog(QDialog):
    """About dialog with a prominent installed-version badge.

    The version is the single source of truth for the self-update system,
    so it is shown as a highlighted badge plus the auto-update-check
    preference and a one-click "التحقق من التحديثات" button that hands
    over to the main window's update checker.
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 auto_update_enabled: Optional[bool] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("حول البرنامج")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(430, 280)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel('<h2 style="margin:0;">مدير الحسابات</h2>')
        title.setTextFormat(Qt.RichText)
        title.setAlignment(ALIGN_RIGHT_ABS)
        layout.addWidget(title)

        # Prominent version badge — mirrors the APP_VERSION the updater
        # compares against, so users can verify the installed build at a
        # glance when an update is announced.
        version_badge = QLabel(f"الإصدار المثبت: v{APP_VERSION}")
        version_badge.setObjectName("versionBadge")
        version_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_badge)

        auto_line = ""
        if auto_update_enabled is not None:
            state = "مفعّل" if auto_update_enabled else "معطّل"
            auto_line = (f'<p><b>التحقق التلقائي من التحديثات عند بدء التشغيل:</b> '
                         f'{state}</p>')
        info = QLabel(
            f'<p><b>المؤلف:</b> {APP_AUTHOR}</p>'
            '<p>تطبيق لإدارة الحسابات والبروكسي والإحصائيات مع بحث فوري وتصدير ونسخ احتياطي.</p>'
            + auto_line
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setAlignment(ALIGN_RIGHT_ABS)
        layout.addWidget(info)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        check_btn = QPushButton("🔄 التحقق من التحديثات")
        check_btn.setObjectName("primaryButton")
        check_btn.setCursor(Qt.PointingHandCursor)
        check_btn.setToolTip("البحث الآن عن إصدار أحدث")
        check_btn.clicked.connect(self._trigger_update_check)
        close_btn = QPushButton("إغلاق")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(check_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _trigger_update_check(self) -> None:
        """Close this dialog and run the main window's update checker so its
        progress/result is visible on the status bar."""
        check = getattr(self.parent(), "_check_for_updates", None)
        self.accept()
        if callable(check):
            check(manual=True)


class UpdateAvailableDialog(QDialog):
    """RTL dialog shown when the update checker finds a newer version.

    Displays the remote version, the current version and the release notes
    from the manifest, then lets the user choose التثبيت الآن / لاحقاً.
    When the manifest flags the release as mandatory the "لاحقاً" button is
    hidden so the only path forward is installing (or quitting from the menu).
    """

    def __init__(self, manifest: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("تحديث جديد متوفر")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(460)
        remote_version = str(manifest.get("version", "?")).strip() or "?"
        notes = str(manifest.get("notes", "") or "").strip() or "بدون ملاحظات إصدار."
        mandatory = bool(manifest.get("mandatory", False))

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(
            f'<h2 style="margin:0;">🔄 يتوفر تحديث جديد</h2>'
            f'<p style="margin:6px 0 0 0;">الإصدار الجديد: <b>v{remote_version}</b>'
            f' &nbsp;&mdash;&nbsp; الإصدار الحالي: <b>v{APP_VERSION}</b></p>'
        )
        header.setTextFormat(Qt.RichText)
        header.setWordWrap(True)
        header.setAlignment(ALIGN_RIGHT_ABS)
        layout.addWidget(header)

        notes_box = QLabel(notes)
        notes_box.setWordWrap(True)
        notes_box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        notes_box.setObjectName("updateNotes")
        notes_box.setMinimumHeight(64)
        layout.addWidget(notes_box)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later_btn = QPushButton("لاحقاً")
        later_btn.setCursor(Qt.PointingHandCursor)
        later_btn.clicked.connect(self.reject)
        install_btn = QPushButton("⬇️ التثبيت الآن")
        install_btn.setObjectName("primaryButton")
        install_btn.setCursor(Qt.PointingHandCursor)
        install_btn.setDefault(True)
        install_btn.clicked.connect(self.accept)
        buttons.addWidget(later_btn)
        buttons.addWidget(install_btn)
        layout.addLayout(buttons)

        if mandatory:
            later_btn.setVisible(False)
            self.setWindowTitle("تحديث إجباري مطلوب")


class CloudSyncDialog(QDialog):
    """نافذة المزامنة السحابية (Supabase) — v6.6.

    تعرض حالة الاتصال (مسجل باسم من / غير مسجل)، وآخر مزامنة ناجحة، وتتيح
    تسجيل الدخول، المزامنة الفورية، وتسجيل الخروج. كل العمليات الشبكية
    تعمل في خيط الخلفية عبر دوال النافذة الرئيسية (run_task) فلا يتجمد
    الواجهة أبدًا، ورسائل الأخطاء عربية قابلة للتنفيذ.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("المزامنة السحابية — Supabase")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.header_label = QLabel()
        self.header_label.setTextFormat(Qt.RichText)
        self.header_label.setWordWrap(True)
        self.header_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.header_label)

        # شرح التفعيل (يظهر فقط عندما تكون ثوابت SUPABASE فارغة)
        self.setup_label = QLabel(
            "المزامنة غير مُفعّلة في هذه النسخة بعد. خطوات التفعيل (للمشرف، مرة واحدة):\n\n"
            "1) أنشئ مشروعًا مجانيًا على supabase.com\n"
            "2) نفّذ ملف supabase_setup.sql المرفق من محرر SQL داخل لوحة المشروع\n"
            "3) أنشئ مستخدمًا لكل شخص من Authentication ← Users ← Add user "
            "(مع تفعيل Auto Confirm)\n"
            "4) انسخ Project URL و anon key إلى الثابتين SUPABASE_URL و "
            "SUPABASE_ANON_KEY أعلى ملف البرنامج ثم أعد توزيعه كتحديث\n\n"
            "بعد التفعيل يكفي أن يسجّل كل مستخدم بريده وكلمة مروره هنا، وتعمل "
            "المزامنة تلقائيًا عند كل إقلاع. بيانات الفريق مشتركة بين جميع "
            "الحسابات المسجّلة في المشروع (الدمج يحسم التعارضات بأحدث تعديل)، "
            "ومن بلا حساب سحابي لا يرى شيئًا بفضل RLS.")
        self.setup_label.setWordWrap(True)
        self.setup_label.setVisible(False)
        layout.addWidget(self.setup_label)

        # نموذج تسجيل الدخول
        self.login_box = QGroupBox("تسجيل الدخول")
        self.login_box.setLayoutDirection(Qt.RightToLeft)
        form = QGridLayout(self.login_box)
        # ملاحظة: الاتجاه يُورَّث من login_box (widget) — QGridLayout نفسه
        # لا يملك setLayoutDirection ونداؤها يرفع AttributeError.
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("البريد الإلكتروني للحساب السحابي")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("كلمة المرور")
        self.password_input.setEchoMode(QLineEdit.Password)
        form.addWidget(QLabel("البريد:"), 0, 0)
        form.addWidget(self.email_input, 0, 1)
        form.addWidget(QLabel("كلمة المرور:"), 1, 0)
        form.addWidget(self.password_input, 1, 1)
        layout.addWidget(self.login_box)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.login_button = QPushButton("🔐 تسجيل الدخول والمزامنة")
        self.login_button.setObjectName("primaryButton")
        self.login_button.clicked.connect(self._on_login)
        self.sync_button = QPushButton("🔄 مزامنة الآن")
        self.sync_button.setObjectName("primaryButton")
        self.sync_button.clicked.connect(self._on_sync_now)
        self.logout_button = QPushButton("🚪 تسجيل الخروج")
        self.logout_button.clicked.connect(self._on_logout)
        self.close_button = QPushButton("إغلاق")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.sync_button)
        buttons.addWidget(self.logout_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.refresh_state()

    # ---------------------------- الحالة ----------------------------
    def _parent_window(self):
        return self.parent() if self.parent() is not None else None

    def _saved_email(self) -> str:
        parent = self._parent_window()
        db = getattr(parent, "db_manager", None) if parent is not None else None
        if db is None:
            return ""
        return str(db.get_setting(SYNC_USER_EMAIL_KEY, "") or "")

    def refresh_state(self) -> None:
        """أعد بناء العرض وفق الوضع الحالي (غير مُعدّة / غير مسجل / مسجل)."""
        parent = self._parent_window()
        db = getattr(parent, "db_manager", None) if parent is not None else None
        configured = _sync_configured()
        email = self._saved_email()
        self.setup_label.setVisible(not configured)
        self.login_box.setVisible(configured and not email)
        self.login_button.setVisible(configured and not email)
        self.sync_button.setVisible(configured and bool(email))
        self.logout_button.setVisible(configured and bool(email))
        if not configured:
            self.header_label.setText(
                f"<h2 style='margin:0;'>☁️ المزامنة السحابية</h2>"
                f"<p style='margin:6px 0 0 0;'>الحالة: <b>غير مُفعّلة في هذه النسخة</b></p>")
            self.status_label.setText("")
            return
        if email:
            last = ""
            if db is not None:
                last = str(db.get_setting(SYNC_LAST_TIME_KEY, "") or "")
            last_display = _format_sync_time(last) if last else "لم تتم بعد"
            self.header_label.setText(
                f"<h2 style='margin:0;'>☁️ المزامنة السحابية</h2>"
                f"<p style='margin:6px 0 0 0;'>متصل باسم: <b>{email}</b><br>"
                f"آخر مزامنة ناجحة: <b>{last_display}</b></p>")
        else:
            self.header_label.setText(
                f"<h2 style='margin:0;'>☁️ المزامنة السحابية</h2>"
                f"<p style='margin:6px 0 0 0;'>الحالة: <b>غير مسجل</b> — "
                f"أدخل بيانات حسابك السحابي لتفعيل المزامنة على هذا الجهاز.</p>")
        if not self.status_label.text():
            self.status_label.setText(
                "البيانات المحلية تبقى المصدر الدائم؛ يعمل البرنامج بشكل كامل "
                "بدون إنترنت وتُرفع التغييرات تلقائيًا عند توفر الاتصال.")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.login_button.setEnabled(not busy)
        self.sync_button.setEnabled(not busy)
        self.logout_button.setEnabled(not busy)
        if message:
            self.set_status(message)

    # ---------------------------- الأزرار ----------------------------
    def _on_login(self) -> None:
        parent = self._parent_window()
        handler = getattr(parent, "_do_cloud_login", None)
        if callable(handler):
            handler(self, self.email_input.text(), self.password_input.text())

    def _on_sync_now(self) -> None:
        parent = self._parent_window()
        handler = getattr(parent, "_run_cloud_sync", None)
        if callable(handler):
            handler(dialog=self, manual=True)

    def _on_logout(self) -> None:
        parent = self._parent_window()
        handler = getattr(parent, "_cloud_logout", None)
        if callable(handler):
            handler(self)


class PreferencesDialog(QDialog):
    def __init__(self, font_manager: FontManager, density: int = UI_DENSITY_DEFAULT,
                 alert_sound: str = DEFAULT_ALERT_SOUND,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.font_manager = font_manager
        self.setWindowTitle("تفضيلات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        size_layout = QHBoxLayout()
        size_lbl = QLabel("حجم الخط:")
        size_lbl.setAlignment(ALIGN_RIGHT_ABS)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(FontManager.MIN_SIZE, FontManager.MAX_SIZE)
        self.font_size_spin.setAlignment(Qt.AlignRight)
        self.font_size_spin.setValue(self.font_manager.size)
        size_layout.addWidget(size_lbl)
        size_layout.addWidget(self.font_size_spin)
        layout.addLayout(size_layout)
        self.bold_checkbox = QCheckBox("خط عريض (Bold)")
        self.bold_checkbox.setChecked(self.font_manager.bold)
        layout.addWidget(self.bold_checkbox)
        dens_layout = QHBoxLayout()
        dens_lbl = QLabel("حجم شريط IP والعداد:")
        dens_lbl.setAlignment(ALIGN_RIGHT_ABS)
        self.density_combo = QComboBox()
        for level in range(UI_DENSITY_MIN, UI_DENSITY_MAX + 1):
            self.density_combo.addItem(UI_DENSITY_LABELS[level], level)
        idx = max(0, min(UI_DENSITY_MAX, density) - 1)
        self.density_combo.setCurrentIndex(idx)
        dens_layout.addWidget(dens_lbl)
        dens_layout.addWidget(self.density_combo)
        layout.addLayout(dens_layout)
        sound_layout = QHBoxLayout()
        sound_lbl = QLabel("صوت اختلاف IP:")
        sound_lbl.setAlignment(ALIGN_RIGHT_ABS)
        self.sound_combo = QComboBox()
        self.sound_combo.setMinimumWidth(220)
        selected = alert_sound or DEFAULT_ALERT_SOUND
        matched = False
        for sid, label in available_alert_sounds():
            self.sound_combo.addItem(label, sid)
            if sid == selected:
                self.sound_combo.setCurrentIndex(self.sound_combo.count() - 1)
                matched = True
        if not matched and selected:
            self.sound_combo.addItem(selected, selected)
            self.sound_combo.setCurrentIndex(self.sound_combo.count() - 1)
        preview_btn = QPushButton("تجربة")
        preview_btn.setCursor(Qt.PointingHandCursor)
        preview_btn.clicked.connect(self._preview_sound)
        sound_layout.addWidget(sound_lbl)
        sound_layout.addWidget(self.sound_combo, 1)
        sound_layout.addWidget(preview_btn)
        layout.addLayout(sound_layout)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("إلغاء")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("تطبيق")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(apply_btn)
        layout.addLayout(btn_layout)

    def _preview_sound(self) -> None:
        sid = self.sound_combo.currentData()
        play_alert_sound(sid if isinstance(sid, str) else DEFAULT_ALERT_SOUND)

    def get_preferences(self) -> Tuple[int, bool, int, str]:
        sid = self.sound_combo.currentData()
        return (
            self.font_size_spin.value(),
            self.bold_checkbox.isChecked(),
            int(self.density_combo.currentData()),
            sid if isinstance(sid, str) else DEFAULT_ALERT_SOUND,
        )


# ============================================================================
# MAIN WINDOW
# ============================================================================
# Tooltip / status text shown for the locked (non-points) fields of the account tab.
LOCKED_FIELD_TOOLTIP: Final[str] = "🔒 الحقل مقفل — للتعديل اضغط زر «تعديل جميع تفاصيل الحساب»"

DEFAULT_ADDONS: Final[List[Tuple[str, str]]] = [
    ("FoxyProxy Standard:", "https://addons.mozilla.org/en-US/firefox/addon/foxyproxy-standard/"),
    ("Translate Web Pages:", "https://addons.mozilla.org/en-US/firefox/addon/traduzir-paginas-web/"),
    ("Disable WebRTC:", "https://addons.mozilla.org/en-US/firefox/addon/happy-bonobo-disable-webrtc/"),
    ("WhatIsMyIPAddress:", "https://whatismyipaddress.com/"),
    ("uBlock Origin:", "https://addons.mozilla.org/en-US/firefox/addon/ublock-origin/"),
    ("Privacy Badger:", "https://addons.mozilla.org/en-US/firefox/addon/privacy-badger17/"),
    ("HTTPS Everywhere:", "https://addons.mozilla.org/en-US/firefox/addon/https-everywhere/"),
    ("Cookie AutoDelete:", "https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/"),
]


class MainWindow(QMainWindow):
    def __init__(self, user_role: str, db_manager: Optional[DatabaseManager] = None, 
                 parent: Optional[QWidget] = None,
                 font_manager: Optional[FontManager] = None) -> None:
        super().__init__(parent)
        self.db_manager = db_manager if db_manager is not None else DatabaseManager()
        # Centralized font management: one FontManager owns family/size/bold
        # for the whole app. main() shares its DB-backed instance; standalone
        # construction (tests) creates one that loads preferences itself.
        self.font_manager = font_manager if font_manager is not None else FontManager(self.db_manager)
        # NOTE: Admin account is permanently disabled — role always "user".
        self.user_role = "user"
        self.current_account_id: Optional[int] = None
        self._active_filter: Optional[int] = 1
        self._proxy_retry_count: int = 0
        self._last_proxy_for_check: Optional[Tuple[str, str, str, str]] = None
        self._thread: Optional[QThread] = None       # proxy-check helper thread
        self._geo_thread: Optional[QThread] = None   # geo-lookup helper thread
        self._countdown_running: bool = False
        self._auto_repeat: bool = False
        self._ip_mismatch_alerted: bool = False
        self.countdown_remaining: int = DEFAULT_COUNTDOWN_SEC
        self._firefox_running_cached: bool = False
        self.proxy_unsaved_changes: bool = False
        self.proxy_original_values: Dict[str, str] = {}
        self._update_check_in_flight: bool = False   # update-checker guard
        self._auto_update_pref: bool = True          # refined right below
        self._sync_in_flight: bool = False           # cloud-sync reentry guard
        self._sync_dialog_ref = None                 # live CloudSyncDialog (if open)
        self._auto_sync_pref: bool = True            # refined right below

        # Async-operation state (see run_task / Worker helpers above)
        self._firefox_check_in_flight: bool = False
        self._firefox_launch_in_progress: bool = False
        self._firefox_exec_cache: Optional[str] = None
        self._filter_seq: int = 0
        self._closing: bool = False
        self._search_text: str = ""
        try:
            saved_density = int(self.db_manager.get_setting("pref_ui_density", str(UI_DENSITY_DEFAULT)) or UI_DENSITY_DEFAULT)
        except (TypeError, ValueError):
            saved_density = UI_DENSITY_DEFAULT
        self._ui_density: int = max(UI_DENSITY_MIN, min(UI_DENSITY_MAX, saved_density))
        self._alert_sound: str = self.db_manager.get_setting("pref_alert_sound", DEFAULT_ALERT_SOUND) or DEFAULT_ALERT_SOUND

        self.setWindowTitle(f"{APP_TITLE}  v{APP_VERSION}")
        self.setMinimumSize(960, 640)
        self.setLayoutDirection(Qt.RightToLeft)


        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray_icon.show()

        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._on_countdown_tick)

        self._firefox_timer = QTimer(self)
        self._firefox_timer.setInterval(FIREFOX_CHECK_INTERVAL_MS)
        self._firefox_timer.timeout.connect(self._check_firefox_status)
        self._firefox_timer.start()

        # Re-render the "last modified" column every minute so "الآن" / "قبل N دقيقة"
        # never stay stale while the window is open.
        self._time_refresh_timer = QTimer(self)
        self._time_refresh_timer.setInterval(60_000)
        self._time_refresh_timer.timeout.connect(lambda: self.accounts_model.refresh_time_column())
        self._time_refresh_timer.start()

        self._setup_ui()
        self._create_toolbar()
        self._create_main_menu()
        self._install_shortcuts()
        self._load_ip_before()
        self.font_manager.apply_to_app()
        self._apply_ui_density()

        # CRITICAL: Load accounts SYNCHRONOUSLY after UI is built
        self.filter_accounts()
        QTimer.singleShot(400, self._debug_db_status)
        QTimer.singleShot(600, self._refresh_dashboard_stats)

        # Update checker: one silent background manifest fetch shortly after
        # the window shows. Only ever disturbs the user when a NEWER version
        # exists; the manual path is ملف → التحقق من التحديثات.
        self._auto_update_pref = self._load_auto_update_pref()
        QTimer.singleShot(3500, lambda: self._check_for_updates(manual=False))

        # المزامنة السحابية: سحب/رفع صامت بعد نافذة فحص التحديث، فقط إن وُجدت
        # جلسة محفوظة وضُبطت ثوابت SUPABASE؛ وإلا فلا شيء يحدث إطلاقًا.
        self._auto_sync_pref = self._load_auto_sync_pref()
        QTimer.singleShot(6500, self._auto_cloud_sync)

        logger.info("MainWindow init complete (admin disabled, all tabs visible)")

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setLayoutDirection(Qt.RightToLeft)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(6, 6, 6, 6)

        self.tab_widget = QTabWidget()
        self.tab_widget.setLayoutDirection(Qt.RightToLeft)

        self.account_tab = QWidget()
        self.account_tab.setLayoutDirection(Qt.RightToLeft)
        self.proxy_tab = QWidget()
        self.proxy_tab.setLayoutDirection(Qt.RightToLeft)
        self.delete_tab = QWidget()
        self.delete_tab.setLayoutDirection(Qt.RightToLeft)
        self.addons_tab = QWidget()
        self.addons_tab.setLayoutDirection(Qt.RightToLeft)
        self.admin_tab = QWidget()
        self.admin_tab.setLayoutDirection(Qt.RightToLeft)
        self.stats_tab = QWidget()
        self.stats_tab.setLayoutDirection(Qt.RightToLeft)

        # Tab order (right -> left in the RTL window):
        # تفاصيل الحساب - إعدادات البروكسي - إحصائيات - الإضافات - حذف حساب - الأدوات
        # (tabs appear in the order their _setup_* method adds them to the QTabWidget)
        self._setup_account_details_tab()
        self._setup_proxy_config_tab()
        self._setup_statistics_tab()
        self._setup_addons_tab()
        self._setup_delete_account_tab()
        self._setup_tools_tab()

        # LEFT PANEL
        left_widget = QWidget()
        left_widget.setLayoutDirection(Qt.RightToLeft)
        self.left_layout = QVBoxLayout(left_widget)
        self.left_layout.setSpacing(6)
        self.left_layout.setContentsMargins(4, 4, 4, 4)

        self._build_ip_countdown_section(self.left_layout)
        self._build_dashboard_strip(self.left_layout)

        # Instant search — filters name / number / email / category.
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_lbl = QLabel("بحث:")
        search_lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ابحث بالاسم أو الرقم أو البريد أو الفئة...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAlignment(Qt.AlignRight)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._apply_search)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        search_row.addWidget(search_lbl)
        search_row.addWidget(self.search_input, 1)
        self.left_layout.addLayout(search_row)

        # Segmented account filter — replaces the three separate filter
        # buttons (one control, zero duplicates).
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)
        seg_note = QLabel("عرض:")
        filter_layout.addWidget(seg_note)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self.show_active_btn = QPushButton("النشطة")
        self.show_inactive_btn = QPushButton("غير النشطة")
        self.show_all_btn = QPushButton("الكل")
        for btn, mode in ((self.show_active_btn, 1), (self.show_inactive_btn, 0), (self.show_all_btn, None)):
            btn.setObjectName("segmentedButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._filter_group.addButton(btn, {1: 1, 0: 0, None: 2}[mode])
            btn.clicked.connect(lambda _=False, m=mode: self.filter_accounts(m))
            filter_layout.addWidget(btn)
        self.show_active_btn.setChecked(True)  # matches default filter (active)
        filter_layout.addStretch()
        self.left_layout.addLayout(filter_layout)

        self.left_layout.addWidget(self._create_category_checkboxes())

        # ACCOUNTS TABLE
        self.accounts_table = QTableView()
        # Object name lets the QSS give the selected account a clearly darker colour.
        self.accounts_table.setObjectName("accountsTable")
        self.accounts_table.setLayoutDirection(Qt.RightToLeft)
        self.accounts_table.setSelectionBehavior(QTableView.SelectRows)
        self.accounts_table.setAlternatingRowColors(True)
        self.accounts_table.setWordWrap(False)
        self.accounts_table.setTextElideMode(Qt.ElideRight)
        self.accounts_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.accounts_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.verticalHeader().setDefaultSectionSize(22)
        self.accounts_table.setTabKeyNavigation(False)
        self.accounts_model = AccountsTableModel(self)
        self.accounts_table.setModel(self.accounts_model)
        self.accounts_table.setSortingEnabled(True)
        header = self.accounts_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Name column (الاسم) stretches to absorb leftover space so long names
        # are never clipped; the other columns are auto-fitted to their content
        # by _autofit_accounts_columns() after every data load.
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.accounts_table.setColumnWidth(0, 50)
        self.accounts_table.setColumnWidth(2, 130)
        self.accounts_table.setColumnWidth(3, 90)
        self.accounts_table.setColumnWidth(4, 110)
        self.accounts_table.selectionModel().selectionChanged.connect(self._on_table_selection)
        self.accounts_table.doubleClicked.connect(lambda _: self.run_firefox())
        self.accounts_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.accounts_table.customContextMenuRequested.connect(self._show_table_context_menu)
        header.sortIndicatorChanged.connect(self._save_table_sort_state)
        self.left_layout.addWidget(self.accounts_table, 1)

        self._load_category_checkbox_states()

        add_row = QHBoxLayout()
        add_btn = QPushButton("إضافة حساب جديد")
        add_btn.setObjectName("primaryButton")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_account)
        self.add_account_btn = add_btn
        dup_btn = QPushButton("نسخ الحساب")
        self.dup_account_btn = dup_btn
        dup_btn.setCursor(Qt.PointingHandCursor)
        dup_btn.setToolTip("تكرار الحساب المحدد")
        dup_btn.clicked.connect(self._duplicate_selected_account)
        add_row.addWidget(add_btn, 2)
        add_row.addWidget(dup_btn, 1)
        self.left_layout.addLayout(add_row)

        # Both halves get the SAME stretch factor and the same size policy, so the accounts
        # panel (right) and the tabs panel (left) always have equal widths.
        for panel in (left_widget, self.tab_widget):
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(left_widget, 1)
        main_layout.addWidget(self.tab_widget, 1)
        self._update_timer_label()

    def _build_dashboard_strip(self, parent_layout: QVBoxLayout) -> None:
        strip = QFrame()
        strip.setObjectName("statsStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)
        self._stat_total = QLabel("الإجمالي: --")
        self._stat_active = QLabel("نشط: --")
        self._stat_inactive = QLabel("غير نشط: --")
        self._stat_points = QLabel("النقاط: --")
        for lbl, name in (
            (self._stat_total, "statCard"),
            (self._stat_active, "statCardGood"),
            (self._stat_inactive, "statCardWarn"),
            (self._stat_points, "statCard"),
        ):
            lbl.setObjectName(name)
            lbl.setAlignment(Qt.AlignCenter)
            row.addWidget(lbl, 1)
        self._stats_strip = strip
        parent_layout.addWidget(strip)

    def _build_ip_countdown_section(self, parent_layout: QVBoxLayout) -> None:
        ip_group = QGroupBox("IP / العداد")
        ip_group.setObjectName("compactIpGroup")
        ip_layout = QVBoxLayout(ip_group)
        self._ip_group = ip_group
        self._ip_group_layout = ip_layout

        ip_fields_row = QHBoxLayout()
        self._ip_fields_row = ip_fields_row
        self.ip_after_field = QLineEdit()
        self.ip_after_field.setObjectName("ip_after_field")
        self.ip_after_field.setAlignment(Qt.AlignRight)
        self.ip_after_field.setPlaceholderText("IP الجديد")
        lbl_after = QLabel("الجديد")
        lbl_after.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        self.ip_before_field = QLineEdit()
        self.ip_before_field.setObjectName("ip_before_field")
        self.ip_before_field.setAlignment(Qt.AlignRight)
        self.ip_before_field.setPlaceholderText("IP السابق")
        lbl_before = QLabel("السابق")
        lbl_before.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        self.ip_before_field.textChanged.connect(self._check_ip_match)
        self.ip_after_field.textChanged.connect(self._check_ip_match)
        self.update_before_btn = QPushButton("تثبيت")
        self.update_before_btn.setCursor(Qt.PointingHandCursor)
        self.update_before_btn.setToolTip("تثبيت العنوان الحالي كـ IP السابق")
        self.update_before_btn.clicked.connect(self._update_before_ip)
        self.check_proxy_ip_btn = QPushButton("جلب")
        self.check_proxy_ip_btn.setCursor(Qt.PointingHandCursor)
        self.check_proxy_ip_btn.setToolTip("جلب عنوان IP الحالي عبر البروكسي")
        self.check_proxy_ip_btn.clicked.connect(self._check_proxy_ip)
        self.geo_ip_btn = QPushButton("موقع")
        self.geo_ip_btn.setCursor(Qt.PointingHandCursor)
        self.geo_ip_btn.setToolTip("الاستعلام عن موقع IP البروكسي (ip2location.io) مع مطابقة توقيت ويندوز")
        self.geo_ip_btn.clicked.connect(self._open_geo_dialog)
        ip_fields_row.addWidget(lbl_before)
        ip_fields_row.addWidget(self.ip_before_field, 1)
        ip_fields_row.addWidget(lbl_after)
        ip_fields_row.addWidget(self.ip_after_field, 1)
        ip_fields_row.addWidget(self.update_before_btn)
        ip_fields_row.addWidget(self.check_proxy_ip_btn)
        ip_fields_row.addWidget(self.geo_ip_btn)
        ip_layout.addLayout(ip_fields_row)

        ctrl = QHBoxLayout()
        self._ip_ctrl_row = ctrl
        lbl_s = QLabel("ثوانٍ")
        lbl_s.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        self.spin_seconds = QSpinBox()
        self.spin_seconds.setRange(0, 999)
        self.spin_seconds.setAlignment(Qt.AlignRight)
        self.spin_seconds.setValue(DEFAULT_COUNTDOWN_SEC)
        self.spin_seconds.valueChanged.connect(self._on_spin_changed)
        self.timer_label = QLabel(f"{DEFAULT_COUNTDOWN_SEC:02d}s")
        self.timer_label.setObjectName("compactTimerLabel")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.start_countdown_btn = QPushButton("بدء")
        self.stop_countdown_btn = QPushButton("إيقاف")
        self.start_countdown_btn.setCursor(Qt.PointingHandCursor)
        self.stop_countdown_btn.setCursor(Qt.PointingHandCursor)
        self.start_countdown_btn.clicked.connect(self._start_countdown)
        self.stop_countdown_btn.clicked.connect(self._stop_countdown)
        ctrl.addWidget(lbl_s)
        ctrl.addWidget(self.spin_seconds)
        ctrl.addWidget(self.timer_label)
        ctrl.addWidget(self.start_countdown_btn)
        ctrl.addWidget(self.stop_countdown_btn)
        ctrl.addStretch()
        ip_layout.addLayout(ctrl)
        parent_layout.addWidget(ip_group)

    def _set_widget_height(self, widget: Optional[QWidget], height: int) -> None:
        if widget is None:
            return
        widget.setMinimumHeight(height)
        widget.setMaximumHeight(height)

    def _apply_ui_density(self, density: Optional[int] = None) -> None:
        if density is None:
            density = self._ui_density
        density = max(UI_DENSITY_MIN, min(UI_DENSITY_MAX, int(density)))
        self._ui_density = density
        sizes = {
            1: {"ctrl": 26, "search": 28, "stat": 24, "row": 22, "btn": 30, "spin_w": 64, "timer_w": 44, "gap": 4, "pad": (6, 10, 6, 4)},
            2: {"ctrl": 32, "search": 34, "stat": 30, "row": 26, "btn": 36, "spin_w": 74, "timer_w": 52, "gap": 6, "pad": (8, 12, 8, 6)},
            3: {"ctrl": 38, "search": 40, "stat": 36, "row": 30, "btn": 42, "spin_w": 84, "timer_w": 60, "gap": 8, "pad": (10, 14, 10, 8)},
        }[density]
        ctrl_h = sizes["ctrl"]
        for w in (
            self.ip_before_field, self.ip_after_field,
            self.update_before_btn, self.check_proxy_ip_btn, self.geo_ip_btn,
            self.spin_seconds, self.start_countdown_btn, self.stop_countdown_btn,
            self.timer_label,
        ):
            self._set_widget_height(w, ctrl_h)
        self.spin_seconds.setMaximumWidth(sizes["spin_w"])
        self.timer_label.setMinimumWidth(sizes["timer_w"])
        ip_layout = getattr(self, "_ip_group_layout", None)
        if ip_layout is not None:
            pad = sizes["pad"]
            ip_layout.setContentsMargins(pad[0], pad[1], pad[2], pad[3])
            ip_layout.setSpacing(max(2, sizes["gap"] - 2))
        fields_row = getattr(self, "_ip_fields_row", None)
        if fields_row is not None:
            fields_row.setSpacing(sizes["gap"])
        ctrl_row = getattr(self, "_ip_ctrl_row", None)
        if ctrl_row is not None:
            ctrl_row.setSpacing(sizes["gap"])
        self._set_widget_height(self.search_input, sizes["search"])
        for lbl in (self._stat_total, self._stat_active, self._stat_inactive, self._stat_points):
            self._set_widget_height(lbl, sizes["stat"])
        strip = getattr(self, "_stats_strip", None)
        if strip is not None:
            sl = strip.layout()
            if sl is not None:
                m = 2 if density == 1 else (4 if density == 2 else 6)
                sl.setContentsMargins(m, m, m, m)
                sl.setSpacing(m)
        self.accounts_table.verticalHeader().setDefaultSectionSize(sizes["row"])
        self._set_widget_height(getattr(self, "add_account_btn", None), sizes["btn"])
        self._set_widget_height(getattr(self, "dup_account_btn", None), sizes["btn"])
        combo = getattr(self, "density_combo", None)
        if combo is not None and combo.currentData() != density:
            combo.blockSignals(True)
            combo.setCurrentIndex(density - 1)
            combo.blockSignals(False)

    def _on_density_changed(self, _index: int = 0) -> None:
        combo = getattr(self, "density_combo", None)
        if combo is None:
            return
        value = combo.currentData()
        if value is None:
            return
        density = int(value)
        if density == self._ui_density:
            return
        self._apply_ui_density(density)
        try:
            self.db_manager.set_setting("pref_ui_density", str(density))
        except Exception as exc:
            logger.error("Error saving UI density: {}", exc)

    def _setup_account_details_tab(self) -> None:
        account_layout = QVBoxLayout(self.account_tab)
        account_layout.setSpacing(15)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(12)

        fields_def = [
            ("الرقم:", "number"), ("البريد الإلكتروني:", "email"), ("كلمة المرور:", "password"),
            ("تاريخ الميلاد:", "dob"), ("العمر:", "age"), ("الشارع:", "street"),
            ("المدينة/البلدة:", "city_town"), ("المنطقة:", "state_province_region"),
            ("الرمز البريدي:", "zip_postal_code"), ("النقاط:", "points"), ("الإحالات:", "referrals"),
        ]
        self.fields: Dict[str, FieldLineEdit] = {}
        for label_text, field_name in fields_def:
            fl = QHBoxLayout()
            fl.setSpacing(10)
            lbl = QLabel(label_text)
            lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
            lbl.setMinimumWidth(100)
            field = FieldLineEdit(self._save_single_field, self._cancel_field_edit,
                                  allow_inline_edit=(field_name == "points"))
            if field_name == "points":
                # The ONLY field that can be edited directly with a double-click.
                field.setToolTip(f"نقرة مزدوجة لتعديل {label_text[:-1]} (Enter للحفظ، Esc للإلغاء)")
            else:
                # Every other field is locked until "تعديل جميع تفاصيل الحساب" is pressed.
                field.setToolTip(LOCKED_FIELD_TOOLTIP)
                field.editBlocked.connect(self._on_field_edit_blocked)
            self.fields[field_name] = field
            btns = QHBoxLayout()
            btns.setSpacing(5)
            copy_btn = QPushButton("📋")
            copy_btn.setObjectName("iconButton")
            copy_btn.setToolTip(f"نسخ {label_text[:-1]}")
            copy_btn.setFixedSize(32, 32)
            copy_btn.setCursor(Qt.PointingHandCursor)
            copy_btn.clicked.connect(lambda _, f=field: self._copy_to_clipboard(f.text()))
            btns.addWidget(copy_btn)
            if field_name == "email":
                qr_btn = QPushButton("QR")
                qr_btn.setObjectName("iconButton")
                qr_btn.setToolTip("عرض QR")
                qr_btn.setFixedSize(40, 32)
                qr_btn.setCursor(Qt.PointingHandCursor)
                qr_btn.clicked.connect(lambda _, f=field: QRCodeDialog(f.text(), self).exec_())
                btns.addWidget(qr_btn)
            fl.addWidget(lbl)
            fl.addWidget(field, 1)
            fl.addLayout(btns)
            scroll_layout.addLayout(fl)

        notes_fl = QHBoxLayout()
        notes_fl.setSpacing(10)
        notes_lbl = QLabel("ملاحظات:")
        notes_lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        notes_lbl.setMinimumWidth(100)
        # Locked like every other field except points: edited only via the full-edit button.
        self.notes_field = FieldLineEdit(self._save_notes_field, self._cancel_notes_edit,
                                         allow_inline_edit=False)
        self.notes_field.setPlaceholderText("أدخل ملاحظات هنا...")
        self.notes_field.setToolTip(LOCKED_FIELD_TOOLTIP)
        self.notes_field.editBlocked.connect(self._on_field_edit_blocked)
        nc_btn = QPushButton("📋")
        nc_btn.setObjectName("iconButton")
        nc_btn.setToolTip("نسخ الملاحظات")
        nc_btn.setFixedSize(32, 32)
        nc_btn.setCursor(Qt.PointingHandCursor)
        nc_btn.clicked.connect(lambda: self._copy_to_clipboard(self.notes_field.text()))
        notes_fl.addWidget(notes_lbl)
        notes_fl.addWidget(self.notes_field, 1)
        notes_fl.addWidget(nc_btn)
        scroll_layout.addLayout(notes_fl)
        hint_lbl = QLabel("💡 نقرة مزدوجة على حقل النقاط لتعديله سريعًا — ولتعديل بقية الحقول استخدم زر «تعديل جميع تفاصيل الحساب» بالأسفل")
        hint_lbl.setObjectName("hintLabel")
        hint_lbl.setAlignment(Qt.AlignCenter)
        scroll_layout.addSpacing(4)
        scroll_layout.addWidget(hint_lbl)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_widget)
        account_layout.addWidget(scroll)
        edit_all_btn = QPushButton("✏️ تعديل جميع تفاصيل الحساب")
        edit_all_btn.setObjectName("primaryButton")
        edit_all_btn.setMinimumHeight(40)
        edit_all_btn.setCursor(Qt.PointingHandCursor)
        edit_all_btn.clicked.connect(self._open_edit_dialog)
        account_layout.addWidget(edit_all_btn)
        self.tab_widget.addTab(self.account_tab, "📋 تفاصيل الحساب")

    def _setup_proxy_config_tab(self) -> None:
        proxy_layout = QVBoxLayout(self.proxy_tab)
        proxy_layout.setSpacing(8)
        proxy_fields = ["ip", "port", "username", "password"]
        self.proxy_inputs: Dict[str, QLineEdit] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        for i, field in enumerate(proxy_fields):
            lbl = QLabel(field.capitalize() + ":")
            lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
            # RTL grid: column 0 is the RIGHT-most one -> label first, input next to it.
            grid.addWidget(lbl, i, 0)
            inp = QLineEdit()
            inp.setAlignment(Qt.AlignRight)
            if field == "port":
                # Digit-only port: blocks invalid input instead of failing on save.
                inp.setValidator(QIntValidator(1, 65535, inp))
                inp.setToolTip("منفذ البروكسي (1 - 65535)")
            if field == "password":
                inp.setToolTip("كلمة مرور البروكسي — تُحفظ في قاعدة البيانات وفي proxy_config.json")
            inp.textChanged.connect(self._on_proxy_field_changed)
            self.proxy_inputs[field] = inp
            grid.addWidget(inp, i, 1)
        grid.setColumnStretch(1, 1)  # inputs absorb the free width
        proxy_layout.addLayout(grid)
        # Inline hint: what "save" does and where the exportable file lands.
        hint = QLabel("اكتب بيانات البروكسي ثم اضغط حفظ — يُخزَّن التكوين في قاعدة البيانات ويُنشأ ملف "
                      "proxy_config.json بجانب البرنامج، جاهز للاستيراد في إضافة FoxyProxy.")
        hint.setObjectName("hintLabel")
        hint.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        hint.setWordWrap(True)
        proxy_layout.addWidget(hint)
        self.save_proxy_btn = QPushButton("💾 حفظ البروكسي")
        self.save_proxy_btn.setObjectName("primaryButton")
        self.save_proxy_btn.setMinimumHeight(40)
        self.save_proxy_btn.setCursor(Qt.PointingHandCursor)
        self.save_proxy_btn.setToolTip("حفظ التكوين في قاعدة البيانات وتحديث proxy_config.json")
        self.save_proxy_btn.clicked.connect(self._save_proxy_config)
        proxy_layout.addWidget(self.save_proxy_btn)
        self.proxy_status_label = QLabel("")
        self.proxy_status_label.setObjectName("proxyStatusLabel")
        self.proxy_status_label.setWordWrap(True)
        self.proxy_status_label.hide()  # empty by default; shown only with a message
        proxy_layout.addWidget(self.proxy_status_label)
        json_header = QHBoxLayout()
        lbl_json = QLabel("تكوين FoxyProxy JSON:")
        lbl_json.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        self.copy_proxy_json_btn = QPushButton("📋 نسخ JSON")
        self.copy_proxy_json_btn.setObjectName("iconButton")
        self.copy_proxy_json_btn.setCursor(Qt.PointingHandCursor)
        self.copy_proxy_json_btn.setToolTip("نسخ تكوين JSON إلى الحافظة")
        self.copy_proxy_json_btn.clicked.connect(self._copy_proxy_json)
        json_header.addWidget(lbl_json, 1)
        json_header.addWidget(self.copy_proxy_json_btn)
        proxy_layout.addLayout(json_header)
        self.json_display = QTextEdit()
        self.json_display.setObjectName("jsonDisplay")
        self.json_display.setReadOnly(True)
        # JSON is LTR technical content: right-to-left mirroring made braces and
        # quotes unreadable. Left-to-right + fixed-width font = legible config.
        self.json_display.setLayoutDirection(Qt.LeftToRight)
        self.json_display.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.json_display.setPlaceholderText('{\n  "mode": "1.2.3.4:1080",\n  "data": [ ... ]\n}')
        proxy_layout.addWidget(self.json_display, 1)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.tab_widget.addTab(self.proxy_tab, "🔧 إعدادات البروكسي")

    def _copy_proxy_json(self) -> None:
        """Copy the generated FoxyProxy JSON to the clipboard (one click)."""
        text = self.json_display.toPlainText().strip()
        if not text:
            self.statusBar().showMessage("ℹ️ لا يوجد تكوين لنسخه بعد — املأ الحقول واحفظ أولًا.", 4000)
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("✅ تم نسخ تكوين JSON إلى الحافظة.", 3000)

    def _setup_delete_account_tab(self) -> None:
        delete_layout = QVBoxLayout(self.delete_tab)
        lbl = QLabel("حدد حسابًا (أو عدة) لحذفه:")
        lbl.setAlignment(ALIGN_RIGHT_ABS)
        delete_layout.addWidget(lbl)
        self.delete_list = QListWidget()
        self.delete_list.setLayoutDirection(Qt.RightToLeft)
        self.delete_list.setSelectionMode(QListWidget.MultiSelection)
        delete_layout.addWidget(self.delete_list)
        self.delete_btn = QPushButton("🗑️ حذف الحسابات المحددة")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.setMinimumHeight(40)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete_selected_accounts)
        delete_layout.addWidget(self.delete_btn)
        self.tab_widget.addTab(self.delete_tab, "🗑️ حذف حساب")

    def _setup_addons_tab(self) -> None:
        """Addons tab — one clean card per link (RTL layout, LTR URLs)."""
        self.addons_tab.setLayoutDirection(Qt.RightToLeft)
        addons_layout = QVBoxLayout(self.addons_tab)
        addons_layout.setSpacing(10)

        header = QLabel("🔗 الإضافات والأدوات المفيدة")
        header.setObjectName("dialogTitle")
        header.setAlignment(ALIGN_RIGHT_ABS)
        addons_layout.addWidget(header)

        hint = QLabel(
            "💡 ✏️ لتعديل الرابط (Enter للحفظ) • 📋 للنسخ • 🌐 للفتح في المتصفح"
        )
        hint.setObjectName("hintLabel")
        hint.setAlignment(ALIGN_RIGHT_ABS)
        hint.setWordWrap(True)
        addons_layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setLayoutDirection(Qt.RightToLeft)
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(8)
        scroll_layout.setContentsMargins(4, 4, 4, 4)
        saved_links = self._load_addon_links()
        for i, (label_text, link) in enumerate(DEFAULT_ADDONS):
            actual_link = saved_links[i] if i < len(saved_links) else link
            self._build_addon_row(scroll_layout, i + 1, label_text, actual_link)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        addons_layout.addWidget(scroll, 1)
        self.tab_widget.addTab(self.addons_tab, "🧩 الإضافات")

    def _build_addon_row(self, parent_layout: QVBoxLayout, idx: int, label_text: str, link: str) -> None:
        """A single addon entry rendered as a hoverable card."""
        card = QFrame()
        card.setObjectName("addonCard")
        # RTL FIX: no explicit setDirection - it was mirrored back to LTR inside the RTL
        # card (label on the left, buttons on the right). The inherited RTL flow puts the
        # label on the right, then the link, then the open/copy/edit buttons on the left.
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        lbl = QLabel(f"{idx}. {label_text}")
        lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        lbl.setMinimumWidth(170)
        row.addWidget(lbl)

        line_edit = QLineEdit(link)
        line_edit.setCursorPosition(0)  # show the START of the URL (the panel is narrower now)
        line_edit.setDisabled(True)
        # URLs are Latin text: keep them left-aligned inside the RTL card so
        # the scheme/host stay readable, while the card itself is RTL.
        line_edit.setLayoutDirection(Qt.LeftToRight)
        line_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        row.addWidget(line_edit, 1)

        edit_btn = QPushButton("✏️")
        edit_btn.setObjectName("iconButton")
        edit_btn.setToolTip("تعديل الرابط")
        edit_btn.setFixedSize(34, 32)
        edit_btn.setCursor(Qt.PointingHandCursor)
        copy_btn = QPushButton("📋")
        copy_btn.setObjectName("iconButton")
        copy_btn.setToolTip("نسخ الرابط")
        copy_btn.setFixedSize(34, 32)
        copy_btn.setCursor(Qt.PointingHandCursor)
        open_btn = QPushButton("🌐 فتح")
        open_btn.setToolTip("فتح الرابط في المتصفح")
        open_btn.setFixedHeight(32)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(lambda _, url=link: webbrowser.open(url))
        row.addWidget(edit_btn)
        row.addWidget(copy_btn)
        row.addWidget(open_btn)
        parent_layout.addWidget(card)

        edit_btn.clicked.connect(
            lambda _, le=line_edit: (le.setEnabled(True), le.setFocus(), le.selectAll()))
        copy_btn.clicked.connect(
            lambda _, le=line_edit: (QApplication.clipboard().setText(le.text()),
                                     self._show_toast("📋 تم نسخ الرابط", copy_btn)))
        line_edit.editingFinished.connect(
            lambda le=line_edit, i=idx: (self._save_addon_value(i, le.text().strip()),
                                         le.setDisabled(True)))

    def _setup_tools_tab(self) -> None:
        """Tools tab (formerly admin-only) — visible to every user."""
        admin_layout = QVBoxLayout(self.admin_tab)
        export_group = QGroupBox("📤 تصدير البيانات")

        export_layout = QVBoxLayout(export_group)
        self.copy_sql_btn = QPushButton("📋 نسخ جميع الحسابات كأوامر SQL")
        self.copy_sql_btn.setCursor(Qt.PointingHandCursor)
        self.copy_sql_btn.clicked.connect(self._copy_all_accounts_as_sql)
        export_layout.addWidget(self.copy_sql_btn)
        admin_layout.addWidget(export_group)
        admin_layout.addSpacing(20)

        cat_group = QGroupBox("👥 إدارة الفئات")

        cat_layout = QVBoxLayout(cat_group)
        self.categories_list = QListWidget()
        self.categories_list.setSelectionMode(QListWidget.SingleSelection)
        cat_layout.addWidget(QLabel("الفئات الموجودة:"))
        cat_layout.addWidget(self.categories_list)
        add_cat = QHBoxLayout()
        self.new_category_input = QLineEdit()
        self.new_category_input.setPlaceholderText("اسم الفئة الجديدة")
        add_cat_btn = QPushButton("➕ إضافة")
        add_cat_btn.clicked.connect(self._add_category)
        add_cat.addWidget(self.new_category_input)
        add_cat.addWidget(add_cat_btn)
        cat_layout.addLayout(add_cat)
        del_cat = QHBoxLayout()
        self.delete_category_combo = QComboBox()
        self._refresh_category_combo()
        del_cat_btn = QPushButton("🗑️ حذف الفئة المحددة")
        del_cat_btn.clicked.connect(self._delete_category)
        del_cat.addWidget(self.delete_category_combo)
        del_cat.addWidget(del_cat_btn)
        cat_layout.addLayout(del_cat)
        self.cat_counts_label = QLabel("")
        cat_layout.addWidget(self.cat_counts_label)
        admin_layout.addWidget(cat_group)
        admin_layout.addStretch()
        self._refresh_categories_list()
        self.tab_widget.addTab(self.admin_tab, "🛠️ الأدوات")

    def _setup_statistics_tab(self) -> None:
        stats_layout = QVBoxLayout(self.stats_tab)
        filter_layout = QHBoxLayout()
        self.stats_tab.setLayoutDirection(Qt.RightToLeft)
        filter_lbl = QLabel("📊 تصفية حسب الحساب:")
        filter_lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        self.stats_filter_combo = QComboBox()
        self.stats_filter_combo.setMinimumWidth(200)
        self.stats_filter_combo.addItem("الكل", None)

        def _populate_combo(names) -> None:
            for acc_id, name in names:
                self.stats_filter_combo.addItem(name, acc_id)
        run_task(self.db_manager.get_account_names, _populate_combo)
        self.stats_filter_combo.currentIndexChanged.connect(self._on_stats_filter_changed)
        filter_layout.addWidget(filter_lbl)
        filter_layout.addWidget(self.stats_filter_combo)
        filter_layout.addStretch()
        stats_layout.addLayout(filter_layout)
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(5)
        self.stats_table.setHorizontalHeaderLabels(["الحساب", "النقاط القديمة", "النقاط الجديدة", "التغيير", "التاريخ"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setLayoutDirection(Qt.RightToLeft)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        stats_layout.addWidget(self.stats_table)
        self.tab_widget.addTab(self.stats_tab, "📈 إحصائيات")
        self._load_point_history()


    def _create_toolbar(self) -> None:
        for tb in self.findChildren(QToolBar):
            try:
                self.removeToolBar(tb)
            except Exception:
                pass
        toolbar = QToolBar("شريط الأدوات")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # Centralized font management: the toolbar emphasis font is derived
        # from the user's preferences (base size + offset) — reproduces the
        # old hard-coded 14pt DemiBold look at default settings, but now
        # scales with the chosen size/bold.
        btn_font = self.font_manager.toolbar_font()

        # Each toolbar action gets its own accent color so the user can tell
        # them apart at a glance (styles come from the QSS #xxxButton rules).
        # NOTE: "فتح حساب" (self.firefox_btn) moved to the "ملف" menu — it is a QAction
        # created in _create_main_menu (enabled/disabled exactly like the old button).
        self.firefox_private_btn = QPushButton("👤 تصفح خفي")
        self.firefox_private_btn.setObjectName("privateButton")
        self.firefox_private_btn.setFont(btn_font)
        self.firefox_private_btn.setCursor(Qt.PointingHandCursor)
        self.firefox_private_btn.clicked.connect(lambda: self.run_firefox(private=True))
        toolbar.addWidget(self.firefox_private_btn)
        toolbar.addSeparator()

        self.telegram_btn = QPushButton("✈️ بوت البروكسي")
        self.telegram_btn.setObjectName("telegramButton")
        self.telegram_btn.setFont(btn_font)
        self.telegram_btn.setCursor(Qt.PointingHandCursor)
        self.telegram_btn.setToolTip("فتح بوت البروكسي في تطبيق Telegram Desktop")
        self.telegram_btn.clicked.connect(lambda: open_telegram_bot(TELEGRAM_BOT_URL))
        toolbar.addWidget(self.telegram_btn)
        toolbar.addSeparator()

        self.tell_ai_btn = QPushButton("🤖 معلومات الشخصية")
        self.tell_ai_btn.setObjectName("aiButton")
        self.tell_ai_btn.setFont(btn_font)
        self.tell_ai_btn.setCursor(Qt.PointingHandCursor)
        self.tell_ai_btn.clicked.connect(self._tell_ai_copy)
        toolbar.addWidget(self.tell_ai_btn)

        self.copilot_btn = QPushButton("💬 موقع الذكاء")
        self.copilot_btn.setObjectName("copilotButton")
        self.copilot_btn.setFont(btn_font)
        self.copilot_btn.setCursor(Qt.PointingHandCursor)
        self.copilot_btn.clicked.connect(lambda: webbrowser.open("https://copilot.microsoft.com"))
        toolbar.addWidget(self.copilot_btn)

        self.yougov_btn = QPushButton("📊 صفحة يوغوف الاساسية")
        self.yougov_btn.setObjectName("yougovButton")
        self.yougov_btn.setFont(btn_font)
        self.yougov_btn.setCursor(Qt.PointingHandCursor)
        self.yougov_btn.clicked.connect(self._copy_yougov_link)
        toolbar.addWidget(self.yougov_btn)

        # New button: copies the link that opens Google Translate.
        self.translate_btn = QPushButton("🌐 ترجمة غوغل")
        self.translate_btn.setObjectName("translateButton")
        self.translate_btn.setFont(btn_font)
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.setToolTip("نسخ رابط ترجمة غوغل")
        self.translate_btn.clicked.connect(self._copy_translate_link)
        toolbar.addWidget(self.translate_btn)

        for btn in [self.firefox_private_btn, self.telegram_btn, self.tell_ai_btn,
                    self.copilot_btn, self.yougov_btn, self.translate_btn]:
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addSeparator()

        dens_lbl = QLabel("حجم الشريط:")
        dens_lbl.setAlignment(ALIGN_RIGHT_ABS | Qt.AlignVCenter)
        toolbar.addWidget(dens_lbl)
        self.density_combo = QComboBox()
        self.density_combo.setToolTip("حجم شريط IP والعداد — مضغوط / متوسط / مريح")
        self.density_combo.setMinimumWidth(90)
        for level in range(UI_DENSITY_MIN, UI_DENSITY_MAX + 1):
            self.density_combo.addItem(UI_DENSITY_LABELS[level], level)
        self.density_combo.setCurrentIndex(self._ui_density - 1)
        self.density_combo.currentIndexChanged.connect(self._on_density_changed)
        toolbar.addWidget(self.density_combo)
        toolbar.addSeparator()

        help_action = QAction(self.style().standardIcon(QStyle.SP_MessageBoxQuestion), "❓ مساعدة", self)
        help_action.triggered.connect(self._show_help_dialog)
        toolbar.addAction(help_action)

    def _create_main_menu(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setLayoutDirection(Qt.RightToLeft)
        for action in list(menu_bar.actions()):
            if action.text() in ("File", "ملف"):
                menu_bar.removeAction(action)
        file_menu = menu_bar.addMenu("📁 ملف")

        # "فتح حساب" moved here from the toolbar. It stays an attribute named firefox_btn
        # because update_firefox_button_state()/run_firefox() enable/disable it by that name
        # (QAction.setEnabled works exactly like the old QPushButton).
        self.firefox_btn = QAction("🔥 فتح حساب", self)
        self.firefox_btn.setShortcut("Ctrl+O")
        self.firefox_btn.setStatusTip("فتح الحساب المحدد في Firefox")
        self.firefox_btn.triggered.connect(lambda: self.run_firefox(private=False))
        file_menu.addAction(self.firefox_btn)
        file_menu.addSeparator()

        change_pass = QAction("🔐 تغيير كلمة المرور", self)
        change_pass.triggered.connect(self._change_password)
        file_menu.addAction(change_pass)

        about = QAction("ℹ️ حول البرنامج", self)
        about.triggered.connect(lambda: AboutDialog(
            self, auto_update_enabled=self._auto_update_pref).exec_())
        file_menu.addAction(about)

        preferences = QAction("⚙️ تفضيلات", self)
        preferences.triggered.connect(self._open_preferences_dialog)
        file_menu.addAction(preferences)

        check_updates = QAction("🔄 التحقق من التحديثات", self)
        check_updates.setStatusTip("البحث عن إصدار أحدث من البرنامج وتثبيته")
        check_updates.triggered.connect(lambda: self._check_for_updates(manual=True))
        file_menu.addAction(check_updates)

        auto_upd = QAction("🕘 فحص التحديثات عند بدء التشغيل", self)
        auto_upd.setCheckable(True)
        auto_upd.setChecked(self._auto_update_pref)
        auto_upd.toggled.connect(self._set_auto_update_pref)
        file_menu.addAction(auto_upd)

        file_menu.addSeparator()
        cloud_sync = QAction("☁️ المزامنة السحابية...", self)
        cloud_sync.setStatusTip("تسجيل الدخول ومزامنة الحسابات مع قاعدة Supabase السحابية")
        cloud_sync.triggered.connect(self._open_cloud_sync_dialog)
        file_menu.addAction(cloud_sync)

        auto_sync = QAction("☁️ مزامنة عند بدء التشغيل", self)
        auto_sync.setCheckable(True)
        auto_sync.setChecked(self._auto_sync_pref)
        auto_sync.toggled.connect(self._set_auto_sync_pref)
        file_menu.addAction(auto_sync)

        save_filters = QAction("💾 حفظ حالة التشيك بوكس", self)
        save_filters.triggered.connect(self._save_category_checkbox_states)
        file_menu.addAction(save_filters)

        debug_act = QAction("🐛 فحص قاعدة البيانات", self)
        debug_act.triggered.connect(self._debug_db_status)
        file_menu.addAction(debug_act)

        file_menu.addSeparator()
        export_csv = QAction("تصدير CSV", self)
        export_csv.setShortcut("Ctrl+E")
        export_csv.triggered.connect(self._export_csv)
        file_menu.addAction(export_csv)

        backup_act = QAction("نسخ احتياطي لقاعدة البيانات", self)
        backup_act.setShortcut("Ctrl+B")
        backup_act.triggered.connect(self._backup_database)
        file_menu.addAction(backup_act)

        exit_act = QAction("خروج", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

    def _install_shortcuts(self) -> None:
        def _bind(seq: str, slot) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)
        _bind("Ctrl+F", self._focus_search)
        _bind("Ctrl+N", self._add_account)
        _bind("Ctrl+R", lambda: self.filter_accounts(self._active_filter))
        _bind("F5", lambda: self.filter_accounts(self._active_filter))
        _bind("Ctrl+D", self._duplicate_selected_account)
        _bind("Delete", self._focus_delete_tab)
        _bind("Escape", self._on_escape)

    def _focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _on_escape(self) -> None:
        if self.search_input.hasFocus() and self.search_input.text():
            self.search_input.clear()

    def _focus_delete_tab(self) -> None:
        self.tab_widget.setCurrentWidget(self.delete_tab)

    def _apply_search(self) -> None:
        self._search_text = self.search_input.text().strip()
        self.filter_accounts(self._active_filter)

    def _create_category_checkboxes(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)
        self.category_checkboxes: Dict[str, QCheckBox] = {}
        categories = self.db_manager.get_all_categories()
        for user in categories:
            cb = QCheckBox(user)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda _, u=user: self.filter_accounts(self._active_filter))
            layout.addWidget(cb)
            self.category_checkboxes[user] = cb
        widget.setLayout(layout)
        self.category_widget = widget
        return widget

    def _update_category_checkboxes(self) -> None:
        insert_at = 0
        for i in range(self.left_layout.count()):
            item = self.left_layout.itemAt(i)
            if item is None:
                continue
            if item.widget() == getattr(self, "category_widget", None):
                insert_at = i
                self.left_layout.removeItem(item)
                item.widget().deleteLater()
                break
            if item.widget() is self.accounts_table:
                insert_at = i
                break
        new_widget = self._create_category_checkboxes()
        self.left_layout.insertWidget(insert_at, new_widget)
        self._load_category_checkbox_states()

    def _load_category_checkbox_states(self) -> None:
        saved = self.db_manager.get_setting("selected_categories", "")
        if not saved:
            # No saved state: ensure ALL checkboxes are checked by default
            for cb in self.category_checkboxes.values():
                cb.setChecked(True)
            return
        saved_set = set(saved.split(","))
        for cat, cb in self.category_checkboxes.items():
            cb.setChecked(cat in saved_set)

    def _save_category_checkbox_states(self) -> None:
        selected = [c for c, cb in self.category_checkboxes.items() if cb.isChecked()]
        self.db_manager.set_setting("selected_categories", ",".join(selected))
        self.statusBar().showMessage("✅ تم حفظ حالة التشيك بوكس.", 3000)

    def _add_account(self) -> None:
        dialog = AddAccountDialog(self.db_manager, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            if not data.get("name", "").strip():
                QMessageBox.warning(self, "خطأ في الإدخال", "لا يمكن أن يكون اسم الحساب فارغًا.")
                return
            try:
                def _added(new_id) -> None:
                    self.statusBar().showMessage(f"تمت إضافة حساب جديد بنجاح! (ID: {new_id})", 3000)
                    # select_id re-selects the new row once the async refresh lands.
                    self.filter_accounts(select_id=new_id)
                    self._update_category_counts()
                    self._populate_delete_list()
                    self._refresh_dashboard_stats()

                def _add_failed(exc: str) -> None:
                    if "UNIQUE" in exc or "IntegrityError" in exc:
                        QMessageBox.warning(self, "خطأ", "يوجد حساب بهذا الرقم بالفعل.")
                    else:
                        QMessageBox.warning(self, "خطأ", f"لا يمكن إضافة الحساب: {exc}")
                    self.statusBar().showMessage("❌ فشل في إضافة الحساب.", 5000)

                # INSERT runs off the GUI thread.
                run_task(self.db_manager.add_account, _added, _add_failed, data)
            except Exception as exc:
                if "UNIQUE" in str(exc) or "IntegrityError" in str(exc):
                    QMessageBox.warning(self, "خطأ", "يوجد حساب بهذا الرقم بالفعل.")
                else:
                    QMessageBox.warning(self, "خطأ", f"لا يمكن إضافة الحساب: {exc}")
                self.statusBar().showMessage("❌ فشل في إضافة الحساب.", 5000)

    def _open_edit_dialog(self) -> None:
        if not self.current_account_id:
            self.statusBar().showMessage("❌ لم يتم تحديد حساب لتعديله.", 5000)
            return
        account_id = self.current_account_id

        def _open(account) -> None:
            if not account:
                self.statusBar().showMessage("❌ خطأ: الحساب غير موجود.", 5000)
                return
            dialog = AddAccountDialog(self.db_manager, account_data=dict(account), parent=self)
            if dialog.exec_() == QDialog.Accepted:
                updated = dialog.get_data()
                old_points = account.get("points")
                new_points = updated.get("points")
                account_name = account.get("name", "")
                need_point_history = new_points != old_points

                def _save(acc_id: int, upd: Dict[str, Any], record_history: bool,
                          acc_name: str, old_pts, new_pts) -> None:
                    if record_history:
                        try:
                            self.db_manager.record_point_change(acc_id, acc_name, old_pts or "0", new_pts or "0")
                        except Exception as exc:
                            logger.warning("Failed to record point history: {}", exc)
                    self.db_manager.update_account(acc_id, upd)

                def _done(_result) -> None:
                    self.statusBar().showMessage("تم حفظ تفاصيل الحساب بنجاح!", 3000)
                    # Selection is restored inside filter_accounts; the
                    # selectionChanged signal then refreshes the details pane.
                    self.filter_accounts(self._active_filter, select_id=account_id)
                    self._update_category_counts()
                    self._refresh_dashboard_stats()
                    if need_point_history:
                        self._load_point_history()

                def _fail(exc: str) -> None:
                    QMessageBox.warning(self, "خطأ", f"لا يمكن حفظ الحساب: {exc}")
                    self.statusBar().showMessage("❌ فشل حفظ تفاصيل الحساب.", 5000)

                # UPDATE (and optional history INSERT) run off the GUI thread.
                run_task(_save, _done, _fail, account_id, updated,
                         need_point_history, account_name, old_points, new_points)

        # Fetch the account row off the GUI thread before opening the dialog.
        run_task(self.db_manager.get_account_by_id, _open, None, account_id)

    def _delete_selected_accounts(self) -> None:
        selected = self.delete_list.selectedItems()
        if not selected:
            self.statusBar().showMessage("❌ يرجى تحديد حساب (حسابات) لحذفها.", 5000)
            return
        names = [item.text() for item in selected]
        reply = QMessageBox.question(
            self, "تأكيد الحذف",
            f"هل أنت متأكد أنك تريد حذف {len(names)} حساب بشكل دائم؟\n"
            f"{', '.join(names[:5])}" + ("..." if len(names) > 5 else ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        sel = self._get_selected_account_id()
        ids_to_delete = []
        for item in selected:
            aid = item.data(Qt.UserRole)
            if aid is not None:
                ids_to_delete.append(int(aid))

        def _delete() -> int:
            for aid in ids_to_delete:
                self.db_manager.delete_account(aid)
            return len(ids_to_delete)

        def _done(count) -> None:
            if not count:
                self.statusBar().showMessage("❌ لم يتم العثور على حسابات مطابقة.", 5000)
                return
            self.statusBar().showMessage(f"تم حذف {count} حساب بنجاح.", 3000)
            self.filter_accounts(select_id=sel)
            self._update_category_counts()
            self._populate_delete_list()
            self._refresh_dashboard_stats()

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"❌ خطأ أثناء الحذف: {exc}", 5000)

        run_task(_delete, _done, _fail,
                 status_bar=self.statusBar(),
                 status_message=f"🗑️ جارٍ حذف {len(names)} حساب...")

    def _populate_delete_list(self) -> None:
        def _done(names) -> None:
            self.delete_list.clear()
            for acc_id, name in names:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, acc_id)
                self.delete_list.addItem(item)
        run_task(self.db_manager.get_account_names, _done)

    def _copy_all_accounts_as_sql(self) -> None:
        def _done(sql) -> None:
            if not sql:
                self.statusBar().showMessage("لا توجد حسابات لتصديرها.", 3000)
                return
            QApplication.clipboard().setText(sql)
            self.statusBar().showMessage("✅ تم نسخ أوامر SQL إلى الحافظة.", 4000)
        # Building the full SQL dump scans every account — keep it off the GUI thread.
        run_task(self.db_manager.export_accounts_as_sql, _done,
                 status_bar=self.statusBar(),
                 status_message="جارٍ تصدير الحسابات كأوامر SQL...")

    def _duplicate_selected_account(self) -> None:
        if not self.current_account_id:
            self.statusBar().showMessage("حدد حسابًا لنسخه أولًا.", 3000)
            return

        def _done(new_id) -> None:
            self.statusBar().showMessage(f"تم نسخ الحساب (ID: {new_id})", 3000)
            self.filter_accounts(select_id=new_id)
            self._update_category_counts()
            self._populate_delete_list()
            self._refresh_dashboard_stats()

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"تعذر نسخ الحساب: {exc}", 5000)

        run_task(self.db_manager.duplicate_account, _done, _fail, self.current_account_id)

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "تصدير الحسابات CSV", str(BASE_DIR / "accounts.csv"), "CSV (*.csv)")
        if not path:
            return

        def _write() -> str:
            payload = self.db_manager.export_accounts_as_csv()
            Path(path).write_text(payload, encoding="utf-8-sig")
            return path

        def _done(saved) -> None:
            self.statusBar().showMessage(f"تم تصدير CSV إلى {saved}", 4000)

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"فشل تصدير CSV: {exc}", 5000)

        run_task(_write, _done, _fail, status_bar=self.statusBar(),
                 status_message="جارٍ تصدير CSV...")

    def _backup_database(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "نسخ احتياطي لقاعدة البيانات",
            str(BASE_DIR / f"accounts-backup-{stamp}.db"), "SQLite (*.db)")
        if not path:
            return

        def _done(saved) -> None:
            self.statusBar().showMessage(f"تم حفظ النسخة الاحتياطية: {saved}", 5000)

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"فشل النسخ الاحتياطي: {exc}", 5000)

        run_task(self.db_manager.backup_database, _done, _fail, path,
                 status_bar=self.statusBar(),
                 status_message="جارٍ إنشاء نسخة احتياطية...")

    def _show_table_context_menu(self, pos) -> None:
        idx = self.accounts_table.indexAt(pos)
        if idx.isValid():
            self.accounts_table.setCurrentIndex(idx)
            self._show_account_details(idx)
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.RightToLeft)
        act_open = menu.addAction("فتح في Firefox")
        act_private = menu.addAction("تصفح خفي")
        act_edit = menu.addAction("تعديل التفاصيل")
        act_dup = menu.addAction("نسخ الحساب")
        act_copy = menu.addAction("نسخ الاسم")
        chosen = menu.exec_(self.accounts_table.viewport().mapToGlobal(pos))
        if chosen is act_open:
            self.run_firefox(private=False)
        elif chosen is act_private:
            self.run_firefox(private=True)
        elif chosen is act_edit:
            self._open_edit_dialog()
        elif chosen is act_dup:
            self._duplicate_selected_account()
        elif chosen is act_copy:
            if idx.isValid():
                name = self.accounts_model.account_name_at(idx.row())
                if name:
                    self._copy_to_clipboard(name)

    def _refresh_dashboard_stats(self) -> None:
        def _done(stats) -> None:
            if self._closing:
                return
            self._stat_total.setText(f"الإجمالي: {stats['total']}")
            self._stat_active.setText(f"نشط: {stats['active']}")
            self._stat_inactive.setText(f"غير نشط: {stats['inactive']}")
            self._stat_points.setText(f"النقاط: {stats['total_points']:.0f}")

        run_task(self.db_manager.get_dashboard_stats, _done)

    def _on_table_selection(self, selected, deselected) -> None:
        if selected.indexes():
            self._show_account_details(selected.indexes()[0])

    def _get_selected_account_id(self) -> Optional[int]:
        idx = self.accounts_table.currentIndex()
        if idx.isValid():
            return self.accounts_model.account_id_at(idx.row())
        return None

    def _restore_selection(self, account_id: Optional[int]) -> None:
        if account_id is None:
            return
        for row in range(self.accounts_model.rowCount()):
            if self.accounts_model.account_id_at(row) == account_id:
                idx = self.accounts_model.index(row, 0)
                self.accounts_table.setCurrentIndex(idx)
                self.accounts_table.scrollTo(idx)
                break

    def _autofit_accounts_columns(self) -> None:
        """Fit the accounts table columns to their content after a data load.

        Samples at most 80 rows so large lists stay snappy; الاسم stays in
        Stretch mode and absorbs leftover width.
        """
        try:
            table = self.accounts_table
            model = self.accounts_model
            fm = table.fontMetrics()
            n = model.rowCount()
            step = max(1, n // 80) if n > 80 else 1
            cache = getattr(model, "_display_cache", [])
            for col in (0, 2, 3, 4):
                width = fm.horizontalAdvance(model.HEADERS[col]) + 28
                if cache:
                    for row in range(0, n, step):
                        try:
                            text = cache[row][col]
                        except IndexError:
                            continue
                        if text:
                            text_w = fm.horizontalAdvance(text) + 28
                            if text_w > width:
                                width = text_w
                table.setColumnWidth(col, min(width, 360))
        except Exception as exc:
            logger.debug("Accounts-table column autofit skipped: {}", exc)

    def filter_accounts(self, is_active_filter: Optional[int] = 1,
                        select_id: Optional[int] = None) -> None:
        selected_cats = [c for c, cb in self.category_checkboxes.items() if cb.isChecked()]
        search = self._search_text or None
        # When select_id is given, that row is (re)selected after the async
        # refresh — callers that add/update rows rely on this because the model
        # is only repopulated later, in the _done callback.
        sel = select_id if select_id is not None else self._get_selected_account_id()
        self._active_filter = is_active_filter
        # Keep the segmented filter control in sync with the active filter.
        seg_btn = {1: self.show_active_btn, 0: self.show_inactive_btn,
                   None: self.show_all_btn}.get(is_active_filter)
        if seg_btn is not None and not seg_btn.isChecked():
            seg_btn.setChecked(True)
        self._filter_seq += 1
        seq = self._filter_seq
        cats_for_sql = selected_cats or None

        def _fetch() -> Tuple[List[Dict[str, Any]], int]:
            filtered = self.db_manager.get_account_list(
                is_active=is_active_filter, categories=cats_for_sql, search=search)
            total, _, _ = self.db_manager.get_account_counts()
            return filtered, total

        def _done(result) -> None:
            if seq != self._filter_seq:
                return
            try:
                filtered, total_in_db = result
                self.accounts_model.setData(filtered)
                self._restore_table_sort_state()
                self._autofit_accounts_columns()
                self._restore_selection(sel)
                count = len(filtered)
                if count == 0 and total_in_db > 0 and not search:
                    self.statusBar().showMessage(
                        f"لا توجد حسابات تطابق الفلاتر المختارة ({total_in_db} في قاعدة البيانات).", 4000
                    )
                else:
                    self.statusBar().showMessage(f"عرض {count} حساب (من أصل {total_in_db})", 2500)
            except Exception as exc:
                logger.error("Error filtering accounts: {}", exc)
                self.statusBar().showMessage(f"خطأ في تحميل الحسابات: {exc}", 5000)

        run_task(_fetch, _done)

    def _show_account_details(self, index) -> None:
        if not index.isValid():
            return
        account_id = self.accounts_model.account_id_at(index.row())
        if not account_id:
            return
        self.current_account_id = account_id
        seq = account_id

        def _done(account) -> None:
            if account is None or self.current_account_id != seq:
                return
            for field_name, widget in self.fields.items():
                if field_name == "age":
                    widget.setText(calculate_age(account.get("dob")))
                else:
                    val = account.get(field_name, "")
                    widget.setText("" if val is None else str(val))
            self.notes_field.setText(account.get("notes") or "")
            self.tab_widget.setCurrentIndex(0)

        run_task(self.db_manager.get_account_by_id, _done, None, account_id)

    def _on_field_edit_blocked(self, _field_widget: "FieldLineEdit") -> None:
        """Double-click on a locked field: explain how to edit it (status bar, no message box)."""
        self.statusBar().showMessage(
            "🔒 هذا الحقل مقفل — لتعديله اضغط زر «تعديل جميع تفاصيل الحساب»", 4000)

    def _cancel_field_edit(self, field_widget: "FieldLineEdit") -> None:
        original = getattr(field_widget, "_original_value", None)
        if original is not None:
            field_widget.setText(original)
        field_widget.restore_readonly()
        self.statusBar().showMessage("تم إلغاء التعديل", 2000)

    def _cancel_notes_edit(self, field_widget: "FieldLineEdit") -> None:
        original = getattr(field_widget, "_original_value", None)
        if original is not None:
            field_widget.setText(original)
        field_widget.restore_readonly()
        self.statusBar().showMessage("تم إلغاء تعديل الملاحظات", 2000)

    def _save_single_field(self, field_widget: "FieldLineEdit") -> None:
        try:
            if field_widget.isReadOnly():
                return
            field_widget.restore_readonly()
            if not self.current_account_id:
                self.statusBar().showMessage("❌ خطأ: لم يتم تحديد حساب.", 5000)
                if hasattr(field_widget, "_original_value"):
                    field_widget.setText(field_widget._original_value)
                return
            field_name = next((fn for fn, w in self.fields.items() if w is field_widget), None)
            if field_name is None:
                return
            new_value = field_widget.text()
            account_id = self.current_account_id

            def _save(acc_id: int, field_name_: str, value: str) -> None:
                account = self.db_manager.get_account_by_id(acc_id)
                if not account:
                    raise RuntimeError("الحساب غير موجود.")
                updated = dict(account)
                updated[field_name_] = value
                if field_name_ == "points" and value != account.get("points"):
                    updated["points_last_modified"] = datetime.now(timezone.utc).isoformat()
                    try:
                        self.db_manager.record_point_change(
                            acc_id, account.get("name", ""),
                            account.get("points") or "0", value,
                        )
                    except Exception as exc:
                        logger.warning("Failed to record point history: {}", exc)
                self.db_manager.update_account(acc_id, updated)

            def _done(_result) -> None:
                self.statusBar().showMessage(f"تم تحديث الحقل '{field_name}' بنجاح!", 3000)
                # Selection is restored inside filter_accounts; the
                # selectionChanged signal then refreshes the details pane.
                self.filter_accounts(self._active_filter, select_id=self.current_account_id)
                if field_name == "points":
                    self._load_point_history()
                    self._refresh_dashboard_stats()

            def _fail(exc: str) -> None:
                logger.error("Error saving field {}: {}", field_name, exc)
                self.statusBar().showMessage(f"❌ خطأ: {str(exc)[:50]}...", 5000)
                if hasattr(field_widget, "_original_value"):
                    field_widget.setText(field_widget._original_value)
                field_widget.restore_readonly()

            # Read-modify-write of the account row runs off the GUI thread.
            run_task(_save, _done, _fail, account_id, field_name, new_value)
        except Exception as exc:
            logger.error("Error saving field: {}", exc)
            self.statusBar().showMessage(f"❌ خطأ: {str(exc)[:50]}...", 5000)
            if hasattr(field_widget, "_original_value"):
                field_widget.setText(field_widget._original_value)
            field_widget.restore_readonly()

    def _save_notes_field(self, field_widget: Optional["FieldLineEdit"] = None) -> None:
        notes = field_widget if field_widget is not None else self.notes_field
        if notes.isReadOnly():
            return
        notes.restore_readonly()
        if not self.current_account_id:
            self.statusBar().showMessage("❌ خطأ: لم يتم تحديد حساب.", 5000)
            return
        account_id = self.current_account_id
        notes_text = notes.text()

        def _save() -> None:
            account = self.db_manager.get_account_by_id(account_id)
            if account:
                updated = dict(account)
                updated["notes"] = notes_text
                self.db_manager.update_account(account_id, updated)

        def _done(_result) -> None:
            self.statusBar().showMessage("✅ تم حفظ الملاحظات.", 3000)

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"❌ خطأ في حفظ الملاحظات: {exc}", 5000)

        # Read-modify-write of the account row runs off the GUI thread.
        run_task(_save, _done, _fail)

    def _tell_ai_copy(self) -> None:
        name_key = "How am I"

        def _load() -> str:
            details_html = self.db_manager.get_survey_details(name_key) or ""
            return html_to_text(details_html)

        def _done(text) -> None:
            QApplication.clipboard().setText(text)
            try:
                if hasattr(self, "tell_ai_btn") and self.tell_ai_btn is not None:
                    self._show_toast("تم النسخ!", self.tell_ai_btn)
                else:
                    self.statusBar().showMessage("✅ تم نسخ التفاصيل إلى الحافظة.", 3000)
            except Exception:
                self.statusBar().showMessage("✅ تم نسخ التفاصيل إلى الحافظة.", 3000)

        run_task(_load, _done)


    def _on_tab_changed(self, index: int) -> None:
        tab_text = self.tab_widget.tabText(index)
        if tab_text == "🔧 إعدادات البروكسي":
            self._load_proxy_config_into_ui()
        elif tab_text == "🗑️ حذف حساب":
            self._populate_delete_list()

    def _load_proxy_config_into_ui(self) -> None:
        last = self.db_manager.get_last_proxy_config()
        source_note = ""
        if not last:
            # Fallback source: proxy_config.json written beside the app.
            # Lets a fresh install (or a restored folder without the DB) pick up
            # the last known proxy instead of presenting an empty form.
            file_cfg = read_proxy_config_file()
            if file_cfg:
                last = dict(file_cfg)
                source_note = (f"ℹ️ تم تحميل التكوين من الملف {PROXY_CONFIG_FILE.name} "
                               "(قاعدة البيانات فارغة) — اضغط حفظ لاعتماده.")
        if last:
            for k in ("ip", "port", "username", "password"):
                self.proxy_inputs[k].setText(last.get(k) or "")
            # Regenerate the canonical JSON from the fields so the display
            # always matches the FoxyProxy format this app writes.
            try:
                self.json_display.setText(generate_foxyproxy_json(
                    last.get("ip") or "", int(last.get("port") or 0),
                    last.get("username") or "", last.get("password") or ""))
            except (ValueError, TypeError):
                self.json_display.setText(last.get("config_json") or "")
            self.proxy_original_values = {k: last.get(k, "") or "" for k in ("ip", "port", "username", "password")}
            self.proxy_unsaved_changes = False
            self._update_proxy_field_styles()
            self._set_proxy_status(source_note)
        else:
            for f in self.proxy_inputs.values():
                f.clear()
            self.json_display.clear()
            self.proxy_original_values = {}
            self.proxy_unsaved_changes = False
            self._set_proxy_status("")

    def _set_proxy_status(self, message: str) -> None:
        """Show the inline status pill only when it has something to say."""
        self.proxy_status_label.setText(message)
        self.proxy_status_label.setVisible(bool(message))

    def _on_proxy_field_changed(self) -> None:
        if not self.proxy_original_values:
            current = {k: w.text() for k, w in self.proxy_inputs.items()}
            self.proxy_unsaved_changes = any(current.values())
        else:
            current = {k: w.text() for k, w in self.proxy_inputs.items()}
            self.proxy_unsaved_changes = current != self.proxy_original_values
        self._update_proxy_field_styles()
        self._set_proxy_status("⚠️ توجد تغييرات غير محفوظة. اضغط حفظ." if self.proxy_unsaved_changes else "")

    def _update_proxy_field_styles(self) -> None:
        for key, widget in self.proxy_inputs.items():
            if key in self.proxy_original_values and widget.text() != self.proxy_original_values[key]:
                # Danger tokens — same palette the QSS theme uses.
                widget.setStyleSheet(
                    f"border: 1px solid {_QSS_DANGER}; background-color: {_QSS_DANGER_SOFT};")
            else:
                widget.setStyleSheet("")

    def _save_proxy_config(self) -> None:
        ip = self.proxy_inputs["ip"].text()
        port = self.proxy_inputs["port"].text()
        username = self.proxy_inputs["username"].text()
        password = self.proxy_inputs["password"].text()
        if not all([ip, port, username, password]):
            self.statusBar().showMessage("❌ يجب ملء جميع حقول البروكسي.", 5000)
            return
        try:
            port_num = int(port)
        except ValueError:
            self.statusBar().showMessage("❌ خطأ: يجب أن يكون المنفذ رقمًا.", 5000)
            return
        try:
            json_str = generate_foxyproxy_json(ip, port_num, username, password)
        except Exception as exc:
            self.statusBar().showMessage(f"❌ خطأ في توليد JSON: {exc}", 5000)
            return
        self.json_display.setText(json_str)

        def _write() -> str:
            # 1) Database stays the authoritative store.
            self.db_manager.save_proxy_config(ip, port, username, password, json_str)
            # 2) Export the FoxyProxy-importable file beside the app. The DB
            #    row survives even when the file write fails, so the file is
            #    best-effort and its failure is reported in the status bar.
            try:
                return str(write_proxy_config_file(json_str))
            except Exception as exc:
                logger.warning("Could not write {}: {}", PROXY_CONFIG_FILE.name, exc)
                return ""

        def _done(file_path: str) -> None:
            if file_path:
                self.statusBar().showMessage(
                    f"✅ تم حفظ تكوين البروكسي وتحديث الملف {Path(file_path).name}.", 4000)
            else:
                self.statusBar().showMessage(
                    "✅ تم حفظ تكوين البروكسي في قاعدة البيانات (تعذّر كتابة الملف).", 4000)
            self.proxy_original_values = {k: self.proxy_inputs[k].text() for k in ("ip", "port", "username", "password")}
            self.proxy_unsaved_changes = False
            self._update_proxy_field_styles()
            self._set_proxy_status("")

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"❌ خطأ في حفظ البروكسي: {exc}", 5000)

        run_task(_write, _done, _fail, busy_button=self.save_proxy_btn,
                 status_bar=self.statusBar(),
                 status_message="💾 جارٍ حفظ تكوين البروكسي...")

    # ------------------------------------------------------------------
    # UPDATE CHECKER — check, offer, download, swap, restart
    # ------------------------------------------------------------------
    def _load_auto_update_pref(self) -> bool:
        try:
            raw = self.db_manager.get_setting(UPDATE_PREF_KEY, "1")
        except Exception:
            raw = "1"
        return str(raw) not in ("0", "false", "False")

    def _set_auto_update_pref(self, checked: bool) -> None:
        self._auto_update_pref = bool(checked)
        try:
            self.db_manager.set_setting(UPDATE_PREF_KEY, "1" if checked else "0")
        except Exception as exc:
            logger.warning("Could not persist update-check preference: {}", exc)

    def _check_for_updates(self, manual: bool = False) -> None:
        """Fetch the update manifest on a worker thread.

        manual=True  → always report the outcome, even "you are up to date".
        manual=False → completely silent unless a newer version is offered.
        """
        if self._update_check_in_flight:
            return
        self._update_check_in_flight = True

        def _done(result: object) -> None:
            self._update_check_in_flight = False
            if not isinstance(result, dict):
                if manual:
                    self.statusBar().showMessage("ℹ️ لا توجد معلومات تحديث صالحة.", 4000)
                return
            remote = str(result.get("version", "")).strip()
            if not is_newer_version(remote):
                if manual:
                    self.statusBar().showMessage(
                        f"✅ أنت تستخدم أحدث إصدار (v{APP_VERSION}).", 4000)
                return
            self._offer_update(result)

        def _fail(err: str) -> None:
            self._update_check_in_flight = False
            if manual:
                QMessageBox.warning(
                    self, "فحص التحديثات",
                    f"تعذّر التحقق من التحديثات:\n{err}")
            else:
                logger.info("Startup update check skipped: {}", err)

        run_task(fetch_update_manifest, _done, _fail,
                 status_bar=self.statusBar() if manual else None,
                 status_message="🔄 جارٍ التحقق من التحديثات..." if manual else "")

    def _offer_update(self, manifest: Dict[str, Any]) -> None:
        """Ask التثبيت الآن / لاحقاً (RTL dialog) and start install on accept."""
        if UpdateAvailableDialog(manifest, self).exec_() == QDialog.Accepted:
            self._install_update(manifest)

    def _install_update(self, manifest: Dict[str, Any]) -> None:
        """Download + verify the new script, then offer an immediate restart.

        The swap itself (apply_self_update) happens ONLY after the user
        picks "إعادة التشغيل الآن" — until then the running code and every
        file beside it remain exactly as they were.
        """
        remote = str(manifest.get("version", "?")).strip() or "?"
        if self._update_check_in_flight:
            return
        self._update_check_in_flight = True

        def _done(staged: object) -> None:
            self._update_check_in_flight = False
            staged_path = Path(staged)
            self.statusBar().showMessage("✅ تم تنزيل التحديث والتحقق منه.", 4000)
            box = QMessageBox(self)
            box.setWindowTitle("التحديث جاهز")
            box.setLayoutDirection(Qt.RightToLeft)
            box.setIcon(QMessageBox.Question)
            box.setText(
                f"تم تنزيل الإصدار v{remote} والتحقق منه بنجاح.\n\n"
                "هل تريد إعادة التشغيل الآن لتطبيق التحديث؟\n"
                f"(سيتم الاحتفاظ بنسخة احتياطية من الإصدار الحالي v{APP_VERSION} "
                "بجانب البرنامج)")
            restart_btn = box.addButton("إعادة التشغيل الآن", QMessageBox.AcceptRole)
            box.addButton("لاحقاً", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is restart_btn:
                try:
                    apply_self_update(staged_path)
                except Exception as exc:
                    logger.opt(exception=True).error("Update swap failed: {}", exc)
                    QMessageBox.critical(
                        self, "فشل التثبيت",
                        f"تعذّر استبدال ملف البرنامج:\n{exc}\n\nلم يتم تعديل أي ملف.")
                    return
                if restart_application():
                    # النسخة الجديدة تعمل الآن — نغلق هذه النسخة بنفس مسار
                    # الإغلاق الطبيعي (يوقف الخيوط ويغلق قاعدة البيانات).
                    self.close()
                else:
                    # التثبيت نجح لكن التشغيل التلقائي فشل — لا خسارة: يكفي
                    # أن يشغّل المستخدم البرنامج يدوياً مرة أخرى.
                    QMessageBox.information(
                        self, "تم تثبيت التحديث",
                        "تم تثبيت الإصدار الجديد بنجاح ✅\n\n"
                        "تعذّر بدء التشغيل التلقائي — الرجاء إغلاق البرنامج "
                        "وتشغيله مرة أخرى يدوياً لتطبيق التحديث.")
                    self.close()
            else:
                # Declined restart: discard the staged file so state stays
                # trivial; the update is simply offered again on next check.
                try:
                    staged_path.unlink(missing_ok=True)
                except OSError:
                    pass
                self.statusBar().showMessage(
                    "ℹ️ سيُعرض التحديث مرة أخرى عند التحقق التالي.", 4000)

        def _fail(err: str) -> None:
            self._update_check_in_flight = False
            QMessageBox.critical(
                self, "فشل التحديث",
                f"تعذّر تنزيل التحديث:\n{err}\n\nلم يتم تعديل أي ملف.")

        run_task(download_and_stage_update, _done, _fail, manifest,
                 status_bar=self.statusBar(),
                 status_message=f"⬇️ جارٍ تنزيل الإصدار v{remote}...")

    # ------------------------------------------------------------------
    # المزامنة السحابية (Supabase) — v6.6
    # ------------------------------------------------------------------
    def _load_auto_sync_pref(self) -> bool:
        return (self.db_manager.get_setting(SYNC_PREF_KEY, "1") or "1") == "1"

    def _set_auto_sync_pref(self, enabled: bool) -> None:
        self._auto_sync_pref = bool(enabled)
        self.db_manager.set_setting(SYNC_PREF_KEY, "1" if enabled else "0")

    def _open_cloud_sync_dialog(self) -> None:
        dlg = CloudSyncDialog(self)
        self._sync_dialog_ref = dlg
        dlg.exec_()
        if self._sync_dialog_ref is dlg:
            self._sync_dialog_ref = None

    def _sync_dialog(self) -> Optional[CloudSyncDialog]:
        """الحوار المفتوح حاليًا فقط (يُتجاهل إن أُغلق)."""
        dlg = self._sync_dialog_ref
        if dlg is not None and dlg.isVisible():
            return dlg
        return None

    def _clear_sync_session(self) -> None:
        for key in (SYNC_REFRESH_TOKEN_KEY, SYNC_USER_ID_KEY, SYNC_USER_EMAIL_KEY):
            try:
                self.db_manager.set_setting(key, "")
            except Exception:
                logger.warning("Failed to clear setting {}", key)

    def _cloud_login_and_sync_worker(self, email: str, password: str) -> Dict[str, Any]:
        """(خيط خلفية) تسجيل دخول ثم مزامنة كاملة بجلسة الدخول الطازجة."""
        session = sync_sign_in(email, password)
        return run_cloud_sync(self.db_manager, session["refresh_token"], session=session)

    def _do_cloud_login(self, dialog: CloudSyncDialog, email: str, password: str) -> None:
        if self._sync_in_flight:
            return
        if not (email or "").strip() or not password:
            dialog.set_status("⚠️ أدخل البريد الإلكتروني وكلمة المرور أولًا.")
            return
        self._sync_in_flight = True
        dialog.set_busy(True, "🔐 جارٍ تسجيل الدخول والمزامنة الأولى...")
        run_task(self._cloud_login_and_sync_worker,
                 lambda res: self._cloud_sync_done(res, True),
                 lambda err: self._cloud_sync_fail(err, True),
                 email.strip(), password)

    def _run_cloud_sync(self, dialog: Optional[CloudSyncDialog] = None,
                        manual: bool = True) -> None:
        if self._sync_in_flight:
            if manual:
                self.statusBar().showMessage("ℹ️ توجد مزامنة قيد التنفيذ بالفعل.", 3000)
            return
        if not _sync_configured():
            if manual:
                QMessageBox.information(
                    self, "المزامنة السحابية",
                    "المزامنة غير مُفعّلة في هذه النسخة.\n\n"
                    "ضع Project URL و anon key في ثوابت SUPABASE أعلى ملف البرنامج "
                    "(الشرح في التعليقات فوقها ونافذة المزامنة نفسها).")
            return
        refresh_token = self.db_manager.get_setting(SYNC_REFRESH_TOKEN_KEY, "") or ""
        if not refresh_token:
            if manual:
                QMessageBox.information(
                    self, "المزامنة السحابية",
                    "لا توجد جلسة مسجّلة على هذا الجهاز.\n\n"
                    "افتح: ملف → ☁️ المزامنة السحابية وسجّل الدخول مرة واحدة.")
            else:
                logger.info("Auto-sync skipped: no saved session")
            return
        self._sync_in_flight = True
        if dialog is not None:
            dialog.set_busy(True, "🔄 جارٍ المزامنة مع السحابة...")
        run_task(run_cloud_sync,
                 lambda res: self._cloud_sync_done(res, manual),
                 lambda err: self._cloud_sync_fail(err, manual),
                 self.db_manager, refresh_token)

    def _auto_cloud_sync(self) -> None:
        """مزامنة صامتة عند الإقلاع — فقط مع جلسة محفوظة وثوابت مضبوطة."""
        if not self._auto_sync_pref:
            return
        if not _sync_configured():
            return
        if not (self.db_manager.get_setting(SYNC_REFRESH_TOKEN_KEY, "") or ""):
            return
        self._run_cloud_sync(dialog=None, manual=False)

    def _cloud_sync_done(self, result: object, manual: bool) -> None:
        self._sync_in_flight = False
        if not isinstance(result, dict):
            if manual:
                self.statusBar().showMessage("ℹ️ لم تُعد المزامنة أي نتيجة صالحة.", 4000)
            return
        try:
            self.db_manager.set_setting(SYNC_REFRESH_TOKEN_KEY, result.get("refresh_token") or "")
            self.db_manager.set_setting(SYNC_USER_ID_KEY, result.get("user_id") or "")
            if result.get("email"):
                self.db_manager.set_setting(SYNC_USER_EMAIL_KEY, result["email"])
            self.db_manager.set_setting(SYNC_LAST_TIME_KEY, result.get("finished_at") or _utc_now_iso())
        except Exception:
            logger.opt(exception=True).warning("Failed to persist sync session state")
        # أظهر الصفوف الواردة من السحابة فورًا في الجدول والإحصاءات
        try:
            self.filter_accounts()
            self._refresh_dashboard_stats()
        except Exception:
            logger.opt(exception=True).warning("Post-sync UI refresh failed")
        msg = (f"☁️ تمت المزامنة: تحديث على الجهاز {result.get('applied_local', 0)}، "
               f"رفع للسحابة {result.get('pushed', 0)}"
               + (f"، تجاهُل {result.get('skipped_local', 0)}" if result.get("skipped_local") else "")
               + ".")
        self.statusBar().showMessage(msg, 6000 if manual else 4000)
        dlg = self._sync_dialog()
        if dlg is not None:
            dlg.set_busy(False)
            dlg.refresh_state()
            dlg.set_status("✅ " + msg)

    def _cloud_sync_fail(self, err: str, manual: bool) -> None:
        self._sync_in_flight = False
        # جلسة منتهية؟ امسح الجلسة المحفوظة حتى تظهر شاشة الدخول من جديد
        if ("سجّل الدخول" in err) or ("انتهت صلاحية الجلسة" in err) or ("غير صحيحة" in err):
            self._clear_sync_session()
        self.statusBar().showMessage(f"☁️ المزامنة السحابية: {err}", 8000 if manual else 4000)
        logger.warning("Cloud sync failed: {}", err)
        dlg = self._sync_dialog()
        if dlg is not None:
            dlg.set_busy(False)
            dlg.refresh_state()
            dlg.set_status("❌ " + err)

    def _cloud_logout(self, dialog: Optional[CloudSyncDialog] = None) -> None:
        """تسجيل الخروج يمسح جلسة هذا الجهاز فقط — البيانات المحلية والسحابية تبقى كما هي."""
        self._clear_sync_session()
        self.statusBar().showMessage(
            "☁️ تم تسجيل الخروج من هذا الجهاز (بياناتك المحلية والسحابية بقيت كما هي).", 5000)
        if dialog is not None:
            dialog.refresh_state()
            dialog.set_status("تم تسجيل الخروج. بياناتك المحلية محفوظة بالكامل، "
                              "ويمكنك تسجيل الدخول مجددًا في أي وقت.")

    def _stop_thread_safely(self, thread_obj: Optional[QThread]) -> None:
        """Stop a helper QThread so it is never destroyed while still running.

        quit() asks the thread's event loop to exit; wait() gives it a grace
        period; terminate() is the last resort for a worker stuck in a network
        call (both workers carry httpx timeouts, so this is rarely reached).
        """
        if thread_obj is None:
            return
        try:
            if not thread_obj.isRunning():
                return
            thread_obj.quit()
            if not thread_obj.wait(1500):
                thread_obj.terminate()
                thread_obj.wait(500)
        except RuntimeError:
            pass  # wrapper already deleted by a finished deleteLater
        except Exception:
            pass

    def _check_proxy_ip(self) -> None:
        try:
            last = self.db_manager.get_last_proxy_config()
        except Exception:
            return
        if not last:
            self.statusBar().showMessage("❌ لم يتم العثور على تكوين بروكسي. يرجى حفظ واحد في تبويب إعدادات البروكسي.", 5000)
            return
        ip, port, username, password = last["ip"], last["port"], last["username"], last["password"]
        if not all([ip, port, username, password]):
            self.statusBar().showMessage("❌ يجب ملء جميع حقول البروكسي.", 5000)
            return
        try:
            self.check_proxy_ip_btn.setEnabled(False)

        except Exception:
            pass
        self._proxy_retry_count = 0
        self._start_proxy_check(ip, port, username, password)

    def _start_proxy_check(self, ip: str, port: str, user: str, pw: str) -> None:
        if self._closing:
            return
        self._last_proxy_for_check = (ip, port, user, pw)
        # A retry replaces the previous thread — stop it first so it can
        # never be destroyed while still running.
        self._stop_thread_safely(self._thread)
        self._thread = QThread(self)
        self._worker = ProxyCheckWorker(ip, port, user, pw)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_proxy_success)
        self._worker.error.connect(self._on_proxy_error)
        # BOTH outcomes must stop the event loop — previously the thread kept
        # running after an error, causing "QThread: Destroyed while thread is
        # still running" when it was later deleted or replaced.
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_proxy_success(self, new_ip: str) -> None:
        self._proxy_retry_count = 0
        self.ip_after_field.setText(new_ip)
        self.statusBar().showMessage("✅ تم جلب IP البروكسي بنجاح.", 5000)
        try:
            self.check_proxy_ip_btn.setEnabled(True)
        except Exception:
            pass

    def _on_proxy_error(self, error_msg: str) -> None:
        try:
            self.check_proxy_ip_btn.setEnabled(True)
        except Exception:
            pass
        display = "انتهت مهلة الاتصال بالبروكسي" if "انتهت مهلة" in error_msg else error_msg
        if self._proxy_retry_count < PROXY_MAX_RETRIES:
            self._proxy_retry_count += 1
            self.statusBar().showMessage(
                f"❌ خطأ: {display} — إعادة المحاولة ({self._proxy_retry_count}/{PROXY_MAX_RETRIES})...", 5000
            )
            QTimer.singleShot(PROXY_RETRY_DELAY_MS, self._retry_proxy_check)
        else:
            self.statusBar().showMessage(f"❌ خطأ في فحص البروكسي: {display}", 7000)

    def _retry_proxy_check(self) -> None:
        if self._closing:
            return  # window is closing — don't start a new check
        last = self._last_proxy_for_check
        if not last:
            return
        self._start_proxy_check(*last)

    # ------------------------------------------------------------------
    # GEO LOOKUP (ip2location.io through the active proxy)
    # ------------------------------------------------------------------

    def _open_geo_dialog(self) -> None:
        try:
            last = self.db_manager.get_last_proxy_config()
        except Exception:
            return
        if not last:
            self.statusBar().showMessage("❌ لم يتم العثور على تكوين بروكسي. يرجى حفظ واحد في إعدادات البروكسي.", 5000)
            return
        ip, port, username, password = last["ip"], last["port"], last["username"], last["password"]
        if not all([ip, port, username, password]):
            self.statusBar().showMessage("❌ يجب ملء جميع حقول البروكسي.", 5000)
            return
        try:
            self.geo_ip_btn.setEnabled(False)
        except Exception:
            pass
        self.statusBar().showMessage("🌍 جاري الاستعلام عن موقع البروكسي عبر ip2location.io...", 5000)
        self._start_geo_lookup(ip, port, username, password)

    def _start_geo_lookup(self, ip: str, port: str, user: str, pw: str) -> None:
        if self._closing:
            return
        # Stop any previous lookup thread so it is never destroyed running.
        self._stop_thread_safely(self._geo_thread)
        self._geo_thread = QThread(self)
        self._geo_worker = GeoLookupWorker(ip, port, user, pw)
        self._geo_worker.moveToThread(self._geo_thread)
        self._geo_thread.started.connect(self._geo_worker.run)
        self._geo_worker.finished.connect(self._on_geo_success)
        self._geo_worker.error.connect(self._on_geo_error)
        # BOTH outcomes must stop the event loop (see _start_proxy_check).
        self._geo_worker.finished.connect(self._geo_thread.quit)
        self._geo_worker.error.connect(self._geo_thread.quit)
        self._geo_worker.finished.connect(self._geo_worker.deleteLater)
        self._geo_worker.error.connect(self._geo_worker.deleteLater)
        self._geo_thread.finished.connect(self._geo_thread.deleteLater)
        self._geo_thread.start()

    def _on_geo_success(self, data: Dict[str, Any]) -> None:
        try:
            self.geo_ip_btn.setEnabled(True)
        except Exception:
            pass
        self.statusBar().showMessage(f"✅ تم جلب الموقع الجغرافي للبروكسي ({data.get('ip', '')}).", 5000)
        try:
            dlg = GeoTimezoneDialog(data, self)
            dlg.exec_()
        except Exception as exc:
            self.statusBar().showMessage(f"❌ خطأ في عرض نتائج الموقع: {exc}", 7000)

    def _on_geo_error(self, error_msg: str) -> None:
        try:
            self.geo_ip_btn.setEnabled(True)
        except Exception:
            pass
        display = "انتهت مهلة الاتصال بالبروكسي" if "انتهت مهلة" in error_msg else error_msg
        self.statusBar().showMessage(f"❌ خطأ في الاستعلام عن الموقع: {display}", 7000)

    def _on_spin_changed(self, new_value: int) -> None:
        if not self._countdown_running:
            self.countdown_remaining = max(0, int(new_value))
            self._update_timer_label()

    def _start_countdown(self) -> None:
        if self._countdown_running:
            self.statusBar().showMessage("العدّ التنازلي جارٍ بالفعل.", 2000)
            return
        val = self.spin_seconds.value()
        self.countdown_remaining = val if val > 0 else self.countdown_remaining or DEFAULT_COUNTDOWN_SEC
        self._update_timer_label()
        self.countdown_timer.start()
        self._countdown_running = True
        self._auto_repeat = True
        self.statusBar().showMessage("▶️ بدأ العدّ التنازلي.", 2000)

    def _stop_countdown(self) -> None:
        if not self._countdown_running:
            self.statusBar().showMessage("العدّ التنازلي غير جارٍ.", 2000)
            return
        self.countdown_timer.stop()
        self._countdown_running = False
        self._auto_repeat = False
        self.statusBar().showMessage("⏸ تم إيقاف العدّ مؤقتًا.", 2000)

    def _on_countdown_tick(self) -> None:
        if self.countdown_remaining > 0:
            self.countdown_remaining -= 1
            self._update_timer_label()
            if self.countdown_remaining == 0:
                try:
                    self.countdown_timer.stop()
                    self._check_proxy_ip()
                except Exception:
                    logger.exception("Error during countdown completion.")
                if self._auto_repeat:
                    val = self.spin_seconds.value()
                    self.countdown_remaining = val if val > 0 else DEFAULT_COUNTDOWN_SEC
                    self._update_timer_label()
                    self.countdown_timer.start()
                else:
                    self._countdown_running = False
        else:
            self.countdown_timer.stop()
            self._countdown_running = False
            self._auto_repeat = False
            self._update_timer_label()

    def _update_timer_label(self) -> None:
        self.timer_label.setText(f"{max(0, self.countdown_remaining):02d}s")

    def _check_ip_match(self) -> None:
        before = self.ip_before_field.text().strip()
        after = self.ip_after_field.text().strip()
        # Soft green tint = the two IPs match; anything else falls back to
        # the QSS card look (empty string clears any previous tint).
        match_style = f"background-color: {_QSS_SUCCESS_SOFT}; font-weight: 700;"
        default_style = ""
        differ = bool(before and after and before != after)
        if differ and not self._ip_mismatch_alerted:
            # Fire the whistle ONCE per mismatch episode. textChanged fires on
            # every keystroke/fetch — playing each time stacked multiple
            # overlapping whistles that sounded broken/garbled.
            self._ip_mismatch_alerted = True
            play_alert_sound(self._alert_sound)
        elif not differ:
            # Mismatch resolved (or a field was cleared) — re-arm the alert.
            self._ip_mismatch_alerted = False
        if differ:
            self.ip_before_field.setStyleSheet(default_style)
            self.ip_after_field.setStyleSheet(default_style)
        elif before and after and before == after:
            self.ip_before_field.setStyleSheet(match_style)
            self.ip_after_field.setStyleSheet(match_style)
        else:
            self.ip_before_field.setStyleSheet(default_style)
            self.ip_after_field.setStyleSheet(default_style)
        self.update_firefox_button_state()

    def _update_before_ip(self) -> None:
        after = self.ip_after_field.text().strip()
        if not after:
            self.statusBar().showMessage("❌ IP 'بعد' فارغ.", 5000)
            return
        self.ip_before_field.setText(after)
        self.ip_after_field.setText("")
        # The "before" IP lives in the settings table (key="ip_before") so it
        # is backed up together with the rest of the app data — no loose
        # .txt file next to the script anymore.
        try:
            self.db_manager.set_setting("ip_before", after)
            self.statusBar().showMessage("✅ تم تحديث IP السابق.", 3000)
        except Exception as exc:
            logger.error("Error saving IP: {}", exc)
            self.statusBar().showMessage(f"❌ خطأ في حفظ IP: {exc}", 5000)

    def _load_ip_before(self) -> None:
        try:
            saved_ip = self.db_manager.get_setting("ip_before", "")
            if saved_ip:
                self.ip_before_field.setText(saved_ip)
        except Exception as exc:
            logger.error("Error loading IP: {}", exc)

    def update_firefox_button_state(self) -> None:
        before = self.ip_before_field.text().strip()
        after = self.ip_after_field.text().strip()
        ff_running = self._firefox_running_cached
        if before and after and before != after:
            self.firefox_btn.setEnabled(not ff_running)
        elif before and after and before == after:
            self.firefox_btn.setEnabled(ff_running)
        else:
            self.firefox_btn.setEnabled(True)

    def _check_firefox_status(self) -> None:
        # Runs every FIREFOX_CHECK_INTERVAL_MS. Never block the GUI thread with
        # the `tasklist` subprocess — poll it on the worker pool instead and
        # guard against overlapping checks.
        if self._firefox_check_in_flight or self._closing:
            return
        self._firefox_check_in_flight = True

        def _done(running) -> None:
            self._firefox_check_in_flight = False
            if running != self._firefox_running_cached:
                self._firefox_running_cached = running
                logger.debug("Firefox running status changed: {}", running)
            self.update_firefox_button_state()

        def _fail(_err: str) -> None:
            self._firefox_check_in_flight = False
            self.update_firefox_button_state()

        run_task(is_firefox_running, _done, _fail)

    def run_firefox(self, private: bool = False) -> None:
        if self._firefox_launch_in_progress:
            self.statusBar().showMessage("⏳ جارٍ فتح Firefox...", 3000)
            return
        self._firefox_launch_in_progress = True
        account_id = self.current_account_id
        try:
            self.firefox_btn.setEnabled(False)
            self.firefox_private_btn.setEnabled(False)
        except Exception:
            pass

        def _prep(acc_id: Optional[int]) -> Tuple[Optional[str], Optional[str]]:
            # The blocking `firefox --version` probe + DB read run off the GUI
            # thread; the resolved path is cached for later launches.
            path = self._firefox_exec_cache
            if path is None:
                path = find_firefox_executable()
                self._firefox_exec_cache = path
            profile: Optional[str] = None
            if acc_id:
                account = self.db_manager.get_account_by_id(acc_id)
                if account:
                    profile = account.get("name")
            return path, profile

        def _done(result) -> None:
            self._firefox_launch_in_progress = False
            try:
                self.firefox_private_btn.setEnabled(True)
            except Exception:
                pass
            self.update_firefox_button_state()
            firefox_path, profile_name = result
            if not firefox_path:
                QMessageBox.critical(self, "Error", "Firefox executable not found. Please ensure it's installed.")
                return
            try:
                if profile_name:
                    safe_profile = _sanitize(profile_name)
                    cmd = [firefox_path, "-P", safe_profile]
                    if private:
                        cmd.append("--private-window")
                    subprocess.Popen(cmd)
                    mode_str = "التصفح الخفي" if private else ""
                    self.statusBar().showMessage(f"✅ Running Firefox {mode_str}بملف التعريف '{safe_profile}'...", 3000)
                else:
                    # No account selected: just open Firefox's currently
                    # selected/default profile in private browsing —
                    # no profile-name prompt.
                    cmd = [firefox_path]
                    if private:
                        cmd.append("--private-window")
                    subprocess.Popen(cmd)
                    mode_str = "التصفح الخفي" if private else ""
                    self.statusBar().showMessage(f"✅ تم فتح Firefox {mode_str} بالملف الشخصي الافتراضي...", 3000)
            except Exception as exc:
                self.statusBar().showMessage(f"❌ Error: {exc}", 5000)

        def _fail(err: str) -> None:
            self._firefox_launch_in_progress = False
            try:
                self.firefox_private_btn.setEnabled(True)
            except Exception:
                pass
            self.update_firefox_button_state()
            self.statusBar().showMessage(f"❌ خطأ في تشغيل Firefox: {err}", 5000)

        run_task(_prep, _done, _fail, account_id,
                 status_bar=self.statusBar(),
                 status_message="🔍 جارٍ البحث عن Firefox...")

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        sender = self.sender()
        if sender:
            self._show_toast("📋 تم النسخ!", sender)
        else:
            self.statusBar().showMessage("✅ تم نسخ النص إلى الحافظة!", 2000)

    def _show_toast(self, message: str, target_widget: QWidget) -> None:
        container = QWidget(self)
        container.setAttribute(Qt.WA_TranslucentBackground)
        container.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        toast = QLabel(message, container)
        toast.setLayoutDirection(Qt.RightToLeft)
        shadow = QGraphicsDropShadowEffect(toast)
        shadow.setOffset(0, 2)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 120))
        toast.setGraphicsEffect(shadow)
        toast.adjustSize()
        container.setFixedSize(toast.size())
        opacity = QGraphicsOpacityEffect(container)
        container.setGraphicsEffect(opacity)
        target_pos = target_widget.mapTo(self, target_widget.rect().topLeft())
        x = target_pos.x() + (target_widget.width() - container.width()) / 2
        y = target_pos.y() - container.height() + 5
        container.move(int(x), int(y))
        anim = QPropertyAnimation(opacity, b"opacity")
        anim.setDuration(1000)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setParent(container)
        anim.finished.connect(container.deleteLater)
        container.show()
        QTimer.singleShot(800, anim.start)

    def _load_addon_links(self) -> List[str]:
        try:
            return self.db_manager.get_addon_links(len(DEFAULT_ADDONS))
        except Exception as exc:
            logger.error("Error loading addons: {}", exc)
        return []

    def _save_addon_value(self, index: int, value: str) -> None:
        try:
            self.db_manager.set_addon_link(index, value)
            self.statusBar().showMessage(f"✅ تم حفظ الإضافة {index}", 3000)
        except Exception as exc:
            logger.error("Error saving addon {}: {}", index, exc)
            self.statusBar().showMessage(f"❌ خطأ في حفظ الإضافة {index}: {exc}", 5000)

    def _refresh_categories_list(self) -> None:
        def _done(cats) -> None:
            self.categories_list.clear()
            for cat in cats:
                self.categories_list.addItem(cat)
        run_task(self.db_manager.get_all_categories, _done)
        self._update_category_counts()

    def _refresh_category_combo(self) -> None:
        def _done(cats) -> None:
            self.delete_category_combo.clear()
            self.delete_category_combo.addItems(cats)
        run_task(self.db_manager.get_all_categories, _done)

    def _update_category_counts(self) -> None:
        def _build() -> str:
            counts = self.db_manager.get_category_counts()
            text = "عدد الحسابات لكل فئة:\n"
            for cat in self.db_manager.get_all_categories():
                text += f"{cat}: {counts.get(cat, 0)}\n"
            return text

        def _done(text) -> None:
            if hasattr(self, "cat_counts_label"):
                self.cat_counts_label.setText(text)

        run_task(_build, _done)

    def _add_category(self) -> None:
        name = self.new_category_input.text().strip()
        if not name:
            QMessageBox.warning(self, "خطأ", "الرجاء إدخال اسم الفئة.")
            return

        def _done(added) -> None:
            if added:
                self.statusBar().showMessage(f"✅ تمت إضافة الفئة '{name}'.", 3000)
                self.new_category_input.clear()
                self._refresh_categories_list()
                self._refresh_category_combo()
                self._update_category_checkboxes()
            else:
                QMessageBox.warning(self, "خطأ", "الفئة موجودة بالفعل.")

        run_task(self.db_manager.add_category, _done, None, name)

    def _delete_category(self) -> None:
        cat = self.delete_category_combo.currentText()
        if not cat or cat == DEFAULT_CATEGORY:
            if cat:
                QMessageBox.warning(self, "لا يمكن الحذف", "لا يمكن حذف هذه الفئة الافتراضية.")
            return
        reply = QMessageBox.question(
            self, "تأكيد الحذف",
            f"سيتم نقل جميع حسابات الفئة '{cat}' إلى '{DEFAULT_CATEGORY}'. هل تريد المتابعة؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def _done(deleted) -> None:
            if deleted:
                self.statusBar().showMessage(f"✅ تم حذف الفئة '{cat}'.", 3000)
                self._refresh_categories_list()
                self._refresh_category_combo()
                self._update_category_checkboxes()
                sel = self._get_selected_account_id()
                self.filter_accounts(self._active_filter, select_id=sel)

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"❌ خطأ في حذف الفئة: {exc}", 5000)

        # Category delete reassigns accounts (3 statements) off the GUI thread.
        run_task(self.db_manager.delete_category, _done, _fail, cat,
                 status_bar=self.statusBar(),
                 status_message=f"🗑️ جارٍ حذف الفئة '{cat}'...")

    def _change_password(self) -> None:
        # Available to every user (admin account is permanently disabled).
        ChangePasswordDialog(self.db_manager, self).exec_()

    def _copy_yougov_link(self) -> None:
        QApplication.clipboard().setText("https://account.yougov.com/us-en/account")
        self._show_toast("📋 تم نسخ رابط يوغوف", self.yougov_btn)

    def _copy_translate_link(self) -> None:
        """Copy the link that opens Google Translate (button "ترجمة غوغل")."""
        QApplication.clipboard().setText(GOOGLE_TRANSLATE_URL)
        self._show_toast("📋 تم نسخ رابط ترجمة غوغل", self.translate_btn)

    def _show_help_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("❓ مساعدة/شرح")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.resize(600, 400)
        layout = QVBoxLayout(dlg)
        text_area = QTextEdit()
        text_area.setHtml(
            "<h1 style='text-align: right;'>مساعدة وشرح التطبيق</h1>"
            "<h2 style='text-align: right;'>1. إدارة الحسابات</h2>"
            "<p style='text-align: right;'>تعرض اللوحة اليمنى قائمة بحساباتك. "
            "الحسابات النشطة مظللة باللون الأخضر، وغير النشطة باللون الأحمر.</p>"
            "<h2 style='text-align: right;'>2. إدارة IP</h2>"
            "<p style='text-align: right;'>اختر مدة العدّ التنازلي ثم ابدأ المؤقت.</p>"
            "<h2 style='text-align: right;'>3. الأدوات</h2>"
            "<p style='text-align: right;'>يمكنك حفظ إعدادات البروكسي وإدارة الفئات وتصدير البيانات — جميع التبويبات متاحة لكل المستخدمين.</p>"
            "<h2 style='text-align: right;'>4. تعديل الحقول</h2>"
            "<p style='text-align: right;'>انقر نقرة مزدوجة على حقل النقاط في تفاصيل الحساب لتعديله مباشرة (Enter للحفظ، Esc للإلغاء). بقية الحقول مقفلة، ولتعديلها استخدم زر «تعديل جميع تفاصيل الحساب».</p>"
        )
        text_area.setReadOnly(True)
        text_area.setLayoutDirection(Qt.RightToLeft)
        layout.addWidget(text_area)
        dlg.exec_()

    def _open_preferences_dialog(self) -> None:
        dlg = PreferencesDialog(self.font_manager, self._ui_density, self._alert_sound, self)
        if dlg.exec_() == QDialog.Accepted:
            font_size, is_bold, density, alert_sound = dlg.get_preferences()
            self.font_manager.save(font_size, is_bold)
            self.font_manager.apply_to_app()
            self._refresh_all_fonts()
            self._apply_ui_density(density)
            self._alert_sound = alert_sound or DEFAULT_ALERT_SOUND
            try:
                self.db_manager.set_setting("pref_ui_density", str(self._ui_density))
                self.db_manager.set_setting("pref_alert_sound", self._alert_sound)
            except Exception as exc:
                logger.error("Error saving preferences: {}", exc)
            self.statusBar().showMessage("✅ تم تطبيق التفضيلات بنجاح.", 3000)

    def _apply_toolbar_font(self) -> None:
        """Re-apply the centralized toolbar font after preference changes."""
        font = self.font_manager.toolbar_font()
        for attr in ("firefox_private_btn", "telegram_btn", "tell_ai_btn",
                     "copilot_btn", "yougov_btn", "translate_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setFont(font)

    def _refresh_all_fonts(self) -> None:
        """Force every already-created widget to pick up the new font size
        immediately, instead of only new widgets/after an app restart.

        QApplication.setFont() (called by font_manager.apply_to_app()) only
        changes the *default* font used for widgets that don't already have
        an explicit one — it does not retroactively repaint widgets that
        were already constructed. So we walk the whole widget tree here and
        re-apply the base font to everything, then restore the toolbar's
        slightly-larger emphasis font on top, and finally force a style
        repolish so the change is reflected on screen right away.
        """
        base_font = self.font_manager.base_font()
        self.setFont(base_font)
        for child in self.findChildren(QWidget):
            child.setFont(base_font)
        # Toolbar buttons use a larger "emphasis" size — reapply after the
        # blanket pass above so they don't end up at the base size.
        self._apply_toolbar_font()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _save_table_sort_state(self, column: int, order: Qt.SortOrder) -> None:
        try:
            self.db_manager.set_setting("table_sort_column", str(column))
            self.db_manager.set_setting("table_sort_order", str(int(order)))
        except Exception as exc:
            logger.warning("Failed to save sort state: {}", exc)

    def _restore_table_sort_state(self) -> None:
        try:
            saved_col = self.db_manager.get_setting("table_sort_column")
            saved_order = self.db_manager.get_setting("table_sort_order")
            if saved_col is not None and saved_order is not None:
                col = int(saved_col)
                order = Qt.SortOrder(int(saved_order))
                if 0 <= col < self.accounts_model.columnCount():
                    self.accounts_table.horizontalHeader().blockSignals(True)
                    self.accounts_model.sort(col, order)
                    self.accounts_table.horizontalHeader().setSortIndicator(col, order)
                    self.accounts_table.horizontalHeader().blockSignals(False)
        except Exception as exc:
            logger.warning("Failed to restore sort state: {}", exc)

    def _on_stats_filter_changed(self, index: int) -> None:
        account_id = self.stats_filter_combo.itemData(index)
        # Point-history scan runs off the GUI thread; results populate the table.
        run_task(self.db_manager.get_point_history, self._populate_stats_table,
                 None, account_id=account_id)

    def _load_point_history(self, account_id: Optional[int] = None) -> None:
        run_task(self.db_manager.get_point_history, self._populate_stats_table,
                 None, account_id=account_id)

    def _populate_stats_table(self, records: List[Dict[str, Any]]) -> None:
        table = self.stats_table
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(records))
            for row_idx, rec in enumerate(records):
                name_item = QTableWidgetItem(str(rec.get("account_name", "")))
                name_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, 0, name_item)
                old_item = QTableWidgetItem(str(rec.get("old_points", "0")))
                old_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, 1, old_item)
                new_item = QTableWidgetItem(str(rec.get("new_points", "0")))
                new_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, 2, new_item)
                change_str = str(rec.get("change_amount", "0"))
                if change_str.lower() in ("none", "null", ""):
                    change_str = "0"
                change_item = QTableWidgetItem(change_str)
                change_item.setTextAlignment(Qt.AlignCenter)
                try:
                    change_val = float(change_str)
                    if change_val > 0:
                        change_item.setForeground(QColor("#2e7d32"))
                    elif change_val < 0:
                        change_item.setForeground(QColor("#c62828"))
                except (ValueError, TypeError):
                    pass
                table.setItem(row_idx, 3, change_item)
                date_str = str(rec.get("changed_at", ""))
                if "T" in date_str:
                    date_str = date_str.replace("T", " ")[:19]
                date_item = QTableWidgetItem(date_str)
                date_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, 4, date_item)
            table.resizeColumnsToContents()
        finally:
            table.setUpdatesEnabled(True)


    def _debug_db_status(self) -> None:
        """Debug helper to show DB status in status bar (scans off the GUI thread)."""
        db_path = os.path.abspath(DB_NAME)

        def _stats() -> Tuple[int, int, int, Dict[str, int]]:
            total, active, inactive = self.db_manager.get_account_counts()
            cats = self.db_manager.get_category_counts()
            return total, active, inactive, cats

        def _done(result) -> None:
            total, active, inactive, cats = result
            cat_str = ", ".join(f"{k}={v}" for k, v in cats.items())
            self.statusBar().showMessage(
                f"📊 إجمالي: {total} | نشط: {active} | غير نشط: {inactive} | الفئات: {cat_str}", 5000
            )
            logger.info("DB Status: path={}, total={}, active={}, inactive={}, cats={}", db_path, total, active, inactive, cats)

        def _fail(exc: str) -> None:
            self.statusBar().showMessage(f"❌ خطأ في فحص قاعدة البيانات: {exc}", 5000)
            logger.error("DB Status error: {}", exc)

        run_task(_stats, _done, _fail)

    def closeEvent(self, event) -> None:
        self._closing = True
        try:
            self.countdown_timer.stop()
            self._countdown_running = False
        except Exception:
            pass
        try:
            self._firefox_timer.stop()
            self._time_refresh_timer.stop()
        except Exception:
            pass
        # Stop the proxy/geo helper threads so they are never destroyed while
        # still running (fixes "QThread: Destroyed while thread is still
        # running" on exit).
        self._stop_thread_safely(self._thread)
        self._stop_thread_safely(self._geo_thread)
        # Let in-flight workers finish before closing the shared connection.
        try:
            QThreadPool.globalInstance().waitForDone(2000)
        except Exception:
            pass
        try:
            self.db_manager.close()
        except Exception:
            pass
        super().closeEvent(event)


# ============================================================================
# PROXY CHECK WORKER (QThread-based for network ops)
# ============================================================================
class ProxyCheckWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, ip: str, port: str, username: str, password: str) -> None:
        super().__init__()
        self.ip = ip.strip()
        self.port = port.strip()
        self.username = username.strip()
        self.password = password.strip()

    def run(self) -> None:
        try:
            proxy_url = f"socks5h://{self.username}:{self.password}@{self.ip}:{self.port}"
            with httpx.Client(proxy=proxy_url, timeout=PROXY_TIMEOUT_SEC, verify=True) as client:
                resp = client.get(PROXY_CHECK_URL)
                resp.raise_for_status()
                new_ip = resp.json()["ip"]
            logger.info("Proxy IP resolved: {}", new_ip)
            self.finished.emit(new_ip)
        except httpx.TimeoutException:
            self.error.emit("انتهت مهلة الاتصال بالبروكسي")
        except httpx.HTTPStatusError as exc:
            self.error.emit(f"HTTP error: {exc.response.status_code}")
        except Exception as exc:
            self.error.emit(f"Unexpected error: {exc}")


# ============================================================================
# TIMEZONE UTILITIES (Windows timezone matching for the geo lookup)
# ============================================================================


_TZ_CREATE_NO_WINDOW: Final[int] = 0x08000000 if IS_WINDOWS else 0


def _decode_tzutil(raw: bytes) -> str:
    """Decode tzutil output: try UTF-8, then the ANSI codepage, then replace."""
    for enc in ("utf-8", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def list_windows_timezones() -> List[Tuple[str, str]]:
    """Return (tz_id, display_name) pairs from the registry (empty list on failure).

    Enumerating HKLM\\...\\Time Zones subkeys is preferred over `tzutil /l`
    because tzutil's line order is (display, id) on some localized Windows
    builds and (id, display) on others, while subkey names are always the IDs.
    """
    if winreg is None:
        return []
    try:
        base = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Time Zones",
        )
    except OSError as exc:
        logger.warning("registry Time Zones open failed: {}", exc)
        return []
    pairs: List[Tuple[str, str]] = []
    with base:
        i = 0
        while True:
            try:
                tz_id = winreg.EnumKey(base, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(base, tz_id) as key:
                    display = winreg.QueryValueEx(key, "Display")[0]
            except OSError:
                display = tz_id
            pairs.append((tz_id, display))
    pairs.sort(key=lambda p: p[0].lower())
    return pairs


def current_windows_timezone_id() -> Optional[str]:
    """Return the active Windows timezone ID via `tzutil /g` (None on failure)."""
    if not IS_WINDOWS:
        return None
    try:
        out = subprocess.check_output(
            ["tzutil", "/g"], stderr=subprocess.DEVNULL,
            creationflags=_TZ_CREATE_NO_WINDOW,
        )
        return _decode_tzutil(out).strip() or None
    except Exception as exc:
        logger.warning("tzutil /g failed: {}", exc)
        return None


def set_windows_timezone(tz_id: str) -> Tuple[bool, str]:
    """Apply a Windows timezone via `tzutil /s`. Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "تغيير المنطقة الزمنية مدعوم على ويندوز فقط."
    try:
        proc = subprocess.run(
            ["tzutil", "/s", tz_id], capture_output=True,
            creationflags=_TZ_CREATE_NO_WINDOW,
        )
    except Exception as exc:
        return False, f"فشل تنفيذ tzutil: {exc}"
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip()
        return False, msg or "فشل تغيير المنطقة الزمنية (قد تحتاج صلاحيات المسؤول)."
    logger.info("Windows timezone set to: {}", tz_id)
    return True, f"تم تطبيق المنطقة الزمنية: {tz_id}"


def country_flag_emoji(code: str) -> str:
    """Return a flag emoji for a 2-letter ISO country code ('' if invalid)."""
    code = (code or "").strip().upper()
    if len(code) == 2 and code.isalpha():
        return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)
    return ""


def _tz_rule_to_datetime(rule: Tuple[int, ...], year: int) -> Optional[datetime]:
    """Convert a REG_TZI SYSTEMTIME rule to a datetime for the given year.

    A rule is (wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMs)
    where the recurring form uses wDay = 1..5 (nth weekday, 5 = last) and
    wDayOfWeek = 0 (Sunday) .. 6 (Saturday).
    """
    _y, month, win_dow, nth, hour, minute, sec, _ms = rule
    if not 1 <= month <= 12 or not 1 <= nth <= 5:
        return None
    py_dow = (win_dow + 6) % 7  # Windows 0=Sunday -> Python 0=Monday
    first = datetime(year, month, 1)
    day = 1 + (py_dow - first.weekday()) % 7 + 7 * (nth - 1)
    last_day = calendar.monthrange(year, month)[1]
    if day > last_day:
        day -= 7  # nth = 5 means "last <weekday> of the month"
    if day < 1:
        return None
    return datetime(year, month, day, hour, minute, sec)


def windows_tz_utc_offset_minutes(tz_id: str, when: Optional[datetime] = None) -> Optional[int]:
    """DST-aware current UTC offset (minutes) of a Windows timezone from its TZI.

    Uses the static REG_TZI rules, so zones with Dynamic DST overrides
    (e.g. Morocco) are approximated. Returns None if the zone cannot be read.
    """
    if winreg is None:
        return None
    when = when or datetime.now()
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Time Zones" + "\\" + tz_id,
        ) as key:
            tzi = winreg.QueryValueEx(key, "TZI")[0]
    except OSError as exc:
        logger.debug("TZI read failed for {}: {}", tz_id, exc)
        return None
    bias, std_bias, dlt_bias = struct.unpack_from("<3l", tzi, 0)
    std_rule = struct.unpack_from("<8H", tzi, 12)
    dlt_rule = struct.unpack_from("<8H", tzi, 28)

    dst_start = _tz_rule_to_datetime(dlt_rule, when.year)
    std_start = _tz_rule_to_datetime(std_rule, when.year)

    in_dst = False
    if dst_start is not None and std_start is not None:
        if dst_start <= std_start:  # northern hemisphere: DST inside the year
            in_dst = dst_start <= when < std_start
        else:  # southern hemisphere: DST wraps across the new year
            in_dst = when >= dst_start or when < std_start
    total_bias = bias + (dlt_bias if in_dst else std_bias)
    return -total_bias


def parse_utc_offset(text: str) -> Optional[int]:
    """Parse '+03:00' / '-04:30' style UTC offsets to minutes (None if invalid)."""
    m = re.fullmatch(r"([+-])(\d{1,2}):(\d{2})", (text or "").strip())
    if not m:
        return None
    sign, hours, minutes = m.group(1), int(m.group(2)), int(m.group(3))
    if minutes > 59 or hours > 14:
        return None
    total = hours * 60 + minutes
    return -total if sign == "-" else total


def format_utc_offset(minutes: int) -> str:
    """Format offset minutes as '+HH:MM' / '-HH:MM'."""
    sign = "-" if minutes < 0 else "+"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


# ============================================================================
# GEO LOOKUP WORKER (ip2location.io queried through the active proxy)
# ============================================================================


class GeoLookupWorker(QObject):
    """Looks up the proxy exit IP's geolocation via ip2location.io.

    The request is routed through the SOCKS5 proxy so the API reports the
    proxy's exit location, and a browser-like User-Agent is required because
    ip2location.io rejects the default Python UA with HTTP 403.
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ip: str, port: str, username: str, password: str) -> None:
        super().__init__()
        self.ip = ip.strip()
        self.port = port.strip()
        self.username = username.strip()
        self.password = password.strip()

    def run(self) -> None:
        proxy_url = f"socks5h://{self.username}:{self.password}@{self.ip}:{self.port}"
        try:
            with httpx.Client(
                proxy=proxy_url, timeout=IP_GEO_TIMEOUT_SEC, verify=True,
                headers={"User-Agent": IP_GEO_BROWSER_UA},
            ) as client:
                resp = client.get(IP_GEO_API_URL)
                resp.raise_for_status()
                data = resp.json()
            if not isinstance(data, dict) or not data.get("ip"):
                self.error.emit("استجابة غير متوقعة من ip2location.io")
                return
            logger.info("Geo lookup OK for {} ({})", data.get("ip"), data.get("country_code"))
            self.finished.emit(data)
        except httpx.TimeoutException:
            self.error.emit("انتهت مهلة الاتصال بالبروكسي")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403, 429):
                self.error.emit(f"رفض ip2location.io الطلب (HTTP {status}) — قد يكون حد الاستخدام اليومي قد استنفد.")
            else:
                self.error.emit(f"HTTP error: {status}")
        except Exception as exc:
            self.error.emit(f"Unexpected error: {exc}")


# ============================================================================
# GEO / TIMEZONE DIALOG (proxy location + Windows timezone matching)
# ============================================================================


class GeoTimezoneDialog(QDialog):
    """Shows ip2location.io geolocation for the proxy IP and offers matching
    Windows timezones (same current UTC offset) with one-click apply."""

    def __init__(self, geo_data: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._geo = geo_data
        self._candidates: List[Tuple[str, str]] = []
        self._applied = False
        self.tz_list: Optional[QListWidget] = None
        self._build_ui()

    def _build_ui(self) -> None:
        code = str(self._geo.get("country_code") or "")
        flag = country_flag_emoji(code)
        country = str(self._geo.get("country_name") or "غير معروف")
        self.setWindowTitle(f"🌍 موقع البروكسي — {self._geo.get('ip', '')}")

        root = QVBoxLayout(self)
        info = QGroupBox("نتائج الاستعلام (ip2location.io)")
        info_layout = QGridLayout(info)
        rows = [
            ("عنوان IP", str(self._geo.get("ip") or "")),
            ("الدولة", f"{flag} {country}".strip()),
            ("المنطقة/المدينة",
             ", ".join(str(x) for x in (self._geo.get("region_name"), self._geo.get("city_name")) if x)),
            ("الإحداثيات",
             f"{self._geo.get('latitude')}, {self._geo.get('longitude')}"
             if self._geo.get("latitude") is not None else ""),
            ("المنطقة الزمنية", str(self._geo.get("time_zone") or "غير معروف")),
            ("ASN", f"{self._geo.get('asn')} — {self._geo.get('as')}" if self._geo.get("asn") else ""),
        ]
        for r, (label, value) in enumerate(rows):
            info_layout.addWidget(QLabel(f"{label}:"), r, 0)
            val_lbl = QLabel(value or "—")
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info_layout.addWidget(val_lbl, r, 1)
        info_layout.setColumnStretch(1, 1)
        root.addWidget(info)

        tz_group = QGroupBox("مطابقة المنطقة الزمنية في ويندوز")
        tz_layout = QVBoxLayout(tz_group)
        target_off = parse_utc_offset(str(self._geo.get("time_zone") or ""))
        if target_off is None:
            warn = QLabel("⚠️ لم تُرجع الخدمة توقيتًا صالحًا، فلا يمكن المطابقة تلقائيًا.")
            warn.setWordWrap(True)
            tz_layout.addWidget(warn)
        else:
            header = QLabel(
                f"المناطق الزمنية المطابقة للتوقيت {format_utc_offset(target_off)} "
                "(مع وضع توقيتك الحالي أولًا إن وُجد):"
            )
            header.setWordWrap(True)
            tz_layout.addWidget(header)
            self.tz_list = QListWidget()
            self.tz_list.setSelectionMode(QAbstractItemView.SingleSelection)
            tz_layout.addWidget(self.tz_list)
        btns = QHBoxLayout()
        self.apply_btn = QPushButton("🗓️ تطبيق المنطقة الزمنية المحددة")
        self.apply_btn.setEnabled(target_off is not None)
        self.apply_btn.clicked.connect(self._apply_selected)
        btns.addWidget(self.apply_btn)
        btns.addStretch(1)
        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        tz_layout.addLayout(btns)
        root.addWidget(tz_group)

        self._refresh_candidates(target_off)

    def _refresh_candidates(self, target_off: Optional[int]) -> None:
        if self.tz_list is None or target_off is None:
            return
        self.apply_btn.setEnabled(False)  # busy while matching timezones

        def _match() -> Tuple[List[Tuple[str, str]], Optional[str]]:
            # Registry enumeration (~100 subkeys) + `tzutil /g` subprocess —
            # both blocking, so they run off the GUI thread.
            candidates = [
                (tz_id, display) for tz_id, display in list_windows_timezones()
                if windows_tz_utc_offset_minutes(tz_id) == target_off
            ]
            current_id = current_windows_timezone_id()
            return candidates, current_id

        def _done(result) -> None:
            candidates, current_id = result
            candidates.sort(key=lambda p: (p[0] != current_id, p[0].lower()))
            self._candidates = candidates
            self.tz_list.clear()
            for tz_id, display in self._candidates:
                label = f"{display}  [{tz_id}]" if display != tz_id else tz_id
                self.tz_list.addItem(QListWidgetItem(label))
            if self._candidates:
                self.tz_list.setCurrentRow(0)
                self.tz_list.setMinimumHeight(160)
            self.apply_btn.setEnabled(True)

        def _fail(_err: str) -> None:
            self._candidates = []
            self.apply_btn.setEnabled(True)

        run_task(_match, _done, _fail)

    def _apply_selected(self) -> None:
        if self.tz_list is None:
            return
        row = self.tz_list.currentRow()
        if row < 0 or row >= len(self._candidates):
            QMessageBox.warning(self, APP_TITLE, "يرجى اختيار منطقة زمنية أولًا.")
            return
        tz_id, _display = self._candidates[row]
        confirm = QMessageBox.question(
            self, APP_TITLE, f"تأكيد تغيير توقيت ويندوز إلى:\n{tz_id}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.apply_btn.setEnabled(False)

        def _done(result) -> None:
            self.apply_btn.setEnabled(True)
            ok, msg = result
            if ok:
                self._applied = True
                QMessageBox.information(self, APP_TITLE, f"✅ {msg}")
            else:
                QMessageBox.warning(
                    self, APP_TITLE,
                    f"❌ {msg}\nيمكنك تغيير التوقيت يدويًا من إعدادات ويندوز.",
                )

        def _fail(err: str) -> None:
            self.apply_btn.setEnabled(True)
            QMessageBox.warning(self, APP_TITLE, f"❌ فشل تنفيذ tzutil: {err}")

        # `tzutil /s` is a blocking subprocess — run it off the GUI thread.
        run_task(set_windows_timezone, _done, _fail, tz_id,
                 busy_button=self.apply_btn)


# NOTE: Geo lookup wiring lives in MainWindow (_open_geo_dialog, _start_geo_lookup,
# _on_geo_success, _on_geo_error) behind the "🌍 موقع البروكسي" button; the worker and
# dialog above follow the same QThread pattern as ProxyCheckWorker.

# ============================================================================
# MAIN
# ============================================================================

# ============================================================================
# THEME / UI (self-contained QSS — no external theme library)
# ============================================================================
_APP_FONT_FAMILY: str = APP_FONT_FAMILY
_bundled_font_registered: bool = False


def _candidate_font_files() -> List[Path]:
    """TTF/OTF files the app can register without any extra payload."""
    names = (
        "calibri.ttf", "calibrib.ttf", "calibril.ttf", "calibrii.ttf",
        "calibri.otf", "Calibri.ttf", "Calibri-Bold.ttf",
        "segoeui.ttf", "segoeuib.ttf", "tahoma.ttf", "tahomabd.ttf",
        "arial.ttf", "arialbd.ttf",
    )
    paths: List[Path] = []
    if APP_FONT_FILE.exists():
        paths.append(APP_FONT_FILE)
    if WINDOWS_FONTS_DIR.is_dir():
        for name in names:
            p = WINDOWS_FONTS_DIR / name
            if p.is_file():
                paths.append(p)
    return paths


def _register_bundled_font() -> str:
    """Make Calibri (or a Windows fallback) available to Qt. Idempotent."""
    global _APP_FONT_FAMILY, _bundled_font_registered
    if _bundled_font_registered:
        return _APP_FONT_FAMILY
    _bundled_font_registered = True
    try:
        db = QFontDatabase()
        available = set(db.families())
        for family in APP_FONT_FALLBACKS:
            if family in available:
                _APP_FONT_FAMILY = family
                logger.info("Using system font family '{}'.", family)
                return _APP_FONT_FAMILY
        for font_path in _candidate_font_files():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id == -1:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                continue
            _APP_FONT_FAMILY = families[0]
            logger.info("Font registered: {} ({})", _APP_FONT_FAMILY, font_path.name)
            return _APP_FONT_FAMILY
    except Exception as exc:
        logger.warning("Font registration failed ({}).", exc)
    return _APP_FONT_FAMILY


# ============================================================================
# CENTRALIZED FONT MANAGEMENT
# One FontManager is the single source of truth for every QFont in the app:
# family (bundled Calibri), point size and bold preference (persisted in the
# settings table). It replaces the previously scattered logic where
# PreferencesDialog defaulted to 10pt, startup loaded 11pt, and the toolbar
# hard-coded 14pt while ignoring the user's preferences entirely.
# ============================================================================
class FontManager:
    """Single source of truth for app fonts (family / size / bold)."""

    DEFAULT_SIZE: Final[int] = 11   # app-wide default point size
    MIN_SIZE: Final[int] = 6        # PreferencesDialog spin-box lower bound
    MAX_SIZE: Final[int] = 24       # PreferencesDialog spin-box upper bound
    # Toolbar emphasis: DEFAULT_SIZE + offset reproduces the old hard-coded
    # 14pt look at default settings — but now scales with the user's size.
    TOOLBAR_SIZE_OFFSET: Final[int] = 3

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self._db = db
        self._size: int = self.DEFAULT_SIZE
        self._bold: bool = False
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> Tuple[int, bool]:
        """(Re)load saved preferences; never raises — falls back to defaults."""
        size, bold = self.DEFAULT_SIZE, False
        if self._db is not None:
            try:
                saved_size = self._db.get_setting("pref_font_size")
                saved_bold = self._db.get_setting("pref_font_bold")
                if saved_size is not None:
                    size = int(saved_size)
                bold = saved_bold == "1"
            except Exception as exc:
                logger.warning("Could not load font preferences: {}", exc)
                size, bold = self.DEFAULT_SIZE, False
        self._size = self._clamp(size)
        self._bold = bold
        return self._size, self._bold

    def save(self, size: int, bold: bool) -> None:
        """Persist preferences and update the in-memory state."""
        self._size = self._clamp(size)
        self._bold = bold
        if self._db is not None:
            self._db.set_setting("pref_font_size", str(self._size))
            self._db.set_setting("pref_font_bold", "1" if bold else "0")

    def _clamp(self, size: int) -> int:
        return max(self.MIN_SIZE, min(self.MAX_SIZE, int(size)))

    # -- accessors -----------------------------------------------------------
    @property
    def size(self) -> int:
        return self._size

    @property
    def bold(self) -> bool:
        return self._bold

    @property
    def family(self) -> str:
        """Resolved UI font (Calibri from Windows, else Segoe UI / Tahoma)."""
        return _register_bundled_font()

    def base_font(self) -> QFont:
        """App-wide base font: system Calibri (or fallback) + user size/bold."""
        font = QFont()
        font.setFamily(self.family)
        font.setStyleHint(QFont.SansSerif)
        font.setPointSize(self._size)
        font.setWeight(QFont.Bold if self._bold else QFont.Normal)
        return font

    def toolbar_font(self) -> QFont:
        """Toolbar emphasis font, derived from the user's preferences."""
        font = self.base_font()
        font.setPointSize(self._clamp(self._size + self.TOOLBAR_SIZE_OFFSET))
        # The bold preference wins; otherwise keep the DemiBold design emphasis.
        font.setWeight(QFont.Bold if self._bold else QFont.DemiBold)
        return font

    def apply_to_app(self) -> None:
        """Apply the base font application-wide (QApplication.setFont)."""
        app = QApplication.instance()
        if app is None:
            return
        app.setFont(self.base_font())
        logger.info("Applied font preferences: family={}, size={}, bold={}.",
                    self.family, self._size, self._bold)


# ============================================================================
# QSS DESIGN TOKENS — light paper dashboard (teal accent), v6.2 token system
# ----------------------------------------------------------------------------
# One palette to rule every widget. Rules:
#   1. Never hard-code a colour inside a component rule — add a token instead.
#   2. Semantic tokens (success/warning/danger) express MEANING, not decoration:
#      green = healthy/active, amber = attention, red = destructive.
#   3. Radius scale is fixed: 6 (small indicators) / 8 (controls) / 10 (cards,
#      lists, menus) / 12 (banners, dialogs). No ad-hoc 5/9/14 px values.
#   4. Every interactive element gets a visible :focus state (accessibility).
# ============================================================================
# -- paper & ink (neutrals) --------------------------------------------------
_QSS_BG: Final[str] = "#f4f6f8"            # window paper (cool grey-blue)
_QSS_CARD: Final[str] = "#ffffff"          # card surface
_QSS_CARD_ALT: Final[str] = "#f8fbfc"      # sunk card / read-only field
_QSS_SUNK: Final[str] = "#eef2f4"          # disabled / sunken surfaces
_QSS_ALT_ROW: Final[str] = "#f5fafb"       # table zebra rows
_QSS_BORDER: Final[str] = "#dfe7ea"
_QSS_BORDER_STRONG: Final[str] = "#b9c9cf"
_QSS_TEXT: Final[str] = "#26333b"
_QSS_TEXT_SOFT: Final[str] = "#5c6f79"
_QSS_TEXT_FADED: Final[str] = "#9fb1ba"
# -- accent (teal) ------------------------------------------------------------
# Slightly deepened vs the old #00acc1: white text on #0097a7 reaches ~3.6:1
# contrast (WCAG-friendly) while hover (#00acc1) keeps the original vibrancy.
_QSS_ACCENT: Final[str] = "#0097a7"
_QSS_ACCENT_HOVER: Final[str] = "#00acc1"
_QSS_ACCENT_PRESSED: Final[str] = "#007e8c"
_QSS_ACCENT_SOFT: Final[str] = "#e0f5f8"
_QSS_ACCENT_SOFT_HOVER: Final[str] = "#cdeef3"
_QSS_ACCENT_DARK: Final[str] = "#00566b"
_QSS_ACCENT_DEEP: Final[str] = "#00697a"   # strong selection (accounts table)
# -- focus ring ---------------------------------------------------------------
_QSS_FOCUS: Final[str] = "#0097a7"         # ring colour for :focus states
# -- semantic: success (healthy / active) --------------------------------------
_QSS_SUCCESS: Final[str] = "#2e7d46"
_QSS_SUCCESS_HOVER: Final[str] = "#389556"
_QSS_SUCCESS_PRESSED: Final[str] = "#1f5e33"
_QSS_SUCCESS_SOFT: Final[str] = "#e3f3e8"
_QSS_SUCCESS_DARK: Final[str] = "#1b5e20"
# -- semantic: warning (attention) ---------------------------------------------
_QSS_WARNING: Final[str] = "#b26a00"
_QSS_WARNING_SOFT: Final[str] = "#fff4e0"
_QSS_WARNING_DARK: Final[str] = "#7a4a00"
# -- semantic: danger (destructive) --------------------------------------------
_QSS_DANGER: Final[str] = "#e53950"
_QSS_DANGER_HOVER: Final[str] = "#ff5f70"
_QSS_DANGER_PRESSED: Final[str] = "#b31027"
_QSS_DANGER_SOFT: Final[str] = "#fdeef1"
_QSS_DANGER_DARK: Final[str] = "#8e1023"
# -- disabled ------------------------------------------------------------------
_QSS_DISABLED_TEXT: Final[str] = "#9fb1ba"
_QSS_DISABLED_BG: Final[str] = "#eef2f4"
_QSS_DISABLED_BORDER: Final[str] = "#e4eaed"

_QSS_PART_1: Final[str] = f"""
/* ===== base surfaces ===== */
QDialog, QMainWindow {{
    background-color: {_QSS_BG};
}}
QWidget {{
    color: {_QSS_TEXT};
}}
QLabel {{
    background: transparent;
    border: none;
}}
QToolTip {{
    color: #ffffff;
    background-color: {_QSS_TEXT};
    border: 1px solid {_QSS_FOCUS};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
/* Message boxes read as cards, and their buttons get a comfortable hit area. */
QMessageBox {{
    background-color: {_QSS_CARD};
}}
QMessageBox QLabel {{
    color: {_QSS_TEXT};
    background: transparent;
}}
QMessageBox QPushButton {{
    min-width: 84px;
    min-height: 30px;
}}

/* ===== buttons ===== */
QPushButton {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
    border-color: {_QSS_FOCUS};
}}
QPushButton:pressed {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT_HOVER};
    border-color: {_QSS_ACCENT_PRESSED};
}}
/* Focus is always visible: accent-dark border + tinted surface (a11y). */
QPushButton:focus {{
    border: 1px solid {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
}}
QPushButton:disabled {{
    color: {_QSS_DISABLED_TEXT};
    background-color: {_QSS_DISABLED_BG};
    border-color: {_QSS_DISABLED_BORDER};
}}

/* primary (accent-filled, subtle vertical gradient for tactile depth) */
QPushButton#primaryButton {{
    color: #ffffff;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_QSS_ACCENT_HOVER}, stop:1 {_QSS_ACCENT});
    border: 1px solid {_QSS_ACCENT};
    border-radius: 8px;
    font-weight: bold;
}}
QPushButton#primaryButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_QSS_ACCENT_HOVER}, stop:1 {_QSS_ACCENT_HOVER});
    border-color: {_QSS_ACCENT_PRESSED};
}}
QPushButton#primaryButton:pressed {{ background-color: {_QSS_ACCENT_PRESSED}; }}
QPushButton#primaryButton:focus {{ border: 1px solid #ffffff; outline: none; background-color: {_QSS_ACCENT}; }}
QPushButton#primaryButton:disabled {{
    color: #ffffff;
    background-color: {_QSS_DISABLED_BORDER};
    border-color: {_QSS_DISABLED_BORDER};
}}

/* danger (destructive, same gradient treatment as primary) */
QPushButton#dangerButton {{
    color: #ffffff;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_QSS_DANGER_HOVER}, stop:1 {_QSS_DANGER});
    border: 1px solid {_QSS_DANGER};
    border-radius: 8px;
    font-weight: bold;
}}
QPushButton#dangerButton:hover {{ background-color: {_QSS_DANGER_HOVER}; }}
QPushButton#dangerButton:pressed {{ background-color: {_QSS_DANGER_PRESSED}; }}
QPushButton#dangerButton:focus {{ border: 1px solid #ffffff; background-color: {_QSS_DANGER}; }}
QPushButton#dangerButton:disabled {{
    color: #ffffff;
    background-color: {_QSS_DISABLED_BORDER};
    border-color: {_QSS_DISABLED_BORDER};
}}

/* small square icon buttons (copy / QR) */
QPushButton#iconButton {{
    color: {_QSS_TEXT_SOFT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 6px;
    padding: 2px;
}}
QPushButton#iconButton:hover {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
    border-color: {_QSS_FOCUS};
}}
QPushButton#iconButton:pressed {{ background-color: {_QSS_ACCENT_SOFT_HOVER}; }}

/* ===== colored toolbar buttons (one accent per action — brand recognition
   beats uniformity here: Firefox orange, Telegram blue, Copilot blue...) ===== */
QPushButton#firefoxButton {{
    color: #ffffff; background-color: #e6611a; border: 1px solid #e6611a; border-radius: 8px;
}}
QPushButton#firefoxButton:hover {{ background-color: #ff7a2e; border-color: #ff7a2e; }}
QPushButton#firefoxButton:pressed {{ background-color: #b84a10; border-color: #b84a10; }}
QPushButton#firefoxButton:focus {{ border: 1px solid #ffffff; background-color: #e6611a; }}
QPushButton#firefoxButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

QPushButton#privateButton {{
    color: #ffffff; background-color: #5e35b1; border: 1px solid #5e35b1; border-radius: 8px;
}}
QPushButton#privateButton:hover {{ background-color: #6f45c4; border-color: #6f45c4; }}
QPushButton#privateButton:pressed {{ background-color: #4527a0; border-color: #4527a0; }}
QPushButton#privateButton:focus {{ border: 1px solid #ffffff; background-color: #5e35b1; }}
QPushButton#privateButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

QPushButton#telegramButton {{
    color: #ffffff; background-color: #2aabee; border: 1px solid #2aabee; border-radius: 8px;
}}
QPushButton#telegramButton:hover {{ background-color: #4cbcf5; border-color: #4cbcf5; }}
QPushButton#telegramButton:pressed {{ background-color: #1d8fd0; border-color: #1d8fd0; }}
QPushButton#telegramButton:focus {{ border: 1px solid #ffffff; background-color: #2aabee; }}
QPushButton#telegramButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

QPushButton#aiButton {{
    color: #ffffff; background-color: #8e24aa; border: 1px solid #8e24aa; border-radius: 8px;
}}
QPushButton#aiButton:hover {{ background-color: #a43cc0; border-color: #a43cc0; }}
QPushButton#aiButton:pressed {{ background-color: #6a1b9a; border-color: #6a1b9a; }}
QPushButton#aiButton:focus {{ border: 1px solid #ffffff; background-color: #8e24aa; }}
QPushButton#aiButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

QPushButton#copilotButton {{
    color: #ffffff; background-color: #1565c0; border: 1px solid #1565c0; border-radius: 8px;
}}
QPushButton#copilotButton:hover {{ background-color: #1e78db; border-color: #1e78db; }}
QPushButton#copilotButton:pressed {{ background-color: #0d47a1; border-color: #0d47a1; }}
QPushButton#copilotButton:focus {{ border: 1px solid #ffffff; background-color: #1565c0; }}
QPushButton#copilotButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

QPushButton#yougovButton {{
    color: #ffffff; background-color: #2e7d32; border: 1px solid #2e7d32; border-radius: 8px;
}}
QPushButton#yougovButton:hover {{ background-color: #3a9a3f; border-color: #3a9a3f; }}
QPushButton#yougovButton:pressed {{ background-color: #1b5e20; border-color: #1b5e20; }}
QPushButton#yougovButton:focus {{ border: 1px solid #ffffff; background-color: #2e7d32; }}
QPushButton#yougovButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

QPushButton#translateButton {{
    color: #ffffff; background-color: #f57c00; border: 1px solid #f57c00; border-radius: 8px;
}}
QPushButton#translateButton:hover {{ background-color: #ff9100; border-color: #ff9100; }}
QPushButton#translateButton:pressed {{ background-color: #c25e00; border-color: #c25e00; }}
QPushButton#translateButton:focus {{ border: 1px solid #ffffff; background-color: #f57c00; }}
QPushButton#translateButton:disabled {{ color: #ffffff; background-color: {_QSS_DISABLED_BORDER}; border-color: {_QSS_DISABLED_BORDER}; }}

/* segmented filter pills */
QPushButton#segmentedButton {{
    color: {_QSS_TEXT_SOFT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 12px;
    padding: 6px 14px;
}}
QPushButton#segmentedButton:hover {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
    border-color: {_QSS_FOCUS};
}}
QPushButton#segmentedButton:focus {{
    color: {_QSS_ACCENT_DARK};
    border-color: {_QSS_ACCENT_DARK};
}}
QPushButton#segmentedButton:checked {{
    color: #ffffff;
    background-color: {_QSS_ACCENT};
    border-color: {_QSS_ACCENT};
    font-weight: bold;
}}
QPushButton#segmentedButton:checked:hover {{
    color: #ffffff;
    background-color: {_QSS_ACCENT_HOVER};
    border-color: {_QSS_ACCENT_HOVER};
}}
"""


_QSS_PART_2: Final[str] = f"""
/* ===== line edits / text areas ===== */
QLineEdit, QTextEdit, QPlainTextEdit {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {_QSS_ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: {_QSS_BORDER_STRONG};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {_QSS_FOCUS};
    background-color: {_QSS_CARD};
}}
QLineEdit:disabled {{
    color: {_QSS_DISABLED_TEXT};
    background-color: {_QSS_DISABLED_BG};
    border-color: {_QSS_DISABLED_BORDER};
}}
/* read-only fields (FieldLineEdit cards): flat, tinted, interactive hint */
QLineEdit[readOnly="true"] {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD_ALT};
    border: 1px solid {_QSS_BORDER};
}}
QLineEdit[readOnly="true"]:focus {{
    border: 1px solid {_QSS_BORDER_STRONG};
}}
QLineEdit[readOnly="true"]:disabled {{
    color: {_QSS_DISABLED_TEXT};
    background-color: {_QSS_DISABLED_BG};
}}
QTextEdit[readOnly="true"], QPlainTextEdit[readOnly="true"] {{
    background-color: {_QSS_CARD_ALT};
}}
QLineEdit#ip_before_field, QLineEdit#ip_after_field {{
    font-weight: bold;
    padding: 2px 6px;
    border-radius: 6px;
}}
QGroupBox#compactIpGroup {{
    margin-top: 8px;
    padding: 8px 6px 4px 6px;
}}
QGroupBox#compactIpGroup QPushButton {{
    padding: 1px 8px;
    border-radius: 6px;
    min-height: 22px;
}}
QGroupBox#compactIpGroup QSpinBox {{
    padding: 1px 4px;
    border-radius: 6px;
    min-height: 22px;
}}
QLabel#compactTimerLabel {{
    font-weight: 700;
    color: {_QSS_ACCENT_DARK};
    min-width: 40px;
}}

/* ===== spin boxes (with visible arrow triangles) ===== */
QSpinBox, QDoubleSpinBox {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    padding: 6px 8px;
}}
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {_QSS_BORDER_STRONG}; }}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {_QSS_FOCUS}; }}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {_QSS_DISABLED_TEXT};
    background-color: {_QSS_DISABLED_BG};
    border-color: {_QSS_DISABLED_BORDER};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {_QSS_ACCENT_SOFT};
    border: none;
    border-left: 1px solid {_QSS_BORDER};
    width: 18px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {_QSS_ACCENT};
}}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
    background-color: {_QSS_ACCENT_PRESSED};
}}
QSpinBox::up-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {_QSS_ACCENT_DARK};
    width: 0; height: 0;
}}
QSpinBox::up-arrow:hover, QSpinBox::up-arrow:pressed {{
    border-bottom-color: #ffffff;
}}
QSpinBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {_QSS_ACCENT_DARK};
    width: 0; height: 0;
}}
QSpinBox::down-arrow:hover, QSpinBox::down-arrow:pressed {{
    border-top-color: #ffffff;
}}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{
    border-bottom-color: {_QSS_DISABLED_TEXT};
    border-top-color: {_QSS_DISABLED_TEXT};
}}

/* ===== combos ===== */
QComboBox {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    padding: 6px 12px;
}}
QComboBox:hover {{ border-color: {_QSS_BORDER_STRONG}; }}
QComboBox:focus {{ border: 1px solid {_QSS_FOCUS}; }}
QComboBox:on {{ border-color: {_QSS_ACCENT_PRESSED}; }}
QComboBox:disabled {{
    color: {_QSS_DISABLED_TEXT};
    background-color: {_QSS_DISABLED_BG};
    border-color: {_QSS_DISABLED_BORDER};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {_QSS_ACCENT};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    selection-background-color: {_QSS_ACCENT_SOFT};
    selection-color: {_QSS_ACCENT_DARK};
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 26px;
    border-radius: 4px;
    padding: 2px 6px;
}}

/* ===== checkboxes ===== */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {_QSS_BORDER_STRONG};
    border-radius: 5px;
    background-color: {_QSS_CARD};
}}
QCheckBox::indicator:hover {{
    border-color: {_QSS_FOCUS};
    background-color: {_QSS_ACCENT_SOFT};
}}
QCheckBox::indicator:focus {{ border-color: {_QSS_ACCENT_DARK}; }}
QCheckBox::indicator:checked {{
    background-color: {_QSS_ACCENT};
    border-color: {_QSS_ACCENT};
}}
QCheckBox::indicator:checked:hover {{ background-color: {_QSS_ACCENT_HOVER}; }}
QCheckBox:disabled {{ color: {_QSS_DISABLED_TEXT}; }}
QCheckBox::indicator:disabled {{
    background-color: {_QSS_DISABLED_BG};
    border-color: {_QSS_DISABLED_BORDER};
}}

/* ===== radio buttons (previously unstyled — now match the checkbox family) */
QRadioButton {{ spacing: 8px; }}
QRadioButton::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {_QSS_BORDER_STRONG};
    border-radius: 9px;
    background-color: {_QSS_CARD};
}}
QRadioButton::indicator:hover {{
    border-color: {_QSS_FOCUS};
    background-color: {_QSS_ACCENT_SOFT};
}}
QRadioButton::indicator:checked {{
    background-color: {_QSS_ACCENT};
    border-color: {_QSS_ACCENT};
}}
QRadioButton:disabled {{ color: {_QSS_DISABLED_TEXT}; }}

/* ===== group boxes (cards) ===== */
QGroupBox {{
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 8px;
    color: {_QSS_ACCENT_DARK};
    font-weight: 600;
}}

/* ===== card-style tabs ===== */
QTabWidget::pane {{
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    background-color: {_QSS_CARD};
    top: -1px;
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    color: {_QSS_TEXT_SOFT};
    background-color: #edf3f5;
    border: 1px solid {_QSS_BORDER};
    border-bottom: none;
    padding: 8px 10px;      /* compact so all six tabs fit in the (now narrower) tab panel */
    margin-left: 2px;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
}}
QTabBar::tab:focus {{
    color: {_QSS_ACCENT_DARK};
    border-color: {_QSS_ACCENT_DARK};
}}
QTabBar::tab:selected {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_CARD};
    border-bottom: 2px solid {_QSS_ACCENT};
    font-weight: bold;
}}
"""


_QSS_PART_3: Final[str] = f"""
/* ===== tables ===== */
QTableView, QTableWidget {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    alternate-background-color: {_QSS_ALT_ROW};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    gridline-color: #e8eef0;
    selection-background-color: {_QSS_ACCENT_SOFT};
    selection-color: {_QSS_ACCENT_DARK};
}}
QTableView::item, QTableWidget::item {{
    padding: 2px 4px;
    border: none;
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background-color: {_QSS_ACCENT_SOFT};
    color: {_QSS_ACCENT_DARK};
}}
/* Accounts list: selected row uses deep teal + white text. */
QTableView#accountsTable {{
    selection-background-color: {_QSS_ACCENT_DEEP};
    selection-color: #ffffff;
}}
QTableView#accountsTable::item:selected,
QTableView#accountsTable::item:selected:active,
QTableView#accountsTable::item:selected:!active {{
    background-color: {_QSS_ACCENT_DEEP};
    color: #ffffff;
}}
QTableView QHeaderView, QTableWidget QHeaderView {{
    background: transparent;
    border: none;
}}
QHeaderView::section {{
    background-color: {_QSS_ACCENT_SOFT};
    color: {_QSS_ACCENT_DARK};
    border: none;
    border-bottom: 1px solid #b2ebf2;
    padding: 5px 4px;
    font-weight: bold;
}}
QHeaderView::section:hover {{
    background-color: {_QSS_ACCENT_SOFT_HOVER};
}}
QTableCornerButton::section {{
    background-color: {_QSS_ACCENT_SOFT};
    border: none;
}}

/* ===== lists ===== */
QListWidget, QListView {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    outline: none;
}}
QListWidget::item, QListView::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}
QListWidget::item:hover {{ background-color: {_QSS_ACCENT_SOFT_HOVER}; }}
QListWidget::item:selected {{
    background-color: {_QSS_ACCENT_SOFT};
    color: {_QSS_ACCENT_DARK};
}}
QListWidget::item:selected:hover {{ background-color: {_QSS_ACCENT_SOFT_HOVER}; }}

/* ===== menus ===== */
QMenuBar {{
    background-color: {_QSS_BG};
    border-bottom: 1px solid {_QSS_BORDER};
}}
QMenuBar::item {{
    color: {_QSS_TEXT};
    padding: 6px 12px;
    border-radius: 6px;
    background: transparent;
}}
QMenuBar::item:selected {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
}}
QMenu {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 16px;      /* symmetric: safe under RTL mirroring */
    border-radius: 6px;
}}
QMenu::item:selected {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
}}
QMenu::item:disabled {{ color: {_QSS_DISABLED_TEXT}; }}
QMenu::separator {{
    height: 1px;
    background-color: {_QSS_BORDER};
    margin: 5px 8px;
}}
QMenu::icon {{
    padding-left: 8px;
}}

/* ===== toolbar / status bar ===== */
QToolBar {{
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    padding: 4px;
    spacing: 6px;
}}
QToolBar::handle {{
    background: transparent;
    width: 6px;
}}
QToolBar::separator {{
    width: 1px;
    background-color: {_QSS_BORDER};
    margin: 4px 4px;
}}
QStatusBar {{
    color: {_QSS_TEXT_SOFT};
    background-color: {_QSS_BG};
    border-top: 1px solid {_QSS_BORDER};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{
    color: {_QSS_TEXT_SOFT};
    background: transparent;
}}

/* ===== thin scrollbars ===== */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: #c3d2d8;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {_QSS_ACCENT}; }}
QScrollBar::handle:vertical:pressed {{ background-color: {_QSS_ACCENT_PRESSED}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background-color: #c3d2d8;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {_QSS_ACCENT}; }}
QScrollBar::handle:horizontal:pressed {{ background-color: {_QSS_ACCENT_PRESSED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ===== scroll areas ===== */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ===== splitter (imported by tools/panels; styled for future layouts) ===== */
QSplitter::handle {{
    background-color: {_QSS_BORDER};
}}
QSplitter::handle:hover {{ background-color: {_QSS_ACCENT}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

/* ===== special labels ===== */
QLabel#loginBanner {{
    color: #ffffff;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {_QSS_ACCENT_HOVER}, stop:1 {_QSS_ACCENT_DARK});
    border-radius: 12px;
    padding: 18px;
    font-size: 22px;
    font-weight: bold;
}}
QLabel#loginSubtitle {{
    color: {_QSS_TEXT_SOFT};
    font-size: 13px;
}}
QLabel#hintLabel {{
    color: {_QSS_TEXT_SOFT};
    font-size: 12px;
    background-color: {_QSS_ACCENT_SOFT};
    border-radius: 8px;
    padding: 8px;
}}
QLabel#dialogTitle {{
    font-size: 17px;
    font-weight: bold;
    color: {_QSS_ACCENT_DARK};
    padding: 2px;
}}

/* ===== proxy tab (v6.2): status pill + monospace JSON card ===== */
QLabel#versionBadge {{
    color: {_QSS_ACCENT_DEEP};
    background-color: {_QSS_ACCENT_SOFT};
    border: 1px solid {_QSS_ACCENT};
    border-radius: 10px;
    padding: 8px 18px;
    font-size: 15px;
    font-weight: 700;
}}
QLabel#proxyStatusLabel {{
    color: {_QSS_WARNING_DARK};
    font-size: 12px;
    background-color: {_QSS_WARNING_SOFT};
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 600;
}}
QTextEdit#jsonDisplay {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_CARD_ALT};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
    padding: 8px;
    selection-background-color: {_QSS_ACCENT};
    selection-color: #ffffff;
}}

/* ===== addon cards (addons tab) ===== */
QFrame#addonCard {{
    background-color: #fbfdfe;
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
}}
QFrame#addonCard:hover {{
    border-color: {_QSS_FOCUS};
    background-color: {_QSS_ACCENT_SOFT};
}}

/* ===== QR popup (frameless + translucent) ===== */
QDialog#qrDialog {{
    background-color: {_QSS_CARD};
    border-radius: 12px;
}}

/* ===== progress ===== */
QProgressBar {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_SUNK};
    border: none;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    font-weight: bold;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {_QSS_ACCENT}, stop:1 {_QSS_ACCENT_HOVER});
    border-radius: 7px;
}}

QFrame#statsStrip {{
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 10px;
}}
/* Dashboard stat cards — semantics: green = healthy, amber = attention. */
QLabel#statCard, QLabel#statCardGood, QLabel#statCardWarn {{
    background-color: {_QSS_CARD_ALT};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    padding: 1px 6px;
    font-weight: 700;
    color: {_QSS_TEXT};
}}
QLabel#statCardGood {{
    color: {_QSS_SUCCESS_DARK};
    border-color: {_QSS_SUCCESS};
    background-color: {_QSS_SUCCESS_SOFT};
}}
QLabel#statCardWarn {{
    color: {_QSS_WARNING_DARK};
    border-color: {_QSS_WARNING};
    background-color: {_QSS_WARNING_SOFT};
}}
QToolButton {{
    color: {_QSS_TEXT};
    background-color: {_QSS_CARD};
    border: 1px solid {_QSS_BORDER};
    border-radius: 8px;
    padding: 6px 10px;
}}
QToolButton:hover {{
    color: {_QSS_ACCENT_DARK};
    background-color: {_QSS_ACCENT_SOFT};
    border-color: {_QSS_FOCUS};
}}
QToolButton:pressed {{ background-color: {_QSS_ACCENT_SOFT_HOVER}; }}
QToolButton:checked {{
    color: #ffffff;
    background-color: {_QSS_ACCENT};
    border-color: {_QSS_ACCENT};
}}
QToolButton:checked:hover {{ background-color: {_QSS_ACCENT_HOVER}; }}
QToolButton:disabled {{
    color: {_QSS_DISABLED_TEXT};
    background-color: {_QSS_DISABLED_BG};
    border-color: {_QSS_DISABLED_BORDER};
}}
"""

# Complete theme, assembled once at import time.
_APP_QSS: Final[str] = _QSS_PART_1 + _QSS_PART_2 + _QSS_PART_3


def _apply_app_theme(app: QApplication,
                     font_manager: Optional[FontManager] = None) -> None:
    """Apply the light paper QSS theme (teal accent, no external library)."""
    family = _register_bundled_font()
    app.setStyle("Fusion")
    fm = font_manager if font_manager is not None else FontManager()
    app.setFont(fm.base_font())
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(_QSS_BG))
    palette.setColor(QPalette.WindowText, QColor(_QSS_TEXT))
    palette.setColor(QPalette.Base, QColor(_QSS_CARD))
    palette.setColor(QPalette.AlternateBase, QColor(_QSS_ALT_ROW))
    palette.setColor(QPalette.Text, QColor(_QSS_TEXT))
    palette.setColor(QPalette.Button, QColor(_QSS_CARD))
    palette.setColor(QPalette.ButtonText, QColor(_QSS_TEXT))
    palette.setColor(QPalette.Highlight, QColor(_QSS_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor(_QSS_TEXT))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.PlaceholderText, QColor(_QSS_TEXT_FADED))
    app.setPalette(palette)
    app.setStyleSheet(f'QWidget {{ font-family: "{family}"; }}\n' + _APP_QSS)


def main() -> None:
    app = QApplication(sys.argv)
    QThreadPool.globalInstance().setMaxThreadCount(2)
    app.setLayoutDirection(Qt.RightToLeft)
    QLocale.setDefault(QLocale(QLocale.Arabic))

    db_manager = DatabaseManager()
    font_manager = FontManager(db_manager)
    _apply_app_theme(app, font_manager)

    login_dialog = LoginDialog(db_manager)
    if login_dialog.exec_() == QDialog.Accepted:
        window = MainWindow(login_dialog.user_role, db_manager=db_manager,
                            font_manager=font_manager)
        window.setLayoutDirection(Qt.RightToLeft)
        window.showMaximized()
        sys.exit(app.exec_())
    else:
        logger.info("Login cancelled. Exiting.")
        db_manager.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
