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
from datetime import datetime, timedelta
from telegram import LabeledPrice
# from typing import Optional # Не используется явно
# import uuid # Не используется явно
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
import html # Для error_handler

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
YOUR_ADMIN_ID = 489230152
# YOUR_BOT_USERNAME = "YourBotUsername" # Замените на имя пользователя вашего бота (без @)

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000
MIN_AI_REQUEST_LENGTH = 4

# --- ЛИМИТЫ ---
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"
DEFAULT_FREE_REQUESTS_GROK_DAILY = 1
DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY = 25

# --- КАНАЛ НОВОСТЕЙ И БОНУС ---
NEWS_CHANNEL_USERNAME = "@timextech"
NEWS_CHANNEL_LINK = "https://t.me/timextech"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro" # Оставлено, измените на Grok если нужно
NEWS_CHANNEL_BONUS_GENERATIONS = 1

# --- РЕЖИМЫ РАБОТЫ ИИ ---
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
        "welcome": "Активирован режим 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый (Gemini Pro)",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент."
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя."
            "Соблюдай вежливость и объективность."
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости."
            "Если твои знания ограничены по времени, указывай это."
        ),
        "welcome": "Активирован режим 'Продвинутый (Gemini Pro)'. Какой у вас запрос?"
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
        "welcome": "Режим 'Творческий' к вашим услугам! Над какой задачей поработаем?"
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
        "welcome": "Режим 'Аналитик' активирован. Какую задачу проанализировать?"
    },
     "grok_3_custom_mode": {
        "name": "Продвинутый (Grok 3)",
        "prompt": (
            "Ты — Grok 3, мощный и немного эксцентричный ИИ-ассистент от xAI."
            "Отвечай точно, развернуто и с долей присущего тебе юмора, если это уместно."
            "Будь объективным, но не бойся высказывать собственное мнение, если тебя об этом просят."
            "Если твои знания ограничены по времени, указывай это."
            "Формулируй ответы ясно и структурированно."
        ),
        "welcome": "Активирован режим 'Продвинутый (Grok 3)'. Задавайте свои каверзные вопросы!"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini."
            "Твоя задача — отвечать на запросы с легкостью, остроумием и юмором, сохраняя при этом полезность."
            "Добавляй шутки, анекдоты или забавные комментарии, но оставайся в рамках приличия."
            "Форматируй ответы так, чтобы они были веселыми и читабельными."
        ),
        "welcome": "Режим 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

# --- МОДЕЛИ ИИ ---
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
        "cost_category": "custom_api_pro_paid",
        "pricing_info": {}
    },
    "custom_api_grok_3": {
        "name": "Grok 3",
        "id": "grok-3-beta", # Это ID модели для payload
        "api_type": "custom_http_api",
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3",
        "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GROK_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY,
        "cost_category": "custom_api_grok_3_paid",
        "pricing_info": {}
    }
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

# --- НОВАЯ СТРУКТУРА МЕНЮ ДЛЯ КЛАВИАТУРЫ ---
MENU_STRUCTURE = {
    "main_menu": {
        "title": "📋 Главное меню",
        "items": [
            {"text": "🤖 Режимы ИИ", "action": "submenu", "target": "ai_modes_submenu"},
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
        "title": "Выберите режим ИИ",
        "items": [
            {"text": mode["name"], "action": "set_agent", "target": key}
            for key, mode in AI_MODES.items()
            if key not in ["gemini_pro_custom_mode", "grok_3_custom_mode"] # Спец.режимы не выбираются тут
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
        "items": [
            {"text": "📊 Показать", "action": "show_limits", "target": "usage"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "bonus_submenu": {
        "title": "Бонус за подписку",
        "items": [
            {"text": "🎁 Получить", "action": "check_bonus", "target": "news_bonus"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "subscription_submenu": {
        "title": "Подписка Профи",
        "items": [
            {"text": "💎 Купить", "action": "show_subscription", "target": "subscribe"} # Можно изменить на "initiate_payment"
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "help_submenu": {
        "title": "Помощь",
        "items": [
            {"text": "❓ Справка", "action": "show_help", "target": "help"}
        ],
        "parent": "main_menu",
        "is_submenu": True
    }
}

# Инициализация Firebase
try:
    firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_credentials:
        try:
            cred_dict = json.loads(firebase_credentials)
            cred = credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга FIREBASE_CREDENTIALS: {e}")
            raise ValueError("Неверный формат FIREBASE_CREDENTIALS. Проверьте JSON в переменной окружения.")
    else:
        logger.warning("FIREBASE_CREDENTIALS не установлена, пытаемся использовать локальный файл")
        # ЗАМЕНИТЕ "your-firebase-adminsdk-file.json" на имя вашего файла ключа
        firebase_key_file = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"
        if os.path.exists(firebase_key_file):
            cred = credentials.Certificate(firebase_key_file)
        else:
            raise FileNotFoundError(f"Файл {firebase_key_file} не найден, и FIREBASE_CREDENTIALS не установлена.")

    if not firebase_admin._apps:
        initialize_app(cred)
        logger.info("Firebase успешно инициализирован")
    else:
        logger.info("Firebase уже инициализирован, пропускаем повторную инициализацию")
    db = firestore.client()
    logger.info("Firestore клиент успешно инициализирован")
except Exception as e:
    logger.error(f"Неизвестная ошибка при инициализации Firebase/Firestore: {e}")
    db = None # Устанавливаем db в None, чтобы последующие вызовы не падали сразу
    logger.warning("Бот будет работать без сохранения данных в Firestore.")


# --- Вспомогательные функции для работы с Firestore ---
async def get_user_data(user_id: int) -> dict:
    if not db: return {} # Работаем без Firestore
    try:
        doc_ref = db.collection("users").document(str(user_id))
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() or {}
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя {user_id} из Firestore: {e}")
        return {}

async def set_user_data(user_id: int, data: dict):
    if not db: return # Работаем без Firestore
    try:
        doc_ref = db.collection("users").document(str(user_id))
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        logger.info(f"Updated user data for {user_id}: {data if len(str(data)) < 200 else str(data)[:200] + '...'}")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных пользователя {user_id} в Firestore: {e}")

async def get_bot_data() -> dict:
    if not db: return {} # Работаем без Firestore
    try:
        doc_ref = db.collection("bot_data").document("data")
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() or {}
    except Exception as e:
        logger.error(f"Ошибка получения данных бота из Firestore: {e}")
        return {}

async def set_bot_data(data: dict):
    if not db: return # Работаем без Firestore
    try:
        doc_ref = db.collection("bot_data").document("data")
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        logger.info(f"Updated bot data: {data if len(str(data)) < 200 else str(data)[:200] + '...'}")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных бота в Firestore: {e}")

async def get_current_mode_details(user_id: int) -> dict:
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id)

    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    elif current_model_key == "custom_api_grok_3":
        return AI_MODES.get("grok_3_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    
    mode_key = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

async def get_current_model_key(user_id: int) -> str:
    user_data = await get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data.get('selected_api_type') != info.get("api_type"):
                user_data['selected_api_type'] = info.get("api_type")
                await set_user_data(user_id, user_data)
                logger.info(f"Updated api_type to '{info.get('api_type')}' for model_id '{selected_id}' for user {user_id}")
            return key

    logger.warning(f"Could not find model key for model_id '{selected_id}' for user {user_id}. Falling back to default.")
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    await set_user_data(user_id, {
        'selected_model_id': default_model_config["id"],
        'selected_api_type': default_model_config["api_type"]
    })
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int) -> dict:
    model_key = await get_current_model_key(user_id)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str):
        logger.warning(f"smart_truncate received non-string type: {type(text)}. Converting to string.")
        text = str(text)
    if len(text) <= max_length:
        return text, False
    
    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)
    
    if adjusted_max_length <= 0:
        return text[:max_length-len("...")] + "...", True
        
    truncated_text = text[:adjusted_max_length]
    
    possible_cut_points = []
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']: 
        pos = truncated_text.rfind(sep)
        if pos != -1:
            actual_pos = pos if sep in ['. ', '! ', '? '] else pos + len(sep)
            if actual_pos > 0:
                possible_cut_points.append(actual_pos)
                
    if possible_cut_points:
        cut_at = max(possible_cut_points)
        if cut_at > adjusted_max_length * 0.3: 
            return text[:cut_at].strip() + suffix, True
            
    return truncated_text.strip() + suffix, True

async def get_user_actual_limit_for_model(user_id: int, model_key: str) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0
    
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id) # Получаем user_data здесь
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    
    current_sub_level = None
    is_profi_subscriber = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                current_sub_level = user_subscription_details.get('level')
                is_profi_subscriber = True
        except Exception: pass

    limit_type = model_config.get("limit_type")
    base_limit = 0

    if limit_type == "daily_free":
        base_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        base_limit = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif not model_config.get("is_limited", False):
        return float('inf') # Безлимитная модель
    
    # Применение бонуса, если пользователь не профи и бонус для этой модели
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False):
        bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        return base_limit + bonus_uses_left
        
    return base_limit

async def check_and_log_request_attempt(user_id: int, model_key: str, bot_username: str) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_config or not model_config.get("is_limited"):
        return True, "", 0

    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)

    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi_subscriber = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                is_profi_subscriber = True
        except Exception: pass
    
    # Если это бонусная модель, пользователь не профи, бонус получен и еще есть попытки
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} using bonus for {model_key}. Allowing.")
        return True, "bonus_available", 0 # 0 current_count, т.к. это бонус

    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0})

    if model_daily_usage.get('date') != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
    
    current_daily_count = model_daily_usage.get('count', 0)
    
    # Получаем лимит только для модели (без учета бонуса, т.к. бонус проверен выше)
    actual_daily_limit_for_model_only = 0
    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free":
        actual_daily_limit_for_model_only = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        actual_daily_limit_for_model_only = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        actual_daily_limit_for_model_only = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)

    if current_daily_count >= actual_daily_limit_for_model_only:
        message_parts = [f"Вы достигли дневного лимита ({current_daily_count}/{actual_daily_limit_for_model_only}) для модели {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not user_data.get('claimed_news_bonus', False):
                message_parts.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a>, чтобы получить бонусные генерации!')
            elif user_data.get('news_bonus_uses_left', 0) == 0:
                message_parts.append(f"ℹ️ Бонус за подписку на канал (<a href='{NEWS_CHANNEL_LINK}'>канал</a>) уже использован.")
        
        subscribe_link = f"https://t.me/{bot_username}?start=subscribe" if bot_username else "/subscribe (или через меню)"
        message_parts.append(f"Попробуйте снова завтра или рассмотрите <a href='{subscribe_link}'>💎 Подписку Профи</a> для увеличения лимитов.")
        return False, "\n".join(message_parts), current_daily_count
        
    return True, "", current_daily_count

async def increment_request_count(user_id: int, model_key: str):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()
    is_profi_subscriber = False
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                is_profi_subscriber = True
        except Exception: pass

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False):
        news_bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        if news_bonus_uses_left > 0:
            user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
            await set_user_data(user_id, user_data)
            logger.info(f"User {user_id} consumed bonus for {model_key}. Remaining: {user_data['news_bonus_uses_left']}")
            return # Бонус использован, основной счетчик не трогаем

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_daily_usage.get('date') != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
    
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
    for menu_config in MENU_STRUCTURE.values():
        for item in menu_config.get("items", []):
            if item["text"] == text:
                return True
    return False

# Функции для меню и команд (start, open_menu_command, etc.) ...
# (Код этих функций из вашего последнего скрипта с небольшими корректировками)
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_key: str):
    user_id = update.effective_user.id
    menu_config = MENU_STRUCTURE.get(menu_key)
    if not menu_config:
        logger.error(f"Menu config for '{menu_key}' not found for user {user_id}. Sending main_menu.")
        menu_key = "main_menu"
        menu_config = MENU_STRUCTURE[menu_key]
    
    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key
    await set_user_data(user_id, user_data)
    
    await update.message.reply_text(
        menu_config["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        disable_web_page_preview=True
    )
    logger.info(f"Sent menu '{menu_key}' to user {user_id}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    user_data['current_menu'] = 'main_menu' # При старте всегда главное меню
    
    # Установка или подтверждение выбранной модели
    current_model_key_from_db = user_data.get('selected_model_key') # Предположим, что мы храним ключ модели
    if not current_model_key_from_db or current_model_key_from_db not in AVAILABLE_TEXT_MODELS:
        current_model_key_from_db = DEFAULT_MODEL_KEY # Фоллбэк на дефолтную модель
        user_data['selected_model_key'] = current_model_key_from_db # Сохраняем ключ
    
    model_conf = AVAILABLE_TEXT_MODELS[current_model_key_from_db]
    user_data['selected_model_id'] = model_conf["id"]
    user_data['selected_api_type'] = model_conf["api_type"]

    if context.args and context.args[0] == 'subscribe':
        await set_user_data(user_id, user_data) # Сохранить данные перед показом подписки
        await show_subscription(update, context, user_id, called_from_start=True)
        return
    
    await set_user_data(user_id, user_data)
    
    mode_details = await get_current_mode_details(user_id) # Учтет спец. режим для выбранной модели
    current_mode_name = mode_details['name']
    current_model_name = model_conf['name']

    greeting = (
        f"👋 Привет, {update.effective_user.first_name}!\n"
        f"Я твой ИИ-бот.\n\n"
        f"🧠 Активный режим: <b>{current_mode_name}</b>\n"
        f"⚙️ Текущая модель: <b>{current_model_name}</b>\n\n"
        f"💬 Задавайте вопросы или используйте меню /menu."
    )
    await update.message.reply_text(
        greeting,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"Sent start message to user {user_id}")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context, "main_menu")

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # context нужен для bot_username
    await show_limits(update, context, update.effective_user.id)

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # context нужен для bot_username
    await show_subscription(update, context, update.effective_user.id)

async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

async def show_limits(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int): # Добавлен context
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    display_sub_level = "Бесплатный доступ"
    subscription_active_profi = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                display_sub_level = f"Подписка Профи (до {valid_until_dt.strftime('%d.%m.%Y')})"
                subscription_active_profi = True
            else:
                display_sub_level = f"Подписка Профи (истекла {valid_until_dt.strftime('%d.%m.%Y')})"
        except Exception:
            display_sub_level = "Подписка Профи (ошибка в дате)"

    usage_text_parts = [
        "<b>📊 Ваши лимиты использования</b>",
        f"Текущий статус: <b>{display_sub_level}</b>", ""
    ]
    bot_username = context.bot.username # Получаем имя бота для ссылки
    subscribe_link = f"https://t.me/{bot_username}?start=subscribe" if bot_username else "/subscribe (или через меню)"

    if not subscription_active_profi:
        usage_text_parts.append(f"Вы можете <a href='{subscribe_link}'>💎 Улучшить до Профи</a> для увеличения лимитов.")
    else:
        usage_text_parts.append("Вам доступны расширенные дневные лимиты.")
    
    usage_text_parts.append("\n<b>Дневные лимиты запросов:</b>")
    
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage_info = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage_info['count'] if model_daily_usage_info.get('date') == today_str else 0
            actual_l = await get_user_actual_limit_for_model(user_id, model_k)
            
            bonus_note = ""
            if model_k == NEWS_CHANNEL_BONUS_MODEL_KEY and not subscription_active_profi and \
               user_data.get('claimed_news_bonus', False) and user_data.get('news_bonus_uses_left', 0) > 0:
                bonus_uses = user_data.get('news_bonus_uses_left', 0)
                bonus_note = f" (вкл. {bonus_uses} бонусн.)"
            
            usage_text_parts.append(f"▫️ {model_c['name']}: <b>{current_c_display} / {actual_l if actual_l != float('inf') else '∞'}</b>{bonus_note}")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
        if bonus_model_config and not subscription_active_profi:
            bonus_model_name = bonus_model_config['name']
            bonus_info = ""
            if not user_data.get('claimed_news_bonus', False):
                bonus_info = f'\n🎁 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a>, чтобы получить <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусных генераций для {bonus_model_name}!'
            elif (bonus_uses_left := user_data.get('news_bonus_uses_left', 0)) > 0:
                bonus_info = f'\n🎁 У вас осталось <b>{bonus_uses_left}</b> бонусных генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
            else:
                bonus_info = f'\nℹ️ Бонус за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a> для {bonus_model_name} использован.'
            if bonus_info: usage_text_parts.append(bonus_info)

    if not subscription_active_profi:
         usage_text_parts.append(f"\nДля увеличения лимитов рассмотрите <a href='{subscribe_link}'>💎 Подписку Профи</a>.")

    final_usage_text = "\n".join(filter(None, usage_text_parts))
    current_menu_key_for_reply = user_data.get('current_menu', 'limits_submenu')
    reply_markup = generate_menu_keyboard(current_menu_key_for_reply)

    await update.message.reply_text(
        final_usage_text, parse_mode=ParseMode.HTML,
        reply_markup=reply_markup, disable_web_page_preview=True
    )
    logger.info(f"Sent limits message to user {user_id}")

async def claim_news_bonus_logic(update: Update, user_id: int): # context не нужен
    user = update.effective_user
    user_data = await get_user_data(user_id)

    if update.message: # Попытка удалить сообщение с командой/кнопкой
        try: await update.message.delete()
        except Exception: pass

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        await update.message.reply_text("Функция бонуса не настроена.", reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text("Ошибка: Бонусная модель не найдена.", reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        return
    bonus_model_name = bonus_model_config['name']
    
    # Проверка на Профи подписку
    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                await update.message.reply_text(f"💎 Вы Профи подписчик. Бонус за канал для вас не суммируется.",
                                                reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
                return
        except: pass


    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        reply_text = f'Вы уже активировали бонус. Осталось <b>{uses_left}</b> генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).' if uses_left > 0 \
                     else f'Бонус для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>) использован.'
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')), disable_web_page_preview=True)
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member_status.status in ['member', 'administrator', 'creator']:
            user_data['claimed_news_bonus'] = True
            user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await set_user_data(user_id, user_data)
            success_text = f'🎉 Спасибо за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>! Вам начислена <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> генерация для {bonus_model_name}.'
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard('main_menu'), disable_web_page_preview=True)
        else:
            fail_text = f'Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> и нажмите «Получить» снова.'
            reply_markup_inline = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)]])
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup_inline, disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest checking channel membership: {e}")
        reply_message_on_error = f'Не удалось проверить подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>. Подпишитесь и попробуйте снова.'
        reply_markup_inline = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)]])
        await update.message.reply_text(reply_message_on_error, parse_mode=ParseMode.HTML, reply_markup=reply_markup_inline, disable_web_page_preview=True)

async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, called_from_start: bool = False): # Добавлен context
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    sub_text_parts = ["<b>💎 Подписка Профи</b>\n"]
    is_active_profi = False

    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                sub_text_parts.append(f"Ваша подписка активна до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
                is_active_profi = True
            else:
                sub_text_parts.append(f"Ваша подписка истекла <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
        except Exception:
            sub_text_parts.append("Ошибка проверки статуса подписки.")

    if not is_active_profi:
        sub_text_parts.append("С подпиской вы получите:")
        sub_text_parts.append(f"▫️ Увеличенные лимиты (например, {DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY} для Gemini 2.5, {DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY} для Gemini Pro, {DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY} для Grok 3).")
        sub_text_parts.append("▫️ Доступ к продвинутым моделям.")
        sub_text_parts.append("\n<b>Стоимость: [ВАША_ЦЕНА] [ВАЛЮТА] / 30 дней.</b>") # ЗАМЕНИТЬ
        sub_text_parts.append(f"\nДля покупки нажмите /pay или кнопку в меню.")
    
    final_sub_text = "\n".join(sub_text_parts)
    
    keyboard_inline = []
    if not is_active_profi:
         # TODO: Замените 'YOUR_PAY_COMMAND_OR_CALLBACK'
        keyboard_inline.append([InlineKeyboardButton("💳 Оформить Подписку Профи", callback_data="initiate_payment_profi")])

    parent_menu_key = 'main_menu' if called_from_start else user_data.get('current_menu', 'subscription_submenu')
    
    await update.message.reply_text(
        final_sub_text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard_inline) if keyboard_inline else generate_menu_keyboard(parent_menu_key),
        disable_web_page_preview=True
    )
    # Если нет инлайн кнопок (уже есть подписка), и мы не в главном меню, покажем клавиатуру навигации
    if not keyboard_inline and not called_from_start:
        await update.message.reply_text("Меню навигации:", reply_markup=generate_menu_keyboard(parent_menu_key))

    logger.info(f"Sent subscription info to user {user_id}")

async def show_help(update: Update, user_id: int): # context не нужен
    user_data = await get_user_data(user_id)
    if update.message: 
        try: await update.message.delete()
        except: pass

    help_text = (
        "<b>❓ Помощь по боту</b>\n\n"
        "Я — ИИ-бот. Вот что я умею:\n"
        "▫️ Отвечать на вопросы в разных режимах ИИ.\n"
        "▫️ Менять модели и режимы через меню (/menu).\n"
        "▫️ Показывать лимиты запросов (/usage).\n"
        "▫️ Предоставлять бонусы за подписку на канал (/bonus).\n"
        "▫️ Поддерживать подписку Профи для расширенных лимитов (/subscribe).\n\n"
        "Используйте меню или команды. Если что-то пошло не так, попробуйте /start."
    )
    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'help_submenu'))
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)
    logger.info(f"Sent help message to user {user_id}")

# ИСПРАВЛЕНО: menu_button_handler
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    
    user_data = await get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', 'main_menu')
    current_menu_config = MENU_STRUCTURE.get(current_menu_key, MENU_STRUCTURE['main_menu'])
    
    selected_item = None
    is_navigation_or_current_menu_button = False

    # 1. Проверка навигационных кнопок
    if button_text == "⬅️ Назад" and current_menu_config.get("parent"):
        selected_item = {"action": "navigate_back", "target": current_menu_config["parent"]}
        is_navigation_or_current_menu_button = True
    elif button_text == "🏠 Главное меню":
        selected_item = {"action": "navigate_home", "target": "main_menu"}
        is_navigation_or_current_menu_button = True
    
    # 2. Проверка кнопок текущего меню, если не навигационная
    if not is_navigation_or_current_menu_button:
        selected_item = next((item for item in current_menu_config.get("items", []) if item["text"] == button_text), None)
        if selected_item:
            is_navigation_or_current_menu_button = True

    # 3. Если это не кнопка текущего меню и не навигация
    if not is_navigation_or_current_menu_button:
        if not is_menu_button_text(button_text): # Вообще не кнопка меню
            logger.info(f"Text '{button_text}' from user {user_id} is not a menu button. Passing to text_handler.")
            # Ничего не делаем, позволяем MessageHandler(group=2) обработать текст
            return
        else: # Это кнопка меню, но не из текущего контекста (старая кнопка)
            logger.warning(f"User {user_id} pressed an old/out-of-context menu button: '{button_text}'. Current menu: '{current_menu_key}'.")
            try: await update.message.delete() # Удаляем сообщение со старой кнопкой
            except: pass
            await update.message.reply_text(
                "Эта кнопка больше не активна или не предназначена для текущего меню. Пожалуйста, используйте актуальное меню.",
                reply_markup=generate_menu_keyboard(current_menu_key)
            )
            return # Важно: выходим, чтобы не было двойной обработки

    # Если это действительная кнопка для текущего контекста, удаляем сообщение и обрабатываем
    if update.message:
        try:
            await update.message.delete()
            logger.info(f"Deleted user's button message '{button_text}' (ID: {update.message.message_id})")
        except Exception as e:
            logger.warning(f"Could not delete user's button message: {e}")

    action = selected_item["action"]
    target = selected_item["target"]
    logger.info(f"User {user_id} (menu: {current_menu_key}) -> Button: '{button_text}', Action: '{action}', Target: '{target}'")

    if action == "submenu":
        await show_menu(update, context, target)
    elif action == "navigate_back" or action == "navigate_home":
        await show_menu(update, context, target)
    elif action == "set_agent":
        return_menu_key = current_menu_config.get("parent", "main_menu")
        if target in AI_MODES and target not in ["gemini_pro_custom_mode", "grok_3_custom_mode"]:
            user_data['current_ai_mode'] = target
            await set_user_data(user_id, user_data)
            mode_details = AI_MODES[target]
            new_text = f"🤖 Режим ИИ изменён на: <b>{mode_details['name']}</b>\n\n{mode_details['welcome']}"
        else:
            new_text = "⚠️ Ошибка: Такой режим ИИ не найден или недоступен."
        await update.message.reply_text(new_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key), disable_web_page_preview=True)
        user_data['current_menu'] = return_menu_key
        await set_user_data(user_id, user_data)

    elif action == "set_model":
        return_menu_key = current_menu_config.get("parent", "main_menu")
        if target in AVAILABLE_TEXT_MODELS:
            model_cfg = AVAILABLE_TEXT_MODELS[target]
            user_data.update({
                'selected_model_id': model_cfg["id"],
                'selected_api_type': model_cfg["api_type"],
                'selected_model_key': target # Сохраняем ключ модели
            })
            # current_ai_mode не меняем здесь, он изменится через get_current_mode_details если нужно
            await set_user_data(user_id, user_data)
            
            bot_data_s = await get_bot_data()
            today_s = datetime.now().strftime("%Y-%m-%d")
            user_counts_s = bot_data_s.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_usage_s = user_counts_s.get(target, {'date': '', 'count': 0})
            count_display_s = model_usage_s['count'] if model_usage_s.get('date') == today_s else 0
            limit_actual_s = await get_user_actual_limit_for_model(user_id, target)
            limit_str_s = f"Лимит: {count_display_s}/{limit_actual_s if limit_actual_s != float('inf') else '∞'} в день"
            
            effective_mode_s = await get_current_mode_details(user_id) # Учтет спец. режим
            
            new_text = (f"⚙️ Модель ИИ изменена на: <b>{model_cfg['name']}</b>.\n"
                        f"🧠 Активный режим для неё: <b>{effective_mode_s['name']}</b>.\n"
                        f"{limit_str_s}")
        else:
            new_text = "⚠️ Ошибка: Такая модель ИИ не найдена."
        await update.message.reply_text(new_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key), disable_web_page_preview=True)
        user_data['current_menu'] = return_menu_key
        await set_user_data(user_id, user_data)

    elif action == "show_limits":
        await show_limits(update, context, user_id) # Передаем context
    elif action == "check_bonus":
        await claim_news_bonus_logic(update, user_id)
    elif action == "show_subscription":
        await show_subscription(update, context, user_id) # Передаем context
    elif action == "show_help":
        await show_help(update, user_id)
    else:
        await update.message.reply_text("Неизвестное действие.", reply_markup=generate_menu_keyboard(current_menu_key))

# ИСПРАВЛЕНО: handle_text для корректного парсинга Grok
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Эта проверка не нужна здесь, т.к. menu_button_handler (group=1) должен обработать кнопки
    # Если он не обработал и не сделал return, значит это текст для ИИ.
    # if is_menu_button_text(user_message):
    #     logger.info(f"Text '{user_message}' from user {user_id} is a menu button, should have been handled by menu_button_handler. Ignoring for AI.")
    #     return

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        logger.info(f"Text '{user_message}' from user {user_id} is too short for AI request.")
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            "Ваш запрос слишком короткий. Пожалуйста, сформулируйте его более подробно.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
        )
        return

    logger.info(f"Processing AI request from user {user_id}: '{user_message[:100]}...'")

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key)
    if not model_config:
        logger.error(f"Critical: model_config is None for key {current_model_key} (user {user_id}).")
        await update.message.reply_text("Ошибка конфигурации модели. Попробуйте /start.", reply_markup=generate_menu_keyboard('main_menu'))
        return

    bot_username = context.bot_data.get('bot_username', "YourBotName") # Получаем имя бота
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key, bot_username)

    if not can_proceed:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            limit_message, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        logger.info(f"User {user_id} limit reached for {current_model_key}.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id)
    system_prompt = mode_details["prompt"]
    response_text = "К сожалению, не удалось получить ответ от ИИ."

    if model_config["api_type"] == "google_genai":
        full_prompt_for_genai = f"{system_prompt}\n\n**Пользовательский запрос:**\n{user_message}"
        genai_model = genai.GenerativeModel(model_config["id"], generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB})
        try:
            response = await asyncio.get_event_loop().run_in_executor(None, lambda: genai_model.generate_content(full_prompt_for_genai))
            if response.text:
                response_text = response.text.strip()
            elif hasattr(response, 'parts') and response.parts:
                all_text_parts = [part.text for part in response.parts if hasattr(part, 'text')]
                response_text = "\n".join(all_text_parts).strip() if all_text_parts else "Ответ от ИИ не содержит текста."
            elif hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                 response_text = f"Запрос заблокирован: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
            if not response_text: response_text = "ИИ не дал ответа."
        except google.api_core.exceptions.ResourceExhausted:
            response_text = "Лимит API Google GenAI исчерпан. Попробуйте позже."
            logger.error(f"Google GenAI ResourceExhausted for user {user_id}, model {model_config['id']}")
        except Exception as e:
            response_text = f"Ошибка Google GenAI: {type(e).__name__}."
            logger.error(f"Google GenAI API error for user {user_id}, model {model_config['id']}: {traceback.format_exc()}")

    elif model_config["api_type"] == "custom_http_api":
        api_key_var_name = model_config.get("api_key_var_name")
        api_key = globals().get(api_key_var_name) if api_key_var_name else None
        if not api_key:
            logger.error(f"API ключ ({api_key_var_name}) не найден для {current_model_key}.")
            response_text = "Ошибка конфигурации API ключа для этой модели."
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}
            payload = {
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                "model": model_config["id"], "is_sync": True, "max_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB,
                "temperature": 1.0, "top_p": 1.0, "n": 1
            }
            try:
                api_response = await asyncio.get_event_loop().run_in_executor(None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=45)) # Увеличен таймаут
                api_response.raise_for_status()
                response_data = api_response.json()
                extracted_text_custom = None

                if model_config["id"] == "grok-3-beta": # ID модели Grok
                    try: # Парсинг специфичной структуры для Grok из логов
                        actual_response_list = response_data.get("response")
                        if actual_response_list and isinstance(actual_response_list, list) and actual_response_list:
                            first_response_item = actual_response_list[0]
                            if isinstance(first_response_item, dict):
                                choices = first_response_item.get("choices")
                                if choices and isinstance(choices, list) and choices:
                                    first_choice = choices[0]
                                    if isinstance(first_choice, dict):
                                        message_obj = first_choice.get("message")
                                        if isinstance(message_obj, dict):
                                            content_obj = message_obj.get("content")
                                            if isinstance(content_obj, dict):
                                                text_candidate = content_obj.get("text")
                                                if text_candidate and isinstance(text_candidate, str):
                                                    extracted_text_custom = text_candidate.strip()
                    except Exception as e_parse:
                        logger.error(f"Error parsing specific Grok-3 response for user {user_id}: {e_parse}. Data: {str(response_data)[:500]}")
                    
                    # Фоллбэк, если специфичный парсинг не удался
                    if not extracted_text_custom:
                        logger.info(f"Specific Grok-3 parsing failed for user {user_id}, trying generic 'output'/'text'.")
                        text_cand_output = response_data.get("output")
                        if text_cand_output and isinstance(text_cand_output, str): extracted_text_custom = text_cand_output.strip()
                        if not extracted_text_custom:
                            text_cand_text = response_data.get("text")
                            if text_cand_text and isinstance(text_cand_text, str): extracted_text_custom = text_cand_text.strip()
                
                elif model_config["id"] == "gemini-2.5-pro-preview-03-25": # ID модели Gemini Pro
                    text_candidate = response_data.get("text") # Основное поле для Gemini Pro
                    if text_candidate and isinstance(text_candidate, str): extracted_text_custom = text_candidate.strip()
                    if not extracted_text_custom: # Фоллбэк
                        text_cand_output = response_data.get("output")
                        if text_cand_output and isinstance(text_cand_output, str): extracted_text_custom = text_cand_output.strip()
                
                # Другие кастомные модели можно добавить сюда по аналогии

                if extracted_text_custom:
                    response_text = extracted_text_custom
                else:
                    response_text = "Ответ от API получен, но текст извлечь не удалось."
                    logger.warning(f"Could not extract text from Custom API for model {model_config['id']}, user {user_id}. Response: {str(response_data)[:500]}")

            except requests.exceptions.Timeout:
                response_text = "Время ожидания ответа от ИИ истекло. Попробуйте позже."
                logger.error(f"Custom API Timeout for user {user_id}, model {model_config['id']}.")
            except requests.exceptions.RequestException as e:
                response_text = "Ошибка сети при обращении к ИИ. Попробуйте позже."
                logger.error(f"Custom API Network Error for user {user_id}, model {model_config['id']}: {e}")
            except json.JSONDecodeError as e:
                response_text = "Сервер ИИ вернул некорректный ответ. Попробуйте позже."
                logger.error(f"Custom API JSONDecodeError for user {user_id}, model {model_config['id']}: {e}. Response: {api_response.text[:200] if 'api_response' in locals() else 'N/A'}")
            except Exception as e:
                response_text = "Непредвиденная ошибка при работе с ИИ. Попробуйте позже."
                logger.error(f"Unexpected Custom API error for user {user_id}, model {model_config['id']}: {traceback.format_exc()}")
    else:
        response_text = "Выбрана модель с неизвестным типом API."
        logger.error(f"Unknown api_type '{model_config.get('api_type')}' for model '{current_model_key}', user {user_id}")

    final_response_text, was_truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"Response for user {user_id} (model {current_model_key}) was truncated.")

    await increment_request_count(user_id, current_model_key)
    user_data_reply = await get_user_data(user_id)
    await update.message.reply_text(
        final_response_text, parse_mode=None,
        reply_markup=generate_menu_keyboard(user_data_reply.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Sent AI response to user {user_id} (model {current_model_key}). Truncated: {was_truncated}. Start: '{final_response_text[:70]}...'")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if PRO_SUBSCRIPTION_LEVEL_KEY not in query.invoice_payload :
        await query.answer(ok=False, error_message="Неверный тип подписки.")
        return
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    if PRO_SUBSCRIPTION_LEVEL_KEY in payment.invoice_payload:
        days = 30 # Можно извлечь из payload если он более сложный
        valid_until = datetime.now().astimezone() + timedelta(days=days)
        bot_data = await get_bot_data()
        user_subscriptions = bot_data.get('user_subscriptions', {})
        user_subscriptions[str(user_id)] = {
            'level': PRO_SUBSCRIPTION_LEVEL_KEY, 'valid_until': valid_until.isoformat(),
            'charge_id': payment.telegram_payment_charge_id, 'amount': payment.total_amount, 'currency': payment.currency
        }
        bot_data['user_subscriptions'] = user_subscriptions
        await set_bot_data(bot_data)
        text = f"🎉 Подписка <b>Профи</b> активирована до <b>{valid_until.strftime('%d.%m.%Y %H:%M %Z')}</b>!"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard('main_menu'))
        logger.info(f"Profi subscription activated for user {user_id} until {valid_until.isoformat()}")
        # Уведомление админу
        # admin_msg = f"User {user_id} ({update.effective_user.full_name or ''} @{update.effective_user.username or ''}) bought Profi sub."
        # if YOUR_ADMIN_ID: await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=admin_msg)
    else:
        logger.warning(f"Success payment with unknown payload: {payment.invoice_payload} from user {user_id}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    update_str = str(update)
    if isinstance(update, Update):
        update_str = json.dumps(update.to_dict(), indent=2, ensure_ascii=False)

    error_message_for_admin = (
        f"Exception handling update:\n"
        f"<pre>update = {html.escape(update_str)}</pre>\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    if YOUR_ADMIN_ID:
        try:
            for chunk in [error_message_for_admin[i:i + MAX_MESSAGE_LENGTH_TELEGRAM] for i in range(0, len(error_message_for_admin), MAX_MESSAGE_LENGTH_TELEGRAM)]:
                await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=chunk, parse_mode=ParseMode.HTML)
        except Exception as e_admin: logger.error(f"Failed to send error to admin: {e_admin}")

    if isinstance(update, Update) and update.effective_message:
        try:
            user_data_err = await get_user_data(update.effective_user.id)
            await update.effective_message.reply_text(
                "Произошла ошибка. Попробуйте /start или свяжитесь с поддержкой.",
                reply_markup=generate_menu_keyboard(user_data_err.get('current_menu', 'main_menu'))
            )
        except Exception as e_user: logger.error(f"Failed to send error reply to user: {e_user}")

async def main():
    app_builder = Application.builder().token(TOKEN)
    # Если хотите использовать context.bot_data для хранения имени бота:
    # app_builder.post_init(post_init_fn) # где post_init_fn асинхронно получает и сохраняет bot.username
    application = app_builder.build()

    # Сохранение имени бота для использования в ссылках
    # (лучше делать это один раз при старте, а не в каждой функции)
    bot_info = await application.bot.get_me()
    application.bot_data['bot_username'] = bot_info.username
    logger.info(f"Bot username: @{application.bot_data['bot_username']}")


    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", open_menu_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command))
    application.add_handler(CommandHandler("bonus", get_news_bonus_info_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_error_handler(error_handler)

    commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Мои лимиты"),
        BotCommand("subscribe", "💎 Подписка Профи"),
        BotCommand("bonus", "🎁 Бонус за канал"),
        BotCommand("help", "❓ Помощь")
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands updated.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

    logger.info("Bot is starting polling...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
        logger.warning("Google Gemini API key не настроен.")
    else:
        try:
            genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API сконфигурирован.")
        except Exception as e: logger.error(f"Ошибка конфигурации Google Gemini API: {e}")

    if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY:
        logger.warning("Custom Gemini Pro API key не настроен.")
    if not CUSTOM_GROK_3_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GROK_3_API_KEY or "sk-" not in CUSTOM_GROK_3_API_KEY:
        logger.warning("Custom Grok 3 API key не настроен.")
    if not PAYMENT_PROVIDER_TOKEN or "YOUR_PAYMENT_PROVIDER_TOKEN" in PAYMENT_PROVIDER_TOKEN:
        logger.warning("PAYMENT_PROVIDER_TOKEN не настроен.")

    asyncio.run(main())
