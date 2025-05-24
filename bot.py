import telegram
from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, Update,
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler
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
from typing import Optional, Dict, Any, Tuple, List
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app # <-- ИСПРАВЛЕНА ЭТА СТРОКА
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1.client import Client as FirestoreClient
from abc import ABC, abstractmethod # Для абстрактных классов

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
    PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "390540012:LIVE:70602") # УБЕДИТЕСЬ, ЧТО ЭТО LIVE ТОКЕН
    ADMIN_ID = int(os.getenv("ADMIN_ID", "489230152"))
    FIREBASE_CREDENTIALS_JSON_STR = os.getenv("FIREBASE_CREDENTIALS")
    FIREBASE_CERT_PATH = "gemioracle-firebase-adminsdk-fbsvc-8f89d5b941.json"
    
    CUSTOM_GEMINI_PRO_ENDPOINT = os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro")
    
    MAX_OUTPUT_TOKENS_GEMINI_LIB = 2048
    MAX_MESSAGE_LENGTH_TELEGRAM = 4000
    MIN_AI_REQUEST_LENGTH = 4

    DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY = 72
    DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY = 48
    DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY = 25 # Бесплатные попытки для GPT-4o mini

    NEWS_CHANNEL_USERNAME = "@timextech"
    NEWS_CHANNEL_LINK = "https://t.me/timextech"
    NEWS_CHANNEL_BONUS_MODEL_KEY = "custom_api_gemini_2_5_pro"
    NEWS_CHANNEL_BONUS_GENERATIONS = 1

    DEFAULT_AI_MODE_KEY = "universal_ai_basic"
    DEFAULT_MODEL_KEY = "google_gemini_2_0_flash"
    DEFAULT_USER_GEMS = 0.0 # Начальный баланс гемов для новых пользователей

CONFIG = AppConfig()

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
    FS_ALL_USER_DAILY_COUNTS_KEY = "all_user_daily_counts"

    MENU_MAIN = "main_menu"
    MENU_AI_MODES_SUBMENU = "ai_modes_submenu"
    MENU_MODELS_SUBMENU = "models_submenu"
    MENU_BALANCE_SUBMENU = "balance_submenu" # Переименовано из MENU_LIMITS_SUBMENU
    MENU_GEMS_SUBMENU = "gems_submenu" # Переименовано из MENU_SUBSCRIPTION_SUBMENU
    MENU_BONUS_SUBMENU = "bonus_submenu"
    MENU_HELP_SUBMENU = "help_submenu"

    CALLBACK_ACTION_SUBMENU = "submenu"
    CALLBACK_ACTION_SET_AGENT = "set_agent"
    CALLBACK_ACTION_SET_MODEL = "set_model"
    CALLBACK_ACTION_SHOW_BALANCE = "show_balance"
    CALLBACK_ACTION_BUY_GEMS = "buy_gems"
    CALLBACK_ACTION_CHECK_BONUS = "check_bonus"
    CALLBACK_ACTION_SHOW_HELP = "show_help"
    CALLBACK_ACTION_SEND_INVOICE = "send_invoice" # Для инлайн кнопок покупки гемов

    API_TYPE_GOOGLE_GENAI = "google_genai"
    API_TYPE_CUSTOM_HTTP = "custom_http_api"

# --- ОПРЕДЕЛЕНИЯ РЕЖИМОВ И МОДЕЛЕЙ ---
AI_MODES = {
    # ... (Содержимое AI_MODES оставлено без изменений, так как оно не затрагивалось)
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

AVAILABLE_TEXT_MODELS = {
    "google_gemini_2_0_flash": {
        "name": "Gemini 2.0", "id": "gemini-2.0-flash", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "limit": CONFIG.DEFAULT_FREE_REQUESTS_GOOGLE_FLASH_DAILY, "gem_cost": 0
    },
    "google_gemini_2_5_flash_preview": {
        "name": "Gemini 2.5", "id": "gemini-2.5-flash-preview-04-17", "api_type": BotConstants.API_TYPE_GOOGLE_GENAI,
        "is_limited": True, "limit": CONFIG.DEFAULT_FREE_REQUESTS_GEMINI_2_5_FLASH_PREVIEW_DAILY, "gem_cost": 0
    },
    "custom_api_gemini_2_5_pro": {
        "name": "Gemini Pro", "id": "gemini-2.5-pro-preview-03-25", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": CONFIG.CUSTOM_GEMINI_PRO_ENDPOINT, "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
        "is_limited": False, "gem_cost": 2.5
    },
    "custom_api_grok_3": {
        "name": "Grok 3", "id": "grok-3-beta", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/grok-3", "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
        "is_limited": False, "gem_cost": 2.5
    },
    "custom_api_gpt_4o_mini": {
        "name": "GPT-4o mini", "id": "gpt-4o-mini", "api_type": BotConstants.API_TYPE_CUSTOM_HTTP,
        "endpoint": "https://api.gen-api.ru/api/v1/networks/gpt-4o-mini", "api_key_var_name": "CUSTOM_GPT4O_MINI_API_KEY",
        "is_limited": True, "limit": CONFIG.DEFAULT_FREE_REQUESTS_GPT4O_MINI_DAILY, "gem_cost": 0.5
    }
}
DEFAULT_MODEL_ID = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]["id"]

MENU_STRUCTURE = {
    BotConstants.MENU_MAIN: {
        "title": "📋 Главное меню", "items": [
            {"text": "🤖 Агенты ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_AI_MODES_SUBMENU},
            {"text": "⚙️ Модели ИИ", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_MODELS_SUBMENU},
            {"text": "📊 Баланс и Лимиты", "action": BotConstants.CALLBACK_ACTION_SUBMENU, "target": BotConstants.MENU_BALANCE_SUBMENU},
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
    BotConstants.MENU_BALANCE_SUBMENU: {"title": "Ваш баланс и лимиты", "items": [{"text": "📊 Показать", "action": BotConstants.CALLBACK_ACTION_SHOW_BALANCE, "target": "usage"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_GEMS_SUBMENU: {"title": "Покупка гемов", "items": [{"text": "💰 Пополнить баланс", "action": BotConstants.CALLBACK_ACTION_BUY_GEMS, "target": "buy"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_BONUS_SUBMENU: {"title": "Бонус за подписку", "items": [{"text": "🎁 Получить", "action": BotConstants.CALLBACK_ACTION_CHECK_BONUS, "target": "news_bonus"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True},
    BotConstants.MENU_HELP_SUBMENU: {"title": "Помощь", "items": [{"text": "❓ Справка", "action": BotConstants.CALLBACK_ACTION_SHOW_HELP, "target": "help"}], "parent": BotConstants.MENU_MAIN, "is_submenu": True}
}

GEM_PACKAGES = {
    "pack_1": {"gems": 50, "price_rub": 100, "title": "Малый набор"},
    "pack_2": {"gems": 150, "price_rub": 250, "title": "Средний набор"},
    "pack_3": {"gems": 500, "price_rub": 750, "title": "Большой набор"},
}

# --- СЕРВИС ДЛЯ РАБОТЫ С FIRESTORE (без изменений) ---
class FirestoreService:
    def __init__(self, cert_path: str, creds_json_str: Optional[str] = None):
        self._db: Optional[Any] = None # FirestoreClient
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

# --- СЕРВИСЫ ДЛЯ РАБОТЫ С AI ---
class BaseAIService(ABC):
    # ... (Абстрактный класс BaseAIService оставлен без изменений)
    pass

class GoogleGenAIService(BaseAIService):
    # ... (Класс GoogleGenAIService оставлен без изменений)
    pass

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
        
        messages_payload = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        payload = {
            "messages": messages_payload,
            "model": self.model_id,
            "is_sync": True,
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
            
            # ИСПРАВЛЕННАЯ И УПРОЩЕННАЯ ЛОГИКА ИЗВЛЕЧЕНИЯ ТЕКСТА
            extracted_text = None
            try:
                # Приоритетный способ для OpenAI-совместимых API
                extracted_text = json_resp['choices'][0]['message']['content'].strip()
            except (KeyError, IndexError, TypeError):
                logger.warning(f"Could not extract text using ['choices'][0]['message']['content'] for model {self.model_id}. Trying other keys.")
                # Запасные варианты для разных форматов ответа
                if "text" in json_resp and isinstance(json_resp["text"], str):
                    extracted_text = json_resp["text"].strip()
                elif "output" in json_resp and isinstance(json_resp["output"], str):
                     extracted_text = json_resp["output"].strip()
                elif "response" in json_resp and isinstance(json_resp["response"], str):
                     extracted_text = json_resp["response"].strip()

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
    # ... (Функция get_ai_service оставлена без изменений)
    pass

# --- УТИЛИТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def _store_and_try_delete_message(update: Update, user_id: int, is_command_to_keep: bool = False):
    # ... (Функция _store_and_try_delete_message оставлена без изменений)
    pass

def auto_delete_message_decorator(is_command_to_keep: bool = False):
    # ... (Декоратор auto_delete_message_decorator оставлен без изменений)
    pass
    
async def get_current_model_key(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> str:
    # ... (Функция get_current_model_key оставлена без изменений)
    pass

async def get_selected_model_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # ... (Функция get_selected_model_details оставлена без изменений)
    pass

async def get_current_mode_details(user_id: int, user_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # ... (Функция get_current_mode_details оставлена без изменений)
    pass

def smart_truncate(text: str, max_length: int) -> Tuple[str, bool]:
    # ... (Функция smart_truncate оставлена без изменений)
    pass

async def process_request_cost(user_id: int, model_key: str) -> Tuple[bool, str]:
    """
    Проверяет возможность выполнения запроса (лимиты, гемы) и списывает стоимость.
    Возвращает (True, "") в случае успеха, или (False, "сообщение_об_ошибке").
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    model_cfg = AVAILABLE_TEXT_MODELS.get(model_key)
    if not model_cfg:
        return False, "Выбранная модель не найдена или неверно настроена."

    user_data = await firestore_service.get_user_data(user_id)
    bot_data = await firestore_service.get_bot_data()
    all_user_daily_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_daily_counts = all_user_daily_counts.get(str(user_id), {})
    model_usage_info = user_daily_counts.get(model_key, {'date': '', 'count': 0})
    
    # Сброс счетчика, если дата устарела
    if model_usage_info.get('date') != today_str:
        current_usage = 0
    else:
        current_usage = model_usage_info.get('count', 0)

    # --- Проверка для моделей с бесплатными попытками ---
    if model_cfg.get("is_limited", False) and model_cfg.get("limit", 0) > 0:
        if current_usage < model_cfg["limit"]:
            # Бесплатная попытка доступна, инкрементируем счетчик
            user_daily_counts[model_key] = {'date': today_str, 'count': current_usage + 1}
            all_user_daily_counts[str(user_id)] = user_daily_counts
            await firestore_service.set_bot_data({BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY: all_user_daily_counts})
            logger.info(f"User {user_id} used a free attempt for {model_key}. Usage: {current_usage + 1}/{model_cfg['limit']}")
            return True, ""
        # Бесплатные попытки закончились, переходим к проверке гемов, если модель платная
        if model_cfg['gem_cost'] == 0:
            msg = (f"Достигнут дневной лимит ({current_usage}/{model_cfg['limit']}) для бесплатной модели «{model_cfg['name']}».\n"
                   f"Попробуйте другую модель или возвращайтесь завтра!")
            return False, msg

    # --- Проверка для платных моделей (или моделей с платой после бесплатных попыток) ---
    gem_cost = model_cfg.get("gem_cost", 0)
    if gem_cost > 0:
        user_gems = float(user_data.get("gems", 0.0))
        if user_gems >= gem_cost:
            # Гемов достаточно, списываем
            new_balance = user_gems - gem_cost
            await firestore_service.set_user_data(user_id, {"gems": new_balance})
            logger.info(f"User {user_id} spent {gem_cost} gems for {model_key}. New balance: {new_balance}")
            return True, ""
        else:
            # Гемов недостаточно
            msg = (f"💎 Недостаточно гемов для использования модели «{model_cfg['name']}».\n\n"
                   f"Требуется: <b>{gem_cost}</b> гемов\n"
                   f"Ваш баланс: <b>{user_gems}</b> гемов\n\n"
                   f"Пожалуйста, пополните баланс, нажав «💎 Гемы» в меню или использовав команду /buy_gems.")
            return False, msg

    return False, "Произошла непредвиденная ошибка при проверке лимитов. Пожалуйста, сообщите администратору."

# --- ФУНКЦИИ МЕНЮ ---

def is_menu_button_text(text: str) -> bool:
    # ... (Функция is_menu_button_text оставлена без изменений)
    pass

def generate_menu_keyboard(menu_key: str) -> ReplyKeyboardMarkup:
    # ... (Функция generate_menu_keyboard оставлена без изменений)
    pass
    
async def show_menu(update: Update, user_id: int, menu_key: str, user_data_param: Optional[Dict[str, Any]] = None):
    # ... (Функция show_menu оставлена без изменений)
    pass

# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---

@auto_delete_message_decorator(is_command_to_keep=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    
    user_data_loc = await firestore_service.get_user_data(user_id)
    updates_to_user_data = {}

    # Инициализация пользовательских данных
    if 'gems' not in user_data_loc:
        updates_to_user_data['gems'] = CONFIG.DEFAULT_USER_GEMS
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
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance_and_limits(update, update.effective_user.id)

@auto_delete_message_decorator()
async def buy_gems_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_gems_purchase_options(update, update.effective_user.id)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Функционал бонуса оставлен без изменений, но вы можете его адаптировать под гемы)
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ ---

async def show_balance_and_limits(update: Update, user_id: int):
    user_data = await firestore_service.get_user_data(user_id)
    bot_data = await firestore_service.get_bot_data()
    
    user_gems = user_data.get("gems", 0.0)
    parts = [f"<b>📊 Ваш баланс и лимиты</b>\n\n💎 Ваш баланс: <b>{user_gems:.1f}</b> гемов.\n"]
    
    parts.append("<b>Стоимость и лимиты моделей:</b>")
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_user_daily_counts = bot_data.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {})
    user_counts_today = all_user_daily_counts.get(str(user_id), {})

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        cost = model_config.get("gem_cost", 0)
        cost_str = f"<b>{cost}</b> 💎" if cost > 0 else "бесплатно"
        
        limit_str = ""
        if model_config.get("is_limited", False):
            usage_info = user_counts_today.get(model_key, {'date': '', 'count': 0})
            current_day_usage = usage_info['count'] if usage_info.get('date') == today_str else 0
            limit = model_config.get('limit', 0)
            
            # Для GPT-4o mini показываем "ИЛИ"
            if cost > 0 and limit > 0:
                limit_str = f" (<b>{current_day_usage}/{limit}</b> беспл. сегодня, затем {cost_str})"
            else:
                 limit_str = f" (<b>{current_day_usage}/{limit}</b> в день)"
        
        parts.append(f"▫️ {model_config['name']}: {cost_str}{limit_str}")

    parts.append("\n💡 Для пополнения баланса используйте команду /buy_gems или меню «💎 Гемы».")
        
    current_menu_for_reply = user_data.get('current_menu', BotConstants.MENU_BALANCE_SUBMENU)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def show_gems_purchase_options(update: Update, user_id: int):
    text = "💎 <b>Пополнение баланса</b>\n\nВыберите один из пакетов гемов для покупки:"
    
    keyboard = []
    for key, package in GEM_PACKAGES.items():
        button_text = f"{package['title']} ({package['gems']} 💎) - {package['price_rub']} RUB"
        callback_data = f"{BotConstants.CALLBACK_ACTION_SEND_INVOICE}_{key}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
async def claim_news_bonus_logic(update: Update, user_id: int):
    # ... (Функция claim_news_bonus_logic оставлена без изменений)
    pass
    
async def show_help(update: Update, user_id: int):
    # ... (Справку нужно будет обновить, чтобы отразить систему гемов)
    pass

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Логика menu_button_handler нуждается в адаптации к новым константам)
    pass

# --- ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (ЗАПРОСЫ К AI) ---
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
    
    current_model_key_val = await get_current_model_key(user_id)
    
    # НОВАЯ ЛОГИКА ПРОВЕРКИ СТОИМОСТИ
    can_proceed, message = await process_request_cost(user_id, current_model_key_val)
    
    if not can_proceed:
        user_data_cache = await firestore_service.get_user_data(user_id)
        await update.message.reply_text(
            message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
            disable_web_page_preview=True
        )
        return

    ai_service = get_ai_service(current_model_key_val)
    if not ai_service:
        # ... (обработка ошибки, как в оригинале)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    user_data_cache = await firestore_service.get_user_data(user_id)
    mode_details_val = await get_current_mode_details(user_id, user_data_cache)
    system_prompt_val = mode_details_val["prompt"]
    
    try:
        ai_response_text = await ai_service.generate_response(system_prompt_val, user_message_text)
    except Exception as e:
        logger.error(f"Unhandled exception in AI service {type(ai_service).__name__} for model {current_model_key_val}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса. Попробуйте позже."

    final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
        disable_web_page_preview=True
    )
    logger.info(f"Successfully sent AI response (model: {current_model_key_val}) to user {user_id}.")

# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ЗА ГЕМЫ ---

async def send_gem_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет счет на оплату выбранного пакета гемов."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action, package_key = query.data.split('_', 1)

    if action != BotConstants.CALLBACK_ACTION_SEND_INVOICE or package_key not in GEM_PACKAGES:
        await query.edit_message_text("Ошибка: неверный пакет гемов.")
        return
        
    package = GEM_PACKAGES[package_key]
    title = f"Покупка гемов: {package['title']}"
    description = f"Вы получите {package['gems']} 💎 на ваш баланс."
    payload = f"gems_purchase_{package_key}_user_{user_id}"
    currency = "RUB"
    price = package['price_rub']
    prices = [LabeledPrice(f"{package['gems']} 💎", price * 100)] # Цена в копейках

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN,
        currency=currency,
        prices=prices
    )
    # Удаляем инлайн-кнопки после выбора
    await query.edit_message_text(f"Создан счет на покупку «{package['title']}». Пожалуйста, оплатите его.")


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload_parts = query.invoice_payload.split('_')
    
    # Валидация payload: gems_purchase_{package_key}_user_{user_id}
    if len(payload_parts) == 4 and payload_parts[0] == "gems" and payload_parts[1] == "purchase":
        package_key = payload_parts[2]
        if package_key in GEM_PACKAGES:
            await query.answer(ok=True)
            logger.info(f"PreCheckoutQuery OK for payload: {query.invoice_payload}")
            return

    await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату.")
    logger.warning(f"PreCheckoutQuery FAILED for payload: {query.invoice_payload}")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    payload = payment_info.invoice_payload
    
    logger.info(f"Successful payment received from user {user_id} for payload: {payload}")

    try:
        _, _, package_key, _ = payload.split('_')
        if package_key in GEM_PACKAGES:
            gems_to_add = GEM_PACKAGES[package_key]['gems']
            
            user_data = await firestore_service.get_user_data(user_id)
            current_gems = user_data.get("gems", 0.0)
            new_balance = float(current_gems) + float(gems_to_add)
            
            await firestore_service.set_user_data(user_id, {"gems": new_balance})
            
            confirmation_message = (
                f"🎉 Оплата прошла успешно! Вам начислено <b>{gems_to_add} 💎</b>.\n\n"
                f"Ваш новый баланс: <b>{new_balance:.1f}</b> гемов."
            )
            
            user_data_for_reply_menu = await firestore_service.get_user_data(user_id)
            await update.message.reply_text(
                confirmation_message, 
                parse_mode=ParseMode.HTML, 
                reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', BotConstants.MENU_MAIN))
            )

            # Уведомление администратору
            if CONFIG.ADMIN_ID:
                admin_message = (
                    f"🔔 Новая покупка гемов!\n"
                    f"Пользователь: {user_id} (@{update.effective_user.username or 'N/A'})\n"
                    f"Пакет: {GEM_PACKAGES[package_key]['title']} ({gems_to_add} 💎)\n"
                    f"Сумма: {payment_info.total_amount / 100} {payment_info.currency}\n"
                    f"Новый баланс: {new_balance:.1f} гемов"
                )
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)
        else:
            raise ValueError("Invalid package key in payload")
            
    except (ValueError, KeyError) as e:
        logger.error(f"Error processing successful payment for user {user_id} with payload {payload}: {e}")
        await update.message.reply_text("Произошла ошибка при зачислении гемов. Пожалуйста, свяжитесь с администратором.")
        if CONFIG.ADMIN_ID:
            await context.bot.send_message(CONFIG.ADMIN_ID, f"⚠️ Ошибка зачисления гемов для пользователя {user_id}! Payload: {payload}")


# --- ОБРАБОТЧИК ОШИБОК (без изменений) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (Функция error_handler оставлена без изменений)
    pass

# --- ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА ---
async def main():
    # ... (Конфигурация API ключей, как в оригинале)
    
    if not firestore_service._db:
        logger.critical("Firestore (db) was NOT initialized successfully! Bot will not work correctly.")
        return

    app = Application.builder().token(CONFIG.TELEGRAM_TOKEN).read_timeout(30).connect_timeout(30).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("balance", balance_command), group=0)
    app.add_handler(CommandHandler("buy_gems", buy_gems_command), group=0)
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    # Обработчик инлайн-кнопок для покупки гемов
    app.add_handler(CallbackQueryHandler(send_gem_invoice, pattern=f"^{BotConstants.CALLBACK_ACTION_SEND_INVOICE}_"))
    
    # Обработчик кнопок меню (текстовых)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    
    # Общий обработчик текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    # Обработчики платежей
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    app.add_error_handler(error_handler)

    # Установка команд бота
    bot_commands = [
        BotCommand("start", "🚀 Перезапуск / Главное меню"),
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("balance", "📊 Показать баланс и лимиты"),
        BotCommand("buy_gems", "💰 Купить гемы"),
        BotCommand("bonus", "🎁 Получить бонус"),
        BotCommand("help", "❓ Помощь")
    ]
    await app.bot.set_my_commands(bot_commands)

    logger.info("Bot polling is starting...")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Примечание: я убрал `nest_asyncio` из основного кода, так как `asyncio.run()` является
    # стандартным способом запуска. Если вы запускаете код в среде, где цикл событий уже
    # запущен (например, Jupyter), верните `nest_asyncio.apply()`.
    asyncio.run(main())
