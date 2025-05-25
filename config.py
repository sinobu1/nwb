# config.py
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

# --- ГЛОБАЛЬНАЯ НАСТРОЙКА ---
nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
class AppConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8185454402:AAEgJLaBSaUSyP9Z_zv76Fn0PtEwltAqga0")
    GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI") # Замените на ваш ключ, если используете
    CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "YOUR_CUSTOM_GEMINI_PRO_API_KEY") # Замените
    CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "YOUR_CUSTOM_GEMINI_PRO_ENDPOINT") # Замените
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "YOUR_CUSTOM_GROK_3_API_KEY") # Замените
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "YOUR_CUSTOM_GPT4O_MINI_API_KEY") # Замените
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "YOUR_PAYMENT_PROVIDER_TOKEN") # Замените

    # --- URL ДЛЯ ВАШЕГО MINI APP ---
    # ВАЖНО: Замените placeholder на реальный URL вашего приложения (например, с GitHub Pages)
    MINI_APP_URL = os.getenv("MINI_APP_URL", "https://sinobu1.github.io/nwb/") # Пример

    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152")) # Ваш ID администратора
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json" # Путь к вашему файлу сертификата Firebase

    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    DEFAULT_FREE_REQUESTS_GEMINI_2_0_FLASH_DAILY = 65
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 50
    DEFAULT_FREE_REQUESTS_CUSTOM_GROK_DAILY = 1
    DEFAULT_FREE_REQUESTS_CUSTOM_GEMINI_PRO_DAILY = 1
    DEFAULT_FREE_REQUESTS_CUSTOM_GPT4O_MINI_DAILY = 10
    
    GEMS_FOR_NEW_USER = 0.0 # Используйте float для гемов
    GEM_PACKAGES = {
        "pack_10_gems": {"gems": 10.0, "price_units": 10000, "currency": "RUB", "title": "✨ 10 Гемов", "description": "Небольшой пакет для старта"},
        "pack_50_gems": {"gems": 50.0, "price_units": 45000, "currency": "RUB", "title": "🌟 50 Гемов", "description": "Средний пакет по выгодной цене"},
        "pack_100_gems": {"gems": 100.0, "price_units": 80000, "currency": "RUB", "title": "💎 100 Гемов", "description": "Большой пакет для активных пользователей"}
    }

    NEWS_CHANNEL_USERNAME = "@timextech" # Ваш новостной канал
    NEWS_CHANNEL_LINK = "https://t.me/timextech"
    NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
    NEWS_CHANNEL_BONUS_GENERATIONS = 1

    DEFAULT_AI_MODE_KEY = "universal_ai_basic"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"

CONFIG = AppConfig()

_API_KEYS_PROVIDER = {
    "CUSTOM_GEMINI_PRO_API_KEY": CONFIG.CUSTOM_GEMINI_PRO_API_KEY,
    "CUSTOM_GROK_3_API_KEY": CONFIG.CUSTOM_GROK_3_API_KEY,
    "CUSTOM_GPT4O_MINI_API_KEY": CONFIG.CUSTOM_GPT4O_MINI_API_KEY,
}

class BotConstants:
    FS_USERS_COLLECTION = "users"
    FS_BOT_DATA_COLLECTION = "bot_data"
    FS_BOT_DATA_DOCUMENT = "data"
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"

    MENU_MAIN = "main_menu"
    MENU_AI_MODES_SUBMENU = "ai_modes_submenu"
    MENU_MODELS_SUBMENU = "models_submenu"
    MENU_LIMITS_SUBMENU = "limits_submenu"
    MENU_BONUS_SUBMENU = "bonus_submenu"
    MENU_GEMS_SUBMENU = "gems_submenu"
    MENU_HELP_SUBMENU = "help_submenu"

    CALLBACK_ACTION_SUBMENU = "submenu"
    CALLBACK_ACTION_SET_AGENT = "set_agent"
    CALLBACK_ACTION_SET_MODEL = "set_model"
    CALLBACK_ACTION_SHOW_LIMITS = "show_limits"
    CALLBACK_ACTION_CHECK_BONUS = "check_bonus"
    CALLBACK_ACTION_SHOW_GEMS_STORE = "show_gems_store"
    CALLBACK_ACTION_BUY_GEM_PACKAGE = "buy_gem_package"
    CALLBACK_ACTION_SHOW_HELP = "show_help"

    API_TYPE_GOOGLE_GENAI = "google_genai"
    API_TYPE_CUSTOM_HTTP = "custom_http_api"

AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": ("Ты — ИИ-ассистент. Твоя задача — кратко и по существу отвечать на широкий круг вопросов пользователя. Будь вежлив и полезен. Используй ясное форматирование для списков и абзацев, если это необходимо."),
        "welcome": "Универсальный агент к вашим услугам. Какой у вас вопрос?",
        "image_url": "https://via.placeholder.com/300x200/FF7EB3/FFFFFF?text=Универсал" # Пример URL картинки
    },
    "idea_generator": {
        "name": "Генератор идей",
        "prompt": ("Ты — Генератор Идей, креативный ИИ-помощник..."),
        "welcome": "Готов генерировать идеи! Какая тема вас интересует?",
        "image_url": "https://via.placeholder.com/300x200/38EF7D/FFFFFF?text=Идеи" # Пример URL картинки
    },
    "career_coach": {
        "name": "Карьерный консультант",
        "prompt": ("Ты — Карьерный Консультант, ИИ-специалист по развитию карьеры..."),
        "welcome": "Раскроем ваш карьерный потенциал! Расскажите о ваших целях или текущей ситуации."
    },
    "programming_partner": {
        "name": "Партнер программиста",
        "prompt": ("Ты — Партнер Программиста, ИИ-ассистент для разработчиков..."),
        "welcome": "Готов помочь с кодом! Какая задача или вопрос у вас сегодня?"
    },
    "tutor_assistant": {
        "name": "Внешкольный наставник",
        "prompt": ("Ты — Внешкольный Наставник, дружелюбный ИИ-помощник для учебы..."),
        "welcome": "Рад помочь с учебой! За что сегодня возьмемся?"
    },
    "literary_editor": {
        "name": "Литературный редактор",
        "prompt": ("Ты — Литературный Редактор, ИИ-помощник для писателей..."),
        "welcome": "Готов помочь улучшить ваш текст! Пожалуйста, предоставьте текст для редактуры."
    },
    "photo_dietitian_analyzer": { 
        "name": "🥑 Диетолог", # Сократил для лучшего отображения
        "prompt": ("Ты — Диетолог-Профессионал..."),
        "welcome": "Здравствуйте! Я ваш Диетолог по фото...",
        "multimodal_capable": True,
        "forced_model_key": "google_gemini_2_5_flash_preview", 
        "native_vision_model_id": "gemini-1.5-flash-latest", # Использовал 'latest' для актуальности
        "initial_lifetime_free_uses": 5,
        "image_url": "https://via.placeholder.com/300x200/764BA2/FFFFFF?text=Диетолог" # Пример URL картинки
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый (Gemini Pro)",
        "prompt": ("Ты — Gemini Pro, мощный ИИ-ассистент..."),
        "welcome": "Активирован агент 'Продвинутый (Gemini Pro)'. Какой у вас запрос?"
    }
}

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0 Flash", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_0_FLASH_DAILY,
        "gem_cost": 0.0 
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5 Flash", "id": "gemini-1.5-flash-latest", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI, # Изменил на 1.5-flash-latest, т.к. 2.5 preview может быть устаревшим
        "is_limited": True,
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "gem_cost": 2.5,
        "image_url": "https://via.placeholder.com/300x200/4FACFE/000000?text=G-Flash" # Пример URL картинки
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro (Custom)", "id": "gemini-2.5-pro-preview-03-25", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_GEMINI_PRO_DAILY,
        "gem_cost": 2.5
    },
    "custom_api_grok_3": {
        "name": "Grok 3 (Custom)", "id": "grok-3-beta", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_GROK_DAILY,
        "gem_cost": 2.5
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini (Custom)", "id": "gpt-4o-mini", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_GPT4O_MINI_DAILY,
        "gem_cost": 0.5,
        "image_url": "https://via.placeholder.com/300x200/F9D423/000000?text=GPT-4o+mini" # Пример URL картинки
    }
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["id"]

MENU_STRUCTURE = {
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню", "items": [
            {"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU},
            {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU},
            {"text": "📊 Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_LIMITS_SUBMENU},
            {"text": "🎁 Бонус", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_BONUS_SUBMENU},
            {"text": "💎 Гемы", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_GEMS_SUBMENU},
            {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}
        ], "parent": None, "is_submenu": False
    },
    BotConstants.MENU_AI_MODES_SUBMENU: {
        "title": "Выберите агент ИИ", "items": [
            {"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_SET_AGENT, "target": key}
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode" # Пример, если этот агент не должен быть в общем списке
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_MODELS_SUBMENU: {
        "title": "Выберите модель ИИ", "items": [
            {"text": model["name"], "action": BotConstants.CALLBACK_ACTION_SET_MODEL, "target": key}
            for key, model in AVAILABLE_TEXT_MODELS.items()
        ], "parent": BotConstants.MENU_MAIN, "is_submenu": True
    },
    BotConstants.MENU_LIMITS_SUBMENU: {"title": "Ваши лимиты и баланс", "items": [{"text": "📊 Показать", "action": BotConstants.CALLBACK_ACTION_SHOW_LIMITS, "target": "usage"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_BONUS_SUBMENU: {"title": "Бонус за подписку на канал", "items": [{"text": "🎁 Получить", "action": BotConstants.CALLBACK_ACTION_CHECK_BONUS, "target": "news_bonus"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_GEMS_SUBMENU: {
        "title": "💎 Магазин Гемов", 
        "items": [
            {"text": package_info["title"], "action": BotConstants.CALLBACK_ACTION_BUY_GEM_PACKAGE, "target": package_key}
            for package_key, package_info in CONFIG.GEM_PACKAGES.items()
        ] + [{"text": "ℹ️ Мой баланс и лимиты", "action": BotConstants.CALLBACK_ACTION_SHOW_LIMITS, "target": "show_limits_from_gems_menu"}],
        "parent": BotConstants.MENU_MAIN, 
        "is_submenu": True
    },
    BotConstants.MENU_HELP_SUBMENU: {"title": "Помощь", "items": [{"text": "❓ Справка", "action": BotConstants.CALLBACK_ACTION_SHOW_HELP, "target": "help"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True}
}

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
                logger.warning(f"Firebase credentials file not found at {cert_path} and JSON string not provided. Firestore will not be initialized.")
                return # Не поднимаем исключение, просто логгируем и не инициализируем

            if not firebase_admin._apps:
                initialize_app(cred_obj)
                logger.info("Firebase app successfully initialized.")
            else:
                logger.info("Firebase app already initialized.")
            self._db = firestore.client()
            logger.info("Firestore client successfully initialized.")
        except Exception as e:
            logger.error(f"Critical error during Firebase/Firestore initialization: {e}", exc_info=True)
            self._db = None # Убедимся, что _db None в случае ошибки

    async def _execute_firestore_op(self, func, *args, **kwargs):
        if not self._db:
            logger.warning(f"Firestore (db) is not initialized. Operation '{func.__name__}' skipped.")
            return None
        try:
            return await asyncio.get_event_loop().run_in_executor(None, lambda: func(*args, **kwargs))
        except Exception as e:
            logger.error(f"Firestore operation '{func.__name__}' failed: {e}", exc_info=True)
            return None


    async def get_user_data(self, user_id: int) -> Dict[str, Any]:
        if not self._db: return {}
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc and doc.exists else {}

    async def set_user_data(self, user_id: int, data: Dict[str, Any]) -> None:
        if not self._db: return
        doc_ref = self._db.collection(BotConstants.FS_USERS_COLLECTION).document(str(user_id))
        await self._execute_firestore_op(doc_ref.set, data, merge=True)
        # logger.debug(f"User data for {user_id} updated with keys: {list(data.keys())}") # Можно раскомментировать для детального логгирования

    async def get_bot_data(self) -> Dict[str, Any]:
        if not self._db: return {}
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document(BotConstants.FS_BOT_DATA_DOCUMENT)
        doc = await self._execute_firestore_op(doc_ref.get)
        return doc.to_dict() if doc and doc.exists else {}

    async def set_bot_data(self, data: Dict[str, Any]) -> None:
        if not self._db: return
        doc_ref = self._db.collection(BotConstants.FS_BOT_DATA_COLLECTION).document(BotConstants.FS_BOT_DATA_DOCUMENT)
        await self._execute_firestore_op(doc_ref.set, data, merge=True)
        # logger.debug(f"Bot data updated with keys: {list(data.keys())}")

firestore_service = FirestoreService(
    cert_path=CONFIG.FIREBASE_CERT_PATH,
    creds_json_str=CONFIG.FIREBASE_CREDENTIALS_JSON_STR
)

class BaseAIService(ABC):
    def __init__(self, model_config: Dict[str, Any]):
        self.model_config = model_config
        self.model_id = model_config["id"]

    @abstractmethod
    async def generate_response(self, system_prompt: str, user_prompt: str, image_data: Optional[Dict[str, Any]] = None) -> str:
        pass

class GoogleGenAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str, image_data: Optional[Dict[str, Any]] = None) -> str:
        if image_data:
            logger.warning(f"GoogleGenAIService for text model {self.model_id} received image_data, but will ignore it.")
        
        full_prompt = f"{system_prompt}\n\n**Запрос:**\n{user_prompt}"
        try:
            if not CONFIG.GOOGLE_GEMINI_API_KEY or "YOUR_" in CONFIG.GOOGLE_GEMINI_API_KEY or not CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
                 logger.warning(f"Google Gemini API key for {self.model_id} is not configured correctly or is missing.")
                 return "API ключ для Google Gemini не настроен или некорректен."

            model_genai = genai.GenerativeModel(
                self.model_id,
                generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB}
            )
            response = await asyncio.get_event_loop().run_in_executor(None, lambda: model_genai.generate_content(full_prompt))
            return response.text.strip() if response.text else "Ответ Google GenAI пуст."
        except google.api_core.exceptions.ResourceExhausted as e:
            logger.error(f"Google GenAI API limit exhausted for model {self.model_id}: {e}")
            return f"Лимит Google API исчерпан для модели {self.model_config.get('name', self.model_id)}."
        except Exception as e:
            logger.error(f"Google GenAI API error for model {self.model_id}: {e}", exc_info=True)
            return f"Ошибка Google API ({type(e).__name__}) при обращении к {self.model_config.get('name', self.model_id)}."

class CustomHttpAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str, image_data: Optional[Dict[str, Any]] = None) -> str:
        api_key_name = self.model_config.get("api_key_var_name")
        actual_key = _API_KEYS_PROVIDER.get(api_key_name)

        if not actual_key or ("YOUR_" in actual_key and not (actual_key.startswith("sk-") or actual_key.startswith("AIzaSy"))): # Уточнил проверку ключа
            logger.error(f"Invalid or missing API key for model {self.model_id} (key name: {api_key_name}). Key value: '{str(actual_key)[:10]}...'")
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."

        headers = { "Authorization": f"Bearer {actual_key}", "Content-Type": "application/json", "Accept": "application/json" }
        endpoint_url = self.model_config.get("endpoint", "")
        if not endpoint_url:
            logger.error(f"Endpoint URL is not configured for model {self.model_id}.")
            return f"Не настроен endpoint для модели «{self.model_config.get('name', self.model_id)}»."

        payload = {
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "is_sync": True, # Этот параметр может быть специфичен для gen-api.ru, для других API его может не быть
            "max_tokens": self.model_config.get("max_tokens", CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB)
        }
        # Добавляем model ID в payload, если это gen-api.ru
        if endpoint_url.startswith("https://api.gen-api.ru") and self.model_id:
             payload['model'] = self.model_id 

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.post(endpoint_url, headers=headers, json=payload, timeout=90)
            )
            response.raise_for_status()
            json_resp = response.json()
            
            # Более гибкое извлечение ответа
            extracted_text = None
            if endpoint_url.startswith("https://api.gen-api.ru"):
                 extracted_text = json_resp.get("output") # Основной ключ для gen-api
            if not extracted_text and isinstance(json_resp.get("choices"), list) and json_resp["choices"]: # OpenAI-like
                extracted_text = json_resp["choices"][0].get("message", {}).get("content")
            if not extracted_text: extracted_text = json_resp.get("text") # Общий ключ

            return extracted_text.strip() if extracted_text else f"Ответ API {self.model_config['name']} не содержит ожидаемого текста."
        except requests.exceptions.HTTPError as e:
            error_body = e.response.text if e.response else "No response body"
            logger.error(f"Custom API HTTPError for {self.model_id} ({endpoint_url}): {e.response.status_code} - {error_body}", exc_info=True)
            return f"Ошибка сети Custom API ({e.response.status_code}) для {self.model_config['name']}. Детали: {error_body[:200]}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Custom API RequestException for {self.model_id} ({endpoint_url}): {e}", exc_info=True)
            return f"Сетевая ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."
        except Exception as e:
            logger.error(f"Unexpected Custom API error for {self.model_id} ({endpoint_url}): {e}", exc_info=True)
            return f"Неожиданная ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def get_user_gem_balance(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> float:
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    return float(user_data.get('gem_balance', 0.0))

async def update_user_gem_balance(user_id: int, new_balance: float) -> None:
    await firestore_service.set_user_data(user_id, {'gem_balance': round(new_balance, 2)})
    logger.info(f"User {user_id} gem balance updated to: {new_balance:.2f}")

async def get_daily_usage_for_model(user_id: int, model_key: str, bot_data_cache: Optional[Dict[str, Any]] = None) -> int:
    if bot_data_cache is None: bot_data_cache = await firestore_service.get_bot_data()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_cache.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})
    model_usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
    return model_usage_info['count'] if model_usage_info.get('date') == today_str else 0

async def get_agent_lifetime_uses_left(user_id: int, agent_config_key: str, user_data: Optional[Dict[str, Any]] = None) -> int:
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    firestore_key = f"lifetime_uses_{agent_config_key}"
    return int(user_data.get(firestore_key, 0))

async def decrement_agent_lifetime_uses(user_id: int, agent_config_key: str, user_data: Optional[Dict[str, Any]] = None) -> None:
    if user_data is None: user_data_to_update = await firestore_service.get_user_data(user_id)
    else: user_data_to_update = user_data # Используем переданные данные, если есть
    firestore_key = f"lifetime_uses_{agent_config_key}"
    current_uses = int(user_data_to_update.get(firestore_key, 0))
    if current_uses > 0:
        await firestore_service.set_user_data(user_id, {firestore_key: current_uses - 1})
        logger.info(f"User {user_id} consumed a lifetime free use for agent {agent_config_key}. Left: {current_uses - 1}")

async def check_and_log_request_attempt(
    user_id: int, model_key: str, user_data: Optional[Dict[str, Any]] = None, 
    bot_data_cache: Optional[Dict[str, Any]] = None, current_agent_key: Optional[str] = None
) -> Tuple[bool, str, str, Optional[float]]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: 
        logger.error(f"Billing model key '{model_key}' not found in AVAILABLE_TEXT_MODELS.")
        return False, "Ошибка: Конфигурация биллинг-модели не найдена.", "error", None

    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    if bot_data_cache is None: bot_data_cache = await firestore_service.get_bot_data()
    
    active_agent_config = None
    if current_agent_key: # current_agent_key - это ключ из AI_MODES
        active_agent_config = AI_MODES.get(current_agent_key)
    
    # 1. Проверка бонусных генераций с новостного канала
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} using news channel bonus for model {model_key}.")
        return True, "Используется бонусная генерация с новостного канала.", "bonus", 0.0

    # 2. Проверка пожизненных бесплатных попыток для агента
    # Это должно применяться только если текущая модель - это forced_model_key активного агента
    if active_agent_config and current_agent_key and \
       model_key == active_agent_config.get("forced_model_key") and \
       active_agent_config.get('initial_lifetime_free_uses') is not None:
        agent_uses_left = await get_agent_lifetime_uses_left(user_id, current_agent_key, user_data)
        if agent_uses_left > 0:
            logger.info(f"User {user_id} using agent lifetime free use for agent {current_agent_key} (model {model_key}). Left: {agent_uses_left}")
            return True, f"Используется бесплатная попытка для агента «{active_agent_config.get('name')}» ({agent_uses_left}/{active_agent_config.get('initial_lifetime_free_uses')}).", "agent_lifetime_free", 0.0

    # 3. Проверка дневных бесплатных лимитов для модели
    free_daily_limit = model_cfg.get('free_daily_limit', 0)
    current_daily_usage = await get_daily_usage_for_model(user_id, model_key, bot_data_cache)
    if current_daily_usage < free_daily_limit:
        logger.info(f"User {user_id} using free daily limit for model {model_key} ({current_daily_usage + 1}/{free_daily_limit}).")
        return True, f"Используется бесплатная дневная попытка для модели «{model_cfg['name']}» ({current_daily_usage + 1}/{free_daily_limit}).", "daily_free", 0.0

    # 4. Проверка баланса гемов, если есть стоимость
    gem_cost = model_cfg.get('gem_cost', 0.0)
    if gem_cost > 0:
        user_gem_balance = await get_user_gem_balance(user_id, user_data)
        if user_gem_balance >= gem_cost:
            logger.info(f"User {user_id} can use model {model_key} for {gem_cost} gems (balance: {user_gem_balance}).")
            return True, f"Будет списано {gem_cost:.1f} гемов.", "gem", gem_cost
        else:
            msg = (f"Недостаточно гемов для модели «{model_cfg['name']}».\n"
                   f"Нужно: {gem_cost:.1f}, у вас: {user_gem_balance:.1f}.\n"
                   f"Пополните баланс: /gems или через меню «💎 Гемы».")
            logger.warning(f"User {user_id} insufficient gems for {model_key}. Needed: {gem_cost}, Has: {user_gem_balance}")
            return False, msg, "no_gems", gem_cost
    
    # 5. Если все лимиты исчерпаны и модель бесплатная (gem_cost == 0)
    if gem_cost == 0 and current_daily_usage >= free_daily_limit:
        msg = (f"Дневной бесплатный лимит для «{model_cfg['name']}» ({free_daily_limit}/{free_daily_limit}) исчерпан. Модель не доступна за гемы.")
        logger.warning(f"User {user_id} free daily limit exhausted for {model_key} (model has no gem cost).")
        return False, msg, "limit_exhausted_no_gems", None

    # Ситуация по умолчанию, если ни одно из условий не выполнено (не должно происходить при правильной логике)
    logger.error(f"User {user_id} check_and_log_request_attempt reached an unexpected state for model {model_key} with agent {current_agent_key}.")
    return False, "Не удалось определить возможность использования модели. Обратитесь в поддержку.", "error", None


async def increment_request_count(user_id: int, model_key: str, usage_type: str, current_agent_key: Optional[str] = None, gem_cost_val: Optional[float] = None):
    if usage_type == "bonus":
        user_data = await firestore_service.get_user_data(user_id) 
        bonus_left = user_data.get('news_bonus_uses_left', 0)
        if bonus_left > 0: await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_left - 1})
        logger.info(f"User {user_id} consumed bonus for {model_key}. Left: {max(0, bonus_left - 1)}")
    elif usage_type == "agent_lifetime_free":
        if not current_agent_key: 
            logger.error(f"User {user_id} used 'agent_lifetime_free' for {model_key} but current_agent_key missing."); return
        await decrement_agent_lifetime_uses(user_id, current_agent_key) # user_data будет прочитана внутри decrement
    elif usage_type == "daily_free":
        bot_data = await firestore_service.get_bot_data()
        all_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
        user_counts = all_counts.get(str(user_id), {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        model_usage = user_counts.get(model_key, {'date': today, 'count': 0})
        if model_usage.get('date') != today: model_usage = {'date': today, 'count': 0} # Сброс если новый день
        model_usage['count'] += 1
        user_counts[model_key] = model_usage
        all_counts[str(user_id)] = user_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_counts})
        logger.info(f"Incremented DAILY FREE for {user_id}, {model_key} to {model_usage['count']}.")
    elif usage_type == "gem":
        if gem_cost_val is None or gem_cost_val <= 0: 
            logger.error(f"User {user_id} gem usage for {model_key} but invalid gem_cost: {gem_cost_val}"); return
        balance = await get_user_gem_balance(user_id) 
        new_balance = balance - gem_cost_val
        if new_balance < 0: 
            logger.error(f"User {user_id} overdraft on gems for {model_key}. Bal: {balance}, Cost: {gem_cost_val}. Setting to 0."); new_balance = 0.0
        await update_user_gem_balance(user_id, new_balance)
        logger.info(f"User {user_id} spent {gem_cost_val:.1f} gems for {model_key}. New balance: {new_balance:.2f}")
    else: logger.error(f"Unknown usage_type '{usage_type}' for {user_id}, {model_key}")


def get_ai_service(model_key: str) -> Optional[BaseAIService]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        logger.error(f"Configuration for model key '{model_key}' not found.")
        return None
    api_type = model_cfg.get("api_type")
    if api_type == BotConstants.API_TYPE_GOOGLE_GENAI: return GoogleGenAIService(model_cfg)
    elif api_type == BotConstants.API_TYPE_CUSTOM_HTTP: return CustomHttpAIService(model_cfg)
    else: 
        logger.error(f"Unknown API type '{api_type}' for model key '{model_key}'.")
        return None

async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    if not update.message: return
    message_id_to_process = update.message.message_id
    timestamp_now_iso = datetime.now(timezone.utc).isoformat()
    chat_id = update.effective_chat.id
    user_data_for_msg_handling = await firestore_service.get_user_data(user_id)
    
    # Удаление предыдущего "командного" сообщения, если оно было и не "сохраняемое"
    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)
    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48): # Удаляем только недавние
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e:
            logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    # Обработка текущего сообщения
    if not is_command_to_keep:
        # Если текущее сообщение не нужно сохранять, пытаемся удалить его сразу
        try:
            await update.message.delete()
            logger.info(f"Successfully deleted current user message {message_id_to_process} (not kept).")
        except telegram.error.BadRequest as e:
            # Если не удалось удалить сразу (например, нет прав), запоминаем для следующего раза
            user_data_for_msg_handling['user_command_to_delete'] = {'message_id': message_id_to_process, 'timestamp': timestamp_now_iso}
            logger.warning(f"Failed to delete current user message {message_id_to_process}: {e}. Will try next time if stored.")
    else:
         # Если текущее сообщение нужно сохранить (is_command_to_keep=True), запоминаем его как "сохраненное"
         # Это сообщение не будет автоматически удаляться этой логикой.
         user_data_for_msg_handling['user_command_message_to_keep'] = {'message_id': message_id_to_process, 'timestamp': timestamp_now_iso}

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
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    # Пытаемся найти модель по ID и API типу
    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key
    
    # Если не нашли или API тип не был указан, ищем только по ID
    # Это может быть полезно, если API тип изменился или не был сохранен
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            # Если API тип в базе отличается от фактического, обновляем его
            if user_data.get('selected_api_type') != info.get("api_type"):
                await firestore_service.set_user_data(user_id, {'selected_api_type': info.get("api_type")})
            return key
            
    # Если ничего не найдено, сбрасываем на дефолтную модель
    logger.warning(f"User {user_id} had an invalid model selection (id: {selected_id}, api_type: {selected_api_type}). Resetting to default.")
    default_cfg = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    await firestore_service.set_user_data(user_id, {
        'selected_model_id': default_cfg["id"], 
        'selected_api_type': default_cfg.get("api_type")
    })
    return CONFIG.DEFAULT_MODEL_KEY

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    active_agent_key = user_data.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    agent_config = AI_MODES.get(active_agent_key)

    if not agent_config: # Если сохраненный ключ невалиден
        logger.warning(f"User {user_id} had an invalid AI mode '{active_agent_key}'. Resetting to default.")
        active_agent_key = CONFIG.DEFAULT_AI_MODE_KEY
        await firestore_service.set_user_data(user_id, {'current_ai_mode': active_agent_key})
        agent_config = AI_MODES[active_agent_key]
        
    return agent_config

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str): text = str(text)
    if len(text) <= max_length: return text, False
    
    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)
    
    if adjusted_max_length <= 0: # Если суффикс уже длиннее максимума
        return text[:max_length - 3] + "...", True 
        
    truncated_text = text[:adjusted_max_length]
    
    # Пытаемся обрезать по последнему предложению или абзацу
    # Ищем в обратном порядке для более естественного обрезания
    for separator in ['.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ', '\n', ' ']: 
        position = truncated_text.rfind(separator)
        if position != -1:
            # Убедимся, что мы не обрезаем слишком мало текста
            if position > adjusted_max_length * 0.5: # Обрезаем, если нашли разделитель не в самом начале
                actual_cut_position = position + (len(separator) if separator.strip() else 0) # Учитываем пробел после точки
                return text[:actual_cut_position].strip() + suffix, True
                
    # Если не нашли подходящий разделитель, просто обрезаем по длине
    return text[:adjusted_max_length].strip() + suffix, True

def is_menu_button_text(text: str) -> bool:
    if text in ["⬅️ Назад", "🏠 Главное меню"]: return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data.get("items", []):
            if item["text"] == text: return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu_config = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    keyboard_rows: List[List[KeyboardButton]] = []
    items = menu_config.get("items", []) 
    
    group_by_two_keys = [
        BotConstants.MENU_MAIN, 
        BotConstants.MENU_MODELS_SUBMENU, 
        BotConstants.MENU_GEMS_SUBMENU,
        BotConstants.MENU_AI_MODES_SUBMENU
    ]
    if menu_key in group_by_two_keys:
        for i in range(0, len(items), 2):
            row = [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            keyboard_rows.append(row)
    else:
        for item in items: keyboard_rows.append([KeyboardButton(item["text"])])
        
    if menu_config.get("is_submenu", False):
        navigation_row = []
        if menu_config.get("parent"): # Добавляем "Назад" только если есть родитель
            navigation_row.append(KeyboardButton("⬅️ Назад"))
        navigation_row.append(KeyboardButton("🏠 Главное меню")) # Главное меню есть всегда в подменю
        keyboard_rows.append(navigation_row)
        
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str, context_param: Optional[ContextTypes.DEFAULT_TYPE] = None):
    """
    Показывает указанное меню пользователю.
    Если update предоставлен, пытается ответить на сообщение или изменить существующее (если callback).
    Если context_param предоставлен и update нет, отправляет новое сообщение.
    """
    bot = None
    if update and hasattr(update, 'effective_message') and update.effective_message:
        bot = update.effective_message.get_bot()
    elif context_param and hasattr(context_param, 'bot'):
        bot = context_param.bot
    
    if not bot:
        logger.error("Bot instance not available in show_menu.")
        return

    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main menu for user {user_id}.")
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        menu_key = BotConstants.MENU_MAIN
        menu_cfg = MENU_STRUCTURE[BotConstants.MENU_MAIN]

    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    keyboard = generate_menu_keyboard(menu_key)
    
    message_text = menu_cfg["title"]

    try:
        # Пытаемся отправить в личные сообщения, если это не ответ на callback_query
        # или если команда была дана в чате (и нужно открыть меню в ЛС)
        if update and update.message and update.message.chat_id != user_id:
             await bot.send_message(
                chat_id=user_id, 
                text=message_text, 
                reply_markup=keyboard, 
                disable_web_page_preview=True
            )
             await update.message.reply_text(f"Открыл «{message_text}» у вас в личных сообщениях.", disable_web_page_preview=True)
        elif update and update.callback_query: # Если это callback от inline кнопки
            await update.callback_query.edit_message_text(
                text=message_text, 
                reply_markup=keyboard, # InlineKeyboardMarkup или ReplyKeyboardMarkup? Для edit - обычно Inline, но тут context...
                                         # Для совместимости, если мы хотим показать ReplyKeyboard, нужно новое сообщение.
                disable_web_page_preview=True
            )
            # Если нужно именно ReplyKeyboard, то после edit_message_text без клавиатуры, отправить новое.
            # Но текущая логика show_menu вызывается кнопками ReplyKeyboard, а не Inline.
            # Поэтому, если это callback_query, это скорее всего не тот show_menu.
            # Этот show_menu вызывается для ReplyKeyboard.
        elif update and update.message: # Обычный ответ на сообщение
             await update.message.reply_text(
                message_text, 
                reply_markup=keyboard, 
                disable_web_page_preview=True
            )
        elif not update and context_param: # Отправка нового сообщения, если нет update
            await bot.send_message(
                chat_id=user_id,
                text=message_text,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        else:
            logger.warning(f"show_menu called for user {user_id} with menu {menu_key} but no way to send message.")


    except telegram.error.BadRequest as e:
        if "chat not found" in str(e).lower() or "bot was blocked by the user" in str(e).lower():
            logger.warning(f"Cannot send message to user {user_id} (chat not found or bot blocked). Menu: {menu_key}")
        elif update and update.message : # Если отправка в ЛС не удалась, пробуем ответить в текущий чат
             await update.message.reply_text(
                message_text, 
                reply_markup=keyboard, 
                disable_web_page_preview=True
            )
        else:
            logger.error(f"Error sending menu '{menu_key}' to user {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in show_menu for user {user_id}, menu '{menu_key}': {e}", exc_info=True)

    logger.info(f"User {user_id} was shown menu '{menu_key}'.")
