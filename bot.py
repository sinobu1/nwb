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
import traceback # Добавлено для детального логгирования ошибок
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta
from telegram import LabeledPrice
from typing import Optional # Оставлено, хотя Optional не используется явно в аннотациях функций в текущем коде
import uuid # Оставлено, хотя uuid не используется явно в текущем коде
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
# from google.cloud.firestore_v1 import AsyncClient # Закомментировано, так как используется синхронный клиент

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
MIN_AI_REQUEST_LENGTH = 4 # Минимальная длина запроса к ИИ (исправлен неразрывный пробел)

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
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro" # Оставлено как есть, можете изменить на Grok при необходимости
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
        "name": "Продвинутый", # Используется для Gemini Pro
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент."
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя."
            "Соблюдай вежливость и объективность."
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости."
            "Если твои знания ограничены по времени, указывай это."
        ),
        "welcome": "Активирован режим 'Продвинутый'. Какой у вас запрос?"
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
     "grok_3_custom_mode": { # Режим для Grok
        "name": "Grok Продвинутый",
        "prompt": (
            "Ты — Grok 3, мощный и немного эксцентричный ИИ-ассистент от xAI."
            "Отвечай точно, развернуто и с долей присущего тебе юмора, если это уместно."
            "Будь объективным, но не бойся высказывать собственное мнение, если тебя об этом просят."
            "Если твои знания ограничены по времени, указывай это."
            "Формулируй ответы ясно и структурированно."
        ),
        "welcome": "Активирован режим 'Grok Продвинутый'. Задавайте свои каверзные вопросы!"
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
            # Не показываем специфичные режимы для моделей в общем списке выбора агентов
            if key not in ["gemini_pro_custom_mode", "grok_3_custom_mode"]
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
        if os.path.exists("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"): # Замените на имя вашего файла ключа Firebase
            cred = credentials.Certificate("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json")
        else:
            raise FileNotFoundError("Файл gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json не найден, и FIREBASE_CREDENTIALS не установлена.")

    # Инициализация приложения Firebase
    try:
        if not firebase_admin._apps: # Проверяем, инициализировано ли уже приложение
            initialize_app(cred)
            logger.info("Firebase успешно инициализирован")
        else:
            logger.info("Firebase уже инициализирован, пропускаем повторную инициализацию")
    except FirebaseError as e: # Более специфичный отлов ошибок Firebase
        logger.error(f"Ошибка инициализации Firebase: {e}")
        raise

    db = firestore.client()
    logger.info("Firestore клиент успешно инициализирован")
except Exception as e: # Общий отлов на случай других проблем при инициализации
    logger.error(f"Неизвестная ошибка при инициализации Firebase/Firestore: {e}")
    # raise # Можно закомментировать raise, если бот должен пытаться работать без Firestore в случае ошибки

# --- Вспомогательные функции для работы с Firestore ---
async def get_user_data(user_id: int) -> dict:
    try:
        doc_ref = db.collection("users").document(str(user_id))
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() or {}
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя {user_id} из Firestore: {e}")
        return {}


async def set_user_data(user_id: int, data: dict):
    try:
        doc_ref = db.collection("users").document(str(user_id))
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        logger.info(f"Updated user data for {user_id}: {data}")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных пользователя {user_id} в Firestore: {e}")


async def get_bot_data() -> dict:
    try:
        doc_ref = db.collection("bot_data").document("data")
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() or {}
    except Exception as e:
        logger.error(f"Ошибка получения данных бота из Firestore: {e}")
        return {}

async def set_bot_data(data: dict):
    try:
        doc_ref = db.collection("bot_data").document("data")
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        logger.info(f"Updated bot data: {data}")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных бота в Firestore: {e}")

# ИСПРАВЛЕНА: Объединенная функция get_current_mode_details
async def get_current_mode_details(user_id: int) -> dict:
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id) # Получаем ключ текущей МОДЕЛИ

    # Специальные режимы для конкретных моделей
    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    elif current_model_key == "custom_api_grok_3":
        return AI_MODES.get("grok_3_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    
    # Общий режим, если не выбран специфичный для модели
    # current_ai_mode из user_data - это ВЫБРАННЫЙ ПОЛЬЗОВАТЕЛЕМ РЕЖИМ (Универсальный, Творческий и т.д.)
    # Он не должен переопределяться только на основании модели, если для модели нет специального режима.
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
            # Если тип API не совпадает или отсутствует, обновляем его для консистентности
            if user_data.get('selected_api_type') != info.get("api_type"):
                user_data['selected_api_type'] = info.get("api_type")
                await set_user_data(user_id, user_data)
                logger.info(f"Updated api_type to '{info.get('api_type')}' for model_id '{selected_id}' for user {user_id}")
            return key

    logger.warning(f"Could not find key for model_id '{selected_id}' for user {user_id}. Falling back to default.")
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
        logger.warning(f"smart_truncate получила не строку: {type(text)}. Возвращаю как есть.")
        return str(text), False # Пытаемся преобразовать в строку
    if len(text) <= max_length:
        return text, False
    
    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)
    
    if adjusted_max_length <= 0: # Если суффикс длиннее максимальной длины
        return text[:max_length-len("...")] + "...", True # Просто обрезаем с "..."
        
    truncated_text = text[:adjusted_max_length]
    
    possible_cut_points = []
    # Ищем точки для "умного" обрезания (предпочтение двойному переносу строки)
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']: 
        pos = truncated_text.rfind(sep)
        if pos != -1:
            # Для знаков препинания с пробелом, обрезаем до знака
            actual_pos = pos if sep in ['. ', '! ', '? '] else pos + len(sep)
            if actual_pos > 0: # Убедимся, что не обрезаем в самом начале
                possible_cut_points.append(actual_pos)
                
    if possible_cut_points:
        cut_at = max(possible_cut_points)
        # Обрезаем, только если это не слишком короткий кусок
        if cut_at > adjusted_max_length * 0.3: # Например, не менее 30% от усеченного текста
            return text[:cut_at].strip() + suffix, True
            
    # Если не нашли подходящей точки или она слишком близко к началу, обрезаем жестко
    return truncated_text.strip() + suffix, True


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
        if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY:
            return model_config.get("subscription_daily_limit", 0)
        else:
            return model_config.get("limit_if_no_subscription", 0)
            
    if limit_type == "subscription_custom_pro":
        base_limit = 0
        if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY:
            base_limit = model_config.get("subscription_daily_limit", 0)
        else:
            base_limit = model_config.get("limit_if_no_subscription", 0)
        
        user_data = await get_user_data(user_id)
        # Бонус за подписку на канал добавляется к лимиту, если он для этой модели
        # и пользователь не профи (профи и так имеют свой лимит)
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
           not (current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY) and \
           user_data.get('claimed_news_bonus', False):
            bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
            # Важно: этот бонус суммируется с базовым лимитом модели, если он есть.
            # Если у модели лимит 0 для не-подписчиков, то будет только бонус.
            return base_limit + bonus_uses_left 
        return base_limit
        
    # Если is_limited False или тип лимита не распознан, считаем безлимитным для этой логики
    return model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0


async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_config or not model_config.get("is_limited"):
        return True, "", 0 # Не лимитировано

    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id) # Получаем user_data один раз

    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    is_profi_subscriber = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                is_profi_subscriber = True
        except Exception:
            pass
    
    # Проверка бонусных использований для NEWS_CHANNEL_BONUS_MODEL_KEY (если пользователь не профи)
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        # Если есть бонусные попытки, разрешаем запрос, даже если дневной лимит модели исчерпан.
        # Основной подсчет будет в increment_request_count
        logger.info(f"User {user_id} has bonus uses for {model_key}. Allowing via bonus.")
        return True, "bonus_available", 0 # Возвращаем 0, так как это бонус, а не счетчик модели

    # Получение и обновление счетчиков использования
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': '', 'count': 0})

    if model_daily_usage.get('date') != today_str:
        model_daily_usage = {'date': today_str, 'count': 0}
        # Не сохраняем здесь, сохраним при инкременте, если потребуется
    
    current_daily_count = model_daily_usage.get('count',0)
    actual_daily_limit_for_model_only = 0 # Лимит самой модели без бонуса
    
    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free":
        actual_daily_limit_for_model_only = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        actual_daily_limit_for_model_only = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
         actual_daily_limit_for_model_only = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    
    if current_daily_count >= actual_daily_limit_for_model_only:
        # Если лимит модели исчерпан, и это не случай с активным бонусом (проверен выше)
        message_parts = [f"Вы достигли дневного лимита ({current_daily_count}/{actual_daily_limit_for_model_only}) для {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not user_data.get('claimed_news_bonus', False):
                message_parts.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонусной генерации!')
            elif user_data.get('news_bonus_uses_left', 0) == 0: # Бонус был, но уже использован
                message_parts.append(f"ℹ️ Бонус за подписку на канал использован.")
        message_parts.append("Попробуйте завтра или рассмотрите возможность <a href='t.me/{context.bot.username}?start=subscribe'>💎 Подписки Профи</a> для увеличения лимитов.") # Пример ссылки на подписку
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
        except Exception:
            pass

    # Логика списания бонуса
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False):
        news_bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        if news_bonus_uses_left > 0:
            user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
            await set_user_data(user_id, user_data)
            logger.info(f"User {user_id} consumed bonus for {model_key}. Remaining bonus uses: {user_data['news_bonus_uses_left']}")
            # Если запрос был за счет бонуса, основной счетчик модели не увеличиваем,
            # если только не решено, что бонусные запросы тоже идут в общий счетчик для статистики (но не для лимита).
            # В данном случае, если бонус использован, основной счетчик модели не трогаем,
            # так как check_and_log_request_attempt уже разрешил запрос на основе бонуса.
            # Если же бонусные попытки закончились, то дальше пойдет обычный подсчет.
            return # Запрос был за счет бонуса

    # Инкремент основного счетчика модели
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0})

    if model_daily_usage.get('date') != today_str: # Сброс счетчика, если новый день
        model_daily_usage = {'date': today_str, 'count': 0}
    
    model_daily_usage['count'] += 1
    user_model_counts[model_key] = model_daily_usage
    all_daily_counts[str(user_id)] = user_model_counts
    bot_data['all_user_daily_counts'] = all_daily_counts
    await set_bot_data(bot_data)
    logger.info(f"User {user_id} daily count for {model_key} incremented to {model_daily_usage['count']}")


# --- Проверка, является ли текст кнопкой меню ---
def is_menu_button_text(text: str) -> bool:
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons:
        return True
    for menu_config in MENU_STRUCTURE.values(): # Итерация по значениям словаря MENU_STRUCTURE
        for item in menu_config.get("items", []):
            if item["text"] == text:
                return True
    return False

# --- Удаление пользовательских сообщений с командами или кнопками ---
async def try_delete_user_message(update: Update, user_id: int):
    # Эта функция может быть не нужна, если удаление происходит сразу в обработчиках
    if not update.message: return # Если это не сообщение (например, callback_query)

    chat_id = update.effective_chat.id
    user_data = await get_user_data(user_id)
    user_command_message_info = user_data.get('user_command_message', {})
    message_id_to_delete = user_command_message_info.get('message_id')
    timestamp_str = user_command_message_info.get('timestamp')

    if not message_id_to_delete or not timestamp_str:
        return

    try:
        msg_time = datetime.fromisoformat(timestamp_str)
        # Сообщения старше 48 часов не удаляем и чистим информацию о них
        if datetime.now(msg_time.tzinfo) - msg_time > timedelta(hours=48):
            logger.info(f"User message {message_id_to_delete} is older than 48 hours for deletion, clearing info.")
            user_data.pop('user_command_message', None)
            await set_user_data(user_id, user_data)
            return
    except ValueError: # Ошибка парсинга timestamp
        logger.warning("Invalid user message timestamp for deletion, clearing info.")
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)
        return
    
    # Попытка удалить само сообщение пользователя, которое было командой/кнопкой
    # Это нужно делать осторожно, чтобы не удалить обычные текстовые запросы к ИИ
    # Обычно удаляют сообщение с командой /start, /menu и т.д.
    # Если update.message.message_id это ID текущего сообщения, а не сохраненного, то логика неверна.
    # Предполагается, что user_command_message_info['message_id'] это ID сообщения, которое НАДО удалить.
    
    # В текущей логике user_command_message хранит ID последнего сообщения с командой/кнопкой.
    # И оно удаляется ПЕРЕД отправкой нового меню/ответа.
    # Это значит, что update.message.message_id в try_delete_user_message уже будет новым сообщением.
    # Логика user_command_message нужна, если мы хотим удалить *предыдущее* сообщение бота или пользователя.
    # Сейчас она удаляет сообщение, которое вызвало команду, перед ответом на нее.

    # Если нужно удалить сообщение, которое *вызвало* текущий обработчик (например, /start)
    # то это делается так: await update.message.delete()
    # Но это не всегда хорошо, т.к. пользователь может не понять, что произошло.

    # Логика ниже удаляет сообщение, ID которого сохранено в user_command_message
    # Это должно быть ID сообщения пользователя, которое было кнопкой/командой.
    try:
        await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_delete)
        logger.info(f"Deleted user's command/button message {message_id_to_delete}")
    except telegram.error.BadRequest as e:
        # Частая ошибка: "message to delete not found" или "message can't be deleted"
        logger.warning(f"Failed to delete user's command/button message {message_id_to_delete}: {e}")
    finally:
        # Очищаем информацию о сообщении, которое пытались удалить, независимо от результата
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)


# --- Функции для меню на клавиатуре ---
def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        # Возвращаем клавиатуру главного меню по умолчанию, если запрошенное не найдено
        logger.warning(f"Menu key '{menu_key}' not found. Falling back to main_menu keyboard.")
        menu = MENU_STRUCTURE["main_menu"] 
    
    keyboard_buttons = []
    # Для главного меню располагаем кнопки по две в ряд
    if menu_key == "main_menu":
        items = menu["items"]
        for i in range(0, len(items), 2):
            row = [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            keyboard_buttons.append(row)
    else: # Для подменю кнопки по одной в ряд
        keyboard_buttons = [[KeyboardButton(item["text"])] for item in menu["items"]]
    
    # Добавление кнопок навигации для подменю
    if menu.get("is_submenu", False): # Проверяем, является ли меню подменю
        nav_row = []
        if menu.get("parent"): # Если есть родитель, добавляем "Назад"
            nav_row.append(KeyboardButton("⬅️ Назад"))
        nav_row.append(KeyboardButton("🏠 Главное меню")) # Кнопка "Главное меню" всегда есть в подменю
        keyboard_buttons.append(nav_row)
    
    return ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True, one_time_keyboard=False)


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_key: str):
    # context не используется в этой функции, можно убрать если не планируется
    user_id = update.effective_user.id
    menu_config = MENU_STRUCTURE.get(menu_key)

    if not menu_config:
        logger.error(f"Menu configuration for key '{menu_key}' not found for user {user_id}.")
        await update.message.reply_text(
            "Ошибка: Меню не найдено. Пожалуйста, попробуйте /start.",
            reply_markup=generate_menu_keyboard("main_menu") # Фоллбэк на главное меню
        )
        return
    
    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key # Сохраняем текущее меню пользователя
    await set_user_data(user_id, user_data)
    
    menu_title = menu_config["title"]
    reply_markup = generate_menu_keyboard(menu_key)
    
    await update.message.reply_text(
        menu_title,
        reply_markup=reply_markup,
        parse_mode=None, # Явно указываем None, если HTML не используется
        disable_web_page_preview=True
    )
    logger.info(f"Sent menu '{menu_key}' to user {user_id}: '{menu_title}'")

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id) # Получаем существующие данные

    # Устанавливаем значения по умолчанию, если их нет
    user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    user_data.setdefault('current_menu', 'main_menu') # При старте всегда главное меню
    
    default_model_key_to_set = user_data.get('selected_model_key', DEFAULT_MODEL_KEY)
    default_model_conf = AVAILABLE_TEXT_MODELS.get(default_model_key_to_set, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

    user_data.setdefault('selected_model_id', default_model_conf["id"])
    user_data.setdefault('selected_api_type', default_model_conf["api_type"])
    
    # Если пользователь пришел по диплинку /start=subscribe
    if context.args and context.args[0] == 'subscribe':
        await show_subscription(update, user_id, called_from_start=True)
        # Не показываем главное меню сразу, т.к. покажем информацию о подписке
        return
    
    await set_user_data(user_id, user_data) # Сохраняем обновленные данные
    
    # Сохраняем ID сообщения /start для возможного удаления, если это кнопка
    # Это не очень хорошая практика - удалять сообщение /start пользователя
    # user_data['user_command_message'] = {
    #     'message_id': update.message.message_id,
    #     'timestamp': datetime.now().isoformat()
    # }
    # await set_user_data(user_id, user_data)
    # await try_delete_user_message(update, user_id) # Попытка удалить команду /start
    
    current_model_key = await get_current_model_key(user_id) # Используем обновленные данные
    mode_details = await get_current_mode_details(user_id)
    current_mode_name = mode_details['name']
    current_model_name = AVAILABLE_TEXT_MODELS[current_model_key]['name']

    greeting = (
        f"👋 Привет, {update.effective_user.first_name}!\n"
        f"Я твой ИИ-бот.\n\n"
        f"🧠 Режим: <b>{current_mode_name}</b>\n"
        f"⚙️ Модель: <b>{current_model_name}</b>\n\n"
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
    user_id = update.effective_user.id
    # Попытка удалить сообщение с командой /menu, если оно не было удалено ранее
    # if update.message: # Убедимся, что это сообщение
    #    try:
    #        await update.message.delete()
    #        logger.info(f"Deleted user's /menu command message {update.message.message_id}")
    #    except Exception as e:
    #        logger.warning(f"Could not delete /menu command message: {e}")
    await show_menu(update, context, "main_menu") # Передаем context


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # if update.message: await update.message.delete() # Опционально удалить команду
    await show_limits(update, user_id) # context здесь не нужен


async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # if update.message: await update.message.delete() # Опционально удалить команду
    await show_subscription(update, user_id) # context здесь не нужен


async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # if update.message: await update.message.delete() # Опционально удалить команду
    await claim_news_bonus_logic(update, user_id) # context здесь не нужен


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # if update.message: await update.message.delete() # Опционально удалить команду
    await show_help(update, user_id) # context здесь не нужен

# --- Отображение специфичных экранов ---
async def show_limits(update: Update, user_id: int):
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
            display_sub_level = "Подписка Профи (ошибка в дате окончания)"

    usage_text_parts = [
        "<b>📊 Ваши лимиты использования</b>",
        f"Текущий статус: <b>{display_sub_level}</b>",
        ""
    ]
    if subscription_active_profi:
         usage_text_parts.append("Вам доступны расширенные дневные лимиты.")
    else:
        usage_text_parts.append("Вы можете <a href='t.me/{context.bot.username}?start=subscribe'>💎 Улучшить до Профи</a> для увеличения лимитов.")


    usage_text_parts.append("\n<b>Дневные лимиты запросов:</b>")
    
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            # Получаем счетчик напрямую из bot_data
            user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage_info = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage_info['count'] if model_daily_usage_info.get('date') == today_str else 0
            
            actual_l = await get_user_actual_limit_for_model(user_id, model_k) # Этот лимит уже учитывает бонус
            
            bonus_note = ""
            # Показываем бонусную информацию только если модель является бонусной и бонус активен
            if model_k == NEWS_CHANNEL_BONUS_MODEL_KEY and \
               not subscription_active_profi and \
               user_data.get('claimed_news_bonus', False) and \
               user_data.get('news_bonus_uses_left', 0) > 0:
                bonus_uses = user_data.get('news_bonus_uses_left', 0)
                # Лимит actual_l уже включает бонус, так что current_c_display сравнивается с ним.
                # Отдельно показываем, сколько из них бонусных.
                bonus_note = f" (вкл. {bonus_uses} бонусн.)"
            
            usage_text_parts.append(f"▫️ {model_c['name']}: <b>{current_c_display} / {actual_l if actual_l != float('inf') else '∞'}</b>{bonus_note}")

    # Информация о бонусе за подписку на канал новостей
    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
        if bonus_model_config:
            bonus_model_name = bonus_model_config['name']
            bonus_info = ""
            if not subscription_active_profi: # Бонус актуален для не-профи
                if not user_data.get('claimed_news_bonus', False):
                    bonus_info = (f'\n🎁 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a>, '
                                  f'чтобы получить <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусных '
                                  f'генераций для модели {bonus_model_name}!')
                elif (bonus_uses_left := user_data.get('news_bonus_uses_left', 0)) > 0:
                    bonus_info = (f'\n🎁 У вас осталось <b>{bonus_uses_left}</b> бонусных генераций '
                                  f'для {bonus_model_name} (из <a href="{NEWS_CHANNEL_LINK}">канала</a>).')
                else: # Бонус был получен, но использован
                    bonus_info = (f'\nℹ️ Бонус за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a> '
                                  f'для {bonus_model_name} был использован.')
            usage_text_parts.append(bonus_info)
    
    # Кнопка "Купить подписку", если не активна
    if not subscription_active_profi:
         usage_text_parts.append("\nДля увеличения лимитов рассмотрите 💎 <b>Подписку Профи</b>.")


    final_usage_text = "\n".join(filter(None, usage_text_parts)) # Убираем пустые строки, если bonus_info был пустым
    
    # Определяем, из какого меню пользователь пришел, чтобы вернуться туда же
    current_menu_key = user_data.get('current_menu', 'limits_submenu')
    if current_menu_key != 'limits_submenu': # Если пришли не из самого меню лимитов
        current_menu_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu")

    reply_markup = generate_menu_keyboard(current_menu_key if current_menu_key == 'limits_submenu' else MENU_STRUCTURE.get(current_menu_key, {}).get("parent", "main_menu"))


    await update.message.reply_text(
        final_usage_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent limits message to user {user_id}")


async def claim_news_bonus_logic(update: Update, user_id: int):
    user = update.effective_user
    user_data = await get_user_data(user_id)

    # if update.message: # Удаляем сообщение с командой /bonus или кнопкой "Получить бонус"
    #     try: await update.message.delete()
    #     except: pass # Игнорируем ошибки удаления

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        text = "К сожалению, функция бонуса за подписку на данный момент не настроена администратором."
        await update.message.reply_text(text, reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        logger.info(f"Bonus feature not configured. Message sent to user {user_id}")
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        text = "Ошибка конфигурации: Бонусная модель не найдена. Пожалуйста, сообщите администратору."
        await update.message.reply_text(text, reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        logger.error("News bonus model key not found in AVAILABLE_TEXT_MODELS.")
        return
    bonus_model_name = bonus_model_config['name']

    # Проверка, не является ли пользователь уже Профи подписчиком
    bot_data = await get_bot_data()
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                await update.message.reply_text(
                    f"💎 Вы уже являетесь Профи подписчиком и имеете расширенные лимиты. Бонус за подписку на канал для вас не актуален.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
                    disable_web_page_preview=True
                )
                return
        except Exception:
            pass # Ошибка парсинга даты, продолжаем как будто нет подписки


    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        if uses_left > 0:
            reply_text = f'Вы уже активировали бонус. У вас осталось <b>{uses_left}</b> генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал новостей</a>).'
        else:
            reply_text = f'Бонус для {bonus_model_name} за подписку на <a href="{NEWS_CHANNEL_LINK}">канал новостей</a> уже был использован.'
        await update.message.reply_text(
            reply_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member_status.status in ['member', 'administrator', 'creator']:
            user_data['claimed_news_bonus'] = True
            user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await set_user_data(user_id, user_data)
            success_text = (f'🎉 Спасибо за подписку на <a href="{NEWS_CHANNEL_LINK}">канал новостей</a>! '
                            f'Вам начислено: <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусная генерация '
                            f'для модели {bonus_model_name}.')
            await update.message.reply_text(
                success_text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard('main_menu'), # Возврат в главное меню
                disable_web_page_preview=True
            )
            logger.info(f"User {user_id} claimed news bonus successfully.")
        else:
            fail_text = (f'Для получения бонуса, пожалуйста, подпишитесь на наш <a href="{NEWS_CHANNEL_LINK}">канал новостей</a>, '
                         f'а затем нажмите кнопку "🎁 Получить" еще раз.')
            reply_markup_inline = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📢 Перейти на канал {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
            ]])
            await update.message.reply_text(
                fail_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup_inline, # Предлагаем перейти на канал
                disable_web_page_preview=True
            )
    except telegram.error.BadRequest as e:
        # Частая ошибка - бот не админ в канале или канал приватный без бота
        logger.error(f"BadRequest error checking channel membership for {NEWS_CHANNEL_USERNAME}: {e}")
        reply_message_on_error = (f'К сожалению, не удалось проверить вашу подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>. '
                                  f'Убедитесь, что вы подписаны, и попробуйте снова через некоторое время. '
                                  f'Если проблема сохраняется, возможно, бот не имеет необходимых прав в канале.')
        reply_markup_inline = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📢 Перейти на канал {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
        ]])
        await update.message.reply_text(
            reply_message_on_error,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup_inline,
            disable_web_page_preview=True
        )

async def show_subscription(update: Update, user_id: int, called_from_start: bool = False):
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    
    sub_text_parts = ["<b>💎 Подписка Профи</b>\n"]
    is_active_profi = False

    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                sub_text_parts.append(f"Поздравляем! Ваша подписка Профи активна до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
                sub_text_parts.append("Вы пользуетесь всеми преимуществами, включая расширенные лимиты.")
                is_active_profi = True
            else:
                sub_text_parts.append(f"Срок вашей подписки Профи истек <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
        except Exception:
            sub_text_parts.append("Не удалось проверить дату окончания вашей подписки. Пожалуйста, свяжитесь с поддержкой, если считаете это ошибкой.")

    if not is_active_profi:
        sub_text_parts.append("Получите максимум от нашего ИИ-ассистента с подпиской Профи!")
        sub_text_parts.append("\n<b>Преимущества подписки Профи:</b>")
        sub_text_parts.append(f"▫️ Значительно увеличенные дневные лимиты на все модели.")
        sub_text_parts.append(f"▫️ Доступ к продвинутым моделям, таким как Gemini Pro и Grok 3, с большим количеством запросов.")
        # sub_text_parts.append(f"▫️ Приоритетная поддержка (если применимо).")
        sub_text_parts.append(f"\nСтоимость подписки: <b>[СУММА] [ВАЛЮТА]</b> за 30 дней.") # ЗАМЕНИТЕ НА ВАШУ ЦЕНУ
        sub_text_parts.append(f"\nДля оформления или продления подписки, пожалуйста, нажмите кнопку «Купить» или используйте команду /pay.")
    
    final_sub_text = "\n".join(sub_text_parts)
    
    # Клавиатура для покупки
    keyboard = []
    if not is_active_profi:
        # TODO: Заменить 'YOUR_BOT_USERNAME' на имя пользователя вашего бота для команды /pay
        # keyboard.append([InlineKeyboardButton("💳 Купить Подписку Профи (30 дней)", callback_data="buy_pro_sub_30d")])
        # Или, если вы используете команду /pay для начала процесса оплаты:
         keyboard.append([InlineKeyboardButton("💳 Купить Подписку Профи (30 дней)", callback_data="initiate_payment_profi")])


    # Кнопка возврата в меню
    # Если вызвано из /start, то главное меню. Иначе - из текущего подменю подписок.
    parent_menu_key = 'main_menu' if called_from_start else user_data.get('current_menu', 'subscription_submenu')
    # reply_markup_replykeyboard = generate_menu_keyboard(parent_menu_key) # Это для ReplyKeyboard

    # Используем InlineKeyboard для кнопки "Купить" и ReplyKeyboard для навигации
    inline_reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await update.message.reply_text(
        final_sub_text,
        parse_mode=ParseMode.HTML,
        reply_markup=inline_reply_markup, # Используем InlineKeyboard для кнопки покупки
        disable_web_page_preview=True
    )
    # Если нужна и ReplyKeyboard для навигации (но это может конфликтовать с инлайн кнопкой покупки)
    # То после сообщения с инлайн кнопкой можно отправить еще одно с ReplyKeyboard
    if not inline_reply_markup: # Если кнопки "Купить" нет (уже активна подписка)
        await update.message.reply_text("Меню навигации:", reply_markup=generate_menu_keyboard(parent_menu_key))


    logger.info(f"Sent subscription info to user {user_id}")


async def show_help(update: Update, user_id: int):
    user_data = await get_user_data(user_id)
    # if update.message: await update.message.delete() # Опционально

    help_text = (
        "<b>❓ Помощь по боту</b>\n\n"
        "Привет! Я ваш многофункциональный ИИ-ассистент.\n"
        "Вот основные возможности:\n"
        "▫️ <b>Общение с ИИ</b>: Просто напишите ваш вопрос или задачу в чат.\n"
        "▫️ <b>Режимы ИИ</b> (/menu -> 🤖 Режимы ИИ): Выберите подходящий режим для вашей задачи (Универсальный, Творческий, Аналитик и др.).\n"
        "▫️ <b>Модели ИИ</b> (/menu -> ⚙️ Модели ИИ): Переключайтесь между различными ИИ-моделями (Gemini, Grok и др.).\n"
        "▫️ <b>Лимиты</b> (/usage или /menu -> 📊 Лимиты): Узнайте ваши текущие дневные лимиты запросов.\n"
        "▫️ <b>Бонус</b> (/bonus или /menu -> 🎁 Бонус): Получите бонусные генерации за подписку на наш новостной канал.\n"
        "▫️ <b>Подписка Профи</b> (/subscribe или /menu -> 💎 Подписка): Оформите подписку для снятия ограничений и получения доступа ко всем возможностям.\n\n"
        "<b>Основные команды:</b>\n"
        "▫️ /start - Перезапустить бота и показать приветствие.\n"
        "▫️ /menu - Открыть главное меню.\n"
        "▫️ /usage - Показать текущие лимиты.\n"
        "▫️ /subscribe - Информация о подписке Профи.\n"
        "▫️ /bonus - Получить бонус за подписку на канал.\n"
        "▫️ /help - Показать это сообщение помощи.\n\n"
        "Если у вас возникли проблемы или вопросы, обращайтесь к администратору." # TODO: Добавить контакт администратора
    )
    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'help_submenu'))

    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    logger.info(f"Sent help message to user {user_id}")

# --- Обработчик кнопок меню ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    
    user_data = await get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', 'main_menu') # Текущее меню пользователя
    
    # Сначала проверяем, является ли текст кнопкой из ТЕКУЩЕГО активного меню или навигационной кнопкой
    current_menu_config = MENU_STRUCTURE.get(current_menu_key, MENU_STRUCTURE['main_menu'])
    selected_item = next((item for item in current_menu_config.get("items", []) if item["text"] == button_text), None)

    is_navigation_button = False
    if button_text == "⬅️ Назад" and current_menu_config.get("parent"):
        selected_item = {"action": "navigate_back", "target": current_menu_config["parent"]}
        is_navigation_button = True
    elif button_text == "🏠 Главное меню":
        selected_item = {"action": "navigate_home", "target": "main_menu"}
        is_navigation_button = True

    # Если кнопка не найдена в текущем меню и это не навигация,
    # проверяем, не является ли это кнопкой из другого меню (менее приоритетно)
    if not selected_item:
        if not is_menu_button_text(button_text): # Проверяем, является ли текст ВООБЩЕ кнопкой меню
            logger.info(f"Text '{button_text}' from user {user_id} is not a menu button, skipping to handle_text.")
            await handle_text(update, context) # Передаем в обработчик текста
            return
        
        # Если это кнопка, но не из текущего меню - возможно, пользователь нажал старую кнопку
        # Попробуем найти ее глобально, но это может привести к неожиданной навигации
        found_globally = False
        for menu_key_iter, menu_conf_iter in MENU_STRUCTURE.items():
            item_found = next((item for item in menu_conf_iter.get("items", []) if item["text"] == button_text), None)
            if item_found:
                logger.warning(f"Button '{button_text}' from user {user_id} (current menu: {current_menu_key}) was found in a different menu '{menu_key_iter}'. Processing its action.")
                selected_item = item_found
                # Если кнопка найдена в другом меню, возможно, стоит перенаправить пользователя в то меню или в главное
                # current_menu_key = menu_key_iter # Опасно, может запутать пользователя
                # await show_menu(update, context, current_menu_key) # Показать меню, где кнопка была найдена
                # return
                break
        if not selected_item: # Если все же не нашли
            logger.warning(f"Button '{button_text}' from user {user_id} (current menu: {current_menu_key}) not matched with any action.")
            await update.message.reply_text("Действие для этой кнопки не определено в текущем контексте. Пожалуйста, используйте актуальное меню.",
                                            reply_markup=generate_menu_keyboard(current_menu_key))
            return
            
    # Удаляем сообщение пользователя, если это была кнопка меню
    if update.message:
        try:
            await update.message.delete()
            logger.info(f"Deleted user's button message '{button_text}' (ID: {update.message.message_id})")
        except Exception as e:
            logger.warning(f"Could not delete user's button message: {e}")


    action = selected_item["action"]
    target = selected_item["target"]
    logger.info(f"User {user_id} pressed button '{button_text}'. Action: '{action}', Target: '{target}' in menu '{current_menu_key if is_navigation_button else 'found_globally_or_current'}'")

    if action == "submenu":
        await show_menu(update, context, target)
    elif action == "navigate_back":
        await show_menu(update, context, target) # target здесь это parent_menu
    elif action == "navigate_home":
        await show_menu(update, context, "main_menu")
    elif action == "set_agent":
        return_menu_key = current_menu_config.get("parent", "main_menu")
        if target in AI_MODES and target not in ["gemini_pro_custom_mode", "grok_3_custom_mode"]:
            user_data['current_ai_mode'] = target
            await set_user_data(user_id, user_data)
            mode_details = AI_MODES[target]
            new_text = f"🤖 Режим ИИ изменён на: <b>{mode_details['name']}</b>\n\n{mode_details['welcome']}"
        # Убрана логика для target == "gemini_pro_custom_mode", т.к. эти режимы не выбираются напрямую из меню агентов
        else:
            new_text = "⚠️ Ошибка: Такой режим ИИ не найден или недоступен для прямого выбора."
            logger.warning(f"Attempt to set invalid AI agent '{target}' by user {user_id}.")
        
        await update.message.reply_text(
            new_text, parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(return_menu_key), # Возвращаемся в родительское меню
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu_key # Обновляем текущее меню пользователя
        await set_user_data(user_id, user_data)

    elif action == "set_model":
        return_menu_key = current_menu_config.get("parent", "main_menu")
        if target in AVAILABLE_TEXT_MODELS:
            model_config_selected = AVAILABLE_TEXT_MODELS[target]
            user_data.update({
                'selected_model_id': model_config_selected["id"],
                'selected_api_type': model_config_selected["api_type"],
                # 'current_ai_mode' должен меняться только если для модели есть специальный режим
                # и пользователь его не выбирал вручную (это делает get_current_mode_details)
            })
            await set_user_data(user_id, user_data) # Сохраняем выбор модели
            
            # Обновляем информацию о лимитах для выбранной модели
            bot_data_local = await get_bot_data() # Получаем свежие данные бота
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts_local = bot_data_local.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage_local = user_model_counts_local.get(target, {'date': '', 'count': 0})
            current_c_display_local = model_daily_usage_local['count'] if model_daily_usage_local.get('date') == today_str else 0
            actual_l_local = await get_user_actual_limit_for_model(user_id, target) # Лимит уже с бонусом
            
            limit_str = f"Лимит: {current_c_display_local}/{actual_l_local if actual_l_local != float('inf') else '∞'} в день"
            
            # Определяем, какой режим будет использоваться с этой моделью
            effective_mode_details = await get_current_mode_details(user_id) # Эта функция учтет спец. режим для модели
            
            new_text = (f"⚙️ Модель ИИ изменена на: <b>{model_config_selected['name']}</b>.\n"
                        f"🧠 Активный режим для этой модели: <b>{effective_mode_details['name']}</b>.\n"
                        f"{limit_str}")
        else:
            new_text = "⚠️ Ошибка: Такая модель ИИ не найдена."
            logger.warning(f"Attempt to set invalid AI model '{target}' by user {user_id}.")

        await update.message.reply_text(
            new_text, parse_mode=ParseMode.HTML,
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
        logger.warning(f"Unknown menu action '{action}' for button '{button_text}' by user {user_id}.")
        await update.message.reply_text("Неизвестное действие.", reply_markup=generate_menu_keyboard(current_menu_key))


# --- Обработчик текстовых сообщений ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Эта проверка уже есть в menu_button_handler, который вызывается первым в группе.
    # Если menu_button_handler не распознал текст как кнопку ИЗ ЕГО КОНТЕКСТА,
    # он может передать управление сюда. Но если is_menu_button_text глобально true,
    # то это все равно кнопка, и ее не нужно обрабатывать как AI запрос.
    if is_menu_button_text(user_message):
        logger.info(f"Text '{user_message}' from user {user_id} was identified globally as a menu button, but not handled by menu_button_handler in its current context. Ignoring for AI request.")
        # Можно отправить сообщение об ошибке или просто игнорировать
        # await update.message.reply_text("Пожалуйста, используйте кнопки из активного меню.", reply_markup=generate_menu_keyboard((await get_user_data(user_id)).get('current_menu','main_menu')))
        return

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        logger.info(f"Text '{user_message}' from user {user_id} is too short for AI request.")
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            "Ваш запрос слишком короткий. Пожалуйста, сформулируйте его более подробно или используйте меню.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
        )
        return

    logger.info(f"Processing AI request from user {user_id}: '{user_message[:100]}...'")

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key) # Не нужно значение по умолчанию, т.к. get_current_model_key его обеспечивает
    
    if not model_config: # На всякий случай, если get_current_model_key вернул что-то не то
        logger.error(f"Critical error: model_config not found for key {current_model_key} for user {user_id}.")
        await update.message.reply_text("Произошла критическая ошибка при выборе модели. Пожалуйста, попробуйте /start.",
                                        reply_markup=generate_menu_keyboard('main_menu'))
        return

    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key)

    if not can_proceed:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            limit_message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        logger.info(f"User {user_id} reached limit for model {current_model_key}. Message: {limit_message}")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id) # Получаем актуальный режим (может быть специфичным для модели)
    system_prompt = mode_details["prompt"]
    # full_prompt для genai, для custom_http_api системный промпт передается отдельно
    
    response_text = "К сожалению, не удалось получить ответ от ИИ." # Значение по умолчанию

    if model_config["api_type"] == "google_genai":
        full_prompt_for_genai = f"{system_prompt}\n\n**Пользовательский запрос:**\n{user_message}"
        genai_model = genai.GenerativeModel(
            model_name=model_config["id"],
            generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB}
            # TODO: Рассмотреть добавление safety_settings, если API это поддерживает и нужно
        )
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: genai_model.generate_content(full_prompt_for_genai)
            )
            if response.text:
                response_text = response.text.strip()
            else: # Если response.text пустой
                logger.warning(f"Google GenAI for user {user_id}, model {model_config['id']} returned empty text. Parts: {response.parts}")
                # Попытка извлечь из parts, если это возможно и структура известна
                try:
                    # Проверяем, есть ли у ответа атрибут parts и он не пустой
                    if hasattr(response, 'parts') and response.parts:
                        all_text_parts = [part.text for part in response.parts if hasattr(part, 'text')]
                        if all_text_parts:
                            response_text = "\n".join(all_text_parts).strip()
                        else: # Если в parts нет текстовых частей
                            response_text = "Ответ от ИИ не содержит текстовой информации."
                    elif hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                         response_text = f"Запрос заблокирован фильтрами безопасности: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
                         logger.warning(f"Google GenAI request blocked for user {user_id}. Reason: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}")
                    else: # Если нет ни text, ни parts, ни block_reason
                        response_text = "Получен пустой ответ от ИИ."

                except Exception as e_parts:
                    logger.error(f"Error processing Google GenAI parts for user {user_id}: {e_parts}")
                    response_text = "Ошибка при обработке сложного ответа от ИИ."
            
            if not response_text: # Если после всех попыток текст пуст
                 response_text = "ИИ не дал ответа на данный запрос."


        except google.api_core.exceptions.ResourceExhausted:
            response_text = "Лимит API Google GenAI исчерпан на стороне провайдера. Пожалуйста, попробуйте позже."
            logger.error(f"Google GenAI ResourceExhausted for user {user_id}, model {model_config['id']}")
        except Exception as e: # Другие ошибки при работе с google.generativeai
            response_text = f"Произошла ошибка при обращении к Google GenAI: {type(e).__name__}. Попробуйте позже."
            logger.error(f"Google GenAI API error for user {user_id}, model {model_config['id']}: {traceback.format_exc()}")

    elif model_config["api_type"] == "custom_http_api":
        api_key_var_name = model_config.get("api_key_var_name")
        if not api_key_var_name:
            logger.error(f"api_key_var_name не указан для custom_http_api модели {current_model_key}")
            response_text = "Ошибка конфигурации API ключа для этой модели."
        else:
            api_key = globals().get(api_key_var_name) # Получаем ключ из глобальных переменных по имени
            if not api_key:
                 logger.error(f"API ключ {api_key_var_name} не найден или пуст для модели {current_model_key}")
                 response_text = "API ключ для этой модели не настроен корректно."
            else:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json" # Некоторые API требуют это
                }
                payload = {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "model": model_config["id"],
                    # Параметры, специфичные для API провайдера (gen-api.ru)
                    "is_sync": True, # Для Grok это важно
                    "max_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB, # Может называться иначе у провайдера
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "n": 1,
                    # "stream": False, # Явно указываем, если нужно
                }
                
                try:
                    api_response = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=30) # Таймаут 30 секунд
                    )
                    api_response.raise_for_status() # Проверка на HTTP ошибки (4xx, 5xx)
                    response_data = api_response.json() # Декодирование JSON
                    
                    extracted_text_custom = None
                    if model_config["id"] == "grok-3-beta":
                        # Сначала пробуем "output" - основной ключ для gen-api.ru по их док-ции (для callback)
                        text_candidate = response_data.get("output")
                        if text_candidate and isinstance(text_candidate, str): # Убедимся, что это строка
                            extracted_text_custom = text_candidate.strip()
                        elif isinstance(text_candidate, dict) and "text" in text_candidate : # Иногда ответ может быть вложенным
                            extracted_text_custom = str(text_candidate.get("text","")).strip()

                        if not extracted_text_custom: # Если в "output" пусто или не строка, пробуем "text"
                            text_candidate_alt = response_data.get("text")
                            if text_candidate_alt and isinstance(text_candidate_alt, str):
                                extracted_text_custom = text_candidate_alt.strip()
                        
                        # Дополнительная проверка на случай, если API вернуло статус ошибки в JSON
                        if response_data.get("status") and response_data.get("status") not in ["success", "completed", "finished"] : # Добавьте другие успешные статусы от gen-api
                            logger.warning(f"Grok API ({model_config['endpoint']}) returned non-success status: {response_data.get('status')}. Response: {response_data}")
                            if not extracted_text_custom: # Если текст не извлечен и статус плохой
                                extracted_text_custom = f"API вернуло статус: {response_data.get('status')}. Подробности: {response_data.get('detail') or response_data.get('error') or ''}"


                    elif model_config["id"] == "gemini-2.5-pro-preview-03-25": # Ваш ID для Gemini Pro
                        # Предполагаем, что для Gemini Pro текст в поле "text" (т.к. он работал)
                        text_candidate = response_data.get("text")
                        if text_candidate and isinstance(text_candidate, str):
                            extracted_text_custom = text_candidate.strip()
                        elif isinstance(text_candidate, dict) and "text" in text_candidate :
                            extracted_text_custom = str(text_candidate.get("text","")).strip()

                        if not extracted_text_custom: # Если в "text" пусто, попробуем и "output"
                            text_candidate_alt = response_data.get("output")
                            if text_candidate_alt and isinstance(text_candidate_alt, str):
                                 extracted_text_custom = text_candidate_alt.strip()


                    if extracted_text_custom:
                        response_text = extracted_text_custom
                    else:
                        response_text = "Ответ от Custom API получен, но текст извлечь не удалось."
                        logger.warning(f"Could not extract text from Custom API response for model {model_config['id']}. Response data: {response_data}")

                except requests.exceptions.Timeout:
                    response_text = "Превышено время ожидания ответа от сервера ИИ. Пожалуйста, попробуйте позже."
                    logger.error(f"Custom API request timeout for user {user_id}, model {model_config['id']}.")
                except requests.exceptions.RequestException as e:
                    response_text = f"Ошибка сети при обращении к Custom API. Пожалуйста, попробуйте позже."
                    logger.error(f"Custom API network error for user {user_id}, model {model_config['id']}: {e}")
                except json.JSONDecodeError as e:
                    response_text = "Получен некорректный ответ от сервера ИИ (не JSON). Пожалуйста, попробуйте позже."
                    logger.error(f"Custom API JSON decode error for user {user_id}, model {model_config['id']}: {e}. Response: {api_response.text[:500] if 'api_response' in locals() else 'N/A'}")
                except Exception as e: # Общий отлов других ошибок
                    response_text = f"Произошла непредвиденная ошибка при работе с Custom API. Пожалуйста, попробуйте позже."
                    logger.error(f"Unexpected Custom API error for user {user_id}, model {model_config['id']}: {traceback.format_exc()}")
    else:
        response_text = "Выбрана модель с неизвестным типом API. Пожалуйста, сообщите администратору."
        logger.error(f"Unknown api_type '{model_config.get('api_type')}' for model_key '{current_model_key}' for user {user_id}")


    final_response_text, was_truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"Response for user {user_id} (model {current_model_key}) was truncated.")

    await increment_request_count(user_id, current_model_key)
    
    user_data_for_reply_markup = await get_user_data(user_id) # Получаем свежие данные для markup
    await update.message.reply_text(
        final_response_text,
        parse_mode=None, # Используйте ParseMode.HTML или MARKDOWN, если форматируете текст от ИИ
        reply_markup=generate_menu_keyboard(user_data_for_reply_markup.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Sent AI response to user {user_id} using model {current_model_key}. Truncated: {was_truncated}. Response start: '{final_response_text[:100]}...'")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # TODO: Добавить более строгую проверку payload, если у вас разные типы подписок
    if PRO_SUBSCRIPTION_LEVEL_KEY not in query.invoice_payload :
        await query.answer(ok=False, error_message="Неверный тип подписки в запросе.")
        logger.warning(f"PreCheckoutQuery with invalid payload: {query.invoice_payload} from user {query.from_user.id}")
        return
    await query.answer(ok=True)
    logger.info(f"PreCheckoutQuery OK for user {query.from_user.id}, payload: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    
    # TODO: Убедитесь, что payload соответствует тому, что вы ожидаете
    # Например, если payload содержит "subscription_profi_access_v1_30days"
    if PRO_SUBSCRIPTION_LEVEL_KEY in payment.invoice_payload: # Простая проверка
        days_subscribed = 30 # По умолчанию 30 дней, или извлеките из payload, если там есть
        # if "_30days" in payment.invoice_payload: days_subscribed = 30
        # elif "_90days" in payment.invoice_payload: days_subscribed = 90
        
        valid_until = datetime.now().astimezone() + timedelta(days=days_subscribed)
        
        bot_data = await get_bot_data()
        user_subscriptions = bot_data.get('user_subscriptions', {})
        
        # Обновляем или добавляем подписку
        user_subscriptions[str(user_id)] = {
            'level': PRO_SUBSCRIPTION_LEVEL_KEY,
            'valid_until': valid_until.isoformat(),
            'telegram_payment_charge_id': payment.telegram_payment_charge_id, # Сохраняем ID платежа
            'provider_payment_charge_id': payment.provider_payment_charge_id,
            'currency': payment.currency,
            'total_amount': payment.total_amount
        }
        bot_data['user_subscriptions'] = user_subscriptions
        await set_bot_data(bot_data)
        
        text = (f"🎉 Поздравляем! Ваша подписка <b>Профи</b> успешно активирована.\n"
                f"Срок действия: до <b>{valid_until.strftime('%d.%m.%Y %H:%M:%S %Z')}</b>.\n"
                f"Наслаждайтесь всеми преимуществами и расширенными лимитами!")
        
        user_data = await get_user_data(user_id) # Для reply_markup
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard('main_menu'), # Отправляем в главное меню
            disable_web_page_preview=True
        )
        logger.info(f"Successful payment for {PRO_SUBSCRIPTION_LEVEL_KEY} processed for user {user_id}. Valid until: {valid_until.isoformat()}")
        
        # Опционально: отправить уведомление администратору
        # admin_message = (f"Пользователь {user_id} ({update.effective_user.full_name} @{update.effective_user.username}) "
        #                  f"оплатил подписку Профи. Сумма: {payment.total_amount / 100} {payment.currency}.")
        # await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=admin_message)

    else:
        logger.warning(f"Successful payment with unhandled payload: {payment.invoice_payload} from user {user_id}")
        await update.message.reply_text("Платеж получен, но не удалось определить тип подписки. Свяжитесь с поддержкой.")


# Глобальный обработчик ошибок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Сбор информации об ошибке
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    error_message_for_admin = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update.to_dict() if isinstance(update, Update) else str(update), indent=2, ensure_ascii=False))}</pre>\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    
    # Отправка сообщения администратору (если YOUR_ADMIN_ID определен)
    if YOUR_ADMIN_ID:
        try:
            # Убедимся, что сообщение не слишком длинное для Telegram
            max_len = MAX_MESSAGE_LENGTH_TELEGRAM
            if len(error_message_for_admin) > max_len:
                 chunks = [error_message_for_admin[i:i + max_len] for i in range(0, len(error_message_for_admin), max_len)]
                 for chunk in chunks:
                    await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=chunk, parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=error_message_for_admin, parse_mode=ParseMode.HTML)
        except Exception as e_admin:
            logger.error(f"Failed to send error message to admin: {e_admin}")

    # Ответ пользователю (если это возможно и уместно)
    if isinstance(update, Update) and update.effective_message:
        try:
            user_id = update.effective_user.id
            user_data = await get_user_data(user_id) # Для клавиатуры
            await update.effective_message.reply_text(
                "Произошла внутренняя ошибка. Мы уже работаем над ее устранением. "
                "Пожалуйста, попробуйте позже или воспользуйтесь командой /start.",
                reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
            )
        except Exception as e_user_reply:
             logger.error(f"Failed to send error reply to user: {e_user_reply}")


async def main():
    # Установка YOUR_BOT_USERNAME для ссылок на подписку (если используется)
    # bot_info = await Application.builder().token(TOKEN).build().bot.get_me()
    # context.bot_data['bot_username'] = bot_info.username # Это нужно делать в другом месте или передавать

    app = Application.builder().token(TOKEN).build()

    # Добавление обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", open_menu_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("subscribe", subscribe_info_command))
    # TODO: Добавить команду /pay для инициации платежа, если не через callback_data
    # app.add_handler(CommandHandler("pay", initiate_payment_command)) # Пример

    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Обработчик кнопок меню должен идти ПЕРЕД обработчиком текста
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    # Обработчик текста для AI запросов
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Глобальный обработчик ошибок
    app.add_error_handler(error_handler)

    commands = [
        BotCommand("start", "🚀 Перезапустить бота / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Мои лимиты"),
        BotCommand("subscribe", "💎 Информация о Подписке Профи"),
        BotCommand("bonus", "🎁 Получить бонус за канал"),
        BotCommand("help", "❓ Помощь по боту")
    ]
    try:
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands updated successfully.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")


    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    import html # Для error_handler

    # Конфигурация Google Gemini API
    if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
        logger.warning("Google Gemini API key не установлен корректно или используется ключ-заглушка.")
    else:
        try:
            genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API успешно сконфигурирован.")
        except Exception as e:
            logger.error(f"Не удалось сконфигурировать Google Gemini API: {str(e)}")

    if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY:
        logger.warning("Custom Gemini Pro API key не установлен корректно или используется ключ-заглушка.")

    if not CUSTOM_GROK_3_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GROK_3_API_KEY or "sk-" not in CUSTOM_GROK_3_API_KEY:
        logger.warning("Custom Grok 3 API key не установлен корректно или используется ключ-заглушка.")
    
    if not PAYMENT_PROVIDER_TOKEN or "YOUR_PAYMENT_PROVIDER_TOKEN" in PAYMENT_PROVIDER_TOKEN: # Пример проверки токена платежей
        logger.warning("Токен провайдера платежей (PAYMENT_PROVIDER_TOKEN) не установлен или используется заглушка.")

    asyncio.run(main())
