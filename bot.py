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
import json # Для отладки и работы с JSON ответами
from datetime import datetime # Для управления ежедневными лимитами

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0") # ОБЯЗАТЕЛЬНО ЗАМЕНИТЕ!

# Ключ для официального Google Gemini API
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # ЗАМЕНИТЕ, если отличается

# Ключ и эндпоинт для "кастомного" API доступа к gemini-2-5-pro
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P") # ЗАМЕНИТЕ, если отличается
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro") # ЗАМЕНИТЕ, если эндпоинт другой!


# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048 # Для моделей, вызываемых через google.generativeai, если нужно ограничение
MAX_MESSAGE_LENGTH_TELEGRAM = 4000 # Максимальная длина сообщения в Telegram (реально 4096)

# Лимиты по умолчанию (могут быть переопределены в конфигурации модели или подпиской)
DEFAULT_FREE_REQUESTS_DAILY = 10
DEFAULT_PRO_SUBSCRIPTION_REQUESTS_DAILY = 25
DEFAULT_ADVANCED_SUBSCRIPTION_REQUESTS_DAILY = 30
DEFAULT_CUSTOM_API_SUBSCRIPTION_REQUESTS_DAILY = 25


# --- РЕЖИМЫ РАБОТЫ ИИ ---
AI_MODES = {
    "universal_ai": {
        "name": "🤖 Универсальный ИИ",
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
        "welcome": "Активирован режим 'Универсальный ИИ'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "✍️ Творческий Помощник",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Помогай пользователю генерировать идеи, писать тексты (рассказы, стихи, сценарии, маркетинговые материалы), "
            "придумывать слоганы, разрабатывать концепции и решать другие творческие задачи. "
            "Будь вдохновляющим, оригинальным и предлагай нестандартные подходы.\n\n"
            "**Оформление творческого ответа (простой структурированный текст):**\n"
            "1.  **Структура и Абзацы:** Для прозы используй абзацы, чтобы четко структурировать повествование. Для стихов сохраняй деление на строфы и правильные переносы строк.\n"
            "2.  **Без специального форматирования:** Пожалуйста, НЕ используй Markdown-разметку (звездочки для жирного текста или курсива и т.п.). Основной акцент на содержании и структуре через абзацы и списки, если они нужны (например, для перечисления идей).\n"
            "3.  **Списки Идей/Вариантов:** Если предлагаешь несколько вариантов (например, заголовков, идей), оформляй их как простой маркированный или нумерованный список.\n"
            "4.  **Диалоги:** Прямую речь в рассказах или сценариях оформляй стандартными литературными способами (например, с использованием тире или кавычек), без Markdown.\n"
            "5.  **Читаемость:** Текст должен легко читаться и быть увлекательным. Структура должна помогать этому.\n"
            "6.  **Завершённость:** Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Режим 'Творческий Помощник' к вашим услугам! Над какой творческой задачей поработаем?"
    },
}
DEFAULT_AI_MODE_KEY = "universal_ai"

# --- МОДЕЛИ ИИ ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "⚡️ Gemini 2.0 Flash (Google)",
        "id": "gemini-2.0-flash",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free", # Отдельный тип для общего бесплатного лимита
        "limit": DEFAULT_FREE_REQUESTS_DAILY, # 10 бесплатных запросов в день к этой модели
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "💨 Gemini 2.5 Flash Preview (Google)",
        "id": "gemini-2.5-flash-preview-04-17",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free", # Доступна по подписке или с меньшим бесплатным лимитом
        "limit_if_no_subscription": 5, # 5 бесплатных в день, если нет подписки
        "subscription_daily_limit": DEFAULT_PRO_SUBSCRIPTION_REQUESTS_DAILY, # 25 для подписчиков "Pro" и выше
        "cost_category": "google_flash_preview_flex"
    },
    "google_gemini_2_5_pro_preview": {
        "name": "👑 Gemini 2.5 Pro Preview (Google)",
        "id": "gemini-2.5-pro-preview-05-06",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_daily_pro", # Требует подписки уровня "Pro" или "Advanced"
        "limit_if_no_subscription": 1, # 1 пробный запрос
        "subscription_daily_limit_pro": DEFAULT_PRO_SUBSCRIPTION_REQUESTS_DAILY, # 25 для "Pro"
        "subscription_daily_limit_advanced": DEFAULT_ADVANCED_SUBSCRIPTION_REQUESTS_DAILY, # 30 для "Advanced"
        "cost_category": "google_pro_paid"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "🌟 Gemini 2.5 Pro (Custom API)",
        "id": "gemini-2-5-pro", # ID для кастомного API
        "api_type": "custom_http_api",
        "endpoint": CUSTOM_GEMINI_PRO_ENDPOINT,
        "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY", # Имя переменной с ключом
        "is_limited": True,
        "limit_type": "subscription_daily_custom", # Требует специальной подписки или высшего уровня
        "limit_if_no_subscription": 0, # Нет бесплатных запросов (или 1 пробный)
        "subscription_daily_limit": DEFAULT_CUSTOM_API_SUBSCRIPTION_REQUESTS_DAILY, # 25 для подписчиков этого API
        "cost_category": "custom_api_pro_premium"
    }
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash" # Ключ модели по умолчанию из AVAILABLE_TEXT_MODELS
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]


# --- Конфигурация API Google Gemini ---
if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
    logger.warning("Google Gemini API key (GOOGLE_GEMINI_API_KEY) is not set correctly or uses a placeholder. Google AI models may not work.")
    # Можно не завершать работу, а просто выводить ошибку при попытке использовать эти модели
else:
    try:
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        logger.info("Google Gemini API configured successfully.")
        # Раскомментируйте для вывода списка доступных моделей при старте:
        # logger.info("Available Google Gemini Models (via google-generativeai library):")
        # for m in genai.list_models():
        #     if 'generateContent' in m.supported_generation_methods:
        #         logger.info(f"- {m.name} (Display: {m.display_name})")
    except Exception as e:
        logger.error(f"Failed to configure Google Gemini API: {str(e)}")

# Проверка ключа для кастомного API
if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or "sk-" not in CUSTOM_GEMINI_PRO_API_KEY :
    logger.warning("Custom Gemini Pro API key (CUSTOM_GEMINI_PRO_API_KEY) is not set correctly or uses a placeholder. Custom API model may not work.")


# --- Вспомогательные функции ---
def get_current_mode_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    mode_key = context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

def get_current_model_key(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Возвращает ключ текущей модели из AVAILABLE_TEXT_MODELS."""
    selected_id = context.user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = context.user_data.get('selected_api_type', AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]['api_type'])
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id and info.get("api_type") == selected_api_type:
            return key
    logger.warning(f"Could not find key for model_id {selected_id} and api_type {selected_api_type}. Falling back to default.")
    return DEFAULT_MODEL_KEY


def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Возвращает полную конфигурацию текущей выбранной модели."""
    model_key = get_current_model_key(context)
    return AVAILABLE_TEXT_MODELS[model_key]


def get_current_model_display_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return get_selected_model_details(context)["name"]


def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if len(text) <= max_length:
        return text, False
    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)
    if adjusted_max_length <= 0: return text[:max_length-len("...")] + "...", True
    truncated_text = text[:adjusted_max_length]
    possible_cut_points = []
    for sep in ['\n\n', '. ', '! ', '? ', '\n']:
        pos = truncated_text.rfind(sep)
        if pos != -1:
            actual_pos = pos + (len(sep) -1 if sep.endswith(' ') and len(sep) > 1 else len(sep))
            if actual_pos > 0 : possible_cut_points.append(actual_pos)
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
        [KeyboardButton("📊 Лимиты / Подписка"), KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# --- Управление лимитами ---
def get_user_actual_limit_for_model(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Определяет актуальный дневной лимит для пользователя для указанной модели."""
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0

    user_subscription = context.user_data.get('subscription_info', {'level': None, 'valid_until': None})
    # TODO: Проверка valid_until для подписки
    
    limit_type = model_config.get("limit_type")
    actual_limit = 0

    if limit_type == "daily_free":
        actual_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        if user_subscription.get('level') in ["pro", "advanced", "custom_api"]: # Пример уровней подписки
            actual_limit = model_config.get("subscription_daily_limit", 0)
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_daily_pro":
        if user_subscription.get('level') == "pro":
            actual_limit = model_config.get("subscription_daily_limit_pro", 0)
        elif user_subscription.get('level') == "advanced": # Advanced включает Pro
             actual_limit = model_config.get("subscription_daily_limit_advanced", model_config.get("subscription_daily_limit_pro",0))
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_daily_premium": # Для самой дорогой Google модели
        if user_subscription.get('level') == "advanced":
             actual_limit = model_config.get("subscription_daily_limit",0) # Берем общий subscription_daily_limit
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_daily_custom": # Для кастомного API
        if user_subscription.get('level') == "custom_api" or user_subscription.get('level') == "advanced": # Пример, что advanced дает доступ
            actual_limit = model_config.get("subscription_daily_limit", 0)
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    else: # Неизвестный тип лимита или нет лимита
        actual_limit = float('inf') # Безлимит, если тип не определен (или 0, если строже)

    return actual_limit

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    """
    Проверяет, может ли пользователь сделать запрос. Не инкрементирует счетчик.
    Возвращает: (can_request: bool, message_if_limit_exceeded: str, current_daily_count_for_model: int)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return True, "", 0 # Нет конфига или модель не лимитирована

    user_counts = context.user_data.setdefault('daily_request_counts', {})
    model_daily_usage = user_counts.setdefault(model_key, {'date': '', 'count': 0})

    if model_daily_usage['date'] != today_str:
        model_daily_usage['date'] = today_str
        model_daily_usage['count'] = 0
    
    current_user_model_count = model_daily_usage['count']
    actual_limit = get_user_actual_limit_for_model(user_id, model_key, context)

    if current_user_model_count >= actual_limit:
        message = (f"Вы достигли дневного лимита ({current_user_model_count}/{actual_limit}) "
                   f"для модели '{model_config['name']}'.\n"
                   "Попробуйте завтра или рассмотрите улучшение подписки.")
        return False, message, current_user_model_count
    
    return True, "", current_user_model_count

def increment_request_count(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE):
    """Инкрементирует счетчик запросов для пользователя и модели."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    user_counts = context.user_data.setdefault('daily_request_counts', {})
    model_daily_usage = user_counts.setdefault(model_key, {'date': today_str, 'count': 0})
    
    # Дополнительная проверка на смену дня, если вдруг не сработало ранее
    if model_daily_usage['date'] != today_str:
        model_daily_usage['date'] = today_str
        model_daily_usage['count'] = 0
        
    model_daily_usage['count'] += 1
    logger.info(f"User {user_id} request count for {model_key} incremented to {model_daily_usage['count']}")


# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    
    # Установка модели по умолчанию, если еще не установлена
    if 'selected_model_id' not in context.user_data or 'selected_api_type' not in context.user_data:
        default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data['selected_model_id'] = default_model_conf["id"]
        context.user_data['selected_api_type'] = default_model_conf["api_type"]

    context.user_data.setdefault('daily_request_counts', {})
    context.user_data.setdefault('subscription_info', {'level': None, 'valid_until': None}) # level: 'pro', 'advanced', 'custom_api'

    current_mode_name = get_current_mode_details(context)['name']
    current_model_name = get_current_model_display_name(context)
    
    greeting = escape_markdown("Привет! Я многофункциональный ИИ-бот.", version=2)
    mode_line = f"{escape_markdown('Текущий режим: ', version=2)}*{escape_markdown(current_mode_name, version=2)}*"
    model_line = f"{escape_markdown('Текущая модель: ', version=2)}*{escape_markdown(current_model_name, version=2)}*"
    
    # Отображение лимита для текущей модели
    current_model_key = get_current_model_key(context)
    _, limit_msg_check, current_count = check_and_log_request_attempt(user_id, current_model_key, context)
    actual_limit_for_model = get_user_actual_limit_for_model(user_id, current_model_key, context)
    limit_info_line = f"{escape_markdown(f'Лимит для текущей модели: {current_count}/{actual_limit_for_model} в день.', version=2)}"
    if "Вы достигли" in limit_msg_check: # Если лимит уже исчерпан
        limit_info_line = escape_markdown(limit_msg_check.split('\n')[0], version=2)


    you_can = escape_markdown("Вы можете:", version=2)
    action1 = escape_markdown("▫️ Задавать мне вопросы или давать задания.", version=2)
    action2 = f"▫️ Сменить режим работы (`/mode` или кнопка)"
    action3 = f"▫️ Выбрать другую модель ИИ (`/model` или кнопка)"
    action4 = f"▫️ Узнать о лимитах и подписке (`/usage` или кнопка)"
    action5 = f"▫️ Получить помощь (`/help`)"
    invitation = escape_markdown("Просто напишите ваш запрос!", version=2)

    text_to_send = (
        f"{greeting}\n\n"
        f"{mode_line}\n"
        f"{model_line}\n"
        f"{limit_info_line}\n\n"
        f"{you_can}\n"
        f"{action1}\n{action2}\n{action3}\n{action4}\n{action5}\n\n"
        f"{invitation}"
    )
    try:
        await update.message.reply_text(text_to_send, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest: # Фоллбэк на простой текст
        plain_text_version = (
            f"Привет! Я многофункциональный ИИ-бот.\n\n"
            f"Текущий режим: {current_mode_name}\n"
            f"Текущая модель: {current_model_name}\n"
            f"Лимит для текущей модели: {current_count}/{actual_limit_for_model} в день.\n\n"
            "Вы можете:\n"
            "▫️ Задавать мне вопросы или давать задания.\n"
            "▫️ Сменить режим работы (/mode или кнопка)\n"
            "▫️ Выбрать другую модель ИИ (/model или кнопка)\n"
            "▫️ Узнать о лимитах и подписке (/usage или кнопка)\n"
            "▫️ Получить помощь (/help)\n\n"
            "Просто напишите ваш запрос!"
        )
        await update.message.reply_text(plain_text_version, reply_markup=get_main_reply_keyboard())
    logger.info(f"Start command processed for user {user_id}.")


async def select_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")] for key, details in AI_MODES.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите режим работы для ИИ:', reply_markup=reply_markup)

async def select_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for key, details in AVAILABLE_TEXT_MODELS.items():
        # Передаем ключ словаря, а не ID, чтобы потом легко найти всю конфигурацию
        keyboard.append([InlineKeyboardButton(details["name"], callback_data=f"set_model_{key}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите модель ИИ:', reply_markup=reply_markup)

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscription_info = context.user_data.get('subscription_info', {'level': None})
    sub_level = subscription_info.get('level', 'Нет')
    sub_valid = subscription_info.get('valid_until', 'N/A')

    usage_text = f"ℹ️ **Информация о ваших лимитах и подписке**\n\n"
    usage_text += f"Текущий уровень подписки: *{escape_markdown(str(sub_level), version=2)}*\n"
    if sub_level != 'Нет' and sub_valid != 'N/A':
        usage_text += f"Действительна до: *{escape_markdown(str(sub_valid), version=2)}*\n"
    usage_text += "\n"

    usage_text += "Ежедневные лимиты запросов по моделям:\n"
    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            _, _, current_count = check_and_log_request_attempt(user_id, model_key, context) # Получаем текущее использование
            actual_limit = get_user_actual_limit_for_model(user_id, model_key, context)
            usage_text += f"▫️ {escape_markdown(model_config['name'], version=2)}: *{current_count}/{actual_limit}*\n"
    
    usage_text += "\n"
    usage_text += escape_markdown("Для изменения подписки или при возникновении вопросов обратитесь к администратору.", version=2) # Заглушка
    
    try:
        await update.message.reply_text(usage_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        # Простая текстовая версия
        plain_usage_text = f"Уровень подписки: {sub_level} (до {sub_valid})\nЛимиты:\n"
        for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
             if model_config.get("is_limited"):
                _, _, current_count = check_and_log_request_attempt(user_id, model_key, context)
                actual_limit = get_user_actual_limit_for_model(user_id, model_key, context)
                plain_usage_text += f"- {model_config['name']}: {current_count}/{actual_limit}\n"
        await update.message.reply_text(plain_usage_text, reply_markup=get_main_reply_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Аналогично start, можно добавить информацию о текущей модели и режиме)
    help_text_md = (
        f"{escape_markdown('🤖 Я многофункциональный ИИ-бот на базе моделей Gemini от Google.', version=2)}\n\n"
        f"{escape_markdown('Основные команды:', version=2)}\n"
        f"`/start` {escape_markdown('- информация о боте и текущих настройках.', version=2)}\n"
        f"`/mode` {escape_markdown(' или кнопка ', version=2)}`🤖 Режим ИИ` {escape_markdown('- смена режима работы ИИ.', version=2)}\n"
        f"`/model` {escape_markdown(' или кнопка ', version=2)}`⚙️ Модель ИИ` {escape_markdown('- выбор одной из доступных моделей Gemini.', version=2)}\n"
        f"`/usage` {escape_markdown(' или кнопка ', version=2)}`📊 Лимиты / Подписка` {escape_markdown('- информация о ваших лимитах.', version=2)}\n"
        f"`/help` {escape_markdown(' или кнопка ', version=2)}`❓ Помощь` {escape_markdown('- это сообщение.', version=2)}\n\n"
        f"{escape_markdown('Просто отправьте свой вопрос или задание боту!', version=2)}"
    )
    try:
        await update.message.reply_text(help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        await update.message.reply_text(
            "Я ИИ-бот. Команды: /start, /mode, /model, /usage, /help. Используйте кнопки.", 
            reply_markup=get_main_reply_keyboard()
        )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Обязательно ответить на коллбэк
    data = query.data
    user_id = query.from_user.id
    message_to_edit = query.message 
    new_text = ""
    plain_text_fallback = ""

    if data.startswith("set_mode_"):
        mode_key = data.split("set_mode_")[1]
        if mode_key in AI_MODES:
            context.user_data['current_ai_mode'] = mode_key
            mode_details = AI_MODES[mode_key]
            new_text = f"Режим изменен на: *{escape_markdown(mode_details['name'],version=2)}*.\n{escape_markdown(mode_details['welcome'],version=2)}"
            plain_text_fallback = f"Режим изменен на: {mode_details['name']}.\n{mode_details['welcome']}"
            logger.info(f"User {user_id} changed AI mode to {mode_key}")
        else:
            new_text = escape_markdown("Ошибка: Такой режим не найден.", version=2)
            plain_text_fallback = "Ошибка: Такой режим не найден."
    
    elif data.startswith("set_model_"):
        model_key_from_callback = data.split("set_model_")[1] # Это ключ из AVAILABLE_TEXT_MODELS
        if model_key_from_callback in AVAILABLE_TEXT_MODELS:
            selected_model_config = AVAILABLE_TEXT_MODELS[model_key_from_callback]
            context.user_data['selected_model_id'] = selected_model_config["id"]
            context.user_data['selected_api_type'] = selected_model_config["api_type"] # Сохраняем тип API

            model_name_md = escape_markdown(selected_model_config['name'], version=2)
            
            # Отображение лимита для новой выбранной модели
            _, limit_msg_check, current_c = check_and_log_request_attempt(user_id, model_key_from_callback, context)
            actual_l = get_user_actual_limit_for_model(user_id, model_key_from_callback, context)
            limit_info_md = f"\n{escape_markdown(f'Лимит: {current_c}/{actual_l} в день.', version=2)}"
            if "Вы достигли" in limit_msg_check:
                limit_info_md = f"\n{escape_markdown(limit_msg_check.splitlines()[0],version=2)}"


            new_text = f"Модель изменена на: *{model_name_md}*.{limit_info_md}"
            plain_text_fallback = f"Модель изменена на: {selected_model_config['name']}. Лимит: {current_c}/{actual_l} в день."
            logger.info(f"User {user_id} changed AI model to key: {model_key_from_callback} (ID: {selected_model_config['id']}, API: {selected_model_config['api_type']})")
        else:
            new_text = escape_markdown("Ошибка: Такая модель не найдена.", version=2)
            plain_text_fallback = "Ошибка: Такая модель не найдена."
            
    if new_text:
        try:
            # Удаляем инлайн-клавиатуру после выбора
            await message_to_edit.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None)
        except telegram.error.BadRequest:
            logger.warning(f"Failed to edit message with MarkdownV2 in button_callback. Sending plain text. Text was: {new_text}")
            await message_to_edit.edit_text(text=plain_text_fallback, reply_markup=None)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.info(f"Received message from user {user_id}: '{user_message}'")

    current_model_key = get_current_model_key(context) # Получаем ключ текущей модели
    selected_model_details = AVAILABLE_TEXT_MODELS[current_model_key] # Полная конфигурация модели

    # --- ПРОВЕРКА ЛИМИТА ЗАПРОСОВ ---
    can_request, limit_message, _ = check_and_log_request_attempt(user_id, current_model_key, context)
    if not can_request:
        await update.message.reply_text(limit_message, reply_markup=get_main_reply_keyboard())
        logger.info(f"User {user_id} limit exceeded for model_key {current_model_key}: {limit_message}")
        return
    # --- КОНЕЦ ПРОВЕРКИ ЛИМИТА ---

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    current_mode_details = get_current_mode_details(context)
    system_prompt_text = current_mode_details["prompt"]
    reply_text = "Произошла ошибка при обработке вашего запроса." # Ответ по умолчанию

    api_type = selected_model_details.get("api_type")

    request_successful = False # Флаг успешности запроса к API

    if api_type == "google_genai":
        if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
            reply_text = "Ключ API для моделей Google Gemini не настроен. Обратитесь к администратору."
        else:
            try:
                model_id_for_api = selected_model_details["id"]
                active_model = genai.GenerativeModel(model_id_for_api)
                logger.info(f"Using Google genai model: {model_id_for_api} for user {user_id}")
                
                generation_config = genai.types.GenerationConfig(temperature=0.75) # max_output_tokens можно добавить при необходимости
                
                chat_history = [
                    {"role": "user", "parts": [system_prompt_text]},
                    {"role": "model", "parts": ["Понял. Я готов помочь."]}
                ]
                chat = active_model.start_chat(history=chat_history)
                response_gen = await chat.send_message_async(user_message, generation_config=generation_config)
                
                api_reply_text_google = response_gen.text

                prompt_tokens, completion_tokens = 0, 0
                if hasattr(response_gen, 'usage_metadata') and response_gen.usage_metadata:
                    usage = response_gen.usage_metadata
                    prompt_tokens = usage.prompt_token_count
                    completion_tokens = usage.candidates_token_count
                    logger.info(f"Google API Usage for {model_id_for_api}: Prompt Tokens: {prompt_tokens}, Completion Tokens: {completion_tokens}")

                if not api_reply_text_google or not api_reply_text_google.strip():
                    block_reason_msg = ""
                    if hasattr(response_gen, 'prompt_feedback') and response_gen.prompt_feedback and response_gen.prompt_feedback.block_reason:
                        block_reason_msg = f" Причина: {response_gen.prompt_feedback.block_reason}."
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
                    reply_text = "Ошибка: API ключ для Google недействителен. Обратитесь к администратору."
                elif "billing account" in error_message or "enable billing" in error_message:
                    reply_text = "Проблема с биллингом для API Google. Обратитесь к администратору."
                elif "resource has been exhausted" in error_message: # Квота
                    reply_text = "Исчерпана квота для Google API. Попробуйте позже или обратитесь к администратору."
                # Добавить другие специфичные обработки ошибок Google API
            except Exception as e_general_google:
                logger.error(f"General error processing Google Gemini model {selected_model_details['id']}: {str(e_general_google)}\n{traceback.format_exc()}")
                reply_text = "Внутренняя ошибка при обработке запроса к Google Gemini."

    elif api_type == "custom_http_api":
        api_key_var_name = selected_model_details.get("api_key_var_name")
        actual_api_key = globals().get(api_key_var_name) # Получаем значение ключа по имени переменной

        if not actual_api_key or "sk-" not in actual_api_key: # Простая проверка формата "sk-"
            reply_text = f"Ключ API для '{selected_model_details['name']}' не настроен корректно."
            logger.warning(f"API key from var '{api_key_var_name}' is missing or invalid for Custom API.")
        else:
            endpoint = selected_model_details["endpoint"]
            model_id_for_payload = selected_model_details["id"]

            messages_payload = [
                {"role": "user", "content": system_prompt_text},
                {"role": "user", "content": user_message}
            ]
            payload = {
                "model": model_id_for_payload,
                "messages": messages_payload,
                "is_sync": True,
                "temperature": 0.75
            }
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {actual_api_key}'
            }
            logger.info(f"Sending request to Custom HTTP API. Endpoint: {endpoint}, Model: {model_id_for_payload}")

            try:
                api_response = requests.post(endpoint, json=payload, headers=headers, timeout=90)
                api_response.raise_for_status()
                response_data = api_response.json()
                logger.debug(f"Custom API raw response: {json.dumps(response_data, ensure_ascii=False, indent=2)}")

                # Адаптируйте парсинг под ваш Custom API. Этот пример предполагает структуру как у gen-api.ru
                if response_data.get("status") == "success" and "output" in response_data:
                    api_reply_text_custom = response_data.get("output")
                    if not api_reply_text_custom or not api_reply_text_custom.strip():
                        reply_text = f"ИИ ({selected_model_details['name']}) вернул пустой ответ."
                    else:
                        reply_text = api_reply_text_custom
                        request_successful = True
                elif "detail" in response_data:
                    reply_text = f"Ошибка Custom API ({selected_model_details['name']}): {response_data['detail']}"
                else: # Если структура ответа другая или нет явного статуса/output
                    # Пытаемся извлечь текст, если он просто лежит в корне или в известном поле
                    possible_text = response_data.get("text") or response_data.get("message") or response_data.get("completion")
                    if isinstance(possible_text, str) and possible_text.strip():
                        reply_text = possible_text
                        request_successful = True
                        logger.info("Extracted text from custom API response from a non-standard field.")
                    else:
                        reply_text = f"Некорректный или пустой ответ от Custom API ({selected_model_details['name']})."
                        logger.warning(f"Unexpected response structure or empty content from Custom API: {response_data}")
                
            except requests.exceptions.HTTPError as e_http:
                error_content = "No details in response."
                try: error_content = e_http.response.json()
                except json.JSONDecodeError: error_content = e_http.response.text
                logger.error(f"HTTPError for Custom API '{selected_model_details['name']}': {e_http}. Status: {e_http.response.status_code}. Content: {error_content}")
                reply_text = f"Ошибка сети ({e_http.response.status_code}) при обращении к '{selected_model_details['name']}'."
            except requests.exceptions.RequestException as e_req_custom:
                logger.error(f"RequestException for Custom API '{selected_model_details['name']}': {e_req_custom}")
                reply_text = f"Ошибка сети при обращении к '{selected_model_details['name']}'. Попробуйте позже."
            except Exception as e_custom_proc:
                logger.error(f"Error processing Custom API response for '{selected_model_details['name']}': {e_custom_proc}\n{traceback.format_exc()}")
                reply_text = f"Ошибка обработки ответа от '{selected_model_details['name']}'."
    else:
        reply_text = f"Неизвестный тип API: {api_type}"
        logger.error(f"Unsupported API type: {api_type} for model_key {current_model_key}")

    if request_successful and selected_model_details.get("is_limited"):
        increment_request_count(user_id, current_model_key, context)
            
    reply_text_for_sending, was_truncated = smart_truncate(reply_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    await update.message.reply_text(reply_text_for_sending, reply_markup=get_main_reply_keyboard())
    if request_successful:
        logger.info(f"Sent successful response for model_key {current_model_key}. Truncated: {was_truncated}")


# --- Настройка команд бота ---
async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "🚀 Перезапуск / Инфо"),
        BotCommand("mode", "🧠 Сменить режим ИИ"),
        BotCommand("model", "⚙️ Выбрать модель ИИ"),
        BotCommand("usage", "📊 Лимиты / Подписка"),
        BotCommand("help", "ℹ️ Помощь"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")


async def main():
    if "YOUR_TELEGRAM_TOKEN" in TOKEN or not TOKEN:
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set or is a placeholder.")
        return
    # Проверки ключей API выполняются при их использовании или при конфигурации genai

    persistence = PicklePersistence(filepath="bot_user_data.pkl") # Используем .pkl для ясности

    application = Application.builder().token(TOKEN).persistence(persistence).build()

    await set_bot_commands(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mode", select_mode_command))
    application.add_handler(CommandHandler("model", select_model_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.Text(["🤖 Режим ИИ"]), select_mode_command))
    application.add_handler(MessageHandler(filters.Text(["⚙️ Модель ИИ"]), select_model_command))
    application.add_handler(MessageHandler(filters.Text(["📊 Лимиты / Подписка"]), usage_command))
    application.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Starting bot with multiple Gemini models and API support...")
    await application.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e_main:
        logger.critical(f"Critical error in main execution: {e_main}\n{traceback.format_exc()}")
