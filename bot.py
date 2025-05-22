import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
)
import logging
import traceback
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, Union, List
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from google.cloud.firestore_v1.client import Client as FirestoreClient
from ai_services import AI_MODES, AVAILABLE_TEXT_MODELS, get_ai_service, AIConfig

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
class AppConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152"))
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"

    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
    DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY = 75
    DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY = 0
    DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY = 25
    PRO_SUBSCRIPTION_LEVEL_KEY = "profi_access_v1"
    DEFAULT_FREE_REQUESTS_GROK_DAILY = 3
    DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY = 25
    DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 3
    DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY = 25

    NEWS_CHANNEL_USERNAME = "@timextech"
    NEWS_CHANNEL_LINK = "https://t.me/timextech"
    NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
    NEWS_CHANNEL_BONUS_GENERATIONS = 1

    DEFAULT_AI_MODE_KEY = "universal_ai_basic"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"

CONFIG = AppConfig()

# --- КОНСТАНТЫ ПРИЛОЖЕНИЯ ---
class BotConstants:
    FS_USERS_COLLECTION = "users"
    FS_BOT_DATA_COLLECTION = "bot_data"
    FS_BOT_DATA_DOCUMENT = "data"
    FS_USER_SUBSCRIPTIONS_KEY = "user_subscriptions"
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"

    MENU_MAIN = "main_menu"
    MENU_AI_MODES_SUBMENU = "ai_modes_submenu"
    MENU_MODELS_SUBMENU = "models_submenu"
    MENU_LIMITS_SUBMENU = "limits_submenu"
    MENU_BONUS_SUBMENU = "bonus_submenu"
    MENU_SUBSCRIPTION_SUBMENU = "subscription_submenu"
    MENU_HELP_SUBMENU = "help_submenu"

    CALLBACK_ACTION_SUBMENU = "submenu"
    CALLBACK_ACTION_SET_AGENT = "set_agent"
    CALLBACK_ACTION_SET_MODEL = "set_model"
    CALLBACK_ACTION_SHOW_LIMITS = "show_limits"
    CALLBACK_ACTION_CHECK_BONUS = "check_bonus"
    CALLBACK_ACTION_SHOW_SUBSCRIPTION = "show_subscription"
    CALLBACK_ACTION_SHOW_HELP = "show_help"

    API_TYPE_GOOGLE_GENAI = "google_genai"
    API_TYPE_CUSTOM_HTTP = "custom_http_api"

DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["id"]

MENU_STRUCTURE = {
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню", "items": [
            {"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU},
            {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU},
            {"text": "📊 Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_LIMITS_SUBMENU},
            {"text": "🎁 Бонус", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_BONUS_SUBMENU},
            {"text": "💎 Подписка", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_SUBSCRIPTION_SUBMENU},
            {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}
        ], "parent": None, "is_submenu": False
    },
    BotConstants.MENU_AI_MODES_SUBMENU: {
        "title": "Выберите агент ИИ", "items": [
            {"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_SET_AGENT, "target": key}
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode"
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_MODELS_SUBMENU: {
        "title": "Выберите модель ИИ", "items": [
            {"text": model["name"], "action": BotConstants.CALLBACK_ACTION_SET_MODEL, "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_LIMITS_SUBMENU: {"title": "Ваши лимиты", "items": [{"text": "📊 Показать", "action": BotConstants.CALLBACK_ACTION_SHOW_LIMITS, "target": "usage"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_BONUS_SUBMENU: {"title": "Бонус за подписку", "items": [{"text": "🎁 Получить", "action": BotConstants.CALLBACK_ACTION_CHECK_BONUS, "target": "news_bonus"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_SUBSCRIPTION_SUBMENU: {"title": "Подписка Профи", "items": [{"text": "💎 Купить", "action": BotConstants.CALLBACK_ACTION_SHOW_SUBSCRIPTION, "target": "subscribe"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_HELP_SUBMENU: {"title": "Помощь", "items": [{"text": "❓ Справка", "action": BotConstants.CALLBACK_ACTION_SHOW_HELP, "target": "help"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True}
}

# --- СЕРВИС ДЛЯ РАБОТЫ С FIRESTORE ---
class FirestoreService:
    def __init__(self, cert_path: str, creds_json_str: Optional[str] = None):
        self._db: Optional[FirestoreClient] = None
        try:
            cred_obj = None
            if creds_json_str:
                try:
                    cred_obj = credentials.Certificate(json.loads(creds_json_str))
                    logger.info("Firebase credentials loaded from JSON string.")
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing FIREBASE_CREDENTIALS_JSON_STR: {e}. Check JSON env var.")
                    raise
            elif os.path.exists(cert_path):
                cred_obj = credentials.Certificate(cert_path)
                logger.info(f"Firebase credentials loaded from file: {cert_path}.")
            else:
                raise FileNotFoundError("Firebase credentials not configured (JSON string or cert file).")

            if not firebase_admin._apps: # pylint: disable=protected-access
                initialize_app(cred_obj)
                logger.info("Firebase app successfully initialized.")
            else:
                logger.info("Firebase app already initialized.")
            self._db = firestore.client()
            logger.info("Firestore client successfully initialized.")
        except Exception as e:
            logger.error(f"Critical error during Firebase/Firestore initialization: {e}", exc_info=True)
            self._db = None

    async def _execute_firestore_op(self, func, *args, **kwargs):
        if not self._db:
            logger.warning(f"Firestore (db) is not initialized. Operation '{func.__name__}' skipped.")
            return None
        return await asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs))

    async def get_user_data(self, user_id: int) -> Dict[str, Any]:
        if not self._db: return {}
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc and doc.exists else {}

    async def set_user_data(self, user_id: int, data: Dict[str, Any]) -> None:
        if not self._db: return
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        await self._execute_firestore_op(doc_ref.set, data, merge=True)
        logger.debug(f"User data for {user_id} updated with keys: {list(data.keys())}")

    async def get_bot_data(self) -> Dict[str, Any]:
        if not self._db: return {}
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document(BotConstants.FS_BOT_DATA_DOCUMENT)
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc and doc.exists else {}

    async def set_bot_data(self, data: Dict[str, Any]) -> None:
        if not self._db: return
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document(BotConstants.FS_BOT_DATA_DOCUMENT)
        await self._execute_firestore_op(doc_ref.set, data, merge=True)
        logger.debug(f"Bot data updated with keys: {list(data.keys())}")

# Инициализация сервиса Firestore
firestore_service = FirestoreService(
    cert_path=CONFIG.FIREBASE_CERT_PATH,
    creds_json_str=CONFIG.FIREBASE_CREDENTIALS_JSON_STR
)

# --- УТИЛИТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    if not update.message: return

    message_id_to_process = update.message.message_id
    timestamp_now_iso = datetime.now(timezone.utc).isoformat()
    chat_id = update.effective_chat.id
    
    user_data_for_msg_handling = await firestore_service.get_user_data(user_id)

    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)
    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48):
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e:
            logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    if not is_command_to_keep:
        user_data_for_msg_handling['user_command_to_delete'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
        try:
            await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_process)
            logger.info(f"Successfully deleted current user message {message_id_to_process} (not kept).")
            user_data_for_msg_handling.pop('user_command_to_delete', None)
        except telegram.error.BadRequest as e:
            logger.warning(f"Failed to delete current user message {message_id_to_process}: {e}. Will try next time if stored.")
    else:
         user_data_for_msg_handling['user_command_message_to_keep'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
    await firestore_service.set_user_data(user_id, user_data_for_msg_handling)

def auto_delete_message_decorator(is_command_to_keep: bool = False):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user and update.message:
                 await _store_and_try_delete_message(update, update.effective_user.id, is_command_to_keep)
            return await func(update, context)
        return wrapper
    return decorator

async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    selected_id = user_data_loc.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data_loc.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key
    
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data_loc.get('selected_api_type') != info.get("api_type"):
                await firestore_service.set_user_data(user_id, {'selected_api_type': info.get("api_type")})
            return key
            
    default_cfg = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    await firestore_service.set_user_data(user_id, {
        'selected_model_id': default_cfg["id"], 
        'selected_api_type': default_cfg["api_type"]
    })
    return CONFIG.DEFAULT_MODEL_KEY

async def get_selected_model_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    model_key = await get_current_model_key(user_id, user_data)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY])

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    current_model_k_loc = await get_current_model_key(user_id, user_data_loc)
    mode_k_loc = user_data_loc.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)

    if mode_k_loc not in AI_MODES:
        mode_k_loc = CONFIG.DEFAULT_AI_MODE_KEY
        await firestore_service.set_user_data(user_id, {'current_ai_mode': mode_k_loc})
    
    if current_model_k_loc == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])
        
    return AI_MODES.get(mode_k_loc, AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str) or len(text) <= max_length:
        return str(text), False

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)

    if adjusted_max_length <= 0:
        return text[:max_length - len("...")] + "...", True 
        
    truncated_text = text[:adjusted_max_length]
    
    for separator in ['\n\n', '. ', '! ', '? ', '\n', ' ']:
        position = truncated_text.rfind(separator)
        if position != -1:
            actual_cut_position = position + (len(separator) if separator != ' ' else 0)
            if actual_cut_position > 0 and actual_cut_position > adjusted_max_length * 0.3:
                 return text[:actual_cut_position].strip() + suffix, True
                 
    return text[:adjusted_max_length].strip() + suffix, True

def is_user_profi_subscriber(subscription_details: Dict[str, Any]) -> bool:
    if not subscription_details: return False
    if subscription_details.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY and \
       subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(subscription_details['valid_until'])
            if valid_until_dt.tzinfo is None:
                valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc).date() <= valid_until_dt.date()
        except ValueError:
            logger.warning(f"Invalid date format for 'valid_until': {subscription_details['valid_until']}")
            return False
    return False

async def get_user_actual_limit_for_model(
    user_id: int, 
    model_key: str, 
    user_data: Optional[Dict[str, Any]] = None, 
    bot_data_cache: Optional[Dict[str, Any]] = None
) -> int:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: return 0

    bot_data_loc = bot_data_cache if bot_data_cache is not None else await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subscriptions)

    limit_type = model_cfg.get("limit_type")
    base_limit = 0

    if limit_type == "daily_free":
        base_limit = model_cfg.get("limit", 0)
    elif limit_type == "subscription_or_daily_free":
        base_limit = model_cfg.get("subscription_daily_limit", 0) if is_profi_user \
                     else model_cfg.get("limit_if_no_subscription", 0)
    elif limit_type == "subscription_custom_pro":
        base_limit = model_cfg.get("subscription_daily_limit", 0) if is_profi_user \
                     else model_cfg.get("limit_if_no_subscription", 0)
    elif not model_cfg.get("is_limited", False):
        return float('inf')
    else:
        return 0

    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False):
        base_limit += user_data_loc.get('news_bonus_uses_left', 0)
        
    return base_limit

async def check_and_log_request_attempt(user_id: int, model_key: str) -> Tuple[bool, str, int]:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_cfg or not model_cfg.get("is_limited"):
        return True, "", 0

    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subscriptions)

    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False) and \
       user_data_loc.get('news_bonus_uses_left', 0) > 0:
        return True, "bonus_available", 0

    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    model_usage_info = user_daily_counts.get(model_key, {'date': '', 'count': 0})

    if model_usage_info['date'] != today_str:
        model_usage_info = {'date': today_str, 'count': 0}

    current_usage_count = model_usage_info['count']
    
    limit_for_comparison = 0 
    if model_cfg.get("limit_type") == "daily_free":
        limit_for_comparison = model_cfg.get("limit", 0)
    elif model_cfg.get("limit_type") == "subscription_or_daily_free":
        limit_for_comparison = model_cfg.get("subscription_daily_limit", 0) if is_profi_user \
                               else model_cfg.get("limit_if_no_subscription", 0)
    elif model_cfg.get("limit_type") == "subscription_custom_pro":
        limit_for_comparison = model_cfg.get("subscription_daily_limit", 0) if is_profi_user \
                               else model_cfg.get("limit_if_no_subscription", 0)

    if current_usage_count >= limit_for_comparison:
        display_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
        message_parts = [f"Достигнут дневной лимит ({current_usage_count}/{display_limit}) для модели «{model_cfg['name']}». Модель была изменена на «{AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]['name']}»."]
        
        default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
        await firestore_service.set_user_data(user_id, {
            'selected_model_id': default_model_config["id"],
            'selected_api_type': default_model_config.get("api_type")
        })

        if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and not is_profi_user:
            bonus_model_name = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY, {}).get("name", "бонусной модели")
            if not user_data_loc.get('claimed_news_bonus', False):
                message_parts.append(f'💡 Подписка на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a> даст вам бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для модели {bonus_model_name})!')
            elif user_data_loc.get('news_bonus_uses_left', 0) == 0:
                message_parts.append(f"ℹ️ Бонус с <a href='{CONFIG.NEWS_CHANNEL_LINK}'>канала новостей</a> для модели {bonus_model_name} уже был использован.")
        
        if not is_profi_user:
            message_parts.append("Попробуйте снова завтра или рассмотрите возможность оформления <a href='https://t.me/gemini_oracle_bot?start=subscribe'>Profi подписки</a> для увеличения лимитов.")
        
        if model_usage_info['date'] == today_str and user_daily_counts.get(model_key) != model_usage_info:
             user_daily_counts[model_key] = model_usage_info
             all_user_daily_counts[str(user_id)] = user_daily_counts
             await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})

        return False, "\n".join(message_parts), current_usage_count

    if model_usage_info['date'] == today_str and user_daily_counts.get(model_key) != model_usage_info:
        user_daily_counts[model_key] = model_usage_info
        all_user_daily_counts[str(user_id)] = user_daily_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
        
    return True, "", current_usage_count

async def increment_request_count(user_id: int, model_key: str):
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"):
        return

    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subscriptions)

    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False):
        bonus_uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        if bonus_uses_left > 0:
            await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_uses_left - 1})
            logger.info(f"User {user_id} consumed a news channel bonus use for model {model_key}. Left: {bonus_uses_left - 1}")
            return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    
    model_usage_info = user_daily_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_usage_info['date'] != today_str:
        model_usage_info = {'date': today_str, 'count': 0}
    
    model_usage_info['count'] += 1
    user_daily_counts[model_key] = model_usage_info
    all_user_daily_counts[str(user_id)] = user_daily_counts
    
    await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
    logger.info(f"Incremented daily count for user {user_id}, model {model_key} to {model_usage_info['count']}.")

# --- ФУНКЦИИ МЕНЮ ---
def is_menu_button_text(text: str) -> bool:
    if text in ["⬅️ Назад", "🏠 Главное меню"]:
        return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data.get("items", []):
            if item["text"] == text:
                return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu_config = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    keyboard_rows: List[List[KeyboardButton]] = []
    items = menu_config["items"]

    if menu_key in [BotConstants.MENU_MAIN, BotConstants.MENU_MODELS_SUBMENU]:
        for i in range(0, len(items), 2):
            keyboard_rows.append(
                [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            )
    else:
        for item in items:
            keyboard_rows.append([KeyboardButton(item["text"])])
            
    if menu_config.get("is_submenu", False):
        navigation_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"):
            navigation_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(navigation_row)
        
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found in MENU_STRUCTURE. Defaulting to main menu for user {user_id}.")
        await update.message.reply_text(
            "Ошибка: Запрошенное меню не найдено. Показываю главное меню.",
            reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN)
        )
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        return

    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    await update.message.reply_text(
        menu_cfg["title"],
        reply_markup=generate_menu_keyboard(menu_key),
        disable_web_page_preview=True
    )
    logger.info(f"User {user_id} was shown menu '{menu_key}'.")

# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---
@auto_delete_message_decorator(is_command_to_keep=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    
    user_data_loc = await firestore_service.get_user_data(user_id)
    updates_to_user_data = {}

    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc:
        updates_to_user_data['current_menu'] = BotConstants.MENU_MAIN
        
    default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
    if 'selected_api_type' not in user_data_loc:
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)
    model_details_res = AVAILABLE_TEXT_MODELS.get(current_model_key_val)

    mode_name = mode_details_res['name'] if mode_details_res else "Неизвестный режим"
    model_name = model_details_res['name'] if model_details_res else "Неизвестная модель"

    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_name}</b>\n"
        f"⚙️ Активная модель: <b>{model_name}</b>\n\n"
        "Я готов к вашим запросам! Используйте текстовые сообщения для общения с ИИ "
        "или кнопки меню для навигации и настроек."
    )
    await update.message.reply_text(
        greeting_message,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN),
        disable_web_page_preview=True
    )
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    logger.info(f"User {user_id} ({user_first_name}) started or restarted the bot.")

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await show_menu(update, user_id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

@auto_delete_message_decorator()
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription(update, update.effective_user.id)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ ---
async def show_limits(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi = is_user_profi_subscriber(user_subscriptions)
    
    subscription_status_display = "Бесплатный"
    if is_profi:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
            if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            subscription_status_display = f"Профи (активна до {valid_until_dt.strftime('%d.%m.%Y')})"
        except (ValueError, KeyError):
            subscription_status_display = "Профи (ошибка в дате)"
    elif user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY:
        try:
            expired_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
            if expired_dt.tzinfo is None: expired_dt = expired_dt.replace(tzinfo=timezone.utc)
            subscription_status_display = f"Профи (истекла {expired_dt.strftime('%d.%m.%Y')})"
        except (ValueError, KeyError):
             subscription_status_display = "Профи (истекла, ошибка в дате)"

    parts = [f"<b>📊 Ваши текущие лимиты</b> (Статус: <b>{subscription_status_display}</b>)\n"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info['date'] == today_str else 0
            
            actual_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
            
            bonus_notification = ""
            if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
               not is_profi and \
               user_data_loc.get('claimed_news_bonus', False):
                bonus_left = user_data_loc.get('news_bonus_uses_left', 0)
                if bonus_left > 0:
                    bonus_notification = f" (включая <b>{bonus_left}</b> бонусных)"
            
            limit_display = '∞' if actual_limit == float('inf') else str(actual_limit)
            parts.append(f"▫️ {model_config['name']}: <b>{current_day_usage} / {limit_display}</b>{bonus_notification}")

    parts.append("")
    
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    bonus_model_name_display = bonus_model_cfg['name'] if bonus_model_cfg else "бонусной модели"

    if not user_data_loc.get('claimed_news_bonus', False):
        parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name_display})! Нажмите «🎁 Бонус» в меню для активации.')
    elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций с канала новостей для модели {bonus_model_name_display}.")
    else:
        parts.append(f"ℹ️ Бонус с канала новостей для модели {bonus_model_name_display} был использован.")
        
    if not is_profi:
        parts.append("\n💎 Хотите больше лимитов и доступ ко всем моделям? Оформите подписку Profi через команду /subscribe или соответствующую кнопку в меню.")
        
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_BONUS_SUBMENU)
    current_menu_config = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    reply_menu_key = current_menu_config.get("parent", BotConstants.MENU_MAIN) if current_menu_config.get("is_submenu") else BotConstants.MENU_MAIN

    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text(
            "К сожалению, настройка бонусной модели в данный момент неисправна. Пожалуйста, сообщите администратору.",
            reply_markup=generate_menu_keyboard(reply_menu_key)
        )
        return
        
    bonus_model_name_display = bonus_model_config['name']

    if user_data_loc.get('claimed_news_bonus', False):
        uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        reply_text = f"Вы уже активировали бонус за подписку на новостной канал. "
        if uses_left > 0:
            reply_text += f"У вас осталось: <b>{uses_left}</b> бонусных генераций для модели {bonus_model_name_display}."
        else:
            reply_text += f"Бонусные генерации для модели {bonus_model_name_display} уже были использованы."
        await update.message.reply_text(
            reply_text, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(reply_menu_key),
            disable_web_page_preview=True
        )
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await firestore_service.set_user_data(user_id, {
                'claimed_news_bonus': True, 
                'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS
            })
            success_text = (
                f'🎉 Отлично! Спасибо за подписку на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>! '
                f"Вам начислен бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> "
                f"генераций для модели {bonus_model_name_display}."
            )
            await update.message.reply_text(
                success_text, 
                parse_mode=ParseMode.HTML, 
                reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN), 
                disable_web_page_preview=True
            )
            await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        else:
            fail_text = (
                f'Для получения бонуса, пожалуйста, сначала подпишитесь на наш новостной канал '
                f'<a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>. '
                f'После подписки, вернитесь сюда и снова нажмите кнопку «🎁 Получить» в меню «Бонус».'
            )
            inline_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 Перейти на канал {CONFIG.NEWS_CHANNEL_USERNAME}", url=CONFIG.NEWS_CHANNEL_LINK)]
            ])
            await update.message.reply_text(
                fail_text, 
                parse_mode=ParseMode.HTML, 
                reply_markup=inline_keyboard, 
                disable_web_page_preview=True
            )
    except telegram.error.TelegramError as e:
        logger.error(f"Telegram API error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла ошибка при проверке вашей подписки на канал. Пожалуйста, попробуйте еще раз немного позже.",
            reply_markup=generate_menu_keyboard(reply_menu_key)
        )
    except Exception as e:
        logger.error(f"Unexpected error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже или свяжитесь с поддержкой, если проблема сохранится.",
            reply_markup=generate_menu_keyboard(reply_menu_key)
        )

async def show_subscription(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_active_profi = is_user_profi_subscriber(user_subscriptions)

    parts = ["<b>💎 Информация о подписке Profi</b>"]

    if is_active_profi:
        try:
            valid_until_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
            if valid_until_dt.tzinfo is None: valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            parts.append(f"\n✅ Ваша подписка Profi <b>активна</b> до <b>{valid_until_dt.strftime('%d.%m.%Y')}</b>.")
            parts.append("Вам доступны расширенные лимиты и все модели ИИ.")
        except (ValueError, KeyError):
            parts.append("\n⚠️ Обнаружена активная подписка Profi, но есть проблема с отображением даты окончания. Пожалуйста, обратитесь в поддержку.")
    else:
        if user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY:
            try:
                expired_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
                if expired_dt.tzinfo is None: expired_dt = expired_dt.replace(tzinfo=timezone.utc)
                parts.append(f"\n⚠️ Ваша подписка Profi истекла <b>{expired_dt.strftime('%d.%m.%Y')}</b>.")
            except (ValueError, KeyError):
                parts.append("\n⚠️ Ваша подписка Profi истекла (ошибка в дате).")

        parts.append("\nПодписка <b>Profi</b> предоставляет следующие преимущества:")
        parts.append("▫️ Значительно увеличенные дневные лимиты на использование всех моделей ИИ.")
        
        pro_models = [m_cfg["name"] for m_key, m_cfg in AVAILABLE_TEXT_MODELS.items() 
                      if m_cfg.get("limit_type") == "subscription_custom_pro" and m_cfg.get("limit_if_no_subscription", -1) == 0]
        if pro_models:
            parts.append(f"▫️ Эксклюзивный доступ к продвинутым моделям: {', '.join(pro_models)}.")
        else:
             parts.append(f"▫️ Доступ к специальным моделям, требующим подписку.")

        parts.append("\nДля оформления или продления подписки Profi, пожалуйста, используйте команду /subscribe "
                     "или соответствующую кнопку «💎 Купить» в меню «Подписка».")

    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_SUBSCRIPTION_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def show_help(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "Я ваш многофункциональный ИИ-ассистент. Вот как со мной работать:\n\n"
        "1.  <b>Запросы к ИИ</b>: Просто напишите ваш вопрос или задачу в чат. Я постараюсь ответить, используя текущие настройки агента и модели.\n\n"
        "2.  <b>Меню</b>: Для доступа ко всем функциям используйте кнопки меню:\n"
        "    ▫️ «<b>🤖 Агенты ИИ</b>»: Выберите роль или специализацию для ИИ (например, 'Универсальный', 'Творческий'). Это влияет на стиль и направленность ответов.\n"
        "    ▫️ «<b>⚙️ Модели ИИ</b>»: Переключайтесь между доступными языковыми моделями. Разные модели могут иметь разные сильные стороны и лимиты.\n"
        "    ▫️ «<b>📊 Лимиты</b>»: Проверьте ваши текущие дневные лимиты использования для каждой модели.\n"
        "    ▫️ «<b>🎁 Бонус</b>»: Получите бонусные генерации за подписку на наш новостной канал.\n"
        "    ▫️ «<b>💎 Подписка</b>»: Узнайте о преимуществах Profi подписки и как ее оформить для расширения возможностей.\n"
        "    ▫️ «<b>❓ Помощь</b>»: Этот раздел справки.\n\n"
        "3.  <b>Основные команды</b> (дублируют функции меню):\n"
        "    ▫️ /start - Перезапуск бота и отображение приветственного сообщения.\n"
        "    ▫️ /menu - Открыть главное меню.\n"
        "    ▫️ /usage - Показать текущие лимиты.\n"
        "    ▫️ /subscribe - Информация о Profi подписке.\n"
        "    ▫️ /bonus - Получить бонус за подписку на канал.\n"
        "    ▫️ /help - Показать эту справку.\n\n"
        "Если у вас возникнут вопросы или проблемы, не стесняйтесь обращаться в поддержку (если доступно) или попробуйте перезапустить бота командой /start."
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_HELP_SUBMENU)
    await update.message.reply_text(
        help_text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    button_text = update.message.text.strip()

    if not is_menu_button_text(button_text):
        return 

    try:
        await update.message.delete()
        logger.info(f"Deleted menu button message '{button_text}' from user {user_id}.")
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}' from user {user_id}: {e}")

    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    logger.info(f"User {user_id} pressed menu button '{button_text}' while in menu '{current_menu_key}'.")

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key, user_data_loc)
        return 
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN, user_data_loc)
        return

    action_item_found = None
    search_menus_order = [current_menu_key] + [key for key in MENU_STRUCTURE if key != current_menu_key]

    for menu_key_to_search in search_menus_order:
        menu_config_to_search = MENU_STRUCTURE.get(menu_key_to_search, {})
        for item in menu_config_to_search.get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                action_origin_menu_key = menu_key_to_search 
                break
        if action_item_found:
            break
    
    if not action_item_found:
        logger.warning(f"Menu button '{button_text}' pressed by user {user_id} was not matched to any action "
                       f"despite is_menu_button_text() returning True. Current menu was '{current_menu_key}'.")
        await update.message.reply_text(
            "Произошла ошибка при обработке вашего выбора. Пожалуйста, попробуйте еще раз или вернитесь в главное меню.",
            reply_markup=generate_menu_keyboard(current_menu_key)
        )
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]
    return_menu_key_after_action = MENU_STRUCTURE.get(action_origin_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
    if action_origin_menu_key == BotConstants.MENU_MAIN:
        return_menu_key_after_action = BotConstants.MENU_MAIN

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target, user_data_loc)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        response_message_text = "⚠️ Произошла ошибка: Выбранный агент не найден или не доступен."
        if action_target in AI_MODES and action_target != "gemini_pro_custom_mode":
            await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
            agent_details = AI_MODES[action_target]
            response_message_text = (f"🤖 Агент ИИ изменен на: <b>{agent_details['name']}</b>.\n"
                                     f"{agent_details.get('welcome', 'Готов к работе!')}")
        await update.message.reply_text(
            response_message_text, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(return_menu_key_after_action), 
            disable_web_page_preview=True
        )
        await firestore_service.set_user_data(user_id, {'current_menu': return_menu_key_after_action})

    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        response_message_text = "⚠️ Произошла ошибка: Выбранная модель не найдена или не доступна."
        if action_target in AVAILABLE_TEXT_MODELS:
            model_info = AVAILABLE_TEXT_MODELS[action_target]
            update_payload = {
                'selected_model_id': model_info["id"], 
                'selected_api_type': model_info["api_type"]
            }
            if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and \
               user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
                update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
                logger.info(f"User {user_id} selected model {action_target}, AI mode reset from gemini_pro_custom_mode to default.")

            await firestore_service.set_user_data(user_id, update_payload)
            user_data_loc.update(update_payload)

            bot_data_cache = await firestore_service.get_bot_data()
            today_string_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            user_model_counts = bot_data_cache.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})
            model_daily_usage = user_model_counts.get(action_target, {'date': '', 'count': 0})
            current_usage_string = str(model_daily_usage['count']) if model_daily_usage['date'] == today_string_val else "0"
            
            actual_limit_string = await get_user_actual_limit_for_model(user_id, action_target, user_data_loc, bot_data_cache)
            limit_display_string = '∞' if actual_limit_string == float('inf') else str(actual_limit_string)
            
            response_message_text = (f"⚙️ Модель ИИ изменена на: <b>{model_info['name']}</b>.\n"
                                     f"Ваш текущий дневной лимит для этой модели: {current_usage_string} / {limit_display_string}.")
        
        await update.message.reply_text(
            response_message_text, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(return_menu_key_after_action), 
            disable_web_page_preview=True
        )
        await firestore_service.set_user_data(user_id, {'current_menu': return_menu_key_after_action})

    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS:
        await claim_news_bonus_logic(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_SUBSCRIPTION:
        await show_subscription(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action type '{action_type}' for button '{button_text}' (target: '{action_target}') by user {user_id}.")
        await update.message.reply_text(
            "Выбранное действие не распознано. Пожалуйста, попробуйте еще раз.",
            reply_markup=generate_menu_keyboard(current_menu_key)
        )

# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        return

    user_message_text = update.message.text.strip()
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)

    if is_menu_button_text(user_message_text):
        logger.debug(f"User {user_id} sent menu button text '{user_message_text}' that reached handle_text. Explicitly ignoring.")
        return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        await update.message.reply_text(
            "Ваш запрос слишком короткий. Пожалуйста, сформулируйте его более подробно.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN))
        )
        return

    logger.info(f"User {user_id} sent AI request (first 100 chars): '{user_message_text[:100]}...'")
    
    user_data_cache = await firestore_service.get_user_data(user_id) 
    current_model_key_val = await get_current_model_key(user_id, user_data_cache)
    
    can_proceed, limit_message, _ = await check_and_log_request_attempt(user_id, current_model_key_val)
    if not can_proceed:
        await update.message.reply_text(
            limit_message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
            disable_web_page_preview=True
        )
        user_data_cache = await firestore_service.get_user_data(user_id)
        await update.message.reply_text(
             "Пожалуйста, выберите другую модель или попробуйте снова позже.",
             reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN))
        )
        return

    current_model_key_val = await get_current_model_key(user_id, user_data_cache)
    ai_service = get_ai_service(current_model_key_val)

    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{current_model_key_val}' for user {user_id}.")
        await update.message.reply_text(
            "Произошла критическая ошибка при выборе AI модели. Пожалуйста, сообщите администратору или попробуйте /start.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN))
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    mode_details = await get_current_mode_details(user_id, user_data_cache)
    system_prompt = mode_details.get('prompt', '')
    
    try:
        response_text = await ai_service.generate_response(system_prompt, user_message_text)
        response_text_truncated, was_truncated = smart_truncate(response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
        
        if was_truncated:
            logger.info(f"Response for user {user_id} was truncated from {len(response_text)} to {len(response_text_truncated)} chars.")
        
        await update.message.reply_text(
            response_text_truncated,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)),
            disable_web_page_preview=True
        )
        
        await increment_request_count(user_id, current_model_key_val)
        logger.info(f"Successfully processed AI request for user {user_id} with model {current_model_key_val}.")
        
    except Exception as e:
        logger.error(f"Error generating AI response for user {user_id} with model {current_model_key_val}: {e}", exc_info=True)
        error_message = (
            f"Произошла ошибка при обработке вашего запроса: {str(e)}.\n"
            "Пожалуйста, попробуйте снова или выберите другую модель ИИ."
        )
        await update.message.reply_text(
            error_message,
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN))
        )

# --- ГЛАВНАЯ ФУНКЦИЯ И ЗАПУСК БОТА ---
async def main():
    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", open_menu_command))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("subscribe", subscribe_info_command))
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    try:
        logger.info("Starting bot polling...")
        await app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Critical error in bot polling: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Failed to start bot: {e}", exc_info=True)
