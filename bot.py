import os
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ChatAction
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler, CallbackContext
)
import logging
from functools import wraps
import sqlite3
import re

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8867593499:AAFs7L3Itycx-YJx9hbACpDODLpkaR6-qCo")
API_BASE_URL = "https://jejelayegct.com.ng/api/v1"
MARKUP_PERCENTAGE = float(os.getenv("MARKUP_PERCENTAGE", "30"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "7190018261").split(","))) if os.getenv("ADMIN_IDS") else [1234567890]

# States for conversation
BUYING, PAYMENT_PENDING = range(2)

# ==================== DATABASE ====================
class AdvancedDatabase:
    def __init__(self, db_path="bot_database.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
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
        
        # Transactions table
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
        
        # Promotions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                discount_percentage REAL,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Bot settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def execute_query(self, query, params=()):
        """Execute a query"""
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
        """Fetch one result"""
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
        """Fetch all results"""
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

# Initialize database
db = AdvancedDatabase()

# ==================== API HANDLER ====================
class APIHandler:
    def __init__(self, base_url):
        self.base_url = base_url
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 300  # 5 minutes
    
    def is_cache_valid(self, endpoint):
        """Check if cache is valid"""
        if endpoint not in self.cache_time:
            return False
        return datetime.now() - self.cache_time[endpoint] < timedelta(seconds=self.cache_duration)
    
    def fetch(self, endpoint):
        """Fetch data from API with caching"""
        try:
            # Check cache first
            if endpoint in self.cache and self.is_cache_valid(endpoint):
                logger.info(f"Using cached data for {endpoint}")
                return self.cache[endpoint]
            
            url = f"{self.base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Cache the result
            self.cache[endpoint] = data
            self.cache_time[endpoint] = datetime.now()
            
            logger.info(f"Fetched fresh data from {endpoint}")
            return data
        
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {endpoint}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error for {endpoint}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {endpoint}: {str(e)}")
            return None
    
    def clear_cache(self):
        """Clear all cache"""
        self.cache.clear()
        self.cache_time.clear()
        logger.info("Cache cleared")

# Initialize API handler
api = APIHandler(API_BASE_URL)

# ==================== USER MANAGEMENT ====================
class UserManager:
    @staticmethod
    def add_user(user_id, username, first_name, last_name=""):
        """Add user to database"""
        db.execute_query(
            'INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
            (user_id, username, first_name, last_name)
        )
    
    @staticmethod
    def update_last_active(user_id):
        """Update last active time"""
        db.execute_query(
            'UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?',
            (user_id,)
        )
    
    @staticmethod
    def get_user(user_id):
        """Get user info"""
        return db.fetch_one('SELECT * FROM users WHERE user_id = ?', (user_id,))
    
    @staticmethod
    def get_balance(user_id):
        """Get user balance"""
        result = db.fetch_one('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        return result[0] if result else 0
    
    @staticmethod
    def add_balance(user_id, amount, description=""):
        """Add balance"""
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
        """Deduct balance"""
        balance = UserManager.get_balance(user_id)
        if balance >= amount:
            db.execute_query(
                'UPDATE users SET balance = balance - ? WHERE user_id = ?',
                (amount, user_id)
            )
            return True
        return False
    
    @staticmethod
    def add_transaction(user_id, trans_type, amount, product, status="completed"):
        """Log transaction"""
        db.execute_query(
            'INSERT INTO transactions (user_id, type, amount, product, status) VALUES (?, ?, ?, ?, ?)',
            (user_id, trans_type, amount, product, status)
        )
    
    @staticmethod
    def get_user_stats(user_id):
        """Get user statistics"""
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
    """Check admin permission"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        user_data = UserManager.get_user(user_id)
        
        is_admin = user_id in ADMIN_IDS or (user_data and user_data[8] == 1)
        
        if not is_admin:
            await update.message.reply_text("❌ Admin access denied.")
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    UserManager.add_user(user.id, user.username, user.first_name, user.last_name)
    UserManager.update_last_active(user.id)
    
    keyboard = [
        [KeyboardButton("🛍️ Browse Services"), KeyboardButton("💰 My Balance")],
        [KeyboardButton("📊 My Stats"), KeyboardButton("🔔 Notifications")],
        [KeyboardButton("⚙️ Settings"), KeyboardButton("📞 Support")],
    ]
    
    # Add admin panel
    if user.id in ADMIN_IDS:
        keyboard.append([KeyboardButton("👨‍💼 Admin Panel")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = (
        f"👋 Welcome {user.first_name}! 🎉\n\n"
        "🤖 Advanced Service Marketplace Bot\n\n"
        "📋 What I can do:\n"
        "✅ Browse & buy premium services\n"
        "✅ Manage your wallet & balance\n"
        "✅ Track transactions & history\n"
        "✅ Get real-time notifications\n"
        f"✅ Enjoy {MARKUP_PERCENTAGE}% markup pricing\n\n"
        "👇 Choose an option to get started!"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def browse_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse services"""
    await update.message.reply_chat_action(ChatAction.TYPING)
    
    UserManager.update_last_active(update.effective_user.id)
    
    msg = await update.message.reply_text("⏳ Loading services from marketplace...\n\n🔄 Please wait...")
    
    # Fetch services
    data = api.fetch("/services")
    services = data if isinstance(data, list) else data.get('data', []) if isinstance(data, dict) else []
    
    if not services:
        await msg.edit_text(
            "❌ No services available.\n\n"
            "Try again later or contact support."
        )
        return
    
    # Limit to 15 services
    services = services[:15]
    
    browse_text = (
        "🛍️ **SERVICES MARKETPLACE**\n"
        "═" * 55 + "\n\n"
        "Click 'Buy' to purchase any service.\n"
        "Prices include {:.0f}% markup profit.\n\n".format(MARKUP_PERCENTAGE)
    )
    
    keyboard = []
    for idx, service in enumerate(services, 1):
        name = service.get('name', f'Service {idx}')[:30]
        service_id = service.get('id', str(idx))
        price = float(service.get('price', 0))
        markup_price = price * (1 + MARKUP_PERCENTAGE / 100)
        
        browse_text += f"{idx}️⃣ *{name}*\n"
        browse_text += f"   💵 ${price:.2f} → 📈 ${markup_price:.2f}\n"
        browse_text += f"   💎 Profit: ${markup_price - price:.2f}\n\n"
        
        button_text = f"Buy {name[:20]}"
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"buy_{service_id}_{markup_price}")
        ])
    
    keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(browse_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show balance"""
    user_id = update.effective_user.id
    UserManager.add_user(user_id, update.effective_user.username, update.effective_user.first_name)
    UserManager.update_last_active(user_id)
    
    stats = UserManager.get_user_stats(user_id)
    
    balance_text = (
        "💰 **YOUR WALLET**\n"
        "═" * 55 + "\n\n"
        f"💵 *Current Balance:* ${stats['balance']:,.2f}\n"
        f"💸 *Total Spent:* ${stats['total_spent']:,.2f}\n"
        f"📦 *Total Purchases:* {stats['total_purchases']}\n"
        f"💎 *Total Profit Earned:* ${stats['total_profit']:,.2f}\n\n"
        f"📅 *Member Since:* {stats['created_at']}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Request Balance", callback_data="request_balance")],
        [InlineKeyboardButton("💳 Payment Methods", callback_data="payment_methods")],
        [InlineKeyboardButton("📜 Transaction History", callback_data="transaction_history")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(balance_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed statistics"""
    user_id = update.effective_user.id
    UserManager.update_last_active(user_id)
    
    stats = UserManager.get_user_stats(user_id)
    transactions = db.fetch_all(
        'SELECT type, amount, product, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 8',
        (user_id,)
    )
    
    avg_purchase = stats['total_spent'] / stats['total_purchases'] if stats['total_purchases'] > 0 else 0
    
    stats_text = (
        "📊 **YOUR STATISTICS**\n"
        "═" * 55 + "\n\n"
        f"💰 Current Balance: ${stats['balance']:,.2f}\n"
        f"💸 Total Spent: ${stats['total_spent']:,.2f}\n"
        f"📈 Average Per Purchase: ${avg_purchase:.2f}\n"
        f"📦 Total Purchases: {stats['total_purchases']}\n"
        f"💎 Profit Earned: ${stats['total_profit']:,.2f}\n\n"
    )
    
    if transactions:
        stats_text += "**Recent Activities:**\n"
        for trans in transactions[:5]:
            stats_text += f"• {trans[0].upper()}: ${trans[1]:.2f} - {trans[2]}\n"
    
    keyboard = [[InlineKeyboardButton("🏠 Back", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show notifications"""
    UserManager.update_last_active(update.effective_user.id)
    
    notif_text = (
        "🔔 **NOTIFICATIONS**\n"
        "═" * 55 + "\n\n"
        "✅ No new notifications\n\n"
        "You'll get alerts for:\n"
        "• Transaction confirmations\n"
        "• Balance updates\n"
        "• New service releases\n"
        "• Special promotions\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔕 Mute Notifications", callback_data="mute_notif")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(notif_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show settings"""
    UserManager.update_last_active(update.effective_user.id)
    
    settings_text = (
        "⚙️ **SETTINGS**\n"
        "═" * 55 + "\n\n"
        "Customize your experience.\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🌍 Language", callback_data="setting_language")],
        [InlineKeyboardButton("🔐 Security", callback_data="setting_security")],
        [InlineKeyboardButton("📧 Email Settings", callback_data="setting_email")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show support"""
    UserManager.update_last_active(update.effective_user.id)
    
    support_text = (
        "📞 **SUPPORT CENTER**\n"
        "═" * 55 + "\n\n"
        "📧 Email: support@example.com\n"
        "💬 Chat: Available 24/7\n"
        "📱 Phone: +234 XXX XXXX XXXX\n\n"
        "Common Issues:\n"
        "• How to add balance?\n"
        "• Why is my transaction pending?\n"
        "• How to refund?\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("💬 Chat with Support", callback_data="chat_support")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(support_text, reply_markup=reply_markup, parse_mode='Markdown')

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    UserManager.update_last_active(update.effective_user.id)
    
    admin_text = (
        "👨‍💼 **ADMIN CONTROL PANEL**\n"
        "═" * 55 + "\n\n"
        "Full bot management & monitoring.\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("💳 Balance Management", callback_data="admin_balance")],
        [InlineKeyboardButton("📊 Analytics", callback_data="admin_analytics")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ Bot Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("🔄 Refresh Cache", callback_data="admin_refresh")],
        [InlineKeyboardButton("🏠 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')

@admin_only
async def admin_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Users page"""
    query = update.callback_query
    await query.answer()
    
    all_users = db.fetch_all('SELECT user_id, username, balance, total_spent, total_purchases, created_at FROM users ORDER BY created_at DESC LIMIT 15')
    
    users_text = (
        "👥 **USER MANAGEMENT**\n"
        "═" * 55 + "\n\n"
        f"📊 Total Users: {len(all_users)}\n\n"
        "**Active Users:**\n\n"
    )
    
    for user in all_users[:10]:
        username = user[1] or f"User_{user[0]}"
        users_text += f"• @{username}\n"
        users_text += f"  💰 Balance: ${user[2]:,.2f} | 💸 Spent: ${user[3]:,.2f} | 📦 Buys: {user[4]}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search")],
        [InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance_to_user")],
        [InlineKeyboardButton("🚫 Suspend User", callback_data="admin_suspend")],
        [InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(users_text, reply_markup=reply_markup, parse_mode='Markdown')

@admin_only
async def admin_analytics_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Analytics"""
    query = update.callback_query
    await query.answer()
    
    total_users = db.fetch_one('SELECT COUNT(*) FROM users')[0] or 0
    total_balance = db.fetch_one('SELECT SUM(balance) FROM users')[0] or 0
    total_spent = db.fetch_one('SELECT SUM(total_spent) FROM users')[0] or 0
    total_transactions = db.fetch_one('SELECT COUNT(*) FROM transactions')[0] or 0
    
    # Calculate profit
    total_profit = total_spent * (MARKUP_PERCENTAGE / 100)
    
    analytics_text = (
        "📊 **ANALYTICS DASHBOARD**\n"
        "═" * 55 + "\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💰 Total User Balance: ${total_balance:,.2f}\n"
        f"💸 Total Revenue: ${total_spent:,.2f}\n"
        f"💎 Total Profit: ${total_profit:,.2f}\n"
        f"📦 Total Transactions: {total_transactions}\n\n"
        f"📈 Avg Balance Per User: ${total_balance / total_users if total_users > 0 else 0:,.2f}\n"
        f"📈 Avg Revenue Per User: ${total_spent / total_users if total_users > 0 else 0:,.2f}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("📈 Detailed Report", callback_data="admin_report")],
        [InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(analytics_text, reply_markup=reply_markup, parse_mode='Markdown')

@admin_only
async def admin_settings_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Settings"""
    query = update.callback_query
    await query.answer()
    
    settings_text = (
        "⚙️ **BOT SETTINGS**\n"
        "═" * 55 + "\n\n"
        f"💹 Markup: {MARKUP_PERCENTAGE}%\n"
        f"🔌 API: {API_BASE_URL}\n"
        f"👨‍💼 Admins: {len(ADMIN_IDS)}\n\n"
        "Settings controlled via .env file\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Cache", callback_data="admin_refresh_cache")],
        [InlineKeyboardButton("📢 Send Broadcast", callback_data="admin_broadcast_msg")],
        [InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== CALLBACK HANDLERS ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    user_id = update.effective_user.id
    
    # Navigation
    if callback_data == "main_menu":
        msg = await query.edit_message_text("Loading menu...")
        await start(query, context)
    
    elif callback_data == "admin_menu":
        await admin_panel(query, context)
    
    # Services
    elif callback_data.startswith("buy_"):
        parts = callback_data.split("_")
        service_id = parts[1]
        price = float(parts[2]) if len(parts) > 2 else 0
        
        balance = UserManager.get_balance(user_id)
        
        if balance >= price:
            # Process purchase
            UserManager.deduct_balance(user_id, price)
            UserManager.add_transaction(user_id, "purchase", price, f"Service #{service_id}", "completed")
            
            # Update profit
            profit = price * (MARKUP_PERCENTAGE / 100)
            db.execute_query(
                'UPDATE users SET total_profit = total_profit + ?, total_purchases = total_purchases + 1 WHERE user_id = ?',
                (profit, user_id)
            )
            
            await query.edit_message_text(
                f"✅ **PURCHASE SUCCESSFUL**\n\n"
                f"💰 Amount: ${price:.2f}\n"
                f"💎 Profit Earned: ${profit:.2f}\n"
                f"📦 Service ID: {service_id}\n\n"
                f"New Balance: ${balance - price:.2f}"
            )
        else:
            await query.edit_message_text(
                f"❌ **INSUFFICIENT BALANCE**\n\n"
                f"💰 Price: ${price:.2f}\n"
                f"💵 Your Balance: ${balance:.2f}\n"
                f"❌ Needed: ${price - balance:.2f} more\n\n"
                "Click 'Request Balance' to add funds."
            )
    
    # Balance actions
    elif callback_data == "request_balance":
        await query.edit_message_text(
            "💳 **REQUEST BALANCE**\n\n"
            "Contact an admin to request balance.\n\n"
            "Admin will verify and add funds."
        )
    
    elif callback_data == "transaction_history":
        transactions = db.fetch_all(
            'SELECT type, amount, product, status, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
            (user_id,)
        )
        
        history_text = "📜 **TRANSACTION HISTORY**\n" + "═" * 55 + "\n\n"
        
        if transactions:
            for trans in transactions:
                history_text += f"{trans[0].upper()}: ${trans[1]:.2f}\n"
                history_text += f"  {trans[2]} - {trans[3]}\n"
                history_text += f"  {trans[4]}\n\n"
        else:
            history_text += "No transactions yet."
        
        keyboard = [[InlineKeyboardButton("🏠 Back", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(history_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    # Admin callbacks
    elif callback_data == "admin_users":
        await admin_users_page(update, context)
    
    elif callback_data == "admin_analytics":
        await admin_analytics_page(update, context)
    
    elif callback_data == "admin_settings":
        await admin_settings_page(update, context)
    
    elif callback_data == "admin_refresh":
        api.clear_cache()
        await query.edit_message_text("✅ Cache cleared successfully!")

# ==================== MESSAGE HANDLER ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages"""
    text = update.message.text
    user_id = update.effective_user.id
    UserManager.add_user(user_id, update.effective_user.username, update.effective_user.first_name, update.effective_user.last_name)
    UserManager.update_last_active(user_id)
    
    if text == "🛍️ Browse Services":
        await browse_services(update, context)
    elif text == "💰 My Balance":
        await show_balance(update, context)
    elif text == "📊 My Stats":
        await show_statistics(update, context)
    elif text == "🔔 Notifications":
        await show_notifications(update, context)
    elif text == "⚙️ Settings":
        await show_settings(update, context)
    elif text == "📞 Support":
        await show_support(update, context)
    elif text == "👨‍💼 Admin Panel":
        if user_id in ADMIN_IDS:
            await admin_panel(update, context)
        else:
            await update.message.reply_text("❌ Access denied.")
    else:
        await update.message.reply_text(
            "I didn't understand that.\n\n"
            "Please use the menu buttons."
        )

# ==================== ERROR HANDLER ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error: {context.error}")

# ==================== MAIN ====================
def main():
    """Start bot"""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("❌ TELEGRAM_BOT_TOKEN not configured!")
        logger.info("Set: export TELEGRAM_BOT_TOKEN='your-token'")
        logger.info("Set: export ADMIN_IDS='123456789,987654321'")
        return
    
    logger.info("🚀 Starting ultra-advanced bot...")
    logger.info(f"📊 Markup: {MARKUP_PERCENTAGE}%")
    logger.info(f"👨‍💼 Admins: {len(ADMIN_IDS)}")
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    logger.info("✅ Bot running... Ctrl+C to stop")
    app.run_polling()

if __name__ == '__main__':
    main()
