import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PicklePersistence, PreCheckoutQueryHandler
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
MIN_AI_REQUEST_LENGTH = 4  # Минимальная длина запроса к ИИ

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
        "name": "Универсальный",
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
        "welcome": "Активирован режим 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент. "
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя. "
            "Соблюдай вежливость и объективность. "
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости. "
            "Избегай излишнего Markdown-форматирования, если это не улучшает читаемость (например, для блоков кода). "
            "Если твои знания ограничены по времени, указывай это."
        ),
        "welcome": "Активирован режим 'Продвинутый'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "Творческий",
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
        "welcome": "Режим 'Творческий' к вашим услугам! Над какой задачей поработаем?"
    },
    "analyst": {
        "name": "Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик на базе Gemini, специализирующийся на анализе данных, фактов и трендов. "
            "Твоя задача — предоставлять точные, логически обоснованные и структурированные ответы на запросы, связанные с анализом информации, статистики или бизнес-вопросов. "
            "Используй структурированный подход:\n"
            "1. **Анализ:** Разбери запрос на ключевые аспекты.\n"
            "2. **Выводы:** Предоставь четкие выводы или рекомендации.\n"
            "3. **Обоснование:** Объясни свои рассуждения, если требуется.\n"
            "Если данных недостаточно, укажи, что нужно для более точного анализа."
        ),
        "welcome": "Режим 'Аналитик' активирован. Какую задачу проанализировать?"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini. "
            "Твоя задача — отвечать на запросы с легкостью, остроумием и юмором, сохраняя при этом полезность. "
            "Добавляй шутки, анекдоты или забавные комментарии, но оставайся в рамках приличия. "
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

# --- Конфигурация API Google Gemini ---
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

# --- Вспомогательные функции ---
def get_current_mode_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    current_model_key = get_current_model_key(context)
    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
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
                logger.info(f"Inferred api_type to '{info.get('api_type')}' for model_id '{selected_id}'")
            return key

    logger.warning(f"Could not find key for model_id '{selected_id}'. Falling back to default.")
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    context.user_data['selected_model_id'] = default_model_config["id"]
    context.user_data['selected_api_type'] = default_model_config["api_type"]
    return DEFAULT_MODEL_KEY

def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    model_key = get_current_model_key(context)
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

def get_user_actual_limit_for_model(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config:
        return 0
    all_user_subscriptions = context.bot_data.setdefault('user_subscriptions', {})
    user_subscription_details = all_user_subscriptions.get(user_id, {})
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
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and context.user_data.get('claimed_news_bonus', False):
            bonus_uses_left = context.user_data.get('news_bonus_uses_left', 0)
            return base_limit + bonus_uses_left
        return base_limit
    return model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return True, "", 0

    is_profi_subscriber = False
    if model_config.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro"]:
        user_subscription_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception:
                pass

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
        message_parts = [f"Вы достигли лимита ({current_daily_count}/{actual_daily_limit}) для {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not context.user_data.get('claimed_news_bonus', False):
                message_parts.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонусной генерации!')
            elif context.user_data.get('news_bonus_uses_left', 0) == 0:
                message_parts.append("ℹ️ Бонус за подписку использован.")
        message_parts.append("Попробуйте завтра или купите подписку в меню «Подписка».")
        return False, "\n".join(message_parts), current_daily_count
    return True, "", current_daily_count

def increment_request_count(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
        is_profi_subscriber = False
        user_subscription_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception:
                pass
        
        if not is_profi_subscriber:
            news_bonus_uses_left = context.user_data.get('news_bonus_uses_left', 0)
            if news_bonus_uses_left > 0:
                context.user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
                logger.info(f"User {user_id} consumed bonus for {model_key}. Remaining: {context.user_data['news_bonus_uses_left']}")
                return

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': today_str, 'count': 0})
    if model_daily_usage['date'] != today_str:
        model_daily_usage.update({'date': today_str, 'count': 0})
    model_daily_usage['count'] += 1
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
async def try_delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_command_message = context.user_data.get('user_command_message', {})
    message_id = user_command_message.get('message_id')
    timestamp = user_command_message.get('timestamp')

    if not message_id or not timestamp:
        return

    try:
        msg_time = datetime.fromisoformat(timestamp)
        if datetime.now(msg_time.tzinfo) - msg_time > timedelta(hours=48):
            logger.info(f"User message {message_id} is older than 48 hours, clearing")
            context.user_data.pop('user_command_message', None)
            return
    except Exception:
        logger.warning("Invalid user message timestamp, clearing")
        context.user_data.pop('user_command_message', None)
        return

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted user message {message_id}")
        context.user_data.pop('user_command_message', None)
    except telegram.error.BadRequest as e:
        logger.warning(f"Failed to delete user message {message_id}: {e}")
        context.user_data.pop('user_command_message', None)

# --- Функции для меню на клавиатуре ---
def generate_menu_keyboard(menu_key: str, context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
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

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_key: str):
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        await update.message.reply_text("Ошибка: Меню не найдено.", reply_markup=generate_menu_keyboard("main_menu", context))
        return
    
    context.user_data['current_menu'] = menu_key
    text = menu["title"]
    reply_markup = generate_menu_keyboard(menu_key, context)
    
    try:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=None,
            disable_web_page_preview=True
        )
        logger.info(f"Sent menu message for {menu_key}: {text}")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending menu message for {menu_key}: {e}")
        await update.message.reply_text(
            "Ошибка при отображении меню. Попробуйте снова.",
            reply_markup=generate_menu_keyboard("main_menu", context)
        )

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    context.user_data.setdefault('current_menu', 'main_menu')
    if 'selected_model_id' not in context.user_data or 'selected_api_type' not in context.user_data:
        default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data.update({'selected_model_id': default_model_conf["id"], 'selected_api_type': default_model_conf["api_type"]})
    
    # Сохраняем данные команды пользователя
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    
    current_model_key = get_current_model_key(context)
    current_mode_name = get_current_mode_details(context)['name']
    current_model_name = AVAILABLE_TEXT_MODELS[current_model_key]['name']

    greeting = f"👋 Привет! Я твой ИИ-бот на базе Gemini.<br>🧠 Агент: <b>{current_mode_name}</b><br>⚙️ Модель: <b>{current_model_name}</b><br><br>💬 Задавайте вопросы или используйте меню ниже!"
    try:
        await update.message.reply_text(
            greeting,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard("main_menu", context),
            disable_web_page_preview=True
        )
        logger.info(f"Sent start message for user {user_id}: {greeting}")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending /start message: {e}")
        plain_text = f"Привет! Я ИИ-бот Gemini.\nАгент: {current_mode_name}\nМодель: {current_model_name}\n\nЗадавайте вопросы или используйте меню!"
        await update.message.reply_text(
            plain_text,
            reply_markup=generate_menu_keyboard("main_menu", context)
        )
    logger.info(f"Start command processed for user {user_id}.")

async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)
    await show_menu(update, context, "main_menu")

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)
    await show_limits(update, context)

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)
    await show_subscription(update, context)

async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)
    await claim_news_bonus_logic(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)
    await show_help(update, context)

async def claim_news_bonus_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        text = "Функция бонуса не настроена."
        try:
            await update.message.reply_text(
                text,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                parse_mode=None
            )
            logger.info(f"Sent bonus not configured message: {text}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for bonus not configured: {e}")
            await update.message.reply_text(
                text,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        text = "Ошибка: Бонусная модель не найдена."
        try:
            await update.message.reply_text(
                text,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                parse_mode=None
            )
            logger.info(f"Sent bonus model not found message: {text}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for bonus model not found: {e}")
            await update.message.reply_text(
                text,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )
        return

    bonus_model_name = bonus_model_config['name']

    if context.user_data.get('claimed_news_bonus', False):
        uses_left = context.user_data.get('news_bonus_uses_left', 0)
        if uses_left > 0:
            reply_text = f'Вы уже активировали бонус. У вас осталось <b>{uses_left}</b> генераций для {bonus_model_name}.<br><a href="{NEWS_CHANNEL_LINK}">Канал</a>'
        else:
            reply_text = f'Бонус для {bonus_model_name} использован.<br><a href="{NEWS_CHANNEL_LINK}">Канал</a>'
        try:
            await update.message.reply_text(
                reply_text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent bonus already claimed message: {reply_text}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for bonus already claimed: {e}")
            await update.message.reply_text(
                reply_text.replace('<b>', '').replace('</b>', ''),
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )
        return

    try:
        member_status = await context.bot.get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member_status.status in ['member', 'administrator', 'creator']:
            context.user_data['claimed_news_bonus'] = True
            context.user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            success_text = f'🎉 Спасибо за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>!<br>Вам начислена <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> генерация для {bonus_model_name}.'
            try:
                await update.message.reply_text(
                    success_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=generate_menu_keyboard('main_menu', context),
                    disable_web_page_preview=True
                )
                logger.info(f"Sent bonus success message: {success_text}")
            except telegram.error.BadRequest as e:
                logger.error(f"Error sending message for bonus success: {e}")
                await update.message.reply_text(
                    success_text.replace('<b>', '').replace('</b>', ''),
                    reply_markup=generate_menu_keyboard('main_menu', context)
                )
        else:
            fail_text = f'Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> и нажмите «Получить» снова.'
            reply_markup_inline = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)]
            ])
            try:
                await update.message.reply_text(
                    fail_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup_inline,
                    disable_web_page_preview=True
                )
                logger.info(f"Sent bonus subscription required message: {fail_text}")
            except telegram.error.BadRequest as e:
                logger.error(f"Error sending message for bonus subscription required: {e}")
                await update.message.reply_text(
                    fail_text,
                    reply_markup=reply_markup_inline
                )
    except telegram.error.BadRequest as e:
        error_text_response = str(e).lower()
        reply_message_on_error = f"Ошибка проверки подписки: {str(e)}. Попробуйте позже."
        if "user not found" in error_text_response or "member not found" in error_text_response or "participant not found" in error_text_response:
            reply_message_on_error = f'Мы не смогли подтвердить подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>. Подпишитесь и попробуйте снова.'
        elif "chat not found" in error_text_response or "channel not found" in error_text_response:
            reply_message_on_error = "Канал не найден."
        elif "bot is not a member" in error_text_response:
            reply_message_on_error = f"Бот должен быть участником канала."
        logger.error(f"BadRequest error checking channel membership: {e}")
        try:
            await update.message.reply_text(
                reply_message_on_error,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent bonus error message: {reply_message_on_error}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for bonus error: {e}")
            await update.message.reply_text(
                reply_message_on_error,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )

async def show_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)

    user_subscription_details = context.bot_data.setdefault('user_subscriptions', {}).get(user_id, {})
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
            user_model_counts = context.bot_data.get('all_user_daily_counts', {}).get(user_id, {})
            model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
            bonus_note = ""
            if model_k == NEWS_CHANNEL_BONUS_MODEL_KEY and context.user_data.get('claimed_news_bonus', False) and context.user_data.get('news_bonus_uses_left', 0) > 0:
                bonus_note = " (вкл. бонус)"
            usage_text_parts.append(f"▫️ {model_c['name']}: <b>{current_c_display}/{actual_l}</b>{bonus_note}")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
        bonus_info = ""
        if not context.user_data.get('claimed_news_bonus', False):
            bonus_info = f'<br>🎁 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> генерации ({bonus_model_name})!'
        elif (bonus_uses_left := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info = f'<br>🎁 У вас <b>{bonus_uses_left}</b> бонусных генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
        else:
            bonus_info = f'<br>ℹ️ Бонус для {bonus_model_name} использован (<a href="{NEWS_CHANNEL_LINK}">канал</a>).'
        usage_text_parts.append(bonus_info)

    if not subscription_active:
        usage_text_parts.append(f"<br>Больше лимитов? Меню «Подписка».")

    final_usage_text = "\n".join(usage_text_parts)
    reply_markup = generate_menu_keyboard(context.user_data.get('current_menu', 'limits_submenu'), context)

    try:
        await update.message.reply_text(
            final_usage_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        logger.info(f"Sent limits message: {final_usage_text}")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending message for show_limits: {e}")
        await update.message.reply_text(
            final_usage_text.replace('<b>', '').replace('</b>', ''),
            reply_markup=reply_markup
        )

async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)

    user_subscription_details = context.bot_data.setdefault('user_subscriptions', {}).get(user_id, {})
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
    reply_markup = generate_menu_keyboard(context.user_data.get('current_menu', 'subscription_submenu'), context)

    try:
        await update.message.reply_text(
            final_sub_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        logger.info(f"Sent subscription message: {final_sub_text}")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending message for show_subscription: {e}")
        await update.message.reply_text(
            final_sub_text.replace('<b>', '').replace('</b>', ''),
            reply_markup=reply_markup
        )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)

    help_text = (
        "<b>❓ Помощь</b>\n\n"
        "Я — ИИ-бот на базе Gemini. Вот что я умею:\n"
        "▫️ Отвечать на вопросы в разных режимах ИИ\n"
        "▫️ Менять модели и режимы через меню\n"
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
    reply_markup = generate_menu_keyboard(context.user_data.get('current_menu', 'help_submenu'), context)

    try:
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        logger.info(f"Sent help message: {help_text}")
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending message for show_help: {e}")
        await update.message.reply_text(
            help_text.replace('<b>', '').replace('</b>', ''),
            reply_markup=reply_markup
        )

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    current_menu_key = context.user_data.get('current_menu', 'main_menu')
    current_menu = MENU_STRUCTURE.get(current_menu_key, MENU_STRUCTURE['main_menu'])

    if not is_menu_button_text(button_text):
        logger.info(f"Text '{button_text}' is not a menu button, skipping to handle_text")
        return

    context.user_data['user_command_message'] = {
        'message_id': update.message.message_id,
        'timestamp': datetime.now().isoformat()
    }
    await try_delete_user_message(update, context)

    logger.info(f"Processing button '{button_text}' in menu '{current_menu_key}'")

    if button_text == "⬅️ Назад":
        parent_menu = current_menu.get("parent")
        if parent_menu:
            await show_menu(update, context, parent_menu)
        else:
            await show_menu(update, context, "main_menu")
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, context, "main_menu")
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
        try:
            await update.message.reply_text(
                text,
                reply_markup=generate_menu_keyboard(current_menu_key, context),
                parse_mode=None
            )
            logger.info(f"Sent unrecognized command message: {text}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for unrecognized command: {e}")
            await update.message.reply_text(
                text,
                reply_markup=generate_menu_keyboard(current_menu_key, context)
            )
        return

    action = selected_item["action"]
    target = selected_item["target"]
    logger.info(f"Button '{button_text}' triggers action '{action}' with target '{target}'")

    if action == "submenu":
        await show_menu(update, context, target)
    elif action == "set_agent":
        return_menu = current_menu.get("parent", "main_menu")
        if target in AI_MODES and target != "gemini_pro_custom_mode":
            context.user_data['current_ai_mode'] = target
            details = AI_MODES[target]
            new_text = f"🤖 Агент изменён на: <b>{details['name']}</b><br><br>{details['welcome']}"
            plain_fallback = f"Агент: {details['name']}.\n{details['welcome']}"
        elif target == "gemini_pro_custom_mode":
            new_text = "Режим для Gemini Pro выбирается автоматически."
            plain_fallback = "Режим для Gemini Pro выбирается автоматически."
        else:
            new_text = "⚠️ Ошибка: Агент не найден."
            plain_fallback = "⚠️ Ошибка: Агент не найден."
        try:
            await update.message.reply_text(
                new_text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard(return_menu, context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent set_agent message for {target}: {new_text}")
            context.user_data['current_menu'] = return_menu
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for set_agent {target}: {e}")
            await update.message.reply_text(
                plain_fallback,
                reply_markup=generate_menu_keyboard(return_menu, context)
            )
            context.user_data['current_menu'] = return_menu
    elif action == "set_model":
        return_menu = current_menu.get("parent", "main_menu")
        if target in AVAILABLE_TEXT_MODELS:
            config = AVAILABLE_TEXT_MODELS[target]
            context.user_data['selected_model_id'] = config["id"]
            context.user_data['selected_api_type'] = config["api_type"]
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = context.bot_data.get('all_user_daily_counts', {}).get(user_id, {})
            model_daily_usage = user_model_counts.get(target, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            actual_l = get_user_actual_limit_for_model(user_id, target, context)
            limit_str = f'Лимит: {current_c_display}/{actual_l} в день'
            new_text = f"⚙️ Модель изменена на: <b>{config['name']}</b><br>{limit_str}"
            plain_fallback = f"Модель: {config['name']}. {limit_str}."
        else:
            new_text = "⚠️ Ошибка: Модель не найдена."
            plain_fallback = "⚠️ Ошибка: Модель не найдена."
        try:
            await update.message.reply_text(
                new_text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard(return_menu, context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent set_model message for {target}: {new_text}")
            context.user_data['current_menu'] = return_menu
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending message for set_model {target}: {e}")
            await update.message.reply_text(
                plain_fallback,
                reply_markup=generate_menu_keyboard(return_menu, context)
            )
            context.user_data['current_menu'] = return_menu
    elif action == "show_limits":
        await show_limits(update, context)
    elif action == "check_bonus":
        await claim_news_bonus_logic(update, context)
    elif action == "show_subscription":
        await show_subscription(update, context)
    elif action == "show_help":
        await show_help(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    if is_menu_button_text(user_message):
        logger.info(f"Text '{user_message}' is a menu button, skipping handle_text")
        return

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        logger.info(f"Text '{user_message}' is too short for AI request, ignoring")
        try:
            await update.message.reply_text(
                "Запрос слишком короткий. Пожалуйста, уточните ваш вопрос или используйте меню.",
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                parse_mode=None
            )
            logger.info(f"Sent short request message")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending short request message: {e}")
            await update.message.reply_text(
                "Запрос слишком короткий. Пожалуйста, уточните ваш вопрос или используйте меню.",
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )
        return

    logger.info(f"Processing AI request: '{user_message}'")

    current_model_key = get_current_model_key(context)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])
    can_proceed, limit_message, current_count = check_and_log_request_attempt(user_id, current_model_key, context)

    if not can_proceed:
        try:
            await update.message.reply_text(
                limit_message,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent limit reached message: {limit_message}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending limit message: {e}")
            await update.message.reply_text(
                limit_message.replace('<b>', '').replace('</b>', ''),
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )
        return

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        mode_details = get_current_mode_details(context)
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
            headers = {
                "Authorization": f"Bearer {CUSTOM_GEMINI_PRO_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "prompt": full_prompt,
                "max_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB,
                "model": model_config["id"]
            }
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=30)
                )
                response.raise_for_status()
                response_data = response.json()
                response_text = response_data.get("text", "Ответ не получен.").strip()
            except requests.exceptions.RequestException as e:
                response_text = f"Ошибка API: {str(e)}"
                logger.error(f"Custom API error for user {user_id}: {str(e)}")
        else:
            response_text = "Неизвестный тип API."
            logger.error(f"Unknown api_type for model {current_model_key}")

        response_text, was_truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
        if was_truncated:
            logger.info(f"Response for user {user_id} was truncated to {MAX_MESSAGE_LENGTH_TELEGRAM} characters")

        increment_request_count(user_id, current_model_key, context)
        try:
            await update.message.reply_text(
                response_text,
                parse_mode=None,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent AI response for request: '{user_message}': {response_text[:100]}...")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending AI response: {e}")
            await update.message.reply_text(
                "Ошибка при отправке ответа. Попробуйте снова.",
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )

    except Exception as e:
        logger.error(f"Unexpected error processing text for user {user_id}: {str(e)}")
        traceback.print_exc()
        error_message = "Произошла ошибка при обработке запроса. Попробуйте снова."
        try:
            await update.message.reply_text(
                error_message,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context),
                parse_mode=None
            )
            logger.info(f"Sent error message: {error_message}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending error message: {e}")
            await update.message.reply_text(
                error_message,
                reply_markup=generate_menu_keyboard(context.user_data.get('current_menu', 'main_menu'), context)
            )

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
        context.bot_data.setdefault('user_subscriptions', {}).setdefault(user_id, {}).update({
            'level': PRO_SUBSCRIPTION_LEVEL_KEY,
            'valid_until': valid_until.isoformat()
        })
        text = f"🎉 Подписка <b>Профи</b> активирована до <b>{valid_until.strftime('%Y-%m-%d')}</b>! Наслаждайтесь расширенными лимитами."
        try:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard('main_menu', context),
                disable_web_page_preview=True
            )
            logger.info(f"Sent payment success message: {text}")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending payment success message: {e}")
            await update.message.reply_text(
                text.replace('<b>', '').replace('</b>', ''),
                reply_markup=generate_menu_keyboard('main_menu', context)
            )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.effective_chat:
        chat_id = update.effective_chat.id
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка. Попробуйте снова или используйте /start.",
                reply_markup=generate_menu_keyboard('main_menu', context),
                parse_mode=None
            )
            logger.info(f"Sent error handler message")
        except telegram.error.BadRequest as e:
            logger.error(f"Error sending error message: {e}")

def main():
    persistence = PicklePersistence(filepath="bot_persistence")
    app = Application.builder().token(TOKEN).persistence(persistence).build()

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
    app.bot.set_my_commands(commands)

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
