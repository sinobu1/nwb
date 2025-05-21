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

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000
MIN_AI_REQUEST_LENGTH = 4  # Минимальная длина запроса к ИИ

# --- ЛИМИТЫ ---
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"
DEFAULT_FREE_REQUESTS_GROK_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY = 25

# --- КАНАЛ НОВОСТЕЙ И БОНУС ---
NEWS_CHANNEL_USERNAME = "@timextech"
NEWS_CHANNEL_LINK = "https://t.me/timextech"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
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
        "id": "grok-3-beta",
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
        if os.path.exists("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"):
            cred = credentials.Certificate("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json")
        else:
            raise FileNotFoundError("Файл gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json не найден, и FIREBASE_CREDENTIALS не установлена.")

    # Инициализация приложения Firebase
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

    # Инициализация асинхронного клиента Firestore из firebase_admin
    db = firestore.client()  # Используем синхронный клиент для совместимости
    logger.info("Firestore клиент успешно инициализирован")
except Exception as e:
    logger.error(f"Неизвестная ошибка при инициализации Firebase/Firestore: {e}")
    raise

# --- Вспомогательные функции для работы с Firestore ---
async def get_user_data(user_id: int) -> dict:
    doc_ref = db.collection("users").document(str(user_id))
    doc = await asyncio.to_thread(doc_ref.get)  # Выполняем в отдельном потоке
    return doc.to_dict() or {}

async def set_user_data(user_id: int, data: dict):
    doc_ref = db.collection("users").document(str(user_id))
    await asyncio.to_thread(doc_ref.set, data, merge=True)  # Выполняем в отдельном потоке
    logger.info(f"Updated user data for {user_id}: {data}")

async def get_bot_data() -> dict:
    doc_ref = db.collection("bot_data").document("data")
    doc = await asyncio.to_thread(doc_ref.get)  # Выполняем в отдельном потоке
    return doc.to_dict() or {}

async def set_bot_data(data: dict):
    doc_ref = db.collection("bot_data").document("data")
    await asyncio.to_thread(doc_ref.set, data, merge=True)  # Выполняем в отдельном потоке
    logger.info(f"Updated bot data: {data}")

async def get_current_mode_details(user_id: int) -> dict:
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id)
    mode_key = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    # Reset to default if mode is invalid or grok_3_custom_mode
    if mode_key not in AI_MODES or mode_key == "grok_3_custom_mode":
        mode_key = DEFAULT_AI_MODE_KEY
        user_data['current_ai_mode'] = mode_key
        await set_user_data(user_id, user_data)
        logger.info(f"Reset invalid mode '{mode_key}' to default for user {user_id}")
    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
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
            if 'selected_api_type' not in user_data or user_data['selected_api_type'] != info.get("api_type"):
                user_data['selected_api_type'] = info.get("api_type")
                await set_user_data(user_id, user_data)
                logger.info(f"Inferred api_type to '{info.get('api_type')}' for model_id '{selected_id}'")
            return key

    logger.warning(f"Could not find key for model_id '{selected_id}'. Falling back to default.")
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
        return str(text), False
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
            actual_pos = pos + (len(sep) if sep != ' ' else 0)
            if actual_pos > 0:
                possible_cut_points.append(actual_pos)
    if possible_cut_points:
        cut_at = max(possible_cut_points)
        if cut_at > adjusted_max_length * 0.3:
            return text[:cut_at].strip() + suffix, True
    return text[:adjusted_max_length].strip() + suffix, True

async def get_user_actual_limit_for_model(user_id: int, model_key: str) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config:
        return 0
    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    current_sub_level = None
    if user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                current_sub_level = user_subscription_details.get('level')
        except Exception:
            pass

    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free":
        return model_config.get("limit", 0)
    if limit_type == "subscription_or_daily_free":
        return model_config.get("subscription_daily_limit" if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY else "limit_if_no_subscription", 0)
    if limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit" if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY else "limit_if_no_subscription", 0)
        user_data = await get_user_data(user_id)
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and user_data.get('claimed_news_bonus', False):
            bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
            return base_limit + bonus_uses_left
        return base_limit
    return model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0

async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return True, "", 0

    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi_subscriber = False
    if model_config.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro"]:
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception:
                pass

    user_data = await get_user_data(user_id)
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
        if user_data.get('news_bonus_uses_left', 0) > 0:
            logger.info(f"User {user_id} has bonus for {model_key}. Allowing.")
            return True, "bonus_available", 0

    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': '', 'count': 0})
    if model_daily_usage['date'] != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
        user_model_counts[model_key] = model_daily_usage
        all_daily_counts[str(user_id)] = user_model_counts
        bot_data['all_user_daily_counts'] = all_daily_counts
        await set_bot_data(bot_data)

    current_daily_count = model_daily_usage['count']
    actual_daily_limit = await get_user_actual_limit_for_model(user_id, model_key)

    if current_daily_count >= actual_daily_limit:
        message_parts = [f"Вы достигли лимита ({current_daily_count}/{actual_daily_limit}) для {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not user_data.get('claimed_news_bonus', False):
                message_parts.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонусной генерации!')
            elif user_data.get('news_bonus_uses_left', 0) == 0:
                message_parts.append(f"ℹ️ Бонус за подписку использован (<a href='{NEWS_CHANNEL_LINK}'>канал</a>).")
        message_parts.append("Попробуйте завтра или купите подписку в меню «Подписка».")
        return False, "\n".join(message_parts), current_daily_count
    return True, "", current_daily_count

async def increment_request_count(user_id: int, model_key: str):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
        is_profi_subscriber = False
        user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception:
                pass
        
        if not is_profi_subscriber:
            news_bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
            if news_bonus_uses_left > 0:
                user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
                await set_user_data(user_id, user_data)
                logger.info(f"User {user_id} consumed bonus for {model_key}. Remaining: {user_data['news_bonus_uses_left']}")
                return

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_daily_usage['date'] != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
    model_daily_usage['count'] += 1
    user_model_counts[model_key] = model_daily_usage
    all_daily_counts[str(user_id)] = user_model_counts
    bot_data['all_user_daily_counts'] = all_daily_counts
    await set_bot_data(bot_data)
    logger.info(f"User {user_id} count for {model_key} incremented to {model_daily_usage['count']}")

# --- Проверка, является ли текст кнопкой меню ---
def is_menu_button_text(text: str) -> bool:
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons:
        return True
    for menu_key, menu in MENU_STRUCTURE.items():
        for item in menu["items"]:
            if item["text"] == text:
                return True
    return False

# --- Удаление пользовательских сообщений с командами или кнопками ---
async def try_delete_user_message(update: Update, user_id: int):
    chat_id = update.effective_chat.id
    user_data = await get_user_data(user_id)
    user_command_message = user_data.get('user_command_message', {})
    message_id = user_command_message.get('message_id')
    timestamp = user_command_message.get('timestamp')

    if not message_id or not timestamp:
        return

    try:
        msg_time = datetime.fromisoformat(timestamp)
        if datetime.now(msg_time.tzinfo) - msg_time > timedelta(hours=48):
            logger.info(f"User message {message_id} is older than 48 hours, clearing")
            user_data.pop('user_command_message', None)
            await set_user_data(user_id, user_data)
            return
    except Exception:
        logger.warning("Invalid user message timestamp, clearing")
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)
        return

    try:
        await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted user message {message_id}")
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)
    except telegram.error.BadRequest as e:
        logger.warning(f"Failed to delete user message {message_id}: {e}")
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)

# --- Функции для меню на клавиатуре ---
def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        return ReplyKeyboardMarkup([[]], resize_keyboard=True, one_time_keyboard=False)
    
    keyboard = []
    if menu_key == "main_menu":
        items = menu["items"]
        for i in range(0, len(items), 2):
            row = [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            keyboard.append(row)
    else:
        keyboard = [[KeyboardButton(item["text"])] for item in menu["items"]]
    
    if menu["is_submenu"]:
        nav_row = []
        if menu["parent"]:
            nav_row.append(KeyboardButton("⬅️ Назад"))
        nav_row.append(KeyboardButton("🏠 Главное меню"))
        keyboard.append(nav_row)
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str):
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        await update.message.reply_text("Ошибка: Меню не найдено.", reply_markup=generate_menu_keyboard("main_menu"))
        return
    
    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key
    await set_user_data(user_id, user_data)
    
    text = menu["title"]
    reply_markup = generate_menu_keyboard(menu_key)
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=None,
        disable_web_page_preview=True
    )
    logger.info(f"Sent menu message for {menu_key}: {text}")

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    user_data.setdefault('current_menu', 'main_menu')
    default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    user_data.setdefault('selected_model_id', default_model_conf["id"])
    user_data.setdefault('selected_api_type', default_model_conf["api_type"])
    await set_user_data(user_id, user_data)
    
    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data)
    
    current_model_key = await get_current_model_key(user_id)
    current_mode_name = (await get_current_mode_details(user_id))['name']
    current_model_name = AVAILABLE_TEXT_MODELS[current_model_key]['name']

    greeting = f"👋 Привет! Я твой ИИ-бот на базе Gemini.\n🧠 Агент: <b>{current_mode_name}</b>\n⚙️ Модель: <b>{current_model_name}</b>\n\n💬 Задавайте вопросы или используйте меню ниже!"
    await update.message.reply_text(
        greeting,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"Sent start message for user {user_id}: {greeting}")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
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
    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data)
    await try_delete_user_message(update, user_id)
    await claim_news_bonus_logic(update, user_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
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
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    display_sub_level = "Бесплатный доступ"
    subscription_active = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                display_sub_level = f"Подписка (до {valid_until_dt.strftime('%Y-%m-%d')})"
                subscription_active = True
            else:
                display_sub_level = f"Подписка (истекла)"
        except Exception:
            display_sub_level = "Подписка (ошибка даты)"

    usage_text_parts = [
        "<b>📊 Ваши лимиты</b>",
        f"Статус: <b>{display_sub_level}</b>",
        "",
        "Лимиты запросов:"
    ]
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            actual_l = await get_user_actual_limit_for_model(user_id, model_k)
            bonus_note = ""
            if model_k == NEWS_CHANNEL_BONUS_MODEL_KEY and user_data.get('claimed_news_bonus', False) and user_data.get('news_bonus_uses_left', 0) > 0:
                bonus_note = " (вкл. бонус)"
            usage_text_parts.append(f"▫️ {model_c['name']}: <b>{current_c_display}/{actual_l}</b>{bonus_note}")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
        bonus_info = ""
        if not user_data.get('claimed_news_bonus', False):
            bonus_info = f'🎁 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> генерации ({bonus_model_name})!'
        elif (bonus_uses_left := user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info = f'🎁 У вас <b>{bonus_uses_left}</b> бонусных генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
        else:
            bonus_info = f'ℹ️ Бонус для {bonus_model_name} использован (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
        usage_text_parts.append(bonus_info)

    if not subscription_active:
        usage_text_parts.append("Больше лимитов? Меню «Подписка».")

    final_usage_text = "\n".join(usage_text_parts)
    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'limits_submenu'))

    await update.message.reply_text(
        final_usage_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent limits message: {final_usage_text}")

async def claim_news_bonus_logic(update: Update, user_id: int):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    user_data = await get_user_data(user_id)
    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data)
    await try_delete_user_message(update, user_id)

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        text = "Функция бонуса не настроена."
        await update.message.reply_text(
            text,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            parse_mode=None
        )
        logger.info(f"Sent bonus not configured message: {text}")
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        text = "Ошибка: Бонусная модель не найдена."
        await update.message.reply_text(
            text,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            parse_mode=None
        )
        logger.info(f"Sent bonus model not found message: {text}")
        return

    bonus_model_name = bonus_model_config['name']

    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        if uses_left > 0:
            reply_text = f'Вы уже активировали бонус. У вас осталось <b>{uses_left}</b> генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
        else:
            reply_text = f'Бонус для {bonus_model_name} использован (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
        await update.message.reply_text(
            reply_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        logger.info(f"Sent bonus already claimed message: {reply_text}")
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member_status.status in ['member', 'administrator', 'creator']:
            user_data['claimed_news_bonus'] = True
            user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await set_user_data(user_id, user_data)
            success_text = f'🎉 Спасибо за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>! Вам начислена <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> генерация для {bonus_model_name}.'
            await update.message.reply_text(
                success_text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard('main_menu'),
                disable_web_page_preview=True
            )
            logger.info(f"Sent bonus success message: {success_text}")
        else:
            fail_text = f'Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> и нажмите «Получить» снова.'
            reply_markup_inline = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
            ]])
            await update.message.reply_text(
                fail_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup_inline,
                disable_web_page_preview=True
            )
            logger.info(f"Sent bonus subscription required message: {fail_text}")
    except telegram.error.BadRequest as e:
        error_text_response = str(e).lower()
        reply_message_on_error = f'Мы не смогли подтвердить подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>. Подпишитесь и попробуйте снова.'
        reply_markup_inline = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
        ]])
        await update.message.reply_text(
            reply_message_on_error,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup_inline,
            disable_web_page_preview=True
        )
        logger.error(f"BadRequest error checking channel membership: {e}")
        logger.info(f"Sent bonus error message: {reply_message_on_error}")

async def show_subscription(update: Update, user_id: int):
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    sub_text_parts = ["<b>💎 Подписка Профи</b>"]
    is_active = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                sub_text_parts.append(f"Ваша подписка активна до <b>{valid_until_dt.strftime('%Y-%m-%d')}</b>.")
                is_active = True
            else:
                sub_text_parts.append(f"Ваша подписка истекла <b>{valid_until_dt.strftime('%Y-%m-%d')}</b>.")
        except Exception:
            sub_text_parts.append("Ошибка проверки статуса подписки.")

    if not is_active:
        sub_text_parts.append("\nС подпиской вы получите:")
        sub_text_parts.append("▫️ Увеличенные лимиты на все модели ИИ")
        sub_text_parts.append("▫️ Доступ к Gemini Pro")
        sub_text_parts.append("\nКупить подписку: /subscribe")

    final_sub_text = "\n".join(sub_text_parts)
    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'subscription_submenu'))

    await update.message.reply_text(
        final_sub_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent subscription message: {final_sub_text}")

async def show_help(update: Update, user_id: int):
    user_data = await get_user_data(user_id)
    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data)
    await try_delete_user_message(update, user_id)

    help_text = (
        "<b>❓ Помощь</b>\n\n"
        "Я — ИИ-бот на базе Gemini. Вот что я умею:\n"
        "▫️ Отвечать на вопросы в разных агентах ИИ\n"
        "▫️ Менять модели и агентов через меню\n"
        "▫️ Показывать лимиты запросов\n"
        "▫️ Предоставлять бонусы за подписку на канал\n"
        "▫️ Поддерживать подписку для расширенных лимитов\n\n"
        "Используйте меню ниже или команды:\n"
        "▫️ /start — Начать\n"
        "▫️ /menu — Открыть меню\n"
        "▫️ /usage — Показать лимиты\n"
        "▫️ /subscribe — Информация о подписке\n"
        "▫️ /bonus — Получить бонус\n"
        "▫️ /help — Эта справка"
    )
    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'help_submenu'))

    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent help message: {help_text}")

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    user_data = await get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', 'main_menu')
    current_menu = MENU_STRUCTURE.get(current_menu_key, MENU_STRUCTURE['main_menu'])

    if not is_menu_button_text(button_text):
        logger.info(f"Text '{button_text}' is not a menu button, skipping to handle_text")
        return

    user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await set_user_data(user_id, user_data)
    await try_delete_user_message(update, user_id)

    logger.info(f"Processing button '{button_text}' in menu '{current_menu_key}'")

    if button_text == "⬅️ Назад":
        parent_menu = current_menu.get("parent")
        if parent_menu:
            await show_menu(update, user_id, parent_menu)
        else:
            await show_menu(update, user_id, "main_menu")
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu")
        return

    selected_item = next((item for item in current_menu["items"] if item["text"] == button_text), None)
    if not selected_item:
        for menu_key, menu in MENU_STRUCTURE.items():
            selected_item = next((item for item in menu["items"] if item["text"] == button_text), None)
            if selected_item:
                logger.info(f"Button '{button_text}' found in menu '{menu_key}'")
                break

    if not selected_item:
        logger.warning(f"Button '{button_text}' not found in any menu. Current menu: {current_menu_key}")
        text = "Команда не распознана. Используйте кнопки меню."
        await update.message.reply_text(
            text,
            reply_markup=generate_menu_keyboard(current_menu_key),
            parse_mode=None
        )
        logger.info(f"Sent unrecognized command message: {text}")
        return

    action = selected_item["action"]
    target = selected_item["target"]
    logger.info(f"Button '{button_text}' triggers action '{action}' with target '{target}'")

    if action == "submenu":
        await show_menu(update, user_id, target)
    elif action == "set_agent":
        return_menu = current_menu.get("parent", "main_menu")
        if target in AI_MODES and target != "gemini_pro_custom_mode":
            user_data['current_ai_mode'] = target
            await set_user_data(user_id, user_data)
            details = AI_MODES[target]
            new_text = f"🤖 Агент изменён на: <b>{details['name']}</b>\n\n{details['welcome']}"
        elif target == "gemini_pro_custom_mode":
            new_text = "Агент для Gemini Pro выбирается автоматически."
        else:
            new_text = "⚠️ Ошибка: Агент не найден."
        await update.message.reply_text(
            new_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu),
            disable_web_page_preview=True
        )
        logger.info(f"Sent set_agent message for {target}: {new_text}")
        user_data['current_menu'] = return_menu
        await set_user_data(user_id, user_data)
    elif action == "set_model":
        return_menu = current_menu.get("parent", "main_menu")
        if target in AVAILABLE_TEXT_MODELS:
            config = AVAILABLE_TEXT_MODELS[target]
            user_data.update({
                'selected_model_id': config["id"],
                'selected_api_type': config["api_type"]
            })
            # Reset current_ai_mode to default if selecting Grok 3
            if target == "custom_api_grok_3":
                user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY
            await set_user_data(user_id, user_data)
            bot_data = await get_bot_data()
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage = user_model_counts.get(target, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            actual_l = await get_user_actual_limit_for_model(user_id, target)
            limit_str = f'Лимит: {current_c_display}/{actual_l} в день'
            new_text = f"⚙️ Модель изменена на: <b>{config['name']}</b>\n{limit_str}"
        else:
            new_text = "⚠️ Ошибка: Модель не найдена."
        await update.message.reply_text(
            new_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu),
            disable_web_page_preview=True
        )
        logger.info(f"Sent set_model message for {target}: {new_text}")
        user_data['current_menu'] = return_menu
        await set_user_data(user_id, user_data)
    elif action == "show_limits":
        await show_limits(update, user_id)
    elif action == "check_bonus":
        await claim_news_bonus_logic(update, user_id)
    elif action == "show_subscription":
        await show_subscription(update, user_id)
    elif action == "show_help":
        await show_help(update, user_id)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    if is_menu_button_text(user_message):
        logger.info(f"Text '{user_message}' is a menu button, skipping handle_text")
        return

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        logger.info(f"Text '{user_message}' is too short for AI request, ignoring")
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            "Запрос слишком короткий. Пожалуйста, уточните ваш вопрос или используйте меню.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            parse_mode=None
        )
        logger.info(f"Sent short request message")
        return

    logger.info(f"Processing AI request: '{user_message}'")

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])
    can_proceed, limit_message, current_count = await check_and_log_request_attempt(user_id, current_model_key)

    if not can_proceed:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            limit_message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        logger.info(f"Sent limit reached message: {limit_message}")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id)
    system_prompt = mode_details["prompt"]
    full_prompt = f"{system_prompt}\n\n**Пользовательский запрос:**\n{user_message}"

    if model_config["api_type"] == "google_genai":
        model = genai.GenerativeModel(
            model_name=model_config["id"],
            generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB}
        )
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.generate_content(full_prompt)
            )
            response_text = response.text.strip() if response.text else "Ответ не получен."
        except google.api_core.exceptions.ResourceExhausted:
            response_text = "Лимит API исчерпан. Попробуйте позже."
            logger.error(f"ResourceExhausted for user {user_id} with model {model_config['id']}")
        except Exception as e:
            response_text = f"Ошибка API: {str(e)}"
            logger.error(f"API error for user {user_id}: {str(e)}")
    elif model_config["api_type"] == "custom_http_api":
        api_key = CUSTOM_GEMINI_PRO_API_KEY if model_config["id"] == "gemini-2.5-pro-preview-03-25" else CUSTOM_GROK_3_API_KEY
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "model": model_config["id"],
            "is_sync": True,
            "max_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB,
            "temperature": 1.0,
            "top_p": 1.0,
            "n": 1
        }
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=30)
            )
            response.raise_for_status()
            response_data = response.json()
            extracted_text = None

            if model_config["id"] == "grok-3-beta":
                # Попробуем несколько возможных ключей для Grok
                for key in ["output", "text", "choices", "message", "content"]:
                    if key in response_data:
                        if key == "choices" and isinstance(response_data[key], list) and len(response_data[key]) > 0:
                            extracted_text = response_data[key][0].get("message", {}).get("content", "").strip()
                        elif key == "message" and isinstance(response_data[key], dict):
                            extracted_text = response_data[key].get("content", "").strip()
                        else:
                            extracted_text = str(response_data[key]).strip()
                        break
                if not extracted_text:
                    # Дополнительная попытка для вложенных структур
                    if "message" in response_data and isinstance(response_data["message"], dict):
                        extracted_text = response_data["message"].get("content", "").strip()
                    elif "choices" in response_data and isinstance(response_data["choices"], list) and len(response_data["choices"]) > 0:
                        extracted_text = response_data["choices"][0].get("text", "").strip()
            elif model_config["id"] == "gemini-2.5-pro-preview-03-25":
                extracted_text = response_data.get("text", "").strip()

            if extracted_text:
                response_text = extracted_text
            else:
                response_text = "Ответ не получен."
                logger.warning(f"Could not extract text for model {model_config['id']}. Response data: {response_data}")
        except requests.exceptions.RequestException as e:
            response_text = f"Ошибка API: {str(e)}"
            logger.error(f"Request error for model {model_config['id']}: {str(e)}")
            logger.debug(f"Response content: {response.text if response else 'No response'}")
    else:
        response_text = "Неизвестный тип API."
        logger.error(f"Unknown api_type for model {current_model_key}")

    response_text, was_truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"Response for user {user_id} was truncated to {MAX_MESSAGE_LENGTH_TELEGRAM} characters")

    await increment_request_count(user_id, current_model_key)
    user_data = await get_user_data(user_id)
    await update.message.reply_text(
        response_text,
        parse_mode=None,
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Sent AI response for request: '{user_message}': {response_text[:100]}...")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload != f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}":
        await query.answer(ok=False, error_message="Неверный payload подписки.")
        return
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    if payment.invoice_payload == f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}":
        valid_until = datetime.now().astimezone() + timedelta(days=30)
        bot_data = await get_bot_data()
        bot_data.setdefault('user_subscriptions', {}).setdefault(str(user_id), {}).update({
            'level': PRO_SUBSCRIPTION_LEVEL_KEY,
            'valid_until': valid_until.isoformat()
        })
        await set_bot_data(bot_data)
        text = f"🎉 Подписка <b>Профи</b> активирована до <b>{valid_until.strftime('%Y-%m-%d')}</b>! Наслаждайтесь расширенными лимитами."
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard('main_menu'),
            disable_web_page_preview=True
        )
        logger.info(f"Sent payment success message: {text}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.effective_chat:
        chat_id = update.effective_chat.id
        user_data = await get_user_data(update.effective_user.id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Произошла ошибка. Попробуйте снова или используйте /start.",
            reply_markup=generate_menu_keyboard('main_menu'),
            parse_mode=None
        )
        logger.info(f"Sent error handler message")

async def main():
    app = Application.builder().token(TOKEN).build()

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

    commands = [
        BotCommand("menu", "Открыть меню"),
        BotCommand("usage", "Показать лимиты"),
        BotCommand("subscribe", "Информация о подписке"),
        BotCommand("bonus", "Получить бонус"),
        BotCommand("help", "Справка")
    ]
    await app.bot.set_my_commands(commands)

    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Configure Google Gemini API
    if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
        logger.warning("Google Gemini API key is not set correctly.")
    else:
        try:
            genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API configured successfully.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API: {str(e)}")

    if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY:
        logger.warning("Custom Gemini Pro API key is not set correctly.")

    if not CUSTOM_GROK_3_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GROK_3_API_KEY or "sk-" not in CUSTOM_GROK_3_API_KEY:
        logger.warning("Custom Grok 3 API key is not set correctly.")

    asyncio.run(main())
