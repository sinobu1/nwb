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
from datetime import datetime, timedelta # ИЗМЕНЕНО: добавлен timedelta

nest_asyncio.apply()
# ИЗМЕНЕНО: Уровень логирования DEBUG для отладки
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")

YOUR_ADMIN_ID = 489230152  # ИЗМЕНЕНО: ВАШ Telegram ID для админ-команд

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000

# Лимиты по умолчанию
DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 10 # Для базовой бесплатной модели
DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 1    # Бесплатных проб для Custom Pro
DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 5 # Для подписчиков на Custom Pro (пример)
DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 15 # Для подписчиков на Google Flash Preview

# --- РЕЖИМЫ РАБОТЫ ИИ ---
AI_MODES = {
    "universal_ai_basic": { # ИЗМЕНЕНО: для базовых моделей
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
     "gemini_pro_custom_mode": { # ИЗМЕНЕНО: Новый специальный режим/промпт для вашей Pro модели
        "name": "🤖 Продвинутый Ассистент", # Имя для пользователя (можно сделать более общим)
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент. " # Убрано "от Google", если Custom API не от Google
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
DEFAULT_AI_MODE_KEY = "universal_ai_basic" # ИЗМЕНЕНО: на новый ключ базового режима

# --- МОДЕЛИ ИИ ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "⚡️ Gemini 2.0 Flash (Базовый)",
        "id": "gemini-2.0-flash",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "daily_free", # Тип лимита для простого ежедневного бесплатного доступа
        "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY,
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "💨 Gemini 2.5 Flash Preview (Google)",
        "id": "gemini-2.5-flash-preview-04-17",
        "api_type": "google_genai",
        "is_limited": True,
        "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": 3, # ИЗМЕНЕНО: для примера
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY, # Лимит для подписчиков (например, уровня "standard_sub")
        "cost_category": "google_flash_preview_flex"
    },
    # ИЗМЕНЕНО: Блок для gemini-2.5-pro-preview-05-06 УДАЛЕН
    "custom_api_gemini_2_5_pro": {
        "name": "🌟 Gemini 2.5 Pro (Платный)",
        "id": "gemini-2.5-pro-preview-03-25",
        "api_type": "custom_http_api",
        "endpoint": CUSTOM_GEMINI_PRO_ENDPOINT,
        "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True,
        "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY, # 1 бесплатная проба
        "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY, # 5 для подписчиков
        "cost_category": "custom_api_pro_paid",
        "pricing_info": { # ИЗМЕНЕНО: Информация для команды /subscribe
            "cost_per_request_rub_approx": 1.50, # ОБНОВИТЕ ЭТО ЗНАЧЕНИЕ ПОСЛЕ ТЕСТА С НОВЫМ ПРОМПТОМ!
            "subscription_price_rub_monthly": 499, # Пример цены
            "subscription_duration_days": 30,
            "description": "Доступ к продвинутой модели Gemini 2.5 Pro, 5 запросов в день."
        }
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
    # ИЗМЕНЕНО: Если выбрана custom_api_gemini_2_5_pro, принудительно используем ее спец. режим
    current_model_key = get_current_model_key(context)
    if current_model_key == "custom_api_gemini_2_5_pro":
        # Проверяем, существует ли специальный режим для этой модели
        if "gemini_pro_custom_mode" in AI_MODES:
            return AI_MODES["gemini_pro_custom_mode"]
        else: # Фоллбэк, если режим не определен
            logger.warning("Dedicated mode 'gemini_pro_custom_mode' not found. Falling back to default AI mode.")
            return AI_MODES.get(DEFAULT_AI_MODE_KEY) # Или другой фоллбэк

    # Для остальных моделей берем выбранный пользователем режим
    mode_key = context.user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

def get_current_model_key(context: ContextTypes.DEFAULT_TYPE) -> str:
    selected_id = context.user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    # ИЗМЕНЕНО: API тип теперь тоже важен для уникальности, если ID могут совпадать
    selected_api_type = context.user_data.get('selected_api_type')
    if not selected_api_type: # Если тип API не сохранен, пытаемся определить по ID
        for key_fallback, info_fallback in AVAILABLE_TEXT_MODELS.items():
            if info_fallback["id"] == selected_id:
                selected_api_type = info_fallback.get("api_type")
                # Сохраняем найденный тип API для будущих вызовов
                context.user_data['selected_api_type'] = selected_api_type
                break
    
    if not selected_api_type: # Если так и не смогли определить
         logger.warning(f"API type for selected_model_id {selected_id} is not stored and couldn't be inferred. Falling back to default model key.")
         return DEFAULT_MODEL_KEY

    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id and info.get("api_type") == selected_api_type:
            return key
            
    logger.warning(f"Could not find key for model_id '{selected_id}' and api_type '{selected_api_type}'. Falling back to default.")
    return DEFAULT_MODEL_KEY


def get_selected_model_details(context: ContextTypes.DEFAULT_TYPE) -> dict:
    model_key = get_current_model_key(context)
    return AVAILABLE_TEXT_MODELS[model_key]

def get_current_model_display_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return get_selected_model_details(context)["name"]

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str): # Добавлена проверка типа
        logger.warning(f"smart_truncate received non-string input: {type(text)}. Returning as is.")
        return str(text), False # Пытаемся преобразовать в строку
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
        [KeyboardButton("📊 Лимиты / Подписка"), KeyboardButton("❓ Помощь")]
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
            valid_until_dt = datetime.strptime(user_subscription_details['valid_until'], "%Y-%m-%d")
            if datetime.now().date() <= valid_until_dt.date(): # ИЗМЕНЕНО: Сравниваем только даты
                current_sub_level = user_subscription_details.get('level')
            else:
                logger.info(f"Subscription for user {user_id} (level {user_subscription_details.get('level')}) expired on {user_subscription_details['valid_until']}.")
                # Можно удалить истекшую подписку
                # current_sub_level останется None
        except ValueError:
            logger.error(f"Invalid date format for subscription for user {user_id}: {user_subscription_details['valid_until']}")

    limit_type = model_config.get("limit_type")
    actual_limit = 0

    if limit_type == "daily_free": # Для google_gemini_2_0_flash
        actual_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free": # Для google_gemini_2_5_flash_preview
        if current_sub_level == "standard_google" or current_sub_level == "premium_all": # Пример уровней
            actual_limit = model_config.get("subscription_daily_limit", DEFAULT_PRO_SUBSCRIPTION_REQUESTS_DAILY) # Исправлено
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro": # Для custom_api_gemini_2_5_pro
        if current_sub_level == "custom_pro_access" or current_sub_level == "premium_all":
            actual_limit = model_config.get("subscription_daily_limit", DEFAULT_CUSTOM_API_SUBSCRIPTION_REQUESTS_DAILY)
        else:
            actual_limit = model_config.get("limit_if_no_subscription", 0)
    else:
        actual_limit = model_config.get("limit", float('inf')) if not model_config.get("is_limited", False) else 0
        if model_config.get("is_limited") and actual_limit == float('inf'):
            logger.warning(f"Model {model_key} is limited but actual_limit is infinity. Setting to 0.")
            actual_limit = 0
    return actual_limit

def check_and_log_request_attempt(user_id: int, model_key: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str, int]:
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"):
        return True, "", 0
    
    # ИЗМЕНЕНО: используем context.bot_data для хранения общих счетчиков пользователей
    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': '', 'count': 0})

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
    today_str = datetime.now().strftime("%Y-%m-%d")
    # ИЗМЕНЕНО: используем context.bot_data
    all_daily_counts = context.bot_data.setdefault('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.setdefault(user_id, {})
    model_daily_usage = user_model_counts.setdefault(model_key, {'date': today_str, 'count': 0})
    
    if model_daily_usage['date'] != today_str: # Дополнительная проверка на смену дня
        model_daily_usage['date'] = today_str
        model_daily_usage['count'] = 0
        
    model_daily_usage['count'] += 1
    logger.info(f"User {user_id} request count for {model_key} incremented to {model_daily_usage['count']}")


# --- Функция для проверки статуса асинхронной задачи ---
async def poll_task_status(request_id: int, api_key: str, endpoint: str) -> dict:
    status_url = f"{endpoint}/{request_id}"  # Предполагаемый эндпоинт для проверки статуса
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    for _ in range(10):  # Проверять до 10 раз
        try:
            response = requests.get(status_url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Polled task status for request_id {request_id}: {json.dumps(data, ensure_ascii=False)}")
            if data.get("status") == "success":
                return data
            elif data.get("status") in ["error", "failed"]:
                return {"status": "error", "detail": data.get("detail", "Task failed")}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error polling task status for request_id {request_id}: {str(e)}")
            await asyncio.sleep(5)
        await asyncio.sleep(5)  # Ждать 5 секунд перед следующей попыткой
    return {"status": "error", "detail": "Task timeout"}

# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Инициализация данных пользователя, если их нет
    context.user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    if 'selected_model_id' not in context.user_data: # Устанавливаем модель по умолчанию только если ее нет
        default_model_conf = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
        context.user_data['selected_model_id'] = default_model_conf["id"]
        context.user_data['selected_api_type'] = default_model_conf["api_type"]

    # Инициализация глобальных данных бота (если они не созданы PicklePersistence)
    context.bot_data.setdefault('user_subscriptions', {})
    context.bot_data.setdefault('all_user_daily_counts', {})
    
    # Для информации в стартовом сообщении
    current_mode_name = get_current_mode_details(context)['name'] # get_current_mode_details теперь учитывает модель
    current_model_name = get_current_model_display_name(context)
    
    greeting = escape_markdown("Привет! Я многофункциональный ИИ-бот.", version=2)
    mode_line = f"{escape_markdown('Текущий режим: ', version=2)}*{escape_markdown(current_mode_name, version=2)}*"
    model_line = f"{escape_markdown('Текущая модель: ', version=2)}*{escape_markdown(current_model_name, version=2)}*"
    
    current_model_key_for_start = get_current_model_key(context)
    _, limit_msg_check, current_count_for_start = check_and_log_request_attempt(user_id, current_model_key_for_start, context)
    actual_limit_for_model_start = get_user_actual_limit_for_model(user_id, current_model_key_for_start, context)
    limit_info_line = f"{escape_markdown(f'Лимит для текущей модели: {current_count_for_start}/{actual_limit_for_model_start} в день.', version=2)}"
    if "Вы достигли" in limit_msg_check: 
        limit_info_line = escape_markdown(limit_msg_check.split('\n')[0], version=2)

    you_can = escape_markdown("Вы можете:", version=2)
    action1 = escape_markdown("▫️ Задавать мне вопросы или давать задания.", version=2)
    action2 = f"▫️ Сменить режим ИИ (`/mode` или кнопка)"
    action3 = f"▫️ Выбрать другую модель (`/model` или кнопка)"
    action4 = f"▫️ Узнать о лимитах и подписке (`/usage` или кнопка)"
    action5 = f"▫️ Посмотреть доступные подписки (`/subscribe`)" # ДОБАВЛЕНО
    action6 = f"▫️ Получить помощь (`/help`)"
    invitation = escape_markdown("Просто напишите ваш запрос!", version=2)

    text_to_send = (
        f"{greeting}\n\n"
        f"{mode_line}\n"
        f"{model_line}\n"
        f"{limit_info_line}\n\n"
        f"{you_can}\n"
        f"{action1}\n{action2}\n{action3}\n{action4}\n{action5}\n{action6}\n\n" # ИЗМЕНЕНО
        f"{invitation}"
    )
    try:
        await update.message.reply_text(text_to_send, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest: 
        plain_text_version = (
            f"Привет! Я многофункциональный ИИ-бот.\n\n"
            f"Режим: {current_mode_name}\nМодель: {current_model_name}\n"
            f"Лимит: {current_count_for_start}/{actual_limit_for_model_start} в день.\n\n"
            "Вы можете:\n"
            "▫️ Задавать вопросы.\n▫️ /mode - сменить режим\n▫️ /model - сменить модель\n"
            "▫️ /usage - лимиты\n▫️ /subscribe - подписки\n▫️ /help - помощь\n\n"
            "Ваш запрос?"
        )
        await update.message.reply_text(plain_text_version, reply_markup=get_main_reply_keyboard())
    logger.info(f"Start command processed for user {user_id}.")


async def select_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ИЗМЕНЕНО: не показывать "gemini_pro_custom_mode" в общем списке режимов,
    # так как он выбирается автоматически для custom_api_gemini_2_5_pro
    keyboard = []
    for key, details in AI_MODES.items():
        if key != "gemini_pro_custom_mode": # Скрываем специальный режим
            keyboard.append([InlineKeyboardButton(details["name"], callback_data=f"set_mode_{key}")])
    
    if not keyboard: # Если вдруг все режимы скрыты
         await update.message.reply_text('В данный момент нет доступных режимов для выбора.', reply_markup=get_main_reply_keyboard())
         return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите режим работы для ИИ:', reply_markup=reply_markup)


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
    
    display_sub_level = "Нет"
    # ИЗМЕНЕНО: Отображение уровня подписки
    if sub_level_key:
        if sub_level_key == "pro_google_access": display_sub_level = "Pro Google"
        elif sub_level_key == "custom_pro_access": display_sub_level = "Pro Custom API"
        elif sub_level_key == "full_access": display_sub_level = "Полный доступ"
        else: display_sub_level = str(sub_level_key) # Если вдруг другой ключ

        if sub_valid_str:
            try:
                valid_until_dt = datetime.strptime(sub_valid_str, "%Y-%m-%d")
                if datetime.now().date() > valid_until_dt.date():
                    display_sub_level += " (истекла)"
            except ValueError:
                pass # Оставляем как есть, если дата неверная

    usage_text = f"ℹ️ **Информация о ваших лимитах и подписке**\n\n"
    usage_text += f"Текущий уровень подписки: *{escape_markdown(display_sub_level, version=2)}*\n"
    if sub_level_key and sub_valid_str and not "(истекла)" in display_sub_level :
        usage_text += f"Действительна до: *{escape_markdown(sub_valid_str, version=2)}*\n"
    usage_text += "\n"

    usage_text += "Ежедневные лимиты запросов по моделям:\n"
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            _, _, current_c = check_and_log_request_attempt(user_id, model_k, context)
            actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
            usage_text += f"▫️ {escape_markdown(model_c['name'], version=2)}: *{current_c}/{actual_l}*\n"
    
    usage_text += f"\n{escape_markdown('Для оформления или продления подписки воспользуйтесь командой /subscribe', version=2)}"
    
    try:
        await update.message.reply_text(usage_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        plain_usage_text = f"Подписка: {display_sub_level} (до {sub_valid_str})\nЛимиты:\n"
        for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
             if model_c.get("is_limited"):
                _, _, current_c = check_and_log_request_attempt(user_id, model_k, context)
                actual_l = get_user_actual_limit_for_model(user_id, model_k, context)
                plain_usage_text += f"- {model_c['name']}: {current_c}/{actual_l}\n"
        plain_usage_text += "\nКоманда для подписки: /subscribe"
        await update.message.reply_text(plain_usage_text, reply_markup=get_main_reply_keyboard())

# ДОБАВЛЕНО: Команда для информации о подписках
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💎 **Информация о доступных подписках**\n\n"
    
    # Информация о подписке на Custom Pro API
    custom_pro_key = "custom_api_gemini_2_5_pro"
    if custom_pro_key in AVAILABLE_TEXT_MODELS:
        config = AVAILABLE_TEXT_MODELS[custom_pro_key]
        pricing = config.get("pricing_info")
        if pricing:
            text += f"✨ **Подписка '{escape_markdown(config['name'], version=2)}'**\n"
            text += f"   ▫️ {escape_markdown(str(config.get('subscription_daily_limit', 'N/A')), version=2)} запросов в день\n"
            if pricing.get('description'):
                 text += f"   ▫️ {escape_markdown(pricing['description'], version=2)}\n"
            text += f"   ▫️ Стоимость: *{escape_markdown(str(pricing.get('subscription_price_rub_monthly', 'N/A')), version=2)} ₽ / {escape_markdown(str(pricing.get('subscription_duration_days', 30)), version=2)} дней*\n"
            text += f"   ▫️ Для оформления: свяжитесь с администратором (контакт в /help или описании бота).\n\n"

    # Можно добавить другие уровни подписки, например, для Google Pro моделей
    # ...

    text += escape_markdown("После оплаты сообщите администратору ваш ID для активации: ", version=2) + f"`{update.effective_user.id}`"
    
    try:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest as e_br:
        logger.error(f"Error sending subscribe_info_command with Markdown: {e_br}")
        await update.message.reply_text("Информация о подписках временно недоступна. Попробуйте позже.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text_md = (
        f"{escape_markdown('🤖 Я многофункциональный ИИ-бот на базе моделей Gemini.', version=2)}\n\n"
        f"{escape_markdown('Основные команды:', version=2)}\n"
        f"`/start` {escape_markdown('- инфо и настройки.', version=2)}\n"
        f"`/mode` {escape_markdown(' или кнопка ', version=2)}`🤖 Режим ИИ` {escape_markdown('- смена режима ИИ.', version=2)}\n"
        f"`/model` {escape_markdown(' или кнопка ', version=2)}`⚙️ Модель ИИ` {escape_markdown('- выбор модели Gemini.', version=2)}\n"
        f"`/usage` {escape_markdown(' или кнопка ', version=2)}`📊 Лимиты / Подписка` {escape_markdown('- ваши лимиты.', version=2)}\n"
        f"`/subscribe` {escape_markdown('- информация о подписках.', version=2)}\n" # ДОБАВЛЕНО
        f"`/help` {escape_markdown(' или кнопка ', version=2)}`❓ Помощь` {escape_markdown('- это сообщение.', version=2)}\n\n"
        f"{escape_markdown('Просто отправьте свой вопрос или задание боту!', version=2)}"
    )
    try:
        await update.message.reply_text(help_text_md, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_main_reply_keyboard())
    except telegram.error.BadRequest:
        await update.message.reply_text(
            "Я ИИ-бот. Команды: /start, /mode, /model, /usage, /subscribe, /help.", 
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
        if mode_key in AI_MODES and mode_key != "gemini_pro_custom_mode": # ИЗМЕНЕНО: не даем выбрать спец.режим напрямую
            context.user_data['current_ai_mode'] = mode_key
            mode_details = AI_MODES[mode_key]
            new_text = f"Режим изменен на: *{escape_markdown(mode_details['name'],version=2)}*\n{escape_markdown(mode_details['welcome'],version=2)}"
            plain_text_fallback = f"Режим изменен на: {mode_details['name']}.\n{mode_details['welcome']}"
            logger.info(f"User {user_id} changed AI mode to {mode_key}")
        elif mode_key == "gemini_pro_custom_mode":
             new_text = escape_markdown("Этот режим выбирается автоматически с соответствующей моделью.", version=2)
             plain_text_fallback = "Этот режим выбирается автоматически."
        else:
            new_text = escape_markdown("Ошибка: Такой режим не найден.", version=2)
            plain_text_fallback = "Ошибка: Такой режим не найден."
    
    elif data.startswith("set_model_"):
        model_key_from_callback = data.split("set_model_")[1]
        if model_key_from_callback in AVAILABLE_TEXT_MODELS:
            selected_model_config = AVAILABLE_TEXT_MODELS[model_key_from_callback]
            context.user_data['selected_model_id'] = selected_model_config["id"]
            context.user_data['selected_api_type'] = selected_model_config["api_type"] # Сохраняем тип API

            model_name_md = escape_markdown(selected_model_config['name'], version=2)
            
            _, limit_msg_check, current_c = check_and_log_request_attempt(user_id, model_key_from_callback, context)
            actual_l = get_user_actual_limit_for_model(user_id, model_key_from_callback, context)
            
            # ИЗМЕНЕНО: Убрал точку из строки лимита для Markdown
            limit_str_escaped = escape_markdown(f'Лимит: {current_c}/{actual_l} в день', version=2)
            limit_info_md = f"\n{limit_str_escaped}"
            if "Вы достигли" in limit_msg_check: # Если лимит исчерпан, показываем сообщение об этом
                limit_info_md = f"\n{escape_markdown(limit_msg_check.splitlines()[0],version=2)}"

            new_text = f"Модель изменена на: *{model_name_md}*\\.{limit_info_md}" # Эскейпим точку после имени модели
            plain_text_fallback = f"Модель изменена на: {selected_model_config['name']}. Лимит: {current_c}/{actual_l} в день."
            logger.info(f"User {user_id} changed AI model to key: {model_key_from_callback} (ID: {selected_model_config['id']}, API: {selected_model_config['api_type']})")
        else:
            new_text = escape_markdown("Ошибка: Такая модель не найдена.", version=2)
            plain_text_fallback = "Ошибка: Такая модель не найдена."
            
    if new_text:
        try:
            await message_to_edit.edit_text(text=new_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=None)
        except telegram.error.BadRequest as e_md:
            logger.warning(f"Failed to edit message with MarkdownV2 in button_callback: {e_md}. Sending plain text. Text was: {new_text}")
            await message_to_edit.edit_text(text=plain_text_fallback, reply_markup=None)

# ИЗМЕНЕНО: Команда для админа для выдачи подписки
async def grant_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_ADMIN_ID:
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    try:
        args = context.args
        if len(args) != 3:
            await update.message.reply_text(
                "Использование: /grantsub <user_id> <level_key> <days>\n"
                "Доступные уровни (пример): standard_google, custom_pro_access, full_access, none (для сброса)" 
            ) # ИЗМЕНЕНО: Уточнил примеры уровней
            return
            
        target_user_id = int(args[0])
        sub_level_key = args[1].lower() 
        days = int(args[2])

        # Пример ключей подписки (вы можете определить их по-своему)
        defined_subscription_levels = ["standard_google", "custom_pro_access", "full_access", "none"] 
        if sub_level_key not in defined_subscription_levels:
            await update.message.reply_text(f"Неизвестный уровень подписки: {sub_level_key}. Доступны: {', '.join(defined_subscription_levels)}")
            return

        all_user_subscriptions = context.bot_data.setdefault('user_subscriptions', {})
        
        if sub_level_key == "none" or days <= 0: # ИЗМЕНЕНО: добавил days <=0 для сброса
             all_user_subscriptions[target_user_id] = {'level': None, 'valid_until': None}
             await update.message.reply_text(f"Подписка для пользователя {target_user_id} сброшена.")
             logger.info(f"Admin {update.effective_user.id} reset subscription for user {target_user_id}.")
        else:
            valid_until_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            all_user_subscriptions[target_user_id] = {
                'level': sub_level_key,
                'valid_until': valid_until_date
            }
            await update.message.reply_text(f"Пользователю {target_user_id} выдана подписка '{sub_level_key}' на {days} дней (до {valid_until_date}).")
            logger.info(f"Admin {update.effective_user.id} granted subscription '{sub_level_key}' for {days} days to user {target_user_id}.")
        
        # Принудительное сохранение данных, если необходимо (обычно PicklePersistence делает это при остановке)
        # await context.application.persist_bot_data() # или flush()

    except (IndexError, ValueError) as e:
        await update.message.reply_text(f"Ошибка в аргументах: {e}\nИспользование: /grantsub <user_id> <level_key> <days>")
    except Exception as e_grant:
        logger.error(f"Error in grant_subscription_command: {e_grant}\n{traceback.format_exc()}")
        await update.message.reply_text(f"Произошла ошибка при выдаче подписки: {e_grant}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.effective_user.id if update.effective_user else "UnknownUser"
    logger.debug(f"handle_message: Received message from user {user_id}: '{user_message}'") # ИЗМЕНЕНО: на debug

    if not user_message or not user_message.strip(): # Проверка на пустое сообщение
        await update.message.reply_text("Пожалуйста, отправьте непустой запрос.", reply_markup=get_main_reply_keyboard())
        return

    current_model_key = get_current_model_key(context)
    selected_model_details = AVAILABLE_TEXT_MODELS[current_model_key]
    
    # --- ВЫБОР СИСТЕМНОГО ПРОМПТА ---
    # Этот блок должен быть ПЕРЕД проверкой лимитов, если разные промпты могут иметь разную "стоимость"
    # Но для простоты лимитов, он пока здесь. Для Custom Pro он уже учтен в get_current_mode_details
    system_prompt_text = get_current_mode_details(context)["prompt"]
    logger.debug(f"Using system prompt for mode: {get_current_mode_details(context)['name']}")


    # --- ПРОВЕРКА ЛИМИТА ЗАПРОСОВ ---
    can_request, limit_message, _ = check_and_log_request_attempt(user_id, current_model_key, context)
    if not can_request:
        await update.message.reply_text(limit_message, reply_markup=get_main_reply_keyboard())
        logger.info(f"User {user_id} limit REJECTED for model_key {current_model_key}: {limit_message}")
        return
    logger.info(f"User {user_id} limit ACCEPTED for model_key {current_model_key}.")
    # --- КОНЕЦ ПРОВЕРКИ ЛИМИТА ---

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    reply_text = "Произошла ошибка при обработке вашего запроса." # Ответ по умолчанию
    api_type = selected_model_details.get("api_type")
    request_successful = False

    if api_type == "google_genai":
        if not GOOGLE_GEMINI_API_KEY or "YOUR_GOOGLE_GEMINI_API_KEY" in GOOGLE_GEMINI_API_KEY or "AIzaSy" not in GOOGLE_GEMINI_API_KEY:
            reply_text = "Ключ API для моделей Google Gemini не настроен. Обратитесь к администратору."
            logger.error("Google Gemini API key is not configured.")
        else:
            try:
                model_id_for_api = selected_model_details["id"]
                active_model = genai.GenerativeModel(model_id_for_api) # ИЗМЕНЕНО: на model_id_for_api
                logger.info(f"Using Google genai model: {model_id_for_api} for user {user_id}")
                
                generation_config_params = {"temperature": 0.75}
                # if MAX_OUTPUT_TOKENS_GEMINI_LIB > 0: # Условие для max_output_tokens
                #    generation_config_params["max_output_tokens"] = MAX_OUTPUT_TOKENS_GEMINI_LIB
                generation_config = genai.types.GenerationConfig(**generation_config_params)
                
                chat_history = [
                    {"role": "user", "parts": [system_prompt_text]},
                    {"role": "model", "parts": ["Понял. Я готов помочь."]}
                ]
                chat = active_model.start_chat(history=chat_history)
                logger.debug(f"Sending to Google API. Model: {model_id_for_api}. System prompt length: {len(system_prompt_text)}, User message: {user_message[:100]}")
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
                elif "resource has been exhausted" in error_message: 
                    reply_text = "Исчерпана квота для Google API. Попробуйте позже или обратитесь к администратору."
                elif "user location" in error_message:
                     reply_text = "Модель недоступна в вашем регионе через Google API."

            except Exception as e_general_google:
                logger.error(f"General error processing Google Gemini model {selected_model_details['id']}: {str(e_general_google)}\n{traceback.format_exc()}")
                reply_text = "Внутренняя ошибка при обработке запроса к Google Gemini."

    elif api_type == "custom_http_api":
        api_key_var_name = selected_model_details.get("api_key_var_name")
        actual_api_key = globals().get(api_key_var_name) # Получаем ключ из глобальных переменных по имени

        if not actual_api_key or ("sk-" not in actual_api_key and "pk-" not in actual_api_key) : # Проверка на общий формат ключей
            reply_text = f"Ключ API для '{selected_model_details['name']}' не настроен корректно."
            logger.warning(f"API key from var '{api_key_var_name}' is missing or invalid for Custom API. Key: {str(actual_api_key)[:10]}...")
        else:
            endpoint = selected_model_details["endpoint"]
            model_id_for_payload_api = selected_model_details["id"]
            
            messages_payload = []
            # ИЗМЕНЕНО: Проверяем, поддерживает ли API роль "system" (пока предполагаем, что да, если не указано иное)
            # Либо жестко задаем формат, который точно работает с gen-api.ru
            # Для gen-api.ru, первый "user" - это системный, второй "user" - это юзерский
            # Но если API поддерживает "system", то лучше так:
            # messages_payload.append({"role": "system", "content": system_prompt_text})
            # messages_payload.append({"role": "user", "content": user_message})
            # Оставляем как в вашем рабочем варианте для gen-api.ru:
            messages_payload.append({"role": "user", "content": system_prompt_text})
            messages_payload.append({"role": "user", "content": user_message})


            payload = {
                "model": model_id_for_payload_api,
                "messages": messages_payload,
                "is_sync": True,
                # "callback_url": None, # Убрали, т.к. вызывало 422 ошибку ранее
                "temperature": selected_model_details.get("temperature", 0.75),
                "stream": False,
                "n": 1,
                "frequency_penalty": 0,
                "presence_penalty": 0,
                "top_p": 1,
                "response_format": json.dumps({"type": "text"}) 
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {actual_api_key}'
            }
            logger.info(f"Sending request to Custom HTTP API. Endpoint: {endpoint}, Model in payload: {model_id_for_payload_api}")
            logger.debug(f"Custom API Payload: {json.dumps(payload, ensure_ascii=False)}")

            try:
                api_response = requests.post(endpoint, json=payload, headers=headers, timeout=90)
                logger.debug(f"Custom API response status: {api_response.status_code}")
                response_data = {}
                try:
                    response_data = api_response.json()
                    logger.debug(f"Custom API response body (JSON): {json.dumps(response_data, ensure_ascii=False, indent=2)}")
                except json.JSONDecodeError as e_json:
                    logger.error(f"Custom API response body (not JSON or decode error): {api_response.text}. Error: {e_json}")
                    reply_text = f"Ошибка декодирования ответа от Custom API ({selected_model_details['name']})."
                    raise # Передаем ошибку выше, чтобы не считать запрос успешным

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
                                # Здесь можно добавить логику сохранения 'cost' в context.user_data или context.bot_data для аналитики
                                context.user_data.setdefault('api_costs', {})
                                context.user_data['api_costs'][datetime.now().isoformat()] = {'model': current_model_key, 'cost': cost }

                            req_id_resp = response_data.get("request_id")
                            model_resp = response_data.get("model")
                            logger.info(f"Custom API success: request_id={req_id_resp}, model_in_response='{model_resp}'")
                        else:
                            reply_text = f"ИИ ({selected_model_details['name']}) вернул пустой ответ в 'content'."
                            logger.warning(f"Custom API returned empty 'content' in message: {response_data}")
                    else:
                        reply_text = f"Некорректная структура 'message' или отсутствует 'content' в ответе от Custom API ({selected_model_details['name']})."
                        logger.warning(f"Custom API: 'message' or 'content' field missing in first choice: {first_choice}")
                elif "detail" in response_data: 
                    reply_text = f"Ошибка Custom API ({selected_model_details['name']}): {response_data['detail']}"
                    logger.error(f"Custom API returned error detail: {response_data['detail']}. Full response: {response_data}")
                else: 
                    reply_text = f"Неожиданная структура ответа от Custom API ({selected_model_details['name']}). Ответ ({api_response.status_code}) получен, но не распознан."
                    logger.warning(f"Unexpected response structure from Custom API ({api_response.status_code}). Full response: {json.dumps(response_data, ensure_ascii=False)}")
            
            except requests.exceptions.HTTPError as e_http:
                error_content_str = "No details in response text."
                try: error_content_json = e_http.response.json(); error_content_str = json.dumps(error_content_json)
                except json.JSONDecodeError: error_content_str = e_http.response.text
                
                logger.error(f"HTTPError for Custom API '{selected_model_details['name']}': {e_http}. Status: {e_http.response.status_code}. Content: {error_content_str}")
                if e_http.response.status_code == 402:
                    reply_text = f"Ошибка 402: Проблема с оплатой для Custom API ({selected_model_details['name']}). Обратитесь в поддержку API."
                elif e_http.response.status_code == 422:
                     reply_text = f"Ошибка 422: Неверный формат запроса к Custom API. Детали: {error_content_str}"
                else:
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


async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "🚀 Перезапуск / Инфо"),
        BotCommand("mode", "🧠 Сменить режим ИИ"),
        BotCommand("model", "⚙️ Выбрать модель ИИ"),
        BotCommand("usage", "📊 Лимиты / Подписка"),
        BotCommand("subscribe", "💎 Информация о подписках"), # ИЗМЕНЕНО
        BotCommand("help", "ℹ️ Помощь"),
    ]
    if YOUR_ADMIN_ID: # Добавляем админ-команду, если ID админа задан
        commands.append(BotCommand("grantsub", "🔑 Выдать подписку (админ)"))

    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")


async def main():
    if "YOUR_TELEGRAM_TOKEN" in TOKEN or not TOKEN or len(TOKEN.split(":")[0]) < 8: # ИЗМЕНЕНО: более строгая проверка токена
        logger.critical("CRITICAL: TELEGRAM_TOKEN is not set correctly or is a placeholder.")
        return
    
    persistence = PicklePersistence(filepath="bot_user_data.pkl") # Убедитесь, что директория доступна для записи

    application = Application.builder().token(TOKEN).persistence(persistence).build()

    await set_bot_commands(application)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mode", select_mode_command))
    application.add_handler(CommandHandler("model", select_model_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command)) # ДОБАВЛЕНО
    application.add_handler(CommandHandler("grantsub", grant_subscription_command)) # ДОБАВЛЕНО

    application.add_handler(MessageHandler(filters.Text(["🤖 Режим ИИ"]), select_mode_command))
    application.add_handler(MessageHandler(filters.Text(["⚙️ Модель ИИ"]), select_model_command))
    application.add_handler(MessageHandler(filters.Text(["📊 Лимиты / Подписка"]), usage_command))
    application.add_handler(MessageHandler(filters.Text(["❓ Помощь"]), help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info("Starting bot with multiple Gemini models and API support...")
    try:
        await application.initialize() # Инициализация перед запуском поллинга
        await application.updater.start_polling()
        await application.start()
        logger.info("Bot started successfully and is polling for updates.")
        # Для graceful shutdown (если нужно будет добавить обработку сигналов)
        # await application.updater.idle() # Это блокирующая операция
    except Exception as e_poll:
        logger.critical(f"Error during application startup or polling: {e_poll}\n{traceback.format_exc()}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
    except Exception as e_main_run:
        logger.critical(f"Critical error in asyncio.run(main()): {e_main_run}\n{traceback.format_exc()}")
