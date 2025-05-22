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
import nest_asyncio
import json
from datetime import datetime, timedelta, timezone
from telegram import LabeledPrice
from typing import Optional, Dict, Any
import uuid # Был импортирован, но не использовался. Оставим на всякий случай.
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient # <--- ИЗМЕНЕНИЕ: Явный импорт для аннотации

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
CONFIG = {
    "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0"),
    "GOOGLE_GEMINI_API_KEY": os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI"),
    "CUSTOM_GEMINI_PRO_API_KEY": os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"),
    "CUSTOM_GEMINI_PRO_ENDPOINT": os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro"),
    "CUSTOM_GROK_3_API_KEY": os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"),
    "CUSTOM_GPT4O_MINI_API_KEY": os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P"),
    "PAYMENT_PROVIDER_TOKEN": os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602"),
    "ADMIN_ID": int(os.getenv("ADMIN_ID", "489230152")),
    "FIREBASE_CREDENTIALS_JSON_STR": os.getenv("FIREBASE_CREDENTIALS"),
    "FIREBASE_CERT_PATH": "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json",

    "MAX_OUTPUT_TOKENS_GEMINI_LIB": 2048,
    "MAX_MESSAGE_LENGTH_TELEGRAM": 4000,
    "MIN_AI_REQUEST_LENGTH": 4,

    "DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY": 72,
    "DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY": 48,
    "DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY": 75,
    "DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY": 0,
    "DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY": 25,
    "PRO_SUBSCRIPTION_LEVEL_KEY": "profi_access_v1",
    "DEFAULT_FREE_REQUESTS_GROK_DAILY": 3,
    "DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY": 25,
    "DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY": 3,
    "DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY": 25,

    "NEWS_CHANNEL_USERNAME": "@timextech",
    "NEWS_CHANNEL_LINK": "https://t.me/timextech",
    "NEWS_CHANNEL_BONUS_MODEL_KEY": "custom_api_gemini_2_5_pro",
    "NEWS_CHANNEL_BONUS_GENERATIONS": 1,

    "DEFAULT_AI_MODE_KEY": "universal_ai_basic",
    "DEFAULT_MODEL_KEY": "google_gemini_2_0_flash",
}

TOKEN = CONFIG["TELEGRAM_TOKEN"]
GOOGLE_GEMINI_API_KEY = CONFIG["GOOGLE_GEMINI_API_KEY"]
CUSTOM_GEMINI_PRO_API_KEY = CONFIG["CUSTOM_GEMINI_PRO_API_KEY"]
CUSTOM_GEMINI_PRO_ENDPOINT = CONFIG["CUSTOM_GEMINI_PRO_ENDPOINT"]
CUSTOM_GROK_3_API_KEY = CONFIG["CUSTOM_GROK_3_API_KEY"]
CUSTOM_GPT4O_MINI_API_KEY = CONFIG["CUSTOM_GPT4O_MINI_API_KEY"]
PAYMENT_PROVIDER_TOKEN = CONFIG["PAYMENT_PROVIDER_TOKEN"]
YOUR_ADMIN_ID = CONFIG["ADMIN_ID"]

AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент от Google."
            "Твоя цель — эффективно помогать пользователю с широким спектром задач:"
            "отвечать на вопросы, генерировать текст, объяснять,"
            "анализировать и предоставлять информацию."
            "Всегда будь вежлив, объективен, точен и полезен."
            "Предупреждай, если твои знания ограничены по времени."
            "ОФОРМЛЕНИЕ ОТВЕТА:"
            "1. Структура и ясность: Ответ должен быть понятным, хорошо структурированным и легким для восприятия. Четко разделяй смысловые блоки абзацами, используя одну или две пустые строки между ними."
            "2. Списки: Для перечислений используй нумерованные списки, например 1., 2., или маркированные списки, например -, *, со стандартными символами."
            "3. Заголовки: Для крупных смысловых блоков можешь использовать краткие поясняющие заголовки на отдельной строке, можно ЗАГЛАВНЫМИ БУКВАМИ."
            "4. Чистота текста: Генерируй только ясный, чистый текст без избыточных символов или пунктуации, не несущей смысловой нагрузки или не требуемой грамматикой."
            "5. Полнота: Старайся давать полные ответы. Убедись, что пункты списков завершены, и не начинай новый, если не уверен, что сможешь его закончить."
        ),
        "welcome": "Активирован агент 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент."
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя."
            "Соблюдай вежливость и объективность."
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости."
            "Если твои знания ограничены по времени, укажи это."
        ),
        "welcome": "Активирован агент 'Продвинутый'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "Творческий",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Твоя миссия — вдохновлять, помогать в создании оригинального контента (тексты, идеи, сценарии, стихи и т.д.) и развивать творческие замыслы пользователя."
            "Будь смелым в идеях, предлагай неожиданные решения, но всегда оставайся в рамках этики и здравого смысла."
            "Форматирование: 1. Абзацы: Для прозы и описаний — четкое разделение на абзацы."
            "2. Стихи: Соблюдай строфы и строки, если это подразумевается заданием."
            "3. Диалоги: Оформляй диалоги стандартным образом, например: - Привет! - сказал он. или с новой строки для каждого персонажа."
            "4. Язык: Используй богатый и выразительный язык, соответствующий творческой задаче."
            "6. Завершённость: Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Агент 'Творческий' к вашим услугам! Над какой задачей поработаем?"
    },
    "analyst": {
        "name": "Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик на базе Gemini, специализирующийся на анализе данных, фактов и трендов."
            "Твоя задача — предоставлять точные, логически обоснованные и структурированные ответы на запросы, связанные с анализом информации, статистики или бизнес-вопросов."
            "Используй структурированный подход:"
            "1. Анализ: Разбери запрос на ключевые аспекты."
            "2. Выводы: Предоставь четкие выводы или рекомендации."
            "3. Обоснование: Объясни свои рассуждения, если требуется."
            "Если данных недостаточно, укажи, что нужно для более точного анализа."
        ),
        "welcome": "Агент 'Аналитик' активирован. Какую задачу проанализировать?"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini."
            "Твоя задача — отвечать на запросы с легкостью, остроумием и юмором, сохраняя при этом полезность."
            "Добавляй шутки, анекдоты или забавные комментарии, но оставайся в рамках приличия."
            "Форматируй ответы так, чтобы они были веселыми и читабельными."
        ),
        "welcome": "Агент 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}
DEFAULT_AI_MODE_KEY = CONFIG["DEFAULT_AI_MODE_KEY"]

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": "google_genai",
        "is_limited": True, "limit_type": "daily_free", "limit": CONFIG["DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY"],
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": "google_genai",
        "is_limited": True, "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY"],
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": "custom_http_api",
        "endpoint": CONFIG["CUSTOM_GEMINI_PRO_ENDPOINT"], "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY"],
        "cost_category": "custom_api_pro_paid", "pricing_info": {}
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GROK_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY"],
        "cost_category": "custom_api_grok_3_paid", "pricing_info": {}
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY"],
        "cost_category": "custom_api_gpt4o_mini_paid", "pricing_info": {}
    }
}
DEFAULT_MODEL_KEY = CONFIG["DEFAULT_MODEL_KEY"]
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

MENU_STRUCTURE = {
    "main_menu": {
        "title": "📋 Главное меню", "items": [
            {"text": "🤖 Агенты ИИ", "action": "submenu", "target": "ai_modes_submenu"},
            {"text": "⚙️ Модели ИИ", "action": "submenu", "target": "models_submenu"},
            {"text": "📊 Лимиты", "action": "submenu", "target": "limits_submenu"},
            {"text": "🎁 Бонус", "action": "submenu", "target": "bonus_submenu"},
            {"text": "💎 Подписка", "action": "submenu", "target": "subscription_submenu"},
            {"text": "❓ Помощь", "action": "submenu", "target": "help_submenu"}
        ], "parent": None, "is_submenu": False
    },
    "ai_modes_submenu": {
        "title": "Выберите агент ИИ", "items": [
            {"text": mode["name"], "action": "set_agent", "target": key}
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode"
        ], "parent": "main_menu", "is_submenu": True
    },
    "models_submenu": {
        "title": "Выберите модель ИИ", "items": [
            {"text": model["name"], "action": "set_model", "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ], "parent": "main_menu", "is_submenu": True
    },
    "limits_submenu": {"title": "Ваши лимиты", "items": [{"text": "📊 Показать", "action": "show_limits", "target": "usage"}], "parent": "main_menu", "is_submenu": True},
    "bonus_submenu": {"title": "Бонус за подписку", "items": [{"text": "🎁 Получить", "action": "check_bonus", "target": "news_bonus"}], "parent": "main_menu", "is_submenu": True},
    "subscription_submenu": {"title": "Подписка Профи", "items": [{"text": "💎 Купить", "action": "show_subscription", "target": "subscribe"}], "parent": "main_menu", "is_submenu": True},
    "help_submenu": {"title": "Помощь", "items": [{"text": "❓ Справка", "action": "show_help", "target": "help"}], "parent": "main_menu", "is_submenu": True}
}

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE ---
db: Optional[FirestoreClient] = None # <--- ИЗМЕНЕНИЕ: Используем импортированный FirestoreClient для аннотации
try:
    firebase_creds_json = CONFIG["FIREBASE_CREDENTIALS_JSON_STR"]
    cred_obj = None
    if firebase_creds_json:
        try:
            cred_obj = credentials.Certificate(json.loads(firebase_creds_json))
            logger.info("Firebase credentials loaded from JSON string.")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing FIREBASE_CREDENTIALS_JSON_STR: {e}. Check JSON env var.")
            raise
    elif os.path.exists(CONFIG["FIREBASE_CERT_PATH"]):
        cred_obj = credentials.Certificate(CONFIG["FIREBASE_CERT_PATH"])
        logger.info(f"Firebase credentials loaded from file: {CONFIG['FIREBASE_CERT_PATH']}.")
    else:
        raise FileNotFoundError("Firebase credentials not configured (JSON string or cert file).")

    if not firebase_admin._apps:
        initialize_app(cred_obj)
        logger.info("Firebase app successfully initialized.")
    else:
        logger.info("Firebase app already initialized.")
    db = firestore.client() # Это возвращает экземпляр FirestoreClient
    logger.info("Firestore client successfully initialized.")
except Exception as e:
    logger.error(f"Critical error during Firebase/Firestore initialization: {e}", exc_info=True)
    db = None

async def _firestore_op(func, *args, **kwargs):
    if not db:
        logger.warning(f"Firestore (db) is not initialized. Operation '{func.__name__}' skipped.")
        return None
    return await asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs))

async def get_user_data(user_id: int, user_data_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if user_data_cache is not None: return user_data_cache
    if not db: return {}
    doc_ref = db.collection("users").document(str(user_id))
    doc = await _firestore_op(doc_ref.get)
    return doc.to_dict() if doc and doc.exists else {}

async def set_user_data(user_id: int, data: Dict[str, Any]):
    if not db: return
    doc_ref = db.collection("users").document(str(user_id))
    await _firestore_op(doc_ref.set, data, merge=True)
    logger.debug(f"User data for {user_id} updated with keys: {list(data.keys())}")

async def get_bot_data() -> Dict[str, Any]:
    if not db: return {}
    doc_ref = db.collection("bot_data").document("data")
    doc = await _firestore_op(doc_ref.get)
    return doc.to_dict() if doc and doc.exists else {}

async def set_bot_data(data: Dict[str, Any]):
    if not db: return
    doc_ref = db.collection("bot_data").document("data")
    await _firestore_op(doc_ref.set, data, merge=True)
    logger.debug(f"Bot data updated with keys: {list(data.keys())}")

async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    if not update.message: return

    message_id_to_process = update.message.message_id
    timestamp_now_iso = datetime.now(timezone.utc).isoformat()
    chat_id = update.effective_chat.id
    
    user_data_for_msg_handling = await get_user_data(user_id)

    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)
    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48):
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e:
            logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    if not is_command_to_keep:
        user_data_for_msg_handling['user_command_to_delete'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
        try:
            await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_process)
            logger.info(f"Successfully deleted current user message {message_id_to_process}")
            user_data_for_msg_handling.pop('user_command_to_delete', None)
        except telegram.error.BadRequest as e:
            logger.warning(f"Failed to delete current user message {message_id_to_process}: {e}. Will try next time.")
    else:
         user_data_for_msg_handling['user_command_message_to_keep'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
    await set_user_data(user_id, user_data_for_msg_handling)

async def auto_delete_message_decorator(is_command_to_keep: bool = False):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user:
                 await _store_and_try_delete_message(update, update.effective_user.id, is_command_to_keep)
            return await func(update, context)
        return wrapper
    return decorator

async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    user_data_loc = user_data or await get_user_data(user_id)
    selected_id = user_data_loc.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data_loc.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type: return key
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data_loc.get('selected_api_type') != info.get("api_type"):
                await set_user_data(user_id, {'selected_api_type': info.get("api_type")})
            return key
    default_cfg = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    await set_user_data(user_id, {'selected_model_id': default_cfg["id"], 'selected_api_type': default_cfg["api_type"]})
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    model_key = await get_current_model_key(user_id, user_data)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_data_loc = user_data or await get_user_data(user_id)
    current_model_k_loc = await get_current_model_key(user_id, user_data_loc)
    mode_k_loc = user_data_loc.get('current_ai_mode', DEFAULT_AI_MODE_KEY)

    if mode_k_loc not in AI_MODES:
        mode_k_loc = DEFAULT_AI_MODE_KEY
        await set_user_data(user_id, {'current_ai_mode': mode_k_loc})
    if current_model_k_loc == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    return AI_MODES.get(mode_k_loc, AI_MODES[DEFAULT_AI_MODE_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str) or len(text) <= max_length: return str(text), False
    suffix = "\n\n(...ответ был сокращен)"
    adj_max_len = max_length - len(suffix)
    if adj_max_len <= 0: return text[:max_length-len("...")] + "...", True
    trunc_text = text[:adj_max_len]
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']:
        pos = trunc_text.rfind(sep)
        if pos != -1:
            actual_pos = pos + (len(sep) if sep != ' ' else 0)
            if actual_pos > 0 and actual_pos > adj_max_len * 0.3:
                 return text[:actual_pos].strip() + suffix, True
    return text[:adj_max_len].strip() + suffix, True

def is_user_profi_subscriber(sub_details: Dict[str, Any]) -> bool:
    if sub_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"] and sub_details.get('valid_until'):
        try:
            valid_dt = datetime.fromisoformat(sub_details['valid_until'])
            if valid_dt.tzinfo is None: valid_dt = valid_dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc).date() <= valid_dt.date()
        except ValueError: return False
    return False

async def get_user_actual_limit_for_model(user_id: int, model_key: str, user_data: Optional[Dict[str, Any]] = None, bot_data_c: Optional[Dict[str, Any]] = None) -> int:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: return 0
    bot_data_loc = bot_data_c or await get_bot_data()
    user_subs = bot_data_loc.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subs)
    limit_type = model_cfg.get("limit_type")
    base_lmt = 0
    if limit_type == "daily_free": base_lmt = model_cfg.get("limit", 0)
    elif limit_type == "subscription_or_daily_free": base_lmt = model_cfg.get("subscription_daily_limit", 0) if is_profi_user else model_cfg.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro": base_lmt = model_cfg.get("subscription_daily_limit", 0) if is_profi_user else model_cfg.get("limit_if_no_subscription", 0)
    elif not model_cfg.get("is_limited", False): return float('inf')
    else: return 0
    user_data_loc = user_data or await get_user_data(user_id)
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi_user and user_data_loc.get('claimed_news_bonus', False):
        base_lmt += user_data_loc.get('news_bonus_uses_left', 0)
    return base_lmt

async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"): return True, "", 0

    user_data_loc = await get_user_data(user_id)
    bot_data_loc = await get_bot_data()
    user_subs = bot_data_loc.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subs)

    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False) and user_data_loc.get('news_bonus_uses_left', 0) > 0:
        return True, "bonus_available", 0

    all_counts = bot_data_loc.get('all_user_daily_counts', {})
    user_counts = all_counts.get(str(user_id), {})
    model_usage = user_counts.get(model_key, {'date': '', 'count': 0})
    if model_usage['date'] != today: model_usage = {'date': today, 'count': 0}
    
    current_cnt = model_usage['count']
    limit_comp = 0 
    if model_cfg.get("limit_type") == "daily_free": limit_comp = model_cfg.get("limit",0)
    elif model_cfg.get("limit_type") == "subscription_or_daily_free": limit_comp = model_cfg.get("subscription_daily_limit",0) if is_profi_user else model_cfg.get("limit_if_no_subscription",0)
    elif model_cfg.get("limit_type") == "subscription_custom_pro": limit_comp = model_cfg.get("subscription_daily_limit",0) if is_profi_user else model_cfg.get("limit_if_no_subscription",0)

    if current_cnt >= limit_comp:
        display_lmt = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
        msg_parts = [f"Достигнут дневной лимит ({current_cnt}/{display_lmt}) для {model_cfg['name']}."]
        if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi_user:
            bonus_name = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"],{}).get("name","бонусной модели")
            if not user_data_loc.get('claimed_news_bonus', False): msg_parts.append(f'💡 Подписка на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">канал</a> даст бонус ({CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]} для {bonus_name})!')
            elif user_data_loc.get('news_bonus_uses_left', 0) == 0: msg_parts.append(f"ℹ️ Бонус с <a href='{CONFIG['NEWS_CHANNEL_LINK']}'>канала</a> использован.")
        if not is_profi_user: msg_parts.append("Попробуйте завтра или оформите <a href='https://t.me/gemini_oracle_bot?start=subscribe'>подписку</a>.")
        if model_usage['date'] == today and user_counts.get(model_key) != model_usage:
            user_counts[model_key] = model_usage
            all_counts[str(user_id)] = user_counts
            await set_bot_data({'all_user_daily_counts': all_counts})
        return False, "\n".join(msg_parts), current_cnt
    
    if model_usage['date'] == today and user_counts.get(model_key) != model_usage:
        user_counts[model_key] = model_usage
        all_counts[str(user_id)] = user_counts
        await set_bot_data({'all_user_daily_counts': all_counts})
    return True, "", current_cnt

async def increment_request_count(user_id: int, model_key: str):
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"): return

    user_data_loc = await get_user_data(user_id)
    bot_data_loc = await get_bot_data()
    user_subs = bot_data_loc.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subs)

    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False) and (bonus_left := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        await set_user_data(user_id, {'news_bonus_uses_left': bonus_left - 1})
        logger.info(f"User {user_id} consumed bonus for {model_key}. Left: {bonus_left - 1}")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_counts = bot_data_loc.get('all_user_daily_counts', {})
    user_counts = all_counts.get(str(user_id), {})
    model_usage = user_counts.get(model_key, {'date': today, 'count': 0})
    if model_usage['date'] != today: model_usage = {'date': today, 'count': 0}
    model_usage['count'] += 1
    user_counts[model_key] = model_usage
    all_counts[str(user_id)] = user_counts
    await set_bot_data({'all_user_daily_counts': all_counts})
    logger.info(f"User {user_id} daily count for {model_key} to {model_usage['count']}")

def is_menu_button_text(text: str) -> bool:
    if text in ["⬅️ Назад", "🏠 Главное меню"]: return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data["items"]:
            if item["text"] == text: return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu_cfg = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE["main_menu"])
    kbd_rows = []
    items = menu_cfg["items"]
    if menu_key in ["main_menu", "models_submenu"]:
        for i in range(0, len(items), 2): kbd_rows.append([KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))])
    else:
        for item in items: kbd_rows.append([KeyboardButton(item["text"])])
    if menu_cfg.get("is_submenu", False):
        nav_row = [KeyboardButton("🏠 Главное меню")]
        if menu_cfg.get("parent"): nav_row.insert(0, KeyboardButton("⬅️ Назад"))
        kbd_rows.append(nav_row)
    return ReplyKeyboardMarkup(kbd_rows, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting for user {user_id}.")
        await update.message.reply_text("Ошибка: Меню не найдено.", reply_markup=generate_menu_keyboard("main_menu"))
        await set_user_data(user_id, {'current_menu': 'main_menu'})
        return
    await set_user_data(user_id, {'current_menu': menu_key})
    await update.message.reply_text(menu_cfg["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)
    logger.info(f"User {user_id} shown menu '{menu_key}'.")

@auto_delete_message_decorator(is_command_to_keep=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_loc = await get_user_data(user_id)
    updates_to_user_data = {}
    if 'current_ai_mode' not in user_data_loc: updates_to_user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc: updates_to_user_data['current_menu'] = 'main_menu'
    default_model_cfg = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc: updates_to_user_data['selected_model_id'] = default_model_cfg["id"]
    if 'selected_api_type' not in user_data_loc: updates_to_user_data['selected_api_type'] = default_model_cfg["api_type"]
    if updates_to_user_data: await set_user_data(user_id, updates_to_user_data)
    if updates_to_user_data: user_data_loc.update(updates_to_user_data) # Обновляем локальную копию user_data_loc

    current_model_k = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)
    model_details_res = AVAILABLE_TEXT_MODELS.get(current_model_k)
    mode_name = mode_details_res['name'] if mode_details_res else "N/A"
    model_name = model_details_res['name'] if model_details_res else "N/A"
    greeting = (f"👋 Привет, {update.effective_user.first_name}!\n"
                f"🤖 Агент: <b>{mode_name}</b> | ⚙️ Модель: <b>{model_name}</b>\n"
                "💬 Задавай вопросы или используй меню!")
    await update.message.reply_text(greeting, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard("main_menu"), disable_web_page_preview=True)
    logger.info(f"User {user_id} started bot.")

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data_loc = await get_user_data(update.effective_user.id)
    await show_menu(update, update.effective_user.id, "main_menu", user_data_loc)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

@auto_delete_message_decorator()
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription(update, update.effective_user.id)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

async def show_limits(update: Update, user_id: int):
    user_data_loc = await get_user_data(user_id)
    bot_data_loc = await get_bot_data()
    user_subs = bot_data_loc.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subs)
    sub_level_disp = "Бесплатный"
    if is_profi:
        valid_dt = datetime.fromisoformat(user_subs['valid_until'])
        if valid_dt.tzinfo is None: valid_dt = valid_dt.replace(tzinfo=timezone.utc)
        sub_level_disp = f"Профи (до {valid_dt.strftime('%d.%m.%Y')})"
    elif user_subs.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"]:
        valid_dt = datetime.fromisoformat(user_subs['valid_until'])
        if valid_dt.tzinfo is None: valid_dt = valid_dt.replace(tzinfo=timezone.utc)
        sub_level_disp = f"Профи (истекла {valid_dt.strftime('%d.%m.%Y')})"
    parts = [f"<b>📊 Ваши лимиты</b> (Статус: <b>{sub_level_disp}</b>)\n"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_counts = bot_data_loc.get('all_user_daily_counts', {})
    user_counts = all_counts.get(str(user_id), {})
    for mk, mc in AVAILABLE_TEXT_MODELS.items():
        if mc.get("is_limited"):
            usage = user_counts.get(mk, {'date': '', 'count': 0})
            count_disp = usage['count'] if usage['date'] == today else 0
            actual_lmt = await get_user_actual_limit_for_model(user_id, mk, user_data_loc, bot_data_loc)
            bonus_n = ""
            if mk == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi and \
               user_data_loc.get('claimed_news_bonus', False) and (b_left := user_data_loc.get('news_bonus_uses_left',0)) > 0:
                bonus_n = f" (+{b_left} бонус)"
            parts.append(f"▫️ {mc['name']}: <b>{count_disp}/{actual_lmt if actual_lmt != float('inf') else '∞'}</b>{bonus_n}")
    parts.append("")
    bonus_model_n = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"],{}).get('name',"бонусной модели")
    if not user_data_loc.get('claimed_news_bonus', False): parts.append(f'🎁 <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">Канал новостей</a>: бонус ({CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]} для {bonus_model_n})!')
    elif (b_left := user_data_loc.get('news_bonus_uses_left',0)) > 0: parts.append(f"✅ Бонус с канала: <b>{b_left}</b> для {bonus_model_n}.")
    else: parts.append(f"ℹ️ Бонус с канала для {bonus_model_n} использован.")
    if not is_profi: parts.append("\n💎 Больше лимитов? /subscribe")
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu','limits_submenu')), disable_web_page_preview=True)

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data_loc = await get_user_data(user_id)
    parent_menu_k = user_data_loc.get('current_menu', 'bonus_submenu')
    current_menu_details = MENU_STRUCTURE.get(parent_menu_k, MENU_STRUCTURE["main_menu"])
    if not current_menu_details.get("is_submenu"): parent_menu_k = "main_menu"
    else: parent_menu_k = current_menu_details.get("parent", "main_menu")
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"])
    if not bonus_model_cfg:
        await update.message.reply_text("Ошибка: Бонусная модель не настроена.", reply_markup=generate_menu_keyboard(parent_menu_k))
        return
    bonus_model_n = bonus_model_cfg['name']
    if user_data_loc.get('claimed_news_bonus', False):
        uses_l = user_data_loc.get('news_bonus_uses_left',0)
        reply = f"Бонус уже активирован. Осталось: <b>{uses_l}</b> для {bonus_model_n}." if uses_l > 0 else f"Бонус для {bonus_model_n} использован."
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(parent_menu_k), disable_web_page_preview=True)
        return
    try:
        member = await update.get_bot().get_chat_member(chat_id=CONFIG["NEWS_CHANNEL_USERNAME"], user_id=user_id)
        if member.status in ['member','administrator','creator']:
            await set_user_data(user_id, {'claimed_news_bonus':True, 'news_bonus_uses_left':CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]})
            success_txt = f'🎉 Спасибо за подписку на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{CONFIG["NEWS_CHANNEL_USERNAME"]}</a>! Бонус: <b>{CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]}</b> для {bonus_model_n}.'
            await update.message.reply_text(success_txt, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard('main_menu'), disable_web_page_preview=True)
        else:
            fail_txt = f'Подпишитесь на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{CONFIG["NEWS_CHANNEL_USERNAME"]}</a>, затем «🎁 Получить».'
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 В канал {CONFIG['NEWS_CHANNEL_USERNAME']}", url=CONFIG["NEWS_CHANNEL_LINK"])]])
            await update.message.reply_text(fail_txt, parse_mode=ParseMode.HTML, reply_markup=kbd, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error claiming bonus for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(parent_menu_k))

async def show_subscription(update: Update, user_id: int):
    user_data_loc = await get_user_data(user_id)
    user_subs = (await get_bot_data()).get('user_subscriptions',{}).get(str(user_id),{})
    is_active = is_user_profi_subscriber(user_subs)
    parts = ["<b>💎 Подписка Профи</b>"]
    if is_active:
        valid_dt = datetime.fromisoformat(user_subs['valid_until'])
        if valid_dt.tzinfo is None: valid_dt = valid_dt.replace(tzinfo=timezone.utc)
        parts.append(f"\n✅ Активна до <b>{valid_dt.strftime('%d.%m.%Y')}</b>. Расширенные лимиты доступны.")
    else:
        if user_subs.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"]: parts.append(f"\n⚠️ Истекла <b>{datetime.fromisoformat(user_subs['valid_until']).strftime('%d.%m.%Y')}</b>.")
        parts.extend(["\nС подпиской <b>Профи</b>:", "▫️ Увеличенные лимиты.",
                      f"▫️ Доступ к {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}.",
                      f"▫️ Доступ к {AVAILABLE_TEXT_MODELS['custom_api_grok_3']['name']}."])
        if "custom_api_gpt_4o_mini" in AVAILABLE_TEXT_MODELS: parts.append(f"▫️ Доступ к {AVAILABLE_TEXT_MODELS['custom_api_gpt_4o_mini']['name']}.")
        parts.append("\nДля оформления: /subscribe или кнопка в меню.")
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu','subscription_submenu')), disable_web_page_preview=True)

async def show_help(update: Update, user_id: int):
    user_data_loc = await get_user_data(user_id)
    help_txt = ("<b>❓ Справка</b>\n\n"
                "▫️ <b>Запросы ИИ</b>: Пишите текст для ответа.\n"
                "▫️ <b>Агенты ИИ</b>: «🤖 Агенты ИИ» для выбора роли.\n"
                "▫️ <b>Модели ИИ</b>: «⚙️ Модели ИИ» для выбора модели.\n"
                "▫️ <b>Лимиты</b>: «📊 Лимиты» или /usage.\n"
                "▫️ <b>Бонус</b>: «🎁 Бонус» за подписку на канал.\n"
                "▫️ <b>Подписка</b>: «💎 Подписка» или /subscribe.\n\n"
                "<b>Команды:</b> /start, /menu, /usage, /subscribe, /bonus, /help")
    await update.message.reply_text(help_txt, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_loc.get('current_menu','help_submenu')), disable_web_page_preview=True)

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return 
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text):
        return # Не кнопка меню, передаем управление дальше (в handle_text)

    # Это кнопка меню, обрабатываем.
    await _store_and_try_delete_message(update, user_id) 
    user_data_loc = await get_user_data(user_id)
    current_menu_k = user_data_loc.get('current_menu', 'main_menu')
    logger.info(f"User {user_id} menu button '{button_text}' from '{current_menu_k}'.")

    if button_text == "⬅️ Назад":
        parent_k = MENU_STRUCTURE.get(current_menu_k, {}).get("parent", "main_menu")
        await show_menu(update, user_id, parent_k, user_data_loc)
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu", user_data_loc)
    else:
        action_item_found = None
        for item_list in [MENU_STRUCTURE.get(current_menu_k, {}).get("items", [])] + \
                         [m_cfg["items"] for m_cfg in MENU_STRUCTURE.values() if m_cfg.get("items")]:
            for item in item_list:
                if item["text"] == button_text: action_item_found = item; break
            if action_item_found: break
        if not action_item_found:
            logger.warning(f"Button '{button_text}' by user {user_id} not matched despite is_menu_button_text=True.")
            await update.message.reply_text("Неизвестная команда.", reply_markup=generate_menu_keyboard(current_menu_k))
        else:
            action, target = action_item_found["action"], action_item_found["target"]
            # Определяем меню для возврата
            action_origin_menu_key = current_menu_k # Предполагаем, что действие из текущего меню
            for menu_key_search, menu_config_search in MENU_STRUCTURE.items():
                for item_search in menu_config_search.get("items", []):
                    if item_search.get("text") == button_text and item_search.get("action") == action and item_search.get("target") == target:
                        action_origin_menu_key = menu_key_search
                        break
                if action_origin_menu_key == menu_key_search:
                    break
            
            return_menu_k = MENU_STRUCTURE.get(action_origin_menu_key, {}).get("parent", "main_menu")
            if action_origin_menu_key == "main_menu" : return_menu_k = "main_menu" # Если из главного, то и возвращаемся в главное


            if action == "submenu": await show_menu(update, user_id, target, user_data_loc)
            elif action == "set_agent":
                response_msg_txt = "⚠️ Ошибка: Агент не найден."
                if target in AI_MODES and target != "gemini_pro_custom_mode":
                    await set_user_data(user_id, {'current_ai_mode': target})
                    agent_details_loc = AI_MODES[target]
                    response_msg_txt = f"🤖 Агент: <b>{agent_details_loc['name']}</b>.\n{agent_details_loc.get('welcome', '')}"
                await update.message.reply_text(response_msg_txt, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_k), disable_web_page_preview=True)
                await set_user_data(user_id, {'current_menu': return_menu_k})
            elif action == "set_model":
                response_msg_txt = "⚠️ Ошибка: Модель не найдена."
                if target in AVAILABLE_TEXT_MODELS:
                    model_info = AVAILABLE_TEXT_MODELS[target]
                    update_p = {'selected_model_id': model_info["id"], 'selected_api_type': model_info["api_type"]}
                    if target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
                        update_p['current_ai_mode'] = DEFAULT_AI_MODE_KEY
                    await set_user_data(user_id, update_p)
                    user_data_loc.update(update_p)
                    bot_data_c = await get_bot_data()
                    today_s_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    user_model_c = bot_data_c.get('all_user_daily_counts', {}).get(str(user_id), {})
                    model_daily_u = user_model_c.get(target, {'date': '', 'count': 0})
                    current_u_s = model_daily_u['count'] if model_daily_u['date'] == today_s_val else 0
                    actual_l_s = await get_user_actual_limit_for_model(user_id, target, user_data_loc, bot_data_c)
                    limit_s_str = f"{current_u_s}/{actual_l_s if actual_l_s != float('inf') else '∞'}"
                    response_msg_txt = f"⚙️ Модель: <b>{model_info['name']}</b>.\nЛимит: {limit_s_str}."
                await update.message.reply_text(response_msg_txt, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_k), disable_web_page_preview=True)
                await set_user_data(user_id, {'current_menu': return_menu_k})
            elif action == "show_limits": await show_limits(update, user_id)
            elif action == "check_bonus": await claim_news_bonus_logic(update, user_id)
            elif action == "show_subscription": await show_subscription(update, user_id)
            elif action == "show_help": await show_help(update, user_id)
            else: logger.warning(f"Unknown action '{action}' for button '{button_text}' user {user_id}.")
    # После обработки кнопки, функция завершается. Неявный return None.
    # Это должно предотвратить переход к handle_text в группе 2.
    return

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text: return
    user_msg_txt = update.message.text.strip()

    if is_menu_button_text(user_msg_txt): 
        logger.debug(f"User {user_id} sent menu button text '{user_msg_txt}' that reached handle_text. Explicitly ignoring.")
        return

    if len(user_msg_txt) < CONFIG["MIN_AI_REQUEST_LENGTH"]:
        user_data_c = await get_user_data(user_id)
        await update.message.reply_text("Запрос слишком короткий.", reply_markup=generate_menu_keyboard(user_data_c.get('current_menu','main_menu')))
        return

    logger.info(f"User {user_id} AI request: '{user_msg_txt[:100]}...'")
    user_data_c = await get_user_data(user_id) 
    current_model_k_val = await get_current_model_key(user_id, user_data_c)
    model_cfg_val = AVAILABLE_TEXT_MODELS.get(current_model_k_val)
    if not model_cfg_val: 
        await update.message.reply_text("Критическая ошибка модели. Сообщите администратору.", reply_markup=generate_menu_keyboard(user_data_c.get('current_menu','main_menu')))
        return

    can_proceed, limit_msg_val, _ = await check_and_log_request_attempt(user_id, current_model_k_val)
    if not can_proceed:
        await update.message.reply_text(limit_msg_val, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_c.get('current_menu','main_menu')), disable_web_page_preview=True)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    mode_details_val = await get_current_mode_details(user_id, user_data_c)
    system_prompt_val = mode_details_val["prompt"]
    response_txt_val = "К сожалению, не удалось получить ответ от ИИ."

    api_type_val = model_cfg_val.get("api_type", "").strip()
    if api_type_val == "google_genai":
        prompt_full = f"{system_prompt_val}\n\n**Запрос:**\n{user_msg_txt}"
        try:
            model_genai = genai.GenerativeModel(model_cfg_val["id"], generation_config={"max_output_tokens": CONFIG["MAX_OUTPUT_TOKENS_GEMINI_LIB"]})
            resp_genai = await asyncio.get_event_loop().run_in_executor(None, lambda: model_genai.generate_content(prompt_full))
            response_txt_val = resp_genai.text.strip() if resp_genai.text else "Ответ Google GenAI пуст."
        except google.api_core.exceptions.ResourceExhausted as e: response_txt_val = f"Лимит Google API исчерпан: {e}"
        except Exception as e: response_txt_val = f"Ошибка Google API: {type(e).__name__}"; logger.error(f"Google GenAI API error: {e}", exc_info=True)
    elif api_type_val == "custom_http_api":
        api_key_name = model_cfg_val.get("api_key_var_name")
        key_actual = globals().get(api_key_name)
        if not key_actual or "YOUR_" in key_actual or not (key_actual.startswith("sk-") or key_actual.startswith("AIzaSy")):
            response_txt_val = f"Ошибка ключа API для «{model_cfg_val.get('name', current_model_k_val)}»."
        else:
            hdrs = {"Authorization": f"Bearer {key_actual}", "Content-Type": "application/json", "Accept": "application/json"}
            is_gpt4o = (model_cfg_val["id"] == "gpt-4o-mini")
            msgs_payload = []
            if system_prompt_val: msgs_payload.append({"role": "system", "content": [{"type": "text", "text": system_prompt_val}] if is_gpt4o else system_prompt_val})
            msgs_payload.append({"role": "user", "content": [{"type": "text", "text": user_msg_txt}] if is_gpt4o else user_msg_txt})
            payload_api = {"messages": msgs_payload, "model": model_cfg_val["id"], "is_sync": True, "max_tokens": model_cfg_val.get("max_tokens", CONFIG["MAX_OUTPUT_TOKENS_GEMINI_LIB"])}
            if model_cfg_val.get("parameters"): payload_api.update(model_cfg_val["parameters"])
            try:
                resp_custom = await asyncio.get_event_loop().run_in_executor(None, lambda: requests.post(model_cfg_val["endpoint"], headers=hdrs, json=payload_api, timeout=45))
                resp_custom.raise_for_status()
                json_resp = resp_custom.json()
                extracted_txt = None
                model_api_id_check = model_cfg_val["id"]
                if model_api_id_check == "grok-3-beta" and "response" in json_resp and isinstance(json_resp["response"], list) and json_resp["response"] and "choices" in json_resp["response"][0] and isinstance(json_resp["response"][0]["choices"], list) and json_resp["response"][0]["choices"]: extracted_txt = json_resp["response"][0]["choices"][0].get("message",{}).get("content","").strip()
                elif model_api_id_check == "gemini-2.5-pro-preview-03-25": extracted_txt = json_resp.get("text","").strip()
                elif model_api_id_check == "gpt-4o-mini":
                    if json_resp.get("status") == "success":
                        output_val = json_resp.get("output")
                        if isinstance(output_val, str): extracted_txt = output_val.strip()
                        elif isinstance(output_val, dict): extracted_txt = output_val.get("text", output_val.get("content", "")).strip()
                        elif output_val is not None: extracted_txt = str(output_val).strip()
                    else: extracted_txt = f"Ошибка API GPT-4o mini: {json_resp.get('status','N/A')}. {json_resp.get('error_message','')}"
                if extracted_txt is None: 
                    for k_check in ["text", "content", "message", "output", "response"]:
                        if isinstance(json_resp.get(k_check),str) and (extracted_txt := json_resp[k_check].strip()): break
                response_txt_val = extracted_txt if extracted_txt else "Ответ API не содержит текста."
            except requests.exceptions.HTTPError as e: response_txt_val = f"Ошибка сети Custom API ({e.response.status_code})."; logger.error(f"Custom API HTTPError: {e}", exc_info=True)
            except requests.exceptions.RequestException as e: response_txt_val = f"Сетевая ошибка Custom API: {type(e).__name__}."; logger.error(f"Custom API RequestException: {e}", exc_info=True)
            except Exception as e: response_txt_val = f"Неожиданная ошибка Custom API: {type(e).__name__}."; logger.error(f"Unexpected Custom API error: {e}", exc_info=True)
    else: response_txt_val = "Ошибка: Неизвестный тип API."

    final_txt_reply, _ = smart_truncate(response_txt_val, CONFIG["MAX_MESSAGE_LENGTH_TELEGRAM"])
    await increment_request_count(user_id, current_model_k_val)
    await update.message.reply_text(final_txt_reply, reply_markup=generate_menu_keyboard(user_data_c.get('current_menu','main_menu')), disable_web_page_preview=True)
    logger.info(f"Sent AI response (model: {current_model_k_val}) to user {user_id}.")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    expected_payload_part = f"subscription_{CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']}"
    if expected_payload_part in query.invoice_payload: await query.answer(ok=True)
    else: await query.answer(ok=False, error_message="Неверный запрос на оплату.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info_obj = update.message.successful_payment
    logger.info(f"Successful payment from {user_id}. Payload: {payment_info_obj.invoice_payload}")
    sub_days = 30 
    bot_data_upd = await get_bot_data()
    user_subs_upd = bot_data_upd.get('user_subscriptions',{})
    current_sub = user_subs_upd.get(str(user_id),{})
    now_utc_val = datetime.now(timezone.utc)
    start_ext_date = now_utc_val
    if is_user_profi_subscriber(current_sub):
        try:
            prev_valid = datetime.fromisoformat(current_sub['valid_until'])
            if prev_valid.tzinfo is None: prev_valid = prev_valid.replace(tzinfo=timezone.utc)
            if prev_valid > now_utc_val: start_ext_date = prev_valid
        except ValueError: pass 
    new_valid_date = start_ext_date + timedelta(days=sub_days)
    user_subs_upd[str(user_id)] = {'level': CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"], 'valid_until': new_valid_date.isoformat(), 'last_payment_amount': payment_info_obj.total_amount, 'currency': payment_info_obj.currency, 'purchase_date': now_utc_val.isoformat()}
    await set_bot_data({'user_subscriptions': user_subs_upd})
    confirm_msg = f"🎉 Оплата успешна! Подписка <b>Профи</b> активна до <b>{new_valid_date.strftime('%d.%m.%Y')}</b>."
    user_data_reply = await get_user_data(user_id)
    await update.message.reply_text(confirm_msg, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data_reply.get('current_menu','main_menu')))
    if CONFIG["ADMIN_ID"]:
        try: await context.bot.send_message(CONFIG["ADMIN_ID"], f"🔔 Новая оплата: User {user_id}, Sub до {new_valid_date.strftime('%d.%m.%Y')}")
        except Exception: pass

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_str = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    if isinstance(update, Update) and update.effective_chat:
        user_data_err = await get_user_data(update.effective_user.id) if update.effective_user else {}
        try: await context.bot.send_message(update.effective_chat.id, "Произошла ошибка. Попробуйте /start.", reply_markup=generate_menu_keyboard(user_data_err.get('current_menu','main_menu')))
        except Exception: pass
    if CONFIG["ADMIN_ID"] and isinstance(update, Update) and update.effective_user:
        try:
            admin_err_text = f"🤖 Ошибка бота:\n{context.error.__class__.__name__}: {context.error}\nUser: {update.effective_user.id}\n```\n{tb_str[:3500]}\n```"
            await context.bot.send_message(CONFIG["ADMIN_ID"], admin_err_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception: pass

async def main():
    app_build = Application.builder().token(CONFIG["TELEGRAM_TOKEN"])
    app_build.read_timeout(30).connect_timeout(30)
    app = app_build.build()

    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("subscribe", subscribe_info_command), group=0)
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_error_handler(error_handler)

    bot_cmds = [BotCommand(c,d) for c,d in [
        ("start","🚀 Перезапуск/Меню"), ("menu","📋 Открыть меню"), ("usage","📊 Мои лимиты"),
        ("subscribe","💎 О подписке"), ("bonus","🎁 Бонус канала"), ("help","❓ Справка")]]
    try: await app.bot.set_my_commands(bot_cmds); logger.info("Bot commands set.")
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

    logger.info("Bot polling started...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    if not CONFIG["GOOGLE_GEMINI_API_KEY"] or "YOUR_" in CONFIG["GOOGLE_GEMINI_API_KEY"] or not CONFIG["GOOGLE_GEMINI_API_KEY"].startswith("AIzaSy"): logger.warning("GOOGLE_GEMINI_API_KEY incorrect.")
    else:
        try: genai.configure(api_key=CONFIG["GOOGLE_GEMINI_API_KEY"]); logger.info("Google Gemini API configured.")
        except Exception as e: logger.error(f"Google Gemini API config error: {e}")
    for k_name in ["CUSTOM_GEMINI_PRO_API_KEY", "CUSTOM_GROK_3_API_KEY", "CUSTOM_GPT4O_MINI_API_KEY"]:
        if not (val := CONFIG.get(k_name,"")) or "YOUR_" in val or not (val.startswith("sk-") or val.startswith("AIzaSy")): logger.warning(f"{k_name} incorrect.")
    if not CONFIG["PAYMENT_PROVIDER_TOKEN"] or "YOUR_" in CONFIG["PAYMENT_PROVIDER_TOKEN"]: logger.warning("PAYMENT_PROVIDER_TOKEN incorrect.")
    if not db: logger.critical("Firestore (db) NOT initialized! Limited functionality.")
    asyncio.run(main())
