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
from typing import Optional # Добавлено для Optional Type Hinting

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
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
            "3.  **Диалоги:** Оформляй диалоги стандартным образом (например, `- Привет! - сказал он.` или с новой строки для каждого персонажа).\n"
            "4.  **Без Markdown:** Генерируй чистый текст без Markdown-разметки (звездочек, решеток и т.п.), если только это не специфический элемент форматирования самого творческого произведения (например, название главы, выделенное заглавными).\n"
            "5.  **Язык:** Используй богатый и выразительный язык, соответствующий творческой задаче.\n"
            "6.  **Завершённость:** Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {"name": "⚡️ Gemini 2.0 Flash", "id": "gemini-2.0-flash", "api_type": "google_genai", "is_limited": True, "limit_type": "daily_free", "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY, "cost_category": "google_flash_free"},
    "google_gemini_2_5_flash_preview": {"name": "💨 Gemini 2.5 Flash Preview", "id": "gemini-2.5-flash-preview-04-17", "api_type": "google_genai", "is_limited": True, "limit_type": "subscription_or_daily_free", "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY, "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY, "cost_category": "google_flash_preview_flex"},
    "custom_api_gemini_2_5_pro": {"name": "🌟 Gemini 2.5 Pro (Продвинутый)", "id": "gemini-2.5-pro-preview-03-25", "api_type": "custom_http_api", "endpoint": CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY", "is_limited": True, "limit_type": "subscription_custom_pro", "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY, "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY, "cost_category": "custom_api_pro_paid", "pricing_info": {}}
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY: logger.warning("Google Gemini API key is not set correctly.")
else:
    try: genai.configure(api_key=GOOGLE_GEMINI_API_KEY); logger.info("Google Gemini API configured.")
    except Exception as e: logger.error(f"Failed to configure Google Gemini API: {e}")
if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY: logger.warning("Custom Gemini Pro API key is not set correctly.")

def get_current_mode_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    key = get_current_model_key(context)
    return AI_MODES.get("gemini_pro_custom_mode" if key == "custom_api_gemini_2_5_pro" else context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY), AI_MODES[DEFAULT_AI_MODE_KEY])

def get_current_model_key(context: ContextTypes.DEFAULT_TYPE) -> str:
    sel_id, sel_api = context.user_data.get('selected_model_id', DEFAULT_MODEL_ID), context.user_data.get('selected_api_type')
    for k, v in AVAILABLE_TEXT_MODELS.items():
        if v["id"] == sel_id and v.get("api_type") == sel_api: return k
    logger.warning(f"Model key not found for id '{sel_id}' type '{sel_api}'. Defaulting.")
    def_cfg = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    context.user_data.update({'selected_model_id': def_cfg["id"], 'selected_api_type': def_cfg["api_type"]})
    return DEFAULT_MODEL_KEY

def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return AVAILABLE_TEXT_MODELS.get(get_current_model_key(context), AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

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
    return ReplyKeyboardMarkup([[KeyboardButton(s) for s in r] for r in [["🤖 Режим ИИ", "⚙️ Модель ИИ"], ["📊 Лимиты", "💎 Подписка Профи"], ["❓ Помощь"]]], resize_keyboard=True)

def get_user_actual_limit_for_model(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not cfg: return 0
    sub_details = context.bot_data.setdefault('user_subscriptions', {}).get(user_id, {})
    is_profi = False
    if sub_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and sub_details.get('valid_until'):
        try: is_profi = datetime.now(datetime.fromisoformat(sub_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(sub_details['valid_until']).date()
        except: pass
    lt = cfg.get("limit_type")
    if lt == "daily_free": return cfg.get("limit", 0)
    if lt in ["subscription_or_daily_free", "subscription_custom_pro"]: return cfg.get("subscription_daily_limit" if is_profi else "limit_if_no_subscription", 0)
    return cfg.get("limit", float('inf')) if not cfg.get("is_limited", False) else 0

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    today = datetime.now().strftime("%Y-%m-%d")
    cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not cfg or not cfg.get("is_limited"): return True, "", 0
    is_profi = False
    if cfg.get("limit_type") in ["subscription_or_daily_free", "subscription_custom_pro", NEWS_CHANNEL_BONUS_MODEL_KEY]: # Check if Profi for bonus model too
        sub_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if sub_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and sub_details.get('valid_until'):
            try: is_profi = datetime.now(datetime.fromisoformat(sub_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(sub_details['valid_until']).date()
            except: pass
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi and context.user_data.get('news_bonus_uses_left', 0) > 0:
        return True, "bonus_available", 0
    counts = context.bot_data.setdefault('all_user_daily_counts', {}).setdefault(user_id, {})
    usage = counts.setdefault(model_key, {'date': '', 'count': 0})
    if usage['date'] != today: usage.update({'date': today, 'count': 0})
    daily_count, daily_limit = usage['count'], get_user_actual_limit_for_model(user_id, model_key, context)
    if daily_count >= daily_limit:
        msg = [f"Вы достигли дневного лимита ({daily_count}/{daily_limit}) для '{cfg['name']}'."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi:
            if not context.user_data.get('claimed_news_bonus', False): msg.append(f"💡 Подпишитесь на [канал]({NEWS_CHANNEL_LINK}) и `/get_news_bonus` для бонуса!")
            elif context.user_data.get('news_bonus_uses_left', 0) == 0: msg.append("ℹ️ Бонус за подписку на новости использован.")
        msg.append("Попробуйте завтра или `/subscribe` для увеличения лимитов.")
        return False, "\n".join(msg), daily_count
    return True, "", daily_count

def increment_request_count(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE):
    cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not cfg or not cfg.get("is_limited"): return
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY:
        is_profi = False
        sub_details = context.bot_data.get('user_subscriptions', {}).get(user_id, {})
        if sub_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and sub_details.get('valid_until'):
            try: is_profi = datetime.now(datetime.fromisoformat(sub_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(sub_details['valid_until']).date()
            except: pass
        if not is_profi and (bonus := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            context.user_data['news_bonus_uses_left'] = bonus - 1
            logger.info(f"User {user_id} consumed news bonus for {model_key}. Left: {bonus-1}")
            return
    today = datetime.now().strftime("%Y-%m-%d")
    usage = context.bot_data.setdefault('all_user_daily_counts', {}).setdefault(user_id, {}).setdefault(model_key, {'date': today, 'count': 0})
    if usage['date'] != today: usage.update({'date': today, 'count': 0})
    usage['count'] += 1
    logger.info(f"User {user_id} daily count for {model_key} to {usage['count']}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    if 'selected_model_id' not in context.user_data or 'selected_api_type' not in context.user_data:
        def_cfg = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data.update({'selected_model_id': def_cfg["id"], 'selected_api_type': def_cfg["api_type"]})
    
    key, mode_name, model_name = get_current_model_key(context), get_current_mode_details(context)['name'], AVAILABLE_TEXT_MODELS[get_current_model_key(context)]['name']
    greeting, mode_l, model_l = "👋 Привет! Я твой ИИ-бот на Gemini.", f"🧠 Режим: *{escape_markdown(mode_name,version=2)}*", f"⚙️ Модель: *{escape_markdown(model_name,version=2)}*"
    _, lim_msg, count = check_and_log_request_attempt(user_id, key, context)
    lim_t = f"Лимит: {count}/{get_user_actual_limit_for_model(user_id, key, context)} в день."
    if "Вы достигли" in lim_msg: lim_t = lim_msg.splitlines()[0]
    lim_l = f"📊 {escape_markdown(lim_t,version=2)}"
    
    parts = [escape_markdown(greeting,version=2), mode_l, model_l, lim_l]
    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle": # Проверяем, что имя канала задано
        bonus_info = ""
        if not context.user_data.get('claimed_news_bonus', False):
            bonus_info = (f"\n🎁 Получите бонус за подписку на [наш новостной канал]({NEWS_CHANNEL_LINK})\! "
                          f"Используйте команду `/get_news_bonus` для инструкций\.")
        elif (bal := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info = f"\n✅ У вас есть *{bal}* бонусных генераций за подписку\."
        else: bonus_info = f"\nℹ️ Бонус за подписку на [канал]({NEWS_CHANNEL_LINK}) уже использован\."
        parts.append(bonus_info)
        
    parts.extend([f"\n{escape_markdown('Вы можете:',version=2)}", "💬 Задавать вопросы", "🤖 `/mode` или кнопка", "⚙️ `/model` или кнопка", "📊 `/usage` или кнопка", "💎 `/subscribe` или кнопка", f"🎁 `/get_news_bonus`", "❓ `/help` или кнопка", f"\n{escape_markdown('Ваш запрос?',version=2)}"])
    final_md = "\n".join(parts)
    try:
        await update.message.reply_text(final_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
    except telegram.error.BadRequest: # Fallback
        # ... (упрощенный plain text fallback для /start)
        await update.message.reply_text("Привет! Используйте кнопки или команды для навигации.", reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
    logger.info(f"Start command for user {user_id}")

async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        await update.message.reply_text("Функция бонуса за подписку временно не настроена.", disable_web_page_preview=True)
        return

    if context.user_data.get('claimed_news_bonus', False) and context.user_data.get('news_bonus_uses_left', 0) == 0:
        await update.message.reply_text(f"Вы уже получали и использовали бонус за подписку на [канал]({NEWS_CHANNEL_LINK})\.", parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        return
    elif context.user_data.get('claimed_news_bonus', False) and (uses_left := context.user_data.get('news_bonus_uses_left', 0)) > 0:
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get('name', "бонусной модели")
        await update.message.reply_text(f"У вас уже есть *{uses_left}* бонусных генераций для модели '{escape_markdown(bonus_model_name, version=2)}' за подписку\.", parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        return

    text = (
        f"Чтобы получить *{NEWS_CHANNEL_BONUS_GENERATIONS}* бонусную генерацию:\n"
        f"1\\. Перейдите на наш [новостной канал]({NEWS_CHANNEL_LINK})\n"
        f"2\\. Подпишитесь\n"
        f"3\\. Вернитесь сюда и нажмите кнопку ниже для проверки\."
    )
    keyboard = [
        [InlineKeyboardButton(f"📢 Перейти на канал {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Я подписался, проверить!", callback_data="check_news_subscription")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

async def claim_news_bonus_logic(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 called_from_button: bool = False, message_to_edit: Optional[telegram.Message] = None):
    user = update.effective_user
    # Определяем, куда отвечать или что редактировать
    if called_from_button and update.callback_query:
        target_chat_id = update.callback_query.message.chat_id
        # message_to_edit передается из button_callback
    elif update.message:
        target_chat_id = update.message.chat_id
        message_to_edit = None # Команда /claim_news_bonus отвечает новым сообщением
    else:
        logger.warning("claim_news_bonus_logic: Could not determine user or reply target.")
        return

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        err_msg = "Функция бонуса не настроена."
        if message_to_edit: await message_to_edit.edit_text(err_msg, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=target_chat_id, text=err_msg, disable_web_page_preview=True)
        return

    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_cfg:
        err_msg = "Ошибка: Бонусная модель не найдена."
        if message_to_edit: await message_to_edit.edit_text(err_msg, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=target_chat_id, text=err_msg, disable_web_page_preview=True)
        return
    bonus_model_name_md = escape_markdown(bonus_model_cfg['name'], version=2)

    if context.user_data.get('claimed_news_bonus', False):
        uses_left = context.user_data.get('news_bonus_uses_left', 0)
        reply_text = ""
        if uses_left > 0:
            reply_text = (f"Вы уже активировали бонус\. У вас осталось *{uses_left}* бесплатных генераций для модели '{bonus_model_name_md}'\.\n"
                          f"Наш [канал]({NEWS_CHANNEL_LINK})\.")
        else:
            reply_text = (f"Вы уже получали и использовали бонус за подписку для модели '{bonus_model_name_md}'\.\n"
                          f"Наш [канал]({NEWS_CHANNEL_LINK})\.")
        
        if message_to_edit: await message_to_edit.edit_text(reply_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=target_chat_id, text=reply_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        return

    try:
        member = await context.bot.get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member.status in ['member', 'administrator', 'creator']:
            context.user_data['claimed_news_bonus'] = True
            context.user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            success_text = (
                f"🎉 Спасибо за подписку на [канал]({NEWS_CHANNEL_LINK})\!\n"
                f"Вам начислена *{NEWS_CHANNEL_BONUS_GENERATIONS}* бесплатная генерация для модели '{bonus_model_name_md}'\."
            )
            if message_to_edit: await message_to_edit.edit_text(success_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
            else: await context.bot.send_message(chat_id=target_chat_id, text=success_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        else:
            # Если подписка не найдена, и это было с кнопки, предлагаем попробовать еще раз (не убираем кнопки)
            fail_text = (f"Подписка на [канал]({NEWS_CHANNEL_LINK}) не найдена\. Пожалуйста, убедитесь, что вы подписаны, и нажмите кнопку проверки еще раз\.")
            keyboard_after_fail = None
            if message_to_edit: # Если есть сообщение для редактирования (значит, это с кнопки)
                 keyboard_after_fail = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"📢 Перейти на канал {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)],
                    [InlineKeyboardButton("✅ Я подписался, проверить снова!", callback_data="check_news_subscription")]
                ])
                 await message_to_edit.edit_text(fail_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard_after_fail, disable_web_page_preview=True)
            else: # Если это была команда /claim_news_bonus
                await context.bot.send_message(chat_id=target_chat_id, text=fail_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

    except telegram.error.BadRequest as e:
        # ... (обработка ошибок get_chat_member как раньше)
        err_msg_on_check = f"Ошибка проверки подписки: {e}. Попробуйте позже."
        if message_to_edit: await message_to_edit.edit_text(err_msg_on_check, reply_markup=None, disable_web_page_preview=True) # Убираем кнопки при ошибке
        else: await context.bot.send_message(chat_id=target_chat_id, text=err_msg_on_check, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"claim_news_bonus_logic general error: {e}\n{traceback.format_exc()}")
        err_msg_general = "Непредвиденная ошибка при получении бонуса."
        if message_to_edit: await message_to_edit.edit_text(err_msg_general, reply_markup=None, disable_web_page_preview=True)
        else: await context.bot.send_message(chat_id=target_chat_id, text=err_msg_general, disable_web_page_preview=True)

async def claim_news_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, context, called_from_button=False, message_to_edit=None)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    # ... (остальной код button_callback без изменений до claim_news_bonus) ...
    if data.startswith("set_mode_"):
        # ... (код как в предыдущей версии)
        # В конце:
        if new_text:
            try: await query.message.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
            except telegram.error.BadRequest: await query.message.edit_text(text=plain_fallback, reply_markup=None, disable_web_page_preview=True)
            except Exception as e: logger.error(f"Edit error in set_mode: {e}")
        return

    elif data.startswith("set_model_"):
        # ... (код как в предыдущей версии)
        # В конце:
        if new_text:
            try: await query.message.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None, disable_web_page_preview=True)
            except telegram.error.BadRequest: await query.message.edit_text(text=plain_fallback, reply_markup=None, disable_web_page_preview=True)
            except Exception as e: logger.error(f"Edit error in set_model: {e}")
        return
        
    elif data == "check_news_subscription":
        await claim_news_bonus_logic(update, context, called_from_button=True, message_to_edit=query.message)
        return # Логика ответа/редактирования внутри claim_news_bonus_logic

    # Остальные обработчики кнопок (например, для покупки) должны быть здесь или в отдельных CallbackQueryHandler
    elif data == "buy_profi_2days": # Переместил сюда для примера, если он был в общем button_callback
        await buy_button_handler(update, context) # buy_button_handler должен быть async и принимать (update, context)
        return

async def select_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # Остальные команды без изменений
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
    user_id = update.effective_user.id # Получаем user_id для get_user_actual_limit_for_model
    keyboard = []
    for key, details in AVAILABLE_TEXT_MODELS.items():
        # Формируем текст для кнопки, включая лимит, если он есть и не бесконечный
        limit_info = ""
        if details.get("is_limited"):
            # _, _, current_c = check_and_log_request_attempt(user_id, key, context) # Не вызываем check_and_log здесь, чтобы не сбрасывать счетчик
            # Вместо этого просто получаем лимит
            actual_l = get_user_actual_limit_for_model(user_id, key, context)
            if actual_l != float('inf'): # Показываем только если лимит не бесконечный
                 # Попробуем получить текущее использование без логирования попытки
                today_str = datetime.now().strftime("%Y-%m-%d")
                user_model_counts = context.bot_data.get('all_user_daily_counts', {}).get(user_id, {})
                model_daily_usage = user_model_counts.get(key, {'date': '', 'count': 0})
                current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
                limit_info = f" ({current_c_display}/{actual_l})"


        button_text = f"{details['name']}{limit_info}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"set_model_{key}")])

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
            # Не вызываем check_and_log_request_attempt здесь, чтобы не сбрасывать счетчик при простом просмотре лимитов.
            # Получаем текущее использование напрямую, если оно есть за сегодня.
            today_str = datetime.now().strftime("%Y-%m-%d")
            all_daily_counts = context.bot_data.get('all_user_daily_counts', {})
            user_model_counts = all_daily_counts.get(user_id, {})
            model_daily_usage = user_model_counts.get(mk, {'date': '', 'count': 0})
            current_c_display = model_daily_usage['count'] if model_daily_usage['date'] == today_str else 0
            
            actual_l = get_user_actual_limit_for_model(user_id, mk, context)
            usage_text_parts.append(f"▫️ {escape_markdown(mc['name'],version=2)}: *{current_c_display}/{actual_l}*")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle":
        bonus_model_name = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY,{}).get('name', "бонусной модели")
        bonus_model_name_md = escape_markdown(bonus_model_name,version=2)
        bonus_info_usage = ""
        if not context.user_data.get('claimed_news_bonus', False):
            bonus_info_usage = (f"\n🎁 Подпишитесь на [канал]({NEWS_CHANNEL_LINK}) и используйте `/get_news_bonus` "
                                f"для получения *{NEWS_CHANNEL_BONUS_GENERATIONS}* генерации ({bonus_model_name_md})\!")
        elif (bonus_left := context.user_data.get('news_bonus_uses_left', 0)) > 0:
            bonus_info_usage = f"\n🎁 У вас *{bonus_left}* бонусных генераций для {bonus_model_name_md} ([канал]({NEWS_CHANNEL_LINK}))\."
        else:
            bonus_info_usage = f"\nℹ️ Бонус за подписку на [канал]({NEWS_CHANNEL_LINK}) ({bonus_model_name_md}) уже использован\."
        usage_text_parts.append(bonus_info_usage)

    if not subscription_active:
        usage_text_parts.append(f"\nХотите больше лимитов? Ознакомьтесь с Подпиской Профи: `/subscribe`")

    final_usage_text_md = "\n".join(usage_text_parts)
    try:
        await update.message.reply_text(final_usage_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
    except telegram.error.BadRequest:
        # ... (plain text fallback для /usage)
        await update.message.reply_text("Не удалось отобразить лимиты.", reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # Без изменений
    text_parts = ["🌟 *Подписка Профи – Максимум возможностей Gemini\!* 🌟",
                  "\nПолучите расширенные дневные лимиты для самых мощных моделей:"]
    for key, model_char in [("google_gemini_2_5_flash_preview", "💨"), ("custom_api_gemini_2_5_pro", "🌟")]:
        m_conf = AVAILABLE_TEXT_MODELS[key]
        text_parts.append(f"{model_char} {escape_markdown(m_conf['name'], version=2)}: *{m_conf['subscription_daily_limit']}* запросов/день "
                          f"(Бесплатно: {m_conf['limit_if_no_subscription']} запросов/день)")
    text_parts.append(f"\nБазовая модель всегда доступна с щедрым лимитом:\n"
                      f"⚡️ {escape_markdown(AVAILABLE_TEXT_MODELS['google_gemini_2_0_flash']['name'], version=2)}: "
                      f"*{DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY}* запросов/день (бесплатно для всех)")
    text_parts.extend(["\n✨ *Доступный тариф Профи для теста:*", f"▫️ Тест-драйв (2 дня): `{escape_markdown('99 рублей', version=2)}`"])
    
    keyboard = [[InlineKeyboardButton("💳 Купить Профи (2 дня - 99 RUB)", callback_data="buy_profi_2days")]]
    reply_markup_subscribe = InlineKeyboardMarkup(keyboard)
    final_text_subscribe = "\n".join(text_parts)

    target_message = update.callback_query.message if update.callback_query else update.message
    edit_func = target_message.edit_text if update.callback_query else target_message.reply_text

    try:
        await edit_func(final_text_subscribe, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup_subscribe, disable_web_page_preview=True)
    except telegram.error.BadRequest:
         await edit_func("Подписка Профи: ... (упрощенный текст)", reply_markup=reply_markup_subscribe, disable_web_page_preview=True)


async def buy_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): # Без изменений, кроме await query.message.reply_text
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "buy_profi_2days":
        if not PAYMENT_PROVIDER_TOKEN or "YOUR_REAL_PAYMENT_PROVIDER_TOKEN_HERE" in PAYMENT_PROVIDER_TOKEN:
            # Отвечаем на сообщение, где была кнопка, или отправляем новое, если то было удалено
            await query.message.reply_text("⚠️ Сервис оплаты временно недоступен.",reply_markup=get_main_reply_keyboard())
            return
        prices = [LabeledPrice(label="Подписка Профи (2 дня)", amount=99 * 100)]
        try:
            await context.bot.send_invoice(
                chat_id=user_id, title="Подписка Профи (2 дня)",
                description="Доступ к расширенным лимитам Gemini на 2 дня.",
                payload=f"profi_2days_uid{user_id}_t{int(datetime.now().timestamp())}",
                provider_token=PAYMENT_PROVIDER_TOKEN, currency="RUB", prices=prices
            )
            # Убираем кнопку "Купить" из сообщения, где она была
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e:
            logger.error(f"Error sending invoice to user {user_id}: {e}")
            await query.message.reply_text("⚠️ Не удалось создать счет. Попробуйте позже.")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): # Без изменений
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("profi_2days_uid"): await query.answer(ok=True)
    else: await query.answer(ok=False, error_message="Платеж не может быть обработан.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): # Без изменений
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE): # Обновлено
    help_text_parts = [
        f"👋 Я многофункциональный ИИ-бот на базе моделей Gemini от Google\.",
        "\n*Основные команды и кнопки:*",
        "`/start` \- Начало / Инфо",
        "`/mode` \- Сменить режим ИИ",
        "`/model` \- Выбрать модель ИИ",
        "`/usage` \- Мои лимиты",
        "`/subscribe` \- Подписка Профи",
        f"`/get_news_bonus` \- 🎁 Бонус за подписку на [канал]({NEWS_CHANNEL_LINK})", # Команда изменена
        "`/help` \- Это сообщение",
        "\n💡 Просто отправьте свой вопрос или задание боту\!"
    ]
    # Собираем текст, только `/command` и ссылки не экранируем дополнительно, остальное экранируем для MarkdownV2
    final_help_text_md = ""
    for part in help_text_parts:
        if part.startswith("`/") or NEWS_CHANNEL_LINK in part : # Не экранируем команды и части со ссылкой
            final_help_text_md += part + "\n"
        else:
            final_help_text_md += escape_markdown(part, version=2) + "\n"

    try:
        await update.message.reply_text(final_help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        logger.error(f"Error sending help_command with MarkdownV2: {e}. Text: {final_help_text_md}")
        plain_help = ["Я ИИ-бот Gemini. Команды: /start, /mode, /model, /usage, /subscribe, /get_news_bonus, /help.", # Команда изменена
                      f"Канал для бонуса: {NEWS_CHANNEL_LINK}", "Напишите ваш вопрос."]
        await update.message.reply_text("\n".join(plain_help), reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE): # Без изменений в логике, но проверил return
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
        # limit_message уже содержит MarkdownV2 если нужно (из check_and_log_request_attempt)
        await update.message.reply_text(limit_message, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard(), disable_web_page_preview=True)
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
                if MAX_OUTPUT_TOKENS_GEMINI_LIB > 0 and not any(s in model_id for s in ["1.5", "2.0"]):
                     gen_config_params["max_output_tokens"] = MAX_OUTPUT_TOKENS_GEMINI_LIB
                
                chat = model.start_chat(history=[{"role": "user", "parts": [system_prompt]}, {"role": "model", "parts": ["Понял. Я готов помочь."]}])
                response = await chat.send_message_async(user_message, generation_config=genai.types.GenerationConfig(**gen_config_params))
                
                if response.text and response.text.strip():
                    reply_text = response.text
                    request_successful = True
                else: 
                    block_reason_msg = ""
                    if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                        block_reason_msg = f" Причина: {response.prompt_feedback.block_reason}."
                    if response.candidates and not response.text: 
                         candidate = response.candidates[0]
                         if candidate.finish_reason != 1: # FINISH_REASON_UNSPECIFIED = 0, FINISH_REASON_STOP = 1, FINISH_REASON_MAX_TOKENS = 2, FINISH_REASON_SAFETY = 3, FINISH_REASON_RECITATION = 4, FINISH_REASON_OTHER = 5
                              block_reason_msg += f" Завершение: {candidate.finish_reason.name if hasattr(candidate.finish_reason, 'name') else candidate.finish_reason}."
                         if candidate.safety_ratings:
                             block_reason_msg += f" Рейтинги безопасности: {[(sr.category.name, sr.probability.name) for sr in candidate.safety_ratings]}."
                    reply_text = f"ИИ (Google) не смог сформировать ответ или он был отфильтрован.{block_reason_msg} Попробуйте другой запрос."


            except google.api_core.exceptions.GoogleAPIError as e:
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
        if not api_key or ("sk-" not in api_key and "pk-" not in api_key) :
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
        BotCommand("get_news_bonus", "🎁 Бонус за новости"), # Изменено
        BotCommand("claim_news_bonus", "✅ Подтвердить бонус (альтерн.)"), # Оставим как альтернативу
        BotCommand("help", "ℹ️ Помощь"),
    ]
    try: await application.bot.set_my_commands(commands)
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

async def main():
    if "YOUR_TELEGRAM_TOKEN" in TOKEN or not TOKEN: # Simplified check
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set correctly.")
        return

    persistence = PicklePersistence(filepath="bot_data.pkl")
    application = Application.builder().token(TOKEN).persistence(persistence).build()
    await set_bot_commands(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mode", select_mode_command))
    application.add_handler(CommandHandler("model", select_model_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command))
    application.add_handler(CommandHandler("get_news_bonus", get_news_bonus_info_command)) # Новая команда
    application.add_handler(CommandHandler("claim_news_bonus", claim_news_bonus_command)) # Альтернативная команда

    application.add_handler(MessageHandler(filters.Text(["🤖 Режим ИИ"]), select_mode_command))
    application.add_handler(MessageHandler(filters.Text(["⚙️ Модель ИИ"]), select_model_command))
    application.add_handler(MessageHandler(filters.Text(["📊 Лимиты"]), usage_command))
    application.add_handler(MessageHandler(filters.Text(["💎 Подписка Профи"]), subscribe_info_command))
    application.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), help_command))
    
    # Общий CallbackQueryHandler для инлайн-кнопок меню и бонуса
    application.add_handler(CallbackQueryHandler(button_callback))
    # Отдельный для покупки, если buy_button_handler не в общем button_callback
    # application.add_handler(CallbackQueryHandler(buy_button_handler, pattern="^buy_profi_2days$")) # Уже есть в общем

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
