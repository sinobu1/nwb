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


nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO) # DEBUG -> INFO
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # ЗАМЕНИ НА СВОЙ КЛЮЧ
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P") # ЗАМЕНИ НА СВОЙ КЛЮЧ
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "YOUR_REAL_PAYMENT_PROVIDER_TOKEN_HERE")
YOUR_ADMIN_ID = 489230152

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000

# --- ОБНОВЛЕННЫЕ ЛИМИТЫ ---
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0 # Бонус за подписку на канал
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"

# --- КАНАЛ НОВОСТЕЙ И БОНУС ---
NEWS_CHANNEL_USERNAME = "@timextech"  # ЗАМЕНИТЕ, ЕСЛИ НУЖНО
NEWS_CHANNEL_LINK = "https://t.me/timextech" # ЗАМЕНИТЕ, ЕСЛИ НУЖНО
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
    "google_gemini_2_0_flash": {
        "name": "⚡️ Gemini 2.0 Flash", # Убрал упоминание лимита из имени
        "id": "gemini-2.0-flash", # Обновлено на более общий ID
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free",
        "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY,
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "💨 Gemini 2.5 Flash Preview",
        "id": "gemini-2.5-flash-preview-04-17", # Пример актуального ID, проверьте на момент использования
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY,
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "🌟 Gemini 2.5 Pro (Продвинутый)",
        "id": "gemini-2.5-pro-preview-03-25", # ID для Custom API (gen-api.ru)
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
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    mode_key = context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

def get_current_model_key(context: ContextTypes.DEFAULT_TYPE) -> str:
    selected_id = context.user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = context.user_data.get('selected_api_type')
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id and info.get("api_type") == selected_api_type:
            return key
    logger.warning(f"Could not find key for model_id '{selected_id}' and api_type '{selected_api_type}'. Falling back to default.")
    default_model_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    context.user_data['selected_model_id'] = default_model_config["id"]
    context.user_data['selected_api_type'] = default_model_config["api_type"]
    return DEFAULT_MODEL_KEY

def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    model_key = get_current_model_key(context)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str): return str(text), False
    if len(text) <= max_length: return text, False
    suffix = "\n\n(...ответ был сокращен)"
    adj_max = max_length - len(suffix)
    if adj_max <= 0: return text[:max_length-len("...")] + "...", True
    trunc = text[:adj_max]
    cuts = [pos + (len(s)-1 if s.endswith(' ') and len(s)>1 else len(s)) for s in ['\n\n','. ','! ','? ','\n'] if (pos := trunc.rfind(s)) != -1 and pos > 0]
    if cuts and (cut_at := max(cuts)) > adj_max * 0.5: return text[:cut_at].strip() + suffix, True
    if (last_space := trunc.rfind(' ')) != -1 and last_space > adj_max * 0.5: return text[:last_space].strip() + suffix, True
    return text[:adj_max].strip() + suffix, True

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
    all_user_subs = context.bot_data.setdefault('user_subscriptions', {})
    user_sub_details = all_user_subs.get(user_id, {})
    current_sub_level = None
    if user_sub_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_sub_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                current_sub_level = user_sub_details.get('level')
        except Exception: pass # Ignore errors in date processing for now

    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free": return model_config.get("limit", 0)
    if limit_type == "subscription_or_daily_free":
        return model_config.get("subscription_daily_limit", 0) if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY else model_config.get("limit_if_no_subscription", 0)
    if limit_type == "subscription_custom_pro":
        return model_config.get("subscription_daily_limit", 0) if current_sub_level == PRO_SUBSCRIPTION_LEVEL_KEY else model_config.get("limit_if_no_subscription", 0)
    return model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"): return True, "", 0

    is_profi_subscriber = False
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY or model_config.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro"]:
        user_sub_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if user_sub_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_sub_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_sub_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_sub_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception: pass

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber and context.user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} using news channel bonus for {model_key}.")
        return True, "bonus_available", 0

    user_model_counts = context.bot_data.setdefault('all_user_daily_counts', {}).setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': '', 'count': 0})
    if model_daily_usage['date'] != today_str:
        model_daily_usage.update({'date': today_str, 'count': 0})

    current_daily_count = model_daily_usage['count']
    actual_daily_limit = get_user_actual_limit_for_model(user_id, model_key, context)

    if current_daily_count >= actual_daily_limit:
        msg_parts = [f"Вы достигли дневного лимита ({current_daily_count}/{actual_daily_limit}) для модели '{model_config['name']}'."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not context.user_data.get('claimed_news_bonus', False):
                msg_parts.append(f"💡 Подпишитесь на [наш новостной канал]({NEWS_CHANNEL_LINK}) и используйте `/claim_news_bonus` для получения {NEWS_CHANNEL_BONUS_GENERATIONS} бонусной генерации!")
            elif context.user_data.get('news_bonus_uses_left', 0) == 0:
                msg_parts.append("ℹ️ Ваш бонус за подписку на новости для этой модели уже использован.")
        msg_parts.append("Попробуйте завтра или рассмотрите подписку `/subscribe` для увеличения лимитов.")
        return False, "\n".join(msg_parts), current_daily_count
    return True, "", current_daily_count

def increment_request_count(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE):
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"): return

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
        is_profi_subscriber = False
        user_sub_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if user_sub_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_sub_details.get('valid_until'):
            try:
                if datetime.now(datetime.fromisoformat(user_sub_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_sub_details['valid_until']).date():
                    is_profi_subscriber = True
            except Exception: pass
        if not is_profi_subscriber and (bonus_left := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            context.user_data['news_bonus_uses_left'] = bonus_left - 1
            logger.info(f"User {user_id} consumed news bonus for {model_key}. Left: {bonus_left - 1}")
            return # Bonus used, no daily count increment

    today_str = datetime.now().strftime("%Y-%m-%d")
    user_model_counts = context.bot_data.setdefault('all_user_daily_counts', {}).setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': today_str, 'count': 0})
    if model_daily_usage['date'] != today_str: model_daily_usage.update({'date': today_str, 'count': 0})
    model_daily_usage['count'] += 1
    logger.info(f"User {user_id} daily count for {model_key} to {model_daily_usage['count']}")

# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    if 'selected_model_id' not in context.user_data or 'selected_api_type' not in context.user_data:
        default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data['selected_model_id'] = default_model_conf["id"]
        context.user_data['selected_api_type'] = default_model_conf["api_type"]

    current_model_key = get_current_model_key(context)
    current_mode_name = get_current_mode_details(context)['name']
    current_model_name = AVAILABLE_TEXT_MODELS[current_model_key]['name']

    greeting = "👋 Привет! Я твой многофункциональный ИИ-бот на базе Gemini."
    mode_line = f"🧠 Текущий режим: *{escape_markdown(current_mode_name, version=2)}*"
    model_line = f"⚙️ Текущая модель: *{escape_markdown(current_model_name, version=2)}*"

    _, limit_msg_check, current_count = check_and_log_request_attempt(user_id, current_model_key, context)
    actual_limit = get_user_actual_limit_for_model(user_id, current_model_key, context)
    limit_info_text = f'Лимит для этой модели: {current_count}/{actual_limit} в день.'
    if "Вы достигли" in limit_msg_check: limit_info_text = limit_msg_check.splitlines()[0]
    limit_info_line = f"📊 {escape_markdown(limit_info_text, version=2)}"

    text_elements = [escape_markdown(greeting, version=2), mode_line, model_line, limit_info_line]

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_info = ""
        if not context.user_data.get('claimed_news_bonus', False):
            bonus_info = (f"\n🎁 Получите бонус за подписку на [наш новостной канал]({NEWS_CHANNEL_LINK})\! "
                          f"Используйте команду `/claim_news_bonus` после подписки\.")
        elif context.user_data.get('news_bonus_uses_left', 0) > 0:
            bonus_info = f"\n✅ У вас есть *{context.user_data.get('news_bonus_uses_left', 0)}* бонусных генераций за подписку на новости\."
        else:
            bonus_info = f"\nℹ️ Бонус за подписку на [новостной канал]({NEWS_CHANNEL_LINK}) уже использован\."
        text_elements.append(bonus_info) # Already MarkdownV2 formatted

    text_elements.extend([
        f"\n{escape_markdown('Вы можете:', version=2)}",
        f"💬 Задавать мне вопросы или давать задания.",
        f"🤖 Сменить режим ИИ (`/mode` или кнопка)",
        f"⚙️ Выбрать другую модель ИИ (`/model` или кнопка)",
        f"📊 Узнать свои лимиты (`/usage` или кнопка)",
        f"💎 Ознакомиться с Подпиской Профи (`/subscribe` или кнопка)",
        f"❓ Получить помощь (`/help`)",
        f"\n{escape_markdown('Просто напишите ваш запрос!', version=2)}"
    ])
    final_text_md = "\n".join(text_elements)

    try:
        await update.message.reply_text(
            final_text_md, parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True
        )
    except telegram.error.BadRequest as e_md_start:
        logger.error(f"Error sending /start with MarkdownV2: {e_md_start}. Text: {final_text_md}")
        plain_elements = [
            greeting, f"Режим: {current_mode_name}", f"Модель: {current_model_name}", limit_info_text
        ]
        if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
            bonus_plain = ""
            if not context.user_data.get('claimed_news_bonus', False):
                bonus_plain = (f"\n🎁 Бонус: подписка на {NEWS_CHANNEL_LINK} -> /claim_news_bonus")
            elif context.user_data.get('news_bonus_uses_left', 0) > 0:
                bonus_plain = f"\n✅ Бонусных генераций: {context.user_data.get('news_bonus_uses_left', 0)}."
            else: bonus_plain = f"\nℹ️ Бонус за {NEWS_CHANNEL_LINK} использован."
            plain_elements.append(bonus_plain)
        plain_elements.extend([
            "\nВы можете:", "▫️ Задавать вопросы.", "▫️ /mode", "▫️ /model", "▫️ /usage",
            "▫️ /subscribe", "▫️ /claim_news_bonus", "▫️ /help", "\nВаш запрос?"
        ])
        await update.message.reply_text(
            "\n".join(plain_elements), reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True
        )
    logger.info(f"Start command processed for user {user_id}.")

async def select_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")]
                for key, details in AI_MODES.items() if key != "gemini_pro_custom_mode"]
    if not keyboard:
        await update.message.reply_text('Нет доступных режимов.', reply_markup=get_main_reply_keyboard())
        return
    await update.message.reply_text(
        'Выберите режим ИИ (для Gemini 2.5 Pro режим выбирается автоматически):',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def select_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(f"{details['name']} ({get_user_actual_limit_for_model(update.effective_user.id, key, context)}/день)", callback_data=f"set_model_{key}")]
                for key, details in AVAILABLE_TEXT_MODELS.items()] # Показываем лимит прямо на кнопке
    await update.message.reply_text('Выберите модель ИИ:', reply_markup=InlineKeyboardMarkup(keyboard))

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sub_details = context.bot_data.setdefault('user_subscriptions', {}).get(user_id, {})
    display_sub_level = "Бесплатный доступ"
    subscription_active = False
    if user_sub_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_sub_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_sub_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                display_sub_level = f"💎 Подписка Профи (до {valid_until_dt.strftime('%Y-%m-%d')})"
                subscription_active = True
            else: display_sub_level = "💎 Подписка Профи (истекла)"
        except Exception: display_sub_level = "💎 Подписка Профи (ошибка даты)"

    usage_text_parts = [f"📊 *Информация о ваших лимитах*", f"Текущий статус: *{escape_markdown(display_sub_level,version=2)}*", "\nЕжедневные лимиты запросов по моделям:"]
    for mk, mc in AVAILABLE_TEXT_MODELS.items():
        if mc.get("is_limited"):
            _, _, current_c = check_and_log_request_attempt(user_id, mk, context) # Берем текущее использование
            actual_l = get_user_actual_limit_for_model(user_id, mk, context)
            usage_text_parts.append(f"▫️ {escape_markdown(mc['name'],version=2)}: *{current_c}/{actual_l}*")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY,{}).get('name', "бонусной модели")
        bonus_info_usage = ""
        if not context.user_data.get('claimed_news_bonus', False):
            bonus_info_usage = (f"\n🎁 Подпишитесь на [канал]({NEWS_CHANNEL_LINK}) и `/claim_news_bonus` "
                                f"для *{NEWS_CHANNEL_BONUS_GENERATIONS}* генерации ({escape_markdown(bonus_model_name,version=2)})!")
        elif (bonus_left := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info_usage = f"\n🎁 У вас *{bonus_left}* бонусных генераций для {escape_markdown(bonus_model_name,version=2)} ([канал]({NEWS_CHANNEL_LINK}))\."
        else:
            bonus_info_usage = f"\nℹ️ Бонус за подписку на [канал]({NEWS_CHANNEL_LINK}) ({escape_markdown(bonus_model_name,version=2)}) уже использован\."
        usage_text_parts.append(bonus_info_usage)

    if not subscription_active:
        usage_text_parts.append(f"\nХотите больше лимитов? Ознакомьтесь с Подпиской Профи: `/subscribe`")

    final_usage_text_md = "\n".join(usage_text_parts)
    try:
        await update.message.reply_text(final_usage_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
    except telegram.error.BadRequest:
        plain_usage_parts = [f"Статус: {display_sub_level}", "Лимиты:"]
        for mk, mc in AVAILABLE_TEXT_MODELS.items():
            if mc.get("is_limited"):
                _, _, current_c = check_and_log_request_attempt(user_id, mk, context)
                actual_l = get_user_actual_limit_for_model(user_id, mk, context)
                plain_usage_parts.append(f"- {mc['name']}: {current_c}/{actual_l}")
        # Add plain bonus info here if needed
        if not subscription_active: plain_usage_parts.append("\nПодписка Профи: /subscribe")
        await update.message.reply_text("\n".join(plain_usage_parts), reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_parts = ["🌟 *Подписка Профи – Максимум возможностей Gemini\!* 🌟",
                  "\nПолучите расширенные дневные лимиты для самых мощных моделей:"]
    for key, model in [("google_gemini_2_5_flash_preview", "💨"), ("custom_api_gemini_2_5_pro", "🌟")]:
        m_conf = AVAILABLE_TEXT_MODELS[key]
        text_parts.append(f"{model} {escape_markdown(m_conf['name'], version=2)}: *{m_conf['subscription_daily_limit']}* запросов/день "
                          f"(Бесплатно: {m_conf['limit_if_no_subscription']} запросов/день)")
    text_parts.append(f"\nБазовая модель всегда доступна с щедрым лимитом:\n"
                      f"⚡️ {escape_markdown(AVAILABLE_TEXT_MODELS['google_gemini_2_0_flash']['name'], version=2)}: "
                      f"*{DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY}* запросов/день (бесплатно для всех)")
    text_parts.extend(["\n✨ *Доступный тариф Профи для теста:*", f"▫️ Тест-драйв (2 дня): `{escape_markdown('99 рублей', version=2)}`"])
    
    keyboard = [[InlineKeyboardButton("💳 Купить Профи (2 дня - 99 RUB)", callback_data="buy_profi_2days")]]
    reply_markup_subscribe = InlineKeyboardMarkup(keyboard)
    final_text_subscribe = "\n".join(text_parts)

    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(final_text_subscribe, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup_subscribe, disable_web_page_preview=True)
        else:
            await update.message.reply_text(final_text_subscribe, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup_subscribe, disable_web_page_preview=True)
    except telegram.error.BadRequest:
        # Fallback plain text
        await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(
            "Подписка Профи: ... (упрощенный текст)", reply_markup=reply_markup_subscribe, disable_web_page_preview=True
        )

async def buy_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "buy_profi_2days":
        if not PAYMENT_PROVIDER_TOKEN or "YOUR_REAL_PAYMENT_PROVIDER_TOKEN_HERE" in PAYMENT_PROVIDER_TOKEN:
            await query.message.reply_text("⚠️ Сервис оплаты временно недоступен.",reply_markup=get_main_reply_keyboard())
            return
        prices = [LabeledPrice(label="Подписка Профи (2 дня)", amount=99 * 100)] # Цена в копейках
        try:
            await context.bot.send_invoice(
                chat_id=user_id, title="Подписка Профи (2 дня)",
                description="Доступ к расширенным лимитам Gemini на 2 дня.",
                payload=f"profi_2days_uid{user_id}_t{int(datetime.now().timestamp())}",
                provider_token=PAYMENT_PROVIDER_TOKEN, currency="RUB", prices=prices
            )
            await query.edit_message_reply_markup(reply_markup=None) # Убираем кнопку "Купить"
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
            f"🎉 Оплата успешна! Подписка Профи активирована до {datetime.fromisoformat(valid_until).strftime('%Y-%m-%d %H:%M')}.",
            reply_markup=get_main_reply_keyboard()
        )
    else: await update.message.reply_text("Оплата прошла, но тип подписки не распознан.",reply_markup=get_main_reply_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text_parts = [
        f"👋 Я многофункциональный ИИ-бот на базе моделей Gemini от Google.",
        "\nОсновные команды и кнопки:",
        "`/start` - Начало / Инфо",
        "`/mode` - Сменить режим ИИ",
        "`/model` - Выбрать модель ИИ",
        "`/usage` - Мои лимиты",
        "`/subscribe` - Подписка Профи",
        f"`/claim_news_bonus` - 🎁 Получить бонус за подписку на [канал]({NEWS_CHANNEL_LINK})",
        "`/help` - Это сообщение",
        "\n💡 Просто отправьте свой вопрос или задание боту!"
    ]
    final_help_text_md = "\n".join(escape_markdown(part, version=2) if not part.startswith("`/") and not NEWS_CHANNEL_LINK in part else part for part in help_text_parts)
    # Корректировка для ссылки в MarkdownV2
    final_help_text_md = final_help_text_md.replace(f"[канал]({NEWS_CHANNEL_LINK})", f"[канал]({escape_markdown(NEWS_CHANNEL_LINK, version=2, entity_type=None)})")


    try:
        await update.message.reply_text(final_help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
    except telegram.error.BadRequest:
        plain_help = ["Я ИИ-бот Gemini. Команды: /start, /mode, /model, /usage, /subscribe, /claim_news_bonus, /help.",
                      f"Канал для бонуса: {NEWS_CHANNEL_LINK}", "Напишите ваш вопрос."]
        await update.message.reply_text("\n".join(plain_help), reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    message_to_edit = query.message
    new_text = ""
    plain_fallback = ""

    if data.startswith("set_mode_"):
        mode_key = data.split("set_mode_")[1]
        if mode_key in AI_MODES and mode_key != "gemini_pro_custom_mode":
            context.user_data['current_ai_mode'] = mode_key
            details = AI_MODES[mode_key]
            new_text = f"🤖 Режим изменен на: *{escape_markdown(details['name'],version=2)}*\n\n{escape_markdown(details['welcome'],version=2)}"
            plain_fallback = f"Режим: {details['name']}.\n{details['welcome']}"
        elif mode_key == "gemini_pro_custom_mode":
            new_text = escape_markdown("Этот режим для Gemini 2.5 Pro выбирается автоматически.", version=2)
            plain_fallback = "Режим для Gemini 2.5 Pro выбирается автоматически."
        else: new_text = plain_fallback = "⚠️ Ошибка: Режим не найден."

    elif data.startswith("set_model_"):
        model_key = data.split("set_model_")[1]
        if model_key in AVAILABLE_TEXT_MODELS:
            config = AVAILABLE_TEXT_MODELS[model_key]
            context.user_data['selected_model_id'] = config["id"]
            context.user_data['selected_api_type'] = config["api_type"]
            _, _, current_c = check_and_log_request_attempt(user_id, model_key, context)
            actual_l = get_user_actual_limit_for_model(user_id, model_key, context)
            limit_str = f'Ваш лимит: {current_c}/{actual_l} в день'
            new_text = f"⚙️ Модель: *{escape_markdown(config['name'],version=2)}*\n{escape_markdown(limit_str,version=2)}"
            plain_fallback = f"Модель: {config['name']}. {limit_str}."
        else: new_text = plain_fallback = "⚠️ Ошибка: Модель не найдена."
    
    # elif data == "claim_news_bonus_button": # Если решите вернуть инлайн-кнопку бонуса
    #     await claim_news_bonus_logic(update, context, called_from_button=True)
    #     return # Не редактируем сообщение с кнопкой, т.к. /start сам обновится

    if new_text: # Только если это был выбор режима или модели
        try:
            await message_to_edit.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None)
        except telegram.error.BadRequest:
            try: await message_to_edit.edit_text(text=plain_fallback, reply_markup=None)
            except Exception as e: logger.error(f"Fallback edit failed in button_callback: {e}")
        except Exception as e: logger.error(f"General edit error in button_callback: {e}")

async def claim_news_bonus_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, called_from_button: bool = False):
    user = update.effective_user
    reply_target = update.message if not called_from_button and update.message else (update.callback_query.message if update.callback_query else None)
    if not user or not reply_target: return

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle": # Используем константу, а не строку
        await reply_target.reply_text("Функция бонуса не настроена.", disable_web_page_preview=True)
        return

    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_cfg:
        await reply_target.reply_text("Ошибка: Бонусная модель не найдена.", disable_web_page_preview=True)
        return
    bonus_model_name = bonus_model_cfg['name']

    if context.user_data.get('claimed_news_bonus', False):
        msg = (f"Вы уже активировали бонус. Осталось {context.user_data.get('news_bonus_uses_left',0)} "
               f"генераций для '{bonus_model_name}'. Канал: {NEWS_CHANNEL_LINK}") \
            if context.user_data.get('news_bonus_uses_left',0) > 0 else \
               (f"Бонус для '{bonus_model_name}' уже использован. Канал: {NEWS_CHANNEL_LINK}")
        await reply_target.reply_text(msg, disable_web_page_preview=True)
        return

    try:
        member = await context.bot.get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member.status in ['member', 'administrator', 'creator']:
            context.user_data['claimed_news_bonus'] = True
            context.user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await reply_target.reply_text(
                f"🎉 Спасибо за подписку на [канал]({NEWS_CHANNEL_LINK})\!\n"
                f"Вам начислено *{NEWS_CHANNEL_BONUS_GENERATIONS}* бесплатных генераций для модели '{escape_markdown(bonus_model_name,version=2)}'\.",
                parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True
            )
        else:
            await reply_target.reply_text(
                f"Не удалось подтвердить подписку на [канал]({NEWS_CHANNEL_LINK})\. Убедитесь, что подписаны, и попробуйте снова.",
                parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True
            )
    except telegram.error.BadRequest as e:
        err_text = str(e).lower()
        if any(s in err_text for s in ["user not found", "member not found", "participant not found"]):
            reply_msg = f"Вы не подписаны на [канал]({NEWS_CHANNEL_LINK})\. Подпишитесь и попробуйте снова."
        elif any(s in err_text for s in ["chat not found", "channel not found"]):
            reply_msg = "Канал для проверки не найден (ошибка администратора)."
        elif "bot is not a member" in err_text:
            reply_msg = "Бот не может проверить подписку (возможно, канал приватный)."
        else:
            reply_msg = "Ошибка проверки подписки."
            logger.error(f"get_chat_member error for {user.id} in {NEWS_CHANNEL_USERNAME}: {e}")
        await reply_target.reply_text(reply_msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"claim_news_bonus_logic error: {e}\n{traceback.format_exc()}")
        await reply_target.reply_text("Непредвиденная ошибка при получении бонуса.", disable_web_page_preview=True)

async def claim_news_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, context, called_from_button=False)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id
    if not user_message or not user_message.strip():
        await update.message.reply_text("Пожалуйста, отправьте непустой запрос.", reply_markup=get_main_reply_keyboard())
        return

    current_model_key = get_current_model_key(context)
    selected_model_details = AVAILABLE_TEXT_MODELS[current_model_key]
    system_prompt = get_current_mode_details(context)["prompt"]

    can_request, limit_message, _ = check_and_log_request_attempt(user_id, current_model_key, context)
    if not can_request:
        await update.message.reply_text(limit_message, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    reply_text = "Произошла ошибка при обработке вашего запроса."
    request_successful = False
    api_type = selected_model_details.get("api_type")

    if api_type == "google_genai":
        if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY: # Simplified check
            reply_text = "Ключ API для Google Gemini не настроен."
        else:
            try:
                model_id = selected_model_details["id"]
                model = genai.GenerativeModel(model_id)
                gen_config_params = {"temperature": 0.75}
                # MAX_OUTPUT_TOKENS_GEMINI_LIB for older models, 1.5/2.0 usually don't need it explicitly this way
                if MAX_OUTPUT_TOKENS_GEMINI_LIB > 0 and not any(s in model_id for s in ["1.5", "2.0"]):
                     gen_config_params["max_output_tokens"] = MAX_OUTPUT_TOKENS_GEMINI_LIB
                
                chat = model.start_chat(history=[{"role": "user", "parts": [system_prompt]}, {"role": "model", "parts": ["Понял. Я готов помочь."]}])
                response = await chat.send_message_async(user_message, generation_config=genai.types.GenerationConfig(**gen_config_params))
                
                if response.text and response.text.strip():
                    reply_text = response.text
                    request_successful = True
                else: # Handle blocked or empty responses
                    block_reason = getattr(response.prompt_feedback, 'block_reason', None)
                    finish_reason = response.candidates[0].finish_reason if response.candidates else None
                    reply_text = f"ИИ не смог сформировать ответ. Причина: {block_reason or finish_reason or 'неизвестно'}."

            except google.api_core.exceptions.GoogleAPIError as e:
                # Simplified error handling
                err_msg_lower = str(e).lower()
                if "api key not valid" in err_msg_lower: reply_text = "⚠️ Ошибка: API ключ Google недействителен."
                elif "billing" in err_msg_lower: reply_text = "⚠️ Проблема с биллингом Google API."
                elif "quota" in err_msg_lower or "resource has been exhausted" in err_msg_lower : reply_text = "⚠️ Исчерпана квота Google API."
                elif "user location" in err_msg_lower: reply_text = "⚠️ Модель недоступна в вашем регионе (Google API)."
                elif "model not found" in err_msg_lower: reply_text = f"⚠️ Модель '{selected_model_details['id']}' не найдена в Google API."
                else: reply_text = f"Ошибка Google API: {type(e).__name__}"
                logger.error(f"GoogleAPIError for {selected_model_details['id']}: {e}")
            except Exception as e:
                logger.error(f"General Google error for {selected_model_details['id']}: {e}\n{traceback.format_exc()}")
                reply_text = "⚠️ Внутренняя ошибка (Google Gemini)."

    elif api_type == "custom_http_api":
        api_key = globals().get(selected_model_details.get("api_key_var_name"))
        if not api_key or ("sk-" not in api_key and "pk-" not in api_key) : # Basic check
            reply_text = f"⚠️ Ключ API для '{selected_model_details['name']}' не настроен."
        else:
            payload = {"model": selected_model_details["id"], "messages": [{"role": "user", "content": system_prompt}, {"role": "user", "content": user_message}],
                       "is_sync": True, "temperature": 0.75, "stream": False}
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {api_key}'}
            try:
                api_response = requests.post(selected_model_details["endpoint"], json=payload, headers=headers, timeout=90)
                api_response.raise_for_status()
                response_data = api_response.json()
                if (res_list := response_data.get("response")) and isinstance(res_list, list) and res_list:
                    if (msg_content := res_list[0].get("message", {}).get("content")):
                        reply_text = msg_content
                        request_successful = True
                    else: reply_text = f"⚠️ ИИ ({selected_model_details['name']}) вернул пустой ответ."
                elif (err_detail := response_data.get("detail")):
                     reply_text = f"⚠️ Ошибка Custom API: {str(err_detail)[:200]}"
                else: reply_text = f"⚠️ Неожиданный ответ от Custom API ({selected_model_details['name']})."
            except requests.exceptions.HTTPError as e_http:
                status = e_http.response.status_code
                if status == 401: reply_text = f"⚠️ Ошибка 401: Неверный API ключ (Custom API)."
                elif status == 402: reply_text = f"⚠️ Ошибка 402: Проблема с оплатой (Custom API)."
                elif status == 429: reply_text = f"⚠️ Ошибка 429: Превышен лимит запросов (Custom API)."
                else: reply_text = f"⚠️ Ошибка сети ({status}) при обращении к '{selected_model_details['name']}'."
                logger.error(f"HTTPError Custom API {selected_model_details['name']}: {e_http}")
            except Exception as e_custom:
                logger.error(f"Custom API error {selected_model_details['name']}: {e_custom}\n{traceback.format_exc()}")
                reply_text = f"⚠️ Ошибка обработки ответа от '{selected_model_details['name']}'."
    else:
        reply_text = f"⚠️ Неизвестный тип API: {api_type}"

    if request_successful and selected_model_details.get("is_limited"):
        increment_request_count(user_id, current_model_key, context)

    reply_text_final, _ = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    await update.message.reply_text(reply_text_final, reply_markup=get_main_reply_keyboard())

async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "🚀 Начало / Инфо"),
        BotCommand("mode", "🧠 Сменить режим ИИ"),
        BotCommand("model", "⚙️ Выбрать модель ИИ"),
        BotCommand("usage", "📊 Мои лимиты"),
        BotCommand("subscribe", "💎 Подписка Профи"),
        BotCommand("claim_news_bonus", "🎁 Бонус за новости"),
        BotCommand("help", "ℹ️ Помощь"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

async def main():
    if "YOUR_TELEGRAM_TOKEN" in TOKEN or not TOKEN or len(TOKEN.split(":")[0]) < 8:
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set correctly or is a placeholder.")
        return

    persistence = PicklePersistence(filepath="bot_data.pkl")
    application = Application.builder().token(TOKEN).persistence(persistence).build()

    await set_bot_commands(application)

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mode", select_mode_command))
    application.add_handler(CommandHandler("model", select_model_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command))
    application.add_handler(CommandHandler("claim_news_bonus", claim_news_bonus_command))

    # Message Handlers for ReplyKeyboard buttons
    application.add_handler(MessageHandler(filters.Text(["🤖 Режим ИИ"]), select_mode_command))
    application.add_handler(MessageHandler(filters.Text(["⚙️ Модель ИИ"]), select_model_command))
    application.add_handler(MessageHandler(filters.Text(["📊 Лимиты"]), usage_command))
    application.add_handler(MessageHandler(filters.Text(["💎 Подписка Профи"]), subscribe_info_command))
    application.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), help_command))

    # CallbackQuery Handler for InlineKeyboard buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(CallbackQueryHandler(buy_button_handler, pattern="^buy_profi_2days$"))


    # Payment Handlers
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # General message handler (must be last for commands)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

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
