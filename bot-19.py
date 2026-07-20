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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8867593499:AAFs7L3Itycx-YJx9hbACpDODLpkaR6-qCo")
JEJELAYE_API_KEY = os.getenv("JEJELAYE_API_KEY", "172|LkO4Jcpfdfrb8TAgYmWCIDiuh9p1xBvvtAqkhrnAa44ff72c")
API_BASE_URL = "https://jejelayegct.com.ng/api/v1"
MARKUP_PERCENTAGE = float(os.getenv("MARKUP_PERCENTAGE", "30"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "7190018261").split(",")))

# Bank transfer details shown to users for manual top-up (EDIT THESE)
BANK_NAME = os.getenv("BANK_NAME", "YOUR BANK NAME")
BANK_ACCOUNT_NUMBER = os.getenv("BANK_ACCOUNT_NUMBER", "0000000000")
BANK_ACCOUNT_NAME = os.getenv("BANK_ACCOUNT_NAME", "YOUR ACCOUNT NAME")

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

# Known category "type" filters from the NewJejeLaye API docs, plus a
# friendly label and keywords to fall back on if the type filter returns
# nothing (some categories may use different type slugs than guessed).
SERVICE_CATEGORIES = [
    {"key": "airtime",          "label": "📱 Airtime",           "type": "airtime",         "match": ["airtime"]},
    {"key": "data",              "label": "📶 Data Bundles",       "type": "data",            "match": ["data"]},
    {"key": "electricity",       "label": "⚡ Electricity",        "type": "electricity",     "match": ["electric"]},
    {"key": "tv",                "label": "📺 Cable TV",           "type": "tv_subscription", "match": ["dstv", "gotv", "startimes", "tv"]},
    {"key": "education",         "label": "🎓 Education PIN",      "type": "education_pin",   "match": ["waec", "neco", "jamb", "education"]},
    {"key": "buy_logs",          "label": "🔐 Buy Logs",           "type": "buy_logs",        "match": ["log"]},
    {"key": "bulk_sms",          "label": "📢 Bulk SMS",           "type": "bulk_sms",        "match": ["sms"]},
    {"key": "social_boost",      "label": "🚀 Social Boost",       "type": "social_boost",    "match": ["boost", "social"]},
    {"key": "print_card",        "label": "🖨️ Recharge Cards",     "type": "print_card",      "match": ["recharge card", "print"]},
]


def get_category_by_key(key):
    return next((c for c in SERVICE_CATEGORIES if c["key"] == key), None)


def fetch_services_for_category(cat):
    """Try the API's type= filter first; fall back to fetching everything
    and matching by category name if the type filter returns nothing."""
    data = api.fetch(f"/services?type={cat['type']}")
    services = data.get('data', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    services = [s for s in services if s.get('is_active', True)]

    if services:
        return services

    # Fallback: fetch all, filter by category name / service name keywords
    data = api.fetch("/services")
    all_services = data.get('data', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    all_services = [s for s in all_services if s.get('is_active', True)]

    matched = []
    for s in all_services:
        cat_name = (s.get('category', {}) or {}).get('name', '').lower()
        service_name = (s.get('name', '') or '').lower()
        if any(kw in cat_name or kw in service_name for kw in cat["match"]):
            matched.append(s)
    return matched


async def browse_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the category menu first, not a flat product list"""
    UserManager.update_last_active(update.effective_user.id)

    text = (
        "🛍️ *SERVICES MARKETPLACE*\n"
        + ("═" * 30) + "\n\n"
        "Choose a category to browse:"
    )

    keyboard = []
    row = []
    for cat in SERVICE_CATEGORIES:
        row.append(InlineKeyboardButton(cat["label"], callback_data=f"cat_{cat['key']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User picked a category -> show page 1 of products in it"""
    query = update.callback_query
    await query.answer()

    cat_key = query.data.replace("cat_", "")
    await show_category_page(query, context, cat_key, page=0)


async def category_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Next/Prev pagination within a category"""
    query = update.callback_query
    await query.answer()

    # callback_data format: page_{cat_key}_{page_number}
    _, cat_key, page_str = query.data.split("_", 2)
    await show_category_page(query, context, cat_key, page=int(page_str))


async def show_category_page(query, context, cat_key, page):
    cat = get_category_by_key(cat_key)
    if not cat:
        await query.edit_message_text("❌ Unknown category.")
        return

    await query.edit_message_text(f"⏳ Loading {cat['label']}...")

    services = fetch_services_for_category(cat)

    if not services:
        keyboard = [[InlineKeyboardButton("🏠 Back", callback_data="main_menu")]]
        await query.edit_message_text(
            f"❌ No services available in {cat['label']} right now.\n\n"
            "Try again later or contact support.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    total = len(services)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    page_items = services[start:start + PAGE_SIZE]

    text = (
        f"{cat['label']}  (Page {page + 1} of {total_pages})\n"
        + ("═" * 30) + "\n\n"
        "Tap a service below to buy."
    )

    keyboard = []
    for service in page_items:
        service_id = service.get('id')
        name, price, _ = format_service_line(0, service)
        label = f"{name[:28]} — ₦{price:,.2f}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"buy_{cat_key}_{service_id}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{cat_key}_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{cat_key}_{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🔙 Categories", callback_data="browse_menu")])
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def browse_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back button from a product page -> category menu again"""
    query = update.callback_query
    await query.answer()

    text = (
        "🛍️ *SERVICES MARKETPLACE*\n"
        + ("═" * 30) + "\n\n"
        "Choose a category to browse:"
    )

    keyboard = []
    row = []
    for cat in SERVICE_CATEGORIES:
        row.append(InlineKeyboardButton(cat["label"], callback_data=f"cat_{cat['key']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def buy_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a user tapping a specific service to buy.
    callback_data format: buy_{cat_key}_{service_id}"""
    query = update.callback_query
    await query.answer()

    _, cat_key, service_id = query.data.split("_", 2)
    cat = get_category_by_key(cat_key)
    services = fetch_services_for_category(cat) if cat else []

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
            [InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_{cat_key}_{service_id}")],
            [InlineKeyboardButton("🏠 Cancel", callback_data="main_menu")]
        ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def confirm_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually deduct balance and log the purchase.
    callback_data format: confirm_{cat_key}_{service_id}
    NOTE: This does not yet call a jejelaye purchase/order endpoint —
    ask your API engineer for the exact request body needed per category
    (e.g. phone number, meter number, recipient email) before wiring real
    fulfillment through POST /services/{service_id}/purchase."""
    query = update.callback_query
    await query.answer()

    _, cat_key, service_id = query.data.split("_", 2)
    cat = get_category_by_key(cat_key)
    services = fetch_services_for_category(cat) if cat else []
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
        "💬 Message the admin directly through this bot.\n"
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
    elif data.startswith("cat_"):
        await category_callback(update, context)
    elif data.startswith("page_"):
        await category_page_callback(update, context)
    elif data.startswith("buy_"):
        await buy_service_callback(update, context)
    elif data.startswith("confirm_") and not data.startswith("confirm_transfer"):
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
    if TELEGRAM_BOT_TOKEN in ("", "YOUR_TELEGRAM_BOT_TOKEN_HERE"):
        logger.error("❌ TELEGRAM_BOT_TOKEN not configured!")
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
