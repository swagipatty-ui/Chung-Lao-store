#!/usr/bin/env python3
"""
🏪 PROFESSIONAL SOCIAL ACCOUNTS RESALE BOT
Dual API Integration (CEOACC + JEJELAYE)
Unified Product Catalog with 100% Professional Interface
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
from typing import List, Dict, Tuple

# =====================================================
#                   ⚙️ CONFIGURATION
# =====================================================

# 🔴 CHANGE THESE VALUES BEFORE GOING LIVE 🔴
TELEGRAM_TOKEN = '8867593499:AAEmZMLV1tWUMUCFhY-s8blSb528f1L4OHY'  # Get from @BotFather
ADMIN_ID = 7190018261                     # Your Telegram ID (from @userinfobot)

# PRIMARY API Configuration (CEOACC)
PRIMARY_API_BASE_URL = 'https://ceoacc.com'
PRIMARY_API_USERNAME = 'Bubu'
PRIMARY_API_PASSWORD = 'Ukhuegbe1$'
PRIMARY_API_NAME = "CEOACC"

# SECONDARY API Configuration (JEJELAYE)
SECONDARY_API_BASE_URL = 'https://jejelayegct.com.ng/api/v1'
SECONDARY_API_TOKEN = '149|FgZo2xfcofM7AFTGwHLXFe1wQbygvSeJuzTPKhwec21d1df9'
SECONDARY_API_USERNAME = 'YUYU Bubu'
SECONDARY_API_PASSWORD = 'YOUR_PASSWORD_HERE'  # ⚠️ FILL THIS IN
SECONDARY_API_NAME = "JEJELAYE"

# Business Settings
MARKUP_PERCENT = 40  # Sell at 140% of original price
CURRENCY = 'USD'

# CEOACC (Primary API) returns prices in Chinese fen (1 yuan = 100 fen),
# denominated in CNY. We must convert fen -> yuan -> USD before markup.
# Update USD_TO_CNY_RATE periodically to reflect the current exchange rate.
CEOACC_PRICE_IS_FEN = True       # CEOACC raw "price" field is in fen (cents of yuan)
USD_TO_CNY_RATE = 7.2            # 1 USD = ~7.2 CNY (update as needed)
USDT_ADDRESS = '9iSxbfgskyBdXEfniWTZ4pGUi4qXRnRGSuFu8dAVanbZ'
ADMIN_USERNAME = '@magicnigga'
STORE_NAME = "🏪 PREMIUM ACCOUNTS STORE"

# File Configuration
DATA_FILE = 'users.json'
LOG_FILE = 'bot.log'
CACHE_FILE = 'products_cache.json'

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
            "joined": datetime.now().isoformat(),
            "purchase_history": []
        }
        save_users(users)

# Load users at startup
users = load_users()
logger.info(f"✅ Loaded {len(users)} users")

# =====================================================
#                   🔌 API FUNCTIONS - PRIMARY (CEOACC)
# =====================================================

def convert_ceoacc_price_to_usd(raw_price) -> float:
    """
    Convert a raw CEOACC price value to USD.
    CEOACC prices are in CNY fen (1 yuan = 100 fen).
    Example: raw "37500" -> 375.00 CNY -> ~52.08 USD (before markup)
    """
    try:
        fen = float(raw_price)
    except (TypeError, ValueError):
        return 0.0

    if CEOACC_PRICE_IS_FEN:
        yuan = fen / 100
    else:
        yuan = fen

    usd = yuan / USD_TO_CNY_RATE
    return round(usd, 4)

def get_primary_products():
    """Fetch all products from CEOACC API"""
    try:
        url = f"{PRIMARY_API_BASE_URL}/api/ListResource.php"
        params = {
            "username": PRIMARY_API_USERNAME,
            "password": PRIMARY_API_PASSWORD
        }
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success" and "categories" in data:
                return data.get("categories", []), PRIMARY_API_NAME
            elif "categories" in data:
                return data.get("categories", []), PRIMARY_API_NAME
            elif isinstance(data, list):
                return data, PRIMARY_API_NAME
        
        logger.warning(f"Primary API returned status {r.status_code}")
        return [], PRIMARY_API_NAME
    except requests.Timeout:
        logger.error("Primary API timeout")
        return [], PRIMARY_API_NAME
    except requests.ConnectionError:
        logger.error("Primary API connection error")
        return [], PRIMARY_API_NAME
    except Exception as e:
        logger.error(f"Primary API error: {e}")
        return [], PRIMARY_API_NAME

def buy_primary_product(product_id, amount=1):
    """Purchase product from CEOACC API"""
    try:
        url = f"{PRIMARY_API_BASE_URL}/api/BResource.php"
        params = {
            "username": PRIMARY_API_USERNAME,
            "password": PRIMARY_API_PASSWORD,
            "id": product_id,
            "amount": amount
        }
        r = requests.get(url, params=params, timeout=15)
        
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                logger.info(f"Purchase success: primary API - product={product_id}")
                return data, PRIMARY_API_NAME
        
        logger.warning(f"Primary purchase failed: {r.status_code}")
        return None, PRIMARY_API_NAME
    except Exception as e:
        logger.error(f"Primary buy error: {e}")
        return None, PRIMARY_API_NAME

# =====================================================
#                   🔌 API FUNCTIONS - SECONDARY (JEJELAYE)
# =====================================================

def get_secondary_products():
    """Fetch all products from JEJELAYE API"""
    try:
        url = f"{SECONDARY_API_BASE_URL}/products"  # Adjust endpoint based on API documentation
        headers = {
            "Authorization": f"Bearer {SECONDARY_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            
            # Handle different response formats
            if isinstance(data, dict):
                # Try common response wrapper formats
                products = data.get("data", data.get("products", data.get("items", [])))
                if isinstance(products, list):
                    # Convert to category format for compatibility
                    converted = convert_secondary_to_standard(products)
                    return converted, SECONDARY_API_NAME
            elif isinstance(data, list):
                converted = convert_secondary_to_standard(data)
                return converted, SECONDARY_API_NAME
        
        logger.warning(f"Secondary API returned status {r.status_code}")
        return [], SECONDARY_API_NAME
    except requests.Timeout:
        logger.error("Secondary API timeout")
        return [], SECONDARY_API_NAME
    except requests.ConnectionError:
        logger.error("Secondary API connection error")
        return [], SECONDARY_API_NAME
    except Exception as e:
        logger.error(f"Secondary API error: {e}")
        return [], SECONDARY_API_NAME

def convert_secondary_to_standard(products: List[Dict]) -> List[Dict]:
    """Convert JEJELAYE products to standard format"""
    try:
        # Group products by category
        categories = {}
        
        for prod in products:
            # Extract category
            category_name = prod.get("category", "General Products")
            
            if category_name not in categories:
                categories[category_name] = {
                    "id": len(categories),
                    "name": category_name,
                    "accounts": []
                }
            
            # Normalize product structure
            normalized_prod = {
                "id": prod.get("id", prod.get("product_id", "")),
                "name": prod.get("name", prod.get("title", "Product")),
                "price": float(prod.get("price", prod.get("cost", 0))),
                "amount": prod.get("stock", prod.get("quantity", 0)),
                "description": prod.get("description", ""),
                "api_source": SECONDARY_API_NAME
            }
            
            categories[category_name]["accounts"].append(normalized_prod)
        
        return list(categories.values())
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        return []

def buy_secondary_product(product_id, amount=1):
    """Purchase product from JEJELAYE API"""
    try:
        url = f"{SECONDARY_API_BASE_URL}/purchase"  # Adjust endpoint based on API documentation
        headers = {
            "Authorization": f"Bearer {SECONDARY_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "product_id": product_id,
            "quantity": amount,
            "username": SECONDARY_API_USERNAME
        }
        
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success" or data.get("success"):
                logger.info(f"Purchase success: secondary API - product={product_id}")
                return data, SECONDARY_API_NAME
        
        logger.warning(f"Secondary purchase failed: {r.status_code}")
        return None, SECONDARY_API_NAME
    except Exception as e:
        logger.error(f"Secondary buy error: {e}")
        return None, SECONDARY_API_NAME

# =====================================================
#                   🔀 UNIFIED PRODUCT MANAGEMENT
# =====================================================

def get_all_products() -> Dict[str, List[Dict]]:
    """Fetch and merge products from BOTH APIs"""
    try:
        primary_prods, _ = get_primary_products()
        secondary_prods, _ = get_secondary_products()
        
        logger.info(f"Primary API: {len(primary_prods)} categories")
        logger.info(f"Secondary API: {len(secondary_prods)} categories")
        
        # Merge products into unified format
        unified_products = {}
        
        # Add primary API products
        if primary_prods:
            for category in primary_prods:
                cat_name = category.get("name", "General")
                accounts = category.get("accounts", [])
                
                if cat_name not in unified_products:
                    unified_products[cat_name] = []
                
                for acc in accounts:
                    acc["api_source"] = PRIMARY_API_NAME
                    acc["api_product_id"] = acc.get("id")
                    # CEOACC returns price in CNY fen - normalize to USD now,
                    # so every downstream consumer sees a correct USD "price".
                    acc["price"] = convert_ceoacc_price_to_usd(acc.get("price", 0))
                    unified_products[cat_name].append(acc)
        
        # Add secondary API products
        if secondary_prods:
            for category in secondary_prods:
                cat_name = category.get("name", "General")
                accounts = category.get("accounts", [])
                
                if cat_name not in unified_products:
                    unified_products[cat_name] = []
                
                for acc in accounts:
                    acc["api_source"] = SECONDARY_API_NAME
                    acc["api_product_id"] = acc.get("id")
                    unified_products[cat_name].append(acc)
        
        logger.info(f"✅ Unified catalog: {len(unified_products)} categories")
        return unified_products
        
    except Exception as e:
        logger.error(f"Error merging products: {e}")
        return {}

def purchase_from_api(product_id, api_source, amount=1) -> Tuple[dict, str]:
    """Route purchase to correct API based on source"""
    if api_source == PRIMARY_API_NAME:
        return buy_primary_product(product_id, amount)
    elif api_source == SECONDARY_API_NAME:
        return buy_secondary_product(product_id, amount)
    else:
        logger.error(f"Unknown API source: {api_source}")
        return None, "Unknown"

# =====================================================
#                   🎯 KEYBOARD BUTTONS
# =====================================================

def get_main_menu():
    """Get main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💰 Check Balance", callback_data="menu_balance")],
        [InlineKeyboardButton("🛍️ Browse Products", callback_data="menu_products")],
        [InlineKeyboardButton("💵 Add Funds", callback_data="menu_deposit")],
        [InlineKeyboardButton("📊 My Purchases", callback_data="menu_purchases")],
        [InlineKeyboardButton("❓ Help & Support", callback_data="menu_help")]
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
        f"{STORE_NAME}\n\n"
        f"👋 Welcome, {user_name}!\n\n"
        "🔥 *Premium Social Accounts at Unbeatable Prices*\n"
        f"💎 *Curated from Top Suppliers*\n"
        f"💸 *Markup: {MARKUP_PERCENT}% Above Cost*\n"
        "⚡ *Instant Account Delivery*\n"
        "🛡️ *100% Trusted & Verified*\n"
        "📦 *50+ Products Available*\n\n"
        "Choose an option below to explore! 👇"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )
    logger.info(f"User started: {uid}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = (
        "❓ *HELP & SUPPORT*\n\n"
        "🛒 *How to Buy:*\n"
        "1️⃣ Add funds via 💵 Add Funds\n"
        "2️⃣ Browse via 🛍️ Browse Products\n"
        "3️⃣ Select your product\n"
        "4️⃣ Get account instantly! ✨\n\n"
        "💡 *Pro Tips:*\n"
        "• Check your balance anytime\n"
        "• All accounts delivered within seconds\n"
        "• Track your purchase history\n\n"
        "📞 *Need Support?*\n"
        f"Contact: {ADMIN_USERNAME}\n"
        "Response time: Usually under 5 mins"
    )
    
    await update.message.reply_text(
        help_text,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check balance command"""
    uid = str(update.effective_user.id)
    ensure_user(uid)
    
    bal = users[uid]["balance"]
    purchases = users[uid]["purchases"]
    
    text = (
        f"💰 *YOUR ACCOUNT BALANCE*\n\n"
        f"Balance: `${bal:.2f}`\n"
        f"Purchases: {purchases}\n\n"
        f"💵 Low balance? Add funds now!"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_back_button())

async def products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse products command"""
    await update.message.reply_text(
        "⏳ Loading products from all suppliers...",
        parse_mode='Markdown'
    )
    
    unified = get_all_products()
    
    if not unified:
        await update.message.reply_text(
            "❌ No products available at the moment. Please try again later.",
            reply_markup=get_back_button()
        )
        return
    
    # Store unified products in context so category selection callbacks work
    # (this was previously missing, causing "Category not found" errors,
    # and Instagram/other categories appearing on the website but not here)
    context.user_data['unified_products'] = unified
    context.user_data['categories_list'] = sorted(unified.keys())
    
    text = f"🛍️ *SELECT A CATEGORY* ({len(unified)} available)\n\nClick below to browse! 👇"
    buttons = []
    
    for i, cat_name in enumerate(context.user_data['categories_list']):
        count = len(unified[cat_name])
        buttons.append([
            InlineKeyboardButton(f"📁 {cat_name} ({count})", callback_data=f"cat_{i}")
        ])
    
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_main")])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='Markdown'
    )

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deposit command"""
    text = (
        f"💵 *ADD FUNDS TO YOUR ACCOUNT*\n\n"
        f"Send USDT (TRC20) to:\n`{USDT_ADDRESS}`\n\n"
        f"Then send proof to: {ADMIN_USERNAME}\n\n"
        f"⏱ *Credited within 10 minutes*\n\n"
        "💡 Pro Tip: Add extra funds to unlock exclusive bundles!"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_back_button())

async def admin_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to credit user"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("/credit <user_id> <amount>")
        return
    
    try:
        uid = str(context.args[0])
        amount = float(context.args[1])
        ensure_user(uid)
        users[uid]["balance"] += amount
        save_users(users)
        await update.message.reply_text(f"✅ Credited ${amount} to user {uid}")
    except:
        await update.message.reply_text("❌ Invalid format")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin stats command"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Admin only")
        return
    
    total_users = len(users)
    total_balance = sum(u["balance"] for u in users.values())
    total_purchases = sum(u["purchases"] for u in users.values())
    
    text = (
        f"📊 *BOT STATISTICS*\n\n"
        f"Users: {total_users}\n"
        f"Total Balance: `${total_balance:.2f}`\n"
        f"Total Purchases: {total_purchases}\n"
        f"Avg Purchase: `${total_balance/max(1, total_purchases):.2f}`"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    q = update.callback_query
    await q.answer()
    
    uid = str(q.from_user.id)
    data = q.data
    ensure_user(uid)
    
    try:
        # Main menu
        if data == "menu_main":
            await q.edit_message_text(
                f"{STORE_NAME}\n\n"
                f"👋 Welcome back!\n\n"
                "Choose an option below 👇",
                reply_markup=get_main_menu(),
                parse_mode='Markdown'
            )
        
        # Balance
        elif data == "menu_balance":
            bal = users[uid]["balance"]
            purchases = users[uid]["purchases"]
            
            await q.edit_message_text(
                f"💰 *YOUR ACCOUNT BALANCE*\n\n"
                f"Current Balance: `${bal:.2f}`\n"
                f"Total Purchases: {purchases}\n\n"
                f"{'✅ You have sufficient funds!' if bal > 0 else '💵 Add funds to start shopping'}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💵 Add Funds", callback_data="menu_deposit")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="menu_main")]
                ]),
                parse_mode='Markdown'
            )
        
        # Products
        elif data == "menu_products":
            await q.edit_message_text("⏳ Loading catalog from all suppliers...")
            
            unified = get_all_products()
            
            if not unified:
                await q.edit_message_text(
                    "❌ No products available",
                    reply_markup=get_back_button()
                )
                return
            
            # Store unified products in context
            context.user_data['unified_products'] = unified
            context.user_data['categories_list'] = sorted(unified.keys())
            
            text = (
                f"🛍️ *SELECT A CATEGORY*\n\n"
                f"Total Categories: {len(unified)}\n"
                f"Total Products: {sum(len(p) for p in unified.values())}\n\n"
                "Click below to browse! 👇"
            )
            buttons = []
            
            for i, cat_name in enumerate(context.user_data['categories_list']):
                count = len(unified[cat_name])
                buttons.append([
                    InlineKeyboardButton(f"📁 {cat_name} ({count})", callback_data=f"cat_{i}")
                ])
            
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_main")])
            
            await q.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode='Markdown'
            )
        
        # Deposit
        elif data == "menu_deposit":
            await q.edit_message_text(
                f"💵 *ADD FUNDS*\n\n"
                f"Send USDT (TRC20):\n`{USDT_ADDRESS}`\n\n"
                f"Then proof to: {ADMIN_USERNAME}\n\n"
                f"⏱ Credited in ~10 minutes",
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        
        # Purchase History
        elif data == "menu_purchases":
            purchases = users[uid]["purchases"]
            text = (
                f"📊 *YOUR PURCHASES*\n\n"
                f"Total Purchases: {purchases}\n"
                f"Member Since: {users[uid]['joined'][:10]}\n\n"
                "Keep shopping for more great deals! 🛍️"
            )
            await q.edit_message_text(
                text,
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        
        # Help
        elif data == "menu_help":
            await q.edit_message_text(
                f"❓ *HELP & SUPPORT*\n\n"
                f"📱 *Contact: {ADMIN_USERNAME}*\n\n"
                f"Hours: 24/7\n"
                f"Response: Usually under 5 mins\n\n"
                f"Common Issues:\n"
                f"• Balance not updating? Contact admin\n"
                f"• Product out of stock? We restock daily\n"
                f"• Need assistance? Click contact above",
                reply_markup=get_back_button(),
                parse_mode='Markdown'
            )
        
        # Category selection
        elif data.startswith("cat_"):
            try:
                cat_index = int(data.split("_")[1])
                unified = context.user_data.get('unified_products', {})
                categories_list = context.user_data.get('categories_list', [])
                
                if cat_index >= len(categories_list):
                    await q.edit_message_text("❌ Category not found")
                    return
                
                cat_name = categories_list[cat_index]
                products_list = unified.get(cat_name, [])
                
                if not products_list:
                    await q.edit_message_text("📭 No products in this category")
                    return
                
                text = f"📦 *{cat_name.upper()}*\n\n"
                text += f"Available: {len(products_list)} products\n\n"
                
                buttons = []
                DISPLAY_LIMIT = 30
                
                for i, prod in enumerate(products_list[:DISPLAY_LIMIT]):
                    try:
                        orig_price = float(prod.get("price", 0))
                        resale_price = round(orig_price * (1 + MARKUP_PERCENT/100), 2)
                        
                        name = prod.get("name", "Product")[:30]
                        pid = str(prod.get("id", ""))
                        stock = prod.get("amount", 0)
                        api_src = prod.get("api_source", "Unknown")
                        
                        # Create unique callback with encoding
                        callback_id = f"buy_{i}_{cat_index}_{pid}_{resale_price}_{orig_price}_{api_src[:3]}"
                        
                        buttons.append([
                            InlineKeyboardButton(
                                f"🛒 {name}\n   ${resale_price} | 📦 {stock}",
                                callback_data=callback_id
                            )
                        ])
                        
                        text += f"• {name}\n  💰 ${resale_price} | 📦 {stock} | 🏢 {api_src}\n"
                    except Exception as e:
                        logger.error(f"Product error: {e}")
                
                if len(products_list) > DISPLAY_LIMIT:
                    text += f"\n_Showing {DISPLAY_LIMIT} of {len(products_list)} products. Contact {ADMIN_USERNAME} for more options._\n"
                
                buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_products")])
                
                await q.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Category error: {e}")
                await q.edit_message_text("❌ Error loading category")
        
        # Product purchase
        elif data.startswith("buy_"):
            try:
                parts = data.split("_")
                _, prod_idx, cat_idx, pid, your_price, orig_price, api_src_short = parts[0:7]
                
                your_price = float(your_price)
                api_src = "CEOACC" if api_src_short == "CEE" else "JEJELAYE"
                
            except:
                await q.edit_message_text("❌ Invalid product data")
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
            
            # Purchase from appropriate API
            result, api_name = purchase_from_api(pid, api_src)
            
            if result:
                users[uid]["purchases"] += 1
                users[uid]["purchase_history"].append({
                    "date": datetime.now().isoformat(),
                    "product": pid,
                    "price": your_price,
                    "api": api_name
                })
                save_users(users)
                
                # Extract account details based on API response format
                account_details = "Account delivered successfully"
                trans_id = result.get("trans_id", result.get("id", "TXN" + str(users[uid]["purchases"])))
                
                # Handle different response formats
                if result.get("lists"):
                    account_details = result.get("lists", [{}])[0].get("account", account_details)
                elif result.get("account"):
                    account_details = result.get("account")
                elif result.get("data"):
                    account_details = str(result.get("data"))
                
                await q.edit_message_text(
                    f"✅ *PURCHASE SUCCESSFUL!* 🎉\n\n"
                    f"Transaction: `{trans_id}`\n"
                    f"From: {api_name}\n\n"
                    f"🔑 *ACCOUNT DETAILS*\n"
                    f"`{account_details}`\n\n"
                    f"💰 New Balance: `${users[uid]['balance']:.2f}`\n"
                    f"📦 Total Purchases: {users[uid]['purchases']}\n\n"
                    f"Thank you for your purchase! 🙏",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛍️ Shop More", callback_data="menu_products")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]
                    ]),
                    parse_mode='Markdown'
                )
                logger.info(f"Purchase: {uid} - ${your_price:.2f} from {api_name}")
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
                logger.warning(f"Purchase failed: {uid} from {api_src}")
    
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
        sys.exit(1)
    
    if SECONDARY_API_PASSWORD == 'YOUR_PASSWORD_HERE':
        print("⚠️  WARNING: JEJELAYE password not set!")
        print("Update SECONDARY_API_PASSWORD in the config")
    
    print("=" * 70)
    print("🏪 PROFESSIONAL ACCOUNTS RESALE BOT 🏪")
    print("=" * 70)
    print(f"✅ Telegram Token: {TELEGRAM_TOKEN[:20]}...")
    print(f"✅ Admin ID: {ADMIN_ID}")
    print(f"✅ Primary API: {PRIMARY_API_BASE_URL}")
    print(f"✅ Secondary API: {SECONDARY_API_BASE_URL}")
    print(f"✅ Markup: {MARKUP_PERCENT}%")
    print(f"✅ Dual API Integration: ACTIVE")
    print(f"✅ Users loaded: {len(users)}")
    print("=" * 70)
    print("🚀 STARTING BOT... (Dual API with Unified Catalog)")
    print("=" * 70)
    
    # Create application
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
    
    logger.info("🏪 DUAL API BOT STARTED")
    print("✅ Bot is LIVE and listening for commands...")
    print("📱 Send /start to your bot to begin")
    
    try:
        app.run_polling()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
