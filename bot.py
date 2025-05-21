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
from typing import Optional
import uuid
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1 import AsyncClient
from gemini_pro_handler import query_gemini_pro, GEMINI_PRO_CONFIG
from gemini_pro_handler import query_gemini_pro, GEMINI_PRO_CONFIG
from grok_3_handler import query_grok_3, GROK_3_CONFIG

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
# --- НОВЫЙ КЛЮЧ API ДЛЯ GPT-4o mini ---
CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P") # Замените на ваш ключ или переменную окружения
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
YOUR_ADMIN_ID = 489230152

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
DEFAULT_FREE_REQUESTS_GROK_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY = 25
# --- НОВЫЕ ЛИМИТЫ ДЛЯ GPT-4o mini ---
DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY = 25


# --- КАНАЛ НОВОСТЕЙ И БОНУС ---
NEWS_CHANNEL_USERNAME = "@timextech"
NEWS_CHANNEL_LINK = "https://t.me/timextech"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro" # Можете изменить, если бонус будет на другую модель
NEWS_CHANNEL_BONUS_GENERATIONS = 1

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
    "custom_api_gemini_2_5_pro": GEMINI_PRO_CONFIG,  # Ссылка на конфигурацию из модуля
    "custom_api_grok_3": GROK_3_CONFIG,  # Ссылка на конфигурацию из модуля
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
        "cost_category": "custom_api_gpt4o_mini_paid",
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
            if key != "gemini_pro_custom_mode" # Исключаем специальный режим, если он не для прямого выбора
        ],
        "parent": "main_menu",
        "is_submenu": True
    },
    "models_submenu": { # Подменю моделей останется здесь, логика генерации клавиатуры изменится
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
            {"text": "💎 Купить", "action": "show_subscription", "target": "subscribe"}
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
        if os.path.exists("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"): # Убедитесь, что имя файла верное
            cred = credentials.Certificate("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json")
        else:
            raise FileNotFoundError("Файл gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json не найден, и FIREBASE_CREDENTIALS не установлена.")

    try:
        initialize_app(cred)
        logger.info("Firebase успешно инициализирован")
    except ValueError as e:
        if "already exists" in str(e).lower():
            logger.info("Firebase уже инициализирован, пропускаем повторную инициализацию")
        else:
            raise
    except FirebaseError as e:
        logger.error(f"Ошибка инициализации Firebase: {e}")
        raise

    db = firestore.client()
    logger.info("Firestore клиент успешно инициализирован")
except Exception as e:
    logger.error(f"Неизвестная ошибка при инициализации Firebase/Firestore: {e}")
    db = None # Устанавливаем db в None, чтобы избежать ошибок при его использовании, если инициализация не удалась
    # Можно добавить raise e, если Firebase критичен для работы бота

# --- Вспомогательные функции для работы с Firestore ---
async def get_user_data(user_id: int) -> dict:
    if not db: return {}
    doc_ref = db.collection("users").document(str(user_id))
    doc = await asyncio.to_thread(doc_ref.get)
    return doc.to_dict() or {}

async def set_user_data(user_id: int, data: dict):
    if not db: return
    doc_ref = db.collection("users").document(str(user_id))
    await asyncio.to_thread(doc_ref.set, data, merge=True)
    logger.info(f"Updated user data for {user_id}: {data}")

async def get_bot_data() -> dict:
    if not db: return {}
    doc_ref = db.collection("bot_data").document("data")
    doc = await asyncio.to_thread(doc_ref.get)
    return doc.to_dict() or {}

async def set_bot_data(data: dict):
    if not db: return
    doc_ref = db.collection("bot_data").document("data")
    await asyncio.to_thread(doc_ref.set, data, merge=True)
    logger.info(f"Updated bot data: {data}")


async def get_current_mode_details(user_id: int) -> dict:
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id)
    mode_key = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)

    if mode_key not in AI_MODES or mode_key == "grok_3_custom_mode": # grok_3_custom_mode seems to be legacy or a typo
        mode_key = DEFAULT_AI_MODE_KEY
        user_data['current_ai_mode'] = mode_key
        await set_user_data(user_id, user_data)
        logger.info(f"Reset invalid mode to default for user {user_id}")

    # If custom Gemini Pro model is selected, always use its specific mode/prompt
    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    
    # For Grok or GPT-4o mini, or other custom models that don't have a dedicated "mode",
    # use the user's selected general AI_MODE.
    # If custom model selected is NOT Gemini Pro custom, use the standard agent prompt.
    # This ensures that Grok, GPT-4o mini etc., use the "Универсальный" or other selected agent.
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])


async def get_current_model_key(user_id: int) -> str:
    user_data = await get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    # First, try to find an exact match with model_id and api_type if available
    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key

    # If not found or api_type was missing, try to find by model_id only
    # and update api_type in user_data if it was missing or mismatched
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            # If api_type was not stored or differs from the found model's api_type, update it
            if 'selected_api_type' not in user_data or user_data['selected_api_type'] != info.get("api_type"):
                user_data['selected_api_type'] = info.get("api_type")
                await set_user_data(user_id, user_data) # Save the corrected/added api_type
                logger.info(f"Inferred and updated api_type to '{info.get('api_type')}' for model_id '{selected_id}' for user {user_id}")
            return key

    # Fallback to default if no match is found
    logger.warning(f"Could not find key for model_id '{selected_id}' (API type: '{selected_api_type}'). Falling back to default model.")
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    await set_user_data(user_id, {
        'selected_model_id': default_model_config["id"],
        'selected_api_type': default_model_config["api_type"] # Ensure api_type is also set to default
    })
    return DEFAULT_MODEL_KEY


async def get_selected_model_details(user_id: int) -> dict:
    model_key = await get_current_model_key(user_id)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str):
        return str(text), False # Should not happen with AI text, but good for robustness
    if len(text) <= max_length:
        return text, False

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)

    if adjusted_max_length <= 0: # Edge case: suffix is too long
        return text[:max_length-len("...")] + "...", True # Simple truncation

    truncated_text = text[:adjusted_max_length]

    # Try to cut at meaningful points, from most to least preferred
    possible_cut_points = []
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']: # Prefer double newline, then sentence end, then single newline, then space
        pos = truncated_text.rfind(sep)
        if pos != -1:
            # For separators like '. ', we want to cut *after* the separator
            actual_pos = pos + (len(sep) if sep != ' ' else 0) # if space, cut before it by not adding len
            if actual_pos > 0: # Ensure we don't take an empty string if separator is at the beginning
                possible_cut_points.append(actual_pos)

    if possible_cut_points:
        cut_at = max(possible_cut_points) # Choose the latest possible meaningful cut point
        # Ensure the cut point is not too early (e.g., less than 30% of the allowed text)
        # This prevents cutting off too much if a separator is found very early.
        if cut_at > adjusted_max_length * 0.3:
            return text[:cut_at].strip() + suffix, True

    # If no good cut point found or the best one is too early, just cut at adjusted_max_length
    return text[:adjusted_max_length].strip() + suffix, True


async def get_user_actual_limit_for_model(user_id: int, model_key: str) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config:
        return 0 # Model not found

    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})

    current_sub_level = None
    if user_subscription_details.get('valid_until'):
        try:
            # Ensure consistent timezone awareness for comparison
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if valid_until_dt.tzinfo is None: # If stored as naive, assume UTC or local as consistently done elsewhere
                 # For safety, let's assume it needs to be made aware if comparison is with aware datetime.now()
                 # However, date() comparison below handles this by ignoring time and tz for daily checks.
                 pass
            # Compare dates directly to avoid timezone issues for "valid until end of day"
            if datetime.now().date() <= valid_until_dt.date():
                current_sub_level = user_subscription_details.get('level')
        except Exception as e:
            logger.error(f"Error parsing valid_until for user {user_id}: {user_subscription_details.get('valid_until')} - {e}")
            pass # Invalid date format or other error, treat as no valid subscription

    limit_type = model_config.get("limit_type")

    if limit_type == "daily_free":
        return model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY:
            return model_config.get("subscription_daily_limit", 0)
        else:
            return model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro": # Covers custom pro and now gpt-4o mini as well
        base_limit = 0
        if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY:
            base_limit = model_config.get("subscription_daily_limit", 0)
        else:
            base_limit = model_config.get("limit_if_no_subscription", 0)
        
        # Add news bonus if applicable and user is NOT a Profi subscriber for this model type
        # (assuming bonus is for non-subscribers or a general bonus)
        user_data = await get_user_data(user_id)
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and user_data.get('claimed_news_bonus', False):
            # Check if subscription already grants access to this model category beyond bonus
            # This logic might need refinement based on how bonus interacts with subscriptions.
            # For now, let's assume bonus adds on top if not Profi, or if Profi limit is base_limit.
            # If Profi has a high limit, bonus might be less relevant or handled differently.
            # Current logic: adds bonus uses on top of the calculated base_limit if bonus is for this model
            bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
            # Only add bonus if it's for this specific model and user has it
            # The condition `not is_profi_subscriber` was in `check_and_log_request_attempt` for bonus use.
            # Here, we calculate total limit. If a profi subscriber has a limit for custom_pro,
            # and the bonus model is custom_pro, does the bonus still add?
            # Let's assume bonus is primarily for free users or a distinct boost.
            # If a user is Profi, their Profi limit for that model category should apply.
            # The bonus consumption logic handles if it's used instead of daily count.
            # Here we just calculate the MAX possible.
            # A simpler way: get_user_actual_limit should reflect subscription. Bonus is a "free pass" that doesn't count against this limit.
            # So, the limit shown should be the subscription/free limit. The `check_and_log` decides if bonus can be used.
            # Let's stick to the existing interpretation: bonus increases the *effective* limit for the bonus model.
            if bonus_uses_left > 0:
                 return base_limit + bonus_uses_left # Bonus adds to the daily limit for the bonus model
        return base_limit
    elif not model_config.get("is_limited", False): # Unlimited models
        return float('inf')
    else: # Default for any other unhandled limited cases
        return 0


async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_config or not model_config.get("is_limited"):
        return True, "", 0 # Not limited, proceed

    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id) # Get user_data for bonus check

    # Check for Profi subscription status
    is_profi_subscriber = False
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    if model_config.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro"]:
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and \
           user_subscription_details.get('valid_until'):
            try:
                valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
                if datetime.now().date() <= valid_until_dt.date():
                    is_profi_subscriber = True
            except Exception:
                pass # Invalid date, not a subscriber

    # Bonus check: if model is the bonus model, user is NOT a profi subscriber, and has bonus uses
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} attempting to use NEWS_CHANNEL_BONUS for {model_key}. Bonus available.")
        return True, "bonus_available", 0 # Allow use of bonus, count will be handled by increment_request_count

    # Regular limit check
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': '', 'count': 0})

    if model_daily_usage['date'] != today_str: # Reset daily count if new day
        model_daily_usage = {'date': today_str, 'count': 0}
        # No need to save here, will be saved if count increments or if a limit is hit.
        # Or, save immediately to reflect reset, but increment_request_count will also save.
        # For consistency, let increment_request_count handle the save of the reset count on first use of the day.

    current_daily_count = model_daily_usage['count']
    # Actual daily limit calculation should NOT include bonus here, as bonus is checked separately above.
    # get_user_actual_limit_for_model_for_counting will be a variant or adjustment.
    # For now, let's assume actual_daily_limit from the function already handles how sub/free limits are defined.
    # The bonus check above bypasses this count if bonus is used.
    # If bonus is NOT used, then we check against the standard daily limit.

    # Recalculate actual_daily_limit *without* bonus for this specific check,
    # as the bonus path is handled separately.
    # To do this cleanly, get_user_actual_limit_for_model might need a flag, or we adjust here.
    # For now, let's use a simplified view: if bonus was not applicable/used, check against normal daily limit.
    # The `get_user_actual_limit_for_model` might return a limit inclusive of bonus if that model is bonus model.
    # This can be tricky. Let's simplify:
    # 1. If bonus is available and used (checked above), allow.
    # 2. If not, check against daily usage limit.
    # The `actual_daily_limit` for the message should reflect the true limit (potentially with bonus).
    
    actual_daily_limit_for_display = await get_user_actual_limit_for_model(user_id, model_key) # Includes bonus for display
    
    # The limit to check against should be the one without bonus if bonus is not being consumed by this request.
    # This logic is getting complicated. Let's refine:
    # `get_user_actual_limit_for_model` returns the total potential (sub + bonus if applicable).
    # If `current_daily_count` (which tracks non-bonus uses mostly) >= `actual_daily_limit_for_display`,
    # then they are over, unless the bonus logic above specifically allowed this request.

    if current_daily_count >= actual_daily_limit_for_display:
        # This condition implies that even with potential bonus added to limit, they are over.
        # Or, if the model is not the bonus model, this is a straightforward limit check.
        message_parts = [
            f"Вы достигли дневного лимита ({current_daily_count}/{actual_daily_limit_for_display}) для модели {model_config['name']}."
        ]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not user_data.get('claimed_news_bonus', False):
                message_parts.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонусной генерации ({NEWS_CHANNEL_BONUS_GENERATIONS} для {AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")})!')
            elif user_data.get('news_bonus_uses_left', 0) == 0: # Claimed but used up
                message_parts.append(f"ℹ️ Бонус за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал</a> уже использован.")
        
        if not is_profi_subscriber : # General message for non-subscribers or if limit still hit with subscription
             message_parts.append("Попробуйте снова завтра или рассмотрите возможность <a href='https://t.me/gemini_oracle_bot?start=subscribe'>приобретения подписки</a> для увеличения лимитов (меню «Подписка»).")


        # Ensure data is saved if it was modified (e.g., date reset)
        if model_daily_usage['date'] == today_str and user_model_counts.get(model_key) != model_daily_usage:
             user_model_counts[model_key] = model_daily_usage
             all_daily_counts[str(user_id)] = user_model_counts
             bot_data['all_user_daily_counts'] = all_daily_counts
             await set_bot_data(bot_data)

        return False, "\n".join(message_parts), current_daily_count

    # If we reach here, user is within their standard daily limits (or bonus was used)
    # Ensure data is saved if it was modified (e.g., date reset)
    if model_daily_usage['date'] == today_str and user_model_counts.get(model_key) != model_daily_usage:
        user_model_counts[model_key] = model_daily_usage
        all_daily_counts[str(user_id)] = user_model_counts
        bot_data['all_user_daily_counts'] = all_daily_counts
        await set_bot_data(bot_data)
        
    return True, "", current_daily_count


async def increment_request_count(user_id: int, model_key: str):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return # Not limited, no need to count

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()

    # Check Profi subscription status
    is_profi_subscriber = False
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and \
       user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now().date() <= valid_until_dt.date():
                is_profi_subscriber = True
        except Exception:
            pass

    # Handle NEWS_CHANNEL_BONUS consumption
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False):
        news_bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        if news_bonus_uses_left > 0:
            user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
            await set_user_data(user_id, user_data)
            logger.info(f"User {user_id} consumed one NEWS_CHANNEL_BONUS use for {model_key}. Remaining: {user_data['news_bonus_uses_left']}")
            # Bonus used, no need to increment daily count for this request against the standard limit
            return 
            # If bonus was just exhausted, the next request will hit normal limits.

    # Increment standard daily count if bonus was not used for this request
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0}) # Default to today, 0 count

    if model_daily_usage['date'] != today_str: # If new day, reset count
        model_daily_usage = {'date': today_str, 'count': 0}
    
    model_daily_usage['count'] += 1
    user_model_counts[model_key] = model_daily_usage
    all_daily_counts[str(user_id)] = user_model_counts
    bot_data['all_user_daily_counts'] = all_daily_counts # Ensure bot_data is updated with new counts
    await set_bot_data(bot_data)
    logger.info(f"User {user_id} daily count for {model_key} incremented to {model_daily_usage['count']}")


def is_menu_button_text(text: str) -> bool:
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons:
        return True
    for menu_key, menu_data in MENU_STRUCTURE.items(): # Use menu_data consistently
        for item in menu_data["items"]:
            if item["text"] == text:
                return True
    return False

async def try_delete_user_message(update: Update, user_id: int):
    if not update or not update.message: # Guard against calls without a message context
        return

    chat_id = update.effective_chat.id
    user_data = await get_user_data(user_id)
    user_command_message = user_data.get('user_command_message', {})
    message_id_to_delete = user_command_message.get('message_id')
    timestamp_str = user_command_message.get('timestamp')

    if not message_id_to_delete or not timestamp_str:
        return

    try:
        msg_time = datetime.fromisoformat(timestamp_str)
        # Ensure msg_time is offset-aware if comparing with offset-aware datetime.now()
        # For simplicity, if it's naive, assume it's in the same local context or UTC as elsewhere.
        # The 48-hour check is robust enough for minor tz drifts.
        if datetime.now(msg_time.tzinfo if msg_time.tzinfo else None) - msg_time > timedelta(hours=48): # Make comparison tz-aware if needed
            logger.info(f"User message {message_id_to_delete} is older than 48 hours, not deleting, clearing record.")
            user_data.pop('user_command_message', None)
            await set_user_data(user_id, user_data)
            return
    except ValueError: # Invalid timestamp format
        logger.warning(f"Invalid timestamp format for user message {message_id_to_delete}, clearing record.")
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)
        return

    try:
        await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_delete)
        logger.info(f"Successfully deleted user message {message_id_to_delete} in chat {chat_id}")
    except telegram.error.BadRequest as e:
        # Common errors: "Message to delete not found" or "Message can't be deleted"
        logger.warning(f"Failed to delete user message {message_id_to_delete} in chat {chat_id}: {e}")
    finally:
        # Always clear the record after attempting deletion (or if it's too old)
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)


# --- Функции для меню на клавиатуре ---
def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        # Fallback to main menu if the requested menu_key is somehow invalid
        logger.warning(f"generate_menu_keyboard called with invalid menu_key: {menu_key}. Falling back to main_menu.")
        menu = MENU_STRUCTURE.get("main_menu")
        if not menu: # Should not happen if main_menu is defined
             return ReplyKeyboardMarkup([[]], resize_keyboard=True, one_time_keyboard=False)


    keyboard_rows = []
    menu_items = menu["items"]

    # --- ИЗМЕНЕНИЕ ДЛЯ ОТОБРАЖЕНИЯ МОДЕЛЕЙ В ДВЕ КОЛОНКИ ---
    if menu_key == "main_menu" or menu_key == "models_submenu": # Apply 2-column layout to main_menu and models_submenu
        for i in range(0, len(menu_items), 2):
            row = [KeyboardButton(menu_items[j]["text"]) for j in range(i, min(i + 2, len(menu_items)))]
            keyboard_rows.append(row)
    else: # Default: one button per row for other submenus
        for item in menu_items:
            keyboard_rows.append([KeyboardButton(item["text"])])
    
    # Add navigation buttons (Back, Main Menu) for submenus
    if menu.get("is_submenu", False): # Check if it's a submenu
        nav_row = []
        if menu.get("parent"): # If parent is defined, add "Back" button
            nav_row.append(KeyboardButton("⬅️ Назад"))
        nav_row.append(KeyboardButton("🏠 Главное меню")) # Always add "Main Menu" to submenus
        keyboard_rows.append(nav_row)
    
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)


async def show_menu(update: Update, user_id: int, menu_key: str):
    menu_data = MENU_STRUCTURE.get(menu_key) # Use menu_data to avoid conflict
    if not menu_data:
        logger.error(f"Menu key '{menu_key}' not found in MENU_STRUCTURE. Defaulting to main_menu for user {user_id}.")
        await update.message.reply_text(
            "Ошибка: Меню не найдено. Пожалуйста, используйте /start.",
            reply_markup=generate_menu_keyboard("main_menu") # Show main menu as a fallback
        )
        # Update user's current menu to main_menu to prevent them getting stuck
        user_data = await get_user_data(user_id)
        user_data['current_menu'] = 'main_menu'
        await set_user_data(user_id, user_data)
        return

    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key # Save current menu state
    await set_user_data(user_id, user_data)
    
    text_to_send = menu_data["title"]
    reply_keyboard_markup = generate_menu_keyboard(menu_key) # Use reply_keyboard_markup
    
    await update.message.reply_text(
        text_to_send,
        reply_markup=reply_keyboard_markup,
        parse_mode=None, # Avoid ParseMode.HTML if title doesn't need it, or set explicitly if it does
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} shown menu '{menu_key}': {text_to_send}")


# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id) # Load existing data first

    # Set defaults only if they are not already present
    user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    user_data.setdefault('current_menu', 'main_menu')
    
    default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    user_data.setdefault('selected_model_id', default_model_conf["id"])
    user_data.setdefault('selected_api_type', default_model_conf["api_type"]) # Also set default api_type
    
    # Store user's command message for potential deletion
    if update.message: # Ensure message exists
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat() # Store as ISO format string
        }
    
    await set_user_data(user_id, user_data) # Save all changes once
    
    # await try_delete_user_message(update, user_id) # Call this *after* storing new message_id if needed, or manage carefully.
    # For /start, usually we don't delete the /start command itself immediately.

    current_model_key_val = await get_current_model_key(user_id) # Shadowing outer scope variable
    mode_details = await get_current_mode_details(user_id)
    current_mode_name_val = mode_details['name'] if mode_details else "Неизвестный"
    
    model_details_val = AVAILABLE_TEXT_MODELS.get(current_model_key_val)
    current_model_name_val = model_details_val['name'] if model_details_val else "Неизвестная"


    greeting = (
        f"👋 Привет, {update.effective_user.first_name}!\n"
        f"Я твой ИИ-бот на базе различных нейросетей.\n\n"
        f"🧠 Текущий агент: <b>{current_mode_name_val}</b>\n"
        f"⚙️ Текущая модель: <b>{current_model_name_val}</b>\n\n"
        "💬 Задавай вопросы или используй клавиатурное меню ниже!"
    )
    await update.message.reply_text(
        greeting,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} started the bot. Sent start message.")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id) # Attempt to delete the /menu command
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
    await show_limits(update, user_id) # show_limits now takes update and user_id


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
    await show_subscription(update, user_id) # show_subscription now takes update and user_id


async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # user_data already loaded and processed in claim_news_bonus_logic
    # Storing and deleting message can be done here or at the start of claim_news_bonus_logic
    _user_data = await get_user_data(user_id) # Use different var name to avoid conflict if not used
    if update.message:
        _user_data['user_command_message'] = { # Storing for deletion
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, _user_data)
        # Deletion will be handled by claim_news_bonus_logic after it processes this message
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
    await show_help(update, user_id) # show_help now takes update and user_id

# Modified show_limits to accept update and user_id
async def show_limits(update: Update, user_id: int): # Added update parameter
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id) # Crucial for bonus info
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    display_sub_level = "Бесплатный доступ"
    subscription_active = False
    valid_until_date_str = ""

    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and \
       user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            valid_until_date_str = valid_until_dt.strftime('%Y-%m-%d')
            if datetime.now().date() <= valid_until_dt.date(): # Compare dates
                display_sub_level = f"Подписка Профи (до {valid_until_date_str})"
                subscription_active = True
            else:
                display_sub_level = f"Подписка Профи (истекла {valid_until_date_str})"
        except Exception as e:
            logger.error(f"Error parsing subscription date for user {user_id}: {e}")
            display_sub_level = "Подписка Профи (ошибка даты)"

    usage_text_parts = [
        "<b>📊 Ваши лимиты запросов</b>",
        f"Текущий статус: <b>{display_sub_level}</b>",
        "" # Empty line for spacing
    ]

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_user_daily_counts.get(str(user_id), {})

    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            
            actual_l = await get_user_actual_limit_for_model(user_id, model_k)
            
            bonus_note = ""
            # Specifically for the bonus model, if bonus is active and adds to limit
            if model_k == NEWS_CHANNEL_BONUS_MODEL_KEY and \
               not subscription_active and \
               user_data.get('claimed_news_bonus', False) and \
               user_data.get('news_bonus_uses_left', 0) > 0:
                # The limit from get_user_actual_limit_for_model might already include bonus.
                # This note can clarify if the displayed limit is higher due to a bonus.
                bonus_note = f" (включая {user_data['news_bonus_uses_left']} бонусных)"


            limit_str = f"<b>{current_c_display}/{actual_l if actual_l != float('inf') else '∞'}</b>"
            usage_text_parts.append(f"▫️ {model_c['name']}: {limit_str}{bonus_note}")

    usage_text_parts.append("") # Empty line

    # News channel bonus information
    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle": # Check if configured
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
        bonus_info_line = ""
        if not user_data.get('claimed_news_bonus', False):
            bonus_info_line = (f'🎁 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал новостей</a> и получите '
                               f"<b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусных генераций для модели {bonus_model_name} (через меню «Бонус»)! ")
        elif (bonus_uses_left := user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info_line = (f"✅ У вас активно <b>{bonus_uses_left}</b> бонусных генераций для {bonus_model_name} "
                               f'(из <a href="{NEWS_CHANNEL_LINK}">канала новостей</a>).')
        else: # Claimed but bonus uses are zero
            bonus_info_line = (f"ℹ️ Бонусные генерации для {bonus_model_name} "
                               f'(из <a href="{NEWS_CHANNEL_LINK}">канала новостей</a>) были использованы.')
        usage_text_parts.append(bonus_info_line)
        usage_text_parts.append("")


    if not subscription_active:
        usage_text_parts.append("Хотите больше лимитов и доступ к продвинутым моделям? "
                                "Посетите меню «Подписка» или введите /subscribe.")

    final_usage_text = "\n".join(usage_text_parts)
    
    # Determine current menu for correct "Back" button behavior, default to 'limits_submenu' if not found
    current_menu_context = user_data.get('current_menu', 'limits_submenu')
    if current_menu_context not in MENU_STRUCTURE: # Ensure it's a valid menu
        current_menu_context = 'limits_submenu'

    reply_markup = generate_menu_keyboard(current_menu_context)

    await update.message.reply_text( # Ensure it's update.message.reply_text
        final_usage_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent usage/limits information to user {user_id}.")


async def claim_news_bonus_logic(update: Update, user_id: int):
    user = update.effective_user
    # chat_id = update.effective_chat.id # Not needed directly unless sending message to a different chat

    user_data = await get_user_data(user_id)
    # Delete the user's command/button press message for "Получить бонус"
    if update.message: # Ensure message object exists
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data) # Save before trying to delete
        await try_delete_user_message(update, user_id) # Attempt deletion

    # Determine the menu to return to (current or main)
    # Fallback to 'bonus_submenu' or 'main_menu' if user_data['current_menu'] is not ideal
    parent_menu_key = user_data.get('current_menu', 'bonus_submenu')
    if parent_menu_key not in MENU_STRUCTURE or not MENU_STRUCTURE[parent_menu_key].get("parent"):
        parent_menu_key = MENU_STRUCTURE.get(parent_menu_key, {}).get("parent", "main_menu")


    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        text_response = "К сожалению, функция получения бонуса за подписку на канал сейчас не настроена."
        await update.message.reply_text(
            text_response,
            reply_markup=generate_menu_keyboard(parent_menu_key),
            parse_mode=None,
            disable_web_page_preview=True
        )
        logger.info(f"Bonus feature not configured. Message sent to user {user_id}.")
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        text_response = "Ошибка: Модель, для которой предназначен бонус, не найдена в конфигурации. Обратитесь к администратору."
        await update.message.reply_text(
            text_response,
            reply_markup=generate_menu_keyboard(parent_menu_key),
            parse_mode=None,
            disable_web_page_preview=True
        )
        logger.error(f"Bonus model key '{NEWS_CHANNEL_BONUS_MODEL_KEY}' not found in AVAILABLE_TEXT_MODELS.")
        return
    
    bonus_model_name = bonus_model_config['name']

    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        if uses_left > 0:
            reply_text_response = (f'Вы уже активировали бонус за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>. '
                                   f'У вас осталось <b>{uses_left}</b> бонусных генераций для модели {bonus_model_name}.')
        else:
            reply_text_response = (f'Бонус за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a> для модели {bonus_model_name} '
                                   'уже был использован.')
        await update.message.reply_text(
            reply_text_response,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(parent_menu_key), # Or 'main_menu'
            disable_web_page_preview=True
        )
        logger.info(f"User {user_id} already claimed bonus or used it up. Status sent.")
        return

    try:
        # Ensure NEWS_CHANNEL_USERNAME starts with "@" if it's a public channel username
        channel_to_check = NEWS_CHANNEL_USERNAME if NEWS_CHANNEL_USERNAME.startswith('@') else f"@{NEWS_CHANNEL_USERNAME}"
        
        member_status_obj = await update.get_bot().get_chat_member(chat_id=channel_to_check, user_id=user.id) # Use updated var name
        
        if member_status_obj.status in ['member', 'administrator', 'creator']:
            user_data['claimed_news_bonus'] = True
            user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await set_user_data(user_id, user_data)
            
            success_text_response = (f'🎉 Спасибо за подписку на <a href="{NEWS_CHANNEL_LINK}">канал {channel_to_check}</a>! '
                                     f'Вам начислено <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусных генераций для модели {bonus_model_name}.')
            await update.message.reply_text(
                success_text_response,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard('main_menu'), # Send to main menu after successful claim
                disable_web_page_preview=True
            )
            logger.info(f"User {user_id} successfully claimed news channel bonus for {bonus_model_name}.")
        else: # User is not a member
            fail_text_response = (f'Для получения бонуса, пожалуйста, сначала подпишитесь на наш <a href="{NEWS_CHANNEL_LINK}">новостной канал {channel_to_check}</a>, '
                                  'а затем нажмите кнопку «🎁 Получить» еще раз в меню «Бонус».')
            # Inline keyboard to directly go to the channel
            inline_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📢 Перейти в канал {channel_to_check}", url=NEWS_CHANNEL_LINK)
            ]])
            await update.message.reply_text(
                fail_text_response,
                parse_mode=ParseMode.HTML,
                reply_markup=inline_keyboard, # Show inline button to join channel
                disable_web_page_preview=True # True because we use a link in text.
            )
            logger.info(f"User {user_id} not subscribed to {channel_to_check}. Bonus not granted.")
            
    except telegram.error.BadRequest as e:
        # Handle cases like "Chat not found" or "User not found" (less likely for user.id)
        # This might happen if NEWS_CHANNEL_USERNAME is incorrect or bot isn't admin in a private channel (if applicable)
        logger.error(f"Telegram API BadRequest when checking channel membership for {NEWS_CHANNEL_USERNAME}: {e}")
        error_message_to_user = (f'Не удалось проверить вашу подписку на <a href="{NEWS_CHANNEL_LINK}">канал {NEWS_CHANNEL_USERNAME}</a>. '
                                 'Убедитесь, что вы подписаны, и попробуйте снова немного позже. '
                                 'Возможно, канал указан неверно или является приватным.')
        inline_keyboard_err = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📢 Попробовать перейти в {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
        ]])
        await update.message.reply_text(
            error_message_to_user,
            parse_mode=ParseMode.HTML,
            reply_markup=inline_keyboard_err, # Provide link again
            disable_web_page_preview=True
        )
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"Unexpected error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла непредвиденная ошибка при попытке получения бонуса. Пожалуйста, попробуйте позже.",
            reply_markup=generate_menu_keyboard(parent_menu_key)
        )

# Modified show_subscription to accept update and user_id
async def show_subscription(update: Update, user_id: int): # Added update parameter
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id) # Load user_data to get current_menu
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    sub_text_parts = ["<b>💎 Информация о Подписке Профи</b>"]
    is_active_profi = False # More specific variable name

    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and \
       user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            valid_until_date_str_display = valid_until_dt.strftime('%d.%m.%Y') # More readable date
            
            if datetime.now().date() <= valid_until_dt.date():
                sub_text_parts.append(f"\n✅ Ваша подписка <b>Профи</b> активна до <b>{valid_until_date_str_display}</b>.")
                sub_text_parts.append("   Вам доступны расширенные лимиты и все модели ИИ.")
                is_active_profi = True
            else:
                sub_text_parts.append(f"\n⚠️ Ваша подписка <b>Профи</b> истекла <b>{valid_until_date_str_display}</b>.")
        except Exception as e:
            logger.error(f"Error parsing subscription 'valid_until' for user {user_id}: {e}")
            sub_text_parts.append("\n⚠️ Не удалось определить статус вашей подписки из-за ошибки в дате.")

    if not is_active_profi:
        sub_text_parts.append("\nС подпиской <b>Профи</b> вы получаете:")
        sub_text_parts.append("▫️ Значительно увеличенные дневные лимиты на все модели ИИ.")
        sub_text_parts.append(f"▫️ Приоритетный доступ к модели {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}.")
        sub_text_parts.append(f"▫️ Расширенный доступ к модели {AVAILABLE_TEXT_MODELS['custom_api_grok_3']['name']}.")
        if "custom_api_gpt_4o_mini" in AVAILABLE_TEXT_MODELS: # If GPT-4o mini is defined
            sub_text_parts.append(f"▫️ Расширенный доступ к модели {AVAILABLE_TEXT_MODELS['custom_api_gpt_4o_mini']['name']}.")
        sub_text_parts.append("▫️ Поддержку развития бота и добавления новых функций.")
        sub_text_parts.append("\nДля оформления или продления подписки, пожалуйста, используйте команду /subscribe.")
        # To initiate payment, you would typically have a command like /pay or a button that triggers an invoice.
        # The /subscribe command here is informational.
        # If you want a direct payment button:
        # sub_text_parts.append("\nНажмите кнопку ниже для покупки или используйте /subscribe для деталей.")
        # (Then add an InlineKeyboardButton that sends an invoice when ready)

    final_sub_text = "\n".join(sub_text_parts)
    
    current_menu_for_reply = user_data.get('current_menu', 'subscription_submenu')
    if current_menu_for_reply not in MENU_STRUCTURE:
        current_menu_for_reply = 'subscription_submenu' # Default if invalid

    # Add button to initiate payment if not active
    inline_buttons = []
    if not is_active_profi and PAYMENT_PROVIDER_TOKEN and PAYMENT_PROVIDER_TOKEN != "YOUR_PAYMENT_PROVIDER_TOKEN":
        # Example: invoice_payload = f"subscribe_profi_30days_{user_id}_{uuid.uuid4()}"
        # This should ideally be handled by a dedicated command that sends an invoice.
        # For now, just text. If you have /pay command, mention it.
        # To make this button work, it should call a command that sends an invoice.
        # For simplicity, let's assume /subscribe is the main command for this info.
        # If you want to add a buy button here that triggers an invoice:
        # inline_buttons.append([InlineKeyboardButton("💳 Оформить Подписку Профи (30 дней - XX RUB)", callback_data="buy_pro_30d")])
        pass # No direct buy button here, assuming /subscribe command leads to payment steps

    reply_markup_obj = generate_menu_keyboard(current_menu_for_reply) # Keyboard menu
    if inline_buttons: # If you add inline buttons for payment
        reply_markup_obj = InlineKeyboardMarkup(inline_buttons)


    await update.message.reply_text( # Ensure it's update.message.reply_text
        final_sub_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup_obj, # Use the generated markup
        disable_web_page_preview=True
    )
    logger.info(f"Sent subscription information to user {user_id}.")

# Modified show_help to accept update and user_id
async def show_help(update: Update, user_id: int): # Added update parameter
    user_data = await get_user_data(user_id) # Load user_data for current_menu

    # Attempt to delete the user's message (e.g., "/help" command or "❓ Помощь" button)
    # This part was missing user_data loading before trying to use it for deletion.
    if update.message: # Ensure message exists
        # Storing the new command message_id to user_data for deletion
        user_data_for_delete = await get_user_data(user_id) # Fresh get for this operation
        user_data_for_delete['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data_for_delete)
        await try_delete_user_message(update, user_id) # Now try to delete it

    help_text_message = (
        "<b>❓ Справочная информация</b>\n\n"
        "Я — ваш многофункциональный ИИ-ассистент! Вот основные возможности:\n"
        "▫️ <b>Взаимодействие с ИИ</b>: Задавайте вопросы и получайте развернутые ответы. Бот использует различные нейросетевые модели.\n"
        "▫️ <b>Агенты ИИ</b>: Выбирайте специализированных агентов (например, 'Универсальный', 'Творческий', 'Аналитик') для более точных ответов в зависимости от вашей задачи. Смена агента доступна в меню «🤖 Агенты ИИ».\n"
        "▫️ <b>Модели ИИ</b>: Переключайтесь между доступными ИИ-моделями (например, Gemini, Grok, GPT). Каждая модель имеет свои сильные стороны и лимиты использования. Смена модели — в меню «⚙️ Модели ИИ».\n"
        "▫️ <b>Лимиты</b>: У каждой модели есть дневные лимиты на бесплатное использование. Подписчики получают расширенные лимиты. Проверить свои текущие лимиты можно в меню «📊 Лимиты» или командой /usage.\n"
        "▫️ <b>Бонус</b>: Подпишитесь на наш новостной канал (ссылка в меню «🎁 Бонус») и получите дополнительные бесплатные генерации для одной из моделей!\n"
        "▫️ <b>Подписка Профи</b>: Оформите подписку для снятия или значительного увеличения лимитов, а также для доступа к самым продвинутым моделям. Информация — в меню «💎 Подписка» или по команде /subscribe.\n\n"
        "<b>Основные команды:</b>\n"
        "▫️ /start — Перезапустить бота и показать приветственное сообщение.\n"
        "▫️ /menu — Открыть главное клавиатурное меню.\n"
        "▫️ /usage — Показать ваши текущие лимиты использования моделей.\n"
        "▫️ /subscribe — Информация о Подписке Профи и ее преимуществах.\n"
        "▫️ /bonus — Инструкции по получению бонуса за подписку на новостной канал.\n"
        "▫️ /help — Показать эту справку.\n\n"
        "Если у вас возникли проблемы или вопросы, обращайтесь к администратору." # Add contact if available
    )
    
    current_menu_for_help_reply = user_data.get('current_menu', 'help_submenu')
    if current_menu_for_help_reply not in MENU_STRUCTURE:
        current_menu_for_help_reply = 'help_submenu'


    await update.message.reply_text( # Ensure it's update.message.reply_text
        help_text_message,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu_for_help_reply), # Use the correct menu context
        disable_web_page_preview=True
    )
    logger.info(f"Sent help information to user {user_id}.")


async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: # Guard clause
        return

    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    
    # If it's not a recognized menu button text, let handle_text process it.
    if not is_menu_button_text(button_text):
        logger.debug(f"Text '{button_text}' from user {user_id} is not a menu button, passing to handle_text.")
        # Explicitly return or ensure this handler doesn't consume the update if not a menu button
        # The group priority in add_handler should manage this, but being explicit can be safer.
        # For now, assume if it's not a menu button, it will be picked up by handle_text.
        # However, the current filter for handle_text is (filters.TEXT & ~filters.COMMAND)
        # and menu_button_handler has the same. We need to ensure this function *only* processes menu buttons.
        # The `is_menu_button_text` check at the start of this function is meant to do that.
        # If it passes this check, it means it *is* a menu button text.
        return # Let `handle_text` catch it if it's not a menu button handled by logic below.

    user_data = await get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', 'main_menu') # Default to main_menu
    
    # Store and attempt to delete the user's message (the button text they sent)
    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data) # Save message_id before attempting delete
    await try_delete_user_message(update, user_id)

    logger.info(f"User {user_id} pressed menu button '{button_text}' while in menu '{current_menu_key}'.")

    # Handle navigation buttons first
    if button_text == "⬅️ Назад":
        parent_menu_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent")
        await show_menu(update, user_id, parent_menu_key if parent_menu_key else "main_menu")
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu")
        return

    # Find the action associated with the button text
    action_item = None
    # Search in the current menu first for efficiency
    current_menu_config = MENU_STRUCTURE.get(current_menu_key)
    if current_menu_config:
        for item in current_menu_config["items"]:
            if item["text"] == button_text:
                action_item = item
                break
    
    # If not found in current menu (e.g., user somehow sent button text from another menu context), search all menus
    if not action_item:
        for menu_conf in MENU_STRUCTURE.values(): # Iterate through all menu configurations
            for item in menu_conf["items"]:
                if item["text"] == button_text:
                    action_item = item
                    # If found in a different menu, potentially log this or update user's current_menu context
                    logger.warning(f"Button '{button_text}' was found in a menu different from user's current_menu ('{current_menu_key}'). User might be in an inconsistent state or message is old.")
                    # For robustness, could set user_data['current_menu'] to the menu where button was found, if that menu is a parent of the action.
                    break
            if action_item:
                break
    
    if not action_item:
        logger.warning(f"Button text '{button_text}' from user {user_id} not matched to any action in any menu. Current menu was '{current_menu_key}'.")
        await update.message.reply_text(
            "Неизвестная команда. Пожалуйста, используйте кнопки на клавиатуре или введите /menu.",
            reply_markup=generate_menu_keyboard(current_menu_key) # Show current menu again
        )
        return

    action = action_item["action"]
    target = action_item["target"]
    logger.info(f"Button '{button_text}' for user {user_id} triggers action '{action}' with target '{target}'.")

    # Execute action
    if action == "submenu":
        await show_menu(update, user_id, target)
    elif action == "set_agent":
        return_menu_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu") # Menu to return to
        if target in AI_MODES and target != "gemini_pro_custom_mode": # Assuming this mode is special
            user_data['current_ai_mode'] = target # Update user's selected AI mode
            await set_user_data(user_id, user_data)
            agent_details = AI_MODES[target]
            response_message_text = f"🤖 Агент ИИ изменен на: <b>{agent_details['name']}</b>.\n\n{agent_details.get('welcome', 'Готов к вашим запросам!')}"
        elif target == "gemini_pro_custom_mode": # Handle selection of the special mode if needed
            # This mode is usually set automatically when custom_api_gemini_2_5_pro model is chosen
            response_message_text = "Агент для модели Gemini Pro (API) устанавливается автоматически при выборе соответствующей модели."
        else:
            response_message_text = "⚠️ Ошибка: Выбранный агент ИИ не найден."
            logger.error(f"Attempt to set invalid AI agent '{target}' by user {user_id}.")
        
        await update.message.reply_text(
            response_message_text, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu_key), # Show parent menu
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu_key # Update user's current menu to the one displayed
        await set_user_data(user_id, user_data)

    elif action == "set_model":
        return_menu_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu")
        if target in AVAILABLE_TEXT_MODELS:
            model_config_data = AVAILABLE_TEXT_MODELS[target]
            user_data.update({
                'selected_model_id': model_config_data["id"],
                'selected_api_type': model_config_data["api_type"]
            })
            
            # If a model like Grok or GPT-4o mini is chosen, and they don't have a specific "mode"
            # like "gemini_pro_custom_mode", ensure the current_ai_mode is a general one.
            if target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"]: # Add other similar models here
                if user_data.get('current_ai_mode') == "gemini_pro_custom_mode": # If previous was specific Gemini Pro mode
                    user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY # Reset to a general agent
                    logger.info(f"Reset AI mode to default for user {user_id} due to model change to {target}")

            await set_user_data(user_id, user_data)
            
            # Display current usage for the newly selected model
            bot_data = await get_bot_data()
            today_date_str = datetime.now().strftime("%Y-%m-%d") # Use different var name
            user_model_counts_data = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage_data = user_model_counts_data.get(target, {'date': '', 'count': 0})
            current_usage_display = model_daily_usage_data['count'] if model_daily_usage_data['date'] == today_date_str else 0
            actual_limit_val = await get_user_actual_limit_for_model(user_id, target)
            limit_str_display = f"{current_usage_display}/{actual_limit_val if actual_limit_val != float('inf') else '∞'}"
            
            response_message_text = (f"⚙️ Модель ИИ изменена на: <b>{model_config_data['name']}</b>.\n"
                                     f"Лимит использования на сегодня: {limit_str_display}.")
        else:
            response_message_text = "⚠️ Ошибка: Выбранная модель ИИ не найдена."
            logger.error(f"Attempt to set invalid AI model '{target}' by user {user_id}.")

        await update.message.reply_text(
            response_message_text, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu_key),
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu_key # Update user's current menu
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
        logger.warning(f"Unknown action '{action}' for button '{button_text}' by user {user_id}.")
        await update.message.reply_text(
            "Действие для этой кнопки не определено. Пожалуйста, сообщите администратору.",
            reply_markup=generate_menu_keyboard(current_menu_key) # Show current menu
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text: # Should not happen with text filter but good practice
        return
        
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Check if the incoming text is actually a menu button text.
    # This can happen if menu_button_handler has higher priority but doesn't consume the update,
    # or if priorities are managed such that this is a fallback.
    # Given `is_menu_button_text` is also called at the start of `menu_button_handler`,
    # this check here acts as a failsafe or if `handle_text` somehow gets a button press.
    if is_menu_button_text(user_message):
        logger.info(f"User {user_id} sent text '{user_message}' which is a menu button. Re-routing or ignoring in handle_text.")
        # Potentially call menu_button_handler here if it wasn't caught, or simply return.
        # For now, return, assuming menu_button_handler (group 1) should have caught it.
        return

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        logger.info(f"User {user_id} sent a message too short for AI: '{user_message}'")
        user_data_short_req = await get_user_data(user_id) # Use new var name
        await update.message.reply_text(
            "Ваш запрос слишком короткий. Пожалуйста, сформулируйте его более подробно или воспользуйтесь меню.",
            reply_markup=generate_menu_keyboard(user_data_short_req.get('current_menu', 'main_menu')),
            parse_mode=None,
            disable_web_page_preview=True
        )
        return

    logger.info(f"User {user_id} sent AI request: '{user_message[:100]}...'") # Log truncated message

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key) # It should always exist due to get_current_model_key fallback
    if not model_config: # Should ideally not happen
        logger.error(f"CRITICAL: Model configuration not found for key '{current_model_key}' for user {user_id}. Defaulting to emergency fallback.")
        # This is a critical state, might indicate issues with DEFAULT_MODEL_KEY or AVAILABLE_TEXT_MODELS structure.
        # As an emergency fallback, try to use the absolute default model if current_model_key resolution failed badly.
        current_model_key = DEFAULT_MODEL_KEY
        model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        # Notify admin if possible, or send a very generic error to user.
        user_data = await get_user_data(user_id)
        await update.message.reply_text("Произошла критическая ошибка конфигурации модели. Пожалуйста, сообщите администратору.",
                                        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        return


    can_proceed, limit_message_text, current_req_count = await check_and_log_request_attempt(user_id, current_model_key) # Use new var name

    if not can_proceed:
        logger.info(f"User {user_id} hit limit for model {current_model_key}. Message: {limit_message_text}")
        user_data_limit = await get_user_data(user_id) # Use new var name
        await update.message.reply_text(
            limit_message_text,
            parse_mode=ParseMode.HTML, # limit_message_text often contains HTML
            reply_markup=generate_menu_keyboard(user_data_limit.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    mode_details_for_prompt = await get_current_mode_details(user_id) # Use new var name
    system_prompt_text = mode_details_for_prompt["prompt"] # Use new var name
    # For google_genai, the full prompt includes the system prompt.
    # For custom_http_api, system_prompt is often sent as a separate message in the payload.
    
    response_text_from_api = "К сожалению, не удалось получить ответ от ИИ." # Default error message

    # --- ИЗМЕНЕНИЕ: ИСПОЛЬЗОВАНИЕ api_type ИЗ КОНФИГУРАЦИИ МОДЕЛИ ---
    api_type_from_config = model_config.get("api_type", "").strip()

    if api_type_from_config == "google_genai":
        # Construct the full prompt for Google GenAI, including the system instructions
        full_prompt_for_google = f"{system_prompt_text}\n\n**Пользовательский запрос:**\n{user_message}"
        
        genai_model = genai.GenerativeModel( # Use new var name
            model_name=model_config["id"],
            generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB}
            # safety_settings can be added here if needed
        )
        try:
            logger.info(f"Sending request to Google GenAI model: {model_config['id']} for user {user_id}")
            genai_response = await asyncio.get_event_loop().run_in_executor( # Use new var name
                None, lambda: genai_model.generate_content(full_prompt_for_google)
            )
            response_text_from_api = genai_response.text.strip() if genai_response.text else "Ответ от Google GenAI пуст."
            logger.info(f"Google GenAI response received for user {user_id}. Length: {len(response_text_from_api)}")
        except google.api_core.exceptions.ResourceExhausted as e_res_exh: # Use new var name
            response_text_from_api = "Лимит использования Google API на данный момент исчерпан. Пожалуйста, попробуйте позже."
            logger.error(f"Google API ResourceExhausted for user {user_id}, model {model_config['id']}: {e_res_exh}")
        except Exception as e_google: # Use new var name
            response_text_from_api = f"Произошла ошибка при обращении к Google API: {type(e_google).__name__}. Попробуйте позже."
            logger.error(f"Google GenAI API error for user {user_id}, model {model_config['id']}: {e_google}", exc_info=True)

    elif api_type_from_config == "custom_http_api":
        api_key_variable_name = model_config.get("api_key_var_name")
        actual_api_key_value = None
        payload_messages_list = []
        if api_key_variable_name:
            actual_api_key_value = globals().get(api_key_variable_name)

        if not actual_api_key_value or "YOUR_" in actual_api_key_value or actual_api_key_value == "":
            response_text_from_api = f"Ошибка конфигурации: Ключ API для модели «{model_config.get('name', current_model_key)}» не настроен корректно. Пожалуйста, сообщите администратору."
            logger.error(f"Custom API key error: Variable name '{api_key_variable_name}' for model '{current_model_key}' not found in globals, is None, or seems to be a placeholder.")
        else:
            if current_model_key == "custom_api_gemini_2_5_pro":
                # Используем модуль gemini_pro_handler
                response_text_from_api, success = await query_gemini_pro(system_prompt_text, user_message)
                if not success:
                    logger.warning(f"Gemini 2.5 Pro query failed for user {user_id}: {response_text_from_api}")
            elif current_model_key == "custom_api_grok_3":
                # Используем модуль grok_3_handler
                response_text_from_api, success = await query_grok_3(system_prompt_text, user_message)
                if not success:
                    logger.warning(f"Grok 3 query failed for user {user_id}: {response_text_from_api}")
            else:
                http_headers = {
                    "Authorization": f"Bearer {actual_api_key_value}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                
                is_gpt_4o_mini = (model_config["id"] == "gpt-4o-mini")
                
                if system_prompt_text:
                    if is_gpt_4o_mini:
                        payload_messages_list.append({
                            "role": "system",
                            "content": [{"type": "text", "text": system_prompt_text}]
                        })
                    else:
                        payload_messages_list.append({"role": "system", "content": system_prompt_text})
                
                if is_gpt_4o_mini:
                    payload_messages_list.append({
                        "role": "user",
                        "content": [{"type": "text", "text": user_message}]
                    })
                else:
                    payload_messages_list.append({"role": "user", "content": user_message})

                api_payload = {
                    "messages": payload_messages_list,
                    "model": model_config["id"],
                    "is_sync": True,
                    "max_tokens": model_config.get("max_tokens", MAX_OUTPUT_TOKENS_GEMINI_LIB),
                    "temperature": model_config.get("temperature", 1.0),
                    "top_p": model_config.get("top_p", 1.0),
                    "n": 1,
                    "stream": False
                }

                try:
                    logger.info(f"Sending request to Custom HTTP API: {model_config['endpoint']} for model {model_config['id']}, user {user_id}")
                    custom_api_response_obj = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: requests.post(model_config["endpoint"], headers=http_headers, json=api_payload, timeout=45)
                    )
                    custom_api_response_obj.raise_for_status()
                    response_json_data = custom_api_response_obj.json()
                    logger.debug(f"Raw JSON response from {model_config['id']} for user {user_id}: {response_json_data}")
                    extracted_api_text = None

                    model_api_id = model_config["id"]
                    if model_api_id == "gpt-4o-mini":
                        if response_json_data.get("status") == "success":
                            raw_output_data = response_json_data.get("output")
                            if isinstance(raw_output_data, str):
                                extracted_api_text = raw_output_data.strip()
                            elif isinstance(raw_output_data, dict):
                                extracted_api_text = raw_output_data.get("text", raw_output_data.get("content", "")).strip()
                                if not extracted_api_text:
                                    logger.warning(f"gpt-4o-mini: 'output' was a dict but no 'text' or 'content' found: {raw_output_data}")
                            elif raw_output_data is not None:
                                extracted_api_text = str(raw_output_data).strip()
                                logger.warning(f"gpt-4o-mini: 'output' was of unexpected type {type(raw_output_data)}, converted to string.")
                            else:
                                logger.warning(f"gpt-4o-mini: 'output' field was null or missing despite status 'success'. Response: {response_json_data}")
                                extracted_api_text = "Ответ получен, но он пуст."
                        else:
                            logger.error(f"gpt-4o-mini API error: Status was '{response_json_data.get('status', 'N/A')}'. Full response: {response_json_data}")
                            extracted_api_text = f"Ошибка от API GPT-4o mini: {response_json_data.get('status', 'статус не указан')}. {response_json_data.get('error_message', '')}"

                    if extracted_api_text is None:
                        logger.warning(f"No specific parser worked for {model_api_id}. Trying generic keys from response: {response_json_data}")
                        for fallback_key in ["text", "content", "message", "output", "response"]:
                            if isinstance(response_json_data.get(fallback_key), str):
                                extracted_api_text = response_json_data[fallback_key].strip()
                                if extracted_api_text:
                                    logger.info(f"Used generic fallback key '{fallback_key}' for {model_api_id}")
                                    break
                        if extracted_api_text is None:
                            extracted_api_text = ""

                    if extracted_api_text:
                        response_text_from_api = extracted_api_text
                    else:
                        response_text_from_api = "Ответ от API не содержит текстовых данных или не удалось его извлечь."
                        logger.warning(f"Could not extract meaningful text for custom model {model_api_id}. Response data: {response_json_data}")

                except requests.exceptions.HTTPError as e_http:
                    response_text_from_api = f"Ошибка сети при обращении к Custom API ({e_http.response.status_code}). Попробуйте позже."
                    logger.error(f"Custom API HTTPError for model {model_config['id']} ({model_config['endpoint']}): {e_http}. Response: {e_http.response.text}", exc_info=True)
                except requests.exceptions.RequestException as e_req:
                    response_text_from_api = f"Сетевая ошибка при обращении к Custom API: {type(e_req).__name__}. Проверьте соединение или попробуйте позже."
                    logger.error(f"Custom API RequestException for model {model_config['id']} ({model_config['endpoint']}): {e_req}", exc_info=True)
                except Exception as e_custom_other:
                    response_text_from_api = f"Неожиданная ошибка при работе с Custom API: {type(e_custom_other).__name__}."
                    logger.error(f"Unexpected error with Custom API model {model_config['id']}: {e_custom_other}", exc_info=True)


    else: # Unknown api_type
        response_text_from_api = "Ошибка конфигурации: Неизвестный тип API для выбранной модели. Обратитесь к администратору."
        logger.error(f"Unknown api_type '{api_type_from_config}' for model {current_model_key}. Please check model configuration in AVAILABLE_TEXT_MODELS.")

    # Truncate if necessary and increment count (even if API errored, the attempt was made)
    final_response_text, was_truncated_flag = smart_truncate(response_text_from_api, MAX_MESSAGE_LENGTH_TELEGRAM) # Use new var names
    if was_truncated_flag:
        logger.info(f"Response for user {user_id} (model {current_model_key}) was truncated to {MAX_MESSAGE_LENGTH_TELEGRAM} chars.")

    # Increment count regardless of success/failure of the API call itself, as an attempt was made
    # unless the failure was due to API key config before the call.
    # The check_and_log_request_attempt ensures user has quota.
    # Increment count here, after the API call attempt.
    await increment_request_count(user_id, current_model_key)
    
    user_data_reply = await get_user_data(user_id) # Use new var name
    await update.message.reply_text(
        final_response_text,
        parse_mode=None, # Send as plain text to avoid issues with special chars in AI response
        reply_markup=generate_menu_keyboard(user_data_reply.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Sent AI response (model: {current_model_key}) to user {user_id}. Start of response: '{final_response_text[:100].replacechr(10, ' ')}...'")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # Example: Check if payload is for a known subscription type
    # This needs to match the invoice payload you send when initiating payment.
    # For instance, if your /subscribe command sends an invoice with payload "profi_sub_30_days"
    expected_payload_prefix = f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}" # Or more specific like "profi_monthly"
    
    # For more flexibility, you might check if query.invoice_payload starts with a certain prefix
    # if you add unique IDs to payloads, e.g., f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_{user_id}_{timestamp}"
    # For simplicity, let's assume a fixed payload for now, or one that's easily identifiable.
    
    # This logic depends heavily on how you generate invoice_payload.
    # If you only have one type of subscription via this bot:
    if query.invoice_payload == f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_payload_example": # Replace with your actual payload
        await query.answer(ok=True)
        logger.info(f"Pre-checkout query for payload '{query.invoice_payload}' OK for user {query.user.id}")
    else:
        await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату. Пожалуйста, попробуйте сформировать счет заново из меню «Подписка».")
        logger.warning(f"Pre-checkout query for payload '{query.invoice_payload}' REJECTED for user {query.user.id}. Expected something like '{expected_payload_prefix}...'.")
        return
    # await query.answer(ok=True) # Default to OK if not specific checks. Or make it strict. For now, strict.

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment # Use new var name

    logger.info(f"Successful payment received from user {user_id}. Invoice Payload: {payment_info.invoice_payload}, Amount: {payment_info.total_amount} {payment_info.currency}")

    # Again, match the invoice_payload
    # Example: if payload was f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_payload_example"
    expected_payload_example = f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_payload_example" # Replace

    if payment_info.invoice_payload == expected_payload_example: # Replace with your actual payload check
        # Determine subscription duration, e.g., 30 days
        # This might also be part of the payload if you have multiple subscription options
        subscription_duration_days = 30
        
        bot_data = await get_bot_data()
        user_subscriptions_data = bot_data.get('user_subscriptions', {}) # Use new var name
        current_user_sub = user_subscriptions_data.get(str(user_id), {}) # Use new var name

        # Calculate new validity date
        # If user already has an active subscription, decide whether to extend or overwrite.
        # For simplicity, let's assume it extends from today or from previous expiry if later.
        now_aware = datetime.now().astimezone() # Timezone-aware current time
        start_date_for_extension = now_aware
        
        if current_user_sub.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and current_user_sub.get('valid_until'):
            try:
                previous_valid_until_dt = datetime.fromisoformat(current_user_sub['valid_until'])
                if previous_valid_until_dt > now_aware: # If previous sub is still valid and in the future
                    start_date_for_extension = previous_valid_until_dt
            except ValueError: # Invalid date format in storage
                logger.warning(f"Invalid 'valid_until' format for user {user_id} during payment: {current_user_sub.get('valid_until')}")


        new_valid_until_dt = start_date_for_extension + timedelta(days=subscription_duration_days)
        
        # Update user's subscription details in bot_data
        user_subscriptions_data[str(user_id)] = {
            'level': PRO_SUBSCRIPTION_LEVEL_KEY,
            'valid_until': new_valid_until_dt.isoformat(), # Store in ISO format
            'last_payment_amount': payment_info.total_amount,
            'last_payment_currency': payment_info.currency,
            'purchase_date': now_aware.isoformat()
        }
        bot_data['user_subscriptions'] = user_subscriptions_data
        await set_bot_data(bot_data)

        confirmation_text = (f"🎉 Оплата успешно получена! Ваша подписка <b>Профи</b> "
                             f"активирована/продлена до <b>{new_valid_until_dt.strftime('%d.%m.%Y')}</b>.\n"
                             f"Спасибо за поддержку! Теперь вам доступны все преимущества подписки.")
        
        user_current_data = await get_user_data(user_id) # Use new var name
        await update.message.reply_text(
            confirmation_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_current_data.get('current_menu', 'main_menu')), # Or always 'main_menu'
            disable_web_page_preview=True
        )
        logger.info(f"Subscription for user {user_id} updated to {PRO_SUBSCRIPTION_LEVEL_KEY} until {new_valid_until_dt.isoformat()}.")
        
        # Optionally, notify admin
        if YOUR_ADMIN_ID:
            try:
                admin_message = (f"🔔 Новая оплата подписки!\n"
                                 f"Пользователь: {update.effective_user.full_name} (ID: {user_id}, @{update.effective_user.username})\n"
                                 f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n" # Assuming amount is in smallest units
                                 f"Подписка '{PRO_SUBSCRIPTION_LEVEL_KEY}' до: {new_valid_until_dt.strftime('%d.%m.%Y')}\n"
                                 f"Payload: {payment_info.invoice_payload}")
                await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=admin_message, parse_mode=ParseMode.HTML)
            except Exception as e_admin_notify:
                 logger.error(f"Failed to send payment notification to admin {YOUR_ADMIN_ID}: {e_admin_notify}")

    else: # Payload mismatch
        logger.error(f"Successful payment received for user {user_id}, but invoice_payload '{payment_info.invoice_payload}' did not match expected. No subscription updated. THIS IS A POTENTIAL ISSUE.")
        await update.message.reply_text(
            "Спасибо за ваш платеж! Однако возникла проблема с автоматической активацией подписки из-за несоответствия данных заказа. Пожалуйста, свяжитесь с администратором для разрешения ситуации.",
            # Provide admin contact if possible
        )
        # Notify admin about this discrepancy immediately
        if YOUR_ADMIN_ID:
            try:
                admin_alert_mismatch = (f"⚠️ КРИТИЧЕСКАЯ ОШИБКА ОПЛАТЫ (несоответствие payload)!\n"
                                     f"Пользователь: {update.effective_user.full_name} (ID: {user_id}, @{update.effective_user.username})\n"
                                     f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                                     f"Полученный Payload: {payment_info.invoice_payload}\n"
                                     f"Ожидаемый Payload (пример): {expected_payload_example}\n"
                                     "ПОДПИСКА НЕ БЫЛА ОБНОВЛЕНА АВТОМАТИЧЕСКИ. ТРЕБУЕТСЯ РУЧНОЕ ВМЕШАТЕЛЬСТВО!")
                await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=admin_alert_mismatch, parse_mode=ParseMode.HTML)
            except Exception as e_admin_alert:
                 logger.error(f"Failed to send CRITICAL payment alert to admin {YOUR_ADMIN_ID}: {e_admin_alert}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Build the message with some markup and additional information about the bot context.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    
    # Log the full traceback string for detailed diagnostics.
    logger.error(f"Full Traceback for error caused by update {update_str}:\n{tb_string}")


    # Send a simplified error message to the user.
    # Check if 'update' is an Update object and has 'effective_chat'
    if isinstance(update, Update) and update.effective_chat:
        user_data_err = await get_user_data(update.effective_user.id) # Use new var name
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла внутренняя ошибка. Мы уже работаем над этим. Пожалуйста, попробуйте выполнить ваш запрос позже или используйте команду /start для возврата в главное меню.",
                reply_markup=generate_menu_keyboard(user_data_err.get('current_menu', 'main_menu')), # Fallback reply markup
                parse_mode=None # Plain text for error message
            )
        except Exception as e_send_err: # If sending the error message itself fails
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e_send_err}")

    # Optionally, send detailed error to admin
    if YOUR_ADMIN_ID and isinstance(update, Update): # Ensure context.bot and YOUR_ADMIN_ID are available
        try:
            # Limit traceback length for admin message
            message_for_admin = (
                f"🤖 Бот столкнулся с ошибкой:\n"
                f"Исключение: {context.error.__class__.__name__}: {context.error}\n"
                f"Пользователь: {update.effective_user.full_name if update.effective_user else 'N/A'} (ID: {update.effective_user.id if update.effective_user else 'N/A'})\n"
                f"Чат ID: {update.effective_chat.id if update.effective_chat else 'N/A'}\n"
                f"Запрос пользователя (если есть): {update.message.text if update.message and update.message.text else 'N/A'}\n\n"
                f"```\n{tb_string[:3500]}\n```" # Truncate traceback for TG message limit
            )
            await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=message_for_admin, parse_mode=ParseMode.MARKDOWN_V2) # Use Markdown for ```
        except Exception as e_admin_err_notify:
            logger.error(f"Failed to send detailed error to admin {YOUR_ADMIN_ID}: {e_admin_err_notify}. Original error: {context.error}")


async def main():
    app_builder = Application.builder().token(TOKEN)
    # Настройте тайм-ауты здесь, если они нужны для всех HTTP-запросов бота:
    app_builder.read_timeout(30).connect_timeout(30) # Таймаут чтения и соединения
    # app_builder.pool_timeout(20) # Таймаут пула соединений, если нужно

    app = app_builder.build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", open_menu_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("subscribe", subscribe_info_command)) # For info and initiating payment
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Message handler for menu buttons (higher priority group)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    
    # Message handler for general text input (lower priority group, will be checked after menu_button_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    # Payment handlers
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Error handler
    app.add_error_handler(error_handler)

    bot_commands = [ # Use new var name
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Мои лимиты использования"),
        BotCommand("subscribe", "💎 Информация о Подписке Профи"),
        BotCommand("bonus", "🎁 Получить бонус за канал"),
        BotCommand("help", "❓ Справка по боту")
    ]
    try:
        await app.bot.set_my_commands(bot_commands)
        logger.info("Bot commands successfully set.")
    except Exception as e_set_commands: # Use new var name
        logger.error(f"Failed to set bot commands: {e_set_commands}")

        logger.info("Bot is starting polling...")
    
    await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    # Configure Google Gemini API
    if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or not GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
        logger.warning("Google Gemini API key (GOOGLE_GEMINI_API_KEY) appears to be missing, a placeholder, or incorrectly formatted.")
    else:
        try:
            genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API configured successfully.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API with key starting '{GOOGLE_GEMINI_API_KEY[:10]}...': {str(e)}")

    # Check Custom API Keys (log warnings if they seem like placeholders)
    if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or not CUSTOM_GEMINI_PRO_API_KEY.startswith("sk-"):
        logger.warning("Custom Gemini Pro API key (CUSTOM_GEMINI_PRO_API_KEY) appears to be missing, a placeholder, or incorrectly formatted.")
    
    if not CUSTOM_GROK_3_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GROK_3_API_KEY or not CUSTOM_GROK_3_API_KEY.startswith("sk-"):
        logger.warning("Custom Grok 3 API key (CUSTOM_GROK_3_API_KEY) appears to be missing, a placeholder, or incorrectly formatted.")

    # --- НОВАЯ ПРОВЕРКА КЛЮЧА ДЛЯ GPT-4o mini ---
    if not CUSTOM_GPT4O_MINI_API_KEY or "YOUR_GPT4O_MINI_KEY_HERE" in CUSTOM_GPT4O_MINI_API_KEY or not CUSTOM_GPT4O_MINI_API_KEY.startswith("sk-"): # Assuming it also starts with "sk-" or similar
        logger.warning("Custom GPT-4o mini API key (CUSTOM_GPT4O_MINI_API_KEY) appears to be missing, a placeholder, or incorrectly formatted. Please set it.")

    if not PAYMENT_PROVIDER_TOKEN or "YOUR_PAYMENT_PROVIDER_TOKEN" in PAYMENT_PROVIDER_TOKEN:
        logger.warning("Payment Provider Token (PAYMENT_PROVIDER_TOKEN) appears to be missing or a placeholder. Payments will not work.")
    
    if not db:
        logger.critical("Firestore database (db) is not initialized. Bot may not function correctly. Check Firebase setup.")
        # Depending on criticality, you might exit or run with limited functionality.
        # For now, it will run but Firestore operations will be skipped.

    asyncio.run(main())
