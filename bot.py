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
from telegram.ext import PreCheckoutQueryHandler # MessageHandler для SUCCESSFUL_PAYMENT уже есть в filters


nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0") # Убедись, что токен здесь или в переменных окружения
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # ЗАМЕНИ НА СВОЙ КЛЮЧ
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P") # ЗАМЕНИ НА СВОЙ КЛЮЧ
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")

# ВАЖНО: Получи этот токен от @BotFather после подключения платежного провайдера
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "YOUR_REAL_PAYMENT_PROVIDER_TOKEN_HERE")

YOUR_ADMIN_ID = 489230152 # Этот ID больше не используется для /grantsub, но может быть полезен для других админских нужд в будущем

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000

# --- ОБНОВЛЕННЫЕ ЛИМИТЫ ---
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72                    # Бесплатно для "2.0" (Gemini 2.0 Flash) - ИЗМЕНЕНО
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48        # Бесплатно для "2.5 флэш" (Gemini 2.5 Flash Preview) - ИЗМЕНЕНО
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75    # С подпиской для "2.5 флэш"

DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0                       # Бесплатно для "2.5 про" (Custom API Gemini 2.5 Pro) - ИЗМЕНЕНО (бонус за подписку на канал)
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25              # С подпиской для "2.5 про"

PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1" # Ключ для идентификации уровня подписки "Профи"

# --- КАНАЛ НОВОСТЕЙ И БОНУС ---
# ВАЖНО: Замените значения ниже на реальный юзернейм и ссылку вашего новостного канала!
NEWS_CHANNEL_USERNAME = "@timextech"  # Например, "@my_cool_news_channel" (начинается с @)
NEWS_CHANNEL_LINK = "https://t.me/timextech" # Например, "https://t.me/my_cool_news_channel"
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro" # Модель, для которой дается бонус
NEWS_CHANNEL_BONUS_GENERATIONS = 1 # Количество бонусных генераций

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
            "3.  **Диалоги:** Оформляй диалоги стандартным образом (например, `- Привет! - сказал он.` или с новой строки для каждого персонажа).\n"
            "4.  **Без Markdown:** Генерируй чистый текст без Markdown-разметки (звездочек, решеток и т.п.), если только это не специфический элемент форматирования самого творческого произведения (например, название главы, выделенное заглавными).\n"
            "5.  **Язык:** Используй богатый и выразительный язык, соответствующий творческой задаче.\n"
            "6.  **Завершённость:** Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

# --- МОДЕЛИ ИИ ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": { # Пользователь называет "2.0"
        "name": "⚡️ Gemini 2.0 Flash (100/день)",
        "id": "gemini-2.0-flash", # ПРОВЕРЬ АКТУАЛЬНОСТЬ ЭТОГО ID ДЛЯ GOOGLE GENAI! Может быть "gemini-1.5-flash-latest"
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY, # 100
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": { # Пользователь называет "2.5 флэш"
        "name": "💨 Gemini 2.5 Flash Preview",
        "id": "gemini-2.5-flash-preview-04-17", # ПРОВЕРЬ АКТУАЛЬНОСТЬ ЭТОГО ID ДЛЯ GOOGLE GENAI! Может быть новее, напр. 'gemini-1.5-flash-preview-0514'
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY, # 50
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY, # 75
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": { # Пользователь называет "2.5 про"
        "name": "🌟 Gemini 2.5 Pro (Продвинутый)",
        "id": "gemini-2.5-pro-preview-03-25", # ID для Custom API (gen-api.ru), проверь его актуальность у провайдера
        "api_type": "custom_http_api",
        "endpoint": CUSTOM_GEMINI_PRO_ENDPOINT,
        "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro", 
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY, # 2
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY, # 25
        "cost_category": "custom_api_pro_paid",
        "pricing_info": {} 
    }
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash" 
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]


# --- Конфигурация API Google Gemini ---
if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
    logger.warning("Google Gemini API key (GOOGLE_GEMINI_API_KEY) is not set correctly or uses a placeholder. Google AI models may not work.")
else:
    try:
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini API: {str(e)}")

if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY:
    logger.warning("Custom Gemini Pro API key (CUSTOM_GEMINI_PRO_API_KEY) is not set correctly or uses a placeholder. Custom API model may not work.")


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

    if not selected_api_type:
        for key_fallback, info_fallback in AVAILABLE_TEXT_MODELS.items():
            if info_fallback["id"] == selected_id:
                selected_api_type = info_fallback.get("api_type")
                context.user_data['selected_api_type'] = selected_api_type
                logger.debug(f"Inferred and saved api_type '{selected_api_type}' for model_id '{selected_id}'")
                break
    
    if not selected_api_type:
         logger.warning(f"API type for selected_model_id '{selected_id}' is not stored and couldn't be inferred. Falling back to default model key: {DEFAULT_MODEL_KEY}.")
         default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
         context.user_data['selected_model_id'] = default_model_config["id"]
         context.user_data['selected_api_type'] = default_model_config["api_type"]
         return DEFAULT_MODEL_KEY

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id and info.get("api_type") == selected_api_type:
            return key
            
    logger.warning(f"Could not find key for model_id '{selected_id}' and api_type '{selected_api_type}'. Falling back to default: {DEFAULT_MODEL_KEY}.")
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    context.user_data['selected_model_id'] = default_model_config["id"]
    context.user_data['selected_api_type'] = default_model_config["api_type"]
    return DEFAULT_MODEL_KEY


def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    model_key = get_current_model_key(context)
    if model_key not in AVAILABLE_TEXT_MODELS:
        logger.error(f"Model key '{model_key}' not found in AVAILABLE_TEXT_MODELS. Falling back to default.")
        return AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    return AVAILABLE_TEXT_MODELS[model_key]

def get_current_model_display_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return get_selected_model_details(context)["name"]

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
    for sep in ['\n\n', '. ', '! ', '? ', '\n']:
        pos = truncated_text.rfind(sep)
        if pos != -1:
            actual_pos = pos + (len(sep) -1 if sep.endswith(' ') and len(sep) > 1 else len(sep))
            if actual_pos > 0:
                possible_cut_points.append(actual_pos)
    if possible_cut_points:
        cut_at = max(possible_cut_points)
        if cut_at > adjusted_max_length * 0.5:
             return text[:cut_at].strip() + suffix, True
    last_space = truncated_text.rfind(' ')
    if last_space != -1 and last_space > adjusted_max_length * 0.5:
        return text[:last_space].strip() + suffix, True
    return text[:adjusted_max_length].strip() + suffix, True

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🤖 Режим ИИ"), KeyboardButton("⚙️ Модель ИИ")],
        [KeyboardButton("📊 Лимиты"), KeyboardButton("💎 Подписка Профи")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# --- Управление лимитами ---
def get_user_actual_limit_for_model(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0

    all_user_subscriptions = context.bot_data.setdefault('user_subscriptions', {})
    user_subscription_details = all_user_subscriptions.get(user_id, {'level': None, 'valid_until': None})
    
    current_sub_level = None
    if user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            now_dt = datetime.now(valid_until_dt.tzinfo) 

            if now_dt.date() <= valid_until_dt.date():
                current_sub_level = user_subscription_details.get('level')
            else:
                logger.info(f"Subscription for user {user_id} (level {user_subscription_details.get('level')}) expired on {user_subscription_details['valid_until']}.")
        except ValueError:
            logger.error(f"Invalid date format for subscription for user {user_id}: {user_subscription_details['valid_until']}")
        except Exception as e_date:
             logger.error(f"Error processing subscription date for user {user_id}: {e_date}")


    limit_type = model_config.get("limit_type")
    actual_limit = 0

    if limit_type == "daily_free":
        actual_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY: 
            actual_limit = model_config.get("subscription_daily_limit", 0)
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY: 
            actual_limit = model_config.get("subscription_daily_limit", 0)
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    else: 
        actual_limit = model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0
        if model_config.get("is_limited") and actual_limit == float('inf'): 
            logger.warning(f"Model {model_key} is limited but actual_limit is infinity for user {user_id} (sub: {current_sub_level}). Setting to 0.")
            actual_limit = 0
    return actual_limit

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        logger.debug(f"Model {model_key} not found or not limited. Allowing request.")
        return True, "", 0

    # --- News Channel Bonus Check ---
    is_profi_subscriber = False # Определим заранее, нужен для логики бонуса и лимитов
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY or model_config.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro"]:
        all_user_subscriptions = context.bot_data.get('user_subscriptions', {})
        user_subscription_details = all_user_subscriptions.get(user_id, {})
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY:
            if user_subscription_details.get('valid_until'):
                try:
                    valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
                    now_dt = datetime.now(valid_until_dt.tzinfo)
                    if now_dt.date() <= valid_until_dt.date():
                        is_profi_subscriber = True
                except ValueError:
                    logger.error(f"Invalid date format for subscription for user {user_id}: {user_subscription_details['valid_until']}")
                except Exception as e_date_check:
                    logger.error(f"Error checking subscription date for user {user_id}: {e_date_check}")


    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
        news_bonus_uses_left = context.user_data.get('news_bonus_uses_left', 0)
        if news_bonus_uses_left > 0:
            logger.info(f"User {user_id} has {news_bonus_uses_left} news channel bonus uses for {model_key}. Allowing request via bonus.")
            return True, "bonus_available", 0 # count_used is 0 for this check, as it's a bonus
    # --- End News Channel Bonus Check ---

    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': '', 'count': 0})

    if model_daily_usage['date'] != today_str:
        logger.info(f"New day for user {user_id}, model {model_key}. Resetting count from {model_daily_usage['count']} (date {model_daily_usage['date']}).")
        model_daily_usage['date'] = today_str
        model_daily_usage['count'] = 0

    current_user_model_count = model_daily_usage['count']
    actual_limit = get_user_actual_limit_for_model(user_id, model_key, context) # actual_limit уже учитывает Profi подписку
    logger.debug(f"User {user_id}, Model {model_key}: Daily Count={current_user_model_count}, Daily Limit={actual_limit}, IsProfi={is_profi_subscriber}")

    if current_user_model_count >= actual_limit:
        message = (f"Вы достигли дневного лимита ({current_user_model_count}/{actual_limit}) "
                   f"для модели '{model_config['name']}'.\n")

        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            claimed_bonus_flag = context.user_data.get('claimed_news_bonus', False)
            current_bonus_uses = context.user_data.get('news_bonus_uses_left', 0)

            if not claimed_bonus_flag :
                message += (f"💡 Подпишитесь на наш новостной канал {NEWS_CHANNEL_LINK} и используйте команду "
                            f"`/claim_news_bonus`, чтобы получить {NEWS_CHANNEL_BONUS_GENERATIONS} бесплатную генерацию для этой модели!\n")
            elif current_bonus_uses == 0 and claimed_bonus_flag:
                 message += "ℹ️ Ваш бонус за подписку на новости для этой модели уже использован.\n"

        message += "Попробуйте завтра или рассмотрите подписку /subscribe для увеличения лимитов."
        return False, message, current_user_model_count
    return True, "", current_user_model_count

def increment_request_count(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return

    # --- News Channel Bonus Consumption ---
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
        all_user_subscriptions = context.bot_data.get('user_subscriptions', {})
        user_subscription_details = all_user_subscriptions.get(user_id, {})
        is_profi_subscriber = False
        if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY:
            if user_subscription_details.get('valid_until'):
                try:
                    valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
                    now_dt = datetime.now(valid_until_dt.tzinfo) # Use timezone from valid_until_dt if available
                    if now_dt.date() <= valid_until_dt.date():
                        is_profi_subscriber = True
                except ValueError:
                    pass # Invalid date format
                except Exception:
                    pass # Other date processing errors


        if not is_profi_subscriber:
            news_bonus_uses_left = context.user_data.get('news_bonus_uses_left', 0)
            if news_bonus_uses_left > 0:
                context.user_data['news_bonus_uses_left'] = news_bonus_uses_left - 1
                logger.info(f"User {user_id} consumed a news channel bonus use for {model_key}. Remaining bonus uses: {context.user_data['news_bonus_uses_left']}")
                # This was a bonus use, do not increment the daily model count for regular limits
                return # IMPORTANT: Exit early, daily count not affected
    # --- End News Channel Bonus Consumption ---

    today_str = datetime.now().strftime("%Y-%m-%d")
    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': today_str, 'count': 0})

    if model_daily_usage['date'] != today_str:
        model_daily_usage['date'] = today_str
        model_daily_usage['count'] = 0

    model_daily_usage['count'] += 1
    logger.info(f"User {user_id} daily request count for {model_key} incremented to {model_daily_usage['count']}")


# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    if 'selected_model_id' not in context.user_data or 'selected_api_type' not in context.user_data:
        default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data['selected_model_id'] = default_model_conf["id"]
        context.user_data['selected_api_type'] = default_model_conf["api_type"]

    context.bot_data.setdefault('user_subscriptions', {}) 
    context.bot_data.setdefault('all_user_daily_counts', {})
    
    current_model_key_for_start = get_current_model_key(context)
    current_mode_name_for_start = get_current_mode_details(context)['name']
    current_model_name_for_start = AVAILABLE_TEXT_MODELS[current_model_key_for_start]['name']
    
    greeting = escape_markdown("👋 Привет! Я твой многофункциональный ИИ-бот на базе Gemini.", version=2)
    mode_line = f"🧠 {escape_markdown('Текущий режим: ', version=2)}*{escape_markdown(current_mode_name_for_start, version=2)}*"
    model_line = f"⚙️ {escape_markdown('Текущая модель: ', version=2)}*{escape_markdown(current_model_name_for_start, version=2)}*"
    
    _, limit_msg_check, current_count_for_start = check_and_log_request_attempt(user_id, current_model_key_for_start, context)
    actual_limit_for_model_start = get_user_actual_limit_for_model(user_id, current_model_key_for_start, context)
    limit_info_line = f"📊 {escape_markdown(f'Лимит для этой модели: {current_count_for_start}/{actual_limit_for_model_start} в день.', version=2)}"
    if "Вы достигли" in limit_msg_check: 
        limit_info_line = f"🚫 {escape_markdown(limit_msg_check.splitlines()[0], version=2)}"

    you_can = escape_markdown("Вы можете:", version=2)
    action1 = f"💬 {escape_markdown('Задавать мне вопросы или давать задания.', version=2)}"
    action2 = f"🤖 {escape_markdown('Сменить режим ИИ (`/mode` или кнопка)', version=2)}"
    action3 = f"⚙️ {escape_markdown('Выбрать другую модель ИИ (`/model` или кнопка)', version=2)}"
    action4 = f"📊 {escape_markdown('Узнать свои лимиты (`/usage` или кнопка)', version=2)}"
    action5 = f"💎 {escape_markdown('Ознакомиться с Подпиской Профи (`/subscribe` или кнопка)', version=2)}"
    action6 = f"❓ {escape_markdown('Получить помощь (`/help`)', version=2)}"
    invitation = escape_markdown("Просто напишите ваш запрос!", version=2)

# ЭТОТ БЛОК ДОЛЖЕН БЫТЬ ВНУТРИ ФУНКЦИИ START, С ПРАВИЛЬНЫМ ОТСТУПОМ
    news_channel_info_md = ""
    if NEWS_CHANNEL_LINK and NEWS_CHANNEL_LINK != "https://t.me/YourNewsChannelHandle":
        bonus_model_name_start = "продвинутой модели"
        if NEWS_CHANNEL_BONUS_MODEL_KEY in AVAILABLE_TEXT_MODELS:
            bonus_model_name_start = f"модели '{escape_markdown(AVAILABLE_TEXT_MODELS[NEWS_CHANNEL_BONUS_MODEL_KEY]['name'], version=2)}'"
        news_channel_info_md = (
            f"📢 {escape_markdown(f'Подпишитесь на наш новостной канал, чтобы получить {NEWS_CHANNEL_BONUS_GENERATIONS} бонусную генерацию для {bonus_model_name_start}: ', version=2)}"
            f"{escape_markdown(NEWS_CHANNEL_LINK, version=2)}\n"
            f"{escape_markdown('После подписки используйте команду ', version=2)} `/claim_news_bonus`\n\n"
        )

    text_to_send = (
        f"{greeting}\n\n"
        f"{mode_line}\n"
        f"{model_line}\n"
        f"{limit_info_line}\n\n"
        f"{news_channel_info_md}"  # Вот эта строка
        f"{you_can}\n"
        f"{action1}\n{action2}\n{action3}\n{action4}\n{action5}\n{action6}\n\n"
        f"{invitation}"
    )
    try:
        await update.message.reply_text(text_to_send, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        # И ЭТОТ БЛОК ТОЖЕ С ПРАВИЛЬНЫМ ОТСТУПОМ
        plain_news_channel_info = ""
        if NEWS_CHANNEL_LINK and NEWS_CHANNEL_LINK != "https://t.me/YourNewsChannelHandle":
            bonus_model_name_plain = "продвинутой модели"
            if NEWS_CHANNEL_BONUS_MODEL_KEY in AVAILABLE_TEXT_MODELS:
                bonus_model_name_plain = f"модели '{AVAILABLE_TEXT_MODELS[NEWS_CHANNEL_BONUS_MODEL_KEY]['name']}'"
            plain_news_channel_info = (
                f"Новости и бонус: Подпишитесь на {NEWS_CHANNEL_LINK} и введите /claim_news_bonus "
                f"для {NEWS_CHANNEL_BONUS_GENERATIONS} генерации ({bonus_model_name_plain}).\n\n"
            )

        plain_text_version = (
            f"Привет! Я твой многофункциональный ИИ-бот.\n\n"
            f"Режим: {current_mode_name_for_start}\nМодель: {current_model_name_for_start}\n"
            f"Лимит: {current_count_for_start}/{actual_limit_for_model_start} в день.\n\n"
            f"{plain_news_channel_info}"
            "Вы можете:\n"
            "▫️ Задавать вопросы.\n▫️ /mode - сменить режим\n▫️ /model - сменить модель\n"
            "▫️ /usage - лимиты\n▫️ /subscribe - Подписка Профи\n▫️ /help - помощь\n\n"
            "Ваш запрос?"
        )
        await update.message.reply_text(plain_text_version, reply_markup=get_main_reply_keyboard()) # Правильный отступ
    logger.info(f"Start command processed for user {user_id}.")


async def select_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for key, details in AI_MODES.items():
        if key != "gemini_pro_custom_mode":
            keyboard.append([InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")])
    
    if not keyboard:
         await update.message.reply_text('В данный момент нет доступных режимов для выбора.', reply_markup=get_main_reply_keyboard())
         return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите режим работы для ИИ (для модели Gemini 2.5 Pro режим выбирается автоматически):', reply_markup=reply_markup)


async def select_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_model_{key}")] for key, details in AVAILABLE_TEXT_MODELS.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите модель ИИ:', reply_markup=reply_markup)


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    all_user_subscriptions = context.bot_data.setdefault('user_subscriptions', {})
    user_subscription_details = all_user_subscriptions.get(user_id, {'level': None, 'valid_until': None})
    
    sub_level_key = user_subscription_details.get('level')
    sub_valid_str = user_subscription_details.get('valid_until')
    
    display_sub_level = "Бесплатный доступ"
    subscription_active = False
    if sub_level_key == PRO_SUBSCRIPTION_LEVEL_KEY:
        if sub_valid_str:
            try:
                valid_until_dt = datetime.fromisoformat(sub_valid_str)
                now_dt = datetime.now(valid_until_dt.tzinfo)
                if now_dt.date() <= valid_until_dt.date():
                    display_sub_level = f"💎 Подписка Профи (до {valid_until_dt.strftime('%Y-%m-%d')})"
                    subscription_active = True
                else:
                    display_sub_level = "💎 Подписка Профи (истекла)"
            except ValueError: 
                display_sub_level = "💎 Подписка Профи (ошибка даты)"
        else:
            display_sub_level = "💎 Подписка Профи (нет даты окончания)"


    usage_text = f"📊 **Информация о ваших лимитах**\n\n"
    usage_text += f"Текущий статус: *{escape_markdown(display_sub_level, version=2)}*\n\n"

    usage_text += "Ежедневные лимиты запросов по моделям:\n"
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            _, _, current_c = check_and_log_request_attempt(user_id, model_k, context)
            actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
            usage_text += f"▫️ {escape_markdown(model_c['name'], version=2)}: *{current_c}/{actual_l}*\n"

    # БЛОК ИНФОРМАЦИИ О БОНУСЕ - ПРАВИЛЬНЫЙ ОТСТУП
    if NEWS_CHANNEL_LINK and NEWS_CHANNEL_LINK != "https://t.me/YourNewsChannelHandle":
        bonus_model_name_usage = "продвинутой модели"
        if NEWS_CHANNEL_BONUS_MODEL_KEY in AVAILABLE_TEXT_MODELS:
            bonus_model_name_usage = f"модели '{escape_markdown(AVAILABLE_TEXT_MODELS[NEWS_CHANNEL_BONUS_MODEL_KEY]['name'], version=2)}'"

        claimed_bonus_usage = context.user_data.get('claimed_news_bonus', False)
        bonus_uses_left_usage = context.user_data.get('news_bonus_uses_left', 0)

        if not claimed_bonus_usage:
            usage_text += (
                f"\n🎁 {escape_markdown(f'Подпишитесь на {NEWS_CHANNEL_LINK} и используйте /claim_news_bonus, ', version=2)}"
                f"{escape_markdown(f'чтобы получить {NEWS_CHANNEL_BONUS_GENERATIONS} генерацию для {bonus_model_name_usage}!', version=2)}\n"
            )
        elif bonus_uses_left_usage > 0:
            usage_text += (
                f"\n🎁 {escape_markdown(f'У вас есть {bonus_uses_left_usage} бонусных генераций для {bonus_model_name_usage} ', version=2)}"
                f"{escape_markdown(f'(за подписку на {NEWS_CHANNEL_LINK})', version=2)}.\n"
            )
        else:  # claimed_bonus_usage is True and bonus_uses_left_usage == 0
            usage_text += (
                f"\nℹ️ {escape_markdown(f'Бонус за подписку на {NEWS_CHANNEL_LINK} ({bonus_model_name_usage}) уже использован.', version=2)}\n"
            )
    # КОНЕЦ БЛОКА ИНФОРМАЦИИ О БОНУСЕ

    if not subscription_active: # Эта проверка должна быть здесь
        usage_text += f"\n{escape_markdown('Хотите больше лимитов? Ознакомьтесь с Подпиской Профи:', version=2)} /subscribe"

    try:
        await update.message.reply_text(usage_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        plain_usage_text = f"Статус: {display_sub_level}\nЛимиты:\n"
        for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
            if model_c.get("is_limited"):
                _, _, current_c = check_and_log_request_attempt(user_id, model_k, context)
                actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
                plain_usage_text += f"- {model_c['name']}: {current_c}/{actual_l}\n"

        # БЛОК ИНФОРМАЦИИ О БОНУСЕ ДЛЯ PLAIN TEXT - ПРАВИЛЬНЫЙ ОТСТУП
        if NEWS_CHANNEL_LINK and NEWS_CHANNEL_LINK != "https://t.me/YourNewsChannelHandle":
            bonus_model_name_plain_usage = "продвинутой модели"
            if NEWS_CHANNEL_BONUS_MODEL_KEY in AVAILABLE_TEXT_MODELS:
                bonus_model_name_plain_usage = f"модели '{AVAILABLE_TEXT_MODELS[NEWS_CHANNEL_BONUS_MODEL_KEY]['name']}'"

            claimed_bonus_plain_usage = context.user_data.get('claimed_news_bonus', False)
            bonus_uses_left_plain_usage = context.user_data.get('news_bonus_uses_left', 0)
            if not claimed_bonus_plain_usage:
                plain_usage_text += f"\nБонус: Подпишитесь на {NEWS_CHANNEL_LINK}, команда /claim_news_bonus для {NEWS_CHANNEL_BONUS_GENERATIONS} генерации ({bonus_model_name_plain_usage}).\n"
            elif bonus_uses_left_plain_usage > 0:
                plain_usage_text += f"\nБонус: У вас {bonus_uses_left_plain_usage} генераций для {bonus_model_name_plain_usage} (канал {NEWS_CHANNEL_LINK}).\n"
            else:
                plain_usage_text += f"\nБонус за подписку на {NEWS_CHANNEL_LINK} ({bonus_model_name_plain_usage}) использован.\n"
        # КОНЕЦ БЛОКА ИНФОРМАЦИИ О БОНУСЕ ДЛЯ PLAIN TEXT

        if not subscription_active: # Эта проверка также здесь
            plain_usage_text += "\nПодписка Профи: /subscribe"
        await update.message.reply_text(plain_usage_text, reply_markup=get_main_reply_keyboard()) # Правильный отступ

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = "🌟 **Подписка Профи – Максимум возможностей Gemini!** 🌟\n\n"

    text += "Получите расширенные дневные лимиты для самых мощных моделей:\n"
    text += f"💨 {escape_markdown(AVAILABLE_TEXT_MODELS['google_gemini_2_5_flash_preview']['name'], version=2)}: *{DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY} запросов/день*\n"
    text += f"   (Бесплатно: {DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY} запросов/день)\n"
    text += f"🌟 {escape_markdown(AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name'], version=2)}: *{DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY} запросов/день*\n"
    text += f"   (Бесплатно: {DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY} пробных запроса/день)\n\n"
    
    text += "Базовая модель всегда доступна с щедрым лимитом:\n"
    text += f"⚡️ {escape_markdown(AVAILABLE_TEXT_MODELS['google_gemini_2_0_flash']['name'], version=2)}: *{DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY} запросов/день* (бесплатно для всех)\n\n"

    text += "✨ **Доступный тариф Профи для теста:**\n"
    text += f"▫️ **Тест-драйв (2 дня):** `{escape_markdown('99 рублей', version=2)}`\n"
    text += "\n"

    # Кнопка для инициирования оплаты
    keyboard = [
        [InlineKeyboardButton("💳 Купить Профи (2 дня - 99 RUB)", callback_data="buy_profi_2days")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Сообщение о разработке автоматической оплаты пока уберем отсюда,
    # так как кнопка "Купить" теперь будет пытаться отправить инвойс.
    # Если токен невалидный, обработчик кнопки сообщит об этом.
    
    # text += "🚀 **Как оформить Подписку Профи?**\n"
    # text += "Автоматическая система оплаты находится в разработке и будет доступна в ближайшее время\\!\n"
    # text += "Следите за обновлениями\\.\n\n" 
    # text += f"{escape_markdown('Ваш Telegram User ID (может понадобиться для ручной активации в будущем):', version=2)} `{user_id}`"
    
    try:
        # Отправляем сообщение с кнопкой "Купить"
        if update.callback_query: # Если это результат нажатия на кнопку (например, из /start)
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

    except telegram.error.BadRequest as e_br:
        logger.error(f"Error sending subscribe_info_command with Markdown: {e_br}. Text: {text}")
        # Упрощенный текст и кнопка, если Markdown не сработал
        plain_text = (
            "🌟 Подписка Профи – Максимум Gemini! 🌟\n\n"
            "Преимущества:\n"
            f"- {AVAILABLE_TEXT_MODELS['google_gemini_2_5_flash_preview']['name']}: {DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY} в день (беспл. {DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY})\n"
            f"- {AVAILABLE_TEXT_MODELS['custom_api_gemini_2_5_pro']['name']}: {DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY} в день (беспл. {DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY})\n"
            f"- {AVAILABLE_TEXT_MODELS['google_gemini_2_0_flash']['name']}: {DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY} в день (бесплатно для всех)\n\n"
            "Тариф для теста:\n"
            "- 2 дня: 99 руб.\n"
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(plain_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(plain_text, reply_markup=reply_markup)

# Обработчик для кнопки "Купить"
async def buy_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Отвечаем на коллбэк
    user_id = query.from_user.id

    if query.data == "buy_profi_2days":
        if not PAYMENT_PROVIDER_TOKEN or "YOUR_REAL_PAYMENT_PROVIDER_TOKEN_HERE" in PAYMENT_PROVIDER_TOKEN:
            await query.message.reply_text(
                "⚠️ К сожалению, сервис автоматической оплаты сейчас настраивается администратором и временно недоступен.\n"
                "Пожалуйста, попробуйте позже или следите за обновлениями.",
                reply_markup=get_main_reply_keyboard() # Возвращаем основную клавиатуру
            )
            logger.warning(f"Payment attempt by user {user_id} failed: PAYMENT_PROVIDER_TOKEN is not set.")
            return

        title = "Подписка Профи (2 дня)"
        description = "Доступ к расширенным лимитам моделей Gemini на 2 дня."
        # payload должен быть уникальным для каждого инвойса и содержать информацию для идентификации покупки.
        # Макс. 128 байт. Включаем тип подписки, user_id (для сверки) и временную метку для уникальности.
        payload = f"profi_2days_uid{user_id}_t{int(datetime.now().timestamp())}"
        currency = "RUB"
        price_amount = 99  # Цена в рублях
        prices = [LabeledPrice(label="Подписка Профи (2 дня)", amount=price_amount * 100)]  # Цена в копейках

        try:
            await context.bot.send_invoice(
                chat_id=user_id,
                title=title,
                description=description,
                payload=payload,
                provider_token=PAYMENT_PROVIDER_TOKEN,
                currency=currency,
                prices=prices,
                # start_parameter='profi-2days-test', # Опциональный параметр для deeplink
                # photo_url='URL_TO_YOUR_PRODUCT_IMAGE', # Опционально: URL картинки для инвойса
                # need_shipping_address=False, # Обычно false для цифровых товаров
            )
            logger.info(f"Invoice sent to user {user_id} for 'profi_2days'. Payload: {payload}")
            # После отправки инвойса обычно сообщение, где была кнопка "Купить", можно отредактировать или оставить как есть.
            # Например, убрать кнопку "Купить", чтобы избежать повторных нажатий:
            await query.edit_message_reply_markup(reply_markup=None)

        except Exception as e:
            logger.error(f"Error sending invoice to user {user_id}: {e}")
            await query.message.reply_text("⚠️ Не удалось создать счет для оплаты. Пожалуйста, попробуйте позже.")

# Обработчик PreCheckoutQuery (обязателен для Telegram Payments)
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # Здесь можно добавить логику проверки (например, доступность товара)
    # Для простоты сейчас всегда подтверждаем
    if query.invoice_payload.startswith("profi_2days_uid"): # Проверяем, что это наш payload
        await query.answer(ok=True)
        logger.info(f"PreCheckoutQuery for payload {query.invoice_payload} answered OK.")
    else:
        # Отклоняем неизвестные или невалидные payload
        await query.answer(ok=False, error_message="Что-то пошло не так с этим платежом. Попробуйте снова.")
        logger.warning(f"PreCheckoutQuery for UNKNOWN payload {query.invoice_payload} answered with error.")

# Обработчик успешного платежа
async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload
    
    logger.info(f"Successful payment from user {user_id}! Payload: {invoice_payload}, Amount: {payment_info.total_amount / 100} {payment_info.currency}")

    # Активируем подписку
    if invoice_payload.startswith("profi_2days_uid"):
        try:
            # Рассчитываем дату окончания подписки
            # Используем datetime.now(timezone.utc) для timezone-aware datetime, если работаем с UTC
            # Или просто datetime.now() если все в одной таймзоне
            valid_until_dt = datetime.now() + timedelta(days=2)
            # Сохраняем в ISO формате. fromisoformat потом сможет это распарсить.
            valid_until_iso = valid_until_dt.isoformat() 

            all_user_subscriptions = context.bot_data.setdefault('user_subscriptions', {})
            all_user_subscriptions[user_id] = {
                'level': PRO_SUBSCRIPTION_LEVEL_KEY,
                'valid_until': valid_until_iso, # 'YYYY-MM-DDTHH:MM:SS.ffffff'
                'purchase_date': datetime.now().isoformat(),
                'payload': invoice_payload,
                'amount': payment_info.total_amount,
                'currency': payment_info.currency
            }
            # Сохраняем данные немедленно (опционально, PicklePersistence делает это периодически)
            # await context.application.persistence.flush()

            logger.info(f"Subscription '{PRO_SUBSCRIPTION_LEVEL_KEY}' activated for user {user_id} until {valid_until_iso}")
            
            await update.message.reply_text(
                f"🎉 Оплата прошла успешно! Ваша Подписка Профи на 2 дня активирована до {valid_until_dt.strftime('%Y-%m-%d %H:%M')}.\n"
                "Теперь вам доступны расширенные лимиты!",
                reply_markup=get_main_reply_keyboard()
            )
        except Exception as e_sub_activation:
            logger.error(f"Error activating subscription for user {user_id} after payment. Payload: {invoice_payload}. Error: {e_sub_activation}")
            await update.message.reply_text(
                "Оплата прошла, но произошла ошибка при активации вашей подписки. Пожалуйста, свяжитесь с администратором.",
                reply_markup=get_main_reply_keyboard()
            )
    else:
        logger.warning(f"Received successful payment with UNKNOWN payload: {invoice_payload} from user {user_id}")
        await update.message.reply_text(
            "Оплата прошла, но тип подписки не распознан. Свяжитесь с администратором.",
            reply_markup=get_main_reply_keyboard()
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text_md = (
        f"👋 {escape_markdown('Я многофункциональный ИИ-бот на базе моделей Gemini от Google.', version=2)}\n\n"
        f"{escape_markdown('Основные команды и кнопки:', version=2)}\n"
        f"`/start` {escape_markdown('или кнопка 🚀 `Начало` (если есть) - информация о боте и текущих настройках.', version=2)}\n"
        f"`/mode` {escape_markdown('или кнопка 🤖 `Режим ИИ` - смена режима работы ИИ (стиль ответов).', version=2)}\n"
        f"`/model` {escape_markdown('или кнопка ⚙️ `Модель ИИ` - выбор конкретной модели Gemini для генерации ответов.', version=2)}\n"
        f"`/usage` {escape_markdown('или кнопка 📊 `Лимиты` - просмотр ваших текущих дневных лимитов на запросы.', version=2)}\n"
        f"`/subscribe` {escape_markdown('или кнопка 💎 `Подписка Профи` - информация о платной подписке для расширения лимитов.', version=2)}\n"
        f"`/claim_news_bonus` {escape_markdown(f'🎁 Получить бонус за подписку на наш новостной канал ({NEWS_CHANNEL_LINK})', version=2)}\n" # ДОБАВЛЕНА ЭТА СТРОКА
        f"`/help` {escape_markdown('или кнопка ❓ `Помощь` - это сообщение.', version=2)}\n\n"
        f"💡 {escape_markdown('Просто отправьте свой вопрос или задание боту, и я постараюсь помочь!', version=2)}"
    )
    try:
        await update.message.reply_text(help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        await update.message.reply_text(
        "Я ИИ-бот Gemini. Доступные команды: /start, /mode, /model, /usage, /subscribe, /claim_news_bonus, /help.\n" # ДОБАВЛЕНО /claim_news_bonus
        f"Новостной канал для бонуса: {NEWS_CHANNEL_LINK}\n" # ДОБАВЛЕНА ЭТА СТРОКА
        "Просто напишите ваш вопрос.",
        reply_markup=get_main_reply_keyboard()
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    data = query.data
    user_id = query.from_user.id
    message_to_edit = query.message 
    new_text = ""
    plain_text_fallback = ""

    if data.startswith("set_mode_"):
        mode_key = data.split("set_mode_")[1]
        if mode_key in AI_MODES and mode_key != "gemini_pro_custom_mode": 
            context.user_data['current_ai_mode'] = mode_key
            mode_details = AI_MODES[mode_key]
            new_text = f"🤖 Режим изменен на: *{escape_markdown(mode_details['name'],version=2)}*\n\n{escape_markdown(mode_details['welcome'],version=2)}"
            plain_text_fallback = f"Режим изменен на: {mode_details['name']}.\n{mode_details['welcome']}"
            logger.info(f"User {user_id} changed AI mode to {mode_key}")
        elif mode_key == "gemini_pro_custom_mode":
             new_text = escape_markdown("Этот режим предназначен для модели Gemini 2.5 Pro и выбирается автоматически.", version=2)
             plain_text_fallback = "Этот режим выбирается автоматически с моделью Gemini 2.5 Pro."
        else:
            new_text = escape_markdown("⚠️ Ошибка: Такой режим не найден.", version=2)
            plain_text_fallback = "Ошибка: Такой режим не найден."
    
    elif data.startswith("set_model_"):
        model_key_from_callback = data.split("set_model_")[1]
        if model_key_from_callback in AVAILABLE_TEXT_MODELS:
            selected_model_config = AVAILABLE_TEXT_MODELS[model_key_from_callback]
            context.user_data['selected_model_id'] = selected_model_config["id"]
            context.user_data['selected_api_type'] = selected_model_config["api_type"]

            model_name_md = escape_markdown(selected_model_config['name'], version=2)
            
            _, _, current_c = check_and_log_request_attempt(user_id, model_key_from_callback, context)
            actual_l = get_user_actual_limit_for_model(user_id, model_key_from_callback, context)
            
            limit_str = f'Ваш лимит для этой модели: {current_c}/{actual_l} в день'
            limit_info_md = f"\n{escape_markdown(limit_str, version=2)}"
            
            new_text = f"⚙️ Модель изменена на: *{model_name_md}*\\.{limit_info_md}"
            plain_text_fallback = f"Модель изменена на: {selected_model_config['name']}. {limit_str}."
            logger.info(f"User {user_id} changed AI model to key: {model_key_from_callback} (ID: {selected_model_config['id']}, API: {selected_model_config['api_type']})")
        else:
            new_text = escape_markdown("⚠️ Ошибка: Такая модель не найдена.", version=2)
            plain_text_fallback = "Ошибка: Такая модель не найдена."
            
    if new_text:
        try:
            await message_to_edit.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None) 
        except telegram.error.BadRequest as e_md:
            logger.warning(f"Failed to edit message with MarkdownV2 in button_callback: {e_md}. Sending plain text. Text was: {new_text}")
            try:
                await message_to_edit.edit_text(text=plain_text_fallback, reply_markup=None)
            except Exception as e_plain_edit:
                 logger.error(f"Failed to edit message with plain text either: {e_plain_edit}")
        except Exception as e_general_edit:
            logger.error(f"General error editing message in button_callback: {e_general_edit}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.debug(f"handle_message: Received message from user {user_id}: '{user_message}'")

    if not user_message or not user_message.strip():
        await update.message.reply_text("Пожалуйста, отправьте непустой запрос.", reply_markup=get_main_reply_keyboard())
        return

    current_model_key = get_current_model_key(context)
    selected_model_details = AVAILABLE_TEXT_MODELS[current_model_key]
    
    system_prompt_text = get_current_mode_details(context)["prompt"]
    logger.debug(f"Using system prompt for mode associated with {current_model_key}: '{get_current_mode_details(context)['name']}'")

    can_request, limit_message, _ = check_and_log_request_attempt(user_id, current_model_key, context)
    if not can_request:
        await update.message.reply_text(limit_message, reply_markup=get_main_reply_keyboard()) 
        logger.info(f"User {user_id} limit REJECTED for model_key {current_model_key}: {limit_message}")
        return
    logger.info(f"User {user_id} limit ACCEPTED for model_key {current_model_key}.")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    reply_text = "Произошла ошибка при обработке вашего запроса." 
    api_type = selected_model_details.get("api_type")
    request_successful = False

    if api_type == "google_genai":
        if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
            reply_text = "Ключ API для моделей Google Gemini не настроен. Обратитесь к администратору."
            logger.error("Google Gemini API key is not configured.")
        else:
            try:
                model_id_for_api = selected_model_details["id"]
                active_model = genai.GenerativeModel(model_id_for_api)
                logger.info(f"Using Google genai model: {model_id_for_api} for user {user_id}")
                
                generation_config_params = {"temperature": 0.75}
                if MAX_OUTPUT_TOKENS_GEMINI_LIB > 0 and "1.5" not in model_id_for_api and "2.0" not in model_id_for_api: 
                    generation_config_params["max_output_tokens"] = MAX_OUTPUT_TOKENS_GEMINI_LIB
                generation_config = genai.types.GenerationConfig(**generation_config_params)
                
                chat_history = [
                    {"role": "user", "parts": [system_prompt_text]}, 
                    {"role": "model", "parts": ["Понял. Я готов помочь."]} 
                ]

                chat = active_model.start_chat(history=chat_history) 
                logger.debug(f"Sending to Google API. Model: {model_id_for_api}. System prompt (len {len(system_prompt_text)}): '{system_prompt_text[:100]}...', User message: '{user_message[:100]}'")
                
                response_gen = await chat.send_message_async(user_message, generation_config=generation_config)
                
                api_reply_text_google = response_gen.text

                prompt_tokens, completion_tokens = 0, 0
                if hasattr(response_gen, 'usage_metadata') and response_gen.usage_metadata:
                    usage = response_gen.usage_metadata
                    prompt_tokens = usage.prompt_token_count
                    completion_tokens = usage.candidates_token_count
                    logger.info(f"Google API Usage for {model_id_for_api}: Prompt Tokens: {prompt_tokens}, Completion Tokens: {completion_tokens}")
                    context.user_data.setdefault('api_token_usage', [])
                    context.user_data['api_token_usage'].append({
                        'timestamp': datetime.now().isoformat(),
                        'model': model_id_for_api,
                        'prompt_tokens': prompt_tokens,
                        'completion_tokens': completion_tokens,
                        'total_tokens': getattr(usage, 'total_token_count', prompt_tokens + completion_tokens)
                    })

                if not api_reply_text_google or not api_reply_text_google.strip():
                    block_reason_msg = ""
                    if hasattr(response_gen, 'prompt_feedback') and response_gen.prompt_feedback and response_gen.prompt_feedback.block_reason:
                        block_reason_msg = f" Причина: {response_gen.prompt_feedback.block_reason}."
                    if response_gen.candidates and not response_gen.text: 
                         candidate = response_gen.candidates[0]
                         if candidate.finish_reason != 1: 
                              block_reason_msg += f" Finish reason: {candidate.finish_reason.name}."
                         if candidate.safety_ratings:
                             block_reason_msg += f" Safety ratings: {[(sr.category.name, sr.probability.name) for sr in candidate.safety_ratings]}."

                    reply_text = f"ИИ (Google) не смог сформировать ответ или он был отфильтрован.{block_reason_msg} Попробуйте другой запрос."
                    logger.warning(f"Empty or blocked response from Google API. Model: {model_id_for_api}.{block_reason_msg}")
                else:
                    reply_text = api_reply_text_google
                    request_successful = True

            except google.api_core.exceptions.GoogleAPIError as e_google_api:
                error_message = str(e_google_api).lower()
                logger.error(f"GoogleAPIError for model {selected_model_details['id']}: {str(e_google_api)}\n{traceback.format_exc()}")
                reply_text = f"Ошибка API Google Gemini: {type(e_google_api).__name__}."
                if "api key not valid" in error_message or "api key invalid" in error_message:
                    reply_text = "⚠️ Ошибка: API ключ для Google недействителен. Обратитесь к администратору."
                elif "billing account" in error_message or "enable billing" in error_message:
                    reply_text = "⚠️ Проблема с биллингом для API Google. Обратитесь к администратору."
                elif "resource has been exhausted" in error_message or "quota" in error_message: 
                    reply_text = "⚠️ Исчерпана квота для Google API. Попробуйте позже или обратитесь к администратору."
                elif "user location" in error_message:
                     reply_text = "⚠️ Модель недоступна в вашем регионе через Google API."
                elif "content filter" in error_message or "safety" in error_message:
                    reply_text = "⚠️ Запрос был заблокирован фильтрами безопасности Google. Попробуйте переформулировать."
                elif "model not found" in error_message or "could not find model" in error_message:
                    reply_text = f"⚠️ Модель '{selected_model_details['id']}' не найдена или неверно указан ID в Google API. Проверьте актуальность ID модели."


            except Exception as e_general_google:
                logger.error(f"General error processing Google Gemini model {selected_model_details['id']}: {str(e_general_google)}\n{traceback.format_exc()}")
                reply_text = "⚠️ Внутренняя ошибка при обработке запроса к Google Gemini."

    elif api_type == "custom_http_api":
        api_key_var_name = selected_model_details.get("api_key_var_name")
        actual_api_key = globals().get(api_key_var_name) 

        if not actual_api_key or ("sk-" not in actual_api_key and "pk-" not in actual_api_key) : 
            reply_text = f"⚠️ Ключ API для '{selected_model_details['name']}' не настроен корректно."
            logger.warning(f"API key from var '{api_key_var_name}' is missing or invalid for Custom API. Key: {str(actual_api_key)[:10]}...")
        else:
            endpoint = selected_model_details["endpoint"]
            model_id_for_payload_api = selected_model_details["id"] 
            
            messages_payload = [
                {"role": "user", "content": system_prompt_text}, 
                {"role": "user", "content": user_message}
            ]

            payload = {
                "model": model_id_for_payload_api,
                "messages": messages_payload,
                "is_sync": True, 
                "temperature": selected_model_details.get("temperature", 0.75),
                "stream": False, 
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {actual_api_key}'
            }
            logger.info(f"Sending request to Custom HTTP API. Endpoint: {endpoint}, Model in payload: {model_id_for_payload_api}")
            logger.debug(f"Custom API Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")

            try:
                api_response = requests.post(endpoint, json=payload, headers=headers, timeout=90) 
                logger.debug(f"Custom API response status: {api_response.status_code}")
                response_data = {}
                try:
                    response_data = api_response.json()
                    logger.debug(f"Custom API response body (JSON): {json.dumps(response_data, ensure_ascii=False, indent=2)}")
                except json.JSONDecodeError as e_json:
                    logger.error(f"Custom API response body (not JSON or decode error for status {api_response.status_code}): {api_response.text}. Error: {e_json}")
                    if api_response.status_code >= 400: 
                         reply_text = f"⚠️ Ошибка от Custom API ({selected_model_details['name']}): {api_response.status_code} - {api_response.text[:200]}"
                    else: 
                         reply_text = f"⚠️ Ошибка декодирования ответа от Custom API ({selected_model_details['name']})."
                
                api_response.raise_for_status() 

                if "response" in response_data and isinstance(response_data["response"], list) and len(response_data["response"]) > 0:
                    first_choice = response_data["response"][0]
                    if "message" in first_choice and "content" in first_choice["message"]:
                        api_reply_text_custom = first_choice["message"]["content"]
                        if api_reply_text_custom and api_reply_text_custom.strip():
                            reply_text = api_reply_text_custom
                            request_successful = True
                            if "cost" in response_data:
                                cost = response_data["cost"]
                                logger.info(f"Custom API request cost for {selected_model_details['name']}: {cost}")
                                context.user_data.setdefault('api_costs', [])
                                context.user_data['api_costs'].append({
                                    'timestamp': datetime.now().isoformat(),
                                    'model_key': current_model_key,
                                    'cost': cost 
                                })
                            req_id_resp = response_data.get("request_id")
                            model_resp = response_data.get("model") 
                            logger.info(f"Custom API success: request_id={req_id_resp}, model_in_response='{model_resp}'")
                        else:
                            reply_text = f"⚠️ ИИ ({selected_model_details['name']}) вернул пустой ответ в 'content'."
                            logger.warning(f"Custom API returned empty 'content' in message: {response_data}")
                    else: 
                        reply_text = f"⚠️ Некорректная структура 'message' или отсутствует 'content' в ответе от Custom API ({selected_model_details['name']})."
                        logger.warning(f"Custom API: 'message' or 'content' field missing in first choice: {first_choice}. Full response: {response_data}")
                elif "detail" in response_data: 
                    error_detail = response_data['detail']
                    if isinstance(error_detail, list) and error_detail and "msg" in error_detail[0]:
                        reply_text = f"⚠️ Ошибка Custom API ({selected_model_details['name']}): {error_detail[0]['msg']}"
                    else:
                        reply_text = f"⚠️ Ошибка Custom API ({selected_model_details['name']}): {str(error_detail)[:200]}"
                    logger.error(f"Custom API returned error detail: {error_detail}. Full response: {response_data}")
                elif not response_data and api_response.status_code == 200: 
                     reply_text = f"⚠️ Custom API ({selected_model_details['name']}) вернул успешный статус, но пустой ответ."
                     logger.warning(f"Custom API returned 200 OK with empty JSON response.")
                else: 
                    reply_text = f"⚠️ Неожиданная структура ответа от Custom API ({selected_model_details['name']}). Статус: {api_response.status_code}."
                    logger.warning(f"Unexpected response structure from Custom API ({api_response.status_code}). Full response: {json.dumps(response_data, ensure_ascii=False)}")
            
            except requests.exceptions.HTTPError as e_http:
                error_content_str = "No details in response text."
                try: 
                    error_content_json = e_http.response.json()
                    if "detail" in error_content_json:
                         error_detail_http = error_content_json['detail']
                         if isinstance(error_detail_http, list) and error_detail_http and "msg" in error_detail_http[0]:
                             error_content_str = error_detail_http[0]['msg']
                         else:
                             error_content_str = str(error_detail_http)
                    else:
                         error_content_str = json.dumps(error_content_json)
                except json.JSONDecodeError: 
                    error_content_str = e_http.response.text[:200] 
                
                logger.error(f"HTTPError for Custom API '{selected_model_details['name']}': {e_http}. Status: {e_http.response.status_code}. Content: {error_content_str}")
                if e_http.response.status_code == 401: 
                    reply_text = f"⚠️ Ошибка 401: Неверный API ключ для Custom API ({selected_model_details['name']}). Проверьте ключ."
                elif e_http.response.status_code == 402:
                    reply_text = f"⚠️ Ошибка 402: Проблема с оплатой для Custom API ({selected_model_details['name']}). Возможно, закончился баланс на стороне API провайдера."
                elif e_http.response.status_code == 422: 
                     reply_text = f"⚠️ Ошибка 422: Неверный формат запроса к Custom API. Детали: {error_content_str}"
                elif e_http.response.status_code == 429: 
                     reply_text = f"⚠️ Ошибка 429: Превышен лимит запросов к Custom API. Попробуйте позже."
                else:
                    reply_text = f"⚠️ Ошибка сети ({e_http.response.status_code}) при обращении к '{selected_model_details['name']}'. Детали: {error_content_str}"

            except requests.exceptions.RequestException as e_req_custom: 
                logger.error(f"RequestException for Custom API '{selected_model_details['name']}': {e_req_custom}")
                reply_text = f"⚠️ Ошибка сети при обращении к '{selected_model_details['name']}'. Попробуйте позже."
            except Exception as e_custom_proc: 
                logger.error(f"Error processing Custom API response for '{selected_model_details['name']}': {e_custom_proc}\n{traceback.format_exc()}")
                reply_text = f"⚠️ Ошибка обработки ответа от '{selected_model_details['name']}'."
    else:
        reply_text = f"⚠️ Неизвестный тип API: {api_type}"
        logger.error(f"Unsupported API type: {api_type} for model_key {current_model_key}")

    if request_successful and selected_model_details.get("is_limited"):
        increment_request_count(user_id, current_model_key, context)
            
    reply_text_for_sending, was_truncated = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    await update.message.reply_text(reply_text_for_sending, reply_markup=get_main_reply_keyboard())
    if request_successful:
        logger.info(f"Sent successful response for model_key {current_model_key}. User: {user_id}. Truncated: {was_truncated}")


async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "🚀 Начало / Инфо"),
        BotCommand("mode", "🧠 Сменить режим ИИ"),
        BotCommand("model", "⚙️ Выбрать модель ИИ"),
        BotCommand("usage", "📊 Мои лимиты"),
        BotCommand("subscribe", "💎 Подписка Профи"),
        BotCommand("claim_news_bonus", "🎁 Бонус за новости"), # ДОБАВЛЕНА ЗАПЯТАЯ
        BotCommand("help", "ℹ️ Помощь"),
    ]

    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

async def claim_news_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        logger.warning("claim_news_bonus_command called without effective_user.")
        return

    # Проверка, настроен ли канал администратором
    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle" or \
       not NEWS_CHANNEL_LINK or NEWS_CHANNEL_LINK == "https://t.me/YourNewsChannelHandle":
        await update.message.reply_text(
            "Функция бонуса за подписку на новостной канал временно не настроена администратором. "
            "Пожалуйста, попробуйте позже."
        )
        logger.warning(f"claim_news_bonus_command: NEWS_CHANNEL_USERNAME ('{NEWS_CHANNEL_USERNAME}') or NEWS_CHANNEL_LINK ('{NEWS_CHANNEL_LINK}') is not configured.")
        return

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text("Ошибка: Модель для начисления бонуса не найдена. Обратитесь к администратору.")
        logger.error(f"NEWS_CHANNEL_BONUS_MODEL_KEY '{NEWS_CHANNEL_BONUS_MODEL_KEY}' not found in AVAILABLE_TEXT_MODELS.")
        return
    bonus_model_name = bonus_model_config['name']


    if context.user_data.get('claimed_news_bonus', False):
        remaining_bonus = context.user_data.get('news_bonus_uses_left', 0)
        if remaining_bonus > 0:
            reply_msg = (
                f"Вы уже активировали бонус за подписку на новостной канал. "
                f"У вас осталось {remaining_bonus} бесплатных генераций для модели '{bonus_model_name}'.\n"
                f"Наш канал: {NEWS_CHANNEL_LINK}"
            )
        else:
            reply_msg = (
                f"Вы уже получали и использовали бонус за подписку на новостной канал для модели '{bonus_model_name}'.\n"
                f"Наш канал: {NEWS_CHANNEL_LINK}"
            )
        await update.message.reply_text(reply_msg)
        return

    try:
        member_status = await context.bot.get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        logger.debug(f"User {user.id} status in {NEWS_CHANNEL_USERNAME}: {member_status.status}")

        # Статусы, подтверждающие членство
        allowed_statuses = ['member', 'administrator', 'creator']
        # Статус 'restricted' также может означать, что пользователь в канале, но с ограничениями (не забанен).
        # Иногда 'left' или 'kicked' могут прийти, если пользователь только что вышел/был удален.
        # Важно: если канал приватный, бот должен быть администратором канала для этой проверки.

        if member_status.status in allowed_statuses:
            context.user_data['claimed_news_bonus'] = True
            context.user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await update.message.reply_text(
                f"🎉 Спасибо за подписку на наш новостной канал!\n"
                f"Вам начислена {NEWS_CHANNEL_BONUS_GENERATIONS} бесплатная генерация для модели '{bonus_model_name}'.\n"
                f"Этот бонус не имеет срока действия, но он одноразовый.\n"
                f"Наш канал: {NEWS_CHANNEL_LINK}"
            )
            logger.info(f"User {user.id} claimed news channel bonus. Granted {NEWS_CHANNEL_BONUS_GENERATIONS} uses for {NEWS_CHANNEL_BONUS_MODEL_KEY}.")
        else:
            await update.message.reply_text(
                f"Мы не смогли подтвердить вашу подписку на канал {NEWS_CHANNEL_LINK}. \n"
                f"Пожалуйста, убедитесь, что вы подписаны, и ваш профиль не скрыт (если канал публичный), "
                f"затем попробуйте снова: /claim_news_bonus\n"
                f"Если вы только что подписались, подождите минуту и повторите команду."
            )
    except telegram.error.BadRequest as e:
        error_text = str(e).lower()
        if "user not found" in error_text or "member not found" in error_text or "participant not found" in error_text :
            await update.message.reply_text(
                f"Мы не смогли подтвердить вашу подписку на канал {NEWS_CHANNEL_LINK}. \n"
                f"Возможно, вы не подписаны. Пожалуйста, подпишитесь и попробуйте снова: /claim_news_bonus"
            )
        elif "chat not found" in error_text or "channel not found" in error_text:
            await update.message.reply_text(
                "Новостной канал для проверки подписки не найден. "
                "Администратор бота, вероятно, указал неверный юзернейм канала."
            )
            logger.error(f"NEWS_CHANNEL_USERNAME ('{NEWS_CHANNEL_USERNAME}') seems to be invalid/incorrect for get_chat_member.")
        elif "bot is not a member" in error_text:
             await update.message.reply_text(
                f"Не удалось проверить подписку. Если канал приватный, бот должен быть его участником (или администратором)."
            )
             logger.error(f"Bot is not a member of the private channel {NEWS_CHANNEL_USERNAME} and cannot check membership.")
        else:
            logger.error(f"BadRequest error checking channel membership for user {user.id} in {NEWS_CHANNEL_USERNAME}: {e}")
            await update.message.reply_text("Произошла ошибка при проверке подписки. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Unexpected error in claim_news_bonus_command for user {user.id}: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("Произошла непредвиденная ошибка при попытке получить бонус. Попробуйте позже.")

async def main():
    if "YOUR_TELEGRAM_TOKEN" in TOKEN or not TOKEN or len(TOKEN.split(":")[0]) < 8:
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set correctly or is a placeholder.")
        return
    # Убрал проверку на плейсхолдеры для API ключей здесь, т.к. она есть при их использовании
    # if "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY and "YOUR_CUSTOM_GEMINI_PRO_API_KEY" in CUSTOM_GEMINI_PRO_API_KEY:
    #      logger.warning("WARNING: API keys seem to be placeholders. Please set them correctly.")
    
    persistence = PicklePersistence(filepath="bot_data.pkl") 

    application = Application.builder().token(TOKEN).persistence(persistence).build()

    await set_bot_commands(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mode", select_mode_command))
    application.add_handler(CommandHandler("model", select_model_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command))
    application.add_handler(CommandHandler("claim_news_bonus", claim_news_bonus_command)) # ПЕРЕМЕЩЕНО СЮДА

    application.add_handler(MessageHandler(filters.Text(["🤖 Режим ИИ"]), select_mode_command))
    application.add_handler(MessageHandler(filters.Text(["⚙️ Модель ИИ"]), select_model_command))
    application.add_handler(MessageHandler(filters.Text(["📊 Лимиты"]), usage_command)) 
    application.add_handler(MessageHandler(filters.Text(["💎 Подписка Профи"]), subscribe_info_command)) 
    application.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))


    logger.info("Starting bot application...")
    try:
        await application.run_polling()
    except Exception as e_poll:
        logger.critical(f"Error during application startup or polling: {e_poll}\n{traceback.format_exc()}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e_main_run:
        logger.critical(f"Critical error in asyncio.run(main()): {e_main_run}\n{traceback.format_exc()}")
