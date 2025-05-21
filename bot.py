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
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
import html # Для error_handler

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КЛЮЧИ API И ТОКЕНЫ ---
TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0") # ВАШ ТОКЕН БОТА
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "YOUR_GOOGLE_GEMINI_API_KEY_HERE")
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "YOUR_CUSTOM_GEMINI_PRO_KEY_HERE")
CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "YOUR_CUSTOM_GROK_3_KEY_HERE")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "YOUR_PAYMENT_PROVIDER_TOKEN_HERE") # ВАШ ПЛАТЕЖНЫЙ ТОКЕН
YOUR_ADMIN_ID = 489230152 # ВАШ ID АДМИНИСТРАТОРА

# --- КОНФИГУРАЦИЯ БОТА ---
MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
MAX_MESSAGE_LENGTH_TELEGRAM = 4000
MIN_AI_REQUEST_LENGTH = 4

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
NEWS_CHANNEL_USERNAME = "@timextech" # Замените на ваш канал, если нужно
NEWS_CHANNEL_LINK = "https://t.me/timextech" # Замените на ссылку на ваш канал
NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_grok_3" # ИЗМЕНЕНО: Бонус для Grok 3
NEWS_CHANNEL_BONUS_GENERATIONS = 1

# --- РЕЖИМЫ РАБОТЫ ИИ ---
AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент от Google."
            "Твоя цель — эффективно помогать пользователю с широким спектром задач."
            "Всегда будь вежлив, объективен, точен и полезен."
            "Оформляй ответ структурировано, используя абзацы и списки при необходимости."
        ),
        "welcome": "Активирован режим 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый (Gemini Pro)",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент."
            "Твоя задача — предоставлять точные, развернутые и полезные ответы."
            "Соблюдай вежливость и объективность."
        ),
        "welcome": "Активирован режим 'Продвинутый (Gemini Pro)'. Какой у вас запрос?"
    },
     "grok_3_custom_mode": {
        "name": "Продвинутый (Grok 3)",
        "prompt": (
            "Ты — Grok 3, мощный и немного эксцентричный ИИ-ассистент от xAI."
            "Отвечай точно, развернуто и с долей присущего тебе юмора, если это уместно."
        ),
        "welcome": "Активирован режим 'Продвинутый (Grok 3)'. Задавайте свои каверзные вопросы!"
    },
    "creative_helper": {
        "name": "Творческий",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Твоя миссия — вдохновлять и помогать в создании оригинального контента."
        ),
        "welcome": "Режим 'Творческий' к вашим услугам! Над какой задачей поработаем?"
    },
    "analyst": {
        "name": "Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик на базе Gemini, специализирующийся на анализе данных."
            "Твоя задача — предоставлять точные, логически обоснованные ответы."
        ),
        "welcome": "Режим 'Аналитик' активирован. Какую задачу проанализировать?"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора. Твоя задача — отвечать с юмором, сохраняя полезность."
        ),
        "welcome": "Режим 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}
DEFAULT_AI_MODE_KEY = "universal_ai_basic"

# --- МОДЕЛИ ИИ ---
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {"name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": "google_genai", "is_limited": True, "limit_type": "daily_free", "limit": DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY, "cost_category": "google_flash_free"},
    "google_gemini_2_5_flash_preview": {"name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": "google_genai", "is_limited": True, "limit_type": "subscription_or_daily_free", "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY, "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY, "cost_category": "google_flash_preview_flex"},
    "custom_api_gemini_2_5_pro": {"name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": "custom_http_api", "endpoint": CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY", "is_limited": True, "limit_type": "subscription_custom_pro", "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY, "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY, "cost_category": "custom_api_pro_paid", "pricing_info": {}},
    "custom_api_grok_3": {"name": "Grok 3", "id": "grok-3-beta", "api_type": "custom_http_api", "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY", "is_limited": True, "limit_type": "subscription_custom_pro", "limit_if_no_subscription": DEFAULT_FREE_REQUESTS_GROK_DAILY, "subscription_daily_limit": DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY, "cost_category": "custom_api_grok_3_paid", "pricing_info": {}}
}
DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]["id"]

# --- СТРУКТУРА МЕНЮ ---
MENU_STRUCTURE = {
    "main_menu": {"title": "📋 Главное меню", "items": [{"text": "🤖 Режимы ИИ", "action": "submenu", "target": "ai_modes_submenu"}, {"text": "⚙️ Модели ИИ", "action": "submenu", "target": "models_submenu"}, {"text": "📊 Лимиты", "action": "submenu", "target": "limits_submenu"}, {"text": "🎁 Бонус", "action": "submenu", "target": "bonus_submenu"}, {"text": "💎 Подписка", "action": "submenu", "target": "subscription_submenu"}, {"text": "❓ Помощь", "action": "submenu", "target": "help_submenu"}], "parent": None, "is_submenu": False},
    "ai_modes_submenu": {"title": "Выберите режим ИИ", "items": [{"text": mode["name"], "action": "set_agent", "target": key} for key, mode in AI_MODES.items() if key not in ["gemini_pro_custom_mode", "grok_3_custom_mode"]], "parent": "main_menu", "is_submenu": True},
    "models_submenu": {"title": "Выберите модель ИИ", "items": [{"text": model["name"], "action": "set_model", "target": key} for key, model in AVAILABLE_TEXT_MODELS.items()], "parent": "main_menu", "is_submenu": True},
    "limits_submenu": {"title": "Ваши лимиты", "items": [{"text": "📊 Показать", "action": "show_limits", "target": "usage"}], "parent": "main_menu", "is_submenu": True},
    "bonus_submenu": {"title": "Бонус за подписку", "items": [{"text": "🎁 Получить", "action": "check_bonus", "target": "news_bonus"}], "parent": "main_menu", "is_submenu": True},
    "subscription_submenu": {"title": "Подписка Профи", "items": [{"text": "💎 Купить", "action": "show_subscription", "target": "subscribe"}], "parent": "main_menu", "is_submenu": True},
    "help_submenu": {"title": "Помощь", "items": [{"text": "❓ Справка", "action": "show_help", "target": "help"}], "parent": "main_menu", "is_submenu": True}
}

# --- ИНИЦИАЛИЗАЦИЯ FIREBASE ---
db = None
try:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS")
    cred = None
    if firebase_credentials_json:
        try:
            cred_dict = json.loads(firebase_credentials_json)
            cred = credentials.Certificate(cred_dict)
            logger.info("Учетные данные Firebase загружены из переменной окружения.")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга FIREBASE_CREDENTIALS: {e}. Попытка использовать локальный файл.")
    
    if not cred: # Если из переменной окружения не загрузилось
        firebase_key_file = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json" # ВАШ ФАЙЛ КЛЮЧА
        if os.path.exists(firebase_key_file):
            cred = credentials.Certificate(firebase_key_file)
            logger.info(f"Учетные данные Firebase загружены из файла: {firebase_key_file}")
        else:
            logger.warning(f"Файл {firebase_key_file} не найден и FIREBASE_CREDENTIALS не установлена или неверна.")
            # raise FileNotFoundError(f"Файл {firebase_key_file} не найден, и FIREBASE_CREDENTIALS не установлена.") # Можно раскомментировать для жесткой ошибки

    if cred:
        if not firebase_admin._apps:
            initialize_app(cred)
            logger.info("Firebase успешно инициализирован.")
        else:
            logger.info("Firebase уже инициализирован.")
        db = firestore.client()
        logger.info("Клиент Firestore успешно инициализирован.")
    else:
        logger.error("Не удалось загрузить учетные данные Firebase. Firestore будет недоступен.")

except Exception as e:
    logger.error(f"Критическая ошибка при инициализации Firebase/Firestore: {e}")
    logger.warning("Бот будет работать без сохранения данных в Firestore.")


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С FIRESTORE ---
async def get_user_data(user_id: int) -> dict:
    if not db: return {}
    try:
        doc_ref = db.collection("users").document(str(user_id))
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() or {}
    except Exception as e:
        logger.error(f"Firestore GET user_data error for {user_id}: {e}")
        return {}

async def set_user_data(user_id: int, data: dict):
    if not db: return
    try:
        doc_ref = db.collection("users").document(str(user_id))
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        # logger.info(f"Updated user data for {user_id}") # Логгирование может быть слишком частым
    except Exception as e:
        logger.error(f"Firestore SET user_data error for {user_id}: {e}")

async def get_bot_data() -> dict:
    if not db: return {}
    try:
        doc_ref = db.collection("bot_data").document("data")
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() or {}
    except Exception as e:
        logger.error(f"Firestore GET bot_data error: {e}")
        return {}

async def set_bot_data(data: dict):
    if not db: return
    try:
        doc_ref = db.collection("bot_data").document("data")
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        logger.info("Updated bot data in Firestore.")
    except Exception as e:
        logger.error(f"Firestore SET bot_data error: {e}")

# --- ЛОГИКА БОТА (РЕЖИМЫ, МОДЕЛИ, ЛИМИТЫ) ---
async def get_current_mode_details(user_id: int) -> dict:
    user_data = await get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id)
    if current_model_key == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    elif current_model_key == "custom_api_grok_3":
        return AI_MODES.get("grok_3_custom_mode", AI_MODES[DEFAULT_AI_MODE_KEY])
    mode_key = user_data.get('current_ai_mode', DEFAULT_AI_MODE_KEY)
    return AI_MODES.get(mode_key, AI_MODES[DEFAULT_AI_MODE_KEY])

async def get_current_model_key(user_id: int) -> str:
    user_data = await get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')
    # Сначала пытаемся найти по ключу, если он сохранен (оптимизация)
    selected_model_key = user_data.get('selected_model_key')
    if selected_model_key and selected_model_key in AVAILABLE_TEXT_MODELS:
        if AVAILABLE_TEXT_MODELS[selected_model_key]['id'] == selected_id and \
           AVAILABLE_TEXT_MODELS[selected_model_key]['api_type'] == selected_api_type:
            return selected_model_key

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                if user_data.get('selected_model_key') != key: # Обновляем ключ, если он изменился
                    user_data['selected_model_key'] = key
                    await set_user_data(user_id, user_data)
                return key
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data.get('selected_api_type') != info.get("api_type") or user_data.get('selected_model_key') != key:
                user_data['selected_api_type'] = info.get("api_type")
                user_data['selected_model_key'] = key
                await set_user_data(user_id, user_data)
                logger.info(f"Inferred/Updated api_type to '{info.get('api_type')}' and model_key to '{key}' for model_id '{selected_id}', user {user_id}")
            return key
    logger.warning(f"Could not find model key for ID '{selected_id}', API type '{selected_api_type}' for user {user_id}. Defaulting.")
    default_config = AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY]
    await set_user_data(user_id, {'selected_model_id': default_config["id"], 'selected_api_type': default_config["api_type"], 'selected_model_key': DEFAULT_MODEL_KEY})
    return DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int) -> dict:
    model_key = await get_current_model_key(user_id)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[DEFAULT_MODEL_KEY])

def smart_truncate(text: str, max_length: int) -> tuple[str, bool]:
    if not isinstance(text, str): text = str(text)
    if len(text) <= max_length: return text, False
    suffix = "\n\n(...ответ сокращен)"
    adj_len = max_length - len(suffix)
    if adj_len <= 0: return text[:max_length-3] + "...", True
    trunc_text = text[:adj_len]
    cuts = [pos for sep in ['\n\n', '. ', '! ', '? ', '\n', ' '] if (pos := trunc_text.rfind(sep)) != -1 and (pos + (len(sep) if sep != ' ' else 0) > 0)]
    if cuts and (cut_at := max(cuts)) > adj_len * 0.3: return text[:cut_at].strip() + suffix, True
    return trunc_text.strip() + suffix, True

async def get_user_actual_limit_for_model(user_id: int, model_key: str) -> int:
    # ... (код этой функции из предыдущего полного ответа, он был в порядке) ...
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config: return 0
    
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    
    is_profi_subscriber = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                is_profi_subscriber = True
        except Exception: pass

    limit_type = model_config.get("limit_type")
    base_limit = 0

    if limit_type == "daily_free":
        base_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        base_limit = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif not model_config.get("is_limited", False):
        return float('inf')
    
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False):
        bonus_uses_left = user_data.get('news_bonus_uses_left', 0)
        return base_limit + bonus_uses_left # Бонус добавляется к базовому лимиту
        
    return base_limit


async def check_and_log_request_attempt(user_id: int, model_key: str, bot_username: str) -> tuple[bool, str, int]:
    # ... (код этой функции из предыдущего полного ответа, но исправить ссылку) ...
    today_str = datetime.now().strftime("%Y-%m-%d")
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_config or not model_config.get("is_limited"):
        return True, "", 0

    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)

    is_profi_subscriber = False
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                is_profi_subscriber = True
        except Exception: pass
    
    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} using bonus for {model_key}. Allowing.")
        return True, "bonus_available", 0

    all_daily_counts = bot_data.get('all_user_daily_counts', {})
    user_model_counts = all_daily_counts.get(str(user_id), {})
    model_daily_usage = user_model_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_daily_usage.get('date') != today_str: model_daily_usage = {'date': today_str, 'count': 0}
    current_daily_count = model_daily_usage.get('count', 0)
    
    # Лимит самой модели, без бонуса (бонус проверяется выше)
    actual_model_limit = 0
    limit_type = model_config.get("limit_type")
    if limit_type == "daily_free": actual_model_limit = model_config.get("limit", 0)
    elif limit_type == "subscription_or_daily_free": actual_model_limit = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro": actual_model_limit = model_config.get("subscription_daily_limit" if is_profi_subscriber else "limit_if_no_subscription", 0)

    if current_daily_count >= actual_model_limit:
        message_parts = [f"Вы достигли дневного лимита ({current_daily_count}/{actual_model_limit}) для {model_config['name']}."]
        if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_subscriber:
            if not user_data.get('claimed_news_bonus', False): message_parts.append(f'💡 Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> для бонусных генераций!')
            elif user_data.get('news_bonus_uses_left', 0) == 0: message_parts.append(f"ℹ️ Бонус за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал</a> использован.")
        
        subscribe_cmd_link = f"https://t.me/{bot_username}?start=subscribe" if bot_username and bot_username != "YourBotName" else "/subscribe (или через меню)"
        message_parts.append(f"Попробуйте завтра или оформите <a href='{subscribe_cmd_link}'>💎 Подписку Профи</a>.")
        return False, "\n".join(message_parts), current_daily_count
        
    return True, "", current_daily_count

async def increment_request_count(user_id: int, model_key: str):
    # ... (код этой функции из предыдущего полного ответа, он был в порядке) ...
    model_config = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_config or not model_config.get("is_limited"): return

    user_data = await get_user_data(user_id)
    bot_data = await get_bot_data()
    is_profi_subscriber = False
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            if datetime.now(datetime.fromisoformat(user_subscription_details['valid_until']).tzinfo).date() <= datetime.fromisoformat(user_subscription_details['valid_until']).date():
                is_profi_subscriber = True
        except Exception: pass

    if model_key == NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_subscriber and \
       user_data.get('claimed_news_bonus', False):
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
    if model_daily_usage.get('date') != today_str: model_daily_usage = {'date': today_str, 'count': 0}
    
    model_daily_usage['count'] += 1
    user_model_counts[model_key] = model_daily_usage
    all_daily_counts[str(user_id)] = user_model_counts
    bot_data['all_user_daily_counts'] = all_daily_counts
    await set_bot_data(bot_data)
    logger.info(f"User {user_id} count for {model_key} incremented to {model_daily_usage['count']}")

# --- ФУНКЦИЯ ОПРЕДЕЛЕНИЯ МЕНЮ (ВАЖНО: ДОЛЖНА БЫТЬ ОПРЕДЕЛЕНА ДО ЕЕ ВЫЗОВОВ) ---
def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu = MENU_STRUCTURE.get(menu_key)
    if not menu:
        logger.warning(f"Menu key '{menu_key}' not found. Defaulting to main_menu keyboard.")
        menu = MENU_STRUCTURE["main_menu"] 
    
    keyboard_buttons = []
    if menu_key == "main_menu":
        items = menu.get("items", [])
        for i in range(0, len(items), 2):
            row = [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            keyboard_buttons.append(row)
    else: 
        keyboard_buttons = [[KeyboardButton(item["text"])] for item in menu.get("items", [])]
    
    if menu.get("is_submenu", False):
        nav_row = []
        if menu.get("parent"):
            nav_row.append(KeyboardButton("⬅️ Назад"))
        nav_row.append(KeyboardButton("🏠 Главное меню"))
        keyboard_buttons.append(nav_row)
    
    return ReplyKeyboardMarkup(keyboard_buttons, resize_keyboard=True, one_time_keyboard=False)

# --- Проверка, является ли текст кнопкой меню ---
def is_menu_button_text(text: str) -> bool:
    # ... (код этой функции из предыдущего полного ответа, он был в порядке) ...
    navigation_buttons = ["⬅️ Назад", "🏠 Главное меню"]
    if text in navigation_buttons: return True
    for menu_config in MENU_STRUCTURE.values():
        for item in menu_config.get("items", []):
            if item["text"] == text: return True
    return False

# --- ОБРАБОТЧИКИ КОМАНД И КНОПОК ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_key: str):
    # ... (код этой функции из предыдущего полного ответа) ...
    user_id = update.effective_user.id
    menu_config = MENU_STRUCTURE.get(menu_key)
    if not menu_config:
        logger.error(f"Menu config for '{menu_key}' not found for user {user_id}. Sending main_menu.")
        menu_key = "main_menu"
        menu_config = MENU_STRUCTURE[menu_key]
    user_data = await get_user_data(user_id)
    user_data['current_menu'] = menu_key
    await set_user_data(user_id, user_data)
    await update.message.reply_text(menu_config["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)
    logger.info(f"Sent menu '{menu_key}' to user {user_id}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код этой функции из предыдущего полного ответа) ...
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_data.setdefault('current_ai_mode', DEFAULT_AI_MODE_KEY)
    user_data['current_menu'] = 'main_menu'
    
    selected_model_key = user_data.get('selected_model_key', DEFAULT_MODEL_KEY)
    if selected_model_key not in AVAILABLE_TEXT_MODELS: selected_model_key = DEFAULT_MODEL_KEY
    
    model_conf = AVAILABLE_TEXT_MODELS[selected_model_key]
    user_data['selected_model_id'] = model_conf["id"]
    user_data['selected_api_type'] = model_conf["api_type"]
    user_data['selected_model_key'] = selected_model_key

    if context.args and context.args[0] == 'subscribe':
        await set_user_data(user_id, user_data)
        await show_subscription(update, context, user_id, called_from_start=True)
        return
    
    await set_user_data(user_id, user_data)
    
    mode_details = await get_current_mode_details(user_id)
    greeting = (f"👋 Привет, {update.effective_user.first_name}!\n"
                f"Я твой ИИ-бот.\n\n"
                f"🧠 Режим: <b>{mode_details['name']}</b>\n"
                f"⚙️ Модель: <b>{model_conf['name']}</b>\n\n"
                f"💬 Задавай вопросы или используй /menu.")
    await update.message.reply_text(greeting, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard("main_menu"), disable_web_page_preview=True)
    logger.info(f"Sent start message to user {user_id}")


async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код этой функции из предыдущего полного ответа) ...
    if update.message: 
        try: await update.message.delete()
        except: pass # Игнорируем, если не удалось удалить
    await show_menu(update, context, "main_menu")

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код этой функции из предыдущего полного ответа) ...
    if update.message: 
        try: await update.message.delete()
        except: pass
    await show_limits(update, context, update.effective_user.id)

async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код этой функции из предыдущего полного ответа) ...
    if update.message: 
        try: await update.message.delete()
        except: pass
    await show_subscription(update, context, update.effective_user.id)

async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код этой функции из предыдущего полного ответа) ...
    if update.message: 
        try: await update.message.delete()
        except: pass
    await claim_news_bonus_logic(update, update.effective_user.id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код этой функции из предыдущего полного ответа) ...
    if update.message: 
        try: await update.message.delete()
        except: pass
    await show_help(update, update.effective_user.id)

async def show_limits(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    # ... (код этой функции из предыдущего полного ответа, включая использование context.bot.username) ...
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
            else: display_sub_level = f"Подписка Профи (истекла {valid_until_dt.strftime('%d.%m.%Y')})"
        except Exception: display_sub_level = "Подписка Профи (ошибка даты)"

    usage_text_parts = [f"<b>📊 Ваши лимиты</b>\nСтатус: <b>{display_sub_level}</b>\n"]
    bot_username = context.bot_data.get('bot_username', "YourBotName") # Используем сохраненное имя
    subscribe_cmd_link = f"https://t.me/{bot_username}?start=subscribe" if bot_username != "YourBotName" else "/subscribe (через меню)"
    if not subscription_active_profi: usage_text_parts.append(f"Для увеличения лимитов <a href='{subscribe_cmd_link}'>💎 оформите Подписку Профи</a>.")
    
    usage_text_parts.append("\n<b>Дневные лимиты запросов:</b>")
    for model_k, model_c in AVAILABLE_TEXT_MODELS.items():
        if model_c.get("is_limited"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            user_model_counts = bot_data.get('all_user_daily_counts', {}).get(str(user_id), {})
            model_daily_usage = user_model_counts.get(model_k, {'date': '', 'count': 0})
            current_c = model_daily_usage['count'] if model_daily_usage.get('date') == today_str else 0
            actual_l = await get_user_actual_limit_for_model(user_id, model_k)
            bonus_n = ""
            if model_k == NEWS_CHANNEL_BONUS_MODEL_KEY and not subscription_active_profi and user_data.get('claimed_news_bonus', False) and (b_left := user_data.get('news_bonus_uses_left', 0)) > 0:
                bonus_n = f" (вкл. {b_left} бонусн.)"
            usage_text_parts.append(f"▫️ {model_c['name']}: <b>{current_c}/{actual_l if actual_l != float('inf') else '∞'}</b>{bonus_n}")

    if NEWS_CHANNEL_USERNAME and NEWS_CHANNEL_USERNAME != "@YourNewsChannelHandle" and not subscription_active_profi:
        bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
        if bonus_model_cfg:
            bonus_model_nm = bonus_model_cfg['name']
            if not user_data.get('claimed_news_bonus', False):
                usage_text_parts.append(f'\n🎁 <a href="{NEWS_CHANNEL_LINK}">Подпишитесь на канал</a> и получите <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусных генераций для {bonus_model_nm}!')
            elif (b_left := user_data.get('news_bonus_uses_left', 0)) > 0:
                usage_text_parts.append(f'\n🎁 У вас <b>{b_left}</b> бонусных генераций для {bonus_model_nm} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).')
            else: usage_text_parts.append(f'\nℹ️ Бонус для {bonus_model_nm} (<a href="{NEWS_CHANNEL_LINK}">канал</a>) использован.')
    
    final_usage_text = "\n".join(filter(None, usage_text_parts))
    reply_markup = generate_menu_keyboard(user_data.get('current_menu', 'limits_submenu'))
    await update.message.reply_text(final_usage_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)
    logger.info(f"Sent limits to user {user_id}")


async def claim_news_bonus_logic(update: Update, user_id: int):
    # ... (код этой функции из предыдущего полного ответа) ...
    user = update.effective_user
    user_data = await get_user_data(user_id)
    if update.message: try: await update.message.delete() catch: pass

    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        await update.message.reply_text("Функция бонуса не настроена.", reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        return
    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text("Ошибка: Бонусная модель не найдена.", reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
        return
    bonus_model_name = bonus_model_config['name']
    
    bot_data = await get_bot_data() # Проверка на Профи
    user_subscriptions = bot_data.get('user_subscriptions', {})
    user_subscription_details = user_subscriptions.get(str(user_id), {})
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                await update.message.reply_text(f"💎 Вы Профи подписчик, бонус за канал не суммируется.", reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')))
                return
        except: pass

    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        reply_text = f'Вы уже активировали бонус. Осталось <b>{uses_left}</b> генераций для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>).' if uses_left > 0 else f'Бонус для {bonus_model_name} (<a href="{NEWS_CHANNEL_LINK}">канал</a>) использован.'
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')), disable_web_page_preview=True)
        return
    try:
        member_status = await update.get_bot().get_chat_member(chat_id=NEWS_CHANNEL_USERNAME, user_id=user.id)
        if member_status.status in ['member', 'administrator', 'creator']:
            user_data.update({'claimed_news_bonus': True, 'news_bonus_uses_left': NEWS_CHANNEL_BONUS_GENERATIONS})
            await set_user_data(user_id, user_data)
            success_text = f'🎉 Спасибо за подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>! Вам начислена <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> генерация для {bonus_model_name}.'
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard('main_menu'), disable_web_page_preview=True)
        else:
            fail_text = f'Подпишитесь на <a href="{NEWS_CHANNEL_LINK}">канал</a> и нажмите «Получить» снова.'
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)]]), disable_web_page_preview=True)
    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest checking channel membership for {NEWS_CHANNEL_USERNAME}: {e}")
        await update.message.reply_text(f'Не удалось проверить подписку на <a href="{NEWS_CHANNEL_LINK}">канал</a>. Попробуйте снова.', parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)]]), disable_web_page_preview=True)

async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, called_from_start: bool = False):
    # ... (код этой функции из предыдущего полного ответа) ...
    bot_data = await get_bot_data()
    user_data = await get_user_data(user_id)
    user_subscription_details = bot_data.get('user_subscriptions', {}).get(str(user_id), {})
    sub_text_parts = ["<b>💎 Подписка Профи</b>\n"]
    is_active_profi = False
    if user_subscription_details.get('level') == PRO_SUBSCRIPTION_LEVEL_KEY and user_subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(user_subscription_details['valid_until'])
            if datetime.now(valid_until_dt.tzinfo).date() <= valid_until_dt.date():
                sub_text_parts.append(f"Ваша подписка активна до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
                is_active_profi = True
            else: sub_text_parts.append(f"Ваша подписка истекла <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
        except Exception: sub_text_parts.append("Ошибка проверки статуса подписки.")

    if not is_active_profi:
        sub_text_parts.append("С подпиской вы получите:")
        sub_text_parts.append(f"▫️ Лимиты: Gemini 2.5 - {DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY}, Gemini Pro - {DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY}, Grok 3 - {DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY}.")
        sub_text_parts.append("▫️ Доступ к продвинутым моделям.")
        sub_text_parts.append("\n<b>Стоимость: [ВАША_ЦЕНА] [ВАЛЮТА] / 30 дней.</b>") # ЗАМЕНИТЬ
        sub_text_parts.append(f"\nДля покупки нажмите /pay или кнопку ниже.")
    
    final_sub_text = "\n".join(sub_text_parts)
    keyboard_inline = []
    if not is_active_profi:
        keyboard_inline.append([InlineKeyboardButton("💳 Оформить Подписку Профи", callback_data="initiate_payment_profi")]) # Замените callback_data если нужно

    parent_menu_key = 'main_menu' if called_from_start else user_data.get('current_menu', 'subscription_submenu')
    reply_markup_to_send = InlineKeyboardMarkup(keyboard_inline) if keyboard_inline else generate_menu_keyboard(parent_menu_key)
    
    await update.message.reply_text(final_sub_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup_to_send, disable_web_page_preview=True)
    if not keyboard_inline and not called_from_start and parent_menu_key != 'main_menu' : # Если нет инлайн кнопок и это не стартовый вызов
         await update.message.reply_text("Вернуться в меню:", reply_markup=generate_menu_keyboard(parent_menu_key))
    logger.info(f"Sent subscription info to user {user_id}")

async def show_help(update: Update, user_id: int):
    # ... (код этой функции из предыдущего полного ответа) ...
    user_data = await get_user_data(user_id)
    if update.message: try: await update.message.delete() catch: pass
    help_text = ("<b>❓ Помощь по боту</b>\n\n"
        "Я — ИИ-бот. Вот что я умею:\n"
        "▫️ Отвечать на вопросы в разных режимах ИИ.\n"
        "▫️ Менять модели и режимы через меню (/menu).\n"
        "▫️ Показывать лимиты запросов (/usage).\n"
        "▫️ Предоставлять бонусы за подписку на канал (/bonus).\n"
        "▫️ Поддерживать подписку Профи для расширенных лимитов (/subscribe).\n\n"
        "Используйте меню или команды. Если что-то пошло не так, попробуйте /start.")
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'help_submenu')), disable_web_page_preview=True)
    logger.info(f"Sent help message to user {user_id}")

# ИСПРАВЛЕН: menu_button_handler для предотвращения двойной обработки
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    button_text = update.message.text.strip()
    
    user_data = await get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', 'main_menu')
    current_menu_config = MENU_STRUCTURE.get(current_menu_key, MENU_STRUCTURE['main_menu'])
    
    selected_item = None
    action_taken_by_menu_handler = False

    # 1. Навигационные кнопки
    if button_text == "⬅️ Назад" and current_menu_config.get("parent"):
        selected_item = {"action": "navigate_back", "target": current_menu_config["parent"]}
    elif button_text == "🏠 Главное меню":
        selected_item = {"action": "navigate_home", "target": "main_menu"}
    
    # 2. Кнопки текущего меню
    if not selected_item:
        selected_item = next((item for item in current_menu_config.get("items", []) if item["text"] == button_text), None)

    if selected_item: # Если это кнопка из текущего меню или навигационная
        action_taken_by_menu_handler = True
        if update.message:
            try: await update.message.delete()
            except Exception as e: logger.warning(f"Could not delete user's button message: {e}")

        action = selected_item["action"]
        target = selected_item["target"]
        logger.info(f"User {user_id} (menu: {current_menu_key}) -> Button: '{button_text}', Action: '{action}', Target: '{target}'")

        if action == "submenu" or action == "navigate_back" or action == "navigate_home":
            await show_menu(update, context, target)
        elif action == "set_agent":
            return_menu_key = current_menu_config.get("parent", "main_menu")
            if target in AI_MODES and target not in ["gemini_pro_custom_mode", "grok_3_custom_mode"]:
                user_data['current_ai_mode'] = target
                await set_user_data(user_id, user_data)
                mode_details = AI_MODES[target]
                new_text = f"🤖 Режим ИИ: <b>{mode_details['name']}</b>\n\n{mode_details['welcome']}"
            else: new_text = "⚠️ Ошибка: Режим не найден."
            await update.message.reply_text(new_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key), disable_web_page_preview=True)
            user_data['current_menu'] = return_menu_key
            await set_user_data(user_id, user_data)
        elif action == "set_model":
            return_menu_key = current_menu_config.get("parent", "main_menu")
            if target in AVAILABLE_TEXT_MODELS:
                model_cfg = AVAILABLE_TEXT_MODELS[target]
                user_data.update({'selected_model_id': model_cfg["id"], 'selected_api_type': model_cfg["api_type"], 'selected_model_key': target})
                await set_user_data(user_id, user_data)
                bot_data_s, today_s = await get_bot_data(), datetime.now().strftime("%Y-%m-%d")
                user_counts_s = bot_data_s.get('all_user_daily_counts', {}).get(str(user_id), {})
                model_usage_s = user_counts_s.get(target, {'date': '', 'count': 0})
                count_display_s = model_usage_s['count'] if model_usage_s.get('date') == today_s else 0
                limit_actual_s = await get_user_actual_limit_for_model(user_id, target)
                limit_str_s = f"Лимит: {count_display_s}/{limit_actual_s if limit_actual_s != float('inf') else '∞'}"
                effective_mode_s = await get_current_mode_details(user_id)
                new_text = (f"⚙️ Модель: <b>{model_cfg['name']}</b>.\n"
                            f"🧠 Режим для неё: <b>{effective_mode_s['name']}</b>.\n{limit_str_s}")
            else: new_text = "⚠️ Ошибка: Модель не найдена."
            await update.message.reply_text(new_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key), disable_web_page_preview=True)
            user_data['current_menu'] = return_menu_key
            await set_user_data(user_id, user_data)
        elif action == "show_limits": await show_limits(update, context, user_id)
        elif action == "check_bonus": await claim_news_bonus_logic(update, user_id)
        elif action == "show_subscription": await show_subscription(update, context, user_id)
        elif action == "show_help": await show_help(update, user_id)
        else: await update.message.reply_text("Неизвестное действие.", reply_markup=generate_menu_keyboard(current_menu_key))
    
    # Если это не кнопка текущего меню и не навигация, но является кнопкой меню ВООБЩЕ (старая кнопка)
    elif not action_taken_by_menu_handler and is_menu_button_text(button_text):
        logger.warning(f"User {user_id} pressed out-of-context menu button: '{button_text}'. Current menu: '{current_menu_key}'.")
        if update.message:
            try: await update.message.delete()
            except: pass
        await update.message.reply_text("Эта кнопка больше не активна. Используйте текущее меню.", reply_markup=generate_menu_keyboard(current_menu_key))
        action_taken_by_menu_handler = True # Считаем обработанной, чтобы не ушло в handle_text

    # Если action_taken_by_menu_handler все еще False, значит это не кнопка меню
    # и управление должно перейти к handle_text (группа 2) автоматически.
    # Поэтому здесь не нужен явный вызов handle_text или return без условия.
    if not action_taken_by_menu_handler:
        logger.info(f"Text '{button_text}' from user {user_id} not handled by menu_button_handler, passing to next handler.")
        # Не делаем return, позволяем telegram.ext передать следующему обработчику

# ИСПРАВЛЕНО: handle_text для корректного парсинга Grok и общей структуры
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text.strip()
    chat_id = update.effective_chat.id

    if len(user_message) < MIN_AI_REQUEST_LENGTH:
        logger.info(f"AI Request too short from user {user_id}: '{user_message}'")
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            "Запрос слишком короткий. Уточните, пожалуйста.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu'))
        )
        return

    logger.info(f"Processing AI request from user {user_id}: '{user_message[:100]}...'")

    current_model_key = await get_current_model_key(user_id)
    model_config = AVAILABLE_TEXT_MODELS.get(current_model_key)
    if not model_config:
        logger.error(f"CRITICAL: model_config is None for key '{current_model_key}' (user {user_id}).")
        await update.message.reply_text("Ошибка конфигурации модели. Попробуйте /start.", reply_markup=generate_menu_keyboard('main_menu'))
        return

    bot_username = context.bot_data.get('bot_username', "YourBotName")
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key, bot_username)

    if not can_proceed:
        user_data = await get_user_data(user_id)
        await update.message.reply_text(
            limit_message, parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', 'main_menu')),
            disable_web_page_preview=True)
        logger.info(f"User {user_id} limit reached for {current_model_key}.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    mode_details = await get_current_mode_details(user_id)
    system_prompt = mode_details["prompt"]
    response_text = "К сожалению, не удалось получить ответ от ИИ." # Default

    if model_config["api_type"] == "google_genai":
        full_prompt_genai = f"{system_prompt}\n\n**Пользовательский запрос:**\n{user_message}"
        genai_model_instance = genai.GenerativeModel(model_config["id"], generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB})
        try:
            api_resp = await asyncio.get_event_loop().run_in_executor(None, lambda: genai_model_instance.generate_content(full_prompt_genai))
            if api_resp.text: response_text = api_resp.text.strip()
            elif hasattr(api_resp, 'parts') and api_resp.parts:
                response_text = "\n".join([p.text for p in api_resp.parts if hasattr(p, 'text')]).strip() or "Ответ не содержит текста."
            elif hasattr(api_resp, 'prompt_feedback') and api_resp.prompt_feedback.block_reason:
                response_text = f"Запрос заблокирован: {api_resp.prompt_feedback.block_reason_message or api_resp.prompt_feedback.block_reason}"
            if not response_text.strip(): response_text = "ИИ не дал содержательного ответа."
        except google.api_core.exceptions.ResourceExhausted:
            response_text = "Лимит API Google GenAI исчерпан. Попробуйте позже."
            logger.error(f"Google GenAI ResourceExhausted: user {user_id}, model {model_config['id']}")
        except Exception as e:
            response_text = f"Ошибка Google GenAI: {type(e).__name__}."
            logger.error(f"Google GenAI API error: user {user_id}, model {model_config['id']}: {traceback.format_exc()}")

    elif model_config["api_type"] == "custom_http_api":
        api_key_name = model_config.get("api_key_var_name")
        api_key_val = globals().get(api_key_name) if api_key_name else None
        if not api_key_val:
            response_text = "Ошибка конфигурации API ключа для этой модели."
            logger.error(f"API key '{api_key_name}' not found for model {current_model_key}.")
        else:
            headers = {"Authorization": f"Bearer {api_key_val}", "Content-Type": "application/json", "Accept": "application/json"}
            payload = {"messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                       "model": model_config["id"], "is_sync": True, "max_tokens": MAX_OUTPUT_TOKENS_GEMINI_LIB,
                       "temperature": 1.0, "top_p": 1.0, "n": 1}
            try:
                http_resp = await asyncio.get_event_loop().run_in_executor(None, lambda: requests.post(model_config["endpoint"], headers=headers, json=payload, timeout=45))
                http_resp.raise_for_status()
                resp_data = http_resp.json()
                extracted_text = None

                if model_config["id"] == "grok-3-beta":
                    try: # Новый парсинг для Grok на основе логов
                        resp_list = resp_data.get("response")
                        if resp_list and isinstance(resp_list, list) and resp_list:
                            choices_list = resp_list[0].get("choices")
                            if choices_list and isinstance(choices_list, list) and choices_list:
                                msg_obj = choices_list[0].get("message")
                                if msg_obj and isinstance(msg_obj, dict):
                                    content_obj = msg_obj.get("content")
                                    if content_obj and isinstance(content_obj, dict):
                                        text_cand = content_obj.get("text")
                                        if text_cand and isinstance(text_cand, str): extracted_text = text_cand.strip()
                    except Exception as e_grok_parse:
                        logger.error(f"Error parsing specific Grok-3 response (user {user_id}): {e_grok_parse}. Data: {str(resp_data)[:300]}")
                    if not extracted_text: # Фоллбэк для Grok
                        if isinstance(resp_data.get("output"), str): extracted_text = resp_data["output"].strip()
                        elif isinstance(resp_data.get("text"), str): extracted_text = resp_data["text"].strip()
                
                elif model_config["id"] == "gemini-2.5-pro-preview-03-25":
                    if isinstance(resp_data.get("text"), str): extracted_text = resp_data["text"].strip()
                    elif isinstance(resp_data.get("output"), str): extracted_text = resp_data["output"].strip() # Фоллбэк

                if extracted_text: response_text = extracted_text
                else:
                    response_text = "Ответ от API получен, но текст извлечь не удалось."
                    logger.warning(f"Could not extract text from Custom API model {model_config['id']}, user {user_id}. Response: {str(resp_data)[:300]}")

            except requests.exceptions.Timeout:
                response_text, logger.error(f"Custom API Timeout: user {user_id}, model {model_config['id']}.")
            except requests.exceptions.RequestException as e:
                response_text, logger.error(f"Custom API Network Error: user {user_id}, model {model_config['id']}: {e}")
            except json.JSONDecodeError as e:
                response_text, logger.error(f"Custom API JSONDecodeError: user {user_id}, model {model_config['id']}: {e}. Response: {http_resp.text[:200] if 'http_resp' in locals() else 'N/A'}")
            except Exception as e:
                response_text, logger.error(f"Unexpected Custom API error: user {user_id}, model {model_config['id']}: {traceback.format_exc()}")
    else:
        response_text = "Неизвестный тип API для выбранной модели."
        logger.error(f"Unknown api_type '{model_config.get('api_type')}' for model '{current_model_key}', user {user_id}")

    final_response_text, was_truncated = smart_truncate(response_text, MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated: logger.info(f"Response (user {user_id}, model {current_model_key}) truncated.")

    await increment_request_count(user_id, current_model_key)
    user_data_reply = await get_user_data(user_id)
    await update.message.reply_text(
        final_response_text, parse_mode=None,
        reply_markup=generate_menu_keyboard(user_data_reply.get('current_menu', 'main_menu')),
        disable_web_page_preview=True)
    logger.info(f"Sent AI response to user {user_id} (model {current_model_key}). Trunc: {was_truncated}. Start: '{final_response_text[:70].replace(chr(10), ' ')}...'")

# ... (precheckout_callback, successful_payment_callback, error_handler, main, if __name__ ...)
# Код этих функций из предыдущего полного ответа в целом корректен, но можно проверить
# использование bot_username в error_handler, если он там нужен для ссылок.
# В error_handler context.bot.username доступен.

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if PRO_SUBSCRIPTION_LEVEL_KEY not in query.invoice_payload :
        await query.answer(ok=False, error_message="Неверный тип подписки.")
        logger.warning(f"PreCheckoutQuery invalid payload: {query.invoice_payload} from user {query.from_user.id}")
        return
    await query.answer(ok=True)
    logger.info(f"PreCheckoutQuery OK for user {query.from_user.id}, payload: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    if PRO_SUBSCRIPTION_LEVEL_KEY in payment.invoice_payload:
        days = 30 
        valid_until = datetime.now().astimezone() + timedelta(days=days)
        bot_data = await get_bot_data()
        user_subscriptions = bot_data.get('user_subscriptions', {})
        user_subscriptions[str(user_id)] = {
            'level': PRO_SUBSCRIPTION_LEVEL_KEY, 'valid_until': valid_until.isoformat(),
            'charge_id': payment.telegram_payment_charge_id, 'amount': payment.total_amount, 'currency': payment.currency
        }
        bot_data['user_subscriptions'] = user_subscriptions
        await set_bot_data(bot_data)
        text = f"🎉 Подписка <b>Профи</b> активирована до <b>{valid_until.strftime('%d.%m.%Y %H:%M %Z')}</b>!"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard('main_menu'))
        logger.info(f"Profi subscription for user {user_id} until {valid_until.isoformat()}")
        if YOUR_ADMIN_ID:
            admin_msg = f"User {user_id} ({update.effective_user.full_name or ''} @{update.effective_user.username or ''}) bought Profi subscription."
            try: await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=admin_msg)
            except Exception as e_admin: logger.error(f"Failed to send payment notification to admin: {e_admin}")
    else:
        logger.warning(f"Success payment with unhandled payload: {payment.invoice_payload} from user {user_id}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    update_str = str(update)
    if isinstance(update, Update): update_str = json.dumps(update.to_dict(), indent=1, ensure_ascii=False, default=str)

    error_message_for_admin = (
        f"<b>Бот столкнулся с ошибкой!</b>\n\n"
        f"<b>Update:</b> <pre>{html.escape(update_str)}</pre>\n"
        f"<b>Chat Data:</b> <pre>{html.escape(str(context.chat_data))}</pre>\n"
        f"<b>User Data:</b> <pre>{html.escape(str(context.user_data))}</pre>\n"
        f"<b>Error:</b> <pre>{html.escape(str(context.error))}</pre>\n"
        f"<b>Traceback:</b>\n<pre>{html.escape(tb_string)}</pre>"
    )
    if YOUR_ADMIN_ID:
        try:
            for chunk in [error_message_for_admin[i:i + MAX_MESSAGE_LENGTH_TELEGRAM] for i in range(0, len(error_message_for_admin), MAX_MESSAGE_LENGTH_TELEGRAM)]:
                await context.bot.send_message(chat_id=YOUR_ADMIN_ID, text=chunk, parse_mode=ParseMode.HTML)
        except Exception as e_admin: logger.error(f"Failed to send error to admin: {e_admin}")

    if isinstance(update, Update) and update.effective_message and update.effective_user:
        try:
            user_data_err = await get_user_data(update.effective_user.id)
            await update.effective_message.reply_text(
                "Произошла внутренняя ошибка. Мы уже уведомлены. Попробуйте /start.",
                reply_markup=generate_menu_keyboard(user_data_err.get('current_menu', 'main_menu')))
        except Exception as e_user: logger.error(f"Failed to send error reply to user: {e_user}")


async def main():
    application = Application.builder().token(TOKEN).build()
    bot_info = await application.bot.get_me()
    application.bot_data['bot_username'] = bot_info.username # Сохраняем для ссылок
    logger.info(f"Bot @{application.bot_data['bot_username']} started.")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", open_menu_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("subscribe", subscribe_info_command))
    application.add_handler(CommandHandler("bonus", get_news_bonus_info_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_error_handler(error_handler)

    commands = [BotCommand("start", "🚀 Перезапуск / Меню"), BotCommand("menu", "📋 Открыть меню"), BotCommand("usage", "📊 Лимиты"), BotCommand("subscribe", "💎 Подписка"), BotCommand("bonus", "🎁 Бонус"), BotCommand("help", "❓ Помощь")]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands set.")
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

    logger.info("Bot is starting polling...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    for key_name, key_value in [("GOOGLE_GEMINI_API_KEY", GOOGLE_GEMINI_API_KEY), 
                               ("CUSTOM_GEMINI_PRO_API_KEY", CUSTOM_GEMINI_PRO_API_KEY), 
                               ("CUSTOM_GROK_3_API_KEY", CUSTOM_GROK_3_API_KEY),
                               ("PAYMENT_PROVIDER_TOKEN", PAYMENT_PROVIDER_TOKEN)]:
        if not key_value or "YOUR_" in key_value.upper() or ("sk-" not in key_value and "AIzaSy" not in key_value and key_name != "PAYMENT_PROVIDER_TOKEN") or (key_name == "PAYMENT_PROVIDER_TOKEN" and ":" not in key_value):
            logger.warning(f"{key_name} не настроен корректно или используется значение-заглушка.")
            if key_name == "TOKEN": exit(f"Критическая ошибка: {key_name} не установлен!") # Выход, если нет токена бота
    if GOOGLE_GEMINI_API_KEY and "AIzaSy" in GOOGLE_GEMINI_API_KEY: # Проверка только для Gemini, если он есть
        try:
            genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API сконфигурирован.")
        except Exception as e: logger.error(f"Ошибка конфигурации Google Gemini API: {e}")
    asyncio.run(main())
