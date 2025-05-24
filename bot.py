import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)
from google.cloud import firestore

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация бота
class AppConfig:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    NEWS_CHANNEL_LINK = "https://t.me/your_news_channel"
    NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_flash_preview"
    NEWS_CHANNEL_BONUS_GENERATIONS = 10
    DEFAULT_AI_MODE_KEY = "default"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
    CUSTOM_GEMINI_PRO_ENDPOINT = "https://api.gen-api.ru/api/v1/networks/gemini-pro"
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY")
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY")
    DEFAULT_CURRENCY = "RUB"
    GEMS_PER_GEMINI_PRO_REQUEST = 2.5
    GEMS_PER_GROK_3_REQUEST = 2.5
    GEMS_PER_GPT4O_MINI_REQUEST = 0.5
    DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 25
    GEMS_PURCHASE_OPTIONS = [
        {"gems": 10, "price_usd": 1.99, "price_rub": 199},
        {"gems": 50, "gems_bonus": 5, "price_usd": 8.99, "price_rub": 899},
        {"gems": 100, "gems_bonus": 15, "price_usd": 16.99, "price_rub": 1699},
    ]

CONFIG = AppConfig()

# Константы
class BotConstants:
    API_TYPE_GOOGLE = "google"
    API_TYPE_CUSTOM_HTTP = "custom_http"
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"
    FS_USER_GEMS_KEY = "user_gems"
    FS_USER_GEMS_TRANSACTIONS = "gems_transactions"
    MENU_MAIN = "main_menu"
    MENU_AI_MODES_SUBMENU = "ai_modes_submenu"
    MENU_MODELS_SUBMENU = "models_submenu"
    MENU_LIMITS_SUBMENU = "limits_submenu"
    MENU_BONUS_SUBMENU = "bonus_submenu"
    MENU_GEMS_SUBMENU = "gems_submenu"
    MENU_HELP_SUBMENU = "help_submenu"
    CALLBACK_ACTION_SUBMENU = "submenu"
    CALLBACK_ACTION_AI_MODE = "ai_mode"
    CALLBACK_ACTION_MODEL = "model"
    CALLBACK_ACTION_CLAIM_BONUS = "claim_bonus"
    CALLBACK_ACTION_BUY_GEMS = "buy_gems"

# Firestore сервис
class FirestoreService:
    def __init__(self):
        self.db = firestore.AsyncClient()
        self.users_collection = self.db.collection("users")
        self.bot_collection = self.db.collection("bot")

    async def get_user_data(self, user_id: int) -> Dict[str, Any]:
        doc_ref = self.users_collection.document(str(user_id))
        doc = await doc_ref.get()
        return doc.to_dict() or {}

    async def set_user_data(self, user_id: int, data: Dict[str, Any]):
        doc_ref = self.users_collection.document(str(user_id))
        await doc_ref.set(data, merge=True)

    async def get_bot_data(self) -> Dict[str, Any]:
        doc_ref = self.bot_collection.document("data")
        doc = await doc_ref.get()
        return doc.to_dict() or {}

    async def set_bot_data(self, data: Dict[str, Any]):
        doc_ref = self.bot_collection.document("data")
        await doc_ref.set(data, merge=True)

firestore_service = FirestoreService()

# Модели ИИ
AVAILABLE_AI_MODES = {
    "default": {
        "name": "Универсальный",
        "system_prompt": "Ты полезный ИИ-ассистент, отвечающий кратко и по делу."
    },
    "creative": {
        "name": "Творческий",
        "system_prompt": "Ты креативный помощник, предлагающий оригинальные идеи."
    }
}

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0 Flash",
        "id": "gemini-2.0-flash",
        "api_type": BotConstants.API_TYPE_GOOGLE,
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": 50,
        "cost_category": "google_gemini_2_0_flash",
        "pricing_info": {}
    },
    "custom_api_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5 Flash Preview",
        "id": "gemini-2.5-flash-preview-03-25",
        "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gemini-2-5-flash-preview",
        "api_key_var_name": "CUSTOM_GEMINI_25_FLASH_PREVIEW_API_KEY",
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": 10,
        "cost_category": "custom_api_gemini_2_5_flash_preview",
        "pricing_info": {}
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro",
        "id": "gemini-2.5-pro-preview-03-25",
        "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT,
        "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True,
        "limit_type": "gems",
        "gems_per_request": CONFIG.GEMS_PER_GEMINI_PRO_REQUEST,
        "cost_category": "custom_api_pro_paid",
        "pricing_info": {}
    },
    "custom_api_grok_3": {
        "name": "Grok 3",
        "id": "grok-3-beta",
        "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3",
        "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True,
        "limit_type": "gems",
        "gems_per_request": CONFIG.GEMS_PER_GROK_3_REQUEST,
        "cost_category": "custom_api_grok_3_paid",
        "pricing_info": {}
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini",
        "id": "gpt-4o-mini",
        "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini",
        "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True,
        "limit_type": "gems_and_free",
        "gems_per_request": CONFIG.GEMS_PER_GPT4O_MINI_REQUEST,
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY,
        "cost_category": "custom_api_gpt4o_mini_paid",
        "pricing_info": {}
    }
}

# Структура меню
MENU_STRUCTURE = {
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню",
        "items": [
            {"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU},
            {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU},
            {"text": "📊 Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_LIMITS_SUBMENU},
            {"text": "🎁 Бонус", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_BONUS_SUBMENU},
            {"text": "💎 Гемы", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_GEMS_SUBMENU},
            {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}
        ],
        "parent": None,
        "is_submenu": False
    },
    BotConstants.MENU_AI_MODES_SUBMENU: {
        "title": "🤖 Агенты ИИ",
        "items": [
            {"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_AI_MODE, "target": mode_key}
            for mode_key, mode in AVAILABLE_AI_MODES.items()
        ],
        "parent": BotConstants.MENU_MAIN,
        "is_submenu": True
    },
    BotConstants.MENU_MODELS_SUBMENU: {
        "title": "⚙️ Модели ИИ",
        "items": [
            {"text": model["name"], "action": BotConstants.CALLBACK_ACTION_MODEL, "target": model_key}
            for model_key, model in AVAILABLE_TEXT_MODELS.items()
        ],
        "parent": BotConstants.MENU_MAIN,
        "is_submenu": True
    },
    BotConstants.MENU_LIMITS_SUBMENU: {
        "title": "📊 Лимиты",
        "items": [],
        "parent": BotConstants.MENU_MAIN,
        "is_submenu": True
    },
    BotConstants.MENU_BONUS_SUBMENU: {
        "title": "🎁 Бонус",
        "items": [
            {"text": "Получить бонус", "action": BotConstants.CALLBACK_ACTION_CLAIM_BONUS, "target": "claim_news_bonus"}
        ],
        "parent": BotConstants.MENU_MAIN,
        "is_submenu": True
    },
    BotConstants.MENU_GEMS_SUBMENU: {
        "title": "💎 Покупка гемов",
        "items": [
            {"text": f"💎 {opt['gems']} гемов за {opt['price_rub']/100} {CONFIG.DEFAULT_CURRENCY}",
             "action": BotConstants.CALLBACK_ACTION_BUY_GEMS,
             "target": f"gems_{opt['gems']}"}
            for opt in CONFIG.GEMS_PURCHASE_OPTIONS
        ],
        "parent": BotConstants.MENU_MAIN,
        "is_submenu": True
    },
    BotConstants.MENU_HELP_SUBMENU: {
        "title": "❓ Помощь",
        "items": [],
        "parent": BotConstants.MENU_MAIN,
        "is_submenu": True
    }
}

# Декоратор для автоудаления сообщений
def auto_delete_message_decorator(is_command_to_keep: bool = False):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            if update.message:
                user_data_loc = await firestore_service.get_user_data(user_id)
                last_bot_messages = user_data_loc.get("last_bot_messages", [])
                if last_bot_messages and not is_command_to_keep:
                    for message_id in last_bot_messages:
                        try:
                            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=message_id)
                        except telegram.error.TelegramError:
                            pass
                    await firestore_service.set_user_data(user_id, {"last_bot_messages": []})
                result = await func(update, context, *args, **kwargs)
                if update.message:
                    new_message = await update.message.reply_text(
                        result or "Обработка завершена.",
                        parse_mode=telegram.constants.ParseMode.HTML,
                        reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', BotConstants.MENU_MAIN))
                    )
                    last_bot_messages.append(new_message.message_id)
                    await firestore_service.set_user_data(user_id, {"last_bot_messages": last_bot_messages})
                return result
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

# Генерация клавиатуры меню
def generate_menu_keyboard(menu_key: str) -> InlineKeyboardMarkup:
    menu_config = MENU_STRUCTURE.get(menu_key, {})
    buttons = []
    for item in menu_config.get("items", []):
        buttons.append([InlineKeyboardButton(
            item["text"],
            callback_data=f"{item['action']}:{item['target']}"
        )])
    if menu_config.get("parent"):
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{BotConstants.CALLBACK_ACTION_SUBMENU}:{menu_config['parent']}")])
    return InlineKeyboardMarkup(buttons)

# Получение текущей модели
async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    user_data_loc = user_data or await firestore_service.get_user_data(user_id)
    selected_model_id = user_data_loc.get('selected_model_id')
    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config["id"] == selected_model_id:
            return model_key
    return CONFIG.DEFAULT_MODEL_KEY

# Получение деталей текущего режима
async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_data_loc = user_data or await firestore_service.get_user_data(user_id)
    return AVAILABLE_AI_MODES.get(user_data_loc.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY), {})

# Проверка и логирование попытки запроса
async def check_and_log_request_attempt(user_id: int, model_key: str) -> Tuple[bool, str, int]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"):
        return True, "", 0

    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    today_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    model_usage_info = user_daily_counts.get(model_key, {'date': '', 'count': 0})

    if model_usage_info['date'] != today_str:
        model_usage_info = {'date': today_str, 'count': 0}
        user_daily_counts[model_key] = model_usage_info
        all_user_daily_counts[str(user_id)] = user_daily_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})

    current_usage_count = model_usage_info['count']
    user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)

    if model_cfg.get("limit_type") == "gems":
        gems_required = model_cfg.get("gems_per_request", 0.0)
        if user_gems < gems_required:
            return False, (
                f"Недостаточно гемов для использования модели «{model_cfg['name']}». "
                f"Требуется: {gems_required} гемов, у вас: {user_gems:.2f}. "
                f"Пожалуйста, купите гемы через меню «💎 Гемы» или команду /buygems."
            ), current_usage_count
        return True, "", current_usage_count

    elif model_cfg.get("limit_type") == "gems_and_free":
        free_limit = model_cfg.get("free_daily_limit", 0)
        gems_required = model_cfg.get("gems_per_request", 0.0)
        if current_usage_count < free_limit:
            return True, "", current_usage_count
        elif user_gems >= gems_required:
            return True, "", current_usage_count
        else:
            return False, (
                f"Исчерпан бесплатный лимит ({current_usage_count}/{free_limit}) для модели «{model_cfg['name']}», "
                f"и недостаточно гемов. Требуется: {gems_required} гемов, у вас: {user_gems:.2f}. "
                f"Купите гемы через меню «💎 Гемы» или команду /buygems."
            ), current_usage_count

    limit_for_comparison = model_cfg.get("limit", 0)
    if current_usage_count >= limit_for_comparison:
        message_parts = [
            f"Достигнут дневной лимит ({current_usage_count}/{limit_for_comparison}) для модели «{model_cfg['name']}». "
            f"Модель изменена на «{AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]['name']}»."
        ]
        default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
        await firestore_service.set_user_data(user_id, {
            'selected_model_id': default_model_config["id"],
            'selected_api_type': default_model_config.get("api_type")
        })
        if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY:
            bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")
            if not user_data_loc.get('claimed_news_bonus', False):
                message_parts.append(
                    f'💡 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a> для бонусных генераций '
                    f'({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для модели {bonus_model_name})!'
                )
            elif user_data_loc.get('news_bonus_uses_left', 0) == 0:
                message_parts.append(
                    f"ℹ️ Бонус с <a href='{CONFIG.NEWS_CHANNEL_LINK}'>канала новостей</a> для модели {bonus_model_name} уже использован."
                )
        message_parts.append("Попробуйте снова завтра или купите гемы для платных моделей.")
        return False, "\n".join(message_parts), current_usage_count

    return True, "", current_usage_count

# Инкремент счетчика запросов
async def increment_request_count(user_id: int, model_key: str):
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"):
        return

    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    today_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d")

    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and user_data_loc.get('claimed_news_bonus', False):
        bonus_uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        if bonus_uses_left > 0:
            await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_uses_left - 1})
            logger.info(f"User {user_id} consumed a news channel bonus use for model {model_key}. Left: {bonus_uses_left - 1}")
            return

    model_usage_info = user_daily_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_usage_info['date'] != today_str:
        model_usage_info = {'date': today_str, 'count': 0}

    if model_cfg.get("limit_type") in ["gems", "gems_and_free"]:
        user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)
        gems_required = model_cfg.get("gems_per_request", 0.0)
        if model_cfg.get("limit_type") == "gems_and_free" and model_usage_info['count'] < model_cfg.get("free_daily_limit", 0):
            model_usage_info['count'] += 1
        elif user_gems >= gems_required:
            new_gems_balance = user_gems - gems_required
            await firestore_service.set_user_data(user_id, {BotConstants.FS_USER_GEMS_KEY: new_gems_balance})
            model_usage_info['count'] += 1
            transaction = {
                'timestamp': datetime.now(ZoneInfo("UTC")).isoformat(),
                'model_key': model_key,
                'gems_spent': gems_required,
                'new_balance': new_gems_balance
            }
            transactions = user_data_loc.get(BotConstants.FS_USER_GEMS_TRANSACTIONS, [])
            transactions.append(transaction)
            await firestore_service.set_user_data(user_id, {BotConstants.FS_USER_GEMS_TRANSACTIONS: transactions})
            logger.info(f"User {user_id} spent {gems_required} gems on {model_key}. New balance: {new_gems_balance}")
        else:
            logger.warning(f"User {user_id} attempted to use {model_key} but has insufficient gems: {user_gems} < {gems_required}")
            return
    else:
        model_usage_info['count'] += 1

    user_daily_counts[model_key] = model_usage_info
    all_user_daily_counts[str(user_id)] = user_daily_counts
    await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
    logger.info(f"Incremented daily count for user {user_id}, model {model_key} to {model_usage_info['count']}.")

# Получение лимита для модели
async def get_user_actual_limit_for_model(
    user_id: int, 
    model_key: str, 
    user_data: Optional[Dict[str, Any]] = None, 
    bot_data_cache: Optional[Dict[str, Any]] = None
) -> int:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        return 0

    bot_data_loc = bot_data_cache or await firestore_service.get_bot_data()
    user_data_loc = user_data or await firestore_service.get_user_data(user_id)

    limit_type = model_cfg.get("limit_type")
    base_limit = 0

    if limit_type == "daily_free":
        base_limit = model_cfg.get("limit", 0)
    elif limit_type == "gems":
        user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)
        gems_per_request = model_cfg.get("gems_per_request", 0.0)
        base_limit = int(user_gems // gems_per_request) if gems_per_request > 0 else 0
    elif limit_type == "gems_and_free":
        base_limit = model_cfg.get("free_daily_limit", 0)
        user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)
        gems_per_request = model_cfg.get("gems_per_request", 0.0)
        base_limit += int(user_gems // gems_per_request) if gems_per_request > 0 else 0
    elif not model_cfg.get("is_limited", False):
        return float('inf')

    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and user_data_loc.get('claimed_news_bonus', False):
        base_limit += user_data_loc.get('news_bonus_uses_left', 0)
        
    return base_limit

# Команда /start
@auto_delete_message_decorator(is_command_to_keep=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    
    user_data_loc = await firestore_service.get_user_data(user_id)
    updates_to_user_data = {}

    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc:
        updates_to_user_data['current_menu'] = BotConstants.MENU_MAIN
    if BotConstants.FS_USER_GEMS_KEY not in user_data_loc:
        updates_to_user_data[BotConstants.FS_USER_GEMS_KEY] = 0.0
        
    default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
    if 'selected_api_type' not in user_data_loc:
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)
    model_details_res = AVAILABLE_TEXT_MODELS.get(current_model_key_val)
    user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)

    mode_name = mode_details_res['name'] if mode_details_res else "Неизвестный режим"
    model_name = model_details_res['name'] if model_details_res else "Неизвестная модель"

    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель: <b>{model_name}</b>\n"
        f"💎 Баланс гемов: <b>{user_gems:.2f}</b>\n\n"
        "Я готов к вашим запросам! Пишите вопросы или используйте меню. "
        "Для платных моделей нужны гемы — купите их через /buygems или меню «💎 Гемы»."
    )
    await update.message.reply_text(
        greeting_message,
        parse_mode=telegram.constants.ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN),
        disable_web_page_preview=True
    )
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    logger.info(f"User {user_id} ({user_first_name}) started or restarted the bot.")

# Команда /menu
@auto_delete_message_decorator()
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    await update.message.reply_text(
        "📋 Главное меню",
        parse_mode=telegram.constants.ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN)
    )

# Команда /usage
@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await show_limits(update, user_id)

# Команда /buygems
@auto_delete_message_decorator()
async def buy_gems_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await show_gems_menu(update, user_id)

# Команда /bonus
@auto_delete_message_decorator()
async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_loc = await firestore_service.get_user_data(user_id)
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_BONUS_SUBMENU})
    
    if user_data_loc.get('claimed_news_bonus', False):
        bonus_left = user_data_loc.get('news_bonus_uses_left', 0)
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")
        message = (
            f"✅ Вы уже получили бонус за подписку на <a href='{CONFIG.NEWS_CHANNEL_LINK}'>канал новостей</a>.\n"
            f"Осталось <b>{bonus_left}</b> бонусных генераций для модели {bonus_model_name}."
        )
    else:
        message = (
            f"🎁 Подпишитесь на <a href='{CONFIG.NEWS_CHANNEL_LINK}'>канал новостей</a>, чтобы получить "
            f"{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} бонусных генераций для модели "
            f"{AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', 'бонусной модели')}.\n"
            "После подписки нажмите «Получить бонус»."
        )
    
    await update.message.reply_text(
        message,
        parse_mode=telegram.constants.ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_BONUS_SUBMENU),
        disable_web_page_preview=True
    )

# Команда /help
@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await show_help(update, user_id)

# Показ лимитов
async def show_limits(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    
    parts = [f"<b>📊 Ваши текущие лимиты и баланс гемов</b>\n"]
    today_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})
    user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)

    parts.append(f"💎 <b>Баланс гемов</b>: {user_gems:.2f}")
    parts.append(f"ℹ️ Использование платных моделей:\n"
                f"  • Gemini Pro: {CONFIG.GEMS_PER_GEMINI_PRO_REQUEST} гема за запрос\n"
                f"  • Grok 3: {CONFIG.GEMS_PER_GROK_3_REQUEST} гема за запрос\n"
                f"  • GPT-4o mini: {CONFIG.GEMS_PER_GPT4O_MINI_REQUEST} гема за запрос (после {CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY} бесплатных попыток в день)")
    parts.append("\n<b>Лимиты использования</b>:")

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info['date'] == today_str else 0
            
            if model_config.get("limit_type") == "gems":
                limit_display = f"зависит от гемов (нужно {model_config['gems_per_request']} гема/запрос)"
            elif model_config.get("limit_type") == "gems_and_free":
                free_limit = model_config.get("free_daily_limit", 0)
                limit_display = f"{free_limit} бесплатно в день, затем {model_config['gems_per_request']} гема/запрос"
            else:
                actual_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
                limit_display = '∞' if actual_limit == float('inf') else str(actual_limit)

            bonus_notification = ""
            if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and user_data_loc.get('claimed_news_bonus', False):
                bonus_left = user_data_loc.get('news_bonus_uses_left', 0)
                if bonus_left > 0:
                    bonus_notification = f" (включая <b>{bonus_left}</b> бонусных)"
            
            parts.append(f"▫️ {model_config['name']}: <b>{current_day_usage} / {limit_display}</b>{bonus_notification}")

    parts.append("")
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    bonus_model_name_display = bonus_model_cfg['name'] if bonus_model_cfg else "бонусной модели"

    if not user_data_loc.get('claimed_news_bonus', False):
        parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name_display})!')
    elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций с канала новостей для модели {bonus_model_name_display}.")
    else:
        parts.append(f"ℹ️ Бонус с канала новостей для модели {bonus_model_name_display} был использован.")
        
    parts.append("\n💎 Нужны гемы для платных моделей? Используйте команду /buygems или меню «💎 Гемы».")

    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=telegram.constants.ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

# Показ меню покупки гемов
async def show_gems_menu(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    user_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)
    
    parts = [
        f"<b>💎 Покупка гемов</b>",
        f"Ваш текущий баланс: <b>{user_gems:.2f}</b> гемов.",
        f"\nВыберите, сколько гемов хотите купить:"
    ]
    
    await update.message.reply_text(
        "\n".join(parts),
        parse_mode=telegram.constants.ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU),
        disable_web_page_preview=True
    )
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_GEMS_SUBMENU})

# Показ справки
async def show_help(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "Я ваш многофункциональный ИИ-ассистент. Вот как со мной работать:\n\n"
        "1.  <b>Запросы к ИИ</b>: Напишите ваш вопрос или задачу в чат. Я использую текущие настройки агента и модели.\n\n"
        "2.  <b>Меню</b>: Используйте кнопки меню для навигации:\n"
        "    ▫️ «<b>🤖 Агенты ИИ</b>»: Выберите роль ИИ (например, 'Универсальный', 'Творческий').\n"
        "    ▫️ «<b>⚙️ Модели ИИ</b>»: Переключайтесь между моделями. Платные модели требуют гемы.\n"
        "    ▫️ «<b>📊 Лимиты</b>»: Проверьте лимиты и баланс гемов.\n"
        "    ▫️ «<b>🎁 Бонус</b>»: Получите бонусные генерации за подписку на канал.\n"
        "    ▫️ «<b>💎 Гемы</b>»: Купите гемы для использования платных моделей.\n"
        "    ▫️ «<b>❓ Помощь</b>»: Этот раздел.\n\n"
        "3.  <b>Основные команды</b>:\n"
        "    ▫️ /start - Перезапуск бота.\n"
        "    ▫️ /menu - Главное меню.\n"
        "    ▫️ /usage - Показать лимиты и гемы.\n"
        "    ▫️ /buygems - Купить гемы.\n"
        "    ▫️ /bonus - Получить бонус за подписку на канал.\n"
        "    ▫️ /help - Эта справка.\n\n"
        "4.  <b>Гемы</b>: Платные модели (Gemini Pro, Grok 3 — 2.5 гема/запрос, GPT-4o mini — 0.5 гема/запрос после 25 бесплатных попыток в день) требуют гемы. Покупайте через /buygems.\n\n"
        "Если что-то не работает, попробуйте /start или обратитесь в поддержку."
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_HELP_SUBMENU)
    await update.message.reply_text(
        help_text, 
        parse_mode=telegram.constants.ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

# Обработчик кнопок меню
@auto_delete_message_decorator()
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_data_loc = await firestore_service.get_user_data(user_id)
    action_type, action_target = query.data.split(":", 1)
    return_menu_key_after_action = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await firestore_service.set_user_data(user_id, {'current_menu': action_target})
        menu_config = MENU_STRUCTURE.get(action_target, {})
        await query.message.edit_text(
            menu_config.get("title", "Меню"),
            parse_mode=telegram.constants.ParseMode.HTML,
            reply_markup=generate_menu_keyboard(action_target)
        )

    elif action_type == BotConstants.CALLBACK_ACTION_AI_MODE:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        mode_name = AVAILABLE_AI_MODES.get(action_target, {}).get("name", "Неизвестный режим")
        await query.message.edit_text(
            f"✅ Выбран агент: <b>{mode_name}</b>",
            parse_mode=telegram.constants.ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu_key_after_action)
        )

    elif action_type == BotConstants.CALLBACK_ACTION_MODEL:
        model_config = AVAILABLE_TEXT_MODELS.get(action_target)
        if model_config:
            await firestore_service.set_user_data(user_id, {
                'selected_model_id': model_config["id"],
                'selected_api_type': model_config.get("api_type")
            })
            await query.message.edit_text(
                f"✅ Выбрана модель: <b>{model_config['name']}</b>",
                parse_mode=telegram.constants.ParseMode.HTML,
                reply_markup=generate_menu_keyboard(return_menu_key_after_action)
            )

    elif action_type == BotConstants.CALLBACK_ACTION_CLAIM_BONUS:
        user_data_loc = await firestore_service.get_user_data(user_id)
        if not user_data_loc.get('claimed_news_bonus', False):
            try:
                chat_member = await context.bot.get_chat_member(CONFIG.NEWS_CHANNEL_LINK.split("/")[-1], user_id)
                if chat_member.status in ['member', 'administrator', 'creator']:
                    await firestore_service.set_user_data(user_id, {
                        'claimed_news_bonus': True,
                        'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS
                    })
                    bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")
                    await query.message.edit_text(
                        f"🎉 Бонус получен! Вам начислено {CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} генераций для модели {bonus_model_name}.",
                        parse_mode=telegram.constants.ParseMode.HTML,
                        reply_markup=generate_menu_keyboard(return_menu_key_after_action)
                    )
                else:
                    await query.message.edit_text(
                        f"⚠️ Вы не подписаны на <a href='{CONFIG.NEWS_CHANNEL_LINK}'>канал новостей</a>. Подпишитесь и попробуйте снова.",
                        parse_mode=telegram.constants.ParseMode.HTML,
                        reply_markup=generate_menu_keyboard(return_menu_key_after_action),
                        disable_web_page_preview=True
                    )
            except telegram.error.TelegramError as e:
                logger.error(f"Error checking channel subscription for user {user_id}: {e}")
                await query.message.edit_text(
                    "⚠️ Ошибка при проверке подписки. Попробуйте позже или свяжитесь с поддержкой.",
                    parse_mode=telegram.constants.ParseMode.HTML,
                    reply_markup=generate_menu_keyboard(return_menu_key_after_action)
                )
        else:
            bonus_left = user_data_loc.get('news_bonus_uses_left', 0)
            bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")
            await query.message.edit_text(
                f"✅ Вы уже получили бонус. Осталось <b>{bonus_left}</b> генераций для модели {bonus_model_name}.",
                parse_mode=telegram.constants.ParseMode.HTML,
                reply_markup=generate_menu_keyboard(return_menu_key_after_action)
            )

    elif action_type == BotConstants.CALLBACK_ACTION_BUY_GEMS:
        gems_count = int(action_target.split('_')[1])
        purchase_option = next((opt for opt in CONFIG.GEMS_PURCHASE_OPTIONS if opt['gems'] == gems_count), None)
        if not purchase_option:
            await query.message.edit_text(
                "Ошибка: Выбранный вариант покупки недоступен.",
                reply_markup=generate_menu_keyboard(return_menu_key_after_action)
            )
            return
        await send_gems_invoice(update, context, user_id, purchase_option)

    await query.answer()

# Отправка счета для покупки гемов
async def send_gems_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, purchase_option: Dict[str, Any]):
    gems_count = purchase_option['gems']
    bonus_gems = purchase_option.get('gems_bonus', 0)
    total_gems = gems_count + bonus_gems
    price = purchase_option[f"price_{CONFIG.DEFAULT_CURRENCY.lower()}"]
    currency = CONFIG.DEFAULT_CURRENCY
    
    title = f"Покупка {total_gems} гемов"
    description = f"Приобретите {gems_count} гемов"
    if bonus_gems > 0:
        description += f" + {bonus_gems} бонусных гемов"
    description += f" для использования платных моделей ИИ."
    
    payload = f"gems_purchase_{gems_count}_user_{user_id}"
    
    prices = [LabeledPrice(f"{total_gems} гемов", int(price * 100))]
    
    try:
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN,
            currency=currency,
            prices=prices,
            max_tip_amount=0,
            suggested_tip_amounts=[],
            start_parameter=f"gems_{gems_count}",
            need_email=False,
            need_phone_number=False,
            need_shipping_address=False,
            is_flexible=False
        )
        logger.info(f"Sent invoice for {total_gems} gems to user {user_id}")
    except telegram.error.TelegramError as e:
        logger.error(f"Failed to send invoice to user {user_id}: {e}")
        user_data_loc = await firestore_service.get_user_data(user_id)
        await update.effective_message.reply_text(
            "Не удалось сформировать счет для покупки. Попробуйте позже или свяжитесь с поддержкой.",
            reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', BotConstants.MENU_GEMS_SUBMENU))
        )

# Обработчик предпроверки платежа
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload and "gems_purchase" in query.invoice_payload:
        await query.answer(ok=True)
        logger.info(f"PreCheckoutQuery OK for payload: {query.invoice_payload}")
    else:
        await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату.")
        logger.warning(f"PreCheckoutQuery FAILED. Expected 'gems_purchase' in payload, got: {query.invoice_payload}")

# Обработчик успешного платежа
async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    payload = payment_info.invoice_payload
    
    if not payload.startswith("gems_purchase_"):
        logger.warning(f"Invalid payment payload for user {user_id}: {payload}")
        return
    
    try:
        gems_count = int(payload.split('_')[2])
        purchase_option = next((opt for opt in CONFIG.GEMS_PURCHASE_OPTIONS if opt['gems'] == gems_count), None)
        if not purchase_option:
            logger.error(f"No matching purchase option for {gems_count} gems for user {user_id}")
            return
        
        total_gems = gems_count + purchase_option.get('gems_bonus', 0)
        user_data_loc = await firestore_service.get_user_data(user_id)
        current_gems = user_data_loc.get(BotConstants.FS_USER_GEMS_KEY, 0.0)
        new_gems_balance = current_gems + total_gems
        
        await firestore_service.set_user_data(user_id, {BotConstants.FS_USER_GEMS_KEY: new_gems_balance})
        
        transaction = {
            'timestamp': datetime.now(ZoneInfo("UTC")).isoformat(),
            'gems_added': total_gems,
            'price': payment_info.total_amount,
            'currency': payment_info.currency,
            'new_balance': new_gems_balance,
            'telegram_payment_charge_id': payment_info.telegram_payment_charge_id,
            'provider_payment_charge_id': payment_info.provider_payment_charge_id
        }
        transactions = user_data_loc.get(BotConstants.FS_USER_GEMS_TRANSACTIONS, [])
        transactions.append(transaction)
        await firestore_service.set_user_data(user_id, {BotConstants.FS_USER_GEMS_TRANSACTIONS: transactions})
        
        bonus_text = f" + {purchase_option['gems_bonus']} бонусных" if purchase_option.get('gems_bonus', 0) > 0 else ""
        confirmation_message = (
            f"🎉 Оплата прошла успешно! Вам начислено <b>{total_gems}</b> гемов{bonus_text}. "
            f"Новый баланс: <b>{new_gems_balance:.2f}</b> гемов."
        )
        
        await update.message.reply_text(
            confirmation_message,
            parse_mode=telegram.constants.ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', BotConstants.MENU_MAIN))
        )
        
        if CONFIG.ADMIN_ID:
            admin_message = (
                f"🔔 Новая покупка гемов!\n"
                f"Пользователь: {user_id} (@{update.effective_user.username})\n"
                f"Гемов: {total_gems} (основные: {gems_count}, бонус: {purchase_option.get('gems_bonus', 0)})\n"
                f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                f"Payload: {payload}"
            )
            await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
            
    except Exception as e:
        logger.error(f"Error processing payment for user {user_id}: {e}", exc_info=True)
        user_data_loc = await firestore_service.get_user_data(user_id)
        await update.message.reply_text(
            "Ошибка при обработке платежа. Пожалуйста, свяжитесь с поддержкой.",
            reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', BotConstants.MENU_MAIN))
        )

# Обработчик текстовых сообщений
@auto_delete_message_decorator()
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_loc = await firestore_service.get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id, user_data_loc)
    current_mode = await get_current_mode_details(user_id, user_data_loc)
    
    can_proceed, error_message, current_usage = await check_and_log_request_attempt(user_id, current_model_key)
    if not can_proceed:
        await update.message.reply_text(
            error_message,
            parse_mode=telegram.constants.ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', BotConstants.MENU_MAIN)),
            disable_web_page_preview=True
        )
        return
    
    # Заглушка для генерации ответа
    response_text = f"Ответ от модели {AVAILABLE_TEXT_MODELS[current_model_key]['name']}: {update.message.text}"
    
    await increment_request_count(user_id, current_model_key)
    
    await update.message.reply_text(
        response_text,
        parse_mode=telegram.constants.ParseMode.HTML,
        reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', BotConstants.MENU_MAIN))
    )

# Основная функция
async def main():
    app = Application.builder().token(CONFIG.BOT_TOKEN).build()
    
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск бота / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Показать лимиты и баланс гемов"),
        BotCommand("buygems", "💎 Купить гемы для платных моделей"),
        BotCommand("bonus", "🎁 Получить бонус за подписку на канал"),
        BotCommand("help", "❓ Получить справку по боту")
    ]
    await app.bot.set_my_commands(bot_commands)

    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("buygems", buy_gems_command), group=0)
    app.add_handler(CommandHandler("bonus", bonus_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    app.add_handler(CallbackQueryHandler(menu_button_handler), group=0)
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback), group=0)
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=0)

    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
