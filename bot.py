import os
import logging
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

import requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
# All secrets come from environment variables only — no hardcoded
# fallbacks. Set these before running, e.g.:
#   export TELEGRAM_BOT_TOKEN="your-token-from-botfather"
#   export JEJELAYE_API_KEY="your-api-key"
#   export ADMIN_IDS="7190018261"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
JEJELAYE_API_KEY = os.getenv("JEJELAYE_API_KEY", "")
API_BASE_URL = os.getenv("API_BASE_URL", "https://jejelayegct.com.ng/api/v1")
MARKUP_PERCENTAGE = float(os.getenv("MARKUP_PERCENTAGE", "30"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# Bank transfer details shown to users for manual top-up
BANK_NAME = os.getenv("BANK_NAME", "OPAY")
BANK_ACCOUNT_NUMBER = os.getenv("BANK_ACCOUNT_NUMBER", "8144841843")
BANK_ACCOUNT_NAME = os.getenv("BANK_ACCOUNT_NAME", "YOUNG")

BUSINESS_NAME = "Chung Lao Store"

# ==================== DATABASE ====================
class AdvancedDatabase:
    def __init__(self, db_path="bot_database.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance REAL DEFAULT 0,
                total_spent REAL DEFAULT 0,
                total_purchases INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                is_suspended INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                product TEXT,
                service_id TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topup_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        conn.commit()
        conn.close()

    def execute_query(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            return None
        finally:
            conn.close()

    def fetch_one(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            return None
        finally:
            conn.close()

    def fetch_all(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            return []
        finally:
            conn.close()


db = AdvancedDatabase()


# ==================== API HANDLER ====================
class APIHandler:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 300  # 5 minutes

    def is_cache_valid(self, endpoint):
        if endpoint not in self.cache_time:
            return False
        return datetime.now() - self.cache_time[endpoint] < timedelta(seconds=self.cache_duration)

    def fetch(self, endpoint):
        """Fetch data from API with caching"""
        try:
            if endpoint in self.cache and self.is_cache_valid(endpoint):
                logger.info(f"Using cached data for {endpoint}")
                return self.cache[endpoint]

            url = f"{self.base_url}{endpoint}"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()

            self.cache[endpoint] = data
            self.cache_time[endpoint] = datetime.now()

            logger.info(f"Fetched fresh data from {endpoint}")
            return data

        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {endpoint}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching {endpoint}: {e} - {getattr(e.response, 'text', '')}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error for {endpoint}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {endpoint}: {str(e)}")
            return None

    def clear_cache(self):
        self.cache.clear()
        self.cache_time.clear()
        logger.info("Cache cleared")

    def fetch_all_pages(self, base_endpoint, max_pages=200):
        """Follow Laravel-style pagination (?page=1, 2, 3...) and collect
        every item across all pages, not just the first page.

        Handles the common response shapes:
          {"current_page": 1, "last_page": 5, "data": [...]}
          {"current_page": 1, "total": 120, "per_page": 15, "data": [...]}
          {"data": [...], "meta": {"last_page": 5}}
          [...]  (a plain list, no pagination at all)

        Stops when: last_page is reached, a page returns no new items,
        or max_pages is hit (safety net against an infinite loop if the
        API's pagination fields don't match what we expect).
        """
        all_items = []
        seen_ids = set()
        page = 1
        separator = "&" if "?" in base_endpoint else "?"

        while page <= max_pages:
            endpoint = f"{base_endpoint}{separator}page={page}"
            data = self.fetch(endpoint)

            if data is None:
                break

            # Plain list response, no pagination wrapper at all
            if isinstance(data, list):
                items = data
                last_page = 1
            else:
                items = data.get('data', [])
                # meta may be nested (e.g. {"meta": {"last_page": N}}) or flat
                meta = data.get('meta', {}) if isinstance(data.get('meta'), dict) else {}
                last_page = (
                    data.get('last_page')
                    or meta.get('last_page')
                    or data.get('total_pages')
                )
                if last_page is None:
                    # Try to derive it from total/per_page if present
                    total = data.get('total') or meta.get('total')
                    per_page = data.get('per_page') or meta.get('per_page') or len(items) or 1
                    if total:
                        last_page = max(1, -(-int(total) // int(per_page)))  # ceil division

            if not items:
                break

            new_count = 0
            for item in items:
                item_id = item.get('id') if isinstance(item, dict) else None
                if item_id is not None:
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                all_items.append(item)
                new_count += 1

            # No new items on this page -> we've looped back or hit the end
            if new_count == 0:
                break

            if last_page is not None and page >= int(last_page):
                break

            # If there's no pagination info at all and we got a full page
            # of items, we can't safely guess whether more exist, so stop
            # after page 1 to avoid hammering the API forever.
            if last_page is None and len(items) < 15:
                break
            if last_page is None and page >= 1 and isinstance(data, list):
                break

            page += 1

        logger.info(f"fetch_all_pages: collected {len(all_items)} items from {base_endpoint} across {page} page(s)")
        return all_items


api = APIHandler(API_BASE_URL, JEJELAYE_API_KEY)


# ==================== USER MANAGEMENT ====================
class UserManager:
    @staticmethod
    def add_user(user_id, username, first_name, last_name=""):
        db.execute_query(
            'INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
            (user_id, username, first_name, last_name)
        )

    @staticmethod
    def update_last_active(user_id):
        db.execute_query(
            'UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?',
            (user_id,)
        )

    @staticmethod
    def get_user(user_id):
        return db.fetch_one('SELECT * FROM users WHERE user_id = ?', (user_id,))

    @staticmethod
    def get_balance(user_id):
        result = db.fetch_one('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        return result[0] if result else 0

    @staticmethod
    def add_balance(user_id, amount, description=""):
        db.execute_query(
            'UPDATE users SET balance = balance + ? WHERE user_id = ?',
            (amount, user_id)
        )
        if description:
            db.execute_query(
                'INSERT INTO transactions (user_id, type, amount, product, status) VALUES (?, ?, ?, ?, ?)',
                (user_id, 'credit', amount, description, 'completed')
            )

    @staticmethod
    def deduct_balance(user_id, amount):
        balance = UserManager.get_balance(user_id)
        if balance >= amount:
            db.execute_query(
                'UPDATE users SET balance = balance - ? WHERE user_id = ?',
                (amount, user_id)
            )
            return True
        return False

    @staticmethod
    def get_user_stats(user_id):
        user = UserManager.get_user(user_id)
        if not user:
            return None
        return {
            'user_id': user[0],
            'username': user[1],
            'balance': user[4],
            'total_spent': user[5],
            'total_purchases': user[6],
            'total_profit': user[7],
            'created_at': user[10],
            'last_active': user[11]
        }


# ==================== DECORATORS ====================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            if update.message:
                await update.message.reply_text("❌ Admin access denied.")
            elif update.callback_query:
                await update.callback_query.answer("❌ Admin access denied.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ==================== HELPERS ====================
def get_main_keyboard(user_id):
    keyboard = [
        [KeyboardButton("🛍️ Browse Services"), KeyboardButton("💰 My Balance")],
        [KeyboardButton("📊 My Stats"), KeyboardButton("📞 Support")],
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton("👨‍💼 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def format_service_line(idx, service):
    name = service.get('name', f'Service {idx}')
    price = float(service.get('selling_price', 0))
    markup_price = round(price * (1 + MARKUP_PERCENTAGE / 100), 2)
    category = service.get('category', {}).get('name', '') if service.get('category') else ''
    return name, markup_price, category


# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - captivating welcome, collected after we know their name"""
    user = update.effective_user
    is_new = UserManager.get_user(user.id) is None
    UserManager.add_user(user.id, user.username, user.first_name, user.last_name)
    UserManager.update_last_active(user.id)

    reply_markup = get_main_keyboard(user.id)

    welcome_text = (
        f"👋 Welcome, {user.first_name}!\n\n"
        f"🏪 *{BUSINESS_NAME}* — your one-stop shop for premium data, airtime, "
        f"electricity, cable TV and more, at unbeatable rates. ⚡\n\n"
        "💳 Fund your wallet, browse services, and get instant delivery — "
        "no stress, no delays.\n\n"
        "👇 Tap a button below to get started!"
    )

    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')


PAGE_SIZE = 10

# Top-level product types we sell. Everything else the API might offer
# (airtime, electricity, etc.) is intentionally left out per business focus.
TOP_LEVEL_TYPES = [
    {"key": "logs",   "label": "🔐 Buy Logs",     "type": "buy_logs",     "match": ["log"]},
    {"key": "boost",  "label": "🚀 Social Boost",  "type": "social_boost", "match": ["boost", "social"]},
]

# In-memory cache of {top_level_key: {sub_category_name: [services]}}
# Rebuilt whenever the underlying service cache is refreshed.
_subcategory_cache = {}
_subcategory_cache_time = {}
_SUBCATEGORY_CACHE_DURATION = 300  # 5 minutes


def get_top_level_by_key(key):
    return next((t for t in TOP_LEVEL_TYPES if t["key"] == key), None)


def fetch_services_for_top_level(top):
    """Pull every service under a top-level type across ALL pages.
    Falls back to fetching all services and keyword-matching if the
    type= filter returns nothing (e.g. wrong slug)."""
    services = api.fetch_all_pages(f"/services?type={top['type']}")
    services = [s for s in services if s.get('is_active', True)]

    if services:
        return services

    all_services = api.fetch_all_pages("/services")
    all_services = [s for s in all_services if s.get('is_active', True)]

    matched = []
    for s in all_services:
        metadata = s.get('metadata') or {}
        cat_name = (s.get('category', {}) or {}).get('name', '').lower()
        sub_cat_name = (metadata.get('category') or '').lower()
        service_name = (s.get('name', '') or '').lower()
        haystack = f"{cat_name} {sub_cat_name} {service_name}"
        if any(kw in haystack for kw in top["match"]):
            matched.append(s)
    return matched


def get_subcategories(top_key):
    """Group a top-level type's services by their REAL sub-category, which
    the jejelaye API stores at metadata.category (e.g. "RANDOM COUNTRIES Fb",
    "Facebook New Account", "Gmail", etc) — NOT the outer category.name
    field, which is always the same top-level label (e.g. "Buy Logs") for
    every item under that type and therefore useless for grouping.
    Returns a dict {category_name: [services]}, sorted by name."""
    now = datetime.now()
    cached_at = _subcategory_cache_time.get(top_key)
    if cached_at and (now - cached_at).total_seconds() < _SUBCATEGORY_CACHE_DURATION:
        return _subcategory_cache[top_key]

    top = get_top_level_by_key(top_key)
    services = fetch_services_for_top_level(top) if top else []

    grouped = {}
    for s in services:
        metadata = s.get('metadata') or {}
        # Real sub-category lives in metadata.category (a plain string).
        # Fall back to the outer category.name only if metadata.category
        # is missing, so nothing silently disappears from the list.
        sub_name = metadata.get('category') or (s.get('category', {}) or {}).get('name') or "Other"
        grouped.setdefault(sub_name, []).append(s)

    # Sort sub-categories alphabetically, and keep "Other" last if present
    sorted_grouped = dict(sorted(grouped.items(), key=lambda kv: (kv[0] == "Other", kv[0])))

    _subcategory_cache[top_key] = sorted_grouped
    _subcategory_cache_time[top_key] = now
    return sorted_grouped


async def browse_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the top-level type menu: Buy Logs / Social Boost"""
    UserManager.update_last_active(update.effective_user.id)

    text = (
        "🛍️ *SERVICES MARKETPLACE*\n"
        + ("═" * 30) + "\n\n"
        "Choose a category to browse:"
    )

    keyboard = [[InlineKeyboardButton(t["label"], callback_data=f"top_{t['key']}")] for t in TOP_LEVEL_TYPES]
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def browse_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to the top-level type menu"""
    query = update.callback_query
    await query.answer()

    text = (
        "🛍️ *SERVICES MARKETPLACE*\n"
        + ("═" * 30) + "\n\n"
        "Choose a category to browse:"
    )
    keyboard = [[InlineKeyboardButton(t["label"], callback_data=f"top_{t['key']}")] for t in TOP_LEVEL_TYPES]
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def top_level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User picked Buy Logs or Social Boost -> show its sub-categories"""
    query = update.callback_query
    await query.answer()

    top_key = query.data.replace("top_", "")
    await show_subcategory_menu(query, top_key, page=0)


SUBCAT_PAGE_SIZE = 10


async def show_subcategory_menu(query, top_key, page=0):
    top = get_top_level_by_key(top_key)
    if not top:
        await query.edit_message_text("❌ Unknown category.")
        return

    await query.edit_message_text(f"⏳ Loading {top['label']}...")

    subcats = get_subcategories(top_key)  # dict {name: [services]}
    names = list(subcats.keys())

    if not names:
        keyboard = [
            [InlineKeyboardButton("🔙 Back", callback_data="browse_menu")],
            [InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            f"❌ No sub-categories available in {top['label']} right now.\n\n"
            "Try again later or contact support.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    total_pages = max(1, (len(names) + SUBCAT_PAGE_SIZE - 1) // SUBCAT_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * SUBCAT_PAGE_SIZE
    page_names = names[start:start + SUBCAT_PAGE_SIZE]

    text = (
        f"{top['label']}  (Page {page + 1} of {total_pages})\n"
        + ("═" * 30) + "\n\n"
        f"{len(names)} sub-categories available. Choose one:"
    )

    keyboard = []
    for name in page_names:
        count = len(subcats[name])
        label = f"{name} ({count})"
        # Encode the subcategory as its index in the full sorted list so
        # callback_data stays short even for long category names.
        idx = names.index(name)
        keyboard.append([InlineKeyboardButton(label, callback_data=f"sub|{top_key}|{idx}|0")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"subpage|{top_key}|{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"subpage|{top_key}|{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🔙 Categories", callback_data="browse_menu")])
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def subcategory_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Next/Prev pagination across the sub-category list itself"""
    query = update.callback_query
    await query.answer()
    _, top_key, page_str = query.data.split("|", 2)
    await show_subcategory_menu(query, top_key, page=int(page_str))


async def subcategory_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User picked a sub-category -> show its products, paginated.
    callback_data format: sub_{top_key}_{subcat_index}_{page}"""
    query = update.callback_query
    await query.answer()

    _, top_key, subcat_idx_str, page_str = query.data.split("|", 3)
    await show_products_page(query, top_key, int(subcat_idx_str), int(page_str))


async def show_products_page(query, top_key, subcat_idx, page):
    top = get_top_level_by_key(top_key)
    subcats = get_subcategories(top_key)
    names = list(subcats.keys())

    if not top or subcat_idx >= len(names):
        await query.edit_message_text("❌ This category is no longer available.")
        return

    subcat_name = names[subcat_idx]
    services = subcats[subcat_name]

    total = len(services)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    page_items = services[start:start + PAGE_SIZE]

    text = (
        f"🔐 {subcat_name}  (Page {page + 1} of {total_pages} — {total} items)\n"
        + ("═" * 30) + "\n\n"
        "Tap a service below to buy."
    )

    keyboard = []
    for service in page_items:
        service_id = service.get('id')
        name, price, _ = format_service_line(0, service)
        label = f"{name[:28]} — ₦{price:,.2f}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"buy|{top_key}|{subcat_idx}|{service_id}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sub|{top_key}|{subcat_idx}|{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sub|{top_key}|{subcat_idx}|{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🔙 Sub-categories", callback_data=f"top_{top_key}")])
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def buy_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a user tapping a specific service to buy.
    callback_data format: buy_{top_key}_{subcat_idx}_{service_id}"""
    query = update.callback_query
    await query.answer()

    _, top_key, subcat_idx_str, service_id = query.data.split("|", 3)
    subcats = get_subcategories(top_key)
    names = list(subcats.keys())
    subcat_idx = int(subcat_idx_str)

    if subcat_idx >= len(names):
        await query.edit_message_text("❌ This service is no longer available.")
        return

    services = subcats[names[subcat_idx]]
    service = next((s for s in services if str(s.get('id')) == service_id), None)
    if not service:
        await query.edit_message_text("❌ This service is no longer available.")
        return

    name, price, category = format_service_line(0, service)
    user_id = query.from_user.id
    balance = UserManager.get_balance(user_id)

    text = (
        f"🛒 *{name}*\n"
        f"📂 Category: {category or 'General'}\n"
        f"💵 Price: ₦{price:,.2f}\n\n"
        f"💰 Your balance: ₦{balance:,.2f}\n\n"
    )

    if balance < price:
        text += "⚠️ Insufficient balance. Please top up your wallet first."
        keyboard = [
            [InlineKeyboardButton("➕ Top Up Balance", callback_data="request_balance")],
            [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
        ]
    else:
        text += "Tap confirm to complete this purchase."
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm|{top_key}|{subcat_idx}|{service_id}")],
            [InlineKeyboardButton("🏠 Cancel", callback_data="main_menu")]
        ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def confirm_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually deduct balance and log the purchase.
    callback_data format: confirm_{top_key}_{subcat_idx}_{service_id}
    NOTE: This does not yet call a jejelaye purchase/order endpoint —
    ask your API engineer for the exact request body needed (e.g. delivery
    email, recipient info) before wiring real fulfillment through
    POST /services/{service_id}/purchase."""
    query = update.callback_query
    await query.answer()

    _, top_key, subcat_idx_str, service_id = query.data.split("|", 3)
    subcats = get_subcategories(top_key)
    names = list(subcats.keys())
    subcat_idx = int(subcat_idx_str)

    if subcat_idx >= len(names):
        await query.edit_message_text("❌ This service is no longer available.")
        return

    services = subcats[names[subcat_idx]]
    service = next((s for s in services if str(s.get('id')) == service_id), None)

    if not service:
        await query.edit_message_text("❌ This service is no longer available.")
        return

    name, price, _ = format_service_line(0, service)
    user_id = query.from_user.id

    if not UserManager.deduct_balance(user_id, price):
        await query.edit_message_text("⚠️ Insufficient balance. Purchase cancelled.")
        return

    db.execute_query(
        'INSERT INTO transactions (user_id, type, amount, product, service_id, status) VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, 'purchase', price, name, service_id, 'completed')
    )
    db.execute_query(
        'UPDATE users SET total_spent = total_spent + ?, total_purchases = total_purchases + 1 WHERE user_id = ?',
        (price, user_id)
    )

    new_balance = UserManager.get_balance(user_id)
    await query.edit_message_text(
        f"✅ Purchase successful!\n\n"
        f"🛍️ {name}\n"
        f"💵 ₦{price:,.2f} deducted\n"
        f"💰 New balance: ₦{new_balance:,.2f}\n\n"
        f"Delivery will be processed shortly."
    )


async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show balance and give the top-up option"""
    user_id = update.effective_user.id
    UserManager.add_user(user_id, update.effective_user.username, update.effective_user.first_name)
    UserManager.update_last_active(user_id)

    stats = UserManager.get_user_stats(user_id)

    balance_text = (
        "💰 *YOUR WALLET*\n"
        + ("═" * 30) + "\n\n"
        f"💵 Current Balance: ₦{stats['balance']:,.2f}\n"
        f"💸 Total Spent: ₦{stats['total_spent']:,.2f}\n"
        f"📦 Total Purchases: {stats['total_purchases']}\n\n"
        f"📅 Member Since: {stats['created_at']}\n"
    )

    keyboard = [
        [InlineKeyboardButton("➕ Top Up Balance", callback_data="request_balance")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(balance_text, reply_markup=reply_markup, parse_mode='Markdown')


async def request_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bank transfer details and let the user say 'I've paid'"""
    query = update.callback_query
    await query.answer()

    text = (
        "➕ *TOP UP YOUR WALLET*\n"
        + ("═" * 30) + "\n\n"
        "Make a bank transfer to:\n\n"
        f"🏦 Bank: *{BANK_NAME}*\n"
        f"🔢 Account Number: `{BANK_ACCOUNT_NUMBER}`\n"
        f"👤 Account Name: *{BANK_ACCOUNT_NAME}*\n\n"
        "After sending the money, tap the button below and enter the amount. "
        "We'll notify our admin to confirm and credit your wallet."
    )

    keyboard = [
        [InlineKeyboardButton("✅ I've Made the Transfer", callback_data="confirm_transfer")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def confirm_transfer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user how much they sent"""
    query = update.callback_query
    await query.answer()

    context.user_data['awaiting_topup_amount'] = True

    await query.edit_message_text(
        "💬 Please type the exact amount you transferred (e.g. `5000`)."
    )


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    UserManager.update_last_active(user_id)

    stats = UserManager.get_user_stats(user_id)
    transactions = db.fetch_all(
        'SELECT type, amount, product, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 8',
        (user_id,)
    )

    avg_purchase = stats['total_spent'] / stats['total_purchases'] if stats['total_purchases'] > 0 else 0

    stats_text = (
        "📊 *YOUR STATISTICS*\n"
        + ("═" * 30) + "\n\n"
        f"💰 Current Balance: ₦{stats['balance']:,.2f}\n"
        f"💸 Total Spent: ₦{stats['total_spent']:,.2f}\n"
        f"📈 Average Per Purchase: ₦{avg_purchase:,.2f}\n"
        f"📦 Total Purchases: {stats['total_purchases']}\n\n"
    )

    if transactions:
        stats_text += "*Recent Activity:*\n"
        for trans in transactions[:5]:
            stats_text += f"• {trans[0].upper()}: ₦{trans[1]:,.2f} - {trans[2]}\n"

    keyboard = [[InlineKeyboardButton("🏠 Back", callback_data="main_menu")]]
    await update.message.reply_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    UserManager.update_last_active(update.effective_user.id)

    support_text = (
        "📞 *SUPPORT*\n"
        + ("═" * 30) + "\n\n"
        "Having an issue? Reach out and we'll sort you out quickly.\n\n"
        "💬 Telegram: @magicnigga\n"
        "📱 WhatsApp: +2348144841843\n"
    )

    keyboard = [[InlineKeyboardButton("🏠 Back", callback_data="main_menu")]]
    await update.message.reply_text(support_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    UserManager.update_last_active(update.effective_user.id)

    pending = db.fetch_all("SELECT COUNT(*) FROM topup_requests WHERE status = 'pending'")
    pending_count = pending[0][0] if pending else 0

    admin_text = (
        "👨‍💼 *ADMIN PANEL*\n"
        + ("═" * 30) + "\n\n"
        f"🔔 Pending top-up requests: {pending_count}\n"
    )

    keyboard = [
        [InlineKeyboardButton(f"💳 Pending Top-Ups ({pending_count})", callback_data="admin_pending_topups")],
        [InlineKeyboardButton("🔄 Refresh Service Cache", callback_data="admin_refresh")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    await update.message.reply_text(admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


@admin_only
async def admin_pending_topups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pending = db.fetch_all(
        "SELECT id, user_id, amount, created_at FROM topup_requests WHERE status = 'pending' ORDER BY created_at ASC LIMIT 10"
    )

    if not pending:
        await query.edit_message_text("✅ No pending top-up requests.")
        return

    keyboard = []
    text = "💳 *PENDING TOP-UPS*\n\n"
    for req_id, user_id, amount, created_at in pending:
        text += f"#{req_id} — User {user_id} — ₦{amount:,.2f}\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ Approve #{req_id}", callback_data=f"approve_topup_{req_id}"),
            InlineKeyboardButton(f"❌ Reject #{req_id}", callback_data=f"reject_topup_{req_id}")
        ])

    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


@admin_only
async def admin_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    api.clear_cache()
    await query.edit_message_text("🔄 Service cache cleared. Next browse will fetch fresh data.")


async def approve_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin taps Yes on a top-up notification -> credits the user automatically"""
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("❌ Admin only.", show_alert=True)
        return
    await query.answer()

    req_id = query.data.replace("approve_topup_", "")
    req = db.fetch_one("SELECT user_id, amount, status FROM topup_requests WHERE id = ?", (req_id,))

    if not req:
        await query.edit_message_text("❌ Request not found.")
        return

    user_id, amount, status = req
    if status != 'pending':
        await query.edit_message_text(f"⚠️ This request was already {status}.")
        return

    UserManager.add_balance(user_id, amount, description="Wallet top-up (bank transfer)")
    db.execute_query(
        "UPDATE topup_requests SET status = 'approved', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (req_id,)
    )

    await query.edit_message_text(f"✅ Approved. ₦{amount:,.2f} credited to user {user_id}.")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your top-up of ₦{amount:,.2f} has been confirmed and added to your wallet!"
        )
    except Exception as e:
        logger.error(f"Could not notify user {user_id}: {e}")


async def reject_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("❌ Admin only.", show_alert=True)
        return
    await query.answer()

    req_id = query.data.replace("reject_topup_", "")
    req = db.fetch_one("SELECT user_id, amount, status FROM topup_requests WHERE id = ?", (req_id,))

    if not req:
        await query.edit_message_text("❌ Request not found.")
        return

    user_id, amount, status = req
    if status != 'pending':
        await query.edit_message_text(f"⚠️ This request was already {status}.")
        return

    db.execute_query(
        "UPDATE topup_requests SET status = 'rejected', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (req_id,)
    )

    await query.edit_message_text(f"❌ Rejected top-up request #{req_id}.")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Your top-up request of ₦{amount:,.2f} could not be confirmed. "
                 f"Please contact support with your payment proof."
        )
    except Exception as e:
        logger.error(f"Could not notify user {user_id}: {e}")


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏠 Main Menu — use the buttons below to navigate.")


# ==================== TEXT MESSAGE HANDLER (menu buttons + free text) ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # If we're waiting for a top-up amount, handle that first
    if context.user_data.get('awaiting_topup_amount'):
        try:
            amount = float(text.replace(',', '').replace('₦', '').strip())
        except ValueError:
            await update.message.reply_text("⚠️ Please enter a valid number, e.g. 5000")
            return

        context.user_data['awaiting_topup_amount'] = False

        req_id = db.execute_query(
            "INSERT INTO topup_requests (user_id, amount, status) VALUES (?, ?, 'pending')",
            (user_id, amount)
        )

        await update.message.reply_text(
            f"✅ Got it! Your top-up request of ₦{amount:,.2f} has been sent for confirmation. "
            f"You'll be notified once it's approved."
        )

        # Notify admin(s) with a one-tap approve button
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_topup_{req_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_topup_{req_id}")
        ]]
        username = update.effective_user.username or update.effective_user.first_name
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"🔔 *New Top-Up Request*\n\n"
                        f"👤 User: @{username} (ID: {user_id})\n"
                        f"💵 Amount: ₦{amount:,.2f}\n\n"
                        f"Tap to confirm the bank transfer was received."
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Could not notify admin {admin_id}: {e}")
        return

    # Menu button routing
    if text == "🛍️ Browse Services":
        await browse_services(update, context)
    elif text == "💰 My Balance":
        await show_balance(update, context)
    elif text == "📊 My Stats":
        await show_statistics(update, context)
    elif text == "📞 Support":
        await show_support(update, context)
    elif text == "👨‍💼 Admin Panel":
        await admin_panel(update, context)
    else:
        await update.message.reply_text(
            "I didn't understand that.\n\nPlease use the menu buttons below. 👇"
        )


# ==================== CALLBACK QUERY ROUTER ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "main_menu":
        await main_menu_callback(update, context)
    elif data == "browse_menu":
        await browse_menu_callback(update, context)
    elif data.startswith("top_"):
        await top_level_callback(update, context)
    elif data.startswith("subpage|"):
        await subcategory_page_callback(update, context)
    elif data.startswith("sub|"):
        await subcategory_products_callback(update, context)
    elif data.startswith("buy|"):
        await buy_service_callback(update, context)
    elif data.startswith("confirm|"):
        await confirm_purchase_callback(update, context)
    elif data == "request_balance":
        await request_balance_callback(update, context)
    elif data == "confirm_transfer":
        await confirm_transfer_callback(update, context)
    elif data == "admin_pending_topups":
        await admin_pending_topups_callback(update, context)
    elif data == "admin_refresh":
        await admin_refresh_callback(update, context)
    elif data.startswith("approve_topup_"):
        await approve_topup_callback(update, context)
    elif data.startswith("reject_topup_"):
        await reject_topup_callback(update, context)
    else:
        await query.answer()


# ==================== ERROR HANDLER ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")


# ==================== MAIN ====================
def main():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not JEJELAYE_API_KEY:
        missing.append("JEJELAYE_API_KEY")
    if not ADMIN_IDS:
        missing.append("ADMIN_IDS")

    if missing:
        logger.error(f"❌ Missing required environment variable(s): {', '.join(missing)}")
        logger.error("Set them before running, e.g.:")
        logger.error("  export TELEGRAM_BOT_TOKEN='your-token-from-botfather'")
        logger.error("  export JEJELAYE_API_KEY='your-api-key'")
        logger.error("  export ADMIN_IDS='7190018261'")
        return

    logger.info("🚀 Starting bot...")
    logger.info(f"📊 Markup: {MARKUP_PERCENTAGE}%")
    logger.info(f"👤 Admins: {len(ADMIN_IDS)}")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)

    logger.info("✅ Bot running... Ctrl+C to stop")
    app.run_polling()


if __name__ == '__main__':
    main()
