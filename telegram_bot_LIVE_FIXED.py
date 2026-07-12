#!/usr/bin/env python3
"""
🏪 CHUNG LAO STORE - TELEGRAM RESALE BOT
Production Ready - Ready to Go Live
Markup: 40% on all products
IMPROVED: Interactive buttons + Better API handling
"""

import logging
import json
import os
import sys
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import requests

# =====================================================
#                   ⚙️ CONFIGURATION
# =====================================================

# 🔴 CHANGE THESE VALUES BEFORE GOING LIVE 🔴
TELEGRAM_TOKEN = '8867593499:AAEmZMLV1tWUMUCFhY-s8blSb528f1L4OHY'  # Get from @BotFather
ADMIN_ID = 7190018261                     # Your Telegram ID (from @userinfobot)

# API Configuration
API_BASE_URL = 'https://ceoacc.com'
API_USERNAME = 'Bubu'       # Get from ceoacc.com
API_PASSWORD = 'Ukhuegbe1$'       # Get from ceoacc.com

# Business Settings
MARKUP_PERCENT = 40  # Sell at 140% of original price
CURRENCY = 'USD'
USDT_ADDRESS = '9iSxbfgskyBdXEfniWTZ4pGUi4qXRnRGSuFu8dAVanbZ'
ADMIN_USERNAME = '@magicnigga'

# File Configuration
DATA_FILE = 'users.json'
LOG_FILE = 'bot.log'

# =====================================================
#                   📋 SETUP LOGGING
# =====================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =====================================================
#                   💾 DATA MANAGEMENT
# =====================================================

def load_users():
    """Load users from storage"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            logger.error("Users file corrupted - starting fresh")
            return {}
    return {}

def save_users(users):
    """Save users to storage with backup"""
    try:
        if os.path.exists(DATA_FILE):
            os.rename(DATA_FILE, f"{DATA_FILE}.bak")
        with open(DATA_FILE, 'w') as f:
            json.dump(users, f, indent=2)
        logger.info(f"Saved {len(users)} users")
    except Exception as e:
        logger.error(f"Save error: {e}")
        if os.path.exists(f"{DATA_FILE}.bak"):
            os.rename(f"{DATA_FILE}.bak", DATA_FILE)

def ensure_user(uid):
    """Ensure user exists in database"""
    if uid not in users:
        users[uid] = {
            "balance": 0.0,
            "purchases": 0,
            "joined": datetime.now().isoformat()
        }
        save_users(users)

# Load users at startup
users = load_users()
logger.info(f"✅ Loaded {len(users)} users")

# =====================================================
#                   🔌 API FUNCTIONS
# =====================================================

def get_products():
    """Fetch all product categories from API"""
    try:
        url = f"{API_BASE_URL}/api/ListResource.php"
        params = {
            "username": API_USERNAME,
            "password": API_PASSWORD
        }
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            # Check various possible response formats
            if data.get("status") == "success" and "categories" in data:
                return data.get("categories", [])
            elif "categories" in data:
                return data.get("categories", [])
            elif isinstance(data, list):
                return data
            else:
                logger.warning(f"Unexpected API format: {data}")
                return []
        
        logger.warning(f"API returned status {r.status_code}")
        return []
    except requests.Timeout:
        logger.error("API timeout - server slow")
        return []
    except requests.ConnectionError:
        logger.error("API connection error")
        return []
    except Exception as e:
        logger.error(f"Get products error: {e}")
        return []

def buy_product(product_id, amount=1):
    """Purchase product from API"""
    try:
        url = f"{API_BASE_URL}/api/BResource.php"
        params = {
            "username": API_USERNAME,
            "password": API_PASSWORD,
            "id": product_id,
            "amount": amount
        }
        r = requests.get(url, params=params, timeout=15)
        
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                logger.info(f"Purchase success: product={product_id}")
                return data
        
        logger.warning(f"Purchase failed: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Buy product error: {e}")
        return None

# =====================================================
#                   🎯 KEYBOARD BUTTONS
# =====================================================

def get_main_menu():
    """Get main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💰 Check Balance", callback_data="menu_balance")],
        [InlineKeyboardButton("🛍️ Browse Products", callback_data="menu_products")],
        [InlineKeyboardButton("💵 Add Funds", callback_data="menu_deposit")],
        [InlineKeyboardButton("❓ Help", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    """Get back to main menu button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_main")]
    ])

# =====================================================
#                   🤖 BOT COMMANDS
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command with interactive menu"""
    uid = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "User"
    ensure_user(uid)
    
    welcome_text = (
        "🏪 *WELCOME TO CHUNG LAO STORE* 🏪\n\n"
        f"👋 Hello {user_name}!\n\n"
        "🔥 *Premium Social Accounts at Best Prices*\n"
        f"💸 *Markup: {MARKUP_PERCENT}% Above Cost*\n"
        "⚡ *Instant Account Delivery*\n"
        "🛡️ *100% Trusted & Safe*\n\n"
        "Choose an option below to get started! 👇"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )
    logger.info(f"New/Returning user: {uid}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command - now interactive"""
    help_text = (
        "❓ *CHUNG LAO STORE - HELP*\n\n"
        "🛒 *How to Buy:*\n"
        "1️⃣ Add funds via💵 Add Funds\n"
        "2️⃣ Browse🛍️ Browse Products\n"
        "3️⃣ Click product to purchase\n"
        "4️⃣ Get account instantly! ✨\n\n"
        "💡 *Pro Tips:*\n"
        "• Check balance anytime with 💰 Check Balance\n"
        "• All accounts delivered within seconds\n"
        "• No refunds but instant replacements\n\n"
        "📞 *Need Support?*\n"
        f"Contact: {ADMIN_USERNAME}"
    )
    
    await update.message.reply_text(
        help_text,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check balance - now interactive"""
    uid = str(update.effective_user.id)
    ensure_user(uid)
    
    bal = users[uid]["balance"]
    purchases = users[uid]["purchases"]
    
    balance_text = (
        f"💰 *YOUR WALLET*\n\n"
        f"💵 Balance: `${bal:.2f}`\n"
        f"📦 Total Purchases: {purchases}\n\n"
    )
    
    if bal < 5:
        balance_text += "⚠️ Low balance! Add funds to start shopping."
    else:
        balance_text += "✅ Ready to shop! Browse products now."
    
    await update.message.reply_text(
        balance_text,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )
    logger.info(f"Balance check: {uid} - ${bal:.2f}")

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deposit information - interactive"""
    deposit_text = (
        f"💵 *ADD FUNDS TO YOUR ACCOUNT*\n\n"
        f"Send USDT (TRC20) to:\n"
        f"`{USDT_ADDRESS}`\n\n"
        f"Then send proof to:\n"
        f"📱 {ADMIN_USERNAME}\n\n"
        f"Include:\n"
        f"✓ Transaction Hash\n"
        f"✓ Amount Sent\n"
        f"✓ Your Username\n\n"
        f"⏱ Credited within 10 minutes\n"
        f"🔒 Safe & Secure"
    )
    
    await update.message.reply_text(
        deposit_text,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )

async def products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse products - improved"""
    uid = str(update.effective_user.id)
    ensure_user(uid)
    
    loading = await update.message.reply_text("⏳ *Loading products...* 🔄", parse_mode='Markdown')
    logger.info(f"User {uid} browsing products")
    
    categories = get_products()
    
    if not categories:
        await loading.edit_text(
            "⚠️ *Products Temporarily Unavailable*\n\n"
            "The API is loading. Please try again in a moment.\n"
            "If issue persists, contact support: " + ADMIN_USERNAME,
            reply_markup=get_back_button(),
            parse_mode='Markdown'
        )
        return
    
    buttons = []
    for cat in categories[:12]:
        name = cat.get("name", "Category")
        cat_id = str(cat.get("id", ""))
        # Add emoji to category name
        buttons.append([
            InlineKeyboardButton(f"📁 {name}", callback_data=f"cat_{cat_id}")
        ])
    
    # Add back button
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_main")])
    
    product_text = (
        "🛍️ *SELECT A CATEGORY*\n\n"
        f"Available: {len(categories)} categories\n"
        "Click below to browse! 👇"
    )
    
    await loading.edit_text(
        product_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='Markdown'
    )

async def admin_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Credit user (ADMIN ONLY)"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ *Admin only*", parse_mode='Markdown')
        return
    
    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: `/credit <user_id> <amount>`\n"
            "Example: `/credit 123456789 100`",
            parse_mode='Markdown'
        )
        return
    
    try:
        user_id, amount = context.args[0], float(context.args[1])
        if amount <= 0:
            await update.message.reply_text("Amount must be > 0")
            return
        
        ensure_user(user_id)
        users[user_id]["balance"] += amount
        save_users(users)
        
        await update.message.reply_text(
            f"✅ *Credited ${amount:.2f}*\n"
            f"User: {user_id}\n"
            f"New Balance: ${users[user_id]['balance']:.2f}",
            parse_mode='Markdown'
        )
        logger.info(f"Admin credited {user_id}: ${amount}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: View statistics (ADMIN ONLY)"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ *Admin only*", parse_mode='Markdown')
        return
    
    total_users = len(users)
    total_balance = sum(u.get("balance", 0) for u in users.values())
    total_purchases = sum(u.get("purchases", 0) for u in users.values())
    
    await update.message.reply_text(
        f"📊 *STORE STATISTICS*\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💰 Total Balance: ${total_balance:.2f}\n"
        f"📦 Total Purchases: {total_purchases}\n"
        f"📈 Markup: {MARKUP_PERCENT}%",
        parse_mode='Markdown'
    )
    logger.info(f"Admin viewed stats")

# =====================================================
#                   🔘 CALLBACKS
# =====================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button clicks"""
    q = update.callback_query
    await q.answer()
    
    uid = str(q.from_user.id)
    ensure_user(uid)
    data = q.data
    
    try:
        # Main menu
        if data == "menu_main":
            await q.edit_message_text(
                "🏪 *CHUNG LAO STORE*\n\n"
                "Choose an option below 👇",
                reply_markup=get_main_menu(),
                parse_mode='Markdown'
            )
        
        # Balance
        elif data == "menu_balance":
            bal = users[uid]["balance"]
            purchases = users[uid]["purchases"]
            
            balance_text = (
                f"💰 *YOUR WALLET*\n\n"
                f"💵 Balance: `${bal:.2f}`\n"
                f"📦 Total Purchases: {purchases}\n\n"
            )
            
            if bal < 5:
                balance_text += "⚠️ Low balance! Add funds to start shopping."
            else:
                balance_text += "✅ Ready to shop! Browse products now."
            
            await q.edit_message_text(
                balance_text,
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        
        # Products
        elif data == "menu_products":
            await q.edit_message_text("⏳ *Loading products...* 🔄", parse_mode='Markdown')
            
            categories = get_products()
            
            if not categories:
                await q.edit_message_text(
                    "⚠️ *Products Temporarily Unavailable*\n\n"
                    "API is loading. Try again in a moment.",
                    reply_markup=get_back_button(),
                    parse_mode='Markdown'
                )
                return
            
            buttons = []
            for cat in categories[:12]:
                name = cat.get("name", "Category")
                cat_id = str(cat.get("id", ""))
                buttons.append([
                    InlineKeyboardButton(f"📁 {name}", callback_data=f"cat_{cat_id}")
                ])
            
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_main")])
            
            await q.edit_message_text(
                "🛍️ *SELECT A CATEGORY*\n\nClick below to browse! 👇",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode='Markdown'
            )
        
        # Deposit
        elif data == "menu_deposit":
            await q.edit_message_text(
                f"💵 *ADD FUNDS TO YOUR ACCOUNT*\n\n"
                f"Send USDT (TRC20) to:\n`{USDT_ADDRESS}`\n\n"
                f"Then send proof to: {ADMIN_USERNAME}\n\n"
                f"⏱ Credited within 10 minutes",
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        
        # Help
        elif data == "menu_help":
            await q.edit_message_text(
                f"❓ *CHUNG LAO STORE - HELP*\n\n"
                f"🛒 *How to Buy:*\n"
                f"1️⃣ Add funds\n2️⃣ Browse products\n"
                f"3️⃣ Click to buy\n4️⃣ Get instantly!\n\n"
                f"📞 Support: {ADMIN_USERNAME}",
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        
        # Category selection
        elif data.startswith("cat_"):
            cat_id = data[4:]
            categories = get_products()
            
            if not categories:
                await q.edit_message_text("❌ No products available")
                return
            
            found_cat = None
            for cat in categories:
                if str(cat.get("id")) == cat_id:
                    found_cat = cat
                    break
            
            if not found_cat:
                await q.edit_message_text("❌ Category not found")
                return
            
            products_list = found_cat.get("accounts", [])
            if not products_list:
                await q.edit_message_text("📭 No products in category")
                return
            
            text = "📦 *AVAILABLE PRODUCTS*\n\n"
            buttons = []
            
            for prod in products_list[:10]:
                try:
                    orig_price = float(prod.get("price", 0))
                    resale_price = round(orig_price * (1 + MARKUP_PERCENT/100), 2)
                    
                    name = prod.get("name", "Product")
                    pid = str(prod.get("id", ""))
                    stock = prod.get("amount", 0)
                    
                    buttons.append([
                        InlineKeyboardButton(
                            f"🛒 {name} - ${resale_price}",
                            callback_data=f"buy_{pid}_{resale_price}_{orig_price}"
                        )
                    ])
                    
                    text += f"• {name}\n  💰 ${resale_price} | 📦 Stock: {stock}\n"
                except Exception as e:
                    logger.error(f"Product error: {e}")
            
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_main")])
            
            await q.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode='Markdown'
            )
        
        # Product purchase
        elif data.startswith("buy_"):
            try:
                parts = data.split("_", 3)
                _, pid, your_price, orig_price = parts
                your_price = float(your_price)
                product_id = int(pid)
            except:
                await q.edit_message_text("❌ Invalid product")
                return
            
            bal = users[uid]["balance"]
            
            if bal < your_price:
                await q.edit_message_text(
                    f"❌ *INSUFFICIENT BALANCE*\n\n"
                    f"You have: `${bal:.2f}`\n"
                    f"Need: `${your_price:.2f}`\n"
                    f"Short: `${your_price - bal:.2f}`\n\n"
                    f"💵 Add funds to continue",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💵 Add Funds", callback_data="menu_deposit")],
                        [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")]
                    ]),
                    parse_mode='Markdown'
                )
                return
            
            # Deduct balance
            users[uid]["balance"] -= your_price
            save_users(users)
            
            # Purchase from API
            result = buy_product(product_id)
            
            if result:
                users[uid]["purchases"] += 1
                save_users(users)
                
                # Get account details
                account = result.get("lists", [{}])[0].get("account", "Account delivered")
                trans_id = result.get("trans_id", "N/A")
                
                await q.edit_message_text(
                    f"✅ *PURCHASE SUCCESSFUL!* 🎉\n\n"
                    f"Transaction: `{trans_id}`\n\n"
                    f"🔑 *ACCOUNT DETAILS*\n"
                    f"`{account}`\n\n"
                    f"💰 New Balance: `${users[uid]['balance']:.2f}`\n"
                    f"📦 Total Purchases: {users[uid]['purchases']}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛍️ Shop More", callback_data="menu_products")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]
                    ]),
                    parse_mode='Markdown'
                )
                logger.info(f"Purchase: {uid} - ${your_price:.2f}")
            else:
                # Refund on failure
                users[uid]["balance"] += your_price
                save_users(users)
                
                await q.edit_message_text(
                    f"❌ *PURCHASE FAILED*\n\n"
                    f"Product out of stock or API error\n"
                    f"💰 Balance refunded: `${your_price:.2f}`\n\n"
                    f"📞 Contact: {ADMIN_USERNAME}",
                    reply_markup=get_back_button(),
                    parse_mode='Markdown'
                )
                logger.warning(f"Purchase failed: {uid}")
    
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await q.edit_message_text(f"❌ Error: {str(e)}")

# =====================================================
#                   🚀 MAIN
# =====================================================

def main():
    """Start the bot"""
    
    # Validate config
    if TELEGRAM_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ ERROR: TELEGRAM_TOKEN not set!")
        print("Edit the script and add your token from @BotFather")
        sys.exit(1)
    
    if API_USERNAME == 'your_api_username':
        print("⚠️ WARNING: API credentials not configured")
        print("Bot will run but won't load products")
    
    print("=" * 60)
    print("🏪 CHUNG LAO STORE - TELEGRAM BOT 🏪")
    print("=" * 60)
    print(f"✅ Token: {TELEGRAM_TOKEN[:20]}...")
    print(f"✅ Admin ID: {ADMIN_ID}")
    print(f"✅ Markup: {MARKUP_PERCENT}%")
    print(f"✅ API: {API_BASE_URL}")
    print(f"✅ Users loaded: {len(users)}")
    print("=" * 60)
    print("🚀 BOT STARTING... (Fixed version with interactive buttons)")
    print("=" * 60)
    
    # Create application with proper event loop handling
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("deposit", deposit))
    app.add_handler(CommandHandler("credit", admin_credit))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("🏪 BOT STARTED")
    print("✅ Bot is LIVE and listening...")
    print("📱 Find your bot on Telegram and send /start")
    
    # Run with proper async handling
    try:
        app.run_polling()
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == '__main__':
    main()
