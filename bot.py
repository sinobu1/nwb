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
import uuid
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
# from google.cloud.firestore_v1 import AsyncClient # Не используется явно, firestore.client() достаточно

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
    "ADMIN_ID": int(os.getenv("ADMIN_ID", "489230152")), # Используем ADMIN_ID из CONFIG
    "FIREBASE_CREDENTIALS_JSON_STR": os.getenv("FIREBASE_CREDENTIALS"),
    "FIREBASE_CERT_PATH": "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json", # Убедитесь, что имя файла верное

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

# --- ИНИЦИАЛИЗАЦИЯ API КЛЮЧЕЙ ИЗ CONFIG ---
# Эти переменные используются напрямую в некоторых местах, поэтому оставим их для обратной совместимости,
# но их значения берутся из CONFIG.
TOKEN = CONFIG["TELEGRAM_TOKEN"]
GOOGLE_GEMINI_API_KEY = CONFIG["GOOGLE_GEMINI_API_KEY"]
CUSTOM_GEMINI_PRO_API_KEY = CONFIG["CUSTOM_GEMINI_PRO_API_KEY"]
CUSTOM_GEMINI_PRO_ENDPOINT = CONFIG["CUSTOM_GEMINI_PRO_ENDPOINT"]
CUSTOM_GROK_3_API_KEY = CONFIG["CUSTOM_GROK_3_API_KEY"]
CUSTOM_GPT4O_MINI_API_KEY = CONFIG["CUSTOM_GPT4O_MINI_API_KEY"]
PAYMENT_PROVIDER_TOKEN = CONFIG["PAYMENT_PROVIDER_TOKEN"]
YOUR_ADMIN_ID = CONFIG["ADMIN_ID"] # Переименовано для ясности в CONFIG, но старое имя используется в коде

# --- АГЕНТЫ ИИ ---
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

# --- МОДЕЛИ ИИ ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0",
        "id": "gemini-2.0-flash",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": CONFIG["DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY"],
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5",
        "id": "gemini-2.5-flash-preview-04-17",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY"],
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro",
        "id": "gemini-2.5-pro-preview-03-25",
        "api_type": "custom_http_api",
        "endpoint": CONFIG["CUSTOM_GEMINI_PRO_ENDPOINT"],
        "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY", # Имя глобальной переменной с ключом
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY"],
        "cost_category": "custom_api_pro_paid",
        "pricing_info": {}
    },
    "custom_api_grok_3": {
        "name": "Grok 3",
        "id": "grok-3-beta",
        "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3",
        "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GROK_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY"],
        "cost_category": "custom_api_grok_3_paid",
        "pricing_info": {}
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini",
        "id": "gpt-4o-mini",
        "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini",
        "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY"],
        "cost_category": "custom_api_gpt4o_mini_paid",
        "pricing_info": {}
    }
}
DEFAULT_MODEL_KEY = CONFIG["DEFAULT_MODEL_KEY"]
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

# --- СТРУКТУРА МЕНЮ ---
MENU_STRUCTURE = {
    "main_menu": {
        "title": "📋 Главное меню",
        "items": [
            {"text": "🤖 Агенты ИИ", "action": "submenu", "target": "ai_modes_submenu"},
            {"text": "⚙️ Модели ИИ", "action": "submenu", "target": "models_submenu"},
            {"text": "📊 Лимиты", "action": "submenu", "target": "limits_submenu"},
            {"text": "🎁 Бонус", "action": "submenu", "target": "bonus_submenu"},
            {"text": "💎 Подписка", "action": "submenu", "target": "subscription_submenu"},
            {"text": "❓ Помощь", "action": "submenu", "target": "help_submenu"}
        ],
        "parent": None,
        "is_submenu": False
    },
    "ai_modes_submenu": {
        "title": "Выберите агент ИИ",
        "items": [
            {"text": mode["name"], "action": "set_agent", "target": key}
            for key, mode in AI_MODES.items()
            if key != "gemini_pro_custom_mode"
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "models_submenu": {
        "title": "Выберите модель ИИ",
        "items": [
            {"text": model["name"], "action": "set_model", "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "limits_submenu": {
        "title": "Ваши лимиты",
        "items": [{"text": "📊 Показать", "action": "show_limits", "target": "usage"}],
        "parent": "main_menu",
        "is_submenu": True
    },
    "bonus_submenu": {
        "title": "Бонус за подписку",
        "items": [{"text": "🎁 Получить", "action": "check_bonus", "target": "news_bonus"}],
        "parent": "main_menu",
        "is_submenu": True
    },
    "subscription_submenu": {
        "title": "Подписка Профи",
        "items": [{"text": "💎 Купить", "action": "show_subscription", "target": "subscribe"}],
        "parent": "main_menu",
        "is_submenu": True
    },
    "help_submenu": {
        "title": "Помощь",
        "items": [{"text": "❓ Справка", "action": "show_help", "target": "help"}],
        "parent": "main_menu",
        "is_submenu": True
    }
}

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE ---
db: Optional[firestore.AsyncClient] = None # Используем AsyncClient если доступен, иначе обычный
try:
    firebase_credentials_json_str = CONFIG["FIREBASE_CREDENTIALS_JSON_STR"]
    cred_object = None
    if firebase_credentials_json_str:
        try:
            cred_dict = json.loads(firebase_credentials_json_str)
            cred_object = credentials.Certificate(cred_dict)
            logger.info("Firebase credentials loaded from JSON string.")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing FIREBASE_CREDENTIALS_JSON_STR: {e}. Check JSON in environment variable.")
            raise
    elif os.path.exists(CONFIG["FIREBASE_CERT_PATH"]):
        cred_object = credentials.Certificate(CONFIG["FIREBASE_CERT_PATH"])
        logger.info(f"Firebase credentials loaded from file: {CONFIG['FIREBASE_CERT_PATH']}.")
    else:
        logger.error("Firebase credentials not found. Neither FIREBASE_CREDENTIALS_JSON_STR nor local cert file were found.")
        raise FileNotFoundError("Firebase credentials not configured.")

    if not firebase_admin._apps: # Проверяем, инициализировано ли приложение по умолчанию
        initialize_app(cred_object)
        logger.info("Firebase app successfully initialized.")
    else:
        logger.info("Firebase app already initialized, skipping re-initialization.")

    db = firestore.client() # Получаем клиент Firestore
    logger.info("Firestore client successfully initialized.")

except Exception as e:
    logger.error(f"Critical error during Firebase/Firestore initialization: {e}", exc_info=True)
    db = None # Устанавливаем db в None, чтобы избежать ошибок при его использовании

# --- УТИЛИТЫ ДЛЯ FIREBASE (асинхронные обертки) ---
async def _execute_firestore_sync(func, *args, **kwargs):
    """Выполняет синхронную функцию Firestore в отдельном потоке."""
    if not db:
        logger.warning("Firestore (db) is not initialized. Operation skipped.")
        return None # Или {} в зависимости от ожидаемого результата
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

async def get_user_data(user_id: int, user_data_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if user_data_cache is not None: # Оптимизация: если данные уже загружены, используем их
        return user_data_cache
    if not db: return {}
    doc_ref = db.collection("users").document(str(user_id))
    doc = await _execute_firestore_sync(doc_ref.get)
    return doc.to_dict() if doc and doc.exists else {}

async def set_user_data(user_id: int, data: Dict[str, Any]):
    if not db: return
    doc_ref = db.collection("users").document(str(user_id))
    await _execute_firestore_sync(doc_ref.set, data, merge=True)
    logger.debug(f"User data for {user_id} updated: {data}")

async def get_bot_data() -> Dict[str, Any]:
    if not db: return {}
    doc_ref = db.collection("bot_data").document("data")
    doc = await _execute_firestore_sync(doc_ref.get)
    return doc.to_dict() if doc and doc.exists else {}

async def set_bot_data(data: Dict[str, Any]):
    if not db: return
    doc_ref = db.collection("bot_data").document("data")
    await _execute_firestore_sync(doc_ref.set, data, merge=True)
    logger.debug(f"Bot data updated: {data}")


# --- УТИЛИТЫ ДЛЯ УПРАВЛЕНИЯ СООБЩЕНИЯМИ ПОЛЬЗОВАТЕЛЯ ---
async def store_user_command_message(update: Update, user_id: int):
    """Сохраняет ID и timestamp сообщения пользователя для возможного удаления."""
    if update.message:
        user_data = await get_user_data(user_id) # Получаем свежие данные
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now(timezone.utc).isoformat() # Используем UTC
        }
        await set_user_data(user_id, user_data)

async def try_delete_user_message(update: Update, user_id: int):
    """Пытается удалить ранее сохраненное сообщение пользователя."""
    if not update or not update.message: return

    chat_id = update.effective_chat.id
    user_data = await get_user_data(user_id) # Получаем свежие данные для удаления
    command_message_info = user_data.pop('user_command_message', None) # Удаляем из user_data сразу

    if not command_message_info or not command_message_info.get('message_id') or not command_message_info.get('timestamp'):
        if command_message_info : await set_user_data(user_id, user_data) # Сохраняем, если что-то было извлечено, но невалидно
        return

    try:
        msg_time = datetime.fromisoformat(command_message_info['timestamp'])
        # Убедимся, что время UTC для сравнения, если оно наивное
        if msg_time.tzinfo is None:
            msg_time = msg_time.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - msg_time > timedelta(hours=48):
            logger.info(f"User message {command_message_info['message_id']} is older than 48 hours, not deleting.")
            await set_user_data(user_id, user_data) # Сохраняем user_data без user_command_message
            return
    except ValueError:
        logger.warning(f"Invalid timestamp for user message {command_message_info['message_id']}. Clearing record.")
        await set_user_data(user_id, user_data) # Сохраняем user_data без user_command_message
        return

    try:
        await update.get_bot().delete_message(chat_id=chat_id, message_id=command_message_info['message_id'])
        logger.info(f"Successfully deleted user message {command_message_info['message_id']} in chat {chat_id}")
    except telegram.error.BadRequest as e:
        logger.warning(f"Failed to delete user message {command_message_info['message_id']} in chat {chat_id}: {e}")
    finally:
        # Запись уже удалена из user_data в начале функции, сохраняем это состояние
        await set_user_data(user_id, user_data)


async def auto_delete_user_message_decorator(func):
    """Декоратор для автоматического сохранения и попытки удаления сообщения пользователя (команды/кнопки)."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if update.message: # Только если есть сообщение для удаления (не для callback_query и т.д.)
            await store_user_command_message(update, user_id)
            await try_delete_user_message(update, user_id) # Попытка удалить *текущее* сообщение
        return await func(update, context)
    return wrapper


# --- ЛОГИКА ПОЛЬЗОВАТЕЛЬСКИХ ДАННЫХ И ЛИМИТОВ ---
async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    user_data = user_data or await get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data.get('selected_api_type') != info.get("api_type"):
                user_data_update = {'selected_api_type': info.get("api_type")}
                await set_user_data(user_id, user_data_update)
                logger.info(f"Inferred and updated api_type to '{info.get('api_type')}' for model_id '{selected_id}' for user {user_id}")
            return key

    logger.warning(f"Could not find key for model_id '{selected_id}' (API type: '{selected_api_type}'). Falling back to default.")
    default_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    await set_user_data(user_id, {
        'selected_model_id': default_config["id"],
        'selected_api_type': default_config["api_type"]
    })
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    model_key = await get_current_model_key(user_id, user_data)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])


async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_data = user_data or await get_user_data(user_id)
    current_model_k = await get_current_model_key(user_id, user_data) # Используем user_data для оптимизации
    mode_k = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)

    if mode_k not in AI_MODES:
        mode_k = DEFAULT_AI_MODE_KEY
        await set_user_data(user_id, {'current_ai_mode': mode_k})
        logger.info(f"Reset invalid AI mode to default for user {user_id}")

    if current_model_k == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    
    return AI_MODES.get(mode_k, AI_MODES[DEFAULT_AI_MODE_KEY])


def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str) or len(text) <= max_length:
        return str(text), False

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)

    if adjusted_max_length <= 0:
        return text[:max_length-len("...")] + "...", True

    truncated_text = text[:adjusted_max_length]
    possible_cut_points = []
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']:
        pos = truncated_text.rfind(sep)
        if pos != -1:
            actual_pos = pos + (len(sep) if sep != ' ' else 0)
            if actual_pos > 0:
                possible_cut_points.append(actual_pos)

    if possible_cut_points:
        cut_at = max(possible_cut_points)
        if cut_at > adjusted_max_length * 0.3: # Не слишком ли рано режем?
            return text[:cut_at].strip() + suffix, True

    return text[:adjusted_max_length].strip() + suffix, True

def is_user_profi_subscriber(user_subscription_details: Dict[str, Any]) -> bool:
    """Проверяет, является ли пользователь активным Profi подписчиком."""
    if user_subscription_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"] and \
       user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            # Убедимся, что valid_until_dt имеет информацию о часовом поясе для сравнения с now(timezone.utc)
            # Если хранится как наивное UTC, добавим tzinfo
            if valid_until_dt.tzinfo is None:
                 valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            
            # Сравниваем даты, а не datetime, чтобы "до конца дня" работало корректно
            return datetime.now(timezone.utc).date() <= valid_until_dt.date()
        except ValueError:
            logger.error(f"Invalid 'valid_until' format: {user_subscription_details.get('valid_until')}")
            return False
    return False

async def get_user_actual_limit_for_model(user_id: int, model_key: str, user_data: Optional[Dict[str, Any]] = None, bot_data_cache: Optional[Dict[str, Any]] = None) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0

    bot_data = bot_data_cache or await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    limit_type = model_config.get("limit_type")
    base_limit = 0

    if limit_type == "daily_free":
        base_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        base_limit = model_config.get("subscription_daily_limit", 0) if is_profi else model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit", 0) if is_profi else model_config.get("limit_if_no_subscription", 0)
    elif not model_config.get("is_limited", False):
        return float('inf')
    else:
        return 0 # Неизвестный тип лимита или неограниченная модель без явного указания

    # Добавляем бонусные использования, если применимо (только для бонусной модели и если не профи)
    # И если бонусные использования не учитываются отдельно при списании.
    # Текущая логика в increment_request_count списывает бонус ПЕРЕД основным лимитом.
    # Поэтому get_user_actual_limit_for_model должен отражать ОБЩЕЕ количество доступных запросов.
    user_data = user_data or await get_user_data(user_id)
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and \
       not is_profi and \
       user_data.get('claimed_news_bonus', False):
        bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        # Этот блок можно было бы вынести, т.к. он дублирует логику из check_and_log_request_attempt немного
        # Для простоты, пока оставим так: бонус добавляется к "базовому" лимиту для этой модели.
        base_limit += bonus_uses_left
        
    return base_limit


async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_config or not model_config.get("is_limited"):
        return True, "", 0

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    # Проверка и возможное использование бонуса
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and \
       not is_profi and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} attempting to use NEWS_CHANNEL_BONUS for {model_key}. Bonus available.")
        return True, "bonus_available", 0 # Разрешаем, счетчик обновится в increment_request_count

    # Проверка основного лимита
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': '', 'count': 0})

    if model_daily_usage['date'] != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
        # Сохранение сброшенного счетчика произойдет в increment_request_count или если лимит достигнут

    current_daily_count = model_daily_usage['count']
    
    # Лимит для сравнения (без учета бонуса, т.к. бонус проверен выше)
    # get_user_actual_limit_for_model_effective вернет лимит БЕЗ бонуса для этой проверки
    limit_for_comparison = 0
    if model_config.get("limit_type") == "daily_free":
        limit_for_comparison = model_config.get("limit", 0)
    elif model_config.get("limit_type") == "subscription_or_daily_free":
        limit_for_comparison = model_config.get("subscription_daily_limit",0) if is_profi else model_config.get("limit_if_no_subscription",0)
    elif model_config.get("limit_type") == "subscription_custom_pro":
        limit_for_comparison = model_config.get("subscription_daily_limit",0) if is_profi else model_config.get("limit_if_no_subscription",0)


    if current_daily_count >= limit_for_comparison:
        # Лимит для отображения (может включать бонус, если он не был использован)
        display_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data, bot_data)
        
        message_parts = [
            f"Вы достигли дневного лимита ({current_daily_count}/{display_limit}) для модели {model_config['name']}."
        ]
        if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi:
            if not user_data.get('claimed_news_bonus', False):
                bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"], {})
                bonus_model_name_msg = bonus_model_cfg.get("name", "бонусной модели")
                message_parts.append(f'💡 Подпишитесь на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">канал</a> для бонусной генерации ({CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]} для {bonus_model_name_msg})!')
            elif user_data.get('news_bonus_uses_left', 0) == 0:
                message_parts.append(f"ℹ️ Бонус за подписку на <a href='{CONFIG['NEWS_CHANNEL_LINK']}'>канал</a> уже использован.")
        
        if not is_profi:
             message_parts.append("Попробуйте снова завтра или рассмотрите возможность <a href='https://t.me/gemini_oracle_bot?start=subscribe'>приобретения подписки</a> для увеличения лимитов (меню «Подписка»).")

        # Сохраняем, если дата сбросилась, но лимит все равно достигнут
        if model_daily_usage['date'] == today_str and user_model_counts.get(model_key) != model_daily_usage:
             user_model_counts[model_key] = model_daily_usage
             all_daily_counts[str(user_id)] = user_model_counts
             bot_data['all_user_daily_counts'] = all_daily_counts
             await set_bot_data(bot_data)

        return False, "\n".join(message_parts), current_daily_count

    # Если лимит не достигнут, но дата сбрасывалась - сохраняем.
    if model_daily_usage['date'] == today_str and user_model_counts.get(model_key) != model_daily_usage:
        user_model_counts[model_key] = model_daily_usage
        all_daily_counts[str(user_id)] = user_model_counts
        bot_data['all_user_daily_counts'] = all_daily_counts
        await set_bot_data(bot_data)
        
    return True, "", current_daily_count


async def increment_request_count(user_id: int, model_key: str):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data() # Получаем свежие данные перед обновлением
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    # Сначала пытаемся списать бонус, если это бонусная модель и пользователь не профи
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and \
       not is_profi and \
       user_data.get('claimed_news_bonus', False):
        news_bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        if news_bonus_uses_left > 0:
            user_data_update = {'news_bonus_uses_left': news_bonus_uses_left - 1}
            await set_user_data(user_id, user_data_update) # Обновляем только измененное поле
            logger.info(f"User {user_id} consumed one NEWS_CHANNEL_BONUS use for {model_key}. Remaining: {news_bonus_uses_left - 1}")
            return # Бонус использован, основной счетчик не трогаем

    # Если бонус не был использован, обновляем основной счетчик
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_daily_counts = bot_data.get('all_user_daily_counts', {}) # Гарантируем, что это словарь
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0})

    if model_daily_usage['date'] != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
    
    model_daily_usage['count'] += 1
    user_model_counts[model_key] = model_daily_usage
    all_daily_counts[str(user_id)] = user_model_counts
    
    await set_bot_data({'all_user_daily_counts': all_daily_counts}) # Обновляем только all_user_daily_counts в bot_data
    logger.info(f"User {user_id} daily count for {model_key} incremented to {model_daily_usage['count']}")


def is_menu_button_text(text: str) -> bool:
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons:
        return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data["items"]:
            if item["text"] == text:
                return True
    return False

# --- ГЕНЕРАЦИЯ КЛАВИАТУРЫ И ОТОБРАЖЕНИЕ МЕНЮ ---
def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu_config = MENU_STRUCTURE.get(menu_key)
    if not menu_config:
        logger.warning(f"Invalid menu_key '{menu_key}' in generate_menu_keyboard. Falling back to main_menu.")
        menu_config = MENU_STRUCTURE["main_menu"]

    keyboard_rows = []
    menu_items = menu_config["items"]

    # Двухколоночный макет для главного меню и меню моделей
    if menu_key in ["main_menu", "models_submenu"]:
        for i in range(0, len(menu_items), 2):
            row = [KeyboardButton(menu_items[j]["text"]) for j in range(i, min(i + 2, len(menu_items)))]
            keyboard_rows.append(row)
    else: # Одна кнопка на строку для остальных
        for item in menu_items:
            keyboard_rows.append([KeyboardButton(item["text"])])
    
    if menu_config.get("is_submenu", False):
        nav_row = []
        if menu_config.get("parent"):
            nav_row.append(KeyboardButton("⬅️ Назад"))
        nav_row.append(KeyboardButton("🏠 Главное меню"))
        keyboard_rows.append(nav_row)
    
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str, user_data: Optional[Dict[str, Any]] = None):
    menu_data_config = MENU_STRUCTURE.get(menu_key)
    if not menu_data_config:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main_menu for user {user_id}.")
        await update.message.reply_text(
            "Ошибка: Меню не найдено. Пожалуйста, используйте /start.",
            reply_markup=generate_menu_keyboard("main_menu")
        )
        await set_user_data(user_id, {'current_menu': 'main_menu'})
        return

    user_data_to_update = user_data or await get_user_data(user_id) # Используем кеш, если есть
    user_data_to_update['current_menu'] = menu_key
    await set_user_data(user_id, {'current_menu': menu_key}) # Обновляем только current_menu
    
    await update.message.reply_text(
        menu_data_config["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} shown menu '{menu_key}'.")


# --- ОБРАБОТЧИКИ КОМАНД ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id) # Загружаем один раз

    # Устанавливаем значения по умолчанию, если их нет
    if 'current_ai_mode' not in user_data: user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data: user_data['current_menu'] = 'main_menu'
    
    default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data: user_data['selected_model_id'] = default_model_conf["id"]
    if 'selected_api_type' not in user_data: user_data['selected_api_type'] = default_model_conf["api_type"]
    
    # Сохраняем сообщение для удаления (start команда обычно не удаляется сразу)
    if update.message:
        user_data['user_command_message_to_keep'] = { # Другое имя, чтобы не удалялось стандартным try_delete
            'message_id': update.message.message_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    await set_user_data(user_id, user_data) # Сохраняем все изменения одним запросом
    
    current_model_key_resolved = await get_current_model_key(user_id, user_data)
    mode_details_resolved = await get_current_mode_details(user_id, user_data)
    model_details_resolved = AVAILABLE_TEXT_MODELS.get(current_model_key_resolved)

    current_mode_name = mode_details_resolved['name'] if mode_details_resolved else "Неизвестный"
    current_model_name = model_details_resolved['name'] if model_details_resolved else "Неизвестная"

    greeting = (
        f"👋 Привет, {update.effective_user.first_name}!\n"
        f"Я твой ИИ-бот на базе различных нейросетей.\n\n"
        f"🧠 Текущий агент: <b>{current_mode_name}</b>\n"
        f"⚙️ Текущая модель: <b>{current_model_name}</b>\n\n"
        "💬 Задавай вопросы или используй клавиатурное меню ниже!"
    )
    await update.message.reply_text(
        greeting,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} started the bot.")

@auto_delete_user_message_decorator
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, "main_menu")

@auto_delete_user_message_decorator
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

@auto_delete_user_message_decorator
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription(update, update.effective_user.id)

@auto_delete_user_message_decorator
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_user_message_decorator
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)


async def show_limits(update: Update, user_id: int):
    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    is_profi = is_user_profi_subscriber(user_subscription_details)
    display_sub_level = "Бесплатный доступ"
    if is_profi:
        valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
        if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        display_sub_level = f"Подписка Профи (до {valid_until_dt.strftime('%Y-%m-%d')})"
    elif user_subscription_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"]: # Истекшая подписка
        valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
        if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        display_sub_level = f"Подписка Профи (истекла {valid_until_dt.strftime('%Y-%m-%d')})"


    usage_text_parts = [
        "<b>📊 Ваши лимиты запросов</b>",
        f"Текущий статус: <b>{display_sub_level}</b>", ""
    ]

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_user_daily_counts.get(str(user_id), {})

    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            
            actual_l = await get_user_actual_limit_for_model(user_id, model_k, user_data, bot_data) # Передаем кеши
            
            bonus_note = ""
            if model_k == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and \
               not is_profi and \
               user_data.get('claimed_news_bonus', False) and \
               user_data.get('news_bonus_uses_left', 0) > 0:
                bonus_note = f" (включая {user_data['news_bonus_uses_left']} бонусных)"

            limit_str = f"<b>{current_c_display}/{actual_l if actual_l != float('inf') else '∞'}</b>"
            usage_text_parts.append(f"▫️ {model_c['name']}: {limit_str}{bonus_note}")

    usage_text_parts.append("")
    bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"], {}).get('name', "бонусной модели")
    if not user_data.get('claimed_news_bonus', False):
        usage_text_parts.append(f'🎁 Подпишитесь на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">канал</a> и получите бонус ({CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]} для {bonus_model_name})!')
    elif (bonus_left := user_data.get('news_bonus_uses_left', 0)) > 0:
        usage_text_parts.append(f"✅ Активно <b>{bonus_left}</b> бонусных генераций ({bonus_model_name}) с <a href='{CONFIG['NEWS_CHANNEL_LINK']}'>канала</a>.")
    else:
        usage_text_parts.append(f"ℹ️ Бонусные генерации ({bonus_model_name}) с <a href='{CONFIG['NEWS_CHANNEL_LINK']}'>канала</a> использованы.")
    usage_text_parts.append("")

    if not is_profi:
        usage_text_parts.append("Больше лимитов и доступ к моделям? Меню «Подписка» или /subscribe.")

    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'limits_submenu'))
    await update.message.reply_text(
        "\n".join(usage_text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent usage/limits to user {user_id}.")


async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data = await get_user_data(user_id) # Загружаем один раз в начале
    # Сообщение пользователя уже должно быть удалено декоратором, если это команда.
    # Если это кнопка, menu_button_handler удалит его.

    parent_menu_key = user_data.get('current_menu', 'bonus_submenu')
    if parent_menu_key not in MENU_STRUCTURE or not MENU_STRUCTURE[parent_menu_key].get("is_submenu"):
         parent_menu_key = MENU_STRUCTURE.get(parent_menu_key, {}).get("parent", "main_menu")


    if not CONFIG["NEWS_CHANNEL_USERNAME"] or CONFIG["NEWS_CHANNEL_USERNAME"] == "@YourNewsChannelHandle":
        await update.message.reply_text(
            "Функция бонуса за подписку на канал не настроена.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"])
    if not bonus_model_config:
        await update.message.reply_text(
            "Ошибка: Бонусная модель не найдена. Обратитесь к администратору.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )
        return
    
    bonus_model_name = bonus_model_config['name']

    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        reply_text = (f'Вы уже активировали бонус. Осталось <b>{uses_left}</b> генераций для {bonus_model_name}.'
                      if uses_left > 0 else f'Бонус для {bonus_model_name} уже использован.')
        await update.message.reply_text(
            reply_text, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(parent_menu_key), disable_web_page_preview=True
        )
        return

    try:
        channel_to_check = CONFIG["NEWS_CHANNEL_USERNAME"]
        member_status = await update.get_bot().get_chat_member(chat_id=channel_to_check, user_id=user_id)
        
        if member_status.status in ['member', 'administrator', 'creator']:
            user_data_update = {
                'claimed_news_bonus': True,
                'news_bonus_uses_left': CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]
            }
            await set_user_data(user_id, user_data_update)
            
            success_text = (f'🎉 Спасибо за подписку на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{channel_to_check}</a>! '
                            f'Вам начислено <b>{CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]}</b> бонусных генераций для {bonus_model_name}.')
            await update.message.reply_text(
                success_text, parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard('main_menu'), disable_web_page_preview=True
            )
            logger.info(f"User {user_id} claimed news bonus for {bonus_model_name}.")
        else:
            fail_text = (f'Подпишитесь на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{channel_to_check}</a>, '
                         'затем нажмите «🎁 Получить» еще раз.')
            inline_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📢 Перейти в {channel_to_check}", url=CONFIG["NEWS_CHANNEL_LINK"])
            ]])
            await update.message.reply_text(
                fail_text, parse_mode=ParseMode.HTML,
                reply_markup=inline_keyboard, disable_web_page_preview=True
            )
    except telegram.error.BadRequest as e:
        logger.error(f"Telegram API BadRequest when checking channel {CONFIG['NEWS_CHANNEL_USERNAME']} membership: {e}")
        error_message = (f'Не удалось проверить подписку на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{CONFIG["NEWS_CHANNEL_USERNAME"]}</a>. '
                         'Убедитесь, что подписаны, и попробуйте позже.')
        await update.message.reply_text(
            error_message, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(parent_menu_key), disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Unexpected error during bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла ошибка при получении бонуса. Попробуйте позже.",
            reply_markup=generate_menu_keyboard(parent_menu_key)
        )


async def show_subscription(update: Update, user_id: int):
    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    sub_text_parts = ["<b>💎 Информация о Подписке Профи</b>"]
    is_active_profi = is_user_profi_subscriber(user_subscription_details)

    if is_active_profi:
        valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
        if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        sub_text_parts.append(f"\n✅ Ваша подписка <b>Профи</b> активна до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
        sub_text_parts.append("   Вам доступны расширенные лимиты и все модели ИИ.")
    else:
        if user_subscription_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"]: # Истекшая
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            sub_text_parts.append(f"\n⚠️ Ваша подписка <b>Профи</b> истекла <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")

        sub_text_parts.extend([
            "\nС подпиской <b>Профи</b> вы получаете:",
            "▫️ Значительно увеличенные дневные лимиты.",
            f"▫️ Приоритетный доступ к {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}.",
            f"▫️ Расширенный доступ к {AVAILABLE_TEXT_MODELS['custom_api_grok_3']['name']}.",
        ])
        if "custom_api_gpt_4o_mini" in AVAILABLE_TEXT_MODELS:
            sub_text_parts.append(f"▫️ Расширенный доступ к {AVAILABLE_TEXT_MODELS['custom_api_gpt_4o_mini']['name']}.")
        sub_text_parts.extend([
            "▫️ Поддержку развития бота.",
            "\nДля оформления или продления используйте /subscribe или кнопку в меню."
        ])
        # Здесь можно добавить кнопку для инициации оплаты, если PAYMENT_PROVIDER_TOKEN настроен
        # и вы готовы обрабатывать callback_data для создания счета.
        # Например: InlineKeyboardButton("💳 Оформить (30 дней - XX RUB)", callback_data="buy_pro_30d")

    current_menu_reply = user_data.get('current_menu', 'subscription_submenu')
    reply_markup_obj = generate_menu_keyboard(current_menu_reply)

    await update.message.reply_text(
        "\n".join(sub_text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup_obj,
        disable_web_page_preview=True
    )
    logger.info(f"Sent subscription info to user {user_id}.")


async def show_help(update: Update, user_id: int):
    user_data = await get_user_data(user_id) # Для reply_markup
    # Сообщение пользователя уже должно быть удалено декоратором или menu_button_handler

    help_text = (
        "<b>❓ Справка</b>\n\n"
        "Я — ваш ИИ-ассистент!\n"
        "▫️ <b>Запросы ИИ</b>: Задавайте вопросы, получайте ответы.\n"
        "▫️ <b>Агенты ИИ</b>: Выбирайте агентов ('Универсальный', 'Творческий' и др.) для разных задач. Меню «🤖 Агенты ИИ».\n"
        "▫️ <b>Модели ИИ</b>: Переключайтесь между моделями (Gemini, Grok, GPT). Меню «⚙️ Модели ИИ».\n"
        "▫️ <b>Лимиты</b>: У каждой модели есть дневные лимиты. Подписчики получают больше. Меню «📊 Лимиты» или /usage.\n"
        "▫️ <b>Бонус</b>: Подпишитесь на новостной канал (меню «🎁 Бонус») для доп. генераций.\n"
        "▫️ <b>Подписка Профи</b>: Больше лимитов и доступ к продвинутым моделям. Меню «💎 Подписка» или /subscribe.\n\n"
        "<b>Команды:</b>\n"
        "▫️ /start — Перезапуск / Главное меню\n"
        "▫️ /menu — Открыть меню\n"
        "▫️ /usage — Мои лимиты\n"
        "▫️ /subscribe — О подписке\n"
        "▫️ /bonus — Получить бонус\n"
        "▫️ /help — Эта справка"
    )
    current_menu_for_reply = user_data.get('current_menu', 'help_submenu')
    await update.message.reply_text(
        help_text, parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )
    logger.info(f"Sent help info to user {user_id}.")


async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    
    if not is_menu_button_text(button_text): # Это не кнопка меню, передаем дальше
        # Этот return важен, чтобы handle_text мог обработать обычный текст
        return True # Возвращаем True, чтобы указать, что сообщение не обработано здесь

    # Если это кнопка меню, удаляем ее отображение в чате
    await store_user_command_message(update, user_id)
    await try_delete_user_message(update, user_id)

    user_data = await get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', 'main_menu')
    logger.info(f"User {user_id} pressed menu button '{button_text}' from menu '{current_menu_key}'.")

    if button_text == "⬅️ Назад":
        parent_menu = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu")
        await show_menu(update, user_id, parent_menu, user_data)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu", user_data)
        return

    action_item = None
    # Ищем действие в текущем меню, затем во всех (на случай рассинхрона)
    for item in MENU_STRUCTURE.get(current_menu_key, {}).get("items", []):
        if item["text"] == button_text: action_item = item; break
    if not action_item:
        for menu_conf_iter in MENU_STRUCTURE.values():
            for item_iter in menu_conf_iter["items"]:
                if item_iter["text"] == button_text: action_item = item_iter; break
            if action_item: break
    
    if not action_item:
        logger.warning(f"Button '{button_text}' not matched by user {user_id}.")
        await update.message.reply_text("Неизвестная команда.", reply_markup=generate_menu_keyboard(current_menu_key))
        return

    action, target = action_item["action"], action_item["target"]
    return_menu = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu") # Куда вернуться

    if action == "submenu":
        await show_menu(update, user_id, target, user_data)
    elif action == "set_agent":
        if target in AI_MODES and target != "gemini_pro_custom_mode":
            await set_user_data(user_id, {'current_ai_mode': target})
            agent = AI_MODES[target]
            response_text = f"🤖 Агент ИИ: <b>{agent['name']}</b>.\n\n{agent.get('welcome', '')}"
        else: response_text = "⚠️ Ошибка: Агент не найден."
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu), disable_web_page_preview=True)
        await set_user_data(user_id, {'current_menu': return_menu})
    elif action == "set_model":
        if target in AVAILABLE_TEXT_MODELS:
            model_cfg = AVAILABLE_TEXT_MODELS[target]
            update_payload = {'selected_model_id': model_cfg["id"], 'selected_api_type': model_cfg["api_type"]}
            
            current_ai_mode = user_data.get('current_ai_mode') # Получаем текущий режим агента
            if target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and current_ai_mode == "gemini_pro_custom_mode":
                update_payload['current_ai_mode'] = DEFAULT_AI_MODE_KEY # Сброс на универсальный агент
                logger.info(f"Reset AI mode to default for user {user_id} due to model change to {target}")
            
            await set_user_data(user_id, update_payload)
            
            # Показываем лимит для новой модели
            bot_data_cache = await get_bot_data() # Кэшируем для get_user_actual_limit_for_model
            today_s = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            user_model_counts_s = bot_data_cache.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage_s = user_model_counts_s.get(target, {'date': '', 'count': 0})
            current_usage_s = model_daily_usage_s['count'] if model_daily_usage_s['date'] == today_s else 0
            actual_limit_s = await get_user_actual_limit_for_model(user_id, target, user_data, bot_data_cache)
            limit_str_s = f"{current_usage_s}/{actual_limit_s if actual_limit_s != float('inf') else '∞'}"
            
            response_text = f"⚙️ Модель ИИ: <b>{model_cfg['name']}</b>.\nЛимит сегодня: {limit_str_s}."
        else: response_text = "⚠️ Ошибка: Модель не найдена."
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu), disable_web_page_preview=True)
        await set_user_data(user_id, {'current_menu': return_menu}) # Обновляем current_menu после ответа
    elif action == "show_limits": await show_limits(update, user_id)
    elif action == "check_bonus": await claim_news_bonus_logic(update, user_id)
    elif action == "show_subscription": await show_subscription(update, user_id)
    elif action == "show_help": await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action '{action}' for button '{button_text}' by user {user_id}.")
        await update.message.reply_text("Действие не определено.", reply_markup=generate_menu_keyboard(current_menu_key))
    
    return None # Указываем, что сообщение обработано


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text: return
        
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Эта проверка была в menu_button_handler. Если menu_button_handler вернул True, значит это не кнопка.
    # if is_menu_button_text(user_message):
    #     logger.debug(f"User {user_id} sent text '{user_message}' which is a menu button. Should have been caught by menu_button_handler.")
    #     return # Предполагается, что menu_button_handler уже обработал или проигнорировал.

    if len(user_message) < CONFIG["MIN_AI_REQUEST_LENGTH"]:
        logger.info(f"User {user_id} sent short message: '{user_message}'")
        user_data_cache = await get_user_data(user_id) # Кэшируем для generate_menu_keyboard
        await update.message.reply_text(
            "Запрос слишком короткий. Пожалуйста, сформулируйте подробнее.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    logger.info(f"User {user_id} AI request: '{user_message[:100]}...'")

    # Кэшируем данные для функций ниже
    user_data_cached = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id, user_data_cached)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key)
    if not model_config: # Аварийный случай
        logger.critical(f"CRITICAL: Model config not found for key '{current_model_key}' for user {user_id}. Defaulting.")
        current_model_key = DEFAULT_MODEL_KEY
        model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        await update.message.reply_text("Критическая ошибка конфигурации модели. Сообщите администратору.",
                                        reply_markup=generate_menu_keyboard(user_data_cached.get('current_menu', 'main_menu')))
        return

    can_proceed, limit_msg, _ = await check_and_log_request_attempt(user_id, current_model_key)
    if not can_proceed:
        logger.info(f"User {user_id} limit for model {current_model_key}. Msg: {limit_msg}")
        await update.message.reply_text(
            limit_msg, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data_cached.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id, user_data_cached)
    system_prompt = mode_details["prompt"]
    response_text = "К сожалению, не удалось получить ответ от ИИ." # По умолчанию

    api_type = model_config.get("api_type", "").strip()

    if api_type == "google_genai":
        full_prompt = f"{system_prompt}\n\n**Пользовательский запрос:**\n{user_message}"
        try:
            genai_model_instance = genai.GenerativeModel(
                model_name=model_config["id"],
                generation_config={"max_output_tokens": CONFIG["MAX_OUTPUT_TOKENS_GEMINI_LIB"]}
            )
            logger.info(f"Sending to Google GenAI: {model_config['id']} for user {user_id}")
            genai_response_obj = await asyncio.get_event_loop().run_in_executor(
                None, lambda: genai_model_instance.generate_content(full_prompt)
            )
            response_text = genai_response_obj.text.strip() if genai_response_obj.text else "Ответ от Google GenAI пуст."
        except google.api_core.exceptions.ResourceExhausted as e:
            response_text = "Лимит Google API исчерпан. Попробуйте позже."
            logger.error(f"Google API ResourceExhausted for user {user_id}, model {model_config['id']}: {e}")
        except Exception as e:
            response_text = f"Ошибка Google API: {type(e).__name__}. Попробуйте позже."
            logger.error(f"Google GenAI API error for user {user_id}, model {model_config['id']}: {e}", exc_info=True)

    elif api_type == "custom_http_api":
        api_key_var = model_config.get("api_key_var_name")
        actual_api_key = globals().get(api_key_var) # Получаем ключ из глобальных переменных, установленных из CONFIG

        if not actual_api_key or "YOUR_" in actual_api_key or actual_api_key == "" or not actual_api_key.startswith("sk-"):
            response_text = f"Ошибка конфигурации ключа API для «{model_config.get('name', current_model_key)}». Сообщите администратору."
            logger.error(f"Custom API key error for '{api_key_var}' (model '{current_model_key}').")
        else:
            headers = {
                "Authorization": f"Bearer {actual_api_key}",
                "Content-Type": "application/json", "Accept": "application/json"
            }
            is_gpt4o_mini_model = (model_config["id"] == "gpt-4o-mini")
            payload_messages = []
            if system_prompt:
                payload_messages.append({
                    "role": "system", 
                    "content": [{"type": "text", "text": system_prompt}] if is_gpt4o_mini_model else system_prompt
                })
            payload_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": user_message}] if is_gpt4o_mini_model else user_message
            })
            
            api_payload_data = {
                "messages": payload_messages, "model": model_config["id"], "is_sync": True,
                "max_tokens": model_config.get("max_tokens", CONFIG["MAX_OUTPUT_TOKENS_GEMINI_LIB"]),
                "temperature": model_config.get("temperature", 1.0), "top_p": model_config.get("top_p", 1.0),
                "n": 1, "stream": False
            }
            if model_config.get("parameters"): api_payload_data.update(model_config["parameters"])

            try:
                logger.info(f"Sending to Custom API: {model_config['endpoint']} for model {model_config['id']}, user {user_id}")
                custom_response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: requests.post(model_config["endpoint"], headers=headers, json=api_payload_data, timeout=45)
                )
                custom_response.raise_for_status()
                response_json = custom_response.json()
                logger.debug(f"Raw JSON from {model_config['id']} for user {user_id}: {response_json}")
                
                extracted_text_content = None
                model_api_id_val = model_config["id"]

                if model_api_id_val == "grok-3-beta":
                    if "response" in response_json and isinstance(response_json["response"], list) and response_json["response"]:
                        completion = response_json["response"][0]
                        if "choices" in completion and isinstance(completion["choices"], list) and completion["choices"]:
                            choice = completion["choices"][0]
                            if "message" in choice and isinstance(choice["message"], dict):
                                extracted_text_content = choice["message"].get("content", "").strip()
                elif model_api_id_val == "gemini-2.5-pro-preview-03-25":
                    extracted_text_content = response_json.get("text", "").strip()
                elif model_api_id_val == "gpt-4o-mini":
                    if response_json.get("status") == "success":
                        output_data = response_json.get("output")
                        if isinstance(output_data, str): extracted_text_content = output_data.strip()
                        elif isinstance(output_data, dict): extracted_text_content = output_data.get("text", output_data.get("content", "")).strip()
                        elif output_data is not None: extracted_text_content = str(output_data).strip()
                        else: logger.warning(f"gpt-4o-mini: 'output' was null. Response: {response_json}")
                    else:
                        logger.error(f"gpt-4o-mini API error: Status '{response_json.get('status', 'N/A')}'. Response: {response_json}")
                        extracted_text_content = f"Ошибка API GPT-4o mini: {response_json.get('status', 'N/A')}. {response_json.get('error_message', '')}"
                
                if extracted_text_content is None: # Общий fallback
                    for key in ["text", "content", "message", "output", "response"]:
                        if isinstance(response_json.get(key), str):
                            extracted_text_content = response_json[key].strip()
                            if extracted_text_content: break
                
                response_text = extracted_text_content if extracted_text_content else "Ответ API не содержит текста или не удалось извлечь."

            except requests.exceptions.HTTPError as e:
                response_text = f"Ошибка сети Custom API ({e.response.status_code}). Попробуйте позже."
                logger.error(f"Custom API HTTPError for model {model_config['id']}: {e}. Response: {e.response.text}", exc_info=True)
            except requests.exceptions.RequestException as e:
                response_text = f"Сетевая ошибка Custom API: {type(e).__name__}. Попробуйте позже."
                logger.error(f"Custom API RequestException for model {model_config['id']}: {e}", exc_info=True)
            except Exception as e:
                response_text = f"Неожиданная ошибка Custom API: {type(e).__name__}."
                logger.error(f"Unexpected error with Custom API model {model_config['id']}: {e}", exc_info=True)
    else:
        response_text = "Ошибка: Неизвестный тип API для модели. Обратитесь к администратору."
        logger.error(f"Unknown api_type '{api_type}' for model {current_model_key}.")

    final_text, truncated = smart_truncate(response_text, CONFIG["MAX_MESSAGE_LENGTH_TELEGRAM"])
    if truncated: logger.info(f"Response for user {user_id} (model {current_model_key}) truncated.")

    await increment_request_count(user_id, current_model_key)
    
    await update.message.reply_text(
        final_text,
        reply_markup=generate_menu_keyboard(user_data_cached.get('current_menu', 'main_menu')), # Используем кеш
        disable_web_page_preview=True
    )
    logger.info(f"Sent AI response (model: {current_model_key}) to user {user_id}. Start: '{final_text[:100].replace(chr(10), ' ')}...'")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # Примерная проверка payload. Должна соответствовать тому, что вы отправляете.
    # Например, "profi_sub_30_days_userid_uniqueid"
    # Для простоты, если есть "subscription_" и PRO_SUBSCRIPTION_LEVEL_KEY в payload
    expected_payload_part = f"subscription_{CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']}" 
    
    if expected_payload_part in query.invoice_payload:
        await query.answer(ok=True)
        logger.info(f"Pre-checkout OK for user {query.user.id}, payload '{query.invoice_payload}'")
    else:
        await query.answer(ok=False, error_message="Неверный запрос на оплату. Попробуйте снова.")
        logger.warning(f"Pre-checkout REJECTED for user {query.user.id}, payload '{query.invoice_payload}'. Expected containing '{expected_payload_part}'.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    logger.info(f"Successful payment from user {user_id}. Payload: {payment.invoice_payload}, Amount: {payment.total_amount} {payment.currency}")

    # Опять же, проверяем payload. Здесь он должен быть более точным.
    # Например, вы генерируете payload "subscription_profi_access_v1_30days"
    # Для примера, предполагаем, что любой payload, прошедший precheckout, валиден для обновления подписки.
    # В реальном приложении здесь должна быть строгая проверка и извлечение деталей (например, длительности).
    
    # Для примера, хардкодим длительность. В реальности это должно быть частью payload или конфигурации товара.
    subscription_duration_days = 30 
    
    bot_data_local = await get_bot_data()
    user_subscriptions_local = bot_data_local.get('user_subscriptions', {})
    current_user_sub_local = user_subscriptions_local.get(str(user_id), {})

    now_utc = datetime.now(timezone.utc)
    start_date_ext = now_utc
    
    if is_user_profi_subscriber(current_user_sub_local): # Если уже есть активная подписка
        try:
            prev_valid_until = datetime.fromisoformat(current_user_sub_local['valid_until'])
            if prev_valid_until.tzinfo is None: prev_valid_until = prev_valid_until.replace(tzinfo=timezone.utc)
            if prev_valid_until > now_utc:
                start_date_ext = prev_valid_until # Продлеваем от предыдущей даты окончания
        except ValueError:
            logger.warning(f"Invalid 'valid_until' format for user {user_id} during payment: {current_user_sub_local.get('valid_until')}")

    new_valid_until = start_date_ext + timedelta(days=subscription_duration_days)
    
    user_subscriptions_local[str(user_id)] = {
        'level': CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"],
        'valid_until': new_valid_until.isoformat(),
        'last_payment_amount': payment.total_amount,
        'last_payment_currency': payment.currency,
        'purchase_date': now_utc.isoformat()
    }
    await set_bot_data({'user_subscriptions': user_subscriptions_local}) # Обновляем только user_subscriptions

    confirmation_msg = (f"🎉 Оплата успешна! Ваша подписка <b>Профи</b> "
                        f"активирована/продлена до <b>{new_valid_until.strftime('%d.%m.%Y')}</b>.\n"
                        f"Спасибо за поддержку!")
    
    user_data_local = await get_user_data(user_id) # Для reply_markup
    await update.message.reply_text(
        confirmation_msg, parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(user_data_local.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Subscription for user {user_id} updated to {CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']} until {new_valid_until.isoformat()}.")
    
    if CONFIG["ADMIN_ID"]:
        try:
            admin_msg = (f"🔔 Новая оплата подписки!\n"
                         f"User: {update.effective_user.full_name} (ID: {user_id}, @{update.effective_user.username})\n"
                         f"Amount: {payment.total_amount / 100} {payment.currency}\n" # Сумма в минимальных единицах
                         f"Sub '{CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']}' until: {new_valid_until.strftime('%d.%m.%Y')}\n"
                         f"Payload: {payment.invoice_payload}")
            await context.bot.send_message(chat_id=CONFIG["ADMIN_ID"], text=admin_msg, parse_mode=ParseMode.HTML)
        except Exception as e_admin:
             logger.error(f"Failed to send payment notification to admin {CONFIG['ADMIN_ID']}: {e_admin}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_list_data = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string_data = "".join(tb_list_data)
    update_str_data = update.to_dict() if isinstance(update, Update) else str(update)
    logger.error(f"Full Traceback for error by update {update_str_data}:\n{tb_string_data}")

    if isinstance(update, Update) and update.effective_chat:
        user_data_err_handler = await get_user_data(update.effective_user.id) if update.effective_user else {}
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла внутренняя ошибка. Мы уже работаем над этим. Попробуйте позже или /start.",
                reply_markup=generate_menu_keyboard(user_data_err_handler.get('current_menu', 'main_menu')),
            )
        except Exception as e_send:
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e_send}")

    if CONFIG["ADMIN_ID"] and isinstance(update, Update) and update.effective_user:
        try:
            user_info = f"{update.effective_user.full_name} (ID: {update.effective_user.id})"
            chat_info = f"Chat ID: {update.effective_chat.id}" if update.effective_chat else "No chat"
            message_text_info = update.message.text if update.message and update.message.text else "N/A"
            
            admin_error_msg = (
                f"🤖 Бот столкнулся с ошибкой:\n"
                f"Exception: {context.error.__class__.__name__}: {context.error}\n"
                f"User: {user_info}\n{chat_info}\n"
                f"User request: {message_text_info}\n\n"
                f"```\n{tb_string_data[:3500]}\n```" # Лимит для Telegram
            )
            await context.bot.send_message(chat_id=CONFIG["ADMIN_ID"], text=admin_error_msg, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e_admin_notify_err:
            logger.error(f"Failed to send detailed error to admin {CONFIG['ADMIN_ID']}: {e_admin_notify_err}. Original error: {context.error}")


async def main():
    app_builder_instance = Application.builder().token(CONFIG["TELEGRAM_TOKEN"])
    app_builder_instance.read_timeout(30).connect_timeout(30)
    app_instance = app_builder_instance.build()

    # Группа 0: Обработчики команд
    app_instance.add_handler(CommandHandler("start", start), group=0)
    app_instance.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app_instance.add_handler(CommandHandler("usage", usage_command), group=0)
    app_instance.add_handler(CommandHandler("subscribe", subscribe_info_command), group=0)
    app_instance.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app_instance.add_handler(CommandHandler("help", help_command), group=0)
    
    # Группа 1: Обработчик кнопок меню (должен идти перед общим текстовым обработчиком)
    # Важно: menu_button_handler должен возвращать НЕ None, если он НЕ обработал сообщение,
    # чтобы оно могло быть передано следующему обработчику в той же группе или следующей группе.
    # Если он обработал, он может вернуть None или что-то другое, что остановит распространение.
    # Здесь мы хотим, чтобы он был эксклюзивным для кнопок.
    app_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    
    # Группа 2: Обработчик обычного текста (после кнопок)
    app_instance.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app_instance.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app_instance.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    app_instance.add_error_handler(error_handler)

    bot_commands_list = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Мои лимиты использования"),
        BotCommand("subscribe", "💎 Информация о Подписке Профи"),
        BotCommand("bonus", "🎁 Получить бонус за канал"),
        BotCommand("help", "❓ Справка по боту")
    ]
    try:
        await app_instance.bot.set_my_commands(bot_commands_list)
        logger.info("Bot commands successfully set.")
    except Exception as e_set_cmd:
        logger.error(f"Failed to set bot commands: {e_set_cmd}")

    logger.info("Bot is starting polling...")
    await app_instance.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    # Конфигурация Google Gemini API
    if not CONFIG["GOOGLE_GEMINI_API_KEY"] or "YOUR_GOOGLE_GEMINI_API_KEY" in CONFIG["GOOGLE_GEMINI_API_KEY"] or not CONFIG["GOOGLE_GEMINI_API_KEY"].startswith("AIzaSy"):
        logger.warning("Google Gemini API key (GOOGLE_GEMINI_API_KEY) missing, placeholder, or incorrect.")
    else:
        try:
            genai.configure(api_key=CONFIG["GOOGLE_GEMINI_API_KEY"])
            logger.info("Google Gemini API configured.")
        except Exception as e_gemini_conf:
            logger.error(f"Failed to configure Google Gemini API: {e_gemini_conf}")

    # Проверка кастомных ключей
    for key_name in ["CUSTOM_GEMINI_PRO_API_KEY", "CUSTOM_GROK_3_API_KEY", "CUSTOM_GPT4O_MINI_API_KEY"]:
        key_value = CONFIG.get(key_name, "")
        if not key_value or "YOUR_" in key_value or (not key_value.startswith("sk-") and "AIzaSy" not in key_value) : # AIzaSy для Gemini, sk- для других
             logger.warning(f"Custom API key {key_name} in CONFIG appears to be missing, a placeholder, or incorrectly formatted.")

    if not CONFIG["PAYMENT_PROVIDER_TOKEN"] or "YOUR_PAYMENT_PROVIDER_TOKEN" in CONFIG["PAYMENT_PROVIDER_TOKEN"]:
        logger.warning("Payment Provider Token (PAYMENT_PROVIDER_TOKEN) missing or placeholder. Payments will not work.")
    
    if not db: # Проверка инициализации Firestore из блока try-except выше
        logger.critical("Firestore database (db) is NOT initialized. Bot functionality will be severely limited. Check Firebase setup.")
        # Можно добавить sys.exit(1) если Firebase критичен

    asyncio.run(main())
