import telegram
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand, ParseMode, ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
import google.generativeai as genai
import google.api_core.exceptions
import requests
import logging
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import AsyncClient
from gemini_pro_handler import query_gemini_pro, GEMINI_PRO_CONFIG
from grok_3_handler import query_grok_3, GROK_3_CONFIG
from bonus_handler import claim_news_bonus_logic, try_delete_user_message

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
YOUR_ADMIN_ID = 489230152

MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000
MIN_AI_REQUEST_LENGTH = 4

# Лимиты запросов
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
DEFAULT_FREE_REQUESTS_GROK_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY = 25
DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 3
DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY = 25
PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"

# Настройки бонусов
NEWS_CHANNEL_USERNAME = "@timextech"
NEWS_CHANNEL_LINK = "https://t.me/timextech"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
NEWS_CHANNEL_BONUS_GENERATIONS = 1

# --- АГЕНТЫ И МОДЕЛИ ИИ ---
AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент. "
            "Отвечай на вопросы, генерируй текст, анализируй информацию. "
            "Будь вежлив, точен, структурируй ответы с абзацами и списками. "
            "Оформляй заголовки, если нужно, и завершай списки."
        ),
        "welcome": "Активирован агент 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый",
        "prompt": (
            "Ты — Gemini 2.5 Pro. "
            "Предоставляй точные, развернутые ответы. "
            "Структурируй текст с абзацами и списками."
        ),
        "welcome": "Активирован агент 'Продвинутый'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "Творческий",
        "prompt": (
            "Ты — креативный ИИ-партнёр. "
            "Помогай создавать тексты, идеи, стихи. "
            "Используй выразительный язык, завершай произведения."
        ),
        "welcome": "Агент 'Творческий' готов! Над чем работаем?"
    },
    "analyst": {
        "name": "Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик. "
            "Анализируй данные, предоставляй структурированные выводы. "
            "Укажи, если данных недостаточно."
        ),
        "welcome": "Агент 'Аналитик' активирован. Какую задачу проанализировать?"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с юмором. "
            "Отвечай остроумно, добавляй шутки, сохраняй полезность."
        ),
        "welcome": "Агент 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

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
    "custom_api_gemini_2_5_pro": GEMINI_PRO_CONFIG,
    "custom_api_grok_3": GROK_3_CONFIG,
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

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE ---
try:
    firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_credentials:
        cred = credentials.Certificate(json.loads(firebase_credentials))
    else:
        cred = credentials.Certificate("gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации Firebase: {e}")
    db = None

# --- РАБОТА С FIRESTORE ---
async def get_user_data(user_id: int) -> dict:
    """Получение данных пользователя из Firestore."""
    if not db:
        return {}
    doc_ref = db.collection("users").document(str(user_id))
    doc = await asyncio.to_thread(doc_ref.get)
    return doc.to_dict() or {}

async def set_user_data(user_id: int, data: dict):
    """Сохранение данных пользователя в Firestore."""
    if not db:
        return
    doc_ref = db.collection("users").document(str(user_id))
    await asyncio.to_thread(doc_ref.set, data, merge=True)
    logger.info(f"Обновлены данные пользователя {user_id}")

async def get_bot_data() -> dict:
    """Получение глобальных данных бота из Firestore."""
    if not db:
        return {}
    doc_ref = db.collection("bot_data").document("data")
    doc = await asyncio.to_thread(doc_ref.get)
    return doc.to_dict() or {}

async def set_bot_data(data: dict):
    """Сохранение глобальных данных бота в Firestore."""
    if not db:
        return
    doc_ref = db.collection("bot_data").document("data")
    await asyncio.to_thread(doc_ref.set, data, merge=True)
    logger.info("Обновлены данные бота")

# --- УПРАВЛЕНИЕ РЕЖИМАМИ И МОДЕЛЯМИ ---
async def get_current_mode_details(user_id: int) -> dict:
    """Получение текущего режима ИИ для пользователя."""
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id)
    mode_key = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)

    if mode_key not in AI_MODES:
        mode_key = DEFAULT_AI_MODE_KEY
        user_data['current_ai_mode'] = mode_key
        await set_user_data(user_id, user_data)
        logger.info(f"Сброшен режим для пользователя {user_id}")

    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

async def get_current_model_key(user_id: int) -> str:
    """Получение текущей модели ИИ для пользователя."""
    user_data = await get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if 'selected_api_type' not in user_data or user_data['selected_api_type'] != info.get("api_type"):
                user_data['selected_api_type'] = info.get("api_type")
                await set_user_data(user_id, user_data)
            return key

    user_data.update({
        'selected_model_id': DEFAULT_MODEL_ID,
        'selected_api_type': AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["api_type"]
    })
    await set_user_data(user_id, user_data)
    logger.warning(f"Модель не найдена для ID {selected_id}. Установлена модель по умолчанию.")
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int) -> dict:
    """Получение деталей текущей модели."""
    model_key = await get_current_model_key(user_id)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

# --- УПРАВЛЕНИЕ ЛИМИТАМИ ---
async def get_user_actual_limit_for_model(user_id: int, model_key: str) -> int:
    """Получение дневного лимита запросов для модели."""
    model_config = AVAILABLE_TEXT_MODELS.get(model_key, {})
    if not model_config.get("is_limited", False):
        return float('inf')

    bot_data = await get_bot_data()
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    is_subscribed = False

    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                is_subscribed = user_subscription.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY
        except Exception as e:
            logger.error(f"Ошибка проверки подписки для {user_id}: {e}")

    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free":
        return model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        return model_config.get("subscription_daily_limit", 0) if is_subscribed else model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit", 0) if is_subscribed else model_config.get("limit_if_no_subscription", 0)
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
            user_data = await get_user_data(user_id)
            if user_data.get('claimed_news_bonus', False):
                return base_limit + user_data.get('news_bonus_uses_left', 0)
        return base_limit
    return 0

async def check_and_log_request_attempt(user_id: int, model_key: str) -> tuple[bool, str, int]:
    """Проверка лимитов и логирование попытки запроса."""
    today = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key, {})
    if not model_config.get("is_limited"):
        return True, "", 0

    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    is_profi = user_subscription.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription.get('valid_until') and \
               datetime.fromisoformat(user_subscription['valid_until']).date() >= datetime.now().date()

    # Проверка бонусных генераций
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user_data.get('claimed_news_bonus', False) and user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"Пользователь {user_id} использует бонус для {model_key}.")
        return True, "bonus_available", 0

    # Проверка дневных лимитов
    user_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
    model_usage = user_counts.get(model_key, {'date': '', 'count': 0})

    if model_usage['date'] != today:
        model_usage = {'date': today, 'count': 0}

    current_count = model_usage['count']
    actual_limit = await get_user_actual_limit_for_model(user_id, model_key)

    if current_count >= actual_limit:
        message = [f"Достигнут лимит ({current_count}/{actual_limit}) для модели {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi:
            if not user_data.get('claimed_news_bonus', False):
                message.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонусных генераций!')
            elif user_data.get('news_bonus_uses_left', 0) == 0:
                message.append(f"ℹ️ Бонус за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал</a> использован.")
        if not is_profi:
            message.append("Попробуйте завтра или оформите подписку в меню «Подписка».")
        return False, "\n".join(message), current_count

    user_counts[model_key] = model_usage
    bot_data.setdefault('all_user_daily_counts', {}).setdefault(str(user_id), user_counts)
    await set_bot_data(bot_data)
    return True, "", current_count

async def increment_request_count(user_id: int, model_key: str):
    """Увеличение счетчика запросов для модели."""
    model_config = AVAILABLE_TEXT_MODELS.get(model_key, {})
    if not model_config.get("is_limited"):
        return

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()

    is_profi = bot_data.get('user_subscriptions', {}).get(str(user_id), {}).get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and \
               datetime.fromisoformat(bot_data.get('user_subscriptions', {}).get(str(user_id), {}).get('valid_until', '1970-01-01')).date() >= datetime.now().date()

    # Использование бонусной генерации
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        if uses_left > 0:
            user_data['news_bonus_uses_left'] = uses_left - 1
            await set_user_data(user_id, user_data)
            logger.info(f"Пользователь {user_id} использовал бонус для {model_key}. Осталось: {uses_left - 1}")
            return

    # Увеличение стандартного счетчика
    today = datetime.now().strftime("%Y-%m-%d")
    user_counts = bot_data.setdefault('all_user_daily_counts', {}).setdefault(str(user_id), {})
    model_usage = user_counts.get(model_key, {'date': today, 'count': 0})

    if model_usage['date'] != today:
        model_usage = {'date': today, 'count': 0}

    model_usage['count'] += 1
    user_counts[model_key] = model_usage
    await set_bot_data(bot_data)
    logger.info(f"Счетчик запросов для {model_key} пользователя {user_id} увеличен до {model_usage['count']}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    """Обрезка текста до максимальной длины с учетом логических точек."""
    if not isinstance(text, str):
        return str(text), False
    if len(text) <= max_length:
        return text, False

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max = max_length - len(suffix)
    if adjusted_max <= 0:
        return text[:max_length - 3] + "...", True

    truncated = text[:adjusted_max]
    for sep in ['\n\n', '. ', '! ', '? ', '\n', ' ']:
        pos = truncated.rfind(sep)
        if pos != -1 and pos > adjusted_max * 0.3:
            cut = pos + (len(sep) if sep != ' ' else 0)
            return text[:cut].strip() + suffix, True
    return truncated.strip() + suffix, True

def is_menu_button_text(text: str) -> bool:
    """Проверка, является ли текст кнопкой меню."""
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons:
        return True
    for menu in MENU_STRUCTURE.values():
        for item in menu["items"]:
            if item["text"] == text:
                return True
    return False

# --- МЕНЮ И КЛАВИАТУРА ---
def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    """Генерация клавиатуры для меню."""
    menu = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE["main_menu"])
    keyboard = []

    if menu_key in ["main_menu", "models_submenu"]:
        for i in range(0, len(menu["items"]), 2):
            row = [KeyboardButton(item["text"]) for item in menu["items"][i:i + 2]]
            keyboard.append(row)
    else:
        keyboard = [[KeyboardButton(item["text"])] for item in menu["items"]]

    if menu.get("is_submenu", False):
        nav_row = []
        if menu.get("parent"):
            nav_row.append(KeyboardButton("⬅️ Назад"))
        nav_row.append(KeyboardButton("🏠 Главное меню"))
        keyboard.append(nav_row)

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str):
    """Отображение меню пользователю."""
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        menu_key = "main_menu"
        menu = MENU_STRUCTURE[menu_key]
        logger.warning(f"Неверный ключ меню: {menu_key}. Используется главное меню.")

    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key
    await set_user_data(user_id, user_data)

    await update.message.reply_text(
        menu["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        parse_mode=None,
        disable_web_page_preview=True
    )
    logger.info(f"Пользователю {user_id} показано меню '{menu_key}'")

# --- ОБРАБОТЧИКИ КОМАНД ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start."""
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_data.update({
        'current_ai_mode': user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY),
        'current_menu': 'main_menu',
        'selected_model_id': user_data.get('selected_model_id', DEFAULT_MODEL_ID),
        'selected_api_type': user_data.get('selected_api_type', AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["api_type"])
    })

    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
    await set_user_data(user_id, user_data)

    current_model_key = await get_current_model_key(user_id)
    mode_details = await get_current_mode_details(user_id)
    model_details = AVAILABLE_TEXT_MODELS.get(current_model_key, {})

    greeting = (
        f"👋 Привет, {update.effective_user.first_name}!\n"
        f"Я твой ИИ-бот на базе различных нейросетей.\n\n"
        f"🧠 Текущий агент: <b>{mode_details.get('name', 'Неизвестный')}</b>\n"
        f"⚙️ Текущая модель: <b>{model_details.get('name', 'Неизвестная')}</b>\n\n"
        "💬 Задавай вопросы или используй меню!"
    )
    await update.message.reply_text(
        greeting,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard("main_menu"),
        disable_web_page_preview=True
    )
    logger.info(f"Пользователь {user_id} запустил бота.")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /menu."""
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
    """Обработка команды /usage."""
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
    """Обработка команды /subscribe."""
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
    """Обработка команды /bonus."""
    user_id = update.effective_user.id
    await claim_news_bonus_logic(update, user_id, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /help."""
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
    """Отображение лимитов использования моделей."""
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})

    sub_status = "Бесплатный доступ"
    is_subscribed = False
    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                sub_status = f"Подписка Профи (до {valid_until.strftime('%Y-%m-%d')})"
                is_subscribed = True
        except Exception as e:
            logger.error(f"Ошибка парсинга даты подписки для {user_id}: {e}")

    text_parts = [
        "<b>📊 Ваши лимиты запросов</b>",
        f"Статус: <b>{sub_status}</b>",
        ""
    ]

    today = datetime.now().strftime("%Y-%m-%d")
    user_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage = user_counts.get(model_key, {'date': '', 'count': 0})
            count = usage['count'] if usage['date'] == today else 0
            limit = await get_user_actual_limit_for_model(user_id, model_key)
            bonus_note = ""
            if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_subscribed and user_data.get('claimed_news_bonus', False):
                bonus_note = f" (включая {user_data.get('news_bonus_uses_left', 0)} бонусных)"
            text_parts.append(f"▫️ {model_config['name']}: <b>{count}/{limit if limit != float('inf') else '∞'}</b>{bonus_note}")

    if not is_subscribed:
        text_parts.append("\nХотите больше лимитов? Оформите подписку в меню «Подписка».")

    current_menu = user_data.get('current_menu', 'limits_submenu')
    if current_menu not in MENU_STRUCTURE:
        current_menu = 'limits_submenu'

    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )
    logger.info(f"Отправлены лимиты для пользователя {user_id}")

async def show_subscription(update: Update, user_id: int):
    """Отображение информации о подписке."""
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription = bot_data.get('user_subscriptions', {}).get(str(user_id), {})

    text_parts = ["<b>💎 Подписка Профи</b>"]
    is_subscribed = False

    if user_subscription.get('valid_until'):
        try:
            valid_until = datetime.fromisoformat(user_subscription['valid_until'])
            if datetime.now().date() <= valid_until.date():
                text_parts.append(f"\n✅ Подписка активна до <b>{valid_until.strftime('%d.%m.%Y')}</b>.")
                text_parts.append("   Доступны расширенные лимиты и все модели.")
                is_subscribed = True
            else:
                text_parts.append(f"\n⚠️ Подписка истекла <b>{valid_until.strftime('%d.%m.%Y')}</b>.")
        except Exception as e:
            logger.error(f"Ошибка парсинга даты подписки для {user_id}: {e}")
            text_parts.append("\n⚠️ Ошибка определения статуса подписки.")

    if not is_subscribed:
        text_parts.extend([
            "\nС подпиской <b>Профи</b> вы получаете:",
            "▫️ Увеличенные лимиты на все модели.",
            f"▫️ Приоритетный доступ к {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}.",
            f"▫️ Расширенный доступ к {AVAILABLE_TEXT_MODELS['custom_api_grok_3']['name']}.",
            f"▫️ Расширенный доступ к {AVAILABLE_TEXT_MODELS['custom_api_gpt_4o_mini']['name']}.",
            "▫️ Поддержку развития бота.",
            "\nОформите подписку командой /subscribe."
        ])

    current_menu = user_data.get('current_menu', 'subscription_submenu')
    if current_menu not in MENU_STRUCTURE:
        current_menu = 'subscription_submenu'

    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )
    logger.info(f"Отправлена информация о подписке для {user_id}")

async def show_help(update: Update, user_id: int):
    """Отображение справочной информации."""
    user_data = await get_user_data(user_id)
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)

    help_text = (
        "<b>❓ Справка</b>\n\n"
        "Я — ИИ-ассистент с поддержкой нескольких моделей.\n"
        "▫️ <b>Взаимодействие</b>: Задавайте вопросы, получайте ответы.\n"
        "▫️ <b>Агенты</b>: Выберите агента в меню «🤖 Агенты ИИ».\n"
        "▫️ <b>Модели</b>: Переключайте модели в меню «⚙️ Модели ИИ».\n"
        "▫️ <b>Лимиты</b>: Проверяйте лимиты в меню «📊 Лимиты».\n"
        "▫️ <b>Бонус</b>: Получите бонус в меню «🎁 Бонус».\n"
        "▫️ <b>Подписка</b>: Увеличьте лимиты в меню «💎 Подписка».\n\n"
        "<b>Команды:</b>\n"
        "▫️ /start — Перезапустить бота.\n"
        "▫️ /menu — Открыть меню.\n"
        "▫️ /usage — Показать лимиты.\n"
        "▫️ /subscribe — Информация о подписке.\n"
        "▫️ /bonus — Получить бонус.\n"
        "▫️ /help — Показать справку."
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
    logger.info(f"Отправлена справка для пользователя {user_id}")

# --- ОБРАБОТКА КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок меню."""
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

    current_menu = user_data.get('current_menu', 'main_menu')
    logger.info(f"Пользователь {user_id} нажал кнопку '{button_text}' в меню '{current_menu}'")

    if button_text == "⬅️ Назад":
        parent_menu = MENU_STRUCTURE.get(current_menu, {}).get("parent", "main_menu")
        await show_menu(update, user_id, parent_menu)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, "main_menu")
        return

    action_item = None
    for menu in MENU_STRUCTURE.values():
        for item in menu["items"]:
            if item["text"] == button_text:
                action_item = item
                break
        if action_item:
            break

    if not action_item:
        await update.message.reply_text(
            "Неизвестная команда. Используйте /menu.",
            reply_markup=generate_menu_keyboard(current_menu),
            parse_mode=None
        )
        return

    action, target = action_item["action"], action_item["target"]
    logger.info(f"Кнопка '{button_text}' вызывает действие '{action}' с целью '{target}'")

    if action == "submenu":
        await show_menu(update, user_id, target)
    elif action == "set_agent":
        return_menu = MENU_STRUCTURE.get(current_menu, {}).get("parent", "main_menu")
        if target in AI_MODES and target != "gemini_pro_custom_mode":
            user_data['current_ai_mode'] = target
            await set_user_data(user_id, user_data)
            agent = AI_MODES[target]
            text = f"🤖 Агент изменен на: <b>{agent['name']}</b>.\n\n{agent.get('welcome', 'Готов!')}"
        else:
            text = "Ошибка: Агент не найден."
            logger.error(f"Попытка установить неверный агент '{target}' пользователем {user_id}")
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu),
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu
        await set_user_data(user_id, user_data)
    elif action == "set_model":
        return_menu = MENU_STRUCTURE.get(current_menu, {}).get("parent", "main_menu")
        if target in AVAILABLE_TEXT_MODELS:
            model_config = AVAILABLE_TEXT_MODELS[target]
            user_data.update({
                'selected_model_id': model_config["id"],
                'selected_api_type': model_config["api_type"]
            })
            if target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and user_data.get('current_ai_mode') == "gemini_pro_custom_mode":
                user_data['current_ai_mode'] = DEFAULT_AI_MODE_KEY
            await set_user_data(user_id, user_data)
            today = datetime.now().strftime("%Y-%m-%d")
            user_counts = (await get_bot_data()).get('all_user_daily_counts', {}).get(str(user_id), {})
            usage = user_counts.get(target, {'date': '', 'count': 0})
            count = usage['count'] if usage['date'] == today else 0
            limit = await get_user_actual_limit_for_model(user_id, target)
            text = f"⚙️ Модель изменена на: <b>{model_config['name']}</b>.\nЛимит: {count}/{limit if limit != float('inf') else '∞'}."
        else:
            text = "Ошибка: Модель не найдена."
            logger.error(f"Попытка установить неверную модель '{target}' пользователем {user_id}")
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(return_menu),
            disable_web_page_preview=True
        )
        user_data['current_menu'] = return_menu
        await set_user_data(user_id, user_data)
    elif action == "show_limits":
        await show_limits(update, user_id)
    elif action == "check_bonus":
        await claim_news_bonus_logic(update, user_id, context)
    elif action == "show_subscription":
        await show_subscription(update, user_id)
    elif action == "show_help":
        await show_help(update, user_id)
    else:
        await update.message.reply_text(
            "Действие не определено. Сообщите администратору.",
            reply_markup=generate_menu_keyboard(current_menu),
            parse_mode=None
        )

# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых запросов к ИИ."""
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
            "Запрос слишком короткий. Уточните или используйте меню.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            parse_mode=None,
            disable_web_page_preview=True
        )
        logger.info(f"Короткий запрос от {user_id}: '{user_message}'")
        return

    logger.info(f"Запрос ИИ от {user_id}: '{user_message[:100]}...'")

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key)
    if not model_config:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            "Ошибка конфигурации модели. Сообщите администратору.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            parse_mode=None
        )
        logger.error(f"Модель не найдена для ключа '{current_model_key}' пользователя {user_id}")
        return

    can_proceed, limit_message, current_count = await check_and_log_request_attempt(user_id, current_model_key)
    if not can_proceed:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            limit_message,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True
        )
        logger.info(f"Лимит превышен для {user_id} на модели {current_model_key}")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id)
    system_prompt = mode_details["prompt"]
    response_text = "Не удалось получить ответ от ИИ."

    api_type = model_config.get("api_type", "").strip()
    if api_type == "google_genai":
        full_prompt = f"{system_prompt}\n\n**Запрос:**\n{user_message}"
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        genai_model = genai.GenerativeModel(model_name=model_config["id"], generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB})
        try:
            logger.info(f"Запрос к Google GenAI: {model_config['id']} для {user_id}")
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: genai_model.generate_content(full_prompt)
            )
            response_text = response.text.strip() or "Ответ от Google GenAI пуст."
            logger.info(f"Ответ Google GenAI получен для {user_id}. Длина: {len(response_text)}")
        except google.api_core.exceptions.ResourceExhausted:
            response_text = "Лимит Google API исчерпан. Попробуйте позже."
            logger.error(f"Google API исчерпан для {user_id}, модель {model_config['id']}")
        except Exception as e:
            response_text = f"Ошибка Google API: {type(e).__name__}. Попробуйте позже."
            logger.error(f"Ошибка Google GenAI для {user_id}, модель {model_config['id']}: {e}")

    elif api_type == "custom_http_api":
        api_key_name = model_config.get("api_key_var_name")
        api_key = globals().get(api_key_name)
        if not api_key or "YOUR_" in api_key or not api_key:
            response_text = f"Ошибка: Ключ API для «{model_config.get('name', current_model_key)}» не настроен."
            logger.error(f"Ошибка ключа API для модели '{current_model_key}'")
        else:
            if current_model_key == "custom_api_gemini_2_5_pro":
                response_text, success = await query_gemini_pro(system_prompt, user_message)
                if not success:
                    logger.warning(f"Ошибка Gemini 2.5 Pro для {user_id}: {response_text}")
            elif current_model_key == "custom_api_grok_3":
                response_text, success = await query_grok_3(system_prompt, user_message)
                if not success:
                    logger.warning(f"Ошибка Grok 3 для {user_id}: {response_text}")
            else:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                messages = []
                is_gpt_4o_mini = model_config["id"] == "gpt-4o-mini"
                if system_prompt:
                    messages.append({
                        "role": "system",
                        "content": [{"type": "text", "text": system_prompt}] if is_gpt_4o_mini else system_prompt
                    })
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": user_message}] if is_gpt_4o_mini else user_message
                })

                payload = {
                    "messages": messages,
                    "model": model_config["id"],
                    "is_sync": True,
                    "max_tokens": model_config.get("max_tokens", MAX_OUTPUT_TOKENS_GEMINI_LIB),
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "n": 1,
                    "stream": False
                }

                try:
                    logger.info(f"Запрос к Custom API: {model_config['endpoint']} для {user_id}")
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=45)
                    )
                    response.raise_for_status()
                    response_json = response.json()
                    extracted_text = None

                    if model_config["id"] == "gpt-4o-mini" and response_json.get("status") == "success":
                        output = response_json.get("output")
                        if isinstance(output, str):
                            extracted_text = output.strip()
                        elif isinstance(output, dict):
                            extracted_text = output.get("text", output.get("content", "")).strip()
                        elif output is not None:
                            extracted_text = str(output).strip()
                            logger.warning(f"gpt-4o-mini: Неожиданный тип данных: {type(output)}")
                        else:
                            extracted_text = "Ответ получен, но он пуст."
                            logger.warning(f"gpt-4o-mini: Поле 'output' отсутствует: {response_json}")
                    else:
                        for key in ["text", "content", "message", "output", "response"]:
                            if isinstance(response_json.get(key), str):
                                extracted_text = response_json[key].strip()
                                break
                        if not extracted_text:
                            extracted_text = ""
                            logger.warning(f"Не удалось извлечь текст для {model_config['id']}: {response_json}")

                    response_text = extracted_text or "Ответ от API пуст или не удалось извлечь текст."
                except requests.exceptions.HTTPError as e:
                    response_text = f"Ошибка сети ({e.response.status_code}). Попробуйте позже."
                    logger.error(f"HTTPError для {model_config['id']}: {e}")
                except requests.exceptions.RequestException as e:
                    response_text = f"Сетевая ошибка: {type(e).__name__}. Проверьте соединение."
                    logger.error(f"RequestException для {model_config['id']}: {e}")
                except Exception as e:
                    response_text = f"Неожиданная ошибка: {type(e).__name__}."
                    logger.error(f"Ошибка для {model_config['id']}: {e}")

    else:
        response_text = "Ошибка: Неизвестный тип API."
        logger.error(f"Неизвестный api_type '{api_type}' для модели {current_model_key}")

    final_response, was_truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"Ответ для {user_id} (модель {current_model_key}) обрезан до {MAX_MESSAGE_LENGTH_TELEGRAM} символов.")

    await increment_request_count(user_id, current_model_key)
    user_data = await get_user_data(user_id)
    await update.message.reply_text(
        final_response,
        parse_mode=None,
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    log_response = final_response[:100].replace('\n', ' ')
    logger.info(f"Отправлен ответ ИИ (модель: {current_model_key}) пользователю {user_id}: '{log_response}...'")

# --- ПЛАТЕЖИ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка предварительной проверки платежа."""
    query = update.pre_checkout_query
    expected_payload = f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_payload_example"
    if query.invoice_payload == expected_payload:
        await query.answer(ok=True)
        logger.info(f"Предварительная проверка платежа для {query.user.id} прошла успешно")
    else:
        await query.answer(ok=False, error_message="Неверный запрос на оплату. Сформируйте новый счет.")
        logger.warning(f"Предварительная проверка платежа отклонена для {query.user.id}: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешного платежа."""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    expected_payload = f"subscription_{PRO_SUBSCRIPTION_LEVEL_KEY}_payload_example"

    logger.info(f"Успешный платеж от {user_id}. Payload: {payment.invoice_payload}, Сумма: {payment.total_amount} {payment.currency}")

    if payment.invoice_payload != expected_payload:
        await update.message.reply_text(
            "Платеж получен, но возникла ошибка активации подписки. Свяжитесь с администратором.",
            parse_mode=None
        )
        if YOUR_ADMIN_ID:
            await context.bot.send_message(
                chat_id=YOUR_ADMIN_ID,
                text=f"⚠️ Ошибка платежа для {user_id}. Payload: {payment.invoice_payload}, Ожидалось: {expected_payload}",
                parse_mode=ParseMode.HTML
            )
        logger.error(f"Несоответствие payload платежа для {user_id}: {payment.invoice_payload}")
        return

    bot_data = await get_bot_data()
    user_subscriptions = bot_data.setdefault('user_subscriptions', {})
    current_sub = user_subscriptions.get(str(user_id), {})
    start_date = datetime.now().astimezone()
    if current_sub.get('valid_until'):
        try:
            previous_valid_until = datetime.fromisoformat(current_sub['valid_until'])
            if previous_valid_until > start_date:
                start_date = previous_valid_until
        except ValueError:
            logger.warning(f"Неверный формат даты подписки для {user_id}")

    new_valid_until = start_date + timedelta(days=30)
    user_subscriptions[str(user_id)] = {
        'level': PRO_SUBSCRIPTION_LEVEL_KEY,
        'valid_until': new_valid_until.isoformat(),
        'last_payment_amount': payment.total_amount,
        'last_payment_currency': payment.currency,
        'purchase_date': datetime.now().astimezone().isoformat()
    }
    bot_data['user_subscriptions'] = user_subscriptions
    await set_bot_data(bot_data)

    user_data = await get_user_data(user_id)
    await update.message.reply_text(
        f"🎉 Платеж успешен! Подписка Профи активна до <b>{new_valid_until.strftime('%d.%m.%Y')}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
        disable_web_page_preview=True
    )
    logger.info(f"Подписка для {user_id} обновлена до {new_valid_until.isoformat()}")

    if YOUR_ADMIN_ID:
        await context.bot.send_message(
            chat_id=YOUR_ADMIN_ID,
            text=(
                f"🔔 Новая оплата!\n"
                f"Пользователь: {update.effective_user.full_name} (ID: {user_id})\n"
                f"Сумма: {payment.total_amount / 100} {payment.currency}\n"
                f"Подписка до: {new_valid_until.strftime('%d.%m.%Y')}"
            ),
            parse_mode=ParseMode.HTML
        )

# --- ОБРАБОТКА ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ошибок бота."""
    logger.error(f"Ошибка: {context.error}", exc_info=True)
    if isinstance(update, Update) and update.effective_chat:
        user_data = await get_user_data(update.effective_user.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Внутренняя ошибка. Попробуйте позже или используйте /start.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            parse_mode=None
        )
    if YOUR_ADMIN_ID and isinstance(update, Update):
        await context.bot.send_message(
            chat_id=YOUR_ADMIN_ID,
            text=f"🤖 Ошибка: {context.error.__class__.__name__}: {context.error}\nПользователь: {update.effective_user.id}",
            parse_mode=ParseMode.HTML
        )

# --- ЗАПУСК БОТА ---
async def main():
    """Запуск бота с настройкой обработчиков."""
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

    commands = [
        BotCommand("start", "🚀 Перезапуск"),
        BotCommand("menu", "📋 Меню"),
        BotCommand("usage", "📊 Лимиты"),
        BotCommand("subscribe", "💎 Подписка"),
        BotCommand("bonus", "🎁 Бонус"),
        BotCommand("help", "❓ Справка")
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Команды бота установлены.")

    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)
        raise
