# config.py
import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, WebAppInfo
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
import base64 
from datetime import datetime, timedelta, timezone
import pytz 
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
    GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
    CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152"))
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://nwb-production.up.railway.app/") 
    
    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4
    MAX_CONVERSATION_HISTORY = 6 # Хранить последние 6 пар (вопрос-ответ)

    DEFAULT_FREE_REQUESTS_GEMINI_2_0_FLASH_DAILY = 65
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 50 
    DEFAULT_FREE_REQUESTS_CUSTOM_GROK_DAILY = 1 # Из вашего config (20).py, в logs было 0/0 - вы можете поменять
    DEFAULT_FREE_REQUESTS_CUSTOM_GEMINI_PRO_DAILY = 1 
    DEFAULT_FREE_REQUESTS_CUSTOM_GPT4O_MINI_DAILY = 10
    
    GEMS_FOR_NEW_USER = 0
    
    GEM_PACKAGES = { # Взято из config (20).py
        "pack_10_gems": {"gems": 10, "price_units": 10000, "currency": "RUB", "title": "✨ 10 Гемов", "description": "Небольшой пакет для старта"},
        "pack_50_gems": {"gems": 50, "price_units": 45000, "currency": "RUB", "title": "🌟 50 Гемов", "description": "Средний пакет по выгодной цене"},
        "pack_100_gems": {"gems": 100, "price_units": 80000, "currency": "RUB", "title": "💎 100 Гемов", "description": "Большой пакет для активных пользователей"}
    }

    NEWS_CHANNEL_USERNAME = "@timextech"
    NEWS_CHANNEL_LINK = "https://t.me/timextech"
    # Новая структура для бонусов по нескольким моделям
    NEWS_CHANNEL_BONUS_CONFIG: Dict[str, int] = {
        "custom_api_gemini_2_5_pro": 1, # Пример
        "custom_api_grok_3": 1          # Пример, так как в логе был бонус для Grok
    }

    DEFAULT_AI_MODE_KEY = "universal_ai_basic"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash" # Было google_gemini_2_0_flash в config (24).py, оставляю его
    
    MOSCOW_TZ = pytz.timezone('Europe/Moscow') # Добавлено из config (24).py

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
    FS_APP_MESSAGES_COLLECTION = "app_messages" 

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
    
    # Добавлено из config (24).py для соответствия структуре меню
    CALLBACK_ACTION_OPEN_MINI_APP = "open_mini_app"


    API_TYPE_GOOGLE_GENAI = "google_genai"
    API_TYPE_CUSTOM_HTTP = "custom_http_api"

AI_MODES = { # Взято из config (24).py / config (20).py - они идентичны в этой части
    "universal_ai_basic": {
        "name": "Универсальный", 
        "prompt": ("Ты — ИИ-ассистент. Твоя задача — кратко и по существу отвечать на широкий круг вопросов пользователя. Будь вежлив и полезен. Используй ясное форматирование для списков и абзацев, если это необходимо."),
        "welcome": "Универсальный агент к вашим услугам. Какой у вас вопрос?"
    },
    "idea_generator": {
        "name": "Генератор идей", 
        "prompt": ("Ты — Генератор Идей, креативный ИИ-помощник. Твоя задача — помогать пользователю находить новые и оригинальные идеи для различных целей: вечеринок, подарков, бизнеса, творческих проектов и многого другого. Предлагай разнообразные варианты, стимулируй воображение пользователя. Будь позитивным и вдохновляющим. Используй списки для перечисления идей, если это уместно. Четко разделяй смысловые блоки."),
        "welcome": "Готов генерировать идеи! Какая тема вас интересует?"
    },
    "career_coach": {
        "name": "Карьерный консультант", 
        "prompt": ("Ты — Карьерный Консультант, ИИ-специалист по развитию карьеры. Твоя цель — помочь пользователю раскрыть свой карьерный потенциал. Предоставляй подробные и структурированные планы по совершенствованию навыков, достижению карьерных целей, поиску работы и профессиональному росту. Будь объективным, давай практические советы. Оформляй планы по пунктам, выделяй ключевые этапы."),
        "welcome": "Раскроем ваш карьерный потенциал! Расскажите о ваших целях или текущей ситуации."
    },
    "programming_partner": {
        "name": "Партнер программиста", 
        "prompt": ("Ты — Партнер Программиста, ИИ-ассистент для разработчиков. Твоя задача — помогать пользователям совершенствовать навыки программирования, работать над проектами и изучать новые технологии. Объясняй концепции, предлагай решения для задач, помогай отлаживать код, делись лучшими практиками. Предоставляй фрагменты кода, если это необходимо, используя форматирование для кода. Будь точным и терпеливым."),
        "welcome": "Готов помочь с кодом! Какая задача или вопрос у вас сегодня?"
    },
    "tutor_assistant": {
        "name": "Внешкольный наставник", 
        "prompt": ("Ты — Внешкольный Наставник, дружелюбный ИИ-помощник для учебы. Твоя миссия — помогать с учебой и практическими заданиями. Объясняй сложные темы простым языком, помогай с решением задач, проверяй понимание материала, предлагай ресурсы для дополнительного изучения. Будь терпеливым, ободряющим и ясным в своих объяснениях."),
        "welcome": "Рад помочь с учебой! За что сегодня возьмемся?"
    },
    "literary_editor": {
        "name": "Литературный редактор", 
        "prompt": ("Ты — Литературный Редактор, ИИ-помощник для писателей. Твоя задача — помогать пользователям писать лучше, предоставляя четкие и конструктивные отзывы по их текстам. Анализируй стиль, грамматику, структуру, логику изложения. Предлагай улучшения, помогай с выбором слов и выражений. Будь тактичным и объективным в своих рекомендациях."),
        "welcome": "Готов помочь улучшить ваш текст! Пожалуйста, предоставьте текст для редактуры."
    },
    "photo_dietitian_analyzer": { # Из config (24).py
        "name": "🥑 Диетолог (анализ фото)", 
        "prompt": (
            "Ты — Диетолог-Профессионал, эксперт по здоровому питанию, работающий с продвинутой мультимодальной ИИ-моделью, способной анализировать изображения еды. "
            "Твоя главная задача — детальный анализ ФОТОГРАФИЙ еды, присланных пользователем, и предоставление развернутых рекомендаций.\n\n"
            "Если пользователь прислал ФОТО и ТЕКСТ (например, вес или комментарий):\n"
            "1. Максимально точно определи все ингредиенты блюда по фото.\n"
            "2. Учитывая указанный вес/комментарий, рассчитай примерное количество калорий (Ккал), содержание белков (Б), жиров (Ж) и углеводов (У) для всей порции.\n"
            "3. Представь результат в четком, структурированном виде. Например:\n"
            "   'Анализ вашего блюда (комментарий/вес: [текст пользователя]):\n"
            "   - Блюдо/Продукты: [Детальное перечисление распознанных ингредиентов]\n"
            "   - Калорийность: ~[X] Ккал\n"
            "   - Белки: ~[Y] г\n"
            "   - Жиры: ~[Z] г\n"
            "   - Углеводы: ~[W] г\n\n"
            "   Рекомендации: [1-2 кратких, полезных совета по данному блюду/приему пищи].'\n"
            "4. Если пользователь прислал только ФОТО без текста: вежливо попроси уточнить примерный вес порции в граммах. Пример: 'Прекрасное фото! Чтобы я мог провести точный анализ и рассчитать КБЖУ, пожалуйста, уточните примерный вес этой порции в граммах или добавьте комментарий.'\n"
            "5. Если пользователь прислал только ТЕКСТ без фото (например, общий вопрос по диетологии): отвечай на него как эксперт-диетолог, основываясь на своих знаниях, без упоминания анализа фото.\n"
            "Будь внимателен, дружелюбен и профессионален. Используй эмодзи уместно."
        ),
        "welcome": "Здравствуйте! Я ваш Диетолог. Прикрепите фото блюда и укажите вес/комментарий для анализа КБЖУ, или задайте вопрос по питанию.",
        "multimodal_capable": True,
        "forced_model_key": "google_gemini_2_5_flash_preview", 
        "native_vision_model_id": "gemini-2.5-flash-preview-04-17", 
        "initial_lifetime_free_uses": 5,
        "gem_cost_after_lifetime": 2.5 
    },
     # "gemini_pro_custom_mode" из config (20).py, можно оставить если нужен
    "gemini_pro_custom_mode": {
        "name": "Продвинутый (Gemini Pro)",
        "prompt": ("Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент. Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя. Соблюдай вежливость и объективность. Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости. Если твои знания ограничены по времени, укажи это."),
        "welcome": "Активирован агент 'Продвинутый (Gemini Pro)'. Какой у вас запрос?"
    }
}

AVAILABLE_TEXT_MODELS = { # Взято из config (24).py, но с названиями из config (20).py
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_0_FLASH_DAILY,
        "gem_cost": 0 
    },
    "google_gemini_2_5_flash_preview": { 
        "name": "Gemini 2.5 Flash", "id": "gemini-2.5-flash-preview-04-17", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True,
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "gem_cost": 2.5, # В config (24).py было 2.5, в config (20).py не было gem_cost для этой модели
        "is_vision_model": True # Добавлено из config (24).py
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
        "gem_cost": 0.5
    }
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["id"] # Это из config (24).py

MENU_STRUCTURE = { # Из config (20).py, т.к. он включал кнопку Mini App
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню", "items": [
            {"text": "📱 Mini App", "action": BotConstants.CALLBACK_ACTION_OPEN_MINI_APP, "target": "main_app", "web_app_url": "https://sinobu1.github.io/nwb/"}, # Из config (20).py
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
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode" # Как в config (20).py
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

class FirestoreService: # Идентичен в config (20).py и config (24).py
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

            if not firebase_admin._apps:
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

class BaseAIService(ABC):
    def __init__(self, model_config: Dict[str, Any]):
        self.model_config = model_config
        self.model_id = model_config["id"]

    @abstractmethod
    async def generate_response(self, system_prompt: str, user_prompt: str, history: List[Dict], image_data: Optional[Dict[str, Any]] = None) -> str: # Добавлена история
        pass

class GoogleGenAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str, history: List[Dict], image_data: Optional[Dict[str, Any]] = None) -> str: # Добавлена история
        try:
            if not CONFIG.GOOGLE_GEMINI_API_KEY or "YOUR_" in CONFIG.GOOGLE_GEMINI_API_KEY:
                 return "API ключ для Google Gemini не настроен."

            model_genai = genai.GenerativeModel(
                self.model_id, 
                generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB},
                # system_instruction передается в start_chat или как часть истории
            )
            
            # Формируем контент для отправки, включая системный промпт в начало истории, если его нет
            gemini_history_format = []
            if system_prompt:
                 gemini_history_format.append({'role': 'user', 'parts': [{'text': system_prompt}]})
                 gemini_history_format.append({'role': 'model', 'parts': [{'text': "Понял. Я готов."}]}) 

            gemini_history_format.extend(history) # Добавляем основную историю (уже в формате Gemini)

            content_parts_for_current_message = []
            if image_data and self.model_config.get("is_vision_model"): # Проверяем, является ли модель вижена
                if image_data.get("base64") and image_data.get("mime_type"):
                    try:
                        image_bytes = base64.b64decode(image_data["base64"])
                        image_part = {"mime_type": image_data["mime_type"], "data": image_bytes}
                        content_parts_for_current_message.append(image_part) 
                        logger.info(f"Image data prepared for vision model {self.model_id}")
                    except Exception as e:
                        logger.error(f"Error decoding base64 image for model {self.model_id}: {e}")
                        return "Ошибка обработки изображения." 
                else:
                    logger.warning(f"Vision model {self.model_id} called but image_data is incomplete.")
            
            if user_prompt: 
                content_parts_for_current_message.append({'text': user_prompt})

            if not content_parts_for_current_message: 
                logger.warning(f"No content parts to send for model {self.model_id}.")
                return "Нет данных для отправки в ИИ."
            
            chat_session = model_genai.start_chat(history=gemini_history_format)
            response = await asyncio.get_event_loop().run_in_executor(None, lambda: chat_session.send_message(content_parts_for_current_message))
            return response.text.strip() if response.text else "Ответ Google GenAI пуст."
        except google.api_core.exceptions.ResourceExhausted as e:
            logger.error(f"Google GenAI API limit exhausted for model {self.model_id}: {e}")
            return f"Лимит Google API исчерпан: {e}"
        except Exception as e:
            logger.error(f"Google GenAI API error for model {self.model_id}: {e}", exc_info=True)
            return f"Ошибка Google API ({type(e).__name__}) при обращении к {self.model_id}."

class CustomHttpAIService(BaseAIService): # ЗАМЕНЯЕМ НА ПОЛНОСТЬЮ НОВУЮ ВЕРСИЮ
    async def generate_response(self, system_prompt: str, user_prompt: str, history: List[Dict], image_data: Optional[Dict[str, Any]] = None) -> str:
        # image_data: {"base64": "...", "mime_type": "image/jpeg"} или None
        
        if image_data and self.model_id != "gpt-4o-mini": 
            logger.warning(f"CustomHttpAIService for model {self.model_id} received image_data, but current implementation ignores it for this model (expects it only for gpt-4o-mini via gen-api).")
            image_data = None 

        api_key_name = self.model_config.get("api_key_var_name")
        actual_key = _API_KEYS_PROVIDER.get(api_key_name)

        if not actual_key or ("YOUR_" in actual_key and not (actual_key.startswith("sk-") or actual_key.startswith("AIzaSy"))):
            logger.error(f"Invalid API key for model {self.model_id} (key name: {api_key_name}).")
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."

        headers = {
            "Authorization": f"Bearer {actual_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        endpoint_url = self.model_config.get("endpoint", "")
        is_gen_api_endpoint = endpoint_url.startswith("https://api.gen-api.ru")
        
        messages_payload = []

        # Специальная обработка для Grok 3: всё в одном user-сообщении
        if self.model_id == "grok-3-beta":
            full_grok_prompt_parts = []
            if system_prompt:
                full_grok_prompt_parts.append(f"System Instruction:\n{system_prompt}")
            
            if history:
                for msg in history:
                    role = msg.get("role", "user") 
                    text_content = ""
                    if msg.get("parts") and isinstance(msg["parts"], list) and msg["parts"][0].get("text"):
                        text_content = msg["parts"][0]["text"]
                    elif isinstance(msg.get("content"), str): # Если история уже в формате content: "string"
                         text_content = msg["content"]
                    elif isinstance(msg.get("content"), list) and msg["content"] and isinstance(msg["content"][0], dict) and "text" in msg["content"][0]: # Если история уже в формате content: [{"type": "text", ...}]
                        text_content = msg["content"][0]["text"]

                    if text_content:
                        full_grok_prompt_parts.append(f"\nPrevious {role.capitalize()}:\n{text_content}")
            
            if user_prompt:
                full_grok_prompt_parts.append(f"\nCurrent User Query:\n{user_prompt}")
            
            final_grok_prompt = "\n\n".join(full_grok_prompt_parts) # Используем двойной перенос для лучшего разделения
            
            # Для gen-api Grok 3, content как массив текста
            messages_payload.append({"role": "user", "content": [{"type": "text", "text": final_grok_prompt}]})
            logger.debug(f"Grok-3 single prompt constructed. Length: {len(final_grok_prompt)}")
        else:
            # Стандартная обработка для других моделей (включая GPT-4o mini)
            if system_prompt:
                if is_gen_api_endpoint: 
                    messages_payload.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})
                else: # Другие кастомные API могут ожидать строку
                    messages_payload.append({"role": "system", "content": system_prompt})

            if history:
                for msg in history:
                    role = msg.get("role", "user")
                    text_content = ""
                    # Извлечение текста из разных возможных форматов истории
                    if msg.get("parts") and isinstance(msg["parts"], list) and msg["parts"][0].get("text"):
                        text_content = msg["parts"][0]["text"]
                    elif isinstance(msg.get("content"), str):
                         text_content = msg["content"]
                    elif isinstance(msg.get("content"), list) and msg["content"] and isinstance(msg["content"][0], dict) and "text" in msg["content"][0]:
                        text_content = msg["content"][0]["text"]
                    
                    if text_content:
                        if is_gen_api_endpoint:
                            messages_payload.append({"role": role, "content": [{"type": "text", "text": text_content}]})
                        else:
                            messages_payload.append({"role": role, "content": text_content})
            
            # Формируем content для текущего запроса пользователя
            user_content_list_for_payload = []
            current_user_prompt_text = user_prompt or "..." # Если user_prompt пуст (например, только картинка)

            if is_gen_api_endpoint:
                # Обработка изображений ТОЛЬКО для gpt-4o-mini через gen-api, если есть image_data
                if image_data and self.model_id == "gpt-4o-mini":
                    if image_data.get("base64") and image_data.get("mime_type"):
                        img_url = f"data:{image_data['mime_type']};base64,{image_data['base64']}"
                        user_content_list_for_payload.append({"type": "image_url", "image_url": {"url": img_url}})
                        logger.info(f"Base64 image added to payload for gpt-4o-mini (gen-api)")
                
                user_content_list_for_payload.append({"type": "text", "text": current_user_prompt_text})
                messages_payload.append({"role": "user", "content": user_content_list_for_payload})
            else: # Для других не-gen-api эндпоинтов (ожидают строку)
                 messages_payload.append({"role": "user", "content": current_user_prompt_text})


        payload = {
            "messages": messages_payload,
            "is_sync": True, 
            "max_tokens": self.model_config.get("max_tokens", CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB)
        }
        
        if is_gen_api_endpoint and self.model_id:
             payload['model'] = self.model_id 

        if self.model_config.get("parameters"):
            payload.update(self.model_config["parameters"])
        
        endpoint = endpoint_url 
        logger.debug(f"Отправка payload на {endpoint} для модели {self.model_id}: {json.dumps(payload, ensure_ascii=False, indent=2)}")

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(endpoint, headers=headers, json=payload, timeout=90)
            )
            response.raise_for_status()
            json_resp = response.json()
            logger.debug(f"Получен ответ от {endpoint} для модели {self.model_id}: {json.dumps(json_resp, ensure_ascii=False, indent=2)}")
            
            extracted_text = None

            if is_gen_api_endpoint:
                if json_resp.get("status") == "success" and "output" in json_resp:
                    extracted_text = json_resp["output"]
                elif "choices" in json_resp and isinstance(json_resp["choices"], list) and json_resp["choices"]: 
                    choice = json_resp["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                         # Если content - строка (некоторые модели gen-api могут так отвечать)
                        if isinstance(choice["message"]["content"], str):
                            extracted_text = choice["message"]["content"]
                        # Если content - массив (например, от gpt-4o-mini, даже если там только текст)
                        elif isinstance(choice["message"]["content"], list) and choice["message"]["content"]:
                             # Ищем первый текстовый блок
                            for content_item in choice["message"]["content"]:
                                if content_item.get("type") == "text":
                                    extracted_text = content_item.get("text")
                                    break
                elif "response" in json_resp and isinstance(json_resp["response"], list) and json_resp["response"]: 
                    first_response_item = json_resp["response"][0]
                    if "message" in first_response_item and "content" in first_response_item["message"]:
                        extracted_text = first_response_item["message"]["content"]
                elif "text" in json_resp: 
                    extracted_text = json_resp.get("text")

                if not extracted_text and json_resp.get("status") not in ["success", "starting", "processing"]:
                    status_from_api = json_resp.get('status','N/A')
                    error_msg_from_api = json_resp.get('error_message', json_resp.get('result'))
                    if isinstance(error_msg_from_api, list): error_msg_from_api = " ".join(error_msg_from_api)
                    
                    if not error_msg_from_api and 'response' in json_resp and isinstance(json_resp['response'], list) and json_resp['response']:
                        if isinstance(json_resp['response'][0], str): # Если это список строк
                             error_msg_from_api = " ".join(json_resp['response'])
                        elif isinstance(json_resp['response'][0], dict) and 'error' in json_resp['response'][0]: # Если это список словарей с ошибкой
                            error_msg_from_api = json_resp['response'][0]['error'].get('message', str(json_resp['response'][0]['error']))


                    input_details_on_error = json_resp.get('input', {})
                    if not error_msg_from_api and isinstance(input_details_on_error, dict): error_msg_from_api = input_details_on_error.get('error', '')
                    
                    logger.error(f"Ошибка API для {self.model_config['name']}. Статус: {status_from_api}. Полный ответ: {json_resp}")
                    final_error_message = f"Ошибка API {self.model_config['name']}: Статус «{status_from_api}». {error_msg_from_api}"
                    if not str(error_msg_from_api).strip() or str(error_msg_from_api) == '0':
                        final_error_message = f"Ошибка API {self.model_config['name']}: Статус «{status_from_api}». Детали: {str(json_resp)[:200]}"
                    return final_error_message
            else: 
                if isinstance(json_resp.get("choices"), list) and json_resp["choices"]:
                    choice = json_resp["choices"][0]
                    if isinstance(choice.get("message"), dict) and choice["message"].get("content"):
                        extracted_text = choice["message"]["content"]
                    elif isinstance(choice.get("text"), str):
                         extracted_text = choice.get("text")
                elif isinstance(json_resp.get("text"), str):
                    extracted_text = json_resp.get("text")
                elif isinstance(json_resp.get("content"), str):
                     extracted_text = json_resp.get("content")
            
            return extracted_text.strip() if extracted_text else f"Ответ API {self.model_config['name']} не содержит ожидаемого текста или структура ответа неизвестна."
        except requests.exceptions.HTTPError as e:
            error_body = e.response.text if e.response else "No response body"; status_code = e.response.status_code if e.response else "N/A"
            logger.error(f"Custom API HTTPError for {self.model_id} ({endpoint}): {status_code} - {error_body}", exc_info=True)
            return f"Ошибка сети Custom API ({status_code}) для {self.model_config['name']}. Ответ: {error_body[:200]}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Custom API RequestException for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Сетевая ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."
        except Exception as e:
            logger.error(f"Unexpected Custom API error for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Неожиданная ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."

# --- Вспомогательные функции для лимитов и биллинга (из config (24).py) ---
async def get_user_gem_balance(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> float:
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    return float(user_data.get('gem_balance', 0.0))

async def update_user_gem_balance(user_id: int, new_balance: float) -> None:
    await firestore_service.set_user_data(user_id, {'gem_balance': round(new_balance, 2)})
    logger.info(f"User {user_id} gem balance updated to: {new_balance:.2f}")

async def get_daily_usage_for_model(user_id: int, model_key: str, bot_data_cache: Optional[Dict[str, Any]] = None) -> int:
    if bot_data_cache is None: bot_data_cache = await firestore_service.get_bot_data()
    today_str = datetime.now(CONFIG.MOSCOW_TZ).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_cache.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})
    model_usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
    
    if model_usage_info.get('date') != today_str:
        return 0
    return model_usage_info['count']

async def get_agent_lifetime_uses_left(user_id: int, agent_config_key: str, user_data: Optional[Dict[str, Any]] = None) -> int:
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    firestore_key = f"lifetime_uses_{agent_config_key}"
    return int(user_data.get(firestore_key, 0))

async def decrement_agent_lifetime_uses(user_id: int, agent_config_key: str, user_data: Optional[Dict[str, Any]] = None) -> None:
    if user_data is None: user_data_to_update = await firestore_service.get_user_data(user_id)
    else: user_data_to_update = user_data
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
    if not model_cfg: return False, "Ошибка: Конфигурация биллинг-модели не найдена.", "error", None

    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    if bot_data_cache is None: bot_data_cache = await firestore_service.get_bot_data()
    active_agent_config = AI_MODES.get(current_agent_key) if current_agent_key else None

    # 1. Проверка бонуса за подписку (теперь для конкретной модели)
    if model_key in CONFIG.NEWS_CHANNEL_BONUS_CONFIG and \
       user_data.get('claimed_news_bonus', False):
        bonus_uses_left_key = f"news_bonus_uses_left_{model_key}"
        if user_data.get(bonus_uses_left_key, 0) > 0:
            logger.info(f"User {user_id} can use model {model_key} via news channel bonus for this model.")
            return True, f"Используется бонусная генерация для «{model_cfg['name']}».", "bonus", 0.0

    # 2. Проверка пожизненного лимита агента
    agent_lifetime_uses_exhausted = False
    if active_agent_config and current_agent_key:
        initial_lifetime_uses = active_agent_config.get('initial_lifetime_free_uses')
        # Проверяем, что модель совпадает с форсированной агентом ИЛИ агент не имеет форсированной модели (тогда лимит агента применяется к текущей выбранной модели)
        applies_to_current_model_for_agent = model_key == active_agent_config.get("forced_model_key") or not active_agent_config.get("forced_model_key")

        if initial_lifetime_uses is not None and applies_to_current_model_for_agent :
            agent_uses_left = await get_agent_lifetime_uses_left(user_id, current_agent_key, user_data)
            if agent_uses_left > 0:
                return True, f"Используется бесплатная попытка для агента «{active_agent_config.get('name')}» ({agent_uses_left}/{initial_lifetime_uses}).", "agent_lifetime_free", 0.0
            else:
                agent_lifetime_uses_exhausted = True 
                
                gem_cost_after_lifetime = active_agent_config.get('gem_cost_after_lifetime')
                if gem_cost_after_lifetime is not None and gem_cost_after_lifetime > 0:
                    user_gem_balance_check = await get_user_gem_balance(user_id, user_data)
                    if user_gem_balance_check >= gem_cost_after_lifetime:
                        return True, f"Будет списано {gem_cost_after_lifetime:.1f} гемов (спец. тариф агента «{active_agent_config.get('name')}» для модели «{model_cfg['name']}»).", "gem", gem_cost_after_lifetime
                    else:
                        msg_no_gems_agent = (f"Недостаточно гемов для агента «{active_agent_config.get('name')}» (модель «{model_cfg['name']}»).\n"
                                           f"Нужно: {gem_cost_after_lifetime:.1f}, у вас: {user_gem_balance_check:.1f}\n"
                                           f"Пополните баланс через меню «💎 Гемы».")
                        return False, msg_no_gems_agent, "no_gems_agent_specific", gem_cost_after_lifetime

    # 3. Проверка дневного бесплатного лимита
    can_try_daily_limit = True
    if agent_lifetime_uses_exhausted and active_agent_config and active_agent_config.get('gem_cost_after_lifetime') is not None:
        can_try_daily_limit = False

    if can_try_daily_limit:
        free_daily_limit = model_cfg.get('free_daily_limit', 0)
        current_daily_usage = await get_daily_usage_for_model(user_id, model_key, bot_data_cache)
        if current_daily_usage < free_daily_limit:
            return True, f"Используется бесплатная дневная попытка для модели «{model_cfg['name']}» ({current_daily_usage + 1}/{free_daily_limit}).", "daily_free", 0.0

    # 4. Проверка платного использования за гемы (обычная стоимость модели)
    gem_cost = model_cfg.get('gem_cost', 0.0)
    if gem_cost > 0:
        user_gem_balance = await get_user_gem_balance(user_id, user_data)
        if user_gem_balance >= gem_cost:
            return True, f"Будет списано {gem_cost:.1f} гемов за «{model_cfg['name']}».", "gem", gem_cost
        else:
            msg = (f"Недостаточно гемов для «{model_cfg['name']}».\n"
                   f"Нужно: {gem_cost:.1f}, у вас: {user_gem_balance:.1f}\n"
                   f"Пополните баланс через меню «💎 Гемы».")
            return False, msg, "no_gems", gem_cost
    
    final_msg = ""
    if agent_lifetime_uses_exhausted and active_agent_config and not active_agent_config.get('gem_cost_after_lifetime'):
        final_msg = (f"Все бесплатные попытки для агента «{active_agent_config.get('name')}» исчерпаны. "
                     f"Эта модель ({model_cfg['name']}) далее не доступна для данного агента по спец. тарифу или бесплатно.")
    else:
        final_msg = (f"Все бесплатные лимиты для «{model_cfg['name']}» на сегодня исчерпаны. "
                     f"Эта модель не доступна за гемы.")
        
    logger.warning(f"User {user_id} all limits exhausted for {model_key} (agent: {current_agent_key}). Message: {final_msg}")
    return False, final_msg, "limit_exhausted_no_gems", None


async def increment_request_count(user_id: int, model_key: str, usage_type: str, current_agent_key: Optional[str] = None, gem_cost_val: Optional[float] = None):
    if usage_type == "bonus":
        user_data = await firestore_service.get_user_data(user_id) 
        bonus_uses_left_key = f"news_bonus_uses_left_{model_key}" # Ключ для конкретной модели
        bonus_left = user_data.get(bonus_uses_left_key, 0)
        if bonus_left > 0: 
            await firestore_service.set_user_data(user_id, {bonus_uses_left_key: bonus_left - 1})
            logger.info(f"User {user_id} consumed bonus for model {model_key}. Left: {bonus_left - 1}")
        else:
            logger.warning(f"User {user_id} tried to consume bonus for model {model_key}, but no uses left (key: {bonus_uses_left_key}).")

    elif usage_type == "agent_lifetime_free":
        if not current_agent_key: 
            logger.error(f"User {user_id} used 'agent_lifetime_free' for {model_key} but current_agent_key missing.")
            return
        await decrement_agent_lifetime_uses(user_id, current_agent_key)
    elif usage_type == "daily_free":
        bot_data = await firestore_service.get_bot_data()
        all_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
        user_counts = all_counts.get(str(user_id), {})
        today = datetime.now(CONFIG.MOSCOW_TZ).strftime("%Y-%m-%d")
        model_usage = user_counts.get(model_key, {'date': today, 'count': 0})
        
        if model_usage.get('date') != today: 
            model_usage = {'date': today, 'count': 0}
            
        model_usage['count'] += 1
        user_counts[model_key] = model_usage
        all_counts[str(user_id)] = user_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_counts})
        logger.info(f"Incremented DAILY FREE for {user_id}, {model_key} to {model_usage['count']} for date {today}.")
    elif usage_type == "gem":
        if gem_cost_val is None or gem_cost_val <= 0: 
            logger.error(f"User {user_id} gem usage for {model_key} but invalid gem_cost: {gem_cost_val}")
            return
        balance = await get_user_gem_balance(user_id) 
        new_balance = balance - gem_cost_val
        if new_balance < 0: 
            logger.error(f"User {user_id} overdraft on gems for {model_key}. Bal: {balance}, Cost: {gem_cost_val}")
            new_balance = 0.0
        await update_user_gem_balance(user_id, new_balance)
        logger.info(f"User {user_id} spent {gem_cost_val:.1f} gems for {model_key}. New balance: {new_balance:.2f}")
    else: 
        logger.error(f"Unknown usage_type '{usage_type}' for {user_id}, {model_key}")

# --- Утилиты и вспомогательные функции (идентичны config (24).py) ---
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
    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)
    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48): # Срок хранения 48ч
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e:
            if "message to delete not found" not in str(e).lower():
                 logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    if not is_command_to_keep: # Для обычных сообщений, которые не являются командами /start, /menu и т.д.
        user_data_for_msg_handling['user_command_to_delete'] = {
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
        # НЕ удаляем сообщение пользователя сразу, если это не кнопка меню. Удаление кнопок происходит в menu_button_handler.
        # Обычные текстовые сообщения пользователя (не команды и не кнопки) - не удаляются, они часть диалога.
    else: # Команды типа /start, /menu и т.д. - эти сообщения СОХРАНЯЮТСЯ
         user_data_for_msg_handling['user_command_message_to_keep'] = { # Используем другой ключ для сохраняемых команд
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
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key
    
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data.get('selected_api_type') != info.get("api_type"): # Обновляем тип API если он не совпадает
                await firestore_service.set_user_data(user_id, {'selected_api_type': info.get("api_type")})
            return key
            
    # Fallback to default if no match found (should not happen ideally)
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
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    
    active_agent_key = user_data.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    agent_config = AI_MODES.get(active_agent_key)

    if not agent_config: 
        logger.warning(f"Invalid agent key '{active_agent_key}' found for user {user_id}. Resetting to default.")
        active_agent_key = CONFIG.DEFAULT_AI_MODE_KEY
        await firestore_service.set_user_data(user_id, {'current_ai_mode': active_agent_key, 'conversation_history': []}) # Сброс истории
        agent_config = AI_MODES[active_agent_key]
        
    return agent_config

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str): text = str(text)
    if len(text) <= max_length: return text, False
    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)
    if adjusted_max_length <= 0: return text[:max_length - len("...")] + "...", True 
    truncated_text = text[:adjusted_max_length]
    # Обрезаем по последнему осмысленному разделителю
    for separator in ['\n\n', '. ', '! ', '? ', '\n', ' ']: 
        position = truncated_text.rfind(separator)
        if position != -1:
            # Убедимся, что отрезаем не слишком мало
            actual_cut_position = position + (len(separator) if separator != ' ' else 0)
            if actual_cut_position > 0 and actual_cut_position > adjusted_max_length * 0.3: # Оставляем хотя бы 30%
                 return text[:actual_cut_position].strip() + suffix, True
    # Если не нашли хорошего разделителя, режем как есть
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

    def create_button(item_config: Dict[str, Any]) -> KeyboardButton:
        text = item_config["text"]
        web_app_url = item_config.get("web_app_url")
        # Проверяем, есть ли web_app_url и action соответствует ли открытию Mini App
        if web_app_url and item_config.get("action") == BotConstants.CALLBACK_ACTION_OPEN_MINI_APP: 
            return KeyboardButton(text, web_app=WebAppInfo(url=web_app_url))
        return KeyboardButton(text)

    group_by_two_keys = [
        BotConstants.MENU_MAIN, 
        BotConstants.MENU_MODELS_SUBMENU, 
        BotConstants.MENU_GEMS_SUBMENU,
        BotConstants.MENU_AI_MODES_SUBMENU
    ]

    if menu_key in group_by_two_keys:
        for i in range(0, len(items), 2):
            row = [create_button(items[j]) for j in range(i, min(i + 2, len(items)))]
            keyboard_rows.append(row)
    else: # Для остальных меню - по одной кнопке в ряду
        for item in items:
            keyboard_rows.append([create_button(item)])

    # Добавление кнопок навигации "Назад" и "Главное меню" для подменю
    if menu_config.get("is_submenu", False):
        navigation_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"): # Если есть родительское меню, добавляем кнопку "Назад"
            navigation_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(navigation_row)

    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False) # one_time_keyboard=False чтобы меню не скрывалось

async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main menu for user {user_id}.")
        # Используем update.message.reply_text, если update.message существует
        reply_target = update.message if update.message else (update.callback_query.message if update.callback_query else None)
        if reply_target:
            await reply_target.reply_text("Ошибка: Запрошенное меню не найдено. Показываю главное меню.",
                reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
        else: # Если нет сообщения для ответа (например, принудительный вызов)
            await Application.get_running_app().bot.send_message(chat_id=user_id, 
                                                               text="Ошибка: Запрошенное меню не найдено. Показываю главное меню.",
                                                               reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        return
    
    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    
    menu_title_to_send = menu_cfg["title"]

    reply_target = update.message if update.message else (update.callback_query.message if update.callback_query else None)
    if reply_target:
        await reply_target.reply_text(menu_title_to_send, reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)
    else:
        await Application.get_running_app().bot.send_message(chat_id=user_id, text=menu_title_to_send, reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)

    logger.info(f"User {user_id} was shown menu '{menu_key}'.")
