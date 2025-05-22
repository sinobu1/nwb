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
from typing import Optional, Dict, Any, Tuple, Union, List # Добавил List
import uuid # Не используется явно, но оставлен на случай скрытой зависимости
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient
from abc import ABC, abstractmethod # Для абстрактных классов

nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ (Оставлена как есть, но обернута для наглядности) ---
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

    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
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

# Глобальные переменные для ключей API (используются в CustomHttpAIService)
# Это упрощает доступ к ним, хотя можно было бы передавать их через конструктор сервиса
# или получать из AppConfig внутри сервиса.
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


# --- ОПРЕДЕЛЕНИЯ РЕЖИМОВ И МОДЕЛЕЙ (как в оригинале, для краткости) ---
    AI_MODES = {
    "universal_ai_basic": {
        "name": "Универсальный",
        "prompt": (
            "Ты — Gemini, продвинутый ИИ-ассистент от Google."
            "Твоя цель — эффективно помогать пользователю с широким спектром задач:"
            "отвечать на вопросы, генерировать текст, объяснять,"
            "анализировать и предоставлять информацию."
            "Всегда будь вежлив, объективен, точен и полезен."
            "Предупреждай, если твои знания ограничены по времени."
            "ОФОРМЛЕНИЕ ОТВЕТА:"
            "1. Структура и ясность: Ответ должен быть понятным, хорошо структурированным и легким для восприятия. Четко разделяй смысловые блоки абзацами, используя одну или две пустые строки между ними."
            "2. Списки: Для перечислений используй нумерованные списки, например 1., 2., или маркированные списки, например -, *, со стандартными символами."
            "3. Заголовки: Для крупных смысловых блоков можешь использовать краткие поясняющие заголовки на отдельной строке, можно ЗАГЛАВНЫМИ БУКВАМИ."
            "4. Чистота текста: Генерируй только ясный, чистый текст без избыточных символов или пунктуации, не несущей смысловой нагрузки или не требуемой грамматикой."
            "5. Полнота: Старайся давать полные ответы. Убедись, что пункты списков завершены, и не начинай новый, если не уверен, что сможешь его закончить."
        ),
        "welcome": "Активирован агент 'Универсальный'. Какой у вас запрос?"
    },
    "gemini_pro_custom_mode": {
        "name": "Продвинутый",
        "prompt": (
            "Ты — Gemini 2.5 Pro, мощный и продвинутый ИИ-ассистент."
            "Твоя задача — предоставлять точные, развернутые и полезные ответы на запросы пользователя."
            "Соблюдай вежливость и объективность."
            "Формулируй ответы ясно и структурированно, используя абзацы и списки при необходимости."
            "Если твои знания ограничены по времени, укажи это."
        ),
        "welcome": "Активирован агент 'Продвинутый'. Какой у вас запрос?"
    },
    "creative_helper": {
        "name": "Творческий",
        "prompt": (
            "Ты — Gemini, креативный ИИ-партнёр и писатель. "
            "Твоя миссия — вдохновлять, помогать в создании оригинального контента (тексты, идеи, сценарии, стихи и т.д.) и развивать творческие замыслы пользователя."
            "Будь смелым в идеях, предлагай неожиданные решения, но всегда оставайся в рамках этики и здравого смысла."
            "Форматирование: 1. Абзацы: Для прозы и описаний — четкое разделение на абзацы."
            "2. Стихи: Соблюдай строфы и строки, если это подразумевается заданием."
            "3. Диалоги: Оформляй диалоги стандартным образом, например: - Привет! - сказал он. или с новой строки для каждого персонажа."
            "4. Язык: Используй богатый и выразительный язык, соответствующий творческой задаче."
            "6. Завершённость: Старайся доводить творческие произведения до логического конца в рамках одного ответа, если это подразумевается задачей."
        ),
        "welcome": "Агент 'Творческий' к вашим услугам! Над какой задачей поработаем?"
    },
    "analyst": {
        "name": "Аналитик",
        "prompt": (
            "Ты — ИИ-аналитик на базе Gemini, специализирующийся на анализе данных, фактов и трендов."
            "Твоя задача — предоставлять точные, логически обоснованные и структурированные ответы на запросы, связанные с анализом информации, статистики или бизнес-вопросов."
            "Используй структурированный подход:"
            "1. Анализ: Разбери запрос на ключевые аспекты."
            "2. Выводы: Предоставь четкие выводы или рекомендации."
            "3. Обоснование: Объясни свои рассуждения, если требуется."
            "Если данных недостаточно, укажи, что нужно для более точного анализа."
        ),
        "welcome": "Агент 'Аналитик' активирован. Какую задачу проанализировать?"
    },
    "joker": {
        "name": "Шутник",
        "prompt": (
            "Ты — ИИ с чувством юмора, основанный на Gemini."
            "Твоя задача — отвечать на запросы с легкостью, остроумием и юмором, сохраняя при этом полезность."
            "Добавляй шутки, анекдоты или забавные комментарии, но оставайся в рамках приличия."
            "Форматируй ответы так, чтобы они были веселыми и читабельными."
        ),
        "welcome": "Агент 'Шутник' включен! 😄 Готов ответить с улыбкой!"
    }
}
# Полные тексты prompt и welcome скрыты для краткости, но они должны быть как в оригинале

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "limit_type": "daily_free", "limit": CONFIG.DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY,
        "cost_category": "google_flash_free"
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "limit_type": "subscription_or_daily_free",
        "limit_if_no_subscription": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY,
        "subscription_daily_limit": CONFIG.DEFAULT_SUBSCRIPTION_REQUESTS_GOOGLE_FLASH_PREVIEW_DAILY,
        "cost_category": "google_flash_preview_flex"
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG.DEFAULT_FREE_REQUESTS_CUSTOM_PRO_DAILY,
        "subscription_daily_limit": CONFIG.DEFAULT_SUBSCRIPTION_REQUESTS_CUSTOM_PRO_DAILY,
        "cost_category": "custom_api_pro_paid", "pricing_info": {}
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG.DEFAULT_FREE_REQUESTS_GROK_DAILY,
        "subscription_daily_limit": CONFIG.DEFAULT_SUBSCRIPTION_REQUESTS_GROK_DAILY,
        "cost_category": "custom_api_grok_3_paid", "pricing_info": {}
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, "limit_type": "subscription_custom_pro",
        "limit_if_no_subscription": CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY,
        "subscription_daily_limit": CONFIG.DEFAULT_SUBSCRIPTION_REQUESTS_GPT4O_MINI_DAILY,
        "cost_category": "custom_api_gpt4o_mini_paid", "pricing_info": {}
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
            {"text": "💎 Подписка", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_SUBSCRIPTION_SUBMENU},
            {"text": "❓ Помощь", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_HELP_SUBMENU}
        ], "parent": None, "is_submenu": False
    },
    BotConstants.MENU_AI_MODES_SUBMENU: {
        "title": "Выберите агент ИИ", "items": [
            {"text": mode["name"], "action": BotConstants.CALLBACK_ACTION_SET_AGENT, "target": key}
            for key, mode in AI_MODES.items() if key != "gemini_pro_custom_mode" # "gemini_pro_custom_mode" handled separately
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
        # Firestore sync operations need to run in an executor for async context
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

# --- СЕРВИСЫ ДЛЯ РАБОТЫ С AI ---
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
            # Предполагается, что genai сконфигурирован глобально
            model_genai = genai.GenerativeModel(
                self.model_id,
                generation_config={"max_output_tokens": CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB}
            )
            # Запуск синхронного вызова в executor
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
        # Используем _API_KEYS_PROVIDER для получения ключа
        actual_key = _API_KEYS_PROVIDER.get(api_key_name)

        if not actual_key or "YOUR_" in actual_key or not (actual_key.startswith("sk-") or actual_key.startswith("AIzaSy")):
            logger.error(f"Invalid API key for model {self.model_id} (key name: {api_key_name}).")
            return f"Ошибка конфигурации ключа API для «{self.model_config.get('name', self.model_id)}»."

        headers = {
            "Authorization": f"Bearer {actual_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        is_gpt4o_like = (self.model_id == "gpt-4o-mini") # Пример для специфичного форматирования
        
        messages_payload = []
        if system_prompt:
            messages_payload.append({
                "role": "system", 
                "content": [{"type": "text", "text": system_prompt}] if is_gpt4o_like else system_prompt
            })
        messages_payload.append({
            "role": "user", 
            "content": [{"type": "text", "text": user_prompt}] if is_gpt4o_like else user_prompt
        })

        payload = {
            "messages": messages_payload,
            "model": self.model_id,
            "is_sync": True, # Это специфично для gen-api.ru, может отличаться для других
            "max_tokens": self.model_config.get("max_tokens", CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB)
        }
        if self.model_config.get("parameters"):
            payload.update(self.model_config["parameters"])
        
        endpoint = self.model_config["endpoint"]

        try:
            # Запуск синхронного HTTP запроса в executor
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(endpoint, headers=headers, json=payload, timeout=45)
            )
            response.raise_for_status()
            json_resp = response.json()
            
            # Логика извлечения текста ответа (может потребовать доработки под разные API)
            extracted_text = None
            if self.model_id == "grok-3-beta": # Пример специфичной обработки
                 if "response" in json_resp and isinstance(json_resp["response"], list) and \
                    json_resp["response"] and "choices" in json_resp["response"][0] and \
                    isinstance(json_resp["response"][0]["choices"], list) and json_resp["response"][0]["choices"]:
                    extracted_text = json_resp["response"][0]["choices"][0].get("message",{}).get("content","").strip()
            elif self.model_id == "gemini-2.5-pro-preview-03-25":
                 extracted_text = json_resp.get("text","").strip()
            elif self.model_id == "gpt-4o-mini":
                if json_resp.get("status") == "success":
                    output_val = json_resp.get("output")
                    if isinstance(output_val, str): extracted_text = output_val.strip()
                    elif isinstance(output_val, dict): extracted_text = output_val.get("text", output_val.get("content", "")).strip()
                    elif output_val is not None: extracted_text = str(output_val).strip()
                else: 
                    extracted_text = f"Ошибка API {self.model_config['name']}: {json_resp.get('status','N/A')}. {json_resp.get('error_message','')}"

            if extracted_text is None: # Общий случай
                for key_check in ["text", "content", "message", "output", "response"]:
                    if isinstance(json_resp.get(key_check), str) and (check_val := json_resp[key_check].strip()):
                        extracted_text = check_val
                        break
            
            return extracted_text if extracted_text else f"Ответ API {self.model_config['name']} не содержит ожидаемого текста."

        except requests.exceptions.HTTPError as e:
            logger.error(f"Custom API HTTPError for {self.model_id} ({endpoint}): {e.response.status_code} - {e.response.text}", exc_info=True)
            return f"Ошибка сети Custom API ({e.response.status_code}) для {self.model_config['name']}."
        except requests.exceptions.RequestException as e:
            logger.error(f"Custom API RequestException for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Сетевая ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."
        except Exception as e:
            logger.error(f"Unexpected Custom API error for {self.model_id} ({endpoint}): {e}", exc_info=True)
            return f"Неожиданная ошибка Custom API ({type(e).__name__}) для {self.model_config['name']}."

def get_ai_service(model_key: str) -> Optional[BaseAIService]:
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

# --- УТИЛИТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (многие остаются как есть, но используют FirestoreService) ---

async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    """
    Обрабатывает удаление предыдущих и текущих сообщений пользователя.
    Использует firestore_service для доступа к данным.
    """
    if not update.message: return

    message_id_to_process = update.message.message_id
    timestamp_now_iso = datetime.now(timezone.utc).isoformat()
    chat_id = update.effective_chat.id
    
    # Получаем данные пользователя через сервис
    user_data_for_msg_handling = await firestore_service.get_user_data(user_id)

    prev_command_info = user_data_for_msg_handling.pop('user_command_to_delete', None)
    if prev_command_info and prev_command_info.get('message_id'):
        try:
            prev_msg_time = datetime.fromisoformat(prev_command_info['timestamp'])
            if prev_msg_time.tzinfo is None: prev_msg_time = prev_msg_time.replace(tzinfo=timezone.utc)
            # Лимит на удаление старых сообщений (48 часов)
            if datetime.now(timezone.utc) - prev_msg_time <= timedelta(hours=48):
                await update.get_bot().delete_message(chat_id=chat_id, message_id=prev_command_info['message_id'])
                logger.info(f"Successfully deleted previous user message {prev_command_info['message_id']}")
        except (telegram.error.BadRequest, ValueError) as e: # BadRequest если сообщение уже удалено или слишком старое
            logger.warning(f"Failed to delete/process previous user message {prev_command_info.get('message_id')}: {e}")
    
    if not is_command_to_keep: # Если сообщение не нужно сохранять (обычный текст, не команда /start)
        user_data_for_msg_handling['user_command_to_delete'] = { # Сохраняем информацию для возможного удаления в следующий раз
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
        try: # Пытаемся удалить текущее сообщение немедленно
            await update.get_bot().delete_message(chat_id=chat_id, message_id=message_id_to_process)
            logger.info(f"Successfully deleted current user message {message_id_to_process} (not kept).")
            user_data_for_msg_handling.pop('user_command_to_delete', None) # Удаляем, так как успешно удалили
        except telegram.error.BadRequest as e:
            logger.warning(f"Failed to delete current user message {message_id_to_process}: {e}. Will try next time if stored.")
    else: # Если это команда, которую нужно "сохранить" (не удалять немедленно)
         user_data_for_msg_handling['user_command_message_to_keep'] = { # Это поле сейчас не используется для удаления, а только для информации
            'message_id': message_id_to_process, 'timestamp': timestamp_now_iso
        }
    # Сохраняем обновленные данные пользователя через сервис
    await firestore_service.set_user_data(user_id, user_data_for_msg_handling)


def auto_delete_message_decorator(is_command_to_keep: bool = False):
    """Декоратор для автоматического вызова _store_and_try_delete_message."""
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_user and update.message: # Убедимся, что есть сообщение для обработки
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
    
    # Если API тип не совпал или не был указан, ищем по ID и обновляем тип
    for key, info in AVAILABLE_TEXT_MODELS.items():
        if info["id"] == selected_id:
            if user_data_loc.get('selected_api_type') != info.get("api_type"): # Обновляем, если тип устарел
                await firestore_service.set_user_data(user_id, {'selected_api_type': info.get("api_type")})
            return key
            
    # Если ничего не найдено, возвращаем и устанавливаем модель по умолчанию
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
    current_model_k_loc = await get_current_model_key(user_id, user_data_loc) # Нужен для спец. режима gemini_pro_custom_mode
    mode_k_loc = user_data_loc.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)

    if mode_k_loc not in AI_MODES: # Если сохраненный режим невалиден
        mode_k_loc = CONFIG.DEFAULT_AI_MODE_KEY
        await firestore_service.set_user_data(user_id, {'current_ai_mode': mode_k_loc})
    
    # Особый случай для продвинутой модели
    if current_model_k_loc == "custom_api_gemini_2_5_pro":
        return AI_MODES.get("gemini_pro_custom_mode", AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])
        
    return AI_MODES.get(mode_k_loc, AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY])

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    if not isinstance(text, str) or len(text) <= max_length:
        return str(text), False # Убедимся, что возвращаем строку, даже если это не строка

    suffix = "\n\n(...ответ был сокращен)"
    adjusted_max_length = max_length - len(suffix)

    if adjusted_max_length <= 0: # Если суффикс длиннее чем max_length
        return text[:max_length - len("...")] + "...", True 
        
    truncated_text = text[:adjusted_max_length]
    
    # Ищем ближайший разделитель для "умного" обрезания
    # Порядок важен: от более крупных разделителей к мелким
    for separator in ['\n\n', '. ', '! ', '? ', '\n', ' ']: 
        position = truncated_text.rfind(separator)
        if position != -1:
            # Обрезаем по найденному разделителю, если он не слишком близко к началу
            actual_cut_position = position + (len(separator) if separator != ' ' else 0) # Не добавлять длину пробела, если это просто пробел
            if actual_cut_position > 0 and actual_cut_position > adjusted_max_length * 0.3: # Эвристика: не резать слишком коротко
                 return text[:actual_cut_position].strip() + suffix, True
                 
    # Если подходящий разделитель не найден, режем по adjusted_max_length
    return text[:adjusted_max_length].strip() + suffix, True

def is_user_profi_subscriber(subscription_details: Dict[str, Any]) -> bool:
    if not subscription_details: return False
    if subscription_details.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY and \
       subscription_details.get('valid_until'):
        try:
            valid_until_dt = datetime.fromisoformat(subscription_details['valid_until'])
            # Если нет таймзоны, предполагаем UTC (стандарт для ISO строк от Firebase)
            if valid_until_dt.tzinfo is None:
                valid_until_dt = valid_until_dt.replace(tzinfo=timezone.utc)
            # Подписка действительна, если текущая дата (UTC) меньше или равна дате окончания подписки
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

    # Используем кеш, если передан, иначе загружаем
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
    elif not model_cfg.get("is_limited", False): # Если модель не лимитирована
        return float('inf') # Бесконечный лимит
    else: # Неизвестный тип лимита или другая ошибка конфигурации
        return 0

    # Бонус за подписку на новостной канал (для не-профи пользователей)
    user_data_loc = user_data if user_data is not None else await firestore_service.get_user_data(user_id)
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False):
        base_limit += user_data_loc.get('news_bonus_uses_left', 0)
        
    return base_limit

async def check_and_log_request_attempt(user_id: int, model_key: str) -> Tuple[bool, str, int]:
    """
    Проверяет, может ли пользователь сделать запрос к модели, и возвращает статус.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)

    if not model_cfg or not model_cfg.get("is_limited"):
        return True, "", 0 # Может продолжать, нет сообщения, текущее использование 0

    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subscriptions)

    # Проверка бонусных использований (приоритетнее дневных лимитов для бонусной модели)
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False) and \
       user_data_loc.get('news_bonus_uses_left', 0) > 0:
        return True, "bonus_available", 0 # Может продолжать, есть бонус

    # Получение текущего использования
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    model_usage_info = user_daily_counts.get(model_key, {'date': '', 'count': 0})

    # Сброс счетчика, если дата устарела
    if model_usage_info['date'] != today_str:
        model_usage_info = {'date': today_str, 'count': 0}
        # Сохраним сброшенный счетчик, если он изменился
        # Это важно, чтобы при первом запросе в день данные были актуальны
        # user_daily_counts[model_key] = model_usage_info
        # all_user_daily_counts[str(user_id)] = user_daily_counts
        # await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})


    current_usage_count = model_usage_info['count']
    
    # Определение лимита для сравнения
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
        # Лимит достигнут
        display_limit = await get_user_actual_limit_for_model(user_id, model_key, user_data_loc, bot_data_loc)
        message_parts = [f"Достигнут дневной лимит ({current_usage_count}/{display_limit}) для модели «{model_cfg['name']}». Модель была изменена на «{AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]['name']}»."]
        
        # Сброс на модель по умолчанию, если текущая модель исчерпана
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
        
        # Важно: если счетчик сбрасывался из-за даты, нужно сохранить это состояние
        if model_usage_info['date'] == today_str and user_daily_counts.get(model_key) != model_usage_info:
             user_daily_counts[model_key] = model_usage_info
             all_user_daily_counts[str(user_id)] = user_daily_counts
             await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})

        return False, "\n".join(message_parts), current_usage_count

    # Если лимит не достигнут, но счетчик был сброшен из-за новой даты, сохраняем это.
    if model_usage_info['date'] == today_str and user_daily_counts.get(model_key) != model_usage_info:
        user_daily_counts[model_key] = model_usage_info
        all_user_daily_counts[str(user_id)] = user_daily_counts
        await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
        
    return True, "", current_usage_count


async def increment_request_count(user_id: int, model_key: str):
    """Инкрементирует счетчик использования модели."""
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg or not model_cfg.get("is_limited"):
        return # Не лимитируемая модель, ничего не делаем

    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    user_subscriptions = bot_data_loc.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {}).get(str(user_id), {})
    is_profi_user = is_user_profi_subscriber(user_subscriptions)

    # Обработка бонусных использований
    if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
       not is_profi_user and \
       user_data_loc.get('claimed_news_bonus', False):
        bonus_uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        if bonus_uses_left > 0:
            await firestore_service.set_user_data(user_id, {'news_bonus_uses_left': bonus_uses_left - 1})
            logger.info(f"User {user_id} consumed a news channel bonus use for model {model_key}. Left: {bonus_uses_left - 1}")
            return # Бонус использован, основной счетчик не трогаем

    # Инкремент основного счетчика
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data_loc.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    
    model_usage_info = user_daily_counts.get(model_key, {'date': today_str, 'count': 0})
    if model_usage_info['date'] != today_str: # Если новая дата, сбрасываем счетчик
        model_usage_info = {'date': today_str, 'count': 0}
    
    model_usage_info['count'] += 1
    user_daily_counts[model_key] = model_usage_info
    all_user_daily_counts[str(user_id)] = user_daily_counts
    
    await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
    logger.info(f"Incremented daily count for user {user_id}, model {model_key} to {model_usage_info['count']}.")

# --- ФУНКЦИИ МЕНЮ (многие остаются похожими, но используют константы и обновленные сервисы) ---

def is_menu_button_text(text: str) -> bool:
    """Проверяет, является ли текст кнопкой из определенной структуры меню."""
    if text in ["⬅️ Назад", "🏠 Главное меню"]: # Общие навигационные кнопки
        return True
    for menu_data in MENU_STRUCTURE.values():
        for item in menu_data.get("items", []): # Добавил .get для безопасности
            if item["text"] == text:
                return True
    return False

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    menu_config = MENU_STRUCTURE.get(menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    keyboard_rows: List[List[KeyboardButton]] = [] # Явная типизация
    items = menu_config["items"]

    # Группировка кнопок по две для главного меню и меню моделей
    if menu_key in [BotConstants.MENU_MAIN, BotConstants.MENU_MODELS_SUBMENU]:
        for i in range(0, len(items), 2):
            keyboard_rows.append(
                [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            )
    else: # Остальные меню - по одной кнопке в ряду
        for item in items:
            keyboard_rows.append([KeyboardButton(item["text"])])
            
    # Добавление навигационных кнопок для подменю
    if menu_config.get("is_submenu", False):
        navigation_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"): # Если есть родитель, добавляем кнопку "Назад"
            navigation_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(navigation_row)
        
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False) # one_time_keyboard=False для постоянного меню

async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    """Отображает указанное меню пользователю."""
    menu_cfg = MENU_STRUCTURE.get(menu_key)
    if not menu_cfg:
        logger.error(f"Menu key '{menu_key}' not found in MENU_STRUCTURE. Defaulting to main menu for user {user_id}.")
        # Если запрошенное меню не найдено, показываем главное меню
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
        disable_web_page_preview=True # Отключаем предпросмотр ссылок в меню
    )
    logger.info(f"User {user_id} was shown menu '{menu_key}'.")


# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---

@auto_delete_message_decorator(is_command_to_keep=True) # Сохраняем сообщение /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    
    user_data_loc = await firestore_service.get_user_data(user_id)
    updates_to_user_data = {}

    # Инициализация пользовательских данных, если они отсутствуют
    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc: # current_menu будет установлено show_menu
        updates_to_user_data['current_menu'] = BotConstants.MENU_MAIN
        
    default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
    if 'selected_api_type' not in user_data_loc: # Важно для правильной работы get_current_model_key
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data) # Обновляем локальную копию

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
        reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN), # Показываем главное меню
        disable_web_page_preview=True
    )
    # Обновляем current_menu после отправки сообщения, если оно было изменено
    await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    logger.info(f"User {user_id} ({user_first_name}) started or restarted the bot.")

@auto_delete_message_decorator() # Удаляем команду /menu
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # user_data_loc = await firestore_service.get_user_data(user_id) # Необязательно передавать, show_menu получит сам
    await show_menu(update, user_id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator() # Удаляем команду /usage
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id) # Делегируем логику

@auto_delete_message_decorator() # Удаляем команду /subscribe
async def subscribe_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription(update, update.effective_user.id) # Делегируем

@auto_delete_message_decorator() # Удаляем команду /bonus
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id) # Делегируем

@auto_delete_message_decorator() # Удаляем команду /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id) # Делегируем

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ (лимиты, подписка, помощь) ---

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
    elif user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY: # Подписка была, но истекла
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
            # Если дата не совпадает с сегодняшней, значит использования сегодня не было
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

    parts.append("") # Пустая строка для разделения
    
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    bonus_model_name_display = bonus_model_cfg['name'] if bonus_model_cfg else "бонусной модели"

    if not user_data_loc.get('claimed_news_bonus', False):
        parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить бонусные генерации ({CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} для {bonus_model_name_display})! Нажмите «🎁 Бонус» в меню для активации.')
    elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
        parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций с канала новостей для модели {bonus_model_name_display}.")
    else: # Бонус был получен, но уже использован
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
    
    # Определяем, из какого меню был вызван бонус, чтобы вернуться туда же
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_BONUS_SUBMENU)
    current_menu_config = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    # Если текущее меню не является подменю (например, пользователь ввел команду /bonus из ниоткуда), 
    # то родительским будет главное меню.
    if not current_menu_config.get("is_submenu"):
        reply_menu_key = BotConstants.MENU_MAIN 
    else: # Иначе, используем родителя текущего подменю или главное меню по умолчанию
        reply_menu_key = current_menu_config.get("parent", BotConstants.MENU_MAIN)


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
            reply_markup=generate_menu_keyboard(reply_menu_key), # Возвращаемся в предыдущее меню
            disable_web_page_preview=True
        )
        return

    try:
        # Проверка подписки на канал
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            # Пользователь подписан, начисляем бонус
            await firestore_service.set_user_data(user_id, {
                'claimed_news_bonus': True, 
                'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS
            })
            success_text = (
                f'🎉 Отлично! Спасибо за подписку на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>! '
                f"Вам начислен бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> "
                f"генераций для модели {bonus_model_name_display}."
            )
            # После успешного получения бонуса, переводим пользователя в главное меню
            await update.message.reply_text(
                success_text, 
                parse_mode=ParseMode.HTML, 
                reply_markup=generate_menu_keyboard(BotConstants.MENU_MAIN), 
                disable_web_page_preview=True
            )
            await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN}) # Обновляем текущее меню
        else:
            # Пользователь не подписан
            fail_text = (
                f'Для получения бонуса, пожалуйста, сначала подпишитесь на наш новостной канал '
                f'<a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>. '
                f'После подписки, вернитесь сюда и снова нажмите кнопку «🎁 Получить» в меню «Бонус».'
            )
            # Кнопка для перехода на канал
            inline_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 Перейти на канал {CONFIG.NEWS_CHANNEL_USERNAME}", url=CONFIG.NEWS_CHANNEL_LINK)]
            ])
            await update.message.reply_text(
                fail_text, 
                parse_mode=ParseMode.HTML, 
                reply_markup=inline_keyboard, 
                disable_web_page_preview=True # Отключаем предпросмотр для основной ссылки, так как есть кнопка
            )
    except telegram.error.TelegramError as e: # Более общее исключение для ошибок Telegram
        logger.error(f"Telegram API error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла ошибка при проверке вашей подписки на канал. Пожалуйста, попробуйте еще раз немного позже.",
            reply_markup=generate_menu_keyboard(reply_menu_key) # Возвращаемся в предыдущее меню
        )
    except Exception as e: # Ловим другие возможные ошибки
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
        if user_subscriptions.get('level') == CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY: # Была, но истекла
            try:
                expired_dt = datetime.fromisoformat(user_subscriptions['valid_until'])
                if expired_dt.tzinfo is None: expired_dt = expired_dt.replace(tzinfo=timezone.utc)
                parts.append(f"\n⚠️ Ваша подписка Profi истекла <b>{expired_dt.strftime('%d.%m.%Y')}</b>.")
            except (ValueError, KeyError):
                parts.append("\n⚠️ Ваша подписка Profi истекла (ошибка в дате).")

        parts.append("\nПодписка <b>Profi</b> предоставляет следующие преимущества:")
        parts.append("▫️ Значительно увеличенные дневные лимиты на использование всех моделей ИИ.")
        
        # Динамически добавляем платные модели в описание
        pro_models = [m_cfg["name"] for m_key, m_cfg in AVAILABLE_TEXT_MODELS.items() 
                      if m_cfg.get("limit_type") == "subscription_custom_pro" and m_cfg.get("limit_if_no_subscription", -1) == 0]
        if pro_models:
            parts.append(f"▫️ Эксклюзивный доступ к продвинутым моделям: {', '.join(pro_models)}.")
        else: # Если вдруг таких моделей нет, но логика подписки есть
             parts.append(f"▫️ Доступ к специальным моделям, требующим подписку.")

        parts.append("\nДля оформления или продления подписки Profi, пожалуйста, используйте команду /subscribe "
                     "или соответствующую кнопку «💎 Купить» в меню «Подписка».") # TODO: Заменить на реальную команду/кнопку покупки если она отличается от /subscribe

    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_SUBSCRIPTION_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )
    # Если это команда /subscribe и пользователь не имеет активной подписки, можно сразу отправить счет
    # if update.message.text == "/subscribe" and not is_active_profi:
    #     await _send_profi_invoice(update, context) # Пример вызова функции отправки счета


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
        return  # Ничего не делаем, если нет текстового сообщения

    user_id = update.effective_user.id
    button_text = update.message.text.strip()

    # Если это не кнопка меню, передаем управление дальше (например, в handle_text)
    # Эта проверка важна, чтобы menu_button_handler обрабатывал только свои кнопки.
    if not is_menu_button_text(button_text):
        return 

    # Удаляем сообщение с кнопкой, так как оно уже обработано
    # Декоратор @auto_delete_message_decorator здесь не используется, 
    # так как нам нужно удалить сообщение *после* того, как мы определили, что это кнопка.
    # Если бы декоратор был здесь, он бы удалял и обычные текстовые сообщения, 
    # которые должны идти в handle_text.
    try:
        await update.message.delete()
        logger.info(f"Deleted menu button message '{button_text}' from user {user_id}.")
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}' from user {user_id}: {e}")
        # Продолжаем обработку, даже если удаление не удалось


    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    logger.info(f"User {user_id} pressed menu button '{button_text}' while in menu '{current_menu_key}'.")

    # Обработка навигационных кнопок
    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key, user_data_loc) # Передаем user_data_loc для возможного использования в show_menu
        return 
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN, user_data_loc)
        return

    # Поиск действия для нажатой кнопки
    action_item_found = None
    # Сначала ищем в текущем меню, затем во всех остальных (на случай, если current_menu устарел)
    # Это немного избыточно, если current_menu всегда актуален, но добавляет надежности.
    search_menus_order = [current_menu_key] + [key for key in MENU_STRUCTURE if key != current_menu_key]

    for menu_key_to_search in search_menus_order:
        menu_config_to_search = MENU_STRUCTURE.get(menu_key_to_search, {})
        for item in menu_config_to_search.get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                # Определяем меню, из которого реально пришло действие, для кнопки "Назад"
                # Это важно, если current_menu в user_data не совпал с реальным источником кнопки.
                # В большинстве случаев action_origin_menu_key будет равен current_menu_key.
                action_origin_menu_key = menu_key_to_search 
                break
        if action_item_found:
            break
    
    if not action_item_found:
        logger.warning(f"Menu button '{button_text}' pressed by user {user_id} was not matched to any action "
                       f"despite is_menu_button_text() returning True. Current menu was '{current_menu_key}'.")
        await update.message.reply_text(
            "Произошла ошибка при обработке вашего выбора. Пожалуйста, попробуйте еще раз или вернитесь в главное меню.",
            reply_markup=generate_menu_keyboard(current_menu_key) # Показываем текущее меню (или то, что считалось текущим)
        )
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]

    # Определяем, в какое меню вернуться после действия (обычно это родительское меню или главное)
    # Используем action_origin_menu_key, так как это фактическое меню, где была найдена кнопка.
    return_menu_key_after_action = MENU_STRUCTURE.get(action_origin_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
    if action_origin_menu_key == BotConstants.MENU_MAIN: # Если действие из главного меню, то и возвращаемся в него
        return_menu_key_after_action = BotConstants.MENU_MAIN


    # --- Диспетчеризация действий по типу ---
    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target, user_data_loc)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        response_message_text = "⚠️ Произошла ошибка: Выбранный агент не найден или не доступен."
        if action_target in AI_MODES and action_target != "gemini_pro_custom_mode": # gemini_pro_custom_mode устанавливается автоматически
            await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
            agent_details = AI_MODES[action_target]
            response_message_text = (f"🤖 Агент ИИ изменен на: <b>{agent_details['name']}</b>.\n"
                                     f"{agent_details.get('welcome', 'Готов к работе!')}")
        # После смены агента, показываем родительское меню (откуда пришли в выбор агентов)
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
            # Если пользователь выбирает Grok или GPT-4o mini, а текущий агент "Продвинутый" (для Gemini Pro),
            # сбрасываем агента на универсального, так как "Продвинутый" агент специфичен для Gemini Pro.
            if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and \
               user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
                update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
                logger.info(f"User {user_id} selected model {action_target}, AI mode reset from gemini_pro_custom_mode to default.")

            await firestore_service.set_user_data(user_id, update_payload)
            user_data_loc.update(update_payload) # Обновляем локальную копию для get_user_actual_limit_for_model

            # Получаем актуальные лимиты для выбранной модели
            bot_data_cache = await firestore_service.get_bot_data() # Кешируем, чтобы не делать два запроса
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
        await show_subscription(update, user_id) # Также может инициировать покупку, если /subscribe
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id)
    else:
        logger.warning(f"Unknown action type '{action_type}' for button '{button_text}' (target: '{action_target}') by user {user_id}.")
        await update.message.reply_text(
            "Выбранное действие не распознано. Пожалуйста, попробуйте еще раз.",
            reply_markup=generate_menu_keyboard(current_menu_key) # Возвращаем в текущее меню
        )
    return # Явный return для обозначения конца обработки кнопки


# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (ЗАПРОСЫ К AI) ---
# @auto_delete_message_decorator() # Не используем здесь, так как _store_and_try_delete_message вызывается в начале handle_text
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        return # Нет текста для обработки

    user_message_text = update.message.text.strip()

    # Сначала вызываем логику удаления сообщения пользователя.
    # Команды (/start и т.д.) обрабатываются декоратором у своих хендлеров.
    # Кнопки меню обрабатываются в menu_button_handler (там свое удаление).
    # Этот вызов для обычных текстовых сообщений, которые идут к ИИ.
    # is_command_to_keep=False означает, что это обычный текст, и его можно попытаться удалить.
    await _store_and_try_delete_message(update, user_id, is_command_to_keep=False)


    # Еще раз проверяем, не является ли это текстом кнопки меню, который мог "проскочить"
    # Это важно, если menu_button_handler по какой-то причине не сработал или не был первым в очереди.
    if is_menu_button_text(user_message_text): 
        logger.debug(f"User {user_id} sent menu button text '{user_message_text}' that reached handle_text. Explicitly ignoring.")
        # Если это все-таки кнопка меню, menu_button_handler должен был ее обработать.
        # Здесь можно либо ничего не делать, либо продублировать логику menu_button_handler,
        # но лучше убедиться, что menu_button_handler имеет приоритет (через группы хендлеров).
        # Для безопасности, если это кнопка, не отправляем ее в ИИ.
        return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id) # Нужен для generate_menu_keyboard
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
        # Если лимит исчерпан, check_and_log_request_attempt уже мог сменить модель на дефолтную
        # Обновим user_data_cache, чтобы меню было правильным
        user_data_cache = await firestore_service.get_user_data(user_id) 
        await update.message.reply_text( # Дополнительное сообщение о смене модели
             "Пожалуйста, выберите другую модель или попробуйте снова позже.",
             reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN))
        )
        return

    # Если лимит был исчерпан и модель сменилась, нужно получить новый current_model_key_val
    # Это важно, если check_and_log_request_attempt изменил модель пользователя.
    current_model_key_val = await get_current_model_key(user_id, user_data_cache) # Перечитываем на случай смены
    ai_service = get_ai_service(current_model_key_val)

    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{current_model_key_val}' for user {user_id}.")
        await update.message.reply_text(
            "Произошла критическая ошибка при выборе AI модели. Пожалуйста, сообщите администратору или попробуйте /start.",
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN))
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details_val = await get_current_mode_details(user_id, user_data_cache)
    system_prompt_val = mode_details_val["prompt"]
    
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ в данный момент." # Ответ по умолчанию
    try:
        ai_response_text = await ai_service.generate_response(system_prompt_val, user_message_text)
    except Exception as e: # Общий обработчик на случай непредвиденных ошибок в сервисах
        logger.error(f"Unhandled exception in AI service {type(ai_service).__name__} for model {current_model_key_val}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса моделью {ai_service.model_config['name']}. Попробуйте позже."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    await increment_request_count(user_id, current_model_key_val)
    
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
        disable_web_page_preview=True # Отключаем предпросмотр ссылок в ответах ИИ
    )
    logger.info(f"Successfully sent AI response (model: {current_model_key_val}) to user {user_id}.")


# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    # Проверяем, что payload соответствует ожидаемому формату для подписки
    # Например, "subscription_profi_access_v1_user_12345"
    # Здесь упрощенная проверка, но в реальности она может быть строже
    expected_payload_part = f"subscription_{CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY}" 
    if query.invoice_payload and expected_payload_part in query.invoice_payload:
        await query.answer(ok=True)
        logger.info(f"PreCheckoutQuery OK for payload: {query.invoice_payload}")
    else:
        await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату. Пожалуйста, попробуйте сформировать счет заново.")
        logger.warning(f"PreCheckoutQuery FAILED. Expected '{expected_payload_part}' in payload, got: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload # Должен содержать информацию о типе подписки и пользователе

    logger.info(f"Successful payment received from user {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {invoice_payload}")

    # TODO: Добавить более строгую валидацию payload, чтобы убедиться, что это оплата за нужную услугу.
    # Например, извлечь user_id из payload и сравнить с update.effective_user.id.

    subscription_days = 30 # Стандартный срок подписки
    
    bot_data = await firestore_service.get_bot_data()
    user_subscriptions_map = bot_data.get(BotConstants.FS_USER_SUBSCRIPTIONS_KEY, {})
    current_user_subscription = user_subscriptions_map.get(str(user_id), {})
    
    now_utc = datetime.now(timezone.utc)
    subscription_start_date = now_utc

    # Если у пользователя уже есть активная подписка Profi, продлеваем ее
    if is_user_profi_subscriber(current_user_subscription):
        try:
            previous_valid_until = datetime.fromisoformat(current_user_subscription['valid_until'])
            if previous_valid_until.tzinfo is None: 
                previous_valid_until = previous_valid_until.replace(tzinfo=timezone.utc)
            
            # Если предыдущая подписка еще не истекла, начинаем новую с даты окончания старой
            if previous_valid_until > now_utc:
                subscription_start_date = previous_valid_until
        except (ValueError, KeyError):
            logger.warning(f"Could not parse previous 'valid_until' for user {user_id}. Starting new subscription from now.")
            # Если дата старой подписки некорректна, начинаем новую с текущего момента

    new_valid_until_date = subscription_start_date + timedelta(days=subscription_days)

    user_subscriptions_map[str(user_id)] = {
        'level': CONFIG.PRO_SUBSCRIPTION_LEVEL_KEY,
        'valid_until': new_valid_until_date.isoformat(),
        'last_payment_amount': payment_info.total_amount, # Сумма в минимальных единицах валюты (копейки, центы)
        'currency': payment_info.currency,
        'purchase_date': now_utc.isoformat(),
        'telegram_payment_charge_id': payment_info.telegram_payment_charge_id, # Важно для сверки
        'provider_payment_charge_id': payment_info.provider_payment_charge_id # Важно для сверки
    }
    
    await firestore_service.set_bot_data({BotConstants.FS_USER_SUBSCRIPTIONS_KEY: user_subscriptions_map})

    confirmation_message = (
        f"🎉 Оплата прошла успешно! Ваша подписка <b>Profi</b> активирована и будет действительна "
        f"до <b>{new_valid_until_date.strftime('%d.%m.%Y')}</b>.\n\n"
        "Спасибо за поддержку! Теперь вам доступны все преимущества Profi."
    )
    
    user_data_for_reply_menu = await firestore_service.get_user_data(user_id)
    await update.message.reply_text(
        confirmation_message, 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', BotConstants.MENU_MAIN))
    )

    # Уведомление администратору о новой оплате
    if CONFIG.ADMIN_ID:
        try:
            admin_message = (
                f"🔔 Новая успешная оплата!\n"
                f"Пользователь: {user_id} ({update.effective_user.full_name})\n"
                f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n" # Переводим в обычные единицы
                f"Подписка Profi до: {new_valid_until_date.strftime('%d.%m.%Y')}\n"
                f"Payload: {invoice_payload}"
            )
            await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
        except Exception as e:
            logger.error(f"Failed to send payment notification to admin: {e}")


# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    # Собираем traceback для логов и, возможно, для отправки админу
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Пытаемся отправить сообщение пользователю, если это возможно
    if isinstance(update, Update) and update.effective_chat:
        user_data_for_error_reply = {} # Пустой по умолчанию
        if update.effective_user: # Если есть пользователь, получаем его данные для меню
             user_data_for_error_reply = await firestore_service.get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="К сожалению, во время обработки вашего запроса произошла внутренняя ошибка. "
                     "Я уже уведомил разработчиков. Пожалуйста, попробуйте выполнить команду /start или выберите действие из меню.",
                reply_markup=generate_menu_keyboard(user_data_for_error_reply.get('current_menu', BotConstants.MENU_MAIN))
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")

    # Отправляем детальную информацию об ошибке администратору
    if CONFIG.ADMIN_ID and isinstance(update, Update) and update.effective_user: # Добавил проверку на effective_user
        error_details = (
            f"🤖 Обнаружена ошибка в боте:\n"
            f"Тип ошибки: {context.error.__class__.__name__}\n"
            f"Сообщение: {context.error}\n"
            f"Пользователь: ID {update.effective_user.id} (@{update.effective_user.username})\n"
            f"Сообщение пользователя: {update.message.text if update.message else 'N/A'}\n\n"
            f"Traceback (первые 3500 символов):\n```\n{tb_string[:3500]}\n```"
        )
        try:
            await context.bot.send_message(CONFIG.ADMIN_ID, error_details, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.error(f"Failed to send detailed error report to admin: {e}. Fallback to plain text.")
            try: # Попытка отправить в простом тексте, если Markdown не удался
                 await context.bot.send_message(CONFIG.ADMIN_ID, error_details.replace("```", ""))
            except Exception as e_plain:
                 logger.error(f"Failed to send plain text detailed error report to admin: {e_plain}")


# --- ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА ---
async def main():
    # Конфигурация Google Gemini API (если используется)
    if CONFIG.GOOGLE_GEMINI_API_KEY and \
       "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY and \
       CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"):
        try:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API successfully configured.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API: {e}", exc_info=True)
    else:
        logger.warning("Google Gemini API key is not configured correctly or is missing. Models using it may not work.")

    # Проверка других ключей API (просто логирование предупреждений)
    for key_name in ["CUSTOM_GEMINI_PRO_API_KEY", "CUSTOM_GROK_3_API_KEY", "CUSTOM_GPT4O_MINI_API_KEY"]:
        key_value = getattr(CONFIG, key_name, "")
        if not key_value or "YOUR_" in key_value or not (key_value.startswith("sk-") or key_value.startswith("AIzaSy")):
            logger.warning(f"API key {key_name} seems to be incorrect or missing. Custom models relying on it might not work.")
    
    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN:
        logger.warning("Payment Provider Token is not configured. Payment functionality will not work.")

    if not firestore_service._db: # Проверка инициализации Firestore (через service) pylint: disable=protected-access
        logger.critical("Firestore (db) was NOT initialized successfully! Bot will have limited functionality or may not work correctly.")
        # Можно добавить логику аварийного завершения, если Firestore критичен
        # return

    app_builder = Application.builder().token(CONFIG.TELEGRAM_TOKEN)
    # Настройка таймаутов для HTTP-запросов Telegram API
    app_builder.read_timeout(30).connect_timeout(30) 
    # Увеличение pool_timeout, если ожидаются долгие операции или много одновременных пользователей
    # app_builder.pool_timeout(60) 
    app = app_builder.build()

    # Регистрация обработчиков
    # Группа 0: Команды - самый высокий приоритет
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("subscribe", subscribe_info_command), group=0) # Также может инициировать платеж
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    # Группа 1: Обработчик кнопок меню
    # Он должен идти перед общим обработчиком текста, чтобы перехватывать нажатия кнопок.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    
    # Группа 2: Общий обработчик текстовых сообщений (запросы к ИИ)
    # Срабатывает, если сообщение не команда и не кнопка меню.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    # Обработчики платежей
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Обработчик ошибок (глобальный)
    app.add_error_handler(error_handler)

    # Установка команд бота для отображения в Telegram
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск бота / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Показать мои лимиты использования"),
        BotCommand("subscribe", "💎 Информация о Profi подписке / Оформить"),
        BotCommand("bonus", "🎁 Получить бонус за подписку на канал"),
        BotCommand("help", "❓ Получить справку по боту")
    ]
    try:
        await app.bot.set_my_commands(bot_commands)
        logger.info("Bot commands have been successfully set.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}", exc_info=True)

    logger.info("Bot polling is starting...")
    # Запуск бота с указанием всех типов обновлений
    await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30) # timeout для long polling

if __name__ == '__main__':
    asyncio.run(main())
