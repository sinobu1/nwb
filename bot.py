import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
)
import google.generativeai as genai
import google.api_core.exceptions
import requests
import logging
import traceback
import os
import asyncio
import json
from datetime import datetime, timedelta
from telegram import LabeledPrice
from typing import Optional
import uuid
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from collections import defaultdict
from time import time

# Enable debug logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# --- API KEYS AND TOKENS ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
YOUR_ADMIN_ID = 489230152

# --- BOT CONFIG ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000
MIN_AI_REQUEST_LENGTH = 4

# --- LIMITS ---
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"
DEFAULT_FREE_REQUESTS_GROK_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY = 25
DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY = 25

# --- NEWS CHANNEL AND BONUS ---
NEWS_CHANNEL_USERNAME = "@timextech"
NEWS_CHANNEL_LINK = "https://t.me/timextech"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
NEWS_CHANNEL_BONUS_GENERATIONS = 1

# --- AI AGENTS ---
AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент от Google. "
            "Твоя цель — эффективно помогать пользователю с широким спектром задач: "
            "отвечать на вопросы, генерировать текст, объяснять, анализировать и предоставлять информацию. "
            "Всегда будь вежлив, объективен, точен и полезен. "
            "Предупреждай, если твои знания ограничены по времени. "
            "ОФОРМЛЕНИЕ ОТВЕТА: "
            "1. Структура и ясность: Ответ должен быть понятным, структурированным, с абзацами. "
            "2. Списки: Используй нумерованные или маркированные списки для перечислений. "
            "3. Заголовки: Для крупных блоков используй краткие заголовки. "
            "4. Чистота текста: Генерируй ясный текст без избыточных символов. "
            "5. Полнота: Давай полные ответы, завершай списки."
        ),
        "welcome": "Активирован агент 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный ИИ-ассистент. "
            "Твоя задача — предоставлять точные, развернутые и полезные ответы. "
            "Соблюдай вежливость и объективность. "
            "Формулируй ответы ясно, структурированно, с абзацами и списками при необходимости. "
            "Укажи, если знания ограничены по времени."
        ),
        "welcome": "Активирован агент 'Продвинутый'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "Творческий",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр. "
            "Твоя миссия — вдохновлять, помогать в создании текстов, идей, сценариев, стихов. "
            "Будь смелым в идеях, но оставайся в рамках этики. "
            "Форматирование: "
            "1. Абзацы: Четкое разделение для прозы. "
            "2. Стихи: Соблюдай строфы и строки. "
            "3. Диалоги: Оформляй стандартно, например: - Привет! - сказал он. "
            "4. Язык: Используй выразительный язык. "
            "5. Завершённость: Доводи произведения до конца."
        ),
        "welcome": "Агент 'Творческий' к вашим услугам! Над какой задачей поработаем?"
    },
    "analyst": {
        "name": "Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик на базе Gemini. "
            "Твоя задача — предоставлять точные, логически обоснованные ответы на запросы, связанные с анализом данных, фактов или бизнес-вопросов. "
            "Используй структурированный подход: "
            "1. Анализ: Разбери запрос на ключевые аспекты. "
            "2. Выводы: Дай четкие выводы или рекомендации. "
            "3. Обоснование: Объясни свои рассуждения. "
            "Если данных недостаточно, укажи это."
        ),
        "welcome": "Агент 'Аналитик' активирован. Какую задачу проанализировать?"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini. "
            "Твоя задача — отвечать с остроумием и юмором, сохраняя полезность. "
            "Добавляй шутки, анекдоты, но оставайся в рамках приличия. "
            "Форматируй ответы весело и читабельно."
        ),
        "welcome": "Агент 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

# --- AI MODELS ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0",
        "id": "gemini-2.0-flash",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY,
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5",
        "id": "gemini-2.5-flash-preview-04-17",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY,
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro",
        "id": "gemini-2.5-pro-preview-03-25",
        "api_type": "custom_http_api",
        "endpoint": CUSTOM_GEMINI_PRO_ENDPOINT,
        "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY,
        "cost_category": "custom_api_pro_paid"
    },
    "custom_api_grok_3": {
        "name": "Grok 3",
        "id": "grok-3-beta",
        "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3",
        "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GROK_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY,
        "cost_category": "custom_api_grok_3_paid"
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini",
        "id": "gpt-4o-mini",
        "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini",
        "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY,
        "cost_category": "custom_api_gpt4o_mini_paid"
    }
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

# --- MENU STRUCTURE ---
MENU_STRUCTURE = {
    "main_menu": {
        "title": "📋 Главное меню",
        "items": [
            ("🤖 Агенты ИИ", "submenu", "ai_modes_submenu"),
            ("⚙️ Модели ИИ", "submenu", "models_submenu"),
            ("📊 Лимиты", "show_limits", "usage"),
            ("🎁 Бонус", "check_bonus", "news_bonus"),
            ("💎 Подписка", "show_subscription", "subscribe"),
            ("❓ Помощь", "show_help", "help")
        ],
        "parent": None
    },
    "ai_modes_submenu": {
        "title": "Выберите агент ИИ",
        "items": [(mode["name"], "set_agent", key) for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode"],
        "parent": "main_menu"
    },
    "models_submenu": {
        "title": "Выберите модель ИИ",
        "items": [(model["name"], "set_model", key) for key, model in AVAILABLE_TEXT_MODELS.items()],
        "parent": "main_menu"
    },
    "limits_submenu": {
        "title": "Ваши лимиты",
        "items": [("📊 Показать", "show_limits", "usage")],
        "parent": "main_menu"
    },
    "bonus_submenu": {
        "title": "Бонус за подписку",
        "items": [("🎁 Получить", "check_bonus", "news_bonus")],
        "parent": "main_menu"
    },
    "subscription_submenu": {
        "title": "Подписка Профи",
        "items": [("💎 Купить", "show_subscription", "subscribe")],
        "parent": "main_menu"
    },
    "help_submenu": {
        "title": "Помощь",
        "items": [("❓ Справка", "show_help", "help")],
        "parent": "main_menu"
    }
}

# --- FIREBASE INITIALIZATION ---
try:
    firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_credentials:
        cred_dict = json.loads(firebase_credentials)
        cred = credentials.Certificate(cred_dict)
    else:
        if os.path.exists("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"):
            cred = credentials.Certificate("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json")
        else:
            raise FileNotFoundError("Firebase credentials missing.")
    initialize_app(cred)
    db = firestore.client()
    logger.info("Firestore initialized.")
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {e}")
    db = None

# --- IN-MEMORY CACHE ---
USER_DATA_CACHE = defaultdict(dict)
BOT_DATA_CACHE = {}
CACHE_TTL = 60  # Cache TTL in seconds

async def get_user_data(user_id: int) -> dict:
    cache_key = str(user_id)
    cached = USER_DATA_CACHE.get(cache_key)
    if cached and (time() - cached['timestamp']) < CACHE_TTL:
        return cached['data']

    if not db:
        return {}
    doc_ref = db.collection("users").document(str(user_id))
    doc = await asyncio.to_thread(doc_ref.get)
    data = doc.to_dict() or {}
    USER_DATA_CACHE[cache_key] = {'data': data, 'timestamp': time()}
    return data

async def set_user_data(user_id: int, data: dict):
    if not db:
        logger.warning(f"Firestore not initialized, cannot set user data for {user_id}")
        return
    doc_ref = db.collection("users").document(str(user_id))
    await asyncio.to_thread(doc_ref.set, data, merge=True)
    cache_key = str(user_id)
    USER_DATA_CACHE[cache_key] = {'data': data, 'timestamp': time()}
    logger.debug(f"Updated user data for {user_id}")

async def get_bot_data() -> dict:
    global BOT_DATA_CACHE
    if BOT_DATA_CACHE and (time() - BOT_DATA_CACHE.get('timestamp', 0)) < CACHE_TTL:
        return BOT_DATA_CACHE['data']

    if not db:
        return {}
    doc_ref = db.collection("bot_data").document("data")
    doc = await asyncio.to_thread(doc_ref.get)
    data = doc.to_dict() or {}
    BOT_DATA_CACHE = {'data': data, 'timestamp': time()}
    return data

async def set_bot_data(data: dict):
    if not db:
        logger.warning("Firestore not initialized, cannot set bot data")
        return
    doc_ref = db.collection("bot_data").document("data")
    await asyncio.to_thread(doc_ref.set, data, merge=True)
    global BOT_DATA_CACHE
    BOT_DATA_CACHE = {'data': data, 'timestamp': time()}
    logger.debug(f"Updated bot data")

async def get_current_mode_details(user_id: int) -> dict:
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id)
    mode_key = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)

    if mode_key not in AI_MODES or mode_key == "grok_3_custom_mode":
        mode_key = DEFAULT_AI_MODE_KEY
        user_data['current_ai_mode'] = mode_key
        await set_user_data(user_id, user_data)
        logger.info(f"Reset invalid mode to default for user {user_id}")

    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])

    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

async def get_current_model_key(user_id: int) -> str:
    user_data = await get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id and (not selected_api_type or info.get("api_type") == selected_api_type):
            return key

    logger.warning(f"Model ID '{selected_id}' or API type '{selected_api_type}' not found for user {user_id}. Setting default.")
    default_model = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    user_data.update({
        'selected_model_id': default_model["id"],
        'selected_api_type': default_model["api_type"]
    })
    await set_user_data(user_id, user_data)
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int) -> dict:
    model_key = await get_current_model_key(user_id)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str):
        return str(text), False
    if len(text) <= max_length:
        return text, False

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)
    if adjusted_max_length <= 0:
        return text[:max_length-3] + "...", True

    possible_cut_points = []
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']:
        pos = text.rfind(sep, 0, adjusted_max_length)
        if pos != -1:
            actual_pos = pos + len(sep) if sep != ' ' else pos
            if actual_pos > 0:
                possible_cut_points.append(actual_pos)

    if possible_cut_points:
        cut_at = max(possible_cut_points)
        return text[:cut_at].strip() + suffix, True

    return text[:adjusted_max_length].strip() + suffix, True

async def get_user_actual_limit_for_model(user_id: int, model_key: str) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key, {})
    if not model_config:
        return 0

    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription = user_subscriptions.get(str(user_id), {})
    is_profi = False

    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                is_profi = user_subscription.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY
        except Exception as e:
            logger.error(f"Error parsing valid_until for user {user_id}: {e}")

    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free":
        return model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        return model_config.get("subscription_daily_limit", 0) if is_profi else model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit", 0) if is_profi else model_config.get("limit_if_no_subscription", 0)
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi:
            user_data = await get_user_data(user_id)
            if user_data.get('claimed_news_bonus', False):
                return base_limit + user_data.get('news_bonus_uses_left', 0)
        return base_limit
    return float('inf') if not model_config.get("is_limited", False) else 0

async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key, {})
    if not model_config or not model_config.get("is_limited"):
        return True, "", 0

    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription = user_subscriptions.get(str(user_id), {})
    is_profi = False

    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                is_profi = user_subscription.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY
        except Exception:
            pass

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user_data.get('claimed_news_bonus', False):
        if user_data.get('news_bonus_uses_left', 0) > 0:
            return True, "bonus_available", 0

    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': '', 'count': 0})

    if model_daily_usage['date'] != today:
        model_daily_usage = {'date': today, 'count': 0}
        user_model_counts[model_key] = model_daily_usage
        all_daily_counts[str(user_id)] = user_model_counts
        bot_data['all_user_daily_counts'] = all_daily_counts
        await set_bot_data(bot_data)

    current_count = model_daily_usage['count']
    actual_limit = await get_user_actual_limit_for_model(user_id, model_key)

    if current_count >= actual_limit:
        message = [f"Вы достигли лимита ({current_count}/{actual_limit}) для модели {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi:
            if not user_data.get('claimed_news_bonus', False):
                message.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонуса ({NEWS_CHANNEL_BONUS_GENERATIONS} для {AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")})!')
            elif user_data.get('news_bonus_uses_left', 0) == 0:
                message.append(f"ℹ️ Бонус за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал</a> использован.")
        if not is_profi:
            message.append("Попробуйте завтра или оформите <a href='https://t.me/gemini_oracle_bot?start=subscribe'>подписку</a>.")
        return False, "\n".join(message), current_count

    return True, "", current_count

async def increment_request_count(user_id: int, model_key: str):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key, {})
    if not model_config or not model_config.get("is_limited"):
        return

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()
    is_profi = False
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})

    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                is_profi = user_subscription.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY
        except Exception:
            pass

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user_data.get('claimed_news_bonus', False):
        news_bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        if news_bonus_uses_left > 0:
            user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
            await set_user_data(user_id, user_data)
            logger.info(f"User {user_id} used bonus for {model_key}. Remaining: {user_data['news_bonus_uses_left']}")
            return

    today = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today, 'count': 0})

    if model_daily_usage['date'] != today:
        model_daily_usage = {'date': today, 'count': 0}

    model_daily_usage['count'] += 1
    user_model_counts[model_key] = model_daily_usage
    all_daily_counts[str(user_id)] = user_model_counts
    bot_data['all_user_daily_counts'] = all_daily_counts
    await set_bot_data(bot_data)
    logger.info(f"User {user_id} count for {model_key} incremented to {model_daily_usage['count']}")

def is_menu_button_text(text: str) -> bool:
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons:
        return True
    for menu in MENU_STRUCTURE.values():
        for item_text, _, _ in menu["items"]:
            if item_text == text:
                return True
    return False

async def try_delete_user_message(update: Update, user_id: int):
    if not update or not update.message:
        return

    chat_id = update.effective_chat.id
    user_data = await get_user_data(user_id)
    user_command_message = user_data.get('user_command_message', {})
    message_id = user_command_message.get('message_id')
    timestamp = user_command_message.get('timestamp')

    if not message_id or not timestamp:
        return

    try:
        msg_time = datetime.fromisoformat(timestamp)
        if (datetime.now(msg_time.tzinfo or None) - msg_time).total_seconds() > 48 * 3600:
            user_data.pop('user_command_message', None)
            await set_user_data(user_id, user_data)
            return
    except ValueError:
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)
        return

    try:
        await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted user message {message_id} in chat {chat_id}")
    except telegram.error.BadRequest as e:
        logger.warning(f"Failed to delete message {message_id}: {e}")
    finally:
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE["main_menu"])
    keyboard = [[KeyboardButton(text) for text, _, _ in menu["items"][i:i+2]] for i in range(0, len(menu["items"]), 2)]
    if menu.get("parent"):
        keyboard.append([KeyboardButton("⬅️ Назад"), KeyboardButton("🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str):
    menu = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE["main_menu"])
    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key
    await set_user_data(user_id, user_data)

    await update.message.reply_text(
        menu["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        parse_mode=None,
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} shown menu '{menu_key}'")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)

    user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    user_data.setdefault('current_menu', 'main_menu')
    default_model = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    user_data.setdefault('selected_model_id', default_model["id"])
    user_data.setdefault('selected_api_type', default_model["api_type"])

    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
    await set_user_data(user_id, user_data)

    current_model_key = await get_current_model_key(user_id)
    mode_details = await get_current_mode_details(user_id)
    current_mode_name = mode_details['name']
    current_model_name = AVAILABLE_TEXT_MODELS[current_model_key]['name']

    greeting = (
        f"👋 Привет, {update.effective_user.first_name}!\n"
        f"Я твой ИИ-бот на базе различных нейросетей.\n\n"
        f"🧠 Текущий агент: <b>{current_mode_name}</b>\n"
        f"⚙️ Текущая модель: <b>{current_model_name}</b>\n\n"
        "💬 Задавай вопросы или используй меню!"
    )
    await update.message.reply_text(
        greeting,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} started the bot")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)
    await show_menu(update, user_id, "main_menu")

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)
    await show_limits(update, user_id)

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)
    await show_subscription(update, user_id)

async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
    await claim_news_bonus_logic(update, user_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)
    await show_help(update, user_id)

async def show_limits(update: Update, user_id: int):
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    display_sub_level = "Бесплатный доступ"
    is_profi = False
    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                display_sub_level = f"Подписка Профи (до {valid_until.strftime('%Y-%m-%d')})"
                is_profi = True
            else:
                display_sub_level = f"Подписка Профи (истекла {valid_until.strftime('%Y-%m-%d')})"
        except Exception as e:
            logger.error(f"Error parsing subscription date for user {user_id}: {e}")
            display_sub_level = "Подписка Профи (ошибка даты)"

    usage_text = [
        "<b>📊 Ваши лимиты запросов</b>",
        f"Текущий статус: <b>{display_sub_level}</b>",
        ""
    ]

    today = datetime.now().strftime("%Y-%m-%d")
    user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            model_daily_usage = user_model_counts.get(model_key, {'date': '', 'count': 0})
            current_count = model_daily_usage['count'] if model_daily_usage['date'] == today else 0
            actual_limit = await get_user_actual_limit_for_model(user_id, model_key)
            bonus_note = ""
            if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user_data.get('claimed_news_bonus', False):
                bonus_note = f" (включая {user_data.get('news_bonus_uses_left', 0)} бонусных)"
            usage_text.append(f"▫️ {model_config['name']}: <b>{current_count}/{actual_limit if actual_limit != float('inf') else '∞'}</b>{bonus_note}")

    usage_text.append("")
    bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
    if not user_data.get('claimed_news_bonus', False):
        usage_text.append(f'🎁 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонуса ({NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name})!')
    elif user_data.get('news_bonus_uses_left', 0) > 0:
        usage_text.append(f"✅ У вас {user_data['news_bonus_uses_left']} бонусных генераций для {bonus_model_name}.")
    else:
        usage_text.append(f"ℹ️ Бонус для {bonus_model_name} использован.")
    usage_text.append("")

    if not is_profi:
        usage_text.append("Хотите больше лимитов? Оформите подписку через /subscribe.")

    current_menu = user_data.get('current_menu', 'limits_submenu')
    if current_menu not in MENU_STRUCTURE:
        current_menu = 'limits_submenu'

    await update.message.reply_text(
        "\n".join(usage_text),
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )
    logger.info(f"Sent usage info to user {user_id}")

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data = await get_user_data(user_id)
    parent_menu_key = user_data.get('current_menu', 'bonus_submenu')
    if parent_menu_key not in MENU_STRUCTURE:
        parent_menu_key = 'main_menu'

    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        await update.message.reply_text(
            "Функция бонуса не настроена.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )
        logger.info(f"Bonus not configured for user {user_id}")
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text(
            "Ошибка: Модель для бонуса не найдена.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )
        logger.error(f"Bonus model '{NEWS_CHANNEL_BONUS_MODEL_KEY}' not found")
        return

    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        bonus_model_name = bonus_model_config.get('name', 'бонусной модели')
        message = f"✅ У вас {uses_left} бонусных генераций для {bonus_model_name}." if uses_left > 0 else f"ℹ️ Бонус для {bonus_model_name} использован."
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )
        return

    try:
        channel_member = await update.get_bot().get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user_id)
        if channel_member.status in ['member', 'administrator', 'creator']:
            user_data.update({
                'claimed_news_bonus': True,
                'news_bonus_uses_left': NEWS_CHANNEL_BONUS_GENERATIONS
            })
            await set_user_data(user_id, user_data)
            bonus_model_name = bonus_model_config.get('name', 'бонусной модели')
            await update.message.reply_text(
                f"🎉 Бонус активирован! Вы получили {NEWS_CHANNEL_BONUS_GENERATIONS} генераций для {bonus_model_name}.",
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard(parent_menu_key),
                disable_web_page_preview=True
            )
            logger.info(f"User {user_id} claimed bonus for {NEWS_CHANNEL_BONUS_MODEL_KEY}")
        else:
            await update.message.reply_text(
                f'Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">{NEWS_CHANNEL_USERNAME}</a> для бонуса.',
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"📢 Перейти в {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
                ]]),
                disable_web_page_preview=True
            )
            logger.info(f"User {user_id} not subscribed to {NEWS_CHANNEL_USERNAME}")
    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest checking channel {NEWS_CHANNEL_USERNAME}: {e}")
        await update.message.reply_text(
            f'Не удалось проверить подписку на <a href="{NEWS_CHANNEL_LINK}">{NEWS_CHANNEL_USERNAME}</a>. Попробуйте позже.',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📢 Перейти в {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
            ]]),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error in claim_news_bonus_logic for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Ошибка при получении бонуса. Попробуйте позже.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )

async def show_subscription(update: Update, user_id: int):
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    sub_text = ["<b>💎 Информация о Подписке Профи</b>"]
    is_profi = False

    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            valid_until_str = valid_until.strftime('%d.%m.%Y')
            if datetime.now().date() <= valid_until.date():
                sub_text.append(f"\n✅ Подписка <b>Профи</b> активна до <b>{valid_until_str}</b>.")
                sub_text.append("   Вам доступны расширенные лимиты и все модели ИИ.")
                is_profi = True
            else:
                sub_text.append(f"\n⚠️ Подписка <b>Профи</b> истекла <b>{valid_until_str}</b>.")
        except Exception as e:
            logger.error(f"Error parsing subscription date for user {user_id}: {e}")
            sub_text.append("\n⚠️ Ошибка в дате подписки.")

    if not is_profi:
        sub_text.append("\nС подпиской <b>Профи</b> вы получаете:")
        sub_text.append("▫️ Увеличенные лимиты на все модели.")
        sub_text.append(f"▫️ Приоритетный доступ к {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}.")
        sub_text.append(f"▫️ Расширенный доступ к {AVAILABLE_TEXT_MODELS['custom_api_grok_3']['name']}.")
        sub_text.append(f"▫️ Расширенный доступ к {AVAILABLE_TEXT_MODELS['custom_api_gpt_4o_mini']['name']}.")
        sub_text.append("▫️ Поддержку развития бота.")
        sub_text.append("\nОформите подписку через /subscribe.")

    current_menu = user_data.get('current_menu', 'subscription_submenu')
    if current_menu not in MENU_STRUCTURE:
        current_menu = 'subscription_submenu'

    await update.message.reply_text(
        "\n".join(sub_text),
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )
    logger.info(f"Sent subscription info to user {user_id}")

async def show_help(update: Update, user_id: int):
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)

    help_text = (
        "<b>❓ Справочная информация</b>\n\n"
        "Я — ваш ИИ-ассистент! Основные возможности:\n"
        "▫️ <b>Взаимодействие с ИИ</b>: Задавайте вопросы, получайте ответы.\n"
        "▫️ <b>Агенты ИИ</b>: Выбирайте агентов (меню «🤖 Агенты ИИ»).\n"
        "▫️ <b>Модели ИИ</b>: Переключайтесь между моделями (меню «⚙️ Модели ИИ»).\n"
        "▫️ <b>Лимиты</b>: Проверяйте лимиты через /usage или меню «📊 Лимиты».\n"
        "▫️ <b>Бонус</b>: Получите бонус за подписку на канал (меню «🎁 Бонус»).\n"
        "▫️ <b>Подписка Профи</b>: Увеличьте лимиты через /subscribe.\n\n"
        "<b>Команды:</b>\n"
        "▫️ /start — Перезапустить бота.\n"
        "▫️ /menu — Открыть меню.\n"
        "▫️ /usage — Показать лимиты.\n"
        "▫️ /subscribe — Информация о подписке.\n"
        "▫️ /bonus — Получить бонус.\n"
        "▫️ /help — Справка."
    )

    current_menu = user_data.get('current_menu', 'help_submenu')
    if current_menu not in MENU_STRUCTURE:
        current_menu = 'help_submenu'

    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )
    logger.info(f"Sent help info to user {user_id}")

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    button_text = update.message.text.strip()

    if not is_menu_button_text(button_text):
        return

    user_data = await get_user_data(user_id)
    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data)
    await try_delete_user_message(update, user_id)

    current_menu_key = user_data.get('current_menu', 'main_menu')
    logger.info(f"User {user_id} pressed button '{button_text}' in menu '{current_menu_key}'")

    if button_text == "⬅️ Назад":
        parent_menu_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu")
        await show_menu(update, user_id, parent_menu_key)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu")
        return

    action_item = None
    current_menu = MENU_STRUCTURE.get(current_menu_key)
    if current_menu:
        for text, action, target in current_menu["items"]:
            if text == button_text:
                action_item = (action, target)
                break

    if not action_item:
        for menu in MENU_STRUCTURE.values():
            for text, action, target in menu["items"]:
                if text == button_text:
                    action_item = (action, target)
                    break
            if action_item:
                break

    if not action_item:
        await update.message.reply_text(
            "Неизвестная команда. Используйте /menu.",
            reply_markup=generate_menu_keyboard(current_menu_key),
            disable_web_page_preview=True
        )
        return

    action, target = action_item
    return_menu_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu")

    if action == "submenu":
        await show_menu(update, user_id, target)
    elif action == "set_agent":
        if target in AI_MODES and target != "gemini_pro_custom_mode":
            user_data['current_ai_mode'] = target
            await set_user_data(user_id, user_data)
            agent_details = AI_MODES[target]
            response_text = f"🤖 Агент изменен на: <b>{agent_details['name']}</b>.\n\n{agent_details.get('welcome', 'Готов к вашим запросам!')}"
        else:
            response_text = "⚠️ Ошибка: Агент не найден."
            logger.error(f"Invalid agent '{target}' for user {user_id}")
        await update.message.reply_text(
            response_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu_key),
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu_key
        await set_user_data(user_id, user_data)
    elif action == "set_model":
        if target in AVAILABLE_TEXT_MODELS:
            model_config = AVAILABLE_TEXT_MODELS[target]
            user_data.update({
                'selected_model_id': model_config["id"],
                'selected_api_type': model_config["api_type"]
            })
            if target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and user_data.get('current_ai_mode') == "gemini_pro_custom_mode":
                user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY
                logger.info(f"Reset AI mode to default for user {user_id} due to model {target}")
            await set_user_data(user_id, user_data)
            bot_data = await get_bot_data()
            today = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage = user_model_counts.get(target, {'date': '', 'count': 0})
            current_count = model_daily_usage['count'] if model_daily_usage['date'] == today else 0
            actual_limit = await get_user_actual_limit_for_model(user_id, target)
            response_text = f"⚙️ Модель изменена на: <b>{model_config['name']}</b>.\nЛимит: {current_count}/{actual_limit if actual_limit != float('inf') else '∞'}."
        else:
            response_text = "⚠️ Ошибка: Модель не найдена."
            logger.error(f"Invalid model '{target}' for user {user_id}")
        await update.message.reply_text(
            response_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu_key),
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu_key
        await set_user_data(user_id, user_data)
    elif action == "show_limits":
        await show_limits(update, user_id)
    elif action == "check_bonus":
        await claim_news_bonus_logic(update, user_id)
    elif action == "show_subscription":
        await show_subscription(update, user_id)
    elif action == "show_help":
        await show_help(update, user_id)
    else:
        await update.message.reply_text(
            "Действие не определено. Сообщите администратору.",
            reply_markup=generate_menu_keyboard(current_menu_key),
            disable_web_page_preview=True
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        return

    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    if is_menu_button_text(user_message):
        return

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            "Запрос слишком короткий. Сформулируйте подробнее.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS[current_model_key]
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key)

    if not can_proceed:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            limit_message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id)
    system_prompt = mode_details["prompt"]
    response_text = "Ошибка: не удалось получить ответ."

    if model_config["api_type"] == "google_genai":
        full_prompt = f"{system_prompt}\n\n**Пользовательский запрос:**\n{user_message}"
        try:
            genai_model = genai.GenerativeModel(
                model_name=model_config["id"],
                generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB}
            )
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: genai_model.generate_content(full_prompt)
            )
            response_text = response.text.strip() or "Ответ пуст."
        except google.api_core.exceptions.ResourceExhausted:
            response_text = "Лимит Google API исчерпан. Попробуйте позже."
        except Exception as e:
            response_text = f"Ошибка Google API: {type(e).__name__}."
            logger.error(f"Google API error for user {user_id}: {e}", exc_info=True)
    elif model_config["api_type"] == "custom_http_api":
        api_key = globals().get(model_config.get("api_key_var_name", ""))
        if not api_key or "YOUR_" in api_key:
            response_text = f"Ошибка: API-ключ для {model_config['name']} не настроен."
            logger.error(f"Invalid API key for {model_config['id']}.")
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            is_gpt_4o_mini = model_config["id"] == "gpt-4o-mini"
            messages = [
                {"role": "system", "content": [{"type": "text", "text": system_prompt}] if is_gpt_4o_mini else system_prompt},
                {"role": "user", "content": [{"type": "text", "text": user_message}] if is_gpt_4o_mini else user_message}
            ]
            payload = {
                "messages": messages,
                "model": model_config["id"],
                "is_sync": True,
                "max_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB,
                "temperature": 1.0,
                "top_p": 1.0,
                "n": 1,
                "stream": False
            }
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=45)
                )
                response.raise_for_status()
                data = response.json()
                logger.debug(f"Raw API response for {model_config['id']}: {json.dumps(data, indent=2, ensure_ascii=False)}")
                if model_config["id"] == "grok-3-beta" and data.get("response", [{}])[0].get("choices"):
                    response_text = data["response"][0]["choices"][0]["message"]["content"].strip()
                elif model_config["id"] == "gemini-2.5-pro-preview-03-25":
                    response_text = data.get("text", "").strip()
                elif model_config["id"] == "gpt-4o-mini":
                    status = data.get("status", "unknown")
                    if status == "success":
                        output = data.get("output", "")
                        if isinstance(output, str):
                            response_text = output.strip()
                        elif isinstance(output, dict):
                            response_text = output.get("text", output.get("content", output.get("message", ""))).strip()
                        elif isinstance(output, list) and output:
                            response_text = output[0].get("text", output[0].get("content", "")).strip()
                        else:
                            response_text = ""
                        if not response_text:
                            response_text = "Ответ пуст: API вернул пустой или некорректный результат."
                    else:
                        error_message = data.get("error", data.get("message", "Нет подробностей об ошибке"))
                        response_text = f"Ошибка API: Статус '{status}', подробности: {error_message}."
                else:
                    response_text = data.get("text", data.get("content", data.get("output", "Ответ пуст."))).strip()
            except requests.exceptions.HTTPError as e:
                response_text = f"Ошибка API: HTTP {e.response.status_code}."
                logger.error(f"HTTPError for {model_config['id']}: {e}", exc_info=True)
                if e.response.status_code == 401:
                    response_text += " Возможна проблема с API-ключом."
                elif e.response.status_code == 429:
                    response_text += " Превышен лимит запросов."
            except Exception as e:
                response_text = f"Ошибка API: {type(e).__name__}."
                logger.error(f"Error for {model_config['id']}: {e}", exc_info=True)

    response_text, truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    await increment_request_count(user_id, current_model_key)
    user_data = await get_user_data(user_id)
    await update.message.reply_text(
        response_text,
        parse_mode=None,
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Sent response (model: {current_model_key}) to user {user_id}")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    expected_prefix = f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_"
    if query.invoice_payload.startswith(expected_prefix):
        await query.answer(ok=True)
        logger.info(f"Pre-checkout OK for user {query.from_user.id}, payload: {query.invoice_payload}")
    else:
        await query.answer(ok=False, error_message="Неверный запрос на оплату. Попробуйте заново.")
        logger.warning(f"Pre-checkout rejected for user {query.from_user.id}, payload: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    expected_prefix = f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_"

    if not payment.invoice_payload.startswith(expected_prefix):
        logger.error(f"Payment payload mismatch for user {user_id}: got {payment.invoice_payload}")
        await update.message.reply_text(
            "Ошибка: платеж получен, но данные не соответствуют. Свяжитесь с администратором.",
            reply_markup=generate_menu_keyboard((await get_user_data(user_id)).get('current_menu', 'main_menu'))
        )
        if YOUR_ADMIN_ID:
            await context.bot.send_message(
                chat_id=YOUR_ADMIN_ID,
                text=f"⚠️ Ошибка платежа для user {user_id}: payload {payment.invoice_payload}",
                parse_mode=ParseMode.HTML
            )
        return

    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    current_sub = user_subscriptions.get(str(user_id), {})
    
    now = datetime.now().astimezone()
    start_date = max(now, datetime.fromisoformat(current_sub['valid_until']) if current_sub.get('valid_until') else now)
    new_valid_until = start_date + timedelta(days=30)
    
    user_subscriptions[str(user_id)] = {
        'level': PRO_SUBSCRIPTION_LEVEL_KEY,
        'valid_until': new_valid_until.isoformat(),
        'last_payment_amount': payment.total_amount,
        'last_payment_currency': payment.currency,
        'purchase_date': now.isoformat()
    }
    bot_data['user_subscriptions'] = user_subscriptions
    await set_bot_data(bot_data)
    
    user_data = await get_user_data(user_id)
    await update.message.reply_text(
        f"🎉 Подписка Профи активирована до {new_valid_until.strftime('%d.%m.%Y')}.",
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    if YOUR_ADMIN_ID:
        await context.bot.send_message(
            chat_id=YOUR_ADMIN_ID,
            text=f"🔔 Платеж от {update.effective_user.full_name} (ID: {user_id}): {payment.total_amount/100} {payment.currency}",
            parse_mode=ParseMode.HTML
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception in update: {context.error}", exc_info=True)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    if isinstance(update, Update) and update.effective_chat:
        user_data = await get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла ошибка. Попробуйте позже или используйте /start.",
                reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
                parse_mode=None
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")

        if YOUR_ADMIN_ID:
            try:
                message = (
                    f"🤖 Ошибка:\n"
                    f"Исключение: {context.error.__class__.__name__}: {context.error}\n"
                    f"Пользователь: {update.effective_user.full_name} (ID: {update.effective_user.id})\n"
                    f"Чат: {update.effective_chat.id}\n"
                    f"Запрос: {update.message.text if update.message else 'N/A'}\n\n"
                    f"```\n{tb_string[:3500]}\n```"
                )
                await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=message, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                logger.error(f"Failed to notify admin {YOUR_ADMIN_ID}: {e}")

# ... (all imports, configurations, and other functions remain unchanged) ...

async def main():
    app = Application.builder().token(TOKEN).read_timeout(30).connect_timeout(30).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", open_menu_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("subscribe", subscribe_info_command))
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_error_handler(error_handler)

    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Мои лимиты"),
        BotCommand("subscribe", "💎 Подписка Профи"),
        BotCommand("bonus", "🎁 Бонус за канал"),
        BotCommand("help", "❓ Справка")
    ]
    await app.bot.set_my_commands(bot_commands)
    logger.info("Bot commands set")
    
    # Initialize and run polling
    await app.initialize()
    await app.start()
    try:
        await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)
    finally:
        # Ensure proper shutdown without closing the loop
        await app.stop()
        await app.shutdown()
        logger.info("Application shutdown complete")

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.warning("Existing event loop is running, scheduling main task.")
            loop.create_task(main())
            # Keep the loop running indefinitely if it's already active
            loop.run_forever()
        else:
            loop.run_until_complete(main())
    except RuntimeError as e:
        logger.error(f"Event loop error: {e}")
        # Create a new loop if the existing one is unusable
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        # Avoid closing the loop to prevent RuntimeError
        logger.info("Bot execution completed")

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.warning("Existing event loop is running, using it.")
            loop.create_task(main())
        else:
            loop.run_until_complete(main())
    except RuntimeError as e:
        logger.error(f"Event loop error: {e}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
