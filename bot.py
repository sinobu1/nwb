import os
import logging
import asyncio
from datetime import datetime, timezone
import json
import requests
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from telegram import BotCommand, ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from firebase_admin import initialize_app, firestore
import firebase_admin

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
class BotConstants:
    FS_USERS_COLLECTION = "users"
    FS_BOT_DATA_COLLECTION = "bot_data"
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"

# Конфигурация
class AppConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID = os.getenv("ADMIN_ID", None)
    MIN_AI_REQUEST_LENGTH = 10
    MAX_MESSAGE_LENGTH_TELEGRAM = 4096
    DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 25
    GEMS_PER_REQUEST_GEMINI_PRO = 2.5
    GEMS_PER_REQUEST_GROK_3 = 2.5
    GEMS_PER_REQUEST_GPT4O_MINI = 0.5
    CALLBACK_URL = os.getenv("CALLBACK_URL", "https://your-server.com/callback")
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TEMPERATURE = 1.0
    DEFAULT_TOP_P = 1.0
    DEFAULT_FREQUENCY_PENALTY = 0.0
    DEFAULT_PRESENCE_PENALTY = 0.0

CONFIG = AppConfig()

# API ключи
_API_KEYS_PROVIDER = {
    "CUSTOM_GEMINI_2_5_PRO_API_KEY": os.getenv("CUSTOM_GEMINI_2_5_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"),
    "CUSTOM_GROK_3_API_KEY": os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"),
    "CUSTOM_GPT4O_MINI_API_KEY": os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
}

# Модели
AVAILABLE_TEXT_MODELS = {
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini 2.5 Pro",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro",
        "api_key_var_name": "CUSTOM_GEMINI_2_5_PRO_API_KEY",
        "is_limited": True,
    },
    "custom_api_grok_3": {
        "name": "Grok 3",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3",
        "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True,
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o Mini",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini",
        "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True,
    }
}

# Структура меню
MENU_STRUCTURE = {
    "main_menu": {
        "title": "📋 Главное меню",
        "items": [
            {"text": "🤖 Агенты ИИ", "action": "submenu", "target": "ai_modes_submenu"},
            {"text": "⚙️ Модели ИИ", "action": "submenu", "target": "models_submenu"},
            {"text": "📊 Лимиты", "action": "submenu", "target": "limits_submenu"},
            {"text": "🎁 Бонус", "action": "submenu", "target": "bonus_submenu"},
            {"text": "💎 Купить гемы", "action": "show_subscription", "target": "buy_gems"},
            {"text": "❓ Помощь", "action": "submenu", "target": "help_submenu"}
        ],
        "parent": None,
        "is_submenu": False
    },
    "ai_modes_submenu": {
        "title": "🤖 Выберите режим ИИ",
        "items": [
            {"text": "🧑‍💻 Программист", "action": "set_mode", "target": "programmer"},
            {"text": "📚 Учитель", "action": "set_mode", "target": "teacher"},
            {"text": "🧠 Психолог", "action": "set_mode", "target": "psychologist"},
            {"text": "🔙 Назад", "action": "submenu", "target": "main_menu"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "models_submenu": {
        "title": "⚙️ Выберите модель ИИ",
        "items": [
            {"text": "Gemini 2.5 Pro", "action": "set_model", "target": "custom_api_gemini_2_5_pro"},
            {"text": "Grok 3", "action": "set_model", "target": "custom_api_grok_3"},
            {"text": "GPT-4o Mini", "action": "set_model", "target": "custom_api_gpt_4o_mini"},
            {"text": "🔙 Назад", "action": "submenu", "target": "main_menu"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "limits_submenu": {
        "title": "📊 Лимиты",
        "items": [
            {"text": "🔙 Назад", "action": "submenu", "target": "main_menu"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "bonus_submenu": {
        "title": "🎁 Бонус",
        "items": [
            {"text": "🔙 Назад", "action": "submenu", "target": "main_menu"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "help_submenu": {
        "title": "❓ Помощь",
        "items": [
            {"text": "🔙 Назад", "action": "submenu", "target": "main_menu"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    }
}

# Сервис Firestore
class FirestoreService:
    def __init__(self):
        self._db = firestore.client() if firebase_admin._apps else None

    async def get_user_data(self, user_id: int) -> Dict[str, Any]:
        if not self._db:
            return {}
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc.exists else {}

    async def set_user_data(self, user_id: int, data: Dict[str, Any]) -> None:
        if not self._db:
            return
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        await self._execute_firestore_op(doc_ref.set, data, merge=True)
        logger.debug(f"User data for {user_id} updated with keys: {list(data.keys())}")

    async def get_bot_data(self) -> Dict[str, Any]:
        if not self._db:
            return {}
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document("data")
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc.exists else {}

    async def set_bot_data(self, data: Dict[str, Any]) -> None:
        if not self._db:
            return
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document("data")
        await self._execute_firestore_op(doc_ref.set, data, merge=True)

    async def _execute_firestore_op(self, op, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: op(*args, **kwargs))

firestore_service = FirestoreService()

# Базовый класс AI сервиса
class BaseAIService:
    def __init__(self, model_id: str, model_config: Dict[str, Any]):
        self.model_id = model_id
        self.model_config = model_config

    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

# HTTP AI сервис
class CustomHttpAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        api_key_name = self.model_config.get("api_key_var_name")
        actual_key = _API_KEYS_PROVIDER.get(api_key_name)

        if not actual_key or "YOUR_" in actual_key or not (actual_key.startswith("sk-") or actual_key.startswith("AIzaSy")):
            logger.error(f"Invalid API key for model {self.model_id} (key name: {api_key_name}).")
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."

        headers = {
            "Authorization": f"Bearer {actual_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        is_gpt4o_like = (self.model_id == "custom_api_gpt_4o_mini")

        messages_payload = []
        if system_prompt:
            messages_payload.append({
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}] if is_gpt4o_like else system_prompt
            })
        messages_payload.append({
            "role": "user",
            "content": [{"type": "text", "text": user_prompt}] if is_gpt4o_like else user_prompt
        })

        payload = {
            "callback_url": CONFIG.CALLBACK_URL,
            "is_sync": False,
            "messages": messages_payload,
            "model": self.model_id,
            "max_tokens": self.model_config.get("max_tokens", CONFIG.DEFAULT_MAX_TOKENS),
            "temperature": CONFIG.DEFAULT_TEMPERATURE,
            "top_p": CONFIG.DEFAULT_TOP_P,
            "frequency_penalty": CONFIG.DEFAULT_FREQUENCY_PENALTY,
            "presence_penalty": CONFIG.DEFAULT_PRESENCE_PENALTY,
            "response_format": {"type": "text"}
        }

        endpoint = self.model_config["endpoint"]

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(endpoint, headers=headers, json=payload, timeout=45)
            )
            response.raise_for_status()
            json_resp = response.json()

            if json_resp.get("status") == "starting":
                request_id = json_resp.get("request_id")
                if request_id:
                    return f"REQUEST_ID:{request_id}"
                return "Ошибка: request_id не получен от API."
            else:
                return f"Ошибка API: {json_resp.get('status', 'N/A')}. {json_resp.get('error_message', '')}"

        except requests.exceptions.HTTPError as e:
            logger.error(f"Custom API HTTPError for {self.model_id} ({endpoint}): {e.response.status_code} - {e.response.text}", exc_info=True)
            return f"Ошибка сети Custom API ({e.response.status_code}) для {self.model_config['name']}."
        except requests.exceptions.RequestException as e:
            logger.error(f"Custom API RequestException for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Сетевая ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."
        except Exception as e:
            logger.error(f"Unexpected Custom API error for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Неожиданная ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."

def get_ai_service(model_key: str) -> Optional[BaseAIService]:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config:
        return None
    return CustomHttpAIService(model_key, model_config)

# Утилиты
def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if len(text) <= max_length:
        return text, False
    return text[:max_length - 3] + "...", True

def is_menu_button_text(text: str) -> bool:
    return any(item["text"] == text for menu in MENU_STRUCTURE.values() for item in menu["items"])

async def get_current_model_key(user_id: int, user_data: Dict[str, Any]) -> str:
    return user_data.get("current_model", "custom_api_gpt_4o_mini")

async def get_current_mode_details(user_id: int, user_data: Dict[str, Any]) -> Dict[str, str]:
    return {"prompt": "You are a helpful AI assistant."}  # Упрощено для примера

async def get_user_actual_limit_for_model(
    user_id: int,
    model_key: str,
    user_data: Optional[Dict[str, Any]] = None,
    bot_data_cache: Optional[Dict[str, Any]] = None
) -> int:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        return 0

    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    gems_balance = user_data_loc.get('gems_balance', 0.0)

    if model_key == "custom_api_gpt_4o_mini":
        return CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY

    cost = CONFIG.GEMS_PER_REQUEST_GEMINI_PRO if model_key in ["custom_api_gemini_2_5_pro", "custom_api_grok_3"] else CONFIG.GEMS_PER_REQUEST_GPT4O_MINI
    return int(gems_balance / cost) if cost > 0 else float('inf')

async def check_and_log_request_attempt(user_id: int, model_key: str) -> Tuple[bool, str, int]:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    user_data_loc = await firestore_service.get_user_data(user_id)
    gems_balance = user_data_loc.get('gems_balance', 0.0)

    if not model_cfg.get("is_limited") or model_key == "custom_api_gpt_4o_mini":
        all_user_daily_counts = (await firestore_service.get_bot_data()).get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
        user_daily_counts = all_user_daily_counts.get(str(user_id), {})
        model_usage_info = user_daily_counts.get(model_key, {'date': today_str, 'count': 0})

        if model_usage_info['date'] != today_str:
            model_usage_info = {'date': today_str, 'count': 0}
            user_daily_counts[model_key] = model_usage_info
            all_user_daily_counts[str(user_id)] = user_daily_counts
            await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})

        current_usage_count = model_usage_info['count']
        limit = CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY if model_key == "custom_api_gpt_4o_mini" else float('inf')

        if current_usage_count >= limit:
            return False, f"Достигнут дневной лимит ({current_usage_count}/{limit}) для модели «{model_cfg['name']}».", current_usage_count
        return True, "", current_usage_count

    cost = CONFIG.GEMS_PER_REQUEST_GEMINI_PRO if model_key in ["custom_api_gemini_2_5_pro", "custom_api_grok_3"] else CONFIG.GEMS_PER_REQUEST_GPT4O_MINI
    if gems_balance < cost:
        return False, f"Недостаточно гемов ({gems_balance:.1f}). Требуется: {cost:.1f}. Пополните баланс через /buy_gems.", 0
    return True, "", 0

async def increment_request_count(user_id: int, model_key: str):
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    user_data_loc = await firestore_service.get_user_data(user_id)

    if not model_cfg.get("is_limited") or model_key == "custom_api_gpt_4o_mini":
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bot_data_loc = await firestore_service.get_bot_data()
        all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
        user_daily_counts = all_user_daily_counts.get(str(user_id), {})
        
        model_usage_info = user_daily_counts.get(model_key, {'date': today_str, 'count': 0})
        if model_usage_info['date'] != today_str:
            model_usage_info = {'date': today_str, 'count': 0}
        
        model_usage_info['count'] += 1
        user_daily_counts[model_key] = model_usage_info
        all_user_daily_counts[str(user_id)] = user_daily_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
        logger.info(f"Incremented daily count for user {user_id}, model {model_key} to {model_usage_info['count']}.")
        return

    cost = CONFIG.GEMS_PER_REQUEST_GEMINI_PRO if model_key in ["custom_api_gemini_2_5_pro", "custom_api_grok_3"] else CONFIG.GEMS_PER_REQUEST_GPT4O_MINI
    new_balance = user_data_loc.get('gems_balance', 0.0) - cost
    await firestore_service.set_user_data(user_id, {'gems_balance': new_balance})
    logger.info(f"User {user_id} spent {cost:.1f} gems on model {model_key}. New balance: {new_balance:.1f}")

def generate_menu_keyboard(current_menu: str) -> InlineKeyboardMarkup:
    menu_data = MENU_STRUCTURE.get(current_menu, MENU_STRUCTURE["main_menu"])
    buttons = [
        InlineKeyboardButton(item["text"], callback_data=f"{item['action']}:{item['target']}")
        for item in menu_data["items"]
    ]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(keyboard)

# Обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await firestore_service.set_user_data(user_id, {
        "current_menu": "main_menu",
        "current_model": "custom_api_gpt_4o_mini",
        "gems_balance": 0.0
    })
    await update.message.reply_text(
        "Добро пожаловать! Выберите опцию в меню:",
        reply_markup=generate_menu_keyboard("main_menu")
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await firestore_service.get_user_data(user_id)
    await update.message.reply_text(
        "📋 Главное меню",
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
    )

async def show_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    
    gems_balance = user_data_loc.get('gems_balance', 0.0)
    parts = [f"<b>📊 Ваш текущий баланс</b>: <b>{gems_balance:.1f}</b> гемов\n"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info['date'] == today_str else 0
            
            if model_key == "custom_api_gpt_4o_mini":
                actual_limit = CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY
                cost = CONFIG.GEMS_PER_REQUEST_GPT4O_MINI
                parts.append(f"▫️ {model_config['name']}: <b>{current_day_usage} / {actual_limit}</b> (бесплатно, затем {cost} гема/запрос)")
            else:
                cost = CONFIG.GEMS_PER_REQUEST_GEMINI_PRO if model_key in ["custom_api_gemini_2_5_pro", "custom_api_grok_3"] else 0
                parts.append(f"▫️ {model_config['name']}: {cost} гема/запрос")

    parts.append("\n💎 Пополните баланс гемов через команду /buy_gems или кнопку «💎 Купить гемы» в меню.")
    
    current_menu_for_reply = user_data_loc.get('current_menu', 'limits_submenu')
    await update.message.reply_text(
        "\n".join(parts),
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def buy_gems_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_loc = await firestore_service.get_user_data(user_id)
    
    gems_balance = user_data_loc.get('gems_balance', 0.0)
    message = (
        f"<b>💎 Покупка гемов</b>\n\n"
        f"Ваш текущий баланс: <b>{gems_balance:.1f}</b> гемов.\n\n"
        f"Стоимость запросов:\n"
        f"▫️ Gemini Pro: {CONFIG.GEMS_PER_REQUEST_GEMINI_PRO} гема\n"
        f"▫️ Grok 3: {CONFIG.GEMS_PER_REQUEST_GROK_3} гема\n"
        f"▫️ GPT-4o Mini: {CONFIG.GEMS_PER_REQUEST_GPT4O_MINI} гема (первые {CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY} бесплатно ежедневно)\n\n"
        f"Выберите количество гемов для покупки:"
    )
    
    inline_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("10 гемов - $1", callback_data="buy_gems_10"),
            InlineKeyboardButton("50 гемов - $4", callback_data="buy_gems_50")
        ],
        [InlineKeyboardButton("100 гемов - $7", callback_data="buy_gems_100")]
    ])
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=inline_keyboard,
        disable_web_page_preview=True
    )

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    action, target = data.split(":", 1) if ":" in data else (data, "")
    
    user_data = await firestore_service.get_user_data(user_id)
    
    if action == "submenu":
        await firestore_service.set_user_data(user_id, {"current_menu": target})
        await query.message.edit_text(
            MENU_STRUCTURE[target]["title"],
            reply_markup=generate_menu_keyboard(target)
        )
    elif action == "set_model":
        await firestore_service.set_user_data(user_id, {"current_model": target})
        await query.message.edit_text(
            f"Выбрана модель: {AVAILABLE_TEXT_MODELS[target]['name']}",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
        )
    elif action == "set_mode":
        await firestore_service.set_user_data(user_id, {"current_mode": target})
        await query.message.edit_text(
            f"Выбран режим: {target}",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
        )
    elif action == "show_subscription" and target == "buy_gems":
        await buy_gems_command(update, context)
    elif action in ["buy_gems_10", "buy_gems_50", "buy_gems_100"]:
        gems_packages = {
            "buy_gems_10": {"gems": 10, "amount": 100},
            "buy_gems_50": {"gems": 50, "amount": 400},
            "buy_gems_100": {"gems": 100, "amount": 700}
        }
        package = gems_packages[action]
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Покупка {package['gems']} гемов",
            description=f"Пополнение баланса на {package['gems']} гемов для использования платных моделей ИИ.",
            payload=f"gems_{package['gems']}_user_{user_id}",
            provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN,
            currency="USD",
            prices=[LabeledPrice(f"{package['gems']} гемов", package['amount'] * 100)],
            start_parameter=f"gems_{package['gems']}"
        )

async def pre_checkout_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.answer_pre_checkout_query(
        pre_checkout_query_id=update.pre_checkout_query.id,
        ok=True
    )

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    payload = payment_info.invoice_payload
    
    logger.info(f"Successful payment received from user {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {payload}")
    
    try:
        gems_count = int(payload.split("_")[1])
        user_data_loc = await firestore_service.get_user_data(user_id)
        current_balance = user_data_loc.get('gems_balance', 0.0)
        new_balance = current_balance + gems_count
        
        await firestore_service.set_user_data(user_id, {
            'gems_balance': new_balance,
            'last_gems_purchase': datetime.now(timezone.utc).isoformat()
        })
        
        confirmation_message = (
            f"🎉 Оплата прошла успешно! Вам начислено <b>{gems_count}</b> гемов.\n"
            f"Новый баланс: <b>{new_balance:.1f}</b> гемов."
        )
        await update.message.reply_text(
            confirmation_message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', 'main_menu'))
        )
        
        if CONFIG.ADMIN_ID:
            admin_message = (
                f"🔔 Новая покупка гемов!\n"
                f"Пользователь: {user_id} (@{update.effective_user.username})\n"
                f"Гемов: {gems_count}\n"
                f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                f"Payload: {payload}"
            )
            await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
            
    except Exception as e:
        logger.error(f"Error processing payment for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Ошибка при начислении гемов. Пожалуйста, свяжитесь с поддержкой.",
            reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu', 'main_menu'))
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        return

    user_message_text = update.message.text.strip()
    
    if is_menu_button_text(user_message_text):
        logger.debug(f"User {user_id} sent menu button text '{user_message_text}' that reached handle_text. Ignoring.")
        return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        await update.message.reply_text(
            "Ваш запрос слишком короткий. Пожалуйста, сформулируйте его более подробно.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu'))
        )
        return

    logger.info(f"User {user_id} sent AI request: '{user_message_text[:100]}...'")
    
    user_data_cache = await firestore_service.get_user_data(user_id)
    current_model_key_val = await get_current_model_key(user_id, user_data_cache)
    
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key_val)
    if not can_proceed:
        await update.message.reply_text(
            limit_message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    ai_service = get_ai_service(current_model_key_val)
    if not ai_service:
        await update.message.reply_text(
            "Ошибка: Не удалось выбрать AI модель. Попробуйте /start.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu'))
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details_val = await get_current_mode_details(user_id, user_data_cache)
    system_prompt_val = mode_details_val["prompt"]
    
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ."
    try:
        ai_response_text = await ai_service.generate_response(system_prompt_val, user_message_text)
        if ai_response_text.startswith("REQUEST_ID:"):
            request_id = ai_response_text.split(":", 1)[1]
            await firestore_service.set_user_data(user_id, {
                'pending_request': {
                    'request_id': request_id,
                    'model_key': current_model_key_val,
                    'chat_id': update.effective_chat.id,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            })
            ai_response_text = "Ваш запрос принят и обрабатывается. Ответ будет отправлен, как только он будет готов."
        else:
            await increment_request_count(user_id, current_model_key_val)
    except Exception as e:
        logger.error(f"Error in AI service {type(ai_service).__name__} for model {current_model_key_val}: {e}", exc_info=True)
        ai_response_text = f"Ошибка при обработке запроса моделью {ai_service.model_config['name']}."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    await update.message.reply_text(
        final_reply_text,
        reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Sent response to user {user_id} for model {current_model_key_val}.")

# Главная функция
async def main():
    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()
    
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск бота / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Показать мой баланс и лимиты"),
        BotCommand("buy_gems", "💎 Купить гемы для использования платных моделей"),
        BotCommand("bonus", "🎁 Получить бонус за подписку на канал"),
        BotCommand("help", "❓ Получить справку по боту")
    ]
    await app.bot.set_my_commands(bot_commands)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("usage", show_limits))
    app.add_handler(CommandHandler("buy_gems", buy_gems_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_query))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)
