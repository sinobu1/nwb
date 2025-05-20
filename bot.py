import telegram
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from telegram.constants import ParseMode, ChatAction
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, PicklePersistence
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
from telegram.ext import PreCheckoutQueryHandler
from typing import Optional
import uuid

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
YOUR_ADMIN_ID = 489230152

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000

# --- ЛИМИТЫ ---
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"

# --- КАНАЛ НОВОСТЕЙ И БОНУС ---
NEWS_CHANNEL_USERNAME = "@timextech"
NEWS_CHANNEL_LINK = "https://t.me/timextech"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
NEWS_CHANNEL_BONUS_GENERATIONS = 1

# --- РЕЖИМЫ РАБОТЫ ИИ ---
AI_MODES = {
    "universal_ai_basic": {
        "name": "🤖 Универсальный ИИ (Базовый)",
        "prompt": (
            "Ты — продвинутый ИИ-ассистент Gemini от Google. "
            "Твоя задача — помогать пользователю с разнообразными запросами: отвечать на вопросы, генерировать текст, "
            "давать объяснения, выполнять анализ и предоставлять информацию по широкому кругу тем. "
            "Будь вежлив, объективен, точен и полезен. "
            "Если твои знания ограничены по времени, предупреждай об этом.\n\n"
            "**Оформление ответа (простой структурированный текст):**\n"
            "1.  **Абзацы:** Четко разделяй смысловые блоки текста абзацами. Используй одну или две пустые строки между абзацами для лучшей читаемости.\n"
            "2.  **Списки:** Если информация предполагает перечисление, используй нумерованные списки (например, `1. Первый пункт`, `2. Второй пункт`) или маркированные списки (например, `- Элемент списка` или `* Другой элемент`). Используй стандартные символы для списков.\n"
            "3.  **Секции/Заголовки (если нужно):** Для разделения крупных смысловых блоков можешь использовать короткую поясняющую фразу или заголовок на отдельной строке. Если хочешь выделить заголовок, можешь написать его ЗАГЛАВНЫМИ БУКВАМИ. Например:\n"
            "    ОСНОВНЫЕ ХАРАКТЕРИСТИКИ:\n"
            "    - Характеристика один...\n"
            "    - Характеристика два...\n"
            "4.  **Без специального форматирования:** Пожалуйста, НЕ используй Markdown-разметку (звездочки для жирного текста или курсива, обратные апострофы для кода, символы цитирования и т.д.). Генерируй только ясный, чистый текст.\n"
            "5.  **Логическая Завершённость:** Старайся, чтобы твои ответы были полными. Если ответ содержит списки, убедись, что последний пункт завершен. Лучше не начинать новый пункт, если не уверен, что успеешь его закончить в рамках разумной длины ответа.\n"
            "6.  **Читаемость:** Главное — чтобы ответ был понятным, хорошо структурированным и легким для восприятия.\n"
            "7. **Без лишних символов:** Не используй в тексте избыточные скобки, дефисы или другие знаки пунктуации, если они не несут смысловой нагрузки или не требуются правилами грамматики."
        ),
        "welcome": "Активирован режим 'Универсальный ИИ (Базовый)'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "🤖 Продвинутый Ассистент (для Gemini 2.5 Pro)",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент. "
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя. "
            "Соблюдай вежливость и объективность. "
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости. "
            "Избегай излишнего Markdown-форматирования, если это не улучшает читаемость (например, для блоков кода). "
            "Если твои знания ограничены по времени, указывай это."
        ),
        "welcome": "Активирован режим 'Продвинутый Ассистент'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "✍️ Творческий Помощник",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Твоя миссия — вдохновлять, помогать в создании оригинального контента (тексты, идеи, сценарии, стихи и т.д.) и развивать творческие замыслы пользователя. "
            "Будь смелым в идеях, предлагай неожиданные решения, но всегда оставайся в рамках этики и здравого смысла. "
            "**Форматирование (если применимо к творческому тексту):**\n"
            "1.  **Абзацы:** Для прозы и описаний — четкое разделение на абзацы.\n"
            "2.  **Стихи:** Соблюдай строфы и строки, если это подразумевается заданием.\n"
            "3.  **Диалоги:** Оформляй диалоги стандартным образом (например, `- Привет! - сказал он.` или с новой строке для каждого персонажа).\n"
            "4.  **Без Markdown:** Генерируй чистый текст без Markdown-разметки (звездочек, решеток и т.п.), если только это не специфический элемент форматирования самого творческого произведения (например, название главы, выделенное заглавными).\n"
            "5.  **Язык:** Используй богатый и выразительный язык, соответствующий творческой задаче.\n"
            "6.  **Завершённость:** Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
    "analyst": {
        "name": "📈 Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик на базе Gemini, специализирующийся на анализе данных, фактов и трендов. "
            "Твоя задача — предоставлять точные, логически обоснованные и структурированные ответы на запросы, связанные с анализом информации, статистики или бизнес-вопросов. "
            "Используй структурированный подход:\n"
            "1. **Анализ:** Разбери запрос на ключевые аспекты.\n"
            "2. **Выводы:** Предоставь четкие выводы или рекомендации.\n"
            "3. **Обоснование:** Объясни свои рассуждения, если требуется.\n"
            "Если данных недостаточно, укажи, что нужно для более точного анализа."
        ),
        "welcome": "Режим 'Аналитик' активирован. Какую задачу или данные нужно проанализировать?"
    },
    "joker": {
        "name": "😜 Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini. "
            "Твоя задача — отвечать на запросы с легкостью, остроумием и юмором, сохраняя при этом полезность. "
            "Добавляй шутки, анекдоты или забавные комментарии, но оставайся в рамках приличия. "
            "Форматируй ответы так, чтобы они были веселыми и читабельными."
        ),
        "welcome": "Режим 'Шутник' включен! 😄 Готов ответить с улыбкой — что у тебя за вопрос?"
    }
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

# --- МОДЕЛИ ИИ ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "⚡️ Gemini 2.0 Flash",
        "id": "gemini-2.0-flash",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY,
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "💨 Gemini 2.5 Flash Preview",
        "id": "gemini-2.5-flash-preview-04-17",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY,
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "🌟 Gemini 2.5 Pro (Продвинутый)",
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
    }
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

# --- НОВАЯ СТРУКТУРА МЕНЮ ---
MENU_STRUCTURE = {
    "main_menu": {
        "title": "📋 Главное меню",
        "items": [
            {"text": "🤖 Режимы ИИ", "action": "submenu", "target": "ai_modes_submenu"},
            {"text": "⚙️ Модели ИИ", "action": "submenu", "target": "models_submenu"},
            {"text": "📊 Лимиты", "action": "submenu", "target": "limits_submenu"},
            {"text": "🎁 Бонус", "action": "submenu", "target": "bonus_submenu"},
            {"text": "💎 Подписка Профи", "action": "submenu", "target": "subscription_submenu"},
            {"text": "❓ Помощь", "action": "submenu", "target": "help_submenu"}
        ],
        "parent": None
    },
    "ai_modes_submenu": {
        "title": "Выберите режим ИИ",
        "items": [
            {"text": mode["name"], "action": "set_agent", "target": key}
            for key, mode in AI_MODES.items()
            if key != "gemini_pro_custom_mode"
        ],
        "parent": "main_menu"
    },
    "models_submenu": {
        "title": "Выберите модель ИИ",
        "items": [
            {"text": model["name"], "action": "set_model", "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ],
        "parent": "main_menu"
    },
    "limits_submenu": {
        "title": "Ваши лимиты",
        "items": [
            {"text": "📊 Показать лимиты", "action": "show_limits", "target": "usage"}
        ],
        "parent": "main_menu"
    },
    "bonus_submenu": {
        "title": "Бонус за подписку",
        "items": [
            {"text": "🎁 Получить бонус", "action": "check_bonus", "target": "news_bonus"}
        ],
        "parent": "main_menu"
    },
    "subscription_submenu": {
        "title": "Подписка Профи",
        "items": [
            {"text": "💎 Информация и покупка", "action": "show_subscription", "target": "subscribe"}
        ],
        "parent": "main_menu"
    },
    "help_submenu": {
        "title": "Помощь",
        "items": [
            {"text": "❓ Показать помощь", "action": "show_help", "target": "help"}
        ],
        "parent": "main_menu"
    }
}

# --- Конфигурация API Google Gemini ---
if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
    logger.warning("Google Gemini API key (GOOGLE_GEMINI_API_KEY) is not set correctly or uses a placeholder.")
else:
    try:
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini API: {str(e)}")

if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY:
    logger.warning("Custom Gemini Pro API key (CUSTOM_GEMINI_PRO_API_KEY) is not set correctly or uses a placeholder.")

# --- Вспомогательные функции ---
def get_current_mode_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    current_model_key = get_current_model_key(context)
    if current_model_key == "custom_api_gemini_2_5_pro":
        if "gemini_pro_custom_mode" in AI_MODES:
            return AI_MODES["gemini_pro_custom_mode"]
        else:
            logger.warning("Dedicated mode 'gemini_pro_custom_mode' not found. Falling back to default AI mode.")
            return AI_MODES.get(DEFAULT_AI_MODE_KEY, AI_MODES["universal_ai_basic"])
    mode_key = context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

def get_current_model_key(context: ContextTypes.DEFAULT_TYPE) -> str:
    selected_id = context.user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = context.user_data.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if 'selected_api_type' not in context.user_data or context.user_data['selected_api_type'] != info.get("api_type"):
                context.user_data['selected_api_type'] = info.get("api_type")
                logger.info(f"Inferred and updated api_type to '{info.get('api_type')}' for model_id '{selected_id}'")
            return key
            
    logger.warning(f"Could not find key for model_id '{selected_id}' (API type '{selected_api_type}' if any). Falling back to default: {DEFAULT_MODEL_KEY}.")
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    context.user_data['selected_model_id'] = default_model_config["id"]
    context.user_data['selected_api_type'] = default_model_config["api_type"]
    return DEFAULT_MODEL_KEY

def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    model_key = get_current_model_key(context)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str):
        logger.warning(f"smart_truncate received non-string input: {type(text)}. Returning as is.")
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

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("📋 Меню")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_user_actual_limit_for_model(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0
    all_user_subscriptions = context.bot_data.setdefault('user_subscriptions', {})
    user_subscription_details = all_user_subscriptions.get(user_id, {})
    current_sub_level = None
    if user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                current_sub_level = user_subscription_details.get('level')
        except Exception: pass

    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free":
        return model_config.get("limit", 0)
    if limit_type == "subscription_or_daily_free":
        return model_config.get("subscription_daily_limit" if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY else "limit_if_no_subscription", 0)
    if limit_type == "subscription_custom_pro":
        return model_config.get("subscription_daily_limit" if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY else "limit_if_no_subscription", 0)
    return model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"): return True, "", 0

    is_profi_subscriber = False
    if model_config.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro"]:
        user_subscription_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception: pass

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
        if context.user_data.get('news_bonus_uses_left', 0) > 0:
            logger.info(f"User {user_id} has bonus for {model_key}. Allowing.")
            return True, "bonus_available", 0

    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': '', 'count': 0})
    if model_daily_usage['date'] != today_str:
        model_daily_usage.update({'date': today_str, 'count': 0})

    current_daily_count = model_daily_usage['count']
    actual_daily_limit = get_user_actual_limit_for_model(user_id, model_key, context)

    if current_daily_count >= actual_daily_limit:
        message_parts = [f"Вы достигли дневного лимита ({current_daily_count}/{actual_daily_limit}) для модели '{escape_markdown(model_config['name'], version=2)}'\."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not context.user_data.get('claimed_news_bonus', False):
                message_parts.append(f"💡 Подпишитесь на [наш новостной канал]({NEWS_CHANNEL_LINK}) и используйте меню «Бонус» для получения бонусной генерации\!")
            elif context.user_data.get('news_bonus_uses_left', 0) == 0:
                 message_parts.append("ℹ️ Ваш бонус за подписку на новости для этой модели уже использован\.")
        message_parts.append("Попробуйте завтра или рассмотрите подписку в меню «Подписка Профи»\.")
        return False, "\n".join(message_parts), current_daily_count
    return True, "", current_daily_count

def increment_request_count(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"): return

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
        is_profi_subscriber = False
        user_subscription_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception: pass
        
        if not is_profi_subscriber:
            news_bonus_uses_left = context.user_data.get('news_bonus_uses_left', 0)
            if news_bonus_uses_left > 0:
                context.user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
                logger.info(f"User {user_id} consumed a news channel bonus use for {model_key}. Remaining: {context.user_data['news_bonus_uses_left']}")
                return

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': today_str, 'count': 0})
    if model_daily_usage['date'] != today_str:
        model_daily_usage.update({'date': today_str, 'count': 0})
    model_daily_usage['count'] += 1
    logger.info(f"User {user_id} daily request count for {model_key} incremented to {model_daily_usage['count']}")

# --- Функции для многоуровневых меню ---
def generate_menu_keyboard(menu_key: str, context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        return InlineKeyboardMarkup([])
    
    keyboard = []
    for item in menu["items"]:
        callback_data = f"menu_{item['action']}_{item['target']}"
        keyboard.append([InlineKeyboardButton(item["text"], callback_data=callback_data)])
    
    nav_buttons = []
    if menu["parent"]:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"menu_back_{menu['parent']}"))
    if menu_key != "main_menu":
        nav_buttons.append(InlineKeyboardButton("🏠 Главное меню", callback_data="menu_goto_main_menu"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    return InlineKeyboardMarkup(keyboard)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_key: str, message_to_edit: Optional[telegram.Message] = None):
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        text = "Ошибка: Меню не найдено."
        if message_to_edit:
            await message_to_edit.edit_text(text, reply_markup=None)
        else:
            await update.message.reply_text(text, reply_markup=get_main_reply_keyboard())
        return
    
    context.user_data['current_menu'] = menu_key
    text = escape_markdown(menu["title"], version=2)
    reply_markup = generate_menu_keyboard(menu_key, context)
    
    if message_to_edit:
        await message_to_edit.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    context.user_data.setdefault('current_menu', 'main_menu')
    if 'selected_model_id' not in context.user_data or 'selected_api_type' not in context.user_data:
        default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data.update({'selected_model_id': default_model_conf["id"], 'selected_api_type': default_model_conf["api_type"]})
    
    current_model_key = get_current_model_key(context)
    current_mode_name = get_current_mode_details(context)['name']
    current_model_name = AVAILABLE_TEXT_MODELS[current_model_key]['name']

    greeting = f"👋 Привет! Я твой ИИ-бот на базе Gemini.\n🧠 Агент: *{escape_markdown(current_mode_name, version=2)}*\n⚙️ Модель: *{escape_markdown(current_model_name, version=2)}*\n\n💬 Задавайте вопросы или используйте *Меню* ниже!"
    try:
        await update.message.reply_text(
            greeting,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_main_reply_keyboard(),
            disable_web_page_preview=True
        )
        await show_menu(update, context, "main_menu")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending /start message: {e}")
        plain_text = f"Привет! Я ИИ-бот Gemini.\nАгент: {current_mode_name}\nМодель: {current_model_name}\n\nЗадавайте вопросы или используйте Меню!"
        await update.message.reply_text(plain_text, reply_markup=get_main_reply_keyboard())
    logger.info(f"Start command processed for user {user_id}.")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context, "main_menu")

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context, "limits_submenu")

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context, "subscription_submenu")

async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context, "bonus_submenu")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context, "help_submenu")

async def claim_news_bonus_logic(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 called_from_button: bool = False, message_to_edit: Optional[telegram.Message] = None):
    user = update.effective_user
    reply_chat_id = None
    if called_from_button and update.callback_query:
        reply_chat_id = update.callback_query.message.chat_id
    elif update.message:
        reply_chat_id = update.message.chat_id
        message_to_edit = None
    else:
        logger.warning("claim_news_bonus_logic: Could not determine user or reply target.")
        return

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        error_message = "Функция бонуса не настроена."
        if message_to_edit: await message_to_edit.edit_text(error_message, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=reply_chat_id, text=error_message, disable_web_page_preview=True)
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        error_message = "Ошибка: Бонусная модель не найдена."
        if message_to_edit: await message_to_edit.edit_text(error_message, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=reply_chat_id, text=error_message, disable_web_page_preview=True)
        return
    bonus_model_name_md = escape_markdown(bonus_model_config['name'], version=2)

    if context.user_data.get('claimed_news_bonus', False):
        uses_left = context.user_data.get('news_bonus_uses_left', 0)
        reply_text_claimed = ""
        if uses_left > 0:
            reply_text_claimed = (f"Вы уже активировали бонус\. У вас осталось *{uses_left}* бесплатных генераций для модели '{bonus_model_name_md}'\.\nНаш [канал]({NEWS_CHANNEL_LINK})\.")
        else:
            reply_text_claimed = (f"Вы уже получали и использовали бонус для модели '{bonus_model_name_md}'\.\nНаш [канал]({NEWS_CHANNEL_LINK})\.")
        if message_to_edit: await message_to_edit.edit_text(reply_text_claimed, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=reply_chat_id, text=reply_text_claimed, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        return

    try:
        member_status = await context.bot.get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member_status.status in ['member', 'administrator', 'creator']:
            context.user_data['claimed_news_bonus'] = True
            context.user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            success_text = (f"🎉 Спасибо за подписку на [канал]({NEWS_CHANNEL_LINK})\!\nВам начислена *{NEWS_CHANNEL_BONUS_GENERATIONS}* бесплатная генерация для модели '{bonus_model_name_md}'\.")
            if message_to_edit: await message_to_edit.edit_text(success_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
            else: await context.bot.send_message(chat_id=reply_chat_id, text=success_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        else:
            fail_text = (f"Подписка на [канал]({NEWS_CHANNEL_LINK}) не найдена\. Пожалуйста, убедитесь, что вы подписаны, и нажмите кнопку проверки еще раз\.")
            reply_markup_after_fail = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Я подписался, проверить снова!", callback_data="menu_check_bonus_news_bonus")]])
            if message_to_edit:
                await message_to_edit.edit_text(fail_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup_after_fail, disable_web_page_preview=True)
            else:
                await context.bot.send_message(chat_id=reply_chat_id, text=fail_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        error_text_response = str(e).lower()
        reply_message_on_error = f"Ошибка проверки подписки: {escape_markdown(str(e), version=2)}\. Попробуйте позже\."
        if "user not found" in error_text_response or "member not found" in error_text_response or "participant not found" in error_text_response:
            reply_message_on_error = f"Мы не смогли подтвердить вашу подписку на [канал]({NEWS_CHANNEL_LINK})\. Возможно, вы не подписаны\. Пожалуйста, подпишитесь и попробуйте снова\."
        elif "chat not found" in error_text_response or "channel not found" in error_text_response:
            reply_message_on_error = "Новостной канал для проверки подписки не найден\. Администратор бота, вероятно, указал неверный юзернейм канала\."
        elif "bot is not a member" in error_text_response:
            reply_message_on_error = f"Не удалось проверить подписку\. Если канал приватный, бот должен быть его участником\."
        logger.error(f"BadRequest error checking channel membership for user {user.id} in {NEWS_CHANNEL_USERNAME}: {e}")
        if message_to_edit: await message_to_edit.edit_text(reply_message_on_error, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=reply_chat_id, text=reply_message_on_error, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Unexpected error in claim_news_bonus_logic for user {user.id}: {e}\n{traceback.format_exc()}")
        error_message_general = "Произошла непредвиденная ошибка при попытке получить бонус\. Попробуйте позже\."
        if message_to_edit: await message_to_edit.edit_text(error_message_general, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=reply_chat_id, text=error_message_general, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

async def show_limits(update: Update, context: ContextTypes.DEFAULT_TYPE, message_to_edit: Optional[telegram.Message] = None):
    user_id = update.effective_user.id
    user_subscription_details = context.bot_data.setdefault('user_subscriptions', {}).get(user_id, {})
    display_sub_level = "Бесплатный доступ"
    subscription_active = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                display_sub_level = f"💎 Подписка Профи (до {valid_until_dt.strftime('%Y-%m-%d')})"
                subscription_active = True
            else: display_sub_level = "💎 Подписка Профи (истекла)"
        except Exception: display_sub_level = "💎 Подписка Профи (ошибка даты)"

    usage_text_parts = [f"📊 *Информация о ваших лимитах*", f"Текущий статус: *{escape_markdown(display_sub_level, version=2)}*", "\nЕжедневные лимиты запросов по моделям:"]
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = context.bot_data.get('all_user_daily_counts', {}).get(user_id, {})
            model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
            usage_text_parts.append(f"▫️ {escape_markdown(model_c['name'], version=2)}: *{current_c_display}/{actual_l}*")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
        bonus_model_name_md = escape_markdown(bonus_model_name, version=2)
        bonus_info_md = ""
        if not context.user_data.get('claimed_news_bonus', False):
            bonus_info_md = (f"\n🎁 Подпишитесь на [наш новостной канал]({NEWS_CHANNEL_LINK}) и используйте меню «Бонус» "
                             f"для получения *{NEWS_CHANNEL_BONUS_GENERATIONS}* генерации ({bonus_model_name_md})\!")
        elif (bonus_uses_left := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info_md = f"\n🎁 У вас есть *{bonus_uses_left}* бонусных генераций для {bonus_model_name_md} ([канал]({NEWS_CHANNEL_LINK}))\."
        else:
            bonus_info_md = f"\nℹ️ Бонус за подписку на [новостной канал]({NEWS_CHANNEL_LINK}) ({bonus_model_name_md}) уже использован\."
        usage_text_parts.append(bonus_info_md)

    if not subscription_active:
        usage_text_parts.append(f"\nХотите больше лимитов? Перейдите в меню «Подписка Профи»\.")

    final_usage_text_md = "\n".join(usage_text_parts)
    reply_markup = generate_menu_keyboard("limits_submenu", context)
    try:
        if message_to_edit:
            await message_to_edit.edit_text(final_usage_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            await update.message.reply_text(final_usage_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending limits: {e}")
        plain_usage_parts = [f"Статус: {display_sub_level}", "Лимиты:"]
        for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
             if model_c.get("is_limited"):
                today_str = datetime.now().strftime("%Y-%m-%d")
                user_model_counts = context.bot_data.get('all_user_daily_counts', {}).get(user_id, {})
                model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
                current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
                actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
                plain_usage_parts.append(f"- {model_c['name']}: {current_c_display}/{actual_l}")
        if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
            bonus_model_name_plain = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
            if not context.user_data.get('claimed_news_bonus', False): plain_usage_parts.append(f"\nБонус: Подписка на {NEWS_CHANNEL_LINK} -> Меню «Бонус»")
            elif (bonus_left := context.user_data.get('news_bonus_uses_left', 0)) > 0: plain_usage_parts.append(f"\nБонус: У вас {bonus_left} генераций для {bonus_model_name_plain}.")
            else: plain_usage_parts.append(f"\nБонус за {NEWS_CHANNEL_LINK} ({bonus_model_name_plain}) использован.")
        if not subscription_active: plain_usage_parts.append("\nПодписка Профи: Меню «Подписка Профи»")
        plain_text = "\n".join(plain_usage_parts)
        if message_to_edit:
            await message_to_edit.edit_text(plain_text, reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            await update.message.reply_text(plain_text, reply_markup=reply_markup, disable_web_page_preview=True)

async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE, message_to_edit: Optional[telegram.Message] = None):
    text_parts = ["🌟 *Подписка Профи – Максимум возможностей Gemini\!* 🌟",
                  "\nПолучите расширенные дневные лимиты для самых мощных моделей:"]
    m_conf_flash = AVAILABLE_TEXT_MODELS['google_gemini_2_5_flash_preview']
    text_parts.append(f"💨 {escape_markdown(m_conf_flash['name'], version=2)}: *{m_conf_flash['subscription_daily_limit']}* з/д \(беспл\.: {m_conf_flash['limit_if_no_subscription']} з/д\)")
    m_conf_pro = AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']
    pro_free_text = f"{m_conf_pro['limit_if_no_subscription']} {escape_markdown('генераций (бонус за новости)', version=2)}" if m_conf_pro['limit_if_no_subscription'] == 0 else f"{m_conf_pro['limit_if_no_subscription']} з/д"
    text_parts.append(f"🌟 {escape_markdown(m_conf_pro['name'], version=2)}: *{m_conf_pro['subscription_daily_limit']}* з/д \(беспл\.: {pro_free_text}\)")
    text_parts.append(f"\nБазовая модель всегда доступна:\n⚡️ {escape_markdown(AVAILABLE_TEXT_MODELS['google_gemini_2_0_flash']['name'], version=2)}: *{DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY}* з/д \(беспл\.\)")
    text_parts.extend(["\n✨ *Тариф Профи для теста:*", f"▫️ Тест-драйв \(2 дня\): `{escape_markdown('99 рублей', version=2)}`"])
    
    keyboard = [[InlineKeyboardButton("💳 Купить Профи (2 дня - 99 RUB)", callback_data="buy_profi_2days")]]
    reply_markup = InlineKeyboardMarkup(keyboard + generate_menu_keyboard("subscription_submenu", context).inline_keyboard)
    final_text_subscribe = "\n".join(text_parts)
    
    try:
        if message_to_edit:
            await message_to_edit.edit_text(final_text_subscribe, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            await update.message.reply_text(final_text_subscribe, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
    except telegram.error.BadRequest:
        plain_text = "Подписка Профи: ... (упрощенный текст)"
        if message_to_edit:
            await message_to_edit.edit_text(plain_text, reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            await update.message.reply_text(plain_text, reply_markup=reply_markup, disable_web_page_preview=True)

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE, message_to_edit: Optional[telegram.Message] = None):
    help_text_parts = [
        f"👋 Я многофункциональный ИИ-бот на базе моделей Gemini от Google\.",
        "\n*Используйте меню для взаимодействия:*",
        "🤖 *Режимы ИИ*: Выберите агента (например, Аналитик, Шутник).",
        "⚙️ *Модели ИИ*: Переключите модель (Gemini 2.0, 2.5 Pro и др.).",
        "📊 *Лимиты*: Проверьте доступные запросы.",
        f"🎁 *Бонус*: Получите генерации за подписку на [канал]({NEWS_CHANNEL_LINK}).",
        "💎 *Подписка Профи*: Увеличьте лимиты.",
        "\n💡 Просто отправьте свой вопрос или задание боту\!"
    ]
    final_help_text_md = "\n".join([escape_markdown(part, version=2) if not part.startswith("`") and not NEWS_CHANNEL_LINK in part else part for part in help_text_parts])
    reply_markup = generate_menu_keyboard("help_submenu", context)
    
    try:
        if message_to_edit:
            await message_to_edit.edit_text(final_help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            await update.message.reply_text(final_help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending help: {e}")
        plain_help_text = ["Я ИИ-бот Gemini. Используйте меню:", "- Режимы ИИ: Выберите агента.", "- Модели ИИ: Переключите модель.",
                           "- Лимиты: Проверьте запросы.", f"- Бонус: Генерации за подписку на {NEWS_CHANNEL_LINK}.", "- Подписка Профи: Увеличьте лимиты.", "\nНапишите ваш вопрос."]
        if message_to_edit:
            await message_to_edit.edit_text("\n".join(plain_help_text), reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            await update.message.reply_text("\n".join(plain_help_text), reply_markup=reply_markup, disable_web_page_preview=True)

# --- Обработчик кнопок ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    message_to_edit = query.message
    new_text = ""
    plain_fallback = ""

    if data.startswith("menu_"):
        action = data.split("_")[1]
        target = "_".join(data.split("_")[2:])
        
        if action == "submenu":
            await show_menu(update, context, target, message_to_edit)
            return
        
        elif action == "set_agent":
            if target in AI_MODES and target != "gemini_pro_custom_mode":
                context.user_data['current_ai_mode'] = target
                details = AI_MODES[target]
                new_text = f"🤖 Агент изменен на: *{escape_markdown(details['name'], version=2)}*\n\n{escape_markdown(details['welcome'], version=2)}"
                plain_fallback = f"Агент: {details['name']}.\n{details['welcome']}"
            elif target == "gemini_pro_custom_mode":
                new_text = escape_markdown("Этот режим для Gemini 2.5 Pro выбирается автоматически.", version=2)
                plain_fallback = "Режим для Gemini 2.5 Pro выбирается автоматически."
            else:
                new_text = plain_fallback = "⚠️ Ошибка: Агент не найден."
            reply_markup = generate_menu_keyboard("ai_modes_submenu", context)
        
        elif action == "set_model":
            if target in AVAILABLE_TEXT_MODELS:
                config = AVAILABLE_TEXT_MODELS[target]
                context.user_data['selected_model_id'] = config["id"]
                context.user_data['selected_api_type'] = config["api_type"]
                today_str = datetime.now().strftime("%Y-%m-%d")
                user_model_counts = context.bot_data.get('all_user_daily_counts', {}).get(user_id, {})
                model_daily_usage = user_model_counts.get(target, {'date': '', 'count': 0})
                current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
                actual_l = get_user_actual_limit_for_model(user_id, target, context)
                limit_str = f'Ваш лимит для этой модели: {current_c_display}/{actual_l} в день'
                new_text = f"⚙️ Модель изменена на: *{escape_markdown(config['name'], version=2)}*\n{escape_markdown(limit_str, version=2)}"
                plain_fallback = f"Модель: {config['name']}. {limit_str}."
            else:
                new_text = plain_fallback = "⚠️ Ошибка: Такая модель не найдена."
            reply_markup = generate_menu_keyboard("models_submenu", context)
        
        elif action == "show_limits":
            await show_limits(update, context, message_to_edit)
            return
        
        elif action == "check_bonus":
            await claim_news_bonus_logic(update, context, called_from_button=True, message_to_edit=message_to_edit)
            return
        
        elif action == "show_subscription":
            await show_subscription(update, context, message_to_edit)
            return
        
        elif action == "show_help":
            await show_help(update, context, message_to_edit)
            return
        
        elif action == "back":
            await show_menu(update, context, target, message_to_edit)
            return
        
        elif action == "goto" and target == "main_menu":
            await show_menu(update, context, "main_menu", message_to_edit)
            return

    elif data == "buy_profi_2days":
        await buy_button_handler(update, context)
        return

    if new_text and message_to_edit:
        try:
            await message_to_edit.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup, disable_web_page_preview=True)
        except telegram.error.BadRequest:
            try:
                await message_to_edit.edit_text(text=plain_fallback, reply_markup=reply_markup, disable_web_page_preview=True)
            except Exception as e_pf:
                logger.error(f"Fallback edit failed in button_callback: {e_pf}")

async def buy_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not PAYMENT_PROVIDER_TOKEN or "YOUR_REAL_PAYMENT_PROVIDER_TOKEN_HERE" in PAYMENT_PROVIDER_TOKEN:
        await query.message.reply_text("⚠️ Сервис оплаты временно недоступен.", reply_markup=get_main_reply_keyboard())
        return
    prices = [LabeledPrice(label="Подписка Профи (2 дня)", amount=99 * 100)]
    try:
        await context.bot.send_invoice(chat_id=user_id, title="Подписка Профи (2 дня)",
            description="Доступ к расширенным лимитам Gemini на 2 дня.",
            payload=f"profi_2days_uid{user_id}_t{int(datetime.now().timestamp())}",
            provider_token=PAYMENT_PROVIDER_TOKEN, currency="RUB", prices=prices)
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.error(f"Error sending invoice to user {user_id}: {e}")
        await query.message.reply_text("⚠️ Не удалось создать счет. Попробуйте позже.")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("profi_2days_uid"): await query.answer(ok=True)
    else: await query.answer(ok=False, error_message="Платеж не может быть обработан.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    if payment.invoice_payload.startswith("profi_2days_uid"):
        valid_until = (datetime.now() + timedelta(days=2)).isoformat()
        context.bot_data.setdefault('user_subscriptions', {})[user_id] = {
            'level': PRO_SUBSCRIPTION_LEVEL_KEY, 'valid_until': valid_until,
            'purchase_date': datetime.now().isoformat(), 'payload': payment.invoice_payload,
            'amount': payment.total_amount, 'currency': payment.currency
        }
        await update.message.reply_text(
            f"🎉 Оплата успешна! Подписка Профи активирована до {datetime.fromisoformat(valid_until):%Y-%m-%d %H:%M}\.\nТеперь вам доступны расширенные лимиты!",
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    else:
        await update.message.reply_text("Оплата прошла, но тип подписки не распознан.", reply_markup=get_main_reply_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id
    if not user_message or not user_message.strip():
        await update.message.reply_text("Пожалуйста, отправьте непустой запрос.", reply_markup=get_main_reply_keyboard())
        return

    current_model_key = get_current_model_key(context)
    selected_model_details = AVAILABLE_TEXT_MODELS[current_model_key]
    system_prompt = get_current_mode_details(context)["prompt"]

    can_request, limit_message_text, _ = check_and_log_request_attempt(user_id, current_model_key, context)
    if not can_request:
        await update.message.reply_text(limit_message_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    reply_text = "Произошла ошибка при обработке вашего запроса."
    request_successful = False
    api_type = selected_model_details.get("api_type")

    if api_type == "google_genai":
        if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
            reply_text = "Ключ API для Google Gemini не настроен."
        else:
            try:
                model_id = selected_model_details["id"]
                model = genai.GenerativeModel(model_id)
                gen_config_params = {"temperature": 0.75}
                if MAX_OUTPUT_TOKENS_GEMINI_LIB > 0 and not any(s_id in model_id for s_id in ["1.5", "2.0"]):
                     gen_config_params["max_output_tokens"] = MAX_OUTPUT_TOKENS_GEMINI_LIB
                
                chat_session = model.start_chat(history=[{"role": "user", "parts": [system_prompt]}, {"role": "model", "parts": ["Понял. Я готов помочь."]}])
                response = await chat_session.send_message_async(user_message, generation_config=genai.types.GenerationConfig(**gen_config_params))
                
                if response.text and response.text.strip():
                    reply_text = response.text
                    request_successful = True
                else: 
                    block_reason_msg = ""
                    if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                        block_reason_msg = f" Причина: {response.prompt_feedback.block_reason.name if hasattr(response.prompt_feedback.block_reason, 'name') else response.prompt_feedback.block_reason}."
                    if response.candidates and not response.text: 
                         candidate = response.candidates[0]
                         if candidate.finish_reason != 1: 
                              block_reason_msg += f" Завершение: {candidate.finish_reason.name if hasattr(candidate.finish_reason, 'name') else candidate.finish_reason}."
                         if candidate.safety_ratings:
                             block_reason_msg += f" Рейтинги: {[(sr.category.name if hasattr(sr.category, 'name') else sr.category, sr.probability.name if hasattr(sr.probability, 'name') else sr.probability) for sr in candidate.safety_ratings]}."
                    reply_text = f"ИИ (Google) не смог сформировать ответ.{block_reason_msg} Попробуйте другой запрос."
            except google.api_core.exceptions.GoogleAPIError as e_google:
                error_message_lower = str(e_google).lower()
                if "api key not valid" in error_message_lower: reply_text = "⚠️ Ошибка: API ключ Google недействителен."
                elif "billing" in error_message_lower: reply_text = "⚠️ Проблема с биллингом Google API."
                elif "quota" in error_message_lower or "resource has been exhausted" in error_message_lower: reply_text = "⚠️ Исчерпана квота Google API."
                elif "user location" in error_message_lower: reply_text = "⚠️ Модель недоступна в вашем регионе (Google API)."
                elif "model not found" in error_message_lower: reply_text = f"⚠️ Модель '{selected_model_details['id']}' не найдена в Google API."
                else: reply_text = f"Ошибка Google API: {type(e_google).__name__}"
                logger.error(f"GoogleAPIError for {selected_model_details['id']}: {e_google}")
            except Exception as e_general_google:
                logger.error(f"General Google error for {selected_model_details['id']}: {e_general_google}\n{traceback.format_exc()}")
                reply_text = "⚠️ Внутренняя ошибка (Google Gemini)."

    elif api_type == "custom_http_api":
        api_key_val = globals().get(selected_model_details.get("api_key_var_name"))
        if not api_key_val or ("sk-" not in api_key_val and "pk-" not in api_key_val):
            reply_text = f"⚠️ Ключ API для '{selected_model_details['name']}' не настроен."
        else:
            payload = {"model": selected_model_details["id"], "messages": [{"role": "user", "content": system_prompt}, {"role": "user", "content": user_message}],
                       "is_sync": True, "temperature": 0.75, "stream": False}
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {api_key_val}'}
            try:
                api_response = requests.post(selected_model_details["endpoint"], json=payload, headers=headers, timeout=90)
                api_response.raise_for_status()
                response_data = api_response.json()
                if (resp_list := response_data.get("response")) and isinstance(resp_list, list) and resp_list:
                    if (msg_content := resp_list[0].get("message", {}).get("content")):
                        reply_text = msg_content
                        request_successful = True
                    else: reply_text = f"⚠️ ИИ ({selected_model_details['name']}) вернул пустой ответ."
                elif (error_detail_msg := response_data.get("detail")):
                     reply_text = f"⚠️ Ошибка Custom API: {str(error_detail_msg)[:200]}"
                else: reply_text = f"⚠️ Неожиданный ответ от Custom API ({selected_model_details['name']})."
            except requests.exceptions.HTTPError as e_http_custom:
                status_code = e_http_custom.response.status_code
                if status_code == 401: reply_text = f"⚠️ Ошибка 401: Неверный API ключ (Custom API)."
                elif status_code == 402: reply_text = f"⚠️ Ошибка 402: Проблема с оплатой (Custom API)."
                elif status_code == 429: reply_text = f"⚠️ Ошибка 429: Превышен лимит запросов (Custom API)."
                else: reply_text = f"⚠️ Ошибка сети ({status_code}) при обращении к '{selected_model_details['name']}'."
                logger.error(f"HTTPError Custom API {selected_model_details['name']}: {e_http_custom}")
            except Exception as e_general_custom:
                logger.error(f"Error Custom API {selected_model_details['name']}: {e_general_custom}\n{traceback.format_exc()}")
                reply_text = f"⚠️ Ошибка ответа от '{selected_model_details['name']}'."
    else: reply_text = f"⚠️ Неизвестный тип API: {api_type}"

    if request_successful and selected_model_details.get("is_limited"):
        increment_request_count(user_id, current_model_key, context)
            
    reply_text_final, _ = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    await update.message.reply_text(reply_text_final, reply_markup=get_main_reply_keyboard())

async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "🚀 Начало"),
        BotCommand("menu", "📋 Открыть меню"),
        BotCommand("usage", "📊 Лимиты"),
        BotCommand("subscribe", "💎 Подписка Профи"),
        BotCommand("get_news_bonus", "🎁 Бонус"),
        BotCommand("help", "❓ Помощь"),
    ]
    try: await application.bot.set_my_commands(commands)
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

async def main():
    if "YOUR_TELEGRAM_TOKEN" in TOKEN or not TOKEN or len(TOKEN.split(":")[0]) < 8 :
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set correctly or is a placeholder.")
        return
    
    persistence = PicklePersistence(filepath="bot_data.pkl")
    application = Application.builder().token(TOKEN).persistence(persistence).build()
    await set_bot_commands(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", open_menu_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command))
    application.add_handler(CommandHandler("get_news_bonus", get_news_bonus_info_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.Text(["📋 Меню"]), open_menu_command))
    
    application.add_handler(CallbackQueryHandler(button_callback))

    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting bot application...")
    try: await application.run_polling()
    except Exception as e: logger.critical(f"Polling error: {e}\n{traceback.format_exc()}")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logger.info("Bot stopped by user.")
    except Exception as e: logger.critical(f"main() error: {e}\n{traceback.format_exc()}")
