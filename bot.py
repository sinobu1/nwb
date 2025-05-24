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
import google.generativeai as genai
import google.api_core.exceptions
import requests
import logging
import traceback
import os
import asyncio
import nest_asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, Union, List
import uuid
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient
from abc import ABC, abstractmethod

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# --- КОНФИГУРАЦИЯ ---
class AppConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
    CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152"))
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"

    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    # Обновленные лимиты
    DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
    # ИЗМЕНЕНО: Добавлено 25 бесплатных попыток для GPT-4o mini
    DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 25

    # Логика бонусов за канал убрана для упрощения в пользу гемов
    # NEWS_CHANNEL_USERNAME = "@timextech"
    # NEWS_CHANNEL_LINK = "https://t.me/timextech"
    # NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
    # NEWS_CHANNEL_BONUS_GENERATIONS = 1

    DEFAULT_AI_MODE_KEY = "universal_ai_basic"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"


CONFIG = AppConfig()

# Глобальные переменные для ключей API
_API_KEYS_PROVIDER = {
    "CUSTOM_GEMINI_PRO_API_KEY": CONFIG.CUSTOM_GEMINI_PRO_API_KEY,
    "CUSTOM_GROK_3_API_KEY": CONFIG.CUSTOM_GROK_3_API_KEY,
    "CUSTOM_GPT4O_MINI_API_KEY": CONFIG.CUSTOM_GPT4O_MINI_API_KEY,
}


# --- КОНСТАНТЫ ПРИЛОЖЕНИЯ ---
class BotConstants:
    FS_USERS_COLLECTION = "users"
    FS_BOT_DATA_COLLECTION = "bot_data"
    FS_BOT_DATA_DOCUMENT = "data"
    # ИЗМЕНЕНО: Ключ для хранения дневных лимитов
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"
    # ИЗМЕНЕНО: Ключ для баланса гемов
    FS_GEMS_BALANCE_KEY = "gems_balance"

    MENU_MAIN = "main_menu"
    MENU_AI_MODES_SUBMENU = "ai_modes_submenu"
    MENU_MODELS_SUBMENU = "models_submenu"
    MENU_LIMITS_SUBMENU = "limits_submenu"
    # ИЗМЕНЕНО: Меню покупки гемов
    MENU_GEMS_STORE_SUBMENU = "gems_store_submenu"
    MENU_HELP_SUBMENU = "help_submenu"

    CALLBACK_ACTION_SUBMENU = "submenu"
    CALLBACK_ACTION_SET_AGENT = "set_agent"
    CALLBACK_ACTION_SET_MODEL = "set_model"
    CALLBACK_ACTION_SHOW_LIMITS = "show_limits"
    # ИЗМЕНЕНО: Действие для покупки гемов
    CALLBACK_ACTION_BUY_GEMS = "buy_gems"
    CALLBACK_ACTION_SHOW_HELP = "show_help"

    API_TYPE_GOOGLE_GENAI = "google_genai"
    API_TYPE_CUSTOM_HTTP = "custom_http_api"


# --- ОПРЕДЕЛЕНИЯ РЕЖИМОВ И МОДЕЛЕЙ ---
AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент от Google."
            "Твоя цель — эффективно помогать пользователю с широким спектром задач."
            # ... (остальной промпт без изменений)
        ),
        "welcome": "Активирован агент 'Универсальный'. Какой у вас запрос?"
    },
    # ... (остальные режимы без изменений)
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini."
            # ... (остальной промпт без изменений)
        ),
        "welcome": "Агент 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}

# ИЗМЕНЕНО: Структура моделей для поддержки гемов
AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY, "gem_cost": 0
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY, "gem_cost": 0
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True, "free_daily_limit": 0, "gem_cost": 2.5
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True, "free_daily_limit": 0, "gem_cost": 2.5
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY, "gem_cost": 0.5
    }
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["id"]

# ИЗМЕНЕНО: Структура меню
MENU_STRUCTURE = {
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню", "items": [
            {"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU},
            {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU},
            {"text": "📊 Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_LIMITS_SUBMENU},
            {"text": "💎 Купить Гемы", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_GEMS_STORE_SUBMENU},
            {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}
        ], "parent": None, "is_submenu": False
    },
    BotConstants.MENU_AI_MODES_SUBMENU: {
        "title": "Выберите агент ИИ", "items": [
            {"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_SET_AGENT, "target": key}
            for key, mode in AI_MODES.items()
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_MODELS_SUBMENU: {
        "title": "Выберите модель ИИ", "items": [
            {"text": model["name"], "action": BotConstants.CALLBACK_ACTION_SET_MODEL, "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_LIMITS_SUBMENU: {"title": "Ваши лимиты", "items": [{"text": "📊 Показать", "action": BotConstants.CALLBACK_ACTION_SHOW_LIMITS, "target": "usage"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_GEMS_STORE_SUBMENU: {"title": "Магазин гемов", "items": [{"text": "💎 Купить 100 гемов", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "buy_100_gems"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_HELP_SUBMENU: {"title": "Помощь", "items": [{"text": "❓ Справка", "action": BotConstants.CALLBACK_ACTION_SHOW_HELP, "target": "help"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True}
}

# --- СЕРВИС ДЛЯ РАБОТЫ С FIRESTORE ---
class FirestoreService:
    # ... (класс без изменений)
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


firestore_service = FirestoreService(
    cert_path=CONFIG.FIREBASE_CERT_PATH,
    creds_json_str=CONFIG.FIREBASE_CREDENTIALS_JSON_STR
)

# --- СЕРВИСЫ ДЛЯ РАБОТЫ С AI ---
class BaseAIService(ABC):
    # ... (класс без изменений)
    def __init__(self, model_config: Dict[str, Any]):
        self.model_config = model_config
        self.model_id = model_config["id"]

    @abstractmethod
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        pass


class GoogleGenAIService(BaseAIService):
    # ... (класс без изменений)
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"{system_prompt}\n\n**Запрос:**\n{user_prompt}"
        try:
            model_genai = genai.GenerativeModel(
                self.model_id,
                generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB}
            )
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model_genai.generate_content(full_prompt)
            )
            return response.text.strip() if response.text else "Ответ Google GenAI пуст."
        except google.api_core.exceptions.ResourceExhausted as e:
            logger.error(f"Google GenAI API limit exhausted for model {self.model_id}: {e}")
            return f"Лимит Google API исчерпан: {e}"
        except Exception as e:
            logger.error(f"Google GenAI API error for model {self.model_id}: {e}", exc_info=True)
            return f"Ошибка Google API ({type(e).__name__}) при обращении к {self.model_id}."


class CustomHttpAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        api_key_name = self.model_config.get("api_key_var_name")
        actual_key = _API_KEYS_PROVIDER.get(api_key_name)

        if not actual_key or "YOUR_" in actual_key or not (actual_key.startswith("sk-") or actual_key.startswith("AIzaSy")):
            logger.error(f"Invalid API key for model {self.model_id} (key name: {api_key_name}).")
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."

        headers = {
            "Authorization": f"Bearer {actual_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # ИСПРАВЛЕНО: Упрощенная и унифицированная структура payload для всех кастомных моделей
        messages_payload = []
        if system_prompt:
            messages_payload.append({"role": "system", "content": system_prompt})
        messages_payload.append({"role": "user", "content": user_prompt})

        payload = {
            "messages": messages_payload,
            "model": self.model_id,
            "max_tokens": self.model_config.get("max_tokens", CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB)
        }
        
        endpoint = self.model_config["endpoint"]

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(endpoint, headers=headers, json=payload, timeout=45)
            )
            response.raise_for_status()
            json_resp = response.json()
            logger.debug(f"Raw API response for {self.model_id}: {json_resp}")

            # ИСПРАВЛЕНО: Более универсальная логика извлечения текста ответа
            extracted_text = None
            if 'choices' in json_resp and isinstance(json_resp['choices'], list) and json_resp['choices']:
                message = json_resp['choices'][0].get('message', {})
                if 'content' in message:
                    extracted_text = message['content']

            # Запасные варианты для разных форматов API
            if extracted_text is None:
                if 'text' in json_resp and isinstance(json_resp['text'], str):
                    extracted_text = json_resp['text']
                elif 'output' in json_resp and isinstance(json_resp['output'], str):
                    extracted_text = json_resp['output']
                elif 'response' in json_resp and isinstance(json_resp['response'], str):
                     extracted_text = json_resp['response']

            return extracted_text.strip() if extracted_text else f"Ответ API {self.model_config['name']} не содержит ожидаемого текста."

        except requests.exceptions.HTTPError as e:
            logger.error(f"Custom API HTTPError for {self.model_id} ({endpoint}): {e.response.status_code} - {e.response.text}", exc_info=True)
            return f"Ошибка сети Custom API ({e.response.status_code}) для {self.model_config['name']}."
        except Exception as e:
            logger.error(f"Unexpected Custom API error for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Неожиданная ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."


def get_ai_service(model_key: str) -> Optional[BaseAIService]:
    # ... (функция без изменений)
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        logger.error(f"Configuration for model key '{model_key}' not found.")
        return None
    
    api_type = model_cfg.get("api_type")
    if api_type == BotConstants.API_TYPE_GOOGLE_GENAI:
        return GoogleGenAIService(model_cfg)
    elif api_type == BotConstants.API_TYPE_CUSTOM_HTTP:
        return CustomHttpAIService(model_cfg)
    else:
        logger.error(f"Unknown API type '{api_type}' for model key '{model_key}'.")
        return None

# --- УТИЛИТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    # ... (функция без изменений)
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
    # ... (функция без изменений)
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user and update.message:
                 await _store_and_try_delete_message(update, update.effective_user.id, is_command_to_keep)
            return await func(update, context)
        return wrapper
    return decorator

async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    # ... (функция без изменений)
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
    # ... (функция без изменений)
    model_key = await get_current_model_key(user_id, user_data)
    return AVAILABLE_TEXT_MODELS.get(model_key, AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY])

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # ... (функция без изменений, удалена спец. логика для gemini_pro_custom_mode)
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    mode_k_loc = user_data_loc.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)

    if mode_k_loc not in AI_MODES:
        mode_k_loc = CONFIG.DEFAULT_AI_MODE_KEY
        await firestore_service.set_user_data(user_id, {'current_ai_mode': mode_k_loc})
        
    return AI_MODES.get(mode_k_loc, AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])


def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    # ... (функция без изменений)
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

# ИЗМЕНЕНО: Новая функция для проверки лимитов и гемов
async def check_and_log_request_attempt(user_id: int, model_key: str) -> Tuple[bool, str, str]:
    """
    Проверяет, может ли пользователь сделать запрос.
    Возвращает: (Может_ли_продолжать, Сообщение_пользователю, Тип_списания)
    Тип_списания: 'free' или 'gems'
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_cfg or not model_cfg.get("is_limited"):
        return True, "", "free"  # Нелимитированная модель

    # Получение данных
    user_data = await firestore_service.get_user_data(user_id)
    bot_data = await firestore_service.get_bot_data()
    
    # Получение дневного использования
    all_user_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_counts.get(str(user_id), {})
    model_usage_info = user_daily_counts.get(model_key, {'date': '', 'count': 0})
    
    current_usage = model_usage_info['count'] if model_usage_info['date'] == today_str else 0
    
    # 1. Проверка бесплатных попыток
    free_limit = model_cfg.get("free_daily_limit", 0)
    if current_usage < free_limit:
        return True, "", "free"

    # 2. Проверка стоимости в гемах
    gem_cost = model_cfg.get("gem_cost", 0)
    if gem_cost > 0:
        user_gems = user_data.get(BotConstants.FS_GEMS_BALANCE_KEY, 0)
        if user_gems >= gem_cost:
            return True, "", "gems"
        else:
            # Недостаточно гемов
            msg = (
                f"Недостаточно гемов для использования модели «{model_cfg['name']}».\n"
                f"Требуется: <b>{gem_cost}</b> 💎, у вас на балансе: <b>{user_gems}</b> 💎.\n\n"
                f"Вы можете пополнить баланс через команду /buy или меню «💎 Купить Гемы»."
            )
            return False, msg, ""
    
    # 3. Если бесплатных попыток нет и модель не платная (gem_cost=0)
    # Это означает, что лимит просто исчерпан
    display_limit = free_limit
    message = (
        f"Достигнут дневной лимит ({current_usage}/{display_limit}) для модели «{model_cfg['name']}».\n"
        f"Попробуйте снова завтра или выберите другую модель."
    )
    return False, message, ""


# ИЗМЕНЕНО: Новая функция для списания гемов
async def deduct_gems(user_id: int, model_key: str):
    """Списывает гемы за использование модели."""
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: return
    
    gem_cost = model_cfg.get("gem_cost", 0)
    if gem_cost <= 0: return

    user_data = await firestore_service.get_user_data(user_id)
    current_gems = user_data.get(BotConstants.FS_GEMS_BALANCE_KEY, 0)
    new_balance = max(0, current_gems - gem_cost)
    
    await firestore_service.set_user_data(user_id, {BotConstants.FS_GEMS_BALANCE_KEY: new_balance})
    logger.info(f"User {user_id} was charged {gem_cost} gems for using {model_key}. New balance: {new_balance}")


async def increment_request_count(user_id: int, model_key: str):
    """Инкрементирует только дневной счетчик использования."""
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"):
        return

    bot_data = await firestore_service.get_bot_data()
    all_user_daily_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    # ... (функция без изменений)
    if text in ["⬅️ Назад", "🏠 Главное меню"]:
        return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data.get("items", []):
            if item["text"] == text:
                return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    # ... (функция без изменений)
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
    # ... (функция без изменений)
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main menu for user {user_id}.")
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

    # Инициализация данных пользователя
    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if BotConstants.FS_GEMS_BALANCE_KEY not in user_data_loc:
        updates_to_user_data[BotConstants.FS_GEMS_BALANCE_KEY] = 0  # Начальный баланс гемов
    
    default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_details = await get_selected_model_details(user_id, user_data_loc)
    mode_details = await get_current_mode_details(user_id, user_data_loc)
    user_gems = user_data_loc.get(BotConstants.FS_GEMS_BALANCE_KEY, 0)

    # ИЗМЕНЕНО: Приветственное сообщение с балансом гемов
    greeting_message = (
        f"👋 Привет, {user_first_name}!\n\n"
        f"🤖 Текущий агент: <b>{mode_details['name']}</b>\n"
        f"⚙️ Активная модель: <b>{current_model_details['name']}</b>\n"
        f"💎 Ваш баланс: <b>{user_gems} гемов</b>\n\n"
        "Я готов к вашим запросам! Используйте текстовые сообщения для общения с ИИ "
        "или кнопки меню для навигации и настроек."
    )
    await update.message.reply_text(
        greeting_message,
        parse_mode=ParseMode.HTML,
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN)
    )
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    logger.info(f"User {user_id} ({user_first_name}) started the bot.")

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

# ИЗМЕНЕНО: Новая команда для покупки гемов
@auto_delete_message_decorator()
async def buy_gems_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_gems_invoice(update, context)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ ---

async def show_limits(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    bot_data = await firestore_service.get_bot_data()
    
    user_gems = user_data.get(BotConstants.FS_GEMS_BALANCE_KEY, 0)
    
    parts = [f"<b>📊 Ваши текущие лимиты и баланс</b>\n💎 Баланс: <b>{user_gems} гемов</b>\n"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_counts_today = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited"):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info['date'] == today_str else 0
            
            free_limit = model_config.get("free_daily_limit", 0)
            gem_cost = model_config.get("gem_cost", 0)

            limit_str = f"{current_day_usage} / {free_limit}"
            cost_str = ""
            if gem_cost > 0:
                cost_str = f" (<b>{gem_cost} 💎</b>/запрос после бесплатных)" if free_limit > 0 else f" (<b>{gem_cost} 💎</b>/запрос)"
            
            parts.append(f"▫️ {model_config['name']}: {limit_str}{cost_str}")

    parts.append("\n💎 Пополнить баланс можно через команду /buy или меню.")
        
    current_menu = user_data.get('current_menu', BotConstants.MENU_LIMITS_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )


async def show_help(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    # ИЗМЕНЕНО: Обновленный текст справки
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "Я ваш многофункциональный ИИ-ассистент. Вот как со мной работать:\n\n"
        "1.  <b>Запросы к ИИ</b>: Просто напишите ваш вопрос или задачу в чат. Я отвечу, используя текущие настройки.\n\n"
        "2.  <b>Экономика гемов 💎</b>: Некоторые продвинутые модели требуют для работы 'гемы'.\n"
        "    - У части моделей есть бесплатные дневные лимиты.\n"
        "    - После исчерпания лимитов или для платных моделей используются гемы с вашего баланса.\n\n"
        "3.  <b>Меню</b>: Для доступа ко всем функциям используйте кнопки:\n"
        "    ▫️ «<b>🤖 Агенты ИИ</b>»: Выберите роль для ИИ (влияет на стиль ответов).\n"
        "    ▫️ «<b>⚙️ Модели ИИ</b>»: Переключайтесь между языковыми моделями.\n"
        "    ▫️ «<b>📊 Лимиты</b>»: Проверьте ваш баланс гемов и дневные лимиты.\n"
        "    ▫️ «<b>💎 Купить Гемы</b>»: Пополните свой баланс гемов.\n"
        "    ▫️ «<b>❓ Помощь</b>»: Этот раздел справки.\n\n"
        "4.  <b>Основные команды</b>:\n"
        "    ▫️ /start - Перезапуск бота.\n"
        "    ▫️ /menu - Открыть главное меню.\n"
        "    ▫️ /usage - Показать лимиты и баланс.\n"
        "    ▫️ /buy - Купить гемы.\n"
        "    ▫️ /help - Показать эту справку."
    )
    current_menu = user_data.get('current_menu', BotConstants.MENU_HELP_SUBMENU)
    await update.message.reply_text(
        help_text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu),
        disable_web_page_preview=True
    )

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    button_text = update.message.text.strip()

    if not is_menu_button_text(button_text): return 

    try:
        await update.message.delete()
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}': {e}")

    user_data = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data.get('current_menu', BotConstants.MENU_MAIN)

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key, user_data)
        return 
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN, user_data)
        return

    action_item_found = None
    action_origin_menu_key = current_menu_key
    for menu_key, menu_config in MENU_STRUCTURE.items():
        for item in menu_config.get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                action_origin_menu_key = menu_key
                break
        if action_item_found: break
    
    if not action_item_found:
        logger.warning(f"Menu button '{button_text}' not matched to any action.")
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]
    return_menu_key = MENU_STRUCTURE.get(action_origin_menu_key, {}).get("parent", BotConstants.MENU_MAIN)

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target, user_data)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        agent_details = AI_MODES[action_target]
        response_text = f"🤖 Агент ИИ изменен на: <b>{agent_details['name']}</b>."
        await update.message.reply_text(
            response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key)
        )
        await firestore_service.set_user_data(user_id, {'current_menu': return_menu_key})

    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS[action_target]
        await firestore_service.set_user_data(user_id, {
            'selected_model_id': model_info["id"], 'selected_api_type': model_info["api_type"]
        })
        response_text = f"⚙️ Модель ИИ изменена на: <b>{model_info['name']}</b>."
        await update.message.reply_text(
            response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(return_menu_key)
        )
        await firestore_service.set_user_data(user_id, {'current_menu': return_menu_key})

    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id)
    elif action_type == BotConstants.CALLBACK_ACTION_BUY_GEMS:
        await send_gems_invoice(update, context) # Вызов функции отправки счета
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)


# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text: return
    user_message_text = update.message.text.strip()
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)

    if is_menu_button_text(user_message_text): return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data = await firestore_service.get_user_data(user_id)
        await update.message.reply_text(
            "Ваш запрос слишком короткий.",
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_MAIN))
        )
        return

    logger.info(f"User {user_id} sent AI request: '{user_message_text[:100]}...'")
    
    user_data = await firestore_service.get_user_data(user_id)
    current_model_key = await get_current_model_key(user_id, user_data)
    
    can_proceed, limit_message, charge_type = await check_and_log_request_attempt(user_id, current_model_key)
    
    if not can_proceed:
        await update.message.reply_text(
            limit_message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_MAIN)), 
            disable_web_page_preview=True
        )
        return

    ai_service = get_ai_service(current_model_key)
    if not ai_service:
        await update.message.reply_text("Критическая ошибка при выборе AI модели. Сообщите администратору.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id, user_data)
    system_prompt = mode_details["prompt"]
    
    try:
        ai_response_text = await ai_service.generate_response(system_prompt, user_message_text)
        
        # Списываем ресурсы ПОСЛЕ успешного ответа
        await increment_request_count(user_id, current_model_key)
        if charge_type == "gems":
            await deduct_gems(user_id, current_model_key)

    except Exception as e:
        logger.error(f"Unhandled exception in AI service for model {current_model_key}: {e}", exc_info=True)
        ai_response_text = "Произошла внутренняя ошибка при обработке вашего запроса. Попробуйте позже."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_MAIN)), 
        disable_web_page_preview=True
    )
    logger.info(f"Successfully sent AI response (model: {current_model_key}) to user {user_id}.")


# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---

# НОВАЯ функция для отправки счета на покупку гемов
async def send_gems_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет пользователю счет на покупку 100 гемов."""
    chat_id = update.effective_chat.id
    title = "Покупка Гемов"
    description = "100 гемов для использования продвинутых моделей ИИ"
    # payload - уникальный идентификатор покупки
    payload = f"buy_gems_100_user_{chat_id}_{uuid.uuid4()}"
    currency = "RUB"
    # Цена в копейках (100 рублей = 10000 копеек)
    price = 10000 
    
    prices = [LabeledPrice("100 💎 Гемов", price)]

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN,
        currency=currency,
        prices=prices,
        # need_name=True, # можно раскомментировать, если нужно имя
        # need_phone_number=True, # если нужен телефон
        # need_email=True, # если нужен email
        # is_flexible=False # True, если есть доставка
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # Проверяем, что это покупка гемов
    if "buy_gems" in query.invoice_payload:
        await query.answer(ok=True)
        logger.info(f"PreCheckoutQuery OK for payload: {query.invoice_payload}")
    else:
        await query.answer(ok=False, error_message="Неверный запрос на оплату.")
        logger.warning(f"PreCheckoutQuery FAILED for payload: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload

    logger.info(f"Successful payment from user {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {invoice_payload}")

    # ИЗМЕНЕНО: Логика зачисления гемов
    gems_to_add = 0
    if "buy_gems_100" in invoice_payload:
        gems_to_add = 100
    
    if gems_to_add > 0:
        user_data = await firestore_service.get_user_data(user_id)
        current_gems = user_data.get(BotConstants.FS_GEMS_BALANCE_KEY, 0)
        new_balance = current_gems + gems_to_add
        await firestore_service.set_user_data(user_id, {BotConstants.FS_GEMS_BALANCE_KEY: new_balance})
        
        confirmation_message = (
            f"🎉 Оплата прошла успешно! Вам начислено <b>{gems_to_add} гемов</b>.\n"
            f"Ваш новый баланс: <b>{new_balance} 💎</b>\n\n"
            "Спасибо за поддержку!"
        )
        await update.message.reply_text(confirmation_message, parse_mode=ParseMode.HTML)

        # Уведомление администратору
        if CONFIG.ADMIN_ID:
            try:
                admin_message = (
                    f"🔔 Новая покупка гемов!\n"
                    f"Пользователь: {user_id} (@{update.effective_user.username})\n"
                    f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                    f"Начислено: {gems_to_add} гемов"
                )
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
            except Exception as e:
                logger.error(f"Failed to send payment notification to admin: {e}")
    else:
        logger.warning(f"Could not determine gems to add from payload: {invoice_payload}")
        await update.message.reply_text("Оплата прошла, но произошла ошибка при начислении гемов. Обратитесь в поддержку.")


# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (функция без изменений)
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    if isinstance(update, Update) and update.effective_chat:
        user_data_for_error_reply = {}
        if update.effective_user:
             user_data_for_error_reply = await firestore_service.get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла внутренняя ошибка. Разработчики уже уведомлены. Попробуйте /start.",
                reply_markup=generate_menu_keyboard(user_data_for_error_reply.get('current_menu', BotConstants.MENU_MAIN))
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")

    if CONFIG.ADMIN_ID and isinstance(update, Update) and update.effective_user:
        error_details = (
            f"🤖 Обнаружена ошибка:\n"
            f"Пользователь: ID {update.effective_user.id} (@{update.effective_user.username})\n"
            f"Traceback:\n```\n{tb_string[:3500]}\n```"
        )
        try:
            await context.bot.send_message(CONFIG.ADMIN_ID, error_details, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.error(f"Failed to send detailed error report to admin: {e}")


# --- ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА ---
async def main():
    if CONFIG.GOOGLE_GEMINI_API_KEY and "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY:
        try:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API configured.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API: {e}")
    else:
        logger.warning("Google Gemini API key is missing or invalid.")

    if not firestore_service._db:
        logger.critical("Firestore was NOT initialized! Bot may not work correctly.")

    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).read_timeout(30).connect_timeout(30).build()

    # ИЗМЕНЕНО: Регистрация обработчиков с новой командой /buy
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("buy", buy_gems_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    app.add_error_handler(error_handler)

    # ИЗМЕНЕНО: Обновленный список команд
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Показать лимиты и баланс"),
        BotCommand("buy", "💎 Купить гемы"),
        BotCommand("help", "❓ Справка по боту")
    ]
    try:
        await app.bot.set_my_commands(bot_commands)
        logger.info("Bot commands successfully set.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

    logger.info("Bot is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    asyncio.run(main())
