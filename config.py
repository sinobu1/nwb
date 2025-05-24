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
    GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY", "AIzaSyCdDMpgLJyz6aYdwT9q4sbBk7sHVID4BTI")
    CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
    CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    CUSTOM_GPT4O_MINI_API_KEY = os.getenv("CUSTOM_GPT4O_MINI_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602") # Ваш реальный токен провайдера платежей
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152"))
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS") # Будет использоваться, если переменная окружения установлена
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json" # Путь к файлу ключа, если FIREBASE_CREDENTIALS не установлена

    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    # Новые дневные БЕСПЛАТНЫЕ лимиты
    DEFAULT_FREE_REQUESTS_GEMINI_2_0_FLASH_DAILY = 65
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 50
    DEFAULT_FREE_REQUESTS_CUSTOM_GROK_DAILY = 1
    DEFAULT_FREE_REQUESTS_CUSTOM_GEMINI_PRO_DAILY = 1
    DEFAULT_FREE_REQUESTS_CUSTOM_GPT4O_MINI_DAILY = 10
    
    GEMS_FOR_NEW_USER = 0  # Начальное количество гемов для нового пользователя

    GEM_PACKAGES = {
        "pack_10_gems": {"gems": 10, "price_units": 10000, "currency": "RUB", "title": "✨ 10 Гемов", "description": "Небольшой пакет для старта"},
        "pack_50_gems": {"gems": 50, "price_units": 45000, "currency": "RUB", "title": "🌟 50 Гемов", "description": "Средний пакет по выгодной цене"},
        "pack_100_gems": {"gems": 100, "price_units": 80000, "currency": "RUB", "title": "💎 100 Гемов", "description": "Большой пакет для активных пользователей"}
    }

    NEWS_CHANNEL_USERNAME = "@timextech"
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
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts" # Для учета бесплатных дневных попыток

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
    "photo_dietitian_analyzer": { # Новый агент для анализа фото
        "name": "🥑 Диетолог (анализ фото)",
        "prompt": (
            "Ты — Диетолог-Профессионал, работающий с продвинутой мультимодальной ИИ-моделью Gemini 2.5 Pro, способной анализировать изображения. "
            "Твоя главная задача — детальный анализ ФОТОГРАФИЙ еды, присланных пользователем. "
            "Твой рабочий процесс СТРОГО следующий:\n"
            "1. Пользователь присылает ФОТО блюда.\n"
            "2. Ты получаешь это фото и текстовый запрос от пользователя с просьбой указать вес блюда. Твоя задача на этом этапе: ТОЛЬКО попросить пользователя указать ВЕС блюда в граммах. Не делай никаких предположений о калорийности или составе до получения веса! Пример твоего ответа: 'Отличное фото! Чтобы я мог точно рассчитать КБЖУ, пожалуйста, укажите примерный вес этой порции в граммах.'\n"
            "3. Пользователь присылает ВЕС порции текстом.\n"
            "4. Теперь, имея ФОТО и ВЕС, ты должен:\n"
            "   а) Максимально точно определить все ингредиенты блюда по фото.\n"
            "   б) Учитывая указанный вес, рассчитать калорийность (Ккал), содержание белков (Б), жиров (Ж) и углеводов (У) для всей порции.\n"
            "   в) Представить результат в четком, структурированном виде. Например:\n"
            "      'Анализ вашего блюда (примерный вес: [вес] г):\n"
            "      - Блюдо: [Название блюда/Основные ингредиенты]\n"
            "      - Калорийность: [X] Ккал\n"
            "      - Белки: [Y] г\n"
            "      - Жиры: [Z] г\n"
            "      - Углеводы: [W] г\n"
            "      [Краткие комментарии или советы по блюду, если уместно]'\n"
            "Если пользователь вместо фото или веса задает ОБЩИЙ текстовый вопрос по диетологии (например, 'польза авокадо'), отвечай на него как эксперт-диетолог, основываясь на своих знаниях, без упоминания анализа фото."
        ),
        "welcome": "Загрузите фото блюда, и я помогу с анализом КБЖУ! Если у вас общий вопрос по диетологии, просто напишите его.",
        "multimodal_capable": True, # Флаг для нашей логики
        "forced_model_key": "custom_api_gemini_2_5_pro" # Модель, которую будет использовать этот агент
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый (Gemini Pro)",
        "prompt": ("Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент. Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя. Соблюдай вежливость и объективность. Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости. Если твои знания ограничены по времени, укажи это."),
        "welcome": "Активирован агент 'Продвинутый (Gemini Pro)'. Какой у вас запрос?"
    }
}

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_0_FLASH_DAILY,
        "gem_cost": 0 
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True,
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "gem_cost": 0
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_GEMINI_PRO_DAILY,
        "gem_cost": 2.5
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_GROK_DAILY,
        "gem_cost": 2.5
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, 
        "free_daily_limit": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_GPT4O_MINI_DAILY,
        "gem_cost": 0.5
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
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode"
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
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        pass

class GoogleGenAIService(BaseAIService):
    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"{system_prompt}\n\n**Запрос:**\n{user_prompt}"
        try:
            model_genai = genai.GenerativeModel(
                self.model_id,
                generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB}
            )
            response = await asyncio.get_event_loop().run_in_executor(None, lambda: model_genai.generate_content(full_prompt))
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
        
        is_gen_api_format = self.model_config.get("endpoint", "").startswith("https://api.gen-api.ru")

        messages_payload = []
        if system_prompt:
            messages_payload.append({
                "role": "system", 
                "content": [{"type": "text", "text": system_prompt}] if is_gen_api_format else system_prompt
            })
        messages_payload.append({
            "role": "user", 
            "content": [{"type": "text", "text": user_prompt}] if is_gen_api_format else user_prompt
        })

        payload = {
            "messages": messages_payload,
            "is_sync": True,
            "max_tokens": self.model_config.get("max_tokens", CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB)
        }
        
        if self.model_config.get("parameters"):
            payload.update(self.model_config["parameters"])
        
        endpoint = self.model_config["endpoint"]

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(endpoint, headers=headers, json=payload, timeout=45)
            )
            response.raise_for_status()
            json_resp = response.json()
            
            extracted_text = None

            if is_gen_api_format:
                if "response" in json_resp and isinstance(json_resp["response"], list) and json_resp["response"]:
                    first_response_item = json_resp["response"][0]
                    if "message" in first_response_item and "content" in first_response_item["message"]:
                        extracted_text = first_response_item["message"]["content"]
                    elif self.model_id == "gemini-2.5-pro-preview-03-25" and "text" in first_response_item:
                         extracted_text = first_response_item["text"]
                
                if self.model_id == "gemini-2.5-pro-preview-03-25" and "text" in json_resp and not extracted_text:
                    extracted_text = json_resp.get("text","").strip()
                
                if not extracted_text and json_resp.get("status") != "success": # "status" может отсутствовать при прямом ответе
                    status_from_api = json_resp.get('status','N/A (успех из-за данных)')
                    error_msg_from_api = json_resp.get('error_message', '')
                    input_details_on_error = json_resp.get('input', {})

                    if not error_msg_from_api and isinstance(input_details_on_error, dict):
                        error_msg_from_api = input_details_on_error.get('error', '')

                    if "response" in json_resp: # Если есть поле response, но текст не извлечен
                         logger.warning(f"API for {self.model_config['name']} returned 'response' field but text extraction failed. Full 'response' field: {json_resp['response']}")
                         if 'output' in json_resp and isinstance(json_resp['output'], str) : # Проверяем output на всякий случай
                             extracted_text = json_resp['output'].strip()

                    if not extracted_text: # Если текст так и не извлечен, формируем сообщение об ошибке
                        logger.error(f"API Error or unexpected response structure for {self.model_config['name']}. Status: {status_from_api}. Full response: {json_resp}")
                        final_error_message = f"Ошибка API {self.model_config['name']}: Статус «{status_from_api}». {error_msg_from_api}"
                        if not error_msg_from_api.strip() and str(error_msg_from_api) != '0':
                            final_error_message = f"Ошибка API {self.model_config['name']}: Статус «{status_from_api}». Детали: {str(json_resp)[:200]}"
                        return final_error_message 
            else: 
                for key_check in ["text", "content", "message", "output", "response"]:
                    if isinstance(json_resp.get(key_check), str) and (check_val := json_resp[key_check].strip()):
                        extracted_text = check_val; break
            
            return extracted_text.strip() if extracted_text else f"Ответ API {self.model_config['name']} не содержит ожидаемого текста или структура ответа неизвестна."

        except requests.exceptions.HTTPError as e:
            error_body = e.response.text
            logger.error(f"Custom API HTTPError for {self.model_id} ({endpoint}): {e.response.status_code} - {error_body}", exc_info=True)
            return f"Ошибка сети Custom API ({e.response.status_code}) для {self.model_config['name']}. Ответ: {error_body[:200]}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Custom API RequestException for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Сетевая ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."
        except Exception as e:
            logger.error(f"Unexpected Custom API error for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Неожиданная ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."

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

async def check_and_log_request_attempt(
    user_id: int, 
    model_key: str, 
    user_data: Optional[Dict[str, Any]] = None, 
    bot_data_cache: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str, str, Optional[float]]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg: return False, "Ошибка: Конфигурация модели не найдена.", "error", None

    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    if bot_data_cache is None: bot_data_cache = await firestore_service.get_bot_data()

    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       user_data.get('claimed_news_bonus', False) and \
       user_data.get('news_bonus_uses_left', 0) > 0:
        logger.info(f"User {user_id} can use model {model_key} via news channel bonus.")
        return True, "Используется бонусная генерация.", "bonus", 0.0

    free_daily_limit = model_cfg.get('free_daily_limit', 0)
    current_free_usage = await get_daily_usage_for_model(user_id, model_key, bot_data_cache)

    if current_free_usage < free_daily_limit:
        logger.info(f"User {user_id} can use model {model_key} via free daily limit ({current_free_usage}/{free_daily_limit}).")
        return True, f"Используется бесплатная попытка ({current_free_usage + 1}/{free_daily_limit}).", "free", 0.0

    gem_cost = model_cfg.get('gem_cost', 0.0)
    if gem_cost > 0:
        user_gem_balance = await get_user_gem_balance(user_id, user_data)
        if user_gem_balance >= gem_cost:
            logger.info(f"User {user_id} can use model {model_key} for {gem_cost} gems (balance: {user_gem_balance}).")
            return True, f"Будет списано {gem_cost:.1f} гемов.", "gem", gem_cost
        else:
            msg = (f"Недостаточно гемов для модели «{model_cfg['name']}».\n"
                   f"Нужно: {gem_cost:.1f} гемов, у вас: {user_gem_balance:.1f}.\n"
                   f"Пополните баланс через меню «💎 Гемы» или команду /gems.")
            logger.warning(f"User {user_id} insufficient gems for {model_key}. Needed: {gem_cost}, Has: {user_gem_balance}")
            return False, msg, "no_gems", gem_cost
    
    if gem_cost == 0 and current_free_usage >= free_daily_limit:
        msg = (f"Дневной бесплатный лимит для модели «{model_cfg['name']}» ({free_daily_limit}/{free_daily_limit}) исчерпан. "
               f"Эта модель не доступна за гемы. Попробуйте завтра или выберите другую модель.")
        logger.warning(f"User {user_id} free daily limit exhausted for {model_key} (no gem cost).")
        return False, msg, "limit_exhausted_no_gems", None

    logger.error(f"User {user_id} check_and_log_request_attempt reached unexpected state for model {model_key}.")
    return False, "Не удалось определить возможность использования модели. Обратитесь в поддержку.", "error", None

async def increment_request_count(user_id: int, model_key: str, usage_type: str, gem_cost_val: Optional[float] = None):
    if usage_type == "bonus":
        user_data = await firestore_service.get_user_data(user_id)
        bonus_left = user_data.get('news_bonus_uses_left', 0)
        if bonus_left > 0:
            await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_left - 1})
            logger.info(f"User {user_id} consumed a news channel bonus for {model_key}. Left: {bonus_left - 1}")
    elif usage_type == "free":
        bot_data = await firestore_service.get_bot_data()
        all_user_daily_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
        user_daily_counts = all_user_daily_counts.get(str(user_id), {})
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        model_usage_info = user_daily_counts.get(model_key, {'date': today_str, 'count': 0})
        if model_usage_info.get('date') != today_str:
            model_usage_info = {'date': today_str, 'count': 0}
        model_usage_info['count'] += 1
        user_daily_counts[model_key] = model_usage_info
        all_user_daily_counts[str(user_id)] = user_daily_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
        logger.info(f"Incremented FREE daily count for user {user_id}, model {model_key} to {model_usage_info['count']}.")
    elif usage_type == "gem":
        if gem_cost_val is None or gem_cost_val <= 0:
            logger.error(f"User {user_id} gem usage for {model_key} but gem_cost_val is invalid: {gem_cost_val}")
            return
        current_balance = await get_user_gem_balance(user_id)
        new_balance = current_balance - gem_cost_val
        if new_balance < 0:
            logger.error(f"User {user_id} attempted to spend {gem_cost_val} gems for {model_key}, but balance {current_balance} is insufficient (should have been caught by check). Setting balance to 0.")
            new_balance = 0.0
        await update_user_gem_balance(user_id, new_balance)
        logger.info(f"User {user_id} spent {gem_cost_val} gems for model {model_key}. New balance: {new_balance:.2f}")
    else:
        logger.error(f"Unknown usage_type '{usage_type}' for user {user_id}, model {model_key}")

def get_ai_service(model_key: str) -> Optional[BaseAIService]:
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        logger.error(f"Configuration for model key '{model_key}' not found.")
        return None
    api_type = model_cfg.get("api_type")
    if api_type == BotConstants.API_TYPE_GOOGLE_GENAI: return GoogleGenAIService(model_cfg)
    elif api_type == BotConstants.API_TYPE_CUSTOM_HTTP: return CustomHttpAIService(model_cfg)
    else: logger.error(f"Unknown API type '{api_type}' for model key '{model_key}'."); return None

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
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    selected_id = user_data.get('selected_model_id', DEFAULT_MODEL_ID)
    selected_api_type = user_data.get('selected_api_type')

    if selected_api_type:
        for key, info in AVAILABLE_TEXT_MODELS.items():
            if info["id"] == selected_id and info.get("api_type") == selected_api_type:
                return key
    
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data.get('selected_api_type') != info.get("api_type"): # Обновляем, если тип устарел или отсутствует
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
    if user_data is None: user_data = await firestore_service.get_user_data(user_id)
    current_model_k_loc = await get_current_model_key(user_id, user_data)
    mode_k_loc = user_data.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)

    if mode_k_loc not in AI_MODES:
        mode_k_loc = CONFIG.DEFAULT_AI_MODE_KEY
        await firestore_service.set_user_data(user_id, {'current_ai_mode': mode_k_loc})
    
    if current_model_k_loc == "custom_api_gemini_2_5_pro" and mode_k_loc != "gemini_pro_custom_mode":
        # Если выбрана модель Gemini Pro, но агент не специальный для нее,
        # можно автоматически переключить на специальный агент или оставить как есть,
        # в зависимости от желаемого поведения. Текущая логика позволяет использовать Gemini Pro с любым агентом.
        # Если нужно принудительно, то:
        # return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])
        pass # Оставляем выбор агента пользователю
        
    return AI_MODES.get(mode_k_loc, AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str): text = str(text) # На случай если пришел не текст
    if len(text) <= max_length: return text, False

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)

    if adjusted_max_length <= 0: return text[:max_length - len("...")] + "...", True 
        
    truncated_text = text[:adjusted_max_length]
    
    for separator in ['\n\n', '. ', '! ', '? ', '\n', ' ']: 
        position = truncated_text.rfind(separator)
        if position != -1:
            actual_cut_position = position + (len(separator) if separator != ' ' else 0)
            if actual_cut_position > 0 and actual_cut_position > adjusted_max_length * 0.3:
                 return text[:actual_cut_position].strip() + suffix, True
                 
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
    items = menu_config["items"]

    # Группировка по две кнопки для основного меню, меню моделей и меню гемов
    if menu_key in [BotConstants.MENU_MAIN, BotConstants.MENU_MODELS_SUBMENU, BotConstants.MENU_GEMS_SUBMENU]:
        for i in range(0, len(items), 2):
            keyboard_rows.append([KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))])
    else: # Остальные меню - по одной кнопке в ряду
        for item in items: keyboard_rows.append([KeyboardButton(item["text"])])
            
    if menu_config.get("is_submenu", False):
        navigation_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"): navigation_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(navigation_row)
        
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)

async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found. Defaulting to main menu for user {user_id}.")
        await update.message.reply_text("Ошибка: Запрошенное меню не найдено. Показываю главное меню.",
            reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN))
        await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
        return

    await firestore_service.set_user_data(user_id, {'current_menu': menu_key})
    await update.message.reply_text(menu_cfg["title"], reply_markup=generate_menu_keyboard(menu_key), disable_web_page_preview=True)
    logger.info(f"User {user_id} was shown menu '{menu_key}'.")
