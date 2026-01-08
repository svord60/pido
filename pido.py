import asyncio
import logging
import sqlite3
import os
import json
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [6997318168]  # ⬅️ ВАШ ID ОТКРЫТО
CRYPTOBOT_TOKEN = os.environ.get("CRYPTOBOT_TOKEN", "")

# Настройки
CARD_NUMBER = "2200700527205453"
STAR_RATE = 1.5  # 1 звезда = 1.5 RUB
USD_RATE = 85.0  # 1 USD = 85 RUB

PREMIUM_PRICES = {
    "3m": {"rub": 1124.11, "name": "3 месяца"},
    "6m": {"rub": 1498.81, "name": "6 месяцев"}, 
    "1y": {"rub": 2716.59, "name": "1 год"}
}

REPUTATION_CHANNEL = "https://t.me/+3pbAABRgo1ljOTJi"
NEWS_CHANNEL = "https://t.me/NewsDigistars"
SUPPORT_USER = "swordSar"

# ========== CRYPTOBOT ==========
class CryptoBotAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount, description=""):
        """Создать счет для оплаты"""
        try:
            url = f"{self.base_url}/createInvoice"
            headers = {"Crypto-Pay-API-Token": self.token}
            
            # Конвертируем рубли в USDT по курсу 85 RUB = 1 USDT
            amount_usdt = amount / 85.0
            
            data = {
                "asset": "USDT",
                "amount": str(round(amount_usdt, 2)),
                "description": description[:1024],
                "paid_btn_name": "openBot",  # ✅ ИСПРАВЛЕНО
                "paid_btn_url": "https://t.me/DigiStoreBot",
                "payload": f"order_{int(datetime.now().timestamp())}",
                "allow_anonymous": False
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]
                return {
                    "success": True,
                    "invoice_id": invoice["invoice_id"],
                    "pay_url": invoice["pay_url"],
                    "amount": invoice["amount"],
                    "asset": invoice["asset"]
                }
            else:
                return {"success": False, "error": result.get("error", {}).get("name", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def check_invoice_status(self, invoice_id):
        """Проверить статус инвойса в CryptoBot"""
        try:
            url = f"{self.base_url}/getInvoices"
            headers = {"Crypto-Pay-API-Token": self.token}
            
            params = {"invoice_ids": invoice_id}
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]["items"][0]
                return {
                    "success": True,
                    "status": invoice["status"],  # "active", "paid", "expired"
                    "paid_at": invoice.get("paid_at"),
                    "amount": invoice.get("amount")
                }
            else:
                return {"success": False, "error": result.get("error", {}).get("name", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}

# Инициализируем CryptoBot если есть токен
cryptobot = CryptoBotAPI(CRYPTOBOT_TOKEN) if CRYPTOBOT_TOKEN else None

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name="digistore.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_type TEXT,
            recipient TEXT,
            details TEXT,
            amount_rub REAL,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            invoice_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, full_name):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        self.conn.commit()
    
    def add_order(self, user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id=None):
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO orders 
            (user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id) 
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id)
        )
        order_id = cursor.lastrowid
        self.conn.commit()
        return order_id
    
    def update_order_status(self, order_id, status):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def update_invoice_id(self, order_id, invoice_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET invoice_id = ? WHERE id = ?",
            (invoice_id, order_id)
        )
        self.conn.commit()
    
    def add_payment_photo(self, order_id, file_id):
        """Сохранить photo_file_id в details заказа"""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET details = json_set(details, '$.payment_photo', ?) WHERE id = ?",
            (file_id, order_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def get_pending_orders(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, user_id, order_type, recipient, amount_rub, payment_method, created_at 
            FROM orders 
            WHERE status = 'pending' 
            ORDER BY created_at DESC
        """)
        return cursor.fetchall()
    
    def get_completed_orders(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, user_id, order_type, recipient, amount_rub, payment_method, created_at 
            FROM orders 
            WHERE status = 'completed' 
            ORDER BY created_at DESC
            LIMIT 50
        """)
        return cursor.fetchall()
    
    def get_all_active_orders(self):
        """Все заказы кроме completed и cancelled"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, user_id, order_type, recipient, amount_rub, payment_method, status, created_at 
            FROM orders 
            WHERE status NOT IN ('completed', 'cancelled')
            ORDER BY created_at DESC
        """)
        return cursor.fetchall()
    
    def get_order(self, order_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id 
            FROM orders WHERE id = ?
        """, (order_id,))
        return cursor.fetchone()
    
    def get_statistics(self):
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
        completed_orders = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(amount_rub) FROM orders WHERE status = 'completed'")
        total_revenue = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
        pending_orders = cursor.fetchone()[0]
        
        return {
            "total_users": total_users,
            "completed_orders": completed_orders,
            "total_revenue": total_revenue,
            "pending_orders": pending_orders
        }

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()

user_states = {}

# ========== КЛАВИАТУРЫ ==========
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Купить звезды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="👑 Купить премиум", callback_data="buy_premium")],
        [InlineKeyboardButton(text="💱 Обмен валют", callback_data="exchange")],
        [InlineKeyboardButton(text="📊 Информация", callback_data="info")],
        [InlineKeyboardButton(text="🆘 Тех поддержка", url=f"https://t.me/{SUPPORT_USER}")]
    ])

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="⏳ Ожидают проверки", callback_data="admin_pending")],
        [InlineKeyboardButton(text="✅ Выполненные", callback_data="admin_completed")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])

def confirm_payment_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"confirm_paid_{order_id}")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def back_kb(target):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=target)]
    ])

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name
    
    db.add_user(user_id, username, full_name)
    
    caption = (
        "🪐 **Digi Store - Главное меню**\n\n"
        "C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )

async def show_main_menu(message: types.Message):
    """Показать главное меню"""
    caption = (
        "🪐 **Digi Store - Главное меню**\n\n"
        "C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )

# ========== ВСЕ ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: types.CallbackQuery):
    caption = (
        "🪐 **Digi Store - Главное меню**\n\n"
        "C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_stars")
async def buy_stars_handler(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = {"action": "waiting_stars_recipient"}
    
    caption = (
        "⭐️ **Покупка Telegram Stars**\n\n"
        f"Курс: **1 звезда = {STAR_RATE} RUB**\n"
        "Диапазон: от 50 до 1,000,000 звезд\n\n"
        "✏️ Введите username получателя (можно с @):"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=back_kb("main_menu"),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_premium")
async def buy_premium_handler(callback: types.CallbackQuery):
    price_text = ""
    for key, value in PREMIUM_PRICES.items():
        price_text += f"• {value['name']}: {value['rub']:.2f} RUB\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 месяца", callback_data="premium_3m")],
        [InlineKeyboardButton(text="6 месяцев", callback_data="premium_6m")],
        [InlineKeyboardButton(text="1 год", callback_data="premium_1y")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    caption = (
        "👑 **Покупка Telegram Premium**\n\n"
        "Выберите период:\n\n"
        f"{price_text}"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("premium_"))
async def premium_period_handler(callback: types.CallbackQuery):
    period = callback.data.replace("premium_", "")
    
    if period in PREMIUM_PRICES:
        user_states[callback.from_user.id] = {
            "action": "waiting_premium_recipient",
            "period": period,
            "amount_rub": PREMIUM_PRICES[period]["rub"]
        }
        
        caption = (
            f"👑 **Telegram Premium - {PREMIUM_PRICES[period]['name']}**\n\n"
            f"Цена: **{PREMIUM_PRICES[period]['rub']:.2f} RUB**\n\n"
            "✏️ Введите username получателя (можно с @):"
        )
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=back_kb("buy_premium"),
            parse_mode="Markdown"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "exchange")
async def exchange_handler(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = {"action": "waiting_exchange_amount"}
    
    caption = (
        "💱 **Обмен валют**\n\n"
        f"Курс: **1 USD = {USD_RATE} RUB**\n\n"
        "Введите сумму в рублях для обмена:\n"
        "(Минимум: 100 RUB)\n\n"
        "💳 **Оплата только картой!**"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=back_kb("main_menu"),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "info")
async def info_handler(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Репутация", url=REPUTATION_CHANNEL)],
        [InlineKeyboardButton(text="📰 Новости", url=NEWS_CHANNEL)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    caption = "📊 **Информация**\n\nВыберите раздел:"
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== ОБРАБОТКА ФОТО ОПЛАТЫ ==========
@dp.message(F.photo)
async def handle_payment_photo(message: types.Message):
    """Обработка фото оплаты"""
    user_id = message.from_user.id
    
    if user_id not in user_states:
        await message.answer("Пожалуйста, используйте кнопки меню.")
        return
    
    state = user_states[user_id]
    
    if state.get("action") == "waiting_payment_photo":
        order_id = state.get("order_id")
        order = db.get_order(order_id)
        
        if not order:
            await message.answer("❌ Заказ не найден")
            return
        
        user_id_db, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
        
        # Получаем file_id фото
        photo_file_id = message.photo[-1].file_id
        
        # Сохраняем фото в базу
        try:
            details_dict = json.loads(details) if details else {}
            details_dict["payment_photo"] = photo_file_id
            db.add_payment_photo(order_id, photo_file_id)
        except:
            pass
        
        # Обновляем статус
        db.update_order_status(order_id, "waiting_confirmation")
        
        # Удаляем состояние
        del user_states[user_id]
        
        # Уведомляем админа с фото
        for admin_id in ADMIN_IDS:
            try:
                # Сначала отправляем фото
                photo_caption = "📸 **Фото оплаты получено**"
                
                if order_type == "exchange":
                    try:
                        details_dict = json.loads(details) if details else {}
                        amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                        photo_caption += f"\n💱 Обмен валют"
                    except:
                        photo_caption += f"\n💱 Обмен валют"
                
                await bot.send_photo(
                    admin_id,
                    photo=photo_file_id,
                    caption=photo_caption
                )
                
                # Затем отправляем детали заказа
                admin_message = f"🆕 Ожидает проверки картой\n"
                admin_message += f"🆔 Заказ: #{order_id}\n"
                admin_message += f"👤 Пользователь: {message.from_user.username or 'Нет юзернейма'}\n"
                admin_message += f"🆔 ID: {message.from_user.id}\n"
                admin_message += f"💰 Сумма: {amount_rub:.2f} RUB\n"
                admin_message += f"📦 Тип: {order_type}\n"
                
                if order_type == "exchange":
                    try:
                        details_dict = json.loads(details) if details else {}
                        amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                        admin_message += f"💸 К выдаче: {amount_usd:.2f} USD\n"
                    except:
                        pass
                else:
                    admin_message += f"👤 Получатель: {recipient}\n"
                
                admin_message += f"\nДля проверки: /check_{order_id}"
                
                await bot.send_message(admin_id, admin_message)
                
            except Exception as e:
                print(f"Ошибка отправки админу: {e}")
        
        # Сообщение пользователю
        if order_type == "exchange":
            try:
                details_dict = json.loads(details) if details else {}
                amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                user_message = (
                    f"✅ Фото оплаты получено!\n"
                    f"💸 Вы получаете: {amount_usd:.2f} USD\n"
                    f"💰 Оплачено: {amount_rub:.2f} RUB\n\n"
                    "Заказ передан админу на проверку.\n"
                    "После проверки USD будут отправлены вам в течение 15 минут - 3 часа."
                )
            except:
                user_message = (
                    "✅ Фото оплаты получено! Заказ передан админу на проверку.\n"
                    "После проверки USD будут отправлены вам в течение 15 минут - 3 часа."
                )
        else:
            user_message = (
                "✅ Фото оплаты получено! Заказ передан админу на проверку.\n"
                "После проверки товар будет доставлен в течение 15 минут - 3 часа."
            )
        
        await message.answer(user_message)
        
        # Возвращаем в главное меню
        await show_main_menu(message)

# ========== КОМАНДЫ ==========
@dp.message(Command("myid"))
async def get_my_id(message: types.Message):
    """Узнать свой ID"""
    await message.answer(f"🆔 Ваш ID: `{message.from_user.id}`", 
                        parse_mode="Markdown")

# ========== АДМИН КОМАНДЫ (ИСПРАВЛЕННЫЕ) ==========
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Админ панель"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(f"❌ Доступ запрещен. Ваш ID: {message.from_user.id}")
        return
    
    # Получаем статистику
    stats = db.get_statistics()
    
    caption = (
        f"🛠️ **Админ панель**\n\n"
        f"📊 **Статистика:**\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"✅ Выполнено заказов: {stats['completed_orders']}\n"
        f"💰 Выручка: {stats['total_revenue']:.2f} RUB\n"
        f"⏳ Ожидают проверки: {stats['pending_orders']}\n\n"
        "Выберите действие:"
    )
    
    await message.answer(caption, reply_markup=admin_menu_kb(), parse_mode="Markdown")

# ========== СТАРЫЕ ФОРМАТЫ КОМАНД (для совместимости) ==========
@dp.message(F.text.startswith("/check_"))
async def check_order_command_old(message: types.Message):
    """Старый формат: /check_11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        order_id = int(message.text.split("_")[1])
        order = db.get_order(order_id)
        
        if not order:
            await message.answer(f"❌ Заказ #{order_id} не найден")
            return
        
        user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
        
        # Получаем дополнительные данные
        details_dict = {}
        amount_usd = 0
        stars_count = 0
        period_name = ""
        
        try:
            if details:
                details_dict = json.loads(details)
                if order_type == "exchange":
                    amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                elif order_type == "stars":
                    stars_count = details_dict.get("stars", 0)
                elif order_type == "premium":
                    period = details_dict.get("period", "")
                    period_name = PREMIUM_PRICES.get(period, {}).get("name", "")
        except:
            pass
        
        # Формируем текст
        text = (
            f"🔍 **Заказ #{order_id}**\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"📦 Тип: {order_type}\n"
        )
        
        if order_type == "stars":
            text += f"⭐️ Количество: {stars_count} звезд\n"
        elif order_type == "premium":
            text += f"👑 Период: {period_name}\n"
        elif order_type == "exchange":
            text += f"💸 К выдаче: {amount_usd:.2f} USD\n"
        
        if order_type != "exchange" and recipient:
            text += f"👤 Получатель: @{recipient}\n"
        
        text += (
            f"💰 Сумма: {amount_rub:.2f} RUB\n"
            f"💳 Метод: {payment_method}\n"
            f"📊 Статус: {status}\n\n"
            "**Управление заказом:**"
        )
        
        # Кнопки управления в зависимости от статуса
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        if status == "waiting_confirmation":
            # Заказ ожидает проверки фото
            keyboard.inline_keyboard = [
                [
                    InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"order_confirm_{order_id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"order_reject_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="📦 Выполнить заказ", callback_data=f"order_complete_{order_id}"),
                    InlineKeyboardButton(text="💬 Написать пользователю", callback_data=f"order_msg_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"order_refresh_{order_id}"),
                    InlineKeyboardButton(text="🔙 К заказам", callback_data="admin_orders")
                ]
            ]
        elif status == "waiting_crypto":
            # CryptoBot оплата
            keyboard.inline_keyboard = [
                [
                    InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_crypto_{order_id}"),
                    InlineKeyboardButton(text="🔁 Статус", callback_data=f"crypto_status_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="📦 Выполнить заказ", callback_data=f"order_complete_{order_id}"),
                    InlineKeyboardButton(text="❌ Отменить", callback_data=f"order_cancel_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="💬 Написать пользователю", callback_data=f"order_msg_{order_id}"),
                    InlineKeyboardButton(text="🔙 К заказам", callback_data="admin_orders")
                ]
            ]
        elif status == "confirmed":
            # Заказ подтвержден, нужно выполнить
            keyboard.inline_keyboard = [
                [
                    InlineKeyboardButton(text="📦 Выполнить заказ", callback_data=f"order_complete_{order_id}"),
                    InlineKeyboardButton(text="✅ Пометить выполненным", callback_data=f"order_finish_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="💬 Написать пользователю", callback_data=f"order_msg_{order_id}"),
                    InlineKeyboardButton(text="🔙 К заказам", callback_data="admin_orders")
                ]
            ]
        else:
            # Другие статусы
            keyboard.inline_keyboard = [
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"order_confirm_{order_id}"),
                    InlineKeyboardButton(text="❌ Отменить", callback_data=f"order_cancel_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="📦 Выполнить", callback_data=f"order_complete_{order_id}"),
                    InlineKeyboardButton(text="💬 Написать", callback_data=f"order_msg_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"order_refresh_{order_id}"),
                    InlineKeyboardButton(text="🔙 К заказам", callback_data="admin_orders")
                ]
            ]
        
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        
        # Показываем фото оплаты если есть
        try:
            if details and "payment_photo" in details_dict:
                await bot.send_photo(
                    message.chat.id,
                    photo=details_dict["payment_photo"],
                    caption=f"📸 Фото оплаты заказа #{order_id}"
                )
        except:
            pass
    
    except (ValueError, IndexError):
        await message.answer("❌ Формат: /check_123")

# НОВЫЕ КОМАНДЫ С АРГУМЕНТАМИ
@dp.message(Command("check"))
async def check_order_command_new(message: types.Message, command: CommandObject):
    """Новый формат: /check 11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    if not command.args:
        await message.answer("❌ Формат: /check <номер_заказа>")
        return
    
    try:
        order_id = int(command.args)
        # Вызываем старую функцию для обработки
        await check_order_command_old(message)
    except ValueError:
        await message.answer("❌ Неверный номер заказа")

# СТАРЫЕ КОМАНДЫ АДМИНА (для совместимости)
@dp.message(F.text.startswith("/confirm_"))
async def confirm_order_command_old(message: types.Message):
    """Старый формат: /confirm_11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        order_id = int(message.text.split("_")[1])
        success = db.update_order_status(order_id, "completed")
        
        if success:
            await message.answer(f"✅ Заказ #{order_id} подтвержден")
        else:
            await message.answer(f"❌ Заказ #{order_id} не найден")
    
    except (ValueError, IndexError):
        await message.answer("❌ Формат: /confirm_123")

@dp.message(F.text.startswith("/complete_"))
async def complete_order_command_old(message: types.Message):
    """Старый формат: /complete_11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        order_id = int(message.text.split("_")[1])
        success = db.update_order_status(order_id, "completed")
        
        if success:
            await message.answer(f"✅ Заказ #{order_id} выполнен")
        else:
            await message.answer(f"❌ Заказ #{order_id} не найден")
    
    except (ValueError, IndexError):
        await message.answer("❌ Формат: /complete_123")

@dp.message(F.text.startswith("/cancel_"))
async def cancel_order_command_old(message: types.Message):
    """Старый формат: /cancel_11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        order_id = int(message.text.split("_")[1])
        success = db.update_order_status(order_id, "cancelled")
        
        if success:
            await message.answer(f"❌ Заказ #{order_id} отменен")
        else:
            await message.answer(f"❌ Заказ #{order_id} не найден")
    
    except (ValueError, IndexError):
        await message.answer("❌ Формат: /cancel_123")

# НОВЫЕ КОМАНДЫ С АРГУМЕНТАМИ (альтернатива)
@dp.message(Command("confirm"))
async def confirm_order_cmd_new(message: types.Message, command: CommandObject):
    """Новый формат: /confirm 11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    if not command.args:
        await message.answer("❌ Формат: /confirm <номер_заказа>")
        return
    
    try:
        order_id = int(command.args)
        success = db.update_order_status(order_id, "completed")
        
        if success:
            await message.answer(f"✅ Заказ #{order_id} подтвержден")
        else:
            await message.answer(f"❌ Заказ #{order_id} не найден")
    except ValueError:
        await message.answer("❌ Неверный номер заказа")

@dp.message(Command("complete"))
async def complete_order_cmd_new(message: types.Message, command: CommandObject):
    """Новый формат: /complete 11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    if not command.args:
        await message.answer("❌ Формат: /complete <номер_заказа>")
        return
    
    try:
        order_id = int(command.args)
        success = db.update_order_status(order_id, "completed")
        
        if success:
            await message.answer(f"✅ Заказ #{order_id} выполнен")
        else:
            await message.answer(f"❌ Заказ #{order_id} не найден")
    except ValueError:
        await message.answer("❌ Неверный номер заказа")

@dp.message(Command("cancel"))
async def cancel_order_cmd_new(message: types.Message, command: CommandObject):
    """Новый формат: /cancel 11"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    if not command.args:
        await message.answer("❌ Формат: /cancel <номер_заказа>")
        return
    
    try:
        order_id = int(command.args)
        success = db.update_order_status(order_id, "cancelled")
        
        if success:
            await message.answer(f"❌ Заказ #{order_id} отменен")
        else:
            await message.answer(f"❌ Заказ #{order_id} не найден")
    except ValueError:
        await message.answer("❌ Неверный номер заказа")

# ========== ОПЛАТА КАРТОЙ ==========
@dp.callback_query(F.data.startswith("card_pay_"))
async def card_payment_handler(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("card_pay_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
    
    # Обновляем статус
    db.update_order_status(order_id, "waiting_payment")
    
    caption = (
        f"💳 **Оплата картой**\n\n"
        f"🆔 Заказ: #{order_id}\n"
        f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
        f"**Реквизиты для перевода:**\n"
        f"`{CARD_NUMBER}`\n\n"
        "**Инструкция:**\n"
        "1. Переведите точную сумму\n"
        "2. Сохраните скриншот перевода\n"
        "3. Нажмите '✅ Я оплатил'\n"
        "4. Отправьте фото оплаты\n"
        "5. Админ проверит оплату\n\n"
        "✅ После проверки товар будет доставлен в течение 15 минут - 3 часа"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=confirm_payment_kb(order_id),
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== ОПЛАТА CRYPTOBOT ==========
@dp.callback_query(F.data.startswith("crypto_pay_"))
async def crypto_payment_handler(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("crypto_pay_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
    
    # Создаем счет в CryptoBot
    result = await cryptobot.create_invoice(
        amount=amount_rub,
        description=f"Заказ #{order_id} | {order_type}"
    )
    
    if result["success"]:
        # Сохраняем invoice_id
        db.update_invoice_id(order_id, result["invoice_id"])
        db.update_order_status(order_id, "waiting_crypto")
        
        # Рассчитываем USDT сумму
        amount_usdt = amount_rub / 85.0
        
        caption = (
            f"💎 **Оплата через CryptoBot**\n\n"
            f"🆔 Заказ: #{order_id}\n"
            f"💰 Сумма: {amount_rub:.2f} RUB\n"
            f"💱 К оплате: {amount_usdt:.2f} USDT\n\n"
            "**Для оплаты:**\n"
            "1. Нажмите кнопку ниже\n"
            "2. Оплатите счет в CryptoBot\n"
            "3. После оплаты нажмите '✅ Проверить оплату'\n\n"
            "✅ Оплата проверяется автоматически, товар доставляется в течение 15 минут - 3 часа"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оплатить в CryptoBot", url=result["pay_url"])],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_crypto_{order_id}")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await callback.answer(f"❌ Ошибка: {result['error']}")
    
    await callback.answer()

# ========== ПРОВЕРКА CRYPTOBOT ОПЛАТЫ (ИСПРАВЛЕННАЯ) ==========
@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("check_crypto_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
    
    if not invoice_id:
        await callback.answer("❌ Нет invoice_id для проверки")
        return
    
    # Показываем "проверяем..."
    await callback.answer("🔍 Проверяем оплату...")
    
    # РЕАЛЬНАЯ проверка статуса в CryptoBot
    result = await cryptobot.check_invoice_status(invoice_id)
    
    if result["success"]:
        if result["status"] == "paid":
            # ОПЛАТА ПРОШЛА!
            db.update_order_status(order_id, "completed")
            
            # Уведомляем админа
            for admin_id in ADMIN_IDS:
                try:
                    admin_message = (
                        f"💎 **CryptoBot оплата ПОДТВЕРЖДЕНА**\n\n"
                        f"🆔 Заказ: #{order_id}\n"
                        f"💰 Сумма: {amount_rub:.2f} RUB\n"
                        f"📦 Тип: {order_type}\n"
                    )
                    
                    if order_type != "exchange":
                        admin_message += f"👤 Получатель: {recipient}\n"
                    
                    admin_message += f"\n✅ Статус: ОПЛАЧЕНО"
                    
                    await bot.send_message(admin_id, admin_message)
                except:
                    pass
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    user_id,
                    f"✅ **Оплата подтверждена!**\n\n"
                    f"🆔 Ваш заказ: #{order_id}\n"
                    f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                    f"Товар будет отправлен в течение 15 минут - 3 часа!"
                )
            except:
                pass
            
            # ОСТАЕМСЯ НА ТЕКУЩЕЙ СТРАНИЦЕ с сообщением об успехе
            caption = (
                f"💎 **Оплата подтверждена!**\n\n"
                f"🆔 Заказ: #{order_id}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n"
                f"✅ Статус: ОПЛАЧЕНО\n\n"
                f"Товар будет отправлен в течение 15 минут - 3 часа!"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        elif result["status"] == "active":
            # Счет активен, но не оплачен
            await callback.answer(
                "❌ Счет не оплачен! Пожалуйста, оплатите счет в CryptoBot.",
                show_alert=True
            )
            
        elif result["status"] == "expired":
            # Счет просрочен
            db.update_order_status(order_id, "cancelled")
            
            caption = f"❌ **Счет просрочен!**\n\nЗаказ #{order_id} отменен."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
    else:
        await callback.answer(
            f"❌ Ошибка проверки: {result.get('error', 'Неизвестная ошибка')}",
            show_alert=True
        )

# ========== ПОДТВЕРЖДЕНИЕ ОПЛАТЫ КАРТОЙ ==========
@dp.callback_query(F.data.startswith("confirm_paid_"))
async def confirm_card_payment(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("confirm_paid_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
    
    # Добавляем ожидание фото
    user_states[callback.from_user.id] = {
        "action": "waiting_payment_photo",
        "order_id": order_id
    }
    
    # Для обмена валют показываем особое сообщение
    if order_type == "exchange":
        try:
            details_dict = json.loads(details) if details else {}
            amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
            
            await callback.message.edit_text(
                f"💱 **Обмен валют**\n\n"
                f"🆔 Заказ: #{order_id}\n"
                f"💸 Вы получаете: {amount_usd:.2f} USD\n"
                f"💰 К оплате: {amount_rub:.2f} RUB\n\n"
                "📸 **Пришлите фото/скриншот оплаты**\n\n"
                "Пожалуйста, отправьте скриншот перевода.\n"
                "После проверки админом USD будут отправлены вам в течение 15 минут - 3 часа.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"cancel_photo_{order_id}")]
                ])
            )
            
        except:
            await callback.message.edit_text(
                f"💱 **Обмен валют**\n\n"
                f"🆔 Заказ: #{order_id}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                "📸 **Пришлите фото/скриншот оплаты**\n\n"
                "Пожалуйста, отправьте скриншот перевода.\n"
                "После проверки админом USD будут отправлены вам в течение 15 минут - 3 часа.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"cancel_photo_{order_id}")]
                ])
            )
    else:
        # Для звезд и премиума обычное сообщение
        await callback.message.edit_text(
            f"📸 **Пришлите фото/скриншот оплаты**\n\n"
            f"🆔 Заказ: #{order_id}\n"
            f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
            "Пожалуйста, отправьте скриншот перевода или фото чека.\n"
            "После отправки фото заказ будет передан админу на проверку.\n"
            "Товар будет доставлен в течение 15 минут - 3 часа.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"cancel_photo_{order_id}")]
            ])
        )
    
    await callback.answer()

# Обработчик отмены отправки фото
@dp.callback_query(F.data.startswith("cancel_photo_"))
async def cancel_photo_handler(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("cancel_photo_", ""))
    
    # Удаляем состояние
    if callback.from_user.id in user_states:
        del user_states[callback.from_user.id]
    
    # Возвращаем к оплате картой
    await card_payment_handler(callback)

# ========== КНОПКИ УПРАВЛЕНИЯ ЗАКАЗАМИ ==========
# Подтверждение заказа
@dp.callback_query(F.data.startswith("order_confirm_"))
async def order_confirm_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_confirm_", ""))
    db.update_order_status(order_id, "confirmed")
    
    await callback.answer(f"✅ Заказ #{order_id} подтвержден!")
    await check_order_refresh(callback, order_id)

# Отклонение заказа
@dp.callback_query(F.data.startswith("order_reject_"))
async def order_reject_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_reject_", ""))
    db.update_order_status(order_id, "cancelled")
    
    await callback.answer(f"❌ Заказ #{order_id} отклонен!")
    await callback.message.delete()

# Выполнение заказа
@dp.callback_query(F.data.startswith("order_complete_"))
async def order_complete_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_complete_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
    
    # ДЛЯ CRYPTOBOT: проверяем оплату перед выполнением
    if invoice_id and cryptobot and status == "waiting_crypto":
        result = await cryptobot.check_invoice_status(invoice_id)
        
        if not result["success"] or result["status"] != "paid":
            await callback.answer(
                "❌ CryptoBot оплата не подтверждена! Сначала проверьте оплату.",
                show_alert=True
            )
            return
    
    # Если оплата подтверждена или это карта - выполняем
    db.update_order_status(order_id, "confirmed")
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"✅ Ваш заказ #{order_id} выполняется!\n"
            f"Товар будет отправлен в течение 15 минут - 3 часа."
        )
    except:
        pass
    
    await callback.answer(f"📦 Заказ #{order_id} выполняется...")
    await check_order_refresh(callback, order_id)

# Пометить как выполненный
@dp.callback_query(F.data.startswith("order_finish_"))
async def order_finish_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_finish_", ""))
    db.update_order_status(order_id, "completed")
    
    # Получаем данные заказа
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"🎉 Ваш заказ #{order_id} выполнен!\n"
                f"Спасибо за покупку! 😊"
            )
        except:
            pass
    
    await callback.answer(f"✅ Заказ #{order_id} помечен как выполненный!")
    await callback.message.delete()  # Удаляем сообщение с заказом

# Отмена заказа
@dp.callback_query(F.data.startswith("order_cancel_"))
async def order_cancel_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_cancel_", ""))
    db.update_order_status(order_id, "cancelled")
    
    # Уведомляем пользователя
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"❌ Ваш заказ #{order_id} отменен.\n"
                f"По вопросам обращайтесь в поддержку."
            )
        except:
            pass
    
    await callback.answer(f"❌ Заказ #{order_id} отменен")
    await callback.message.delete()

# Написать пользователю
@dp.callback_query(F.data.startswith("order_msg_"))
async def order_msg_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_msg_", ""))
    order = db.get_order(order_id)
    
    if order:
        user_id = order[0]
        await callback.answer(f"👤 ID пользователя: {user_id}")
        await callback.message.answer(
            f"✏️ **Написать пользователю**\n\n"
            f"🆔 Заказ: #{order_id}\n"
            f"👤 User ID: `{user_id}`\n\n"
            f"Чтобы написать: `{user_id}`",
            parse_mode="Markdown"
        )
    else:
        await callback.answer("❌ Заказ не найден")

# Обновить информацию о заказе
@dp.callback_query(F.data.startswith("order_refresh_"))
async def order_refresh_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("order_refresh_", ""))
    await check_order_refresh(callback, order_id)

# Статус CryptoBot
@dp.callback_query(F.data.startswith("crypto_status_"))
async def crypto_status_handler(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("crypto_status_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
    
    if not invoice_id:
        await callback.answer("❌ Нет invoice_id")
        return
    
    # Проверяем статус
    result = await cryptobot.check_invoice_status(invoice_id)
    
    if result["success"]:
        status_text = {
            "active": "⏳ Активен (ожидает оплаты)",
            "paid": "✅ Оплачен",
            "expired": "❌ Просрочен"
        }.get(result["status"], result["status"])
        
        message = (
            f"💎 **Статус CryptoBot**\n\n"
            f"🆔 Заказ: #{order_id}\n"
            f"💰 Сумма: {amount_rub:.2f} RUB\n"
            f"📊 Статус: {status_text}\n"
        )
        
        if result.get("paid_at"):
            message += f"📅 Оплачен: {result['paid_at']}\n"
        
        await callback.message.answer(message, parse_mode="Markdown")
        await callback.answer(f"Статус: {status_text}")
    
    else:
        await callback.answer(f"❌ Ошибка: {result.get('error', 'Неизвестная')}")

async def check_order_refresh(callback: types.CallbackQuery, order_id: int):
    """Обновить информацию о заказе"""
    order = db.get_order(order_id)
    
    if order:
        user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id = order
        
        text = (
            f"🔍 **Заказ #{order_id}** (обновлено)\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"📦 Тип: {order_type}\n"
        )
        
        if order_type != "exchange" and recipient:
            text += f"👤 Получатель: @{recipient}\n"
        
        text += (
            f"💰 Сумма: {amount_rub:.2f} RUB\n"
            f"💳 Метод: {payment_method}\n"
            f"📊 Статус: {status}\n\n"
            "✅ Статус обновлен!"
        )
        
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer("🔄 Информация обновлена")
    else:
        await callback.answer("❌ Заказ не найден")

# ========== РАЗДЕЛЫ АДМИН ПАНЕЛИ ==========
@dp.callback_query(F.data == "admin_orders")
async def admin_orders_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    orders = db.get_all_active_orders()
    
    if not orders:
        text = "📦 **Все заказы**\n\nНет активных заказов"
    else:
        text = "📦 **Все заказы**\n\n"
        for order in orders[:10]:  # Показываем первые 10
            order_id, user_id, order_type, recipient, amount_rub, payment_method, status, created_at = order
            
            # Статусы в emoji
            status_emoji = {
                'pending': '⏳',
                'waiting_payment': '💳',
                'waiting_confirmation': '📸',
                'waiting_crypto': '💎',
                'confirmed': '✅'
            }.get(status, '❓')
            
            # Форматируем дату
            created_short = str(created_at)[:16] if created_at else "---"
            
            text += f"{status_emoji} **#{order_id}** | {order_type}\n"
            text += f"👤 @{recipient if recipient else 'Нет'} | 💰 {amount_rub:.2f} RUB\n"
            text += f"📅 {created_short}\n"
            text += f"🔍 /check_{order_id}\n\n"
    
    # Кнопки для управления
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_orders"),
            InlineKeyboardButton(text="📦 Все", callback_data="orders_all")
        ],
        [
            InlineKeyboardButton(text="⏳ В ожидании", callback_data="orders_pending"),
            InlineKeyboardButton(text="💳 На оплате", callback_data="orders_waiting")
        ],
        [
            InlineKeyboardButton(text="📸 На проверке", callback_data="orders_confirmation"),
            InlineKeyboardButton(text="💎 CryptoBot", callback_data="orders_crypto")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")
        ]
    ])
    
    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    stats = db.get_statistics()
    
    caption = (
        f"📊 **Статистика магазина**\n\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"✅ Выполнено заказов: {stats['completed_orders']}\n"
        f"💰 Выручка: {stats['total_revenue']:.2f} RUB\n"
        f"⏳ Ожидают проверки: {stats['pending_orders']}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_pending")
async def admin_pending_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    orders = db.get_pending_orders()
    
    if not orders:
        text = "⏳ Нет заказов, ожидающих проверки"
    else:
        text = "⏳ **Заказы, ожидающие проверки:**\n\n"
        for order in orders:
            order_id, user_id, order_type, recipient, amount_rub, payment_method, created_at = order
            text += f"🆔 #{order_id} | {order_type} | {amount_rub:.2f} RUB\n"
            text += f"👤 {recipient} | 💳 {payment_method}\n"
            text += f"📅 {created_at}\n"
            text += f"🔍 /check_{order_id}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_pending")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_completed")
async def admin_completed_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    orders = db.get_completed_orders()
    
    if not orders:
        text = "✅ **Выполненные заказы**\n\nНет выполненных заказов"
    else:
        text = "✅ **Выполненные заказы**\n\n"
        total_amount = sum(order[4] for order in orders)  # amount_rub
        
        for order in orders[:15]:  # Показываем 15 последних
            order_id, user_id, order_type, recipient, amount_rub, payment_method, created_at = order
            
            # Короткая дата
            if isinstance(created_at, str):
                created_short = created_at.split()[0]
            else:
                created_short = str(created_at)[:10]
            
            text += f"🆔 #{order_id} | {order_type} | {amount_rub:.2f} RUB\n"
            
            if order_type != "exchange":
                text += f"👤 {recipient} | "
            
            text += f"💳 {payment_method}\n"
            text += f"📅 {created_short}\n"
            text += f"🔍 /check_{order_id}\n\n"
        
        if len(orders) > 15:
            text += f"... и ещё {len(orders) - 15} заказов\n"
        
        text += f"\n📊 Всего: {len(orders)} заказов на {total_amount:.2f} RUB"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_completed")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        text=text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    stats = db.get_statistics()
    
    caption = (
        f"🛠️ **Админ панель**\n\n"
        f"📊 **Статистика:**\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"✅ Выполнено заказов: {stats['completed_orders']}\n"
        f"💰 Выручка: {stats['total_revenue']:.2f} RUB\n"
        f"⏳ Ожидают проверки: {stats['pending_orders']}\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (В САМОМ КОНЦЕ) ==========
@dp.message(F.text)
async def handle_text_messages(message: types.Message):
    # Пропускаем команды (они начинаются с /)
    if message.text.startswith('/'):
        return
    
    # Проверяем, не ожидается ли фото
    user_id = message.from_user.id
    if user_id in user_states and user_states[user_id].get("action") == "waiting_payment_photo":
        await message.answer("📸 Пожалуйста, отправьте фото/скриншот оплаты")
        return
    
    text = message.text.strip()
    
    if user_id not in user_states:
        await message.answer("Используйте меню", reply_markup=main_menu_kb())
        return
    
    state = user_states[user_id]
    action = state.get("action")
    
    if action == "waiting_stars_recipient":
        # ✅ РАЗРЕШАЕМ ВВОД С @
        recipient = text.strip()
        
        if recipient.startswith('@'):
            recipient = recipient[1:]
            
        if not recipient:
            await message.answer("❌ Введите username получателя (можно с @)")
            return
        
        state["recipient"] = recipient
        state["action"] = "waiting_stars_amount"
        
        await message.answer(
            f"✅ Получатель: @{recipient}\n\n"
            "Теперь введите количество звезд (от 50 до 1,000,000):",
            reply_markup=back_kb("buy_stars")
        )
    
    elif action == "waiting_stars_amount":
        try:
            stars = int(text)
            if stars < 50 or stars > 1000000:
                await message.answer("❌ Количество звезд должно быть от 50 до 1,000,000")
                return
            
            amount_rub = stars * STAR_RATE
            recipient = state.get("recipient", "")
            
            state["stars_amount"] = stars
            state["amount_rub"] = amount_rub
            
            # Создаем заказ
            order_id = db.add_order(
                user_id, "stars", recipient, 
                json.dumps({"stars": stars}), 
                amount_rub, "card"
            )
            
            # Создаем клавиатуру оплаты
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перевод на карту", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_stars")]
            ])
            
            # Добавляем CryptoBot если есть токен
            if cryptobot:
                keyboard.inline_keyboard.insert(0, [
                    InlineKeyboardButton(text="💎 CryptoBot", callback_data=f"crypto_pay_{order_id}")
                ])
            
            await message.answer(
                f"✅ {stars} звезд для @{recipient}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                "Выберите способ оплаты:",
                reply_markup=keyboard
            )
            
        except ValueError:
            await message.answer("❌ Пожалуйста, введите число")
    
    elif action == "waiting_premium_recipient":
        # ✅ РАЗРЕШАЕМ ВВОД С @
        recipient = text.strip()
        
        if recipient.startswith('@'):
            recipient = recipient[1:]
            
        period = state.get("period")
        amount_rub = state.get("amount_rub")
        
        if period and amount_rub:
            state["recipient"] = recipient
            
            # Создаем заказ
            order_id = db.add_order(
                user_id, "premium", recipient,
                json.dumps({"period": period}),
                amount_rub, "card"
            )
            
            # Создаем клавиатуру оплаты
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перевод на карту", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_premium")]
            ])
            
            # Добавляем CryptoBot если есть токен
            if cryptobot:
                keyboard.inline_keyboard.insert(0, [
                    InlineKeyboardButton(text="💎 CryptoBot", callback_data=f"crypto_pay_{order_id}")
                ])
            
            await message.answer(
                f"✅ {PREMIUM_PRICES[period]['name']} для @{recipient}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                "Выберите способ оплаты:",
                reply_markup=keyboard
            )
    
    elif action == "waiting_exchange_amount":
        try:
            amount_rub = float(text)
            if amount_rub < 100:
                await message.answer("❌ Минимальная сумма: 100 RUB")
                return
            
            amount_usd = amount_rub / USD_RATE
            
            # Создаем заказ
            order_id = db.add_order(
                user_id, "exchange", "",
                json.dumps({
                    "amount_rub": amount_rub, 
                    "amount_usd": amount_usd,
                    "exchange_rate": USD_RATE
                }),
                amount_rub, "card"  # Только карта!
            )
            
            # ✅ ДЛЯ ОБМЕНА ВАЛЮТ ТОЛЬКО КАРТА!
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить картой", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="exchange")]
            ])
            
            await message.answer(
                f"✅ **Обмен валют**\n"
                f"📊 Курс: 1 USD = {USD_RATE} RUB\n"
                f"💸 Вы получаете: {amount_usd:.2f} USD\n"
                f"💰 К оплате: {amount_rub:.2f} RUB\n\n"
                "💳 **Оплата только картой!**\n"
                "После оплаты пришлите скриншот перевода.",
                reply_markup=keyboard
            )
            
        except ValueError:
            await message.answer("❌ Пожалуйста, введите число")

# ========== ЗАПУСК БОТА ==========
async def main():
    print("=" * 50)
    print("🚀 Digi Store Bot запускается...")
    print("=" * 50)
    
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не найден!")
        print("ℹ️  Установите переменную окружения BOT_TOKEN")
        exit(1)
    
    print(f"🤖 Бот: ✅ Настроен")
    print(f"👑 Админ ID: {ADMIN_IDS}")
    print(f"💎 CryptoBot: {'✅ Настроен' if CRYPTOBOT_TOKEN else '❌ Нет токена'}")
    print(f"💳 Карта: {CARD_NUMBER}")
    print(f"⭐️ Курс звезд: 1 звезда = {STAR_RATE} RUB")
    print(f"💱 Курс обмена: 1 USD = {USD_RATE} RUB")
    print("=" * 50)
    print("✅ Все команды готовы к работе!")
    print("📋 Поддерживаемые команды:")
    print(f"👉 /start - начать")
    print(f"👉 /myid - узнать ID")
    print(f"👉 /admin - админ панель")
    print(f"👉 /check_11 или /check 11 - проверить заказ")
    print(f"👉 /confirm_11 или /confirm 11 - подтвердить заказ")
    print(f"👉 /complete_11 или /complete 11 - выполнить заказ")
    print(f"👉 /cancel_11 или /cancel 11 - отменить заказ")
    print("=" * 50)
    print("ℹ️  Старые форматы (/check_11) и новые (/check 11) работают одновременно!")
    print("=" * 50)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())