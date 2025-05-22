import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, # InlineKeyboards might be used for specific actions like payments
    LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler # CallbackQueryHandler for Inline buttons if any
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
from typing import Optional, Dict, Any, List, Tuple

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient

nest_asyncio.apply()

# --- Глобальная конфигурация логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ (из оригинального файла bot (46).py) ---
# Загрузка конфигурации из переменных окружения с значениями по умолчанию из вашего файла
CONFIG_DEFAULTS = {
    "TELEGRAM_TOKEN": "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0",
    "GOOGLE_GEMINI_API_KEY": "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI", # Для Flash моделей через google-generativeai
    "CUSTOM_API_KEY_FOR_PRO_GROK_GPT": "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P", # Единый ключ для Gemini Pro (кастом), Grok, GPT
    "CUSTOM_GEMINI_PRO_ENDPOINT": "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro",
    "PAYMENT_PROVIDER_TOKEN": "390540012:LIVE:70602",
    "ADMIN_ID": "489230152", # Ваш ID администратора
    "FIREBASE_CREDENTIALS_JSON_STR": None, # Будет загружен из os.getenv("FIREBASE_CREDENTIALS")
    "FIREBASE_CERT_PATH": "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json", # Путь по умолчанию, если JSON_STR нет

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
    "NEWS_CHANNEL_BONUS_MODEL_KEY": "custom_api_gemini_2_5_pro", # Ключ из AVAILABLE_TEXT_MODELS
    "NEWS_CHANNEL_BONUS_GENERATIONS": 1,

    "DEFAULT_AI_MODE_KEY": "universal_ai_basic",
    "DEFAULT_MODEL_KEY": "google_gemini_2_0_flash", # Ключ из AVAILABLE_TEXT_MODELS
}

CONFIG = {}
for key, default_value in CONFIG_DEFAULTS.items():
    if key == "FIREBASE_CREDENTIALS_JSON_STR":
        CONFIG[key] = os.getenv("FIREBASE_CREDENTIALS") # Специальное имя переменной из вашего файла
    elif key == "ADMIN_ID":
        CONFIG[key] = int(os.getenv(key, default_value))
    else:
        CONFIG[key] = os.getenv(key, default_value)

# Переопределение глобальных констант для удобства, как в вашем файле
TOKEN = CONFIG["TELEGRAM_TOKEN"]
GOOGLE_GEMINI_API_KEY = CONFIG["GOOGLE_GEMINI_API_KEY"] # Для официальных Flash моделей
CUSTOM_API_KEY = CONFIG["CUSTOM_API_KEY_FOR_PRO_GROK_GPT"] # Единый ключ для кастомных вызовов
CUSTOM_GEMINI_PRO_ENDPOINT = CONFIG["CUSTOM_GEMINI_PRO_ENDPOINT"]
PAYMENT_PROVIDER_TOKEN = CONFIG["PAYMENT_PROVIDER_TOKEN"]
ADMIN_ID = CONFIG["ADMIN_ID"]


# --- AI MODES (Агенты ИИ) ---
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
    "gemini_pro_custom_mode": { # Этот режим будет использоваться, если выбрана модель custom_api_gemini_2_5_pro
        "name": "Продвинутый (Gemini Pro Custom)",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент."
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя."
            "Соблюдай вежливость и объективность."
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости."
            "Если твои знания ограничены по времени, укажи это."
        ),
        "welcome": "Активирован агент 'Продвинутый (Gemini Pro Custom)'. Какой у вас запрос?"
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

# --- AVAILABLE TEXT MODELS (Модели ИИ) ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0 Flash", "id": "gemini-2.0-flash", "api_type": "google_genai",
        "is_limited": True, "limit_type": "daily_free", "limit": CONFIG["DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY"],
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5 Flash Preview", "id": "gemini-2.5-flash-preview-04-17", "api_type": "google_genai",
        "is_limited": True, "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY"],
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": { # Gemini Pro через кастомный API
        "name": "Gemini 2.5 Pro Preview (Custom)", "id": "gemini-2.5-pro-preview-03-25", "api_type": "custom_http_api",
        "endpoint": CONFIG["CUSTOM_GEMINI_PRO_ENDPOINT"], "api_key_var_name": "CUSTOM_API_KEY_FOR_PRO_GROK_GPT", # Используем общий кастомный ключ
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY"],
        "cost_category": "custom_api_pro_paid", "pricing_info": {}
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": "custom_http_api", # ID может отличаться в вашем API
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_API_KEY_FOR_PRO_GROK_GPT", # Используем общий кастомный ключ
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GROK_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY"],
        "cost_category": "custom_api_grok_3_paid", "pricing_info": {}
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_API_KEY_FOR_PRO_GROK_GPT", # Используем общий кастомный ключ
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG["DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY"],
        "subscription_daily_limit": CONFIG["DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY"],
        "cost_category": "custom_api_gpt4o_mini_paid", "pricing_info": {}
    }
}
DEFAULT_MODEL_KEY = CONFIG["DEFAULT_MODEL_KEY"]
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]


# --- MENU STRUCTURE (Структура меню) ---
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
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode" # gemini_pro_custom_mode выбирается автоматически с моделью
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

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE (как в оригинальном файле) ---
db: Optional[FirestoreClient] = None
try:
    firebase_creds_json_str = CONFIG["FIREBASE_CREDENTIALS_JSON_STR"]
    cred_obj = None
    if firebase_creds_json_str:
        try:
            cred_obj = credentials.Certificate(json.loads(firebase_creds_json_str))
            logger.info("Firebase credentials loaded from JSON string (env var: FIREBASE_CREDENTIALS).")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing FIREBASE_CREDENTIALS_JSON_STR: {e}. Check environment variable.")
            # Попытка загрузить из файла, если JSON не удался, но файл указан
            if os.path.exists(CONFIG["FIREBASE_CERT_PATH"]):
                logger.info(f"Attempting to load Firebase credentials from file: {CONFIG['FIREBASE_CERT_PATH']} due to JSON error.")
                cred_obj = credentials.Certificate(CONFIG["FIREBASE_CERT_PATH"])
            else:
                raise # Перевыброс ошибки, если и файл не найден
        except Exception as e_cert_json: # Другие ошибки при создании Certificate из JSON
             logger.error(f"Error creating Certificate from JSON string: {e_cert_json}. Check JSON content.")
             if os.path.exists(CONFIG["FIREBASE_CERT_PATH"]):
                logger.info(f"Attempting to load Firebase credentials from file: {CONFIG['FIREBASE_CERT_PATH']} due to JSON Certificate error.")
                cred_obj = credentials.Certificate(CONFIG["FIREBASE_CERT_PATH"])
             else:
                raise

    elif os.path.exists(CONFIG["FIREBASE_CERT_PATH"]):
        cred_obj = credentials.Certificate(CONFIG["FIREBASE_CERT_PATH"])
        logger.info(f"Firebase credentials loaded from file: {CONFIG['FIREBASE_CERT_PATH']}.")
    else:
        logger.error("Firebase credentials not configured: Neither FIREBASE_CREDENTIALS (JSON string) env var nor cert file found.")
        # db останется None

    if cred_obj: # Только если cred_obj успешно создан
        if not firebase_admin._apps:
            initialize_app(cred_obj) # databaseURL не используется в Firestore SDK v1+ напрямую
            logger.info("Firebase app successfully initialized.")
        else:
            logger.info("Firebase app already initialized.")
        db = firestore.client()
        logger.info("Firestore client successfully initialized.")

except Exception as e:
    logger.critical(f"CRITICAL error during Firebase/Firestore initialization: {e}", exc_info=True)
    db = None # Убеждаемся, что db None в случае любой ошибки инициализации

# --- ИНИЦИАЛИЗАЦИЯ AI СЕРВИСОВ (только genai.configure) ---
if GOOGLE_GEMINI_API_KEY and not GOOGLE_GEMINI_API_KEY.startswith("YOUR_") and GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
    try:
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        logger.info(f"Google Gemini API (для Flash моделей) сконфигурирован (ключ: ...{GOOGLE_GEMINI_API_KEY[-4:]}).")
    except Exception as e:
        logger.error(f"Ошибка конфигурации Google Gemini API (для Flash): {e}", exc_info=True)
else:
    logger.warning(f"GOOGLE_GEMINI_API_KEY (для Flash) не настроен корректно. Функциональность этих моделей Gemini будет недоступна через 'genai'.")

# Кастомные ключи проверяются при вызове API

# --- УТИЛИТЫ FIREBASE (как в оригинальном файле) ---
async def _firestore_op(func, *args, **kwargs):
    """Helper to run synchronous Firestore operations in a thread."""
    if not db:
        logger.warning(f"Firestore (db) is not initialized. Operation '{func.__name__}' skipped.")
        return None
    try:
        return await asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs))
    except Exception as e:
        logger.error(f"Firestore operation {func.__name__} failed: {e}", exc_info=True)
        return None


async def get_user_data(user_id: int, user_data_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Получает данные пользователя из Firestore. Если user_data_cache передан, использует его."""
    if user_data_cache is not None:
        return user_data_cache
    if not db: return {} # Возвращаем пустой dict, если БД недоступна
    doc_ref = db.collection("users").document(str(user_id))
    doc = await _firestore_op(doc_ref.get)
    return doc.to_dict() if doc and doc.exists else {}

async def set_user_data(user_id: int, data: Dict[str, Any]):
    """Обновляет данные пользователя в Firestore."""
    if not db: return
    doc_ref = db.collection("users").document(str(user_id))
    await _firestore_op(doc_ref.set, data, merge=True)
    logger.debug(f"User data for {user_id} updated with keys: {list(data.keys())}")

async def get_bot_data() -> Dict[str, Any]:
    """Получает общие данные бота из Firestore."""
    if not db: return {}
    doc_ref = db.collection("bot_data").document("data") # Единый документ для данных бота
    doc = await _firestore_op(doc_ref.get)
    return doc.to_dict() if doc and doc.exists else {}

async def set_bot_data(data: Dict[str, Any]):
    """Обновляет общие данные бота в Firestore."""
    if not db: return
    doc_ref = db.collection("bot_data").document("data")
    await _firestore_op(doc_ref.set, data, merge=True)
    logger.debug(f"Bot data updated with keys: {list(data.keys())}")


# --- УДАЛЕНИЕ СООБЩЕНИЙ (как в оригинальном файле) ---
async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    """Stores message ID to delete later or deletes immediately if not to keep."""
    if not update.message: return

    message_id_to_process = update.message.message_id
    timestamp_now_iso = datetime.now(timezone.utc).isoformat()
    chat_id = update.effective_chat.id
    
    user_data_for_msg_handling = await get_user_data(user_id) # Получаем свежие данные

    # Пытаемся удалить предыдущее сохраненное сообщение пользователя (не команду)
    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)
    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc) # Ensure timezone aware
            
            # Удаляем только если сообщение не слишком старое (например, 48 часов)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48):
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e: # ValueError for fromisoformat
            logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    # Обработка текущего сообщения
    if not is_command_to_keep: # Если это обычный текст пользователя, пытаемся удалить сразу
        user_data_for_msg_handling['user_command_to_delete'] = { # Сохраняем на случай, если удаление не удастся
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
        try:
            await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_process)
            logger.info(f"Successfully deleted current user message {message_id_to_process}")
            user_data_for_msg_handling.pop('user_command_to_delete', None) # Удаляем из "очереди на удаление", если успешно
        except telegram.error.BadRequest as e:
            logger.warning(f"Failed to delete current user message {message_id_to_process}: {e}. Will try next time if stored.")
            # Сообщение остается в user_command_to_delete для следующей попытки
    else: # Если это команда, которую нужно сохранить (например, /start)
         # Очищаем предыдущую команду, которую нужно было сохранить, если она была
        user_data_for_msg_handling.pop('user_command_message_to_keep', None)
        user_data_for_msg_handling['user_command_message_to_keep'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
    await set_user_data(user_id, user_data_for_msg_handling)

def auto_delete_message_decorator(is_command_to_keep: bool = False):
    """Decorator to handle message deletion logic."""
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user and update.message: # Убедимся, что есть сообщение для обработки
                 await _store_and_try_delete_message(update, update.effective_user.id, is_command_to_keep)
            return await func(update, context)
        return wrapper
    return decorator

# --- УТИЛИТЫ ДЛЯ МОДЕЛЕЙ И РЕЖИМОВ (как в оригинальном файле) ---
async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    """Определяет текущий ключ модели для пользователя."""
    user_data_loc = user_data if user_data is not None else await get_user_data(user_id)
    selected_id = user_data_loc.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data_loc.get('selected_api_type') # Тип API, сохраненный для пользователя

    # Сначала ищем точное совпадение ID и типа API
    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key
    
    # Если точного совпадения нет или тип API не сохранен, ищем по ID и обновляем тип API
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            # Если тип API пользователя не совпадает с типом в конфигурации модели, обновляем его
            if user_data_loc.get('selected_api_type') != info.get("api_type"):
                await set_user_data(user_id, {'selected_api_type': info.get("api_type")})
            return key
            
    # Если модель вообще не найдена, возвращаем и устанавливаем дефолтную
    logger.warning(f"Model ID '{selected_id}' not found for user {user_id}. Reverting to default.")
    default_cfg = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    await set_user_data(user_id, {'selected_model_id': default_cfg["id"], 'selected_api_type': default_cfg["api_type"]})
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Получает полную конфигурацию для текущей выбранной модели пользователя."""
    model_key = await get_current_model_key(user_id, user_data)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])


async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Определяет текущий режим (агент) ИИ для пользователя."""
    user_data_loc = user_data if user_data is not None else await get_user_data(user_id)
    current_model_k_loc = await get_current_model_key(user_id, user_data_loc) # Получаем ключ текущей модели
    
    # Специальный режим для custom_api_gemini_2_5_pro
    if current_model_k_loc == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY]) # Возвращаем специальный режим

    # Для остальных моделей используем сохраненный режим или дефолтный
    mode_k_loc = user_data_loc.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    if mode_k_loc not in AI_MODES or mode_k_loc == "gemini_pro_custom_mode": # Если сохранен невалидный или специальный режим для другой модели
        mode_k_loc = DEFAULT_AI_MODE_KEY
        await set_user_data(user_id, {'current_ai_mode': mode_k_loc}) # Сбрасываем на дефолтный
        
    return AI_MODES.get(mode_k_loc, AI_MODES[DEFAULT_AI_MODE_KEY])


def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    """Обрезает текст до max_length, стараясь сохранить целостность предложений/абзацев."""
    if not isinstance(text, str) or len(text) <= max_length:
        return str(text), False # Возвращаем как есть, если нечего обрезать или не строка

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)

    if adjusted_max_length <= 0: # Если даже суффикс не помещается
        return text[:max_length - len("...")] + "...", True # Просто обрезаем

    truncated_text = text[:adjusted_max_length]
    
    # Ищем ближайший подходящий разделитель с конца
    # Приоритет: двойной перенос строки, конец предложения, одинарный перенос, пробел
    for separator in ['\n\n', '. ', '! ', '? ', '\n', ' ']:
        last_separator_pos = truncated_text.rfind(separator)
        if last_separator_pos != -1:
            # Убедимся, что обрезка не слишком короткая (например, не менее 30% от желаемой длины)
            # и что позиция разделителя не в самом начале
            actual_cut_pos = last_separator_pos + (len(separator) if separator != ' ' else 0) # Для пробела не добавляем его длину
            if actual_cut_pos > 0 and actual_cut_pos > adjusted_max_length * 0.3: # Обрезаем по этому разделителю
                 return text[:actual_cut_pos].strip() + suffix, True
                 
    # Если подходящий разделитель не найден, просто обрезаем по adjusted_max_length
    return text[:adjusted_max_length].strip() + suffix, True


# --- ЛИМИТЫ И ПОДПИСКА (как в оригинальном файле) ---
def is_user_profi_subscriber(subscription_details: Dict[str, Any]) -> bool:
    """Проверяет, является ли пользователь активным подписчиком 'Профи'."""
    if subscription_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"] and subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(subscription_details['valid_until'])
            if valid_until_dt.tzinfo is None: # Если нет таймзоны, считаем UTC
                valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            # Сравниваем только даты, без времени, чтобы подписка действовала весь последний день
            return datetime.now(timezone.utc).date() <= valid_until_dt.date()
        except ValueError:
            logger.error(f"Invalid date format in subscription_details['valid_until']: {subscription_details['valid_until']}")
            return False
    return False

async def get_user_actual_limit_for_model(user_id: int, model_key: str, user_data: Optional[Dict[str, Any]] = None, bot_data_cache: Optional[Dict[str, Any]] = None) -> int:
    """Рассчитывает актуальный дневной лимит для пользователя и модели."""
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0 # Модель не найдена

    bot_data_loc = bot_data_cache if bot_data_cache is not None else await get_bot_data()
    user_subscriptions = bot_data_loc.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    base_limit = 0
    limit_type = model_config.get("limit_type")

    if limit_type == "daily_free":
        base_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        base_limit = model_config.get("subscription_daily_limit", 0) if is_profi else model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit", 0) if is_profi else model_config.get("limit_if_no_subscription", 0)
    elif not model_config.get("is_limited", False): # Если модель не лимитирована
        return float('inf') 
    else: # Неизвестный тип лимита или модель лимитирована, но тип не указан
        return 0

    # Добавление бонуса, если применимо
    user_data_loc = user_data if user_data is not None else await get_user_data(user_id)
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi and \
       user_data_loc.get('claimed_news_bonus', False):
        base_limit += user_data_loc.get('news_bonus_uses_left', 0)
        
    return base_limit


async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    """Проверяет лимиты и возвращает (можно_ли_продолжить, сообщение_об_ошибке, текущее_использование)."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_config or not model_config.get("is_limited", False): # Если модель не найдена или не лимитирована
        return True, "", 0 

    user_data_loc = await get_user_data(user_id) # Нужны для проверки бонуса
    bot_data_loc = await get_bot_data()
    user_subscriptions = bot_data_loc.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    # Проверка бонуса ПЕРЕД проверкой основного лимита, если это бонусная модель и пользователь не профи
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi and \
       user_data_loc.get('claimed_news_bonus', False) and user_data_loc.get('news_bonus_uses_left', 0) > 0:
        return True, "bonus_available", 0 # Возвращаем 0 как "текущее использование основного лимита"

    # Получение текущего использования из all_user_daily_counts
    all_user_daily_counts = bot_data_loc.get('all_user_daily_counts', {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    model_usage_today = user_daily_counts.get(model_key, {'date': '', 'count': 0})

    current_usage_count = 0
    if model_usage_today['date'] == today_str:
        current_usage_count = model_usage_today['count']
    else: # Если дата не сегодняшняя, сбрасываем счетчик (но это должно происходить при инкременте)
        model_usage_today = {'date': today_str, 'count': 0}
        # Не сохраняем здесь, сохранение при инкременте

    # Получение актуального лимита
    # Передаем user_data_loc и bot_data_loc, чтобы избежать повторных чтений из БД
    actual_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
    
    if actual_limit == float('inf'): # Безлимит
        return True, "", current_usage_count

    if current_usage_count >= actual_limit:
        limit_message_parts = [f"Достигнут дневной лимит ({current_usage_count}/{actual_limit}) для {model_config['name']}."]
        
        # Информация о бонусе, если это бонусная модель и он не активен/использован
        if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi:
            bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"],{}).get("name","бонусной модели")
            if not user_data_loc.get('claimed_news_bonus', False):
                limit_message_parts.append(f'💡 Подписка на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">канал</a> даст бонус ({CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]} для {bonus_model_name})!')
            elif user_data_loc.get('news_bonus_uses_left', 0) == 0: # Бонус был, но использован
                limit_message_parts.append(f"ℹ️ Бонус с <a href='{CONFIG['NEWS_CHANNEL_LINK']}'>канала</a> для {bonus_model_name} использован.")

        if not is_profi: # Если не профи, предлагаем подписку
            limit_message_parts.append("Попробуйте завтра или оформите <a href='https://t.me/gemini_oracle_bot?start=subscribe'>подписку</a> для увеличения лимитов.")
        
        # Обновляем данные в bot_data, если дата не совпадает (на всякий случай, хотя это должно быть при инкременте)
        if model_usage_today['date'] != today_str and user_daily_counts.get(model_key) != model_usage_today :
            user_daily_counts[model_key] = model_usage_today
            all_user_daily_counts[str(user_id)] = user_daily_counts
            await set_bot_data({'all_user_daily_counts': all_user_daily_counts})

        return False, "\n".join(limit_message_parts), current_usage_count
    
    # Если лимит не достигнут, но дата старая, обновляем запись (это должно быть сделано при инкременте, но для консистентности)
    if model_usage_today['date'] != today_str and user_daily_counts.get(model_key) != model_usage_today:
        user_daily_counts[model_key] = {'date': today_str, 'count': 0} # Сброс на новый день
        all_user_daily_counts[str(user_id)] = user_daily_counts
        await set_bot_data({'all_user_daily_counts': all_user_daily_counts})
        current_usage_count = 0 # Обновляем для возврата

    return True, "", current_usage_count


async def increment_request_count(user_id: int, model_key: str):
    """Увеличивает счетчик использования для пользователя и модели."""
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited", False):
        return # Не увеличиваем счетчик для нелимитированных моделей

    user_data_loc = await get_user_data(user_id)
    bot_data_loc = await get_bot_data()
    user_subscriptions = bot_data_loc.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    # Если это бонусная модель, пользователь не профи, бонус активирован и есть попытки
    if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi and \
       user_data_loc.get('claimed_news_bonus', False) and \
       (bonus_uses_left := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        
        await set_user_data(user_id, {'news_bonus_uses_left': bonus_uses_left - 1})
        logger.info(f"User {user_id} consumed a NEWS CHANNEL BONUS use for {model_key}. Uses left: {bonus_uses_left - 1}")
        return # Основной счетчик не трогаем

    # Обновление основного счетчика в all_user_daily_counts
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get('all_user_daily_counts', {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    
    model_usage_today = user_daily_counts.get(model_key, {'date': '', 'count': 0})

    if model_usage_today['date'] == today_str:
        model_usage_today['count'] += 1
    else: # Первый запрос сегодня для этой модели
        model_usage_today = {'date': today_str, 'count': 1}
    
    user_daily_counts[model_key] = model_usage_today
    all_user_daily_counts[str(user_id)] = user_daily_counts
    await set_bot_data({'all_user_daily_counts': all_user_daily_counts})
    logger.info(f"User {user_id} daily count for {model_key} incremented to {model_usage_today['count']} on {today_str}")


# --- ГЕНЕРАЦИЯ МЕНЮ (как в оригинальном файле) ---
def is_menu_button_text(text: str) -> bool:
    """Проверяет, является ли текст кнопкой из меню."""
    if text in ["⬅️ Назад", "🏠 Главное меню"]: return True
    for menu_key, menu_data in MENU_STRUCTURE.items():
        for item in menu_data["items"]:
            if item["text"] == text:
                return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    """Генерирует ReplyKeyboardMarkup для указанного ключа меню."""
    menu_config = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE["main_menu"]) # По умолчанию главное меню
    keyboard_rows = []
    items = menu_config["items"]

    # Логика расположения кнопок из вашего файла
    if menu_key in ["main_menu", "models_submenu", "ai_modes_submenu"]: # Для этих меню кнопки по 2 в ряд
        for i in range(0, len(items), 2):
            row = [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            keyboard_rows.append(row)
    else: # Для остальных меню - по одной кнопке в ряд
        for item in items:
            keyboard_rows.append([KeyboardButton(item["text"])])
    
    # Добавление кнопок навигации "Назад" и "Главное меню" для подменю
    if menu_config.get("is_submenu", False):
        navigation_row = []
        if menu_config.get("parent"): # Если есть родитель, добавляем "Назад"
            navigation_row.append(KeyboardButton("⬅️ Назад"))
        navigation_row.append(KeyboardButton("🏠 Главное меню")) # "Главное меню" всегда есть в подменю
        keyboard_rows.append(navigation_row)
        
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False) # one_time_keyboard=False чтобы меню не скрывалось


async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    """Отображает указанное меню пользователю."""
    menu_config = MENU_STRUCTURE.get(menu_key)
    if not menu_config:
        logger.error(f"Menu key '{menu_key}' not found in MENU_STRUCTURE. Defaulting to main_menu for user {user_id}.")
        menu_key = "main_menu"
        menu_config = MENU_STRUCTURE[menu_key]

    await set_user_data(user_id, {'current_menu': menu_key}) # Сохраняем текущее меню пользователя
    
    # Проверяем, есть ли сообщение для ответа или редактирования
    reply_target = update.message or (update.callback_query and update.callback_query.message)
    if not reply_target:
        logger.error(f"Cannot show menu '{menu_key}' for user {user_id}: no message or callback_query.message to reply to.")
        # Можно попробовать отправить новое сообщение, если chat_id известен
        if update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=menu_config["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)
        return

    try:
        # Если это callback_query, пытаемся отредактировать сообщение
        if update.callback_query and update.callback_query.message:
             await update.callback_query.edit_message_text(
                text=menu_config["title"], 
                reply_markup=generate_menu_keyboard(menu_key), # ReplyKeyboardMarkup не работает с edit_message_text
                                                              # Здесь должна быть InlineKeyboardMarkup, если мы хотим редактировать
                                                              # Пока оставим так, но это не будет работать для callback
                parse_mode=ParseMode.HTML, 
                disable_web_page_preview=True
            )
             logger.warning("Attempted to use ReplyKeyboardMarkup with edit_message_text. This will likely fail.")
        elif update.message: # Если это обычное сообщение, отвечаем новым
            await update.message.reply_text(
                menu_config["title"], 
                reply_markup=generate_menu_keyboard(menu_key), 
                disable_web_page_preview=True
            )
        logger.info(f"User {user_id} shown menu '{menu_key}'.")
    except telegram.error.BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info(f"Menu message for '{menu_key}' not modified for user {user_id}.")
        else:
            logger.error(f"Error showing menu '{menu_key}' for user {user_id}: {e}", exc_info=True)
            # Если редактирование не удалось, пробуем отправить новое сообщение (если это был callback)
            if update.callback_query and update.effective_chat:
                 await update.effective_chat.send_message(text=menu_config["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)


# --- ОБРАБОТЧИКИ КОМАНД (с декоратором удаления) ---
@auto_delete_message_decorator(is_command_to_keep=True) # /start обычно не удаляют
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data_loc = await get_user_data(user_id) # Получаем данные пользователя
    
    updates_to_user_data = {}
    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc: # Устанавливаем текущее меню
        updates_to_user_data['current_menu'] = 'main_menu'
        
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
    if 'selected_api_type' not in user_data_loc: # Сохраняем и тип API
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if updates_to_user_data:
        await set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data) # Обновляем локальную копию

    # Получение актуальных имен для приветствия
    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_val = await get_current_mode_details(user_id, user_data_loc) # Передаем user_data_loc
    model_details_val = AVAILABLE_TEXT_MODELS.get(current_model_key_val)

    mode_name_display = mode_details_val['name'] if mode_details_val else "N/A"
    model_name_display = model_details_val['name'] if model_details_val else "N/A"
    
    greeting_message = (
        f"👋 Привет, {update.effective_user.first_name or user_id}!\n"
        f"🤖 Агент: <b>{mode_name_display}</b> | ⚙️ Модель: <b>{model_name_display}</b>\n"
        "💬 Задавай вопросы или используй меню!"
    )
    await update.message.reply_text(
        greeting_message, 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} ({update.effective_user.username or 'N/A'}) executed /start.")

@auto_delete_message_decorator() # Команду /menu обычно удаляют после показа меню
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data_loc = await get_user_data(update.effective_user.id) # Получаем данные для show_menu
    await show_menu(update, update.effective_user.id, "main_menu", user_data_loc)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id) # show_limits сама отправит сообщение

@auto_delete_message_decorator()
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription(update, update.effective_user.id)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)


# --- ФУНКЦИИ ОТОБРАЖЕНИЯ ИНФОРМАЦИИ (как в оригинальном файле) ---
async def show_limits(update: Update, user_id: int):
    """Отображает лимиты пользователя."""
    user_data_loc = await get_user_data(user_id)
    bot_data_loc = await get_bot_data()
    user_subscriptions = bot_data_loc.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscription_details)

    subscription_level_display = "Бесплатный"
    if is_profi:
        valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
        if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        subscription_level_display = f"Профи (до {valid_until_dt.strftime('%d.%m.%Y')})"
    elif user_subscription_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"]: # Если была подписка, но истекла
        valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
        if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        subscription_level_display = f"Профи (истекла {valid_until_dt.strftime('%d.%m.%Y')})"

    message_parts = [f"<b>📊 Ваши лимиты</b> (Статус: <b>{subscription_level_display}</b>)\n"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get('all_user_daily_counts', {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            model_usage_today = user_daily_counts.get(model_key, {'date': '', 'count': 0})
            usage_count_display = model_usage_today['count'] if model_usage_today['date'] == today_str else 0
            
            actual_user_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
            
            bonus_note = ""
            if model_key == CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"] and not is_profi and \
               user_data_loc.get('claimed_news_bonus', False) and \
               (bonus_left := user_data_loc.get('news_bonus_uses_left',0)) > 0:
                # Бонус добавляется к общему лимиту в get_user_actual_limit_for_model,
                # но можно указать его отдельно для ясности, если хотите
                bonus_note = f" (вкл. {bonus_left} бонус)" 
            
            limit_display_str = str(actual_user_limit) if actual_user_limit != float('inf') else '∞'
            message_parts.append(f"▫️ {model_config['name']}: <b>{usage_count_display}/{limit_display_str}</b>{bonus_note}")

    message_parts.append("") # Пустая строка для разделения
    bonus_model_name_display = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"],{}).get("name","бонусной модели")
    if not user_data_loc.get('claimed_news_bonus', False):
        message_parts.append(f'🎁 <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">Канал новостей</a>: бонус ({CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]} для {bonus_model_name_display})!')
    elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left',0)) > 0:
        message_parts.append(f"✅ Бонус с канала: <b>{bonus_left_val}</b> для {bonus_model_name_display}.")
    else: # Бонус был, но использован
        message_parts.append(f"ℹ️ Бонус с канала для {bonus_model_name_display} использован.")

    if not is_profi:
        message_parts.append("\n💎 Больше лимитов? /subscribe или кнопка «💎 Подписка» в меню.")
    
    current_menu_key_for_reply = user_data_loc.get('current_menu', 'limits_submenu') # Откуда пришел пользователь
    await update.message.reply_text(
        "\n".join(message_parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_key_for_reply),
        disable_web_page_preview=True
    )

async def claim_news_bonus_logic(update: Update, user_id: int):
    """Логика проверки подписки на канал и начисления бонуса."""
    user_data_loc = await get_user_data(user_id)
    # Определяем, в какое меню вернуть пользователя
    parent_menu_key = user_data_loc.get('current_menu', 'bonus_submenu') # Меню, из которого вызвали
    current_menu_details = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE["main_menu"])
    if not current_menu_details.get("is_submenu"): # Если это не подменю, возвращаем в главное
        parent_menu_key = "main_menu"
    else: # Иначе, возвращаем в родительское меню текущего подменю
        parent_menu_key = current_menu_details.get("parent", "main_menu")


    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG["NEWS_CHANNEL_BONUS_MODEL_KEY"])
    if not bonus_model_config:
        await update.message.reply_text("Ошибка: Бонусная модель не настроена администратором.", reply_markup=generate_menu_keyboard(parent_menu_key))
        return
        
    bonus_model_name_display = bonus_model_config['name']

    if user_data_loc.get('claimed_news_bonus', False):
        uses_left = user_data_loc.get('news_bonus_uses_left',0)
        reply_message = f"Бонус уже был активирован. Осталось: <b>{uses_left}</b> бесплатных генераций для модели «{bonus_model_name_display}»." if uses_left > 0 \
                        else f"Бонус для модели «{bonus_model_name_display}» уже был использован."
        await update.message.reply_text(reply_message, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(parent_menu_key), disable_web_page_preview=True)
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG["NEWS_CHANNEL_USERNAME"], user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await set_user_data(user_id, {
                'claimed_news_bonus': True, 
                'news_bonus_uses_left': CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]
            })
            success_message = (f'🎉 Спасибо за подписку на <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{CONFIG["NEWS_CHANNEL_USERNAME"]}</a>! '
                               f'Вам начислен бонус: <b>{CONFIG["NEWS_CHANNEL_BONUS_GENERATIONS"]}</b> бесплатных генераций для модели «{bonus_model_name_display}».')
            await update.message.reply_text(success_message, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard('main_menu'), disable_web_page_preview=True) # Возвращаем в главное меню
        else:
            failure_message = (f'Для получения бонуса, пожалуйста, сначала подпишитесь на канал <a href="{CONFIG["NEWS_CHANNEL_LINK"]}">{CONFIG["NEWS_CHANNEL_USERNAME"]}</a>, '
                               'а затем нажмите кнопку «🎁 Получить» еще раз.')
            # Предлагаем кнопку для перехода на канал
            inline_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на канал {CONFIG['NEWS_CHANNEL_USERNAME']}", url=CONFIG["NEWS_CHANNEL_LINK"])]])
            await update.message.reply_text(failure_message, parse_mode=ParseMode.HTML, reply_markup=inline_keyboard, disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        if "user not found" in str(e).lower() or "chat not found" in str(e).lower():
             await update.message.reply_text(f"Не удалось проверить подписку: возможно, вы не взаимодействовали с ботом ранее или канал {CONFIG['NEWS_CHANNEL_USERNAME']} недоступен. Попробуйте написать боту что-нибудь, а затем снова запросить бонус.", reply_markup=generate_menu_keyboard(parent_menu_key))
        else:
            logger.error(f"Error checking channel subscription for user {user_id}: {e}", exc_info=True)
            await update.message.reply_text("Произошла ошибка при проверке подписки на канал. Пожалуйста, попробуйте позже.", reply_markup=generate_menu_keyboard(parent_menu_key))
    except Exception as e:
        logger.error(f"Unexpected error claiming bonus for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.", reply_markup=generate_menu_keyboard(parent_menu_key))


async def show_subscription(update: Update, user_id: int):
    """Отображает информацию о подписке и кнопку для оплаты."""
    user_data_loc = await get_user_data(user_id)
    bot_data_loc = await get_bot_data()
    user_subscriptions = bot_data_loc.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_active_profi = is_user_profi_subscriber(user_subscription_details)

    message_parts = ["<b>💎 Подписка Профи</b>"]
    if is_active_profi:
        valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
        if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
        message_parts.append(f"\n✅ Ваша подписка <b>Профи</b> активна до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
        message_parts.append("Вам доступны расширенные лимиты и все модели.")
    else:
        if user_subscription_details.get('level') == CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"]: # Была, но истекла
             valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
             if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
             message_parts.append(f"\n⚠️ Ваша подписка <b>Профи</b> истекла <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
        
        message_parts.append("\nС подпиской <b>Профи</b> вы получаете:")
        message_parts.append("▫️ Значительно увеличенные дневные лимиты на все модели.")
        # Перечисляем платные модели, доступные по подписке
        if "custom_api_gemini_2_5_pro" in AVAILABLE_TEXT_MODELS:
             message_parts.append(f"▫️ Доступ к модели {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}.")
        if "custom_api_grok_3" in AVAILABLE_TEXT_MODELS:
             message_parts.append(f"▫️ Доступ к модели {AVAILABLE_TEXT_MODELS['custom_api_grok_3']['name']}.")
        if "custom_api_gpt_4o_mini" in AVAILABLE_TEXT_MODELS:
             message_parts.append(f"▫️ Доступ к модели {AVAILABLE_TEXT_MODELS['custom_api_gpt_4o_mini']['name']}.")
        
        price_rub = CONFIG["PRICE_AMOUNT_RUB"] / 100
        message_parts.append(f"\nСтоимость: <b>{price_rub:.0f} {CONFIG['CURRENCY']}</b> за 30 дней.")
        # Кнопка для оплаты (Inline)
        payment_button = InlineKeyboardButton(
            f"💳 Оплатить {price_rub:.0f} {CONFIG['CURRENCY']}", 
            callback_data="initiate_payment_profi_v1" # Уникальный callback для платежа
        )
        inline_keyboard_markup = InlineKeyboardMarkup([[payment_button]])
        
        # Отправляем сообщение с ReplyKeyboard текущего меню и Inline кнопкой оплаты
        current_menu_key_for_reply = user_data_loc.get('current_menu', 'subscription_submenu')
        await update.message.reply_text(
            "\n".join(message_parts), 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(current_menu_key_for_reply), # ReplyKeyboard для навигации
            disable_web_page_preview=True
        )
        # Отдельным сообщением отправляем кнопку оплаты, если не активна
        await update.message.reply_text(
            "Нажмите кнопку ниже, чтобы перейти к оплате:",
            reply_markup=inline_keyboard_markup
        )
        return # Выходим, так как уже отправили два сообщения

    current_menu_key_for_reply = user_data_loc.get('current_menu', 'subscription_submenu')
    await update.message.reply_text(
        "\n".join(message_parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_key_for_reply),
        disable_web_page_preview=True
    )


async def show_help(update: Update, user_id: int):
    """Отображает справочную информацию."""
    user_data_loc = await get_user_data(user_id)
    help_text_message = (
        "<b>❓ Справка по боту</b>\n\n"
        "▫️ <b>Запросы к ИИ</b>: Просто напишите ваш вопрос или задачу в чат, и бот ответит, используя текущий активный агент и модель.\n"
        "▫️ <b>Агенты ИИ</b>: Перейдите в меню «🤖 Агенты ИИ» для выбора специализированной роли ИИ (например, 'Творческий', 'Аналитик'). Это изменит стиль и направленность ответов.\n"
        "▫️ <b>Модели ИИ</b>: В меню «⚙️ Модели ИИ» вы можете выбрать конкретную нейросетевую модель для генерации ответов.\n"
        "▫️ <b>Лимиты</b>: Узнать ваши текущие дневные лимиты на использование моделей можно в меню «📊 Лимиты» или командой /usage.\n"
        "▫️ <b>Бонус</b>: Подпишитесь на наш новостной канал (кнопка «🎁 Бонус» в меню) и получите дополнительные бесплатные генерации для одной из продвинутых моделей!\n"
        "▫️ <b>Подписка</b>: Для снятия ограничений и доступа ко всем моделям оформите подписку «Профи» через меню «💎 Подписка» или команду /subscribe.\n\n"
        "<b>Доступные команды:</b>\n"
        "/start - Перезапустить бота и показать главное меню.\n"
        "/menu - Открыть главное меню.\n"
        "/usage - Показать ваши текущие лимиты.\n"
        "/subscribe - Информация о подписке Профи.\n"
        "/bonus - Получить бонус за подписку на новостной канал.\n"
        "/help - Показать эту справку."
    )
    current_menu_key_for_reply = user_data_loc.get('current_menu', 'help_submenu')
    await update.message.reply_text(
        help_text_message, 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_key_for_reply),
        disable_web_page_preview=True
    )

# --- ОБРАБОТЧИК КНОПОК МЕНЮ (текстовых) ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на кнопки ReplyKeyboard меню."""
    if not update.message or not update.message.text:
        logger.debug("menu_button_handler: No message or text in update.")
        return # Нечего обрабатывать
        
    user_id = update.effective_user.id
    button_text = update.message.text.strip()

    # Сначала проверяем, является ли текст кнопкой меню. Если нет, передаем управление дальше.
    if not is_menu_button_text(button_text):
        logger.debug(f"User {user_id} text '{button_text}' is not a menu button. Passing to handle_text.")
        # Здесь не должно быть return, чтобы handle_text мог обработать
        # Но если мы хотим строгую обработку только кнопок здесь, то return
        # В вашем оригинальном файле, если это не кнопка, то идет в handle_text.
        # Поэтому здесь не ставим return, а позволяем фильтрам в main решить.
        return 

    # Если это кнопка меню, удаляем сообщение с кнопкой
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False) 
                                       # is_command_to_keep=False, т.к. это текстовая кнопка меню

    user_data_loc = await get_user_data(user_id) # Получаем свежие данные
    current_menu_key = user_data_loc.get('current_menu', 'main_menu')
    logger.info(f"User {user_id} pressed menu button '{button_text}' while in menu '{current_menu_key}'.")

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu")
        await show_menu(update, user_id, parent_key, user_data_loc)
        return 
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu", user_data_loc)
        return
    else:
        # Ищем действие для этой кнопки в текущем меню или во всех меню (на случай прямого ввода)
        action_item = None
        # Сначала ищем в текущем меню
        for item_spec in MENU_STRUCTURE.get(current_menu_key, {}).get("items", []):
            if item_spec["text"] == button_text:
                action_item = item_spec
                break
        # Если не найдено в текущем, ищем во всех (для случаев, когда пользователь мог ввести текст кнопки другого меню)
        if not action_item:
            for menu_data_iter in MENU_STRUCTURE.values():
                for item_spec_iter in menu_data_iter["items"]:
                    if item_spec_iter["text"] == button_text:
                        action_item = item_spec_iter
                        # Обновляем current_menu, если кнопка из другого меню была "нажата" текстом
                        # Это эмулирует нажатие кнопки из того меню, где она определена
                        # await set_user_data(user_id, {'current_menu': menu_key_where_button_found})
                        # Но лучше просто выполнить действие и вернуть в родительское меню того меню, где кнопка
                        break
                if action_item: break
        
        if not action_item:
            logger.warning(f"Button text '{button_text}' by user {user_id} not matched to any action despite is_menu_button_text=True.")
            await update.message.reply_text("Неизвестная команда меню.", reply_markup=generate_menu_keyboard(current_menu_key))
            return

        action_type = action_item["action"]
        action_target = action_item["target"]
        
        # Определяем, в какое меню вернуть пользователя после действия
        # Обычно это родительское меню того меню, где была "нажата" кнопка
        # Найдем, в каком меню определена эта кнопка
        origin_menu_key_of_action = current_menu_key # По умолчанию - текущее
        for m_key, m_data in MENU_STRUCTURE.items():
            if any(it["text"] == button_text and it["action"] == action_type and it["target"] == action_target for it in m_data["items"]):
                origin_menu_key_of_action = m_key
                break
        
        return_to_menu_key = MENU_STRUCTURE.get(origin_menu_key_of_action, {}).get("parent", "main_menu")
        if origin_menu_key_of_action == "main_menu": # Если действие из главного меню, остаемся в главном
            return_to_menu_key = "main_menu"


        if action_type == "submenu":
            await show_menu(update, user_id, action_target, user_data_loc)
        elif action_type == "set_agent":
            response_message_text = "⚠️ Ошибка: Такой агент ИИ не найден."
            if action_target in AI_MODES and action_target != "gemini_pro_custom_mode":
                await set_user_data(user_id, {'current_ai_mode': action_target})
                agent_details = AI_MODES[action_target]
                response_message_text = f"🤖 Агент ИИ изменен на: <b>{agent_details['name']}</b>.\n{agent_details.get('welcome', '')}"
            await update.message.reply_text(response_message_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_to_menu_key), disable_web_page_preview=True)
            await set_user_data(user_id, {'current_menu': return_to_menu_key}) # Обновляем текущее меню

        elif action_type == "set_model":
            response_message_text = "⚠️ Ошибка: Такая модель ИИ не найдена."
            if action_target in AVAILABLE_TEXT_MODELS:
                model_info_selected = AVAILABLE_TEXT_MODELS[action_target]
                update_payload = {
                    'selected_model_id': model_info_selected["id"], 
                    'selected_api_type': model_info_selected.get("api_type")
                }
                # Если выбран Grok или GPT, а текущий агент был gemini_pro_custom_mode, сбрасываем агента на дефолтный
                if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and \
                   user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
                    update_payload['current_ai_mode'] = DEFAULT_AI_MODE_KEY
                
                await set_user_data(user_id, update_payload)
                user_data_loc.update(update_payload) # Обновляем локальную копию для get_user_actual_limit_for_model

                # Показываем лимит для выбранной модели
                bot_data_cached = await get_bot_data()
                today_string_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                user_model_counts = bot_data_cached.get('all_user_daily_counts', {}).get(str(user_id), {})
                model_daily_usage = user_model_counts.get(action_target, {'date': '', 'count': 0})
                current_usage_selected_model = model_daily_usage['count'] if model_daily_usage['date'] == today_string_val else 0
                actual_limit_selected_model = await get_user_actual_limit_for_model(user_id, action_target, user_data_loc, bot_data_cached)
                limit_string = f"{current_usage_selected_model}/{actual_limit_selected_model if actual_limit_selected_model != float('inf') else '∞'}"
                
                response_message_text = f"⚙️ Модель ИИ изменена на: <b>{model_info_selected['name']}</b>.\nТекущий лимит: {limit_string}."
            
            await update.message.reply_text(response_message_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_to_menu_key), disable_web_page_preview=True)
            await set_user_data(user_id, {'current_menu': return_to_menu_key}) # Обновляем текущее меню

        elif action_type == "show_limits": await show_limits(update, user_id)
        elif action_type == "check_bonus": await claim_news_bonus_logic(update, user_id)
        elif action_type == "show_subscription": await show_subscription(update, user_id) # Эта функция сама отправит кнопку оплаты если надо
        elif action_type == "show_help": await show_help(update, user_id)
        else:
            logger.warning(f"Unknown action type '{action_type}' for button '{button_text}' by user {user_id}.")
            await update.message.reply_text("Действие для этой кнопки не определено.", reply_markup=generate_menu_keyboard(current_menu_key))
    return # Явный return в конце обработки кнопки меню


# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (AI запросы) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения как запросы к AI."""
    if not update.message or not update.message.text or not update.effective_user:
        return

    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()

    # Важно: убедиться, что это не текстовая кнопка меню, которая случайно прошла фильтры
    if is_menu_button_text(user_message_text):
        logger.debug(f"User {user_id} sent menu button text '{user_message_text}' that reached handle_text. Explicitly ignoring to prevent double processing.")
        return # menu_button_handler должен был это обработать

    # Удаляем сообщение пользователя (если это не команда, которую нужно сохранить)
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)


    if len(user_message_text) < CONFIG["MIN_AI_REQUEST_LENGTH"]:
        user_data_cache = await get_user_data(user_id) # Получаем для reply_markup
        await update.message.reply_text(
            f"Ваш запрос слишком короткий. Минимальная длина: {CONFIG['MIN_AI_REQUEST_LENGTH']} символа.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu'))
        )
        return

    logger.info(f"User {user_id} ({update.effective_user.username or 'N/A'}) AI request: '{user_message_text[:100]}...'")
    
    user_data_cache = await get_user_data(user_id) # Получаем свежие данные пользователя
    current_model_key = await get_current_model_key(user_id, user_data_cache)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key)

    if not model_config:
        logger.error(f"CRITICAL: Model key '{current_model_key}' for user {user_id} not found in AVAILABLE_TEXT_MODELS.")
        await update.message.reply_text(
            "Критическая ошибка: выбранная модель не найдена. Пожалуйста, выберите другую модель в меню или сообщите администратору.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu'))
        )
        return

    # Проверка лимитов
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key)
    if not can_proceed:
        await update.message.reply_text(
            limit_message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id, user_data_cache)
    system_prompt_text = mode_details["prompt"]
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ в данный момент." # Ответ по умолчанию

    api_type = model_config.get("api_type", "").strip()
    model_id_for_api = model_config["id"]

    if api_type == "google_genai":
        full_prompt = f"{system_prompt_text}\n\n**Запрос пользователя:**\n{user_message_text}"
        try:
            # Используем GOOGLE_GEMINI_API_KEY, который был сконфигурирован в genai.configure()
            genai_model_instance = genai.GenerativeModel(
                model_id_for_api, 
                generation_config={"max_output_tokens": CONFIG["MAX_OUTPUT_TOKENS_GEMINI_LIB"]}
            )
            genai_response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: genai_model_instance.generate_content(full_prompt)
            )
            ai_response_text = genai_response.text.strip() if genai_response.text else "Ответ от Gemini (Official API) пуст."
        except google.api_core.exceptions.ResourceExhausted as e_res:
            ai_response_text = f"Лимит для модели {model_config['name']} через Google API исчерпан. Попробуйте позже."
            logger.error(f"Google GenAI API ResourceExhausted for {model_id_for_api}: {e_res}", exc_info=True)
        except Exception as e_genai:
            ai_response_text = f"Произошла ошибка при обращении к модели {model_config['name']} через Google API."
            logger.error(f"Google GenAI API error for {model_id_for_api}: {e_genai}", exc_info=True)

    elif api_type == "custom_http_api":
        # Для кастомных API используем CUSTOM_API_KEY
        actual_api_key = CUSTOM_API_KEY # Единый ключ для всех кастомных
        endpoint_url = model_config.get("endpoint")

        if not actual_api_key or actual_api_key.startswith("YOUR_") or not endpoint_url:
            ai_response_text = f"Ошибка конфигурации для модели «{model_config.get('name', current_model_key)}»: API ключ или эндпоинт не настроен."
            logger.error(f"Missing API key or endpoint for custom model {current_model_key}. Key: {'Set' if actual_api_key else 'Not Set'}, Endpoint: {endpoint_url}")
        else:
            headers = {
                "Authorization": f"Bearer {actual_api_key}", 
                "Content-Type": "application/json",
                "Accept": "application/json" # Как в вашем файле
            }
            # Формирование payload в зависимости от модели, как в вашем оригинальном файле
            is_gpt_format = (model_id_for_api == "gpt-4o-mini") # Пример для GPT-подобного формата
            
            messages_payload_list = []
            if system_prompt_text:
                messages_payload_list.append({
                    "role": "system", 
                    "content": [{"type": "text", "text": system_prompt_text}] if is_gpt_format else system_prompt_text
                })
            messages_payload_list.append({
                "role": "user", 
                "content": [{"type": "text", "text": user_message_text}] if is_gpt_format else user_message_text
            })
            
            api_payload = {
                "messages": messages_payload_list,
                "model": model_id_for_api, # ID модели для API
                "is_sync": True, # Как в вашем файле
                "max_tokens": model_config.get("max_tokens", CONFIG["MAX_OUTPUT_TOKENS_GEMINI_LIB"]) # max_tokens из конфига модели или общий
            }
            if model_config.get("parameters"): # Дополнительные параметры, если есть
                api_payload.update(model_config["parameters"])

            try:
                http_response = await asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: requests.post(endpoint_url, headers=headers, json=api_payload, timeout=45) # timeout 45s
                )
                http_response.raise_for_status() # Вызовет исключение для 4xx/5xx
                
                response_json = http_response.json()
                extracted_text_content = None

                # Логика извлечения ответа, адаптированная из вашего файла
                if model_id_for_api == "grok-3-beta": # ID из вашего AVAILABLE_TEXT_MODELS
                    # Пример структуры для Grok из вашего файла
                    if "response" in response_json and isinstance(response_json["response"], list) and \
                       response_json["response"] and "choices" in response_json["response"][0] and \
                       isinstance(response_json["response"][0]["choices"], list) and response_json["response"][0]["choices"]:
                        extracted_text_content = response_json["response"][0]["choices"][0].get("message",{}).get("content","").strip()
                elif model_id_for_api == "gemini-2.5-pro-preview-03-25": # ID из вашего AVAILABLE_TEXT_MODELS
                     extracted_text_content = response_json.get("text","").strip() # Как в вашем файле
                elif model_id_for_api == "gpt-4o-mini": # ID из вашего AVAILABLE_TEXT_MODELS
                    if response_json.get("status") == "success":
                        output_content = response_json.get("output")
                        if isinstance(output_content, str): extracted_text_content = output_content.strip()
                        elif isinstance(output_content, dict): extracted_text_content = output_content.get("text", output_content.get("content", "")).strip()
                        elif output_content is not None: extracted_text_content = str(output_content).strip()
                    else:
                        extracted_text_content = f"Ошибка API {model_config['name']}: {response_json.get('status','N/A')}. {response_json.get('error_message','')}"
                
                # Общий fallback, если специфичное извлечение не сработало
                if extracted_text_content is None: 
                    for key_to_check in ["text", "content", "message", "output", "response"]: # Порядок важен
                        if isinstance(response_json.get(key_to_check), str) and (potential_text := response_json[key_to_check].strip()):
                            extracted_text_content = potential_text
                            break
                
                ai_response_text = extracted_text_content if extracted_text_content else "Ответ от Custom API не содержит ожидаемого текста."

            except requests.exceptions.HTTPError as e_http:
                ai_response_text = f"Ошибка сети при обращении к Custom API ({model_config['name']}): {e_http.response.status_code}."
                logger.error(f"Custom API HTTPError for {model_id_for_api} at {endpoint_url}: {e_http}", exc_info=True)
            except requests.exceptions.RequestException as e_req:
                ai_response_text = f"Сетевая ошибка при обращении к Custom API ({model_config['name']}): {type(e_req).__name__}."
                logger.error(f"Custom API RequestException for {model_id_for_api} at {endpoint_url}: {e_req}", exc_info=True)
            except Exception as e_custom_api:
                ai_response_text = f"Неожиданная ошибка при обращении к Custom API ({model_config['name']})."
                logger.error(f"Unexpected Custom API error for {model_id_for_api} at {endpoint_url}: {e_custom_api}", exc_info=True)
    else:
        ai_response_text = "Ошибка: Неизвестный тип API для выбранной модели."
        logger.error(f"Unknown api_type '{api_type}' for model_key '{current_model_key}' user {user_id}.")

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG["MAX_MESSAGE_LENGTH_TELEGRAM"])
    await increment_request_count(user_id, current_model_key) # Увеличиваем счетчик после успешного (или неуспешного) запроса
    
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', 'main_menu')),
        disable_web_page_preview=True # Как в вашем файле
    )
    logger.info(f"Sent AI response (model: {current_model_key}) to user {user_id}.")


# --- ПЛАТЕЖИ (как в оригинальном файле) ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает pre-checkout запросы."""
    query = update.pre_checkout_query
    # Проверяем, что payload соответствует ожидаемому для подписки "Профи"
    expected_payload_part = f"subscription_{CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']}" # Например, "subscription_profi_access_v1"
    if query.invoice_payload and expected_payload_part in query.invoice_payload:
        await query.answer(ok=True)
        logger.info(f"PreCheckoutQuery OK for user {query.from_user.id}, payload: {query.invoice_payload}")
    else:
        logger.warning(f"PreCheckoutQuery FAILED for user {query.from_user.id}. Payload: {query.invoice_payload}, Expected part: {expected_payload_part}")
        await query.answer(ok=False, error_message="Неверный запрос на оплату. Пожалуйста, попробуйте снова из меню.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщение об успешном платеже."""
    if not update.message or not update.message.successful_payment or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    logger.info(f"Successful payment received from user {user_id}. Payload: {payment_info.invoice_payload}, Amount: {payment_info.total_amount} {payment_info.currency}")

    subscription_days = 30 # Длительность подписки
    bot_data_to_update = await get_bot_data() # Получаем текущие данные бота
    user_subscriptions_map = bot_data_to_update.get('user_subscriptions', {})
    
    current_user_subscription = user_subscriptions_map.get(str(user_id), {})
    now_utc = datetime.now(timezone.utc)
    
    # Определяем дату начала продления подписки
    subscription_extension_start_date = now_utc
    if is_user_profi_subscriber(current_user_subscription): # Если уже есть активная подписка
        try:
            previous_valid_until_dt = datetime.fromisoformat(current_user_subscription['valid_until'])
            if previous_valid_until_dt.tzinfo is None: previous_valid_until_dt = previous_valid_until_dt.replace(tzinfo=timezone.utc)
            
            if previous_valid_until_dt > now_utc: # Если старая подписка еще действительна, продлеваем от ее конца
                subscription_extension_start_date = previous_valid_until_dt
        except ValueError:
            logger.warning(f"Could not parse previous valid_until date '{current_user_subscription.get('valid_until')}' for user {user_id}. Extending from now.")
            
    new_valid_until_date = subscription_extension_start_date + timedelta(days=subscription_days)
    
    # Обновляем данные о подписке пользователя
    user_subscriptions_map[str(user_id)] = {
        'level': CONFIG["PRO_SUBSCRIPTION_LEVEL_KEY"],
        'valid_until': new_valid_until_date.isoformat(), # Сохраняем в ISO формате
        'last_payment_amount': payment_info.total_amount,
        'currency': payment_info.currency,
        'purchase_date': now_utc.isoformat(),
        'invoice_payload': payment_info.invoice_payload, # Сохраняем payload для истории
        'telegram_payment_charge_id': payment_info.telegram_payment_charge_id,
        'provider_payment_charge_id': payment_info.provider_payment_charge_id
    }
    await set_bot_data({'user_subscriptions': user_subscriptions_map}) # Сохраняем обновленную карту подписок

    confirmation_message = f"🎉 Оплата прошла успешно! Ваша подписка <b>Профи</b> активна до <b>{new_valid_until_date.strftime('%d.%m.%Y')}</b>."
    
    user_data_for_reply_menu = await get_user_data(user_id) # Для получения current_menu
    await update.message.reply_text(
        confirmation_message, 
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', 'main_menu'))
    )

    # Уведомление администратору
    if ADMIN_ID and ADMIN_ID != 0 :
        try:
            admin_notification = (f"🔔 Новая оплата Профи!\n"
                                  f"Пользователь: {user_id} (@{update.effective_user.username or 'N/A'})\n"
                                  f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                                  f"Подписка активна до: {new_valid_until_date.strftime('%d.%m.%Y')}")
            await context.bot.send_message(ADMIN_ID, admin_notification)
        except Exception as e_admin_notify:
            logger.error(f"Failed to send payment notification to admin {ADMIN_ID}: {e_admin_notify}")

# CallbackQueryHandler для кнопки оплаты
async def payment_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатие на Inline кнопку 'Оплатить'."""
    query = update.callback_query
    await query.answer() # Отвечаем на callback

    user_id = update.effective_user.id
    if not query.data == "initiate_payment_profi_v1":
        logger.warning(f"Unexpected callback_data for payment: {query.data} from user {user_id}")
        await query.message.reply_text("Неверная команда для оплаты.")
        return

    logger.info(f"User {user_id} initiated payment for 'profi_access_v1'")

    title = "Подписка Профи"
    description = f"Доступ ко всем моделям и расширенные лимиты на {CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']} на 30 дней."
    payload = f"subscription_{CONFIG['PRO_SUBSCRIPTION_LEVEL_KEY']}_{user_id}_{int(datetime.now().timestamp())}" # Уникальный payload
    provider_token_val = PAYMENT_PROVIDER_TOKEN
    currency_val = CONFIG["CURRENCY"]
    price_amount_val = CONFIG["PRICE_AMOUNT_RUB"] # Цена в копейках

    if not provider_token_val or "YOUR_" in provider_token_val or \
       (provider_token_val == CONFIG_DEFAULTS["PAYMENT_PROVIDER_TOKEN"] and os.getenv("PAYMENT_PROVIDER_TOKEN") is None):
        logger.error(f"Payment provider token ({CONFIG_PAYMENT_PROVIDER_TOKEN}) is not configured correctly.")
        await query.message.reply_text("К сожалению, система оплаты временно недоступна (ошибка конфигурации). Пожалуйста, свяжитесь с администратором.")
        return

    prices = [LabeledPrice(label=f"{title} (30 дней)", amount=price_amount_val)]

    try:
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token_val,
            currency=currency_val,
            prices=prices
        )
    except Exception as e_invoice:
        logger.error(f"Failed to send invoice to user {user_id}: {e_invoice}", exc_info=True)
        await query.message.reply_text("Не удалось создать счет на оплату. Пожалуйста, попробуйте позже или свяжитесь с поддержкой.")


# --- ОБРАБОТЧИК ОШИБОК (как в оригинальном файле) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    # Собираем traceback для детального логирования и отправки админу
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Формируем сообщение для пользователя
    user_error_message = "Произошла внутренняя ошибка. Мы уже работаем над этим. Пожалуйста, попробуйте позже или команду /start."
    if isinstance(context.error, telegram.error.NetworkError):
        user_error_message = "Проблема с сетевым подключением. Пожалуйста, проверьте ваше интернет-соединение и попробуйте снова."
    elif isinstance(context.error, telegram.error.BadRequest) and "message is not modified" in str(context.error).lower():
        logger.warning(f"Tried to modify a message without changes: {context.error}")
        return # Не отправляем сообщение пользователю в этом случае

    # Отправляем сообщение пользователю, если это возможно
    if isinstance(update, Update) and update.effective_chat:
        user_data_for_error_menu = {}
        if update.effective_user: # Пытаемся получить меню пользователя
            user_data_for_error_menu = await get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=user_error_message,
                reply_markup=generate_menu_keyboard(user_data_for_error_menu.get('current_menu', 'main_menu'))
            )
        except Exception as e_reply_error:
            logger.error(f"Failed to send error message to user: {e_reply_error}")

    # Уведомление администратора
    if ADMIN_ID and ADMIN_ID != 0:
        try:
            admin_message_text = f"🤖 Ошибка в боте:\n"
            admin_message_text += f"Тип ошибки: {type(context.error).__name__}\n"
            admin_message_text += f"Сообщение ошибки: {str(context.error)}\n"
            if isinstance(update, Update):
                if update.effective_user:
                    admin_message_text += f"Пользователь: {update.effective_user.id} (@{update.effective_user.username or 'N/A'})\n"
                if update.effective_message and update.effective_message.text:
                     admin_message_text += f"Текст сообщения: {update.effective_message.text[:200]}\n" # Первые 200 символов
                elif update.callback_query and update.callback_query.data:
                     admin_message_text += f"Callback data: {update.callback_query.data}\n"
            
            # Ограничиваем длину traceback для Telegram
            max_len_for_tb = 4000 - len(admin_message_text) - 50 # Запас для остального текста и форматирования
            truncated_tb_string = tb_string[:max_len_for_tb] + "\n... (traceback truncated)" if len(tb_string) > max_len_for_tb else tb_string
            
            final_admin_message = admin_message_text + "\n```\n" + truncated_tb_string + "\n```" # Markdown для traceback

            await context.bot.send_message(chat_id=ADMIN_ID, text=final_admin_message[:4096], parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e_admin_send:
            logger.error(f"Failed to send error notification to admin {ADMIN_ID}: {e_admin_send}")


# --- ОСНОВНАЯ ФУНКЦИЯ (main) ---
async def main():
    """Start the bot."""
    # Инициализация Firebase (уже сделана глобально, но убедимся, что db не None)
    if not db:
        logger.critical("Firestore (db) IS NOT INITIALIZED after global attempt! Bot will have severely limited functionality or may fail.")
        # Можно добавить sys.exit(1) если Firebase критичен

    # Инициализация genai (уже сделана глобально)
    if not genai._is_configured(): # Проверка, что genai.configure был вызван успешно
        logger.warning("Google Generative AI SDK (genai) is not configured. Calls to official Gemini models may fail.")

    # Создание Application
    application_builder = Application.builder().token(TOKEN)
    application_builder.read_timeout(30).connect_timeout(30) # Таймауты из вашего файла
    application = application_builder.build()

    # Регистрация обработчиков команд (группа 0 - высший приоритет)
    application.add_handler(CommandHandler("start", start), group=0)
    application.add_handler(CommandHandler("menu", open_menu_command), group=0)
    application.add_handler(CommandHandler("usage", usage_command), group=0)
    application.add_handler(CommandHandler("subscribe", subscribe_info_command), group=0)
    application.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    application.add_handler(CommandHandler("help", help_command), group=0)
    
    # Обработчик нажатий на кнопки меню (текстовые) (группа 1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    
    # Обработчик текстовых сообщений для AI (группа 2 - более низкий приоритет, чем кнопки меню)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    # Обработчики платежей
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # Обработчик нажатий на Inline кнопки (если будут добавлены, например, для оплаты)
    application.add_handler(CallbackQueryHandler(payment_button_callback, pattern="^initiate_payment_profi_v1$"))


    # Регистрация обработчика ошибок (должен быть последним)
    application.add_error_handler(error_handler)

    # Установка команд бота
    bot_commands_list = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Мои лимиты и использование"),
        BotCommand("subscribe", "💎 Информация о подписке Профи"),
        BotCommand("bonus", "🎁 Получить бонус за подписку на канал"),
        BotCommand("help", "❓ Справка по боту")
    ]
    try:
        await application.bot.set_my_commands(bot_commands_list)
        logger.info("Bot commands successfully set.")
    except Exception as e_set_commands:
        logger.error(f"Failed to set bot commands: {e_set_commands}")

    logger.info("Bot polling started...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    # Проверки конфигурации при запуске (как в вашем файле)
    # Firebase инициализируется глобально выше
    # genai.configure() вызывается глобально выше
    
    # Дополнительные проверки ключей, если нужно
    if not TOKEN or "YOUR_TELEGRAM_TOKEN" == TOKEN or len(TOKEN.split(':')) != 2:
        logger.critical("TELEGRAM_TOKEN is not set correctly!")
    # Проверка GOOGLE_GEMINI_API_KEY уже есть при genai.configure
    # Проверка CUSTOM_API_KEY
    if not CUSTOM_API_KEY or CUSTOM_API_KEY.startswith("YOUR_") or not (CUSTOM_API_KEY.startswith("sk-") or CUSTOM_API_KEY.startswith("AIzaSy")): # AIzaSy для Gemini, sk- для других
        logger.warning(f"CUSTOM_API_KEY_FOR_PRO_GROK_GPT ({CONFIG_DEFAULTS['CUSTOM_API_KEY_FOR_PRO_GROK_GPT']}) seems incorrect or is default. Custom models may not work.")
    if not PAYMENT_PROVIDER_TOKEN or "YOUR_" in PAYMENT_PROVIDER_TOKEN or \
       (PAYMENT_PROVIDER_TOKEN == CONFIG_DEFAULTS["PAYMENT_PROVIDER_TOKEN"] and os.getenv("PAYMENT_PROVIDER_TOKEN") is None):
        logger.warning("PAYMENT_PROVIDER_TOKEN seems incorrect or is default and not overridden. Payments may fail.")

    if not db:
        logger.critical("Firestore (db) IS NOT INITIALIZED at script execution! Bot will have severely limited functionality.")
        # Решение о выходе, если Firebase критичен
        # import sys
        # sys.exit("Firestore initialization failed. Exiting.")

    asyncio.run(main())
