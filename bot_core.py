import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple, List
from abc import ABC, abstractmethod

import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from google.cloud.firestore_v1.client import Client as FirestoreClient
import google.generativeai as genai
import google.api_core.exceptions
import requests
from telegram import ReplyKeyboardMarkup, KeyboardButton # Только для generate_menu_keyboard, если она останется тут


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

    NEWS_CHANNEL_USERNAME = "@timextech" # Пример
    NEWS_CHANNEL_LINK = "https://t.me/timextech" # Пример
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

# --- ОПРЕДЕЛЕНИЯ РЕЖИМОВ И МОДЕЛЕЙ ---
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
        self._loop = asyncio.get_event_loop() # Сохраняем цикл событий для run_in_executor
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
        return await self._loop.run_in_executor(None, lambda: func(*args, **kwargs))

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

# Инициализация сервиса Firestore (глобальный экземпляр)
firestore_service = FirestoreService(
    cert_path=CONFIG.FIREBASE_CERT_PATH,
    creds_json_str=CONFIG.FIREBASE_CREDENTIALS_JSON_STR
)

# --- СЕРВИСЫ ДЛЯ РАБОТЫ С AI ---
class BaseAIService(ABC):
    def __init__(self, model_config: Dict[str, Any]):
        self.model_config = model_config
        self.model_id = model_config["id"]
        self._loop = asyncio.get_event_loop()

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
            response = await self._loop.run_in_executor(
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
        is_gpt4o_like = (self.model_id == "gpt-4o-mini")
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
            "is_sync": True,
            "max_tokens": self.model_config.get("max_tokens", CONFIG.MAX_OUTPUT_TOKENS_GEMINI_LIB)
        }
        if self.model_config.get("parameters"):
            payload.update(self.model_config["parameters"])
        
        endpoint = self.model_config["endpoint"]
        try:
            response = await self._loop.run_in_executor(
                None,
                lambda: requests.post(endpoint, headers=headers, json=payload, timeout=45)
            )
            response.raise_for_status()
            json_resp = response.json()
            
            extracted_text = None
            if self.model_id == "grok-3-beta":
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
            if extracted_text is None:
                for key_check in ["text", "content", "message", "output", "response"]:
                    if isinstance(json_resp.get(key_check), str) and (check_val := json_resp[key_check].strip()):
                        extracted_text = check_val; break
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

# --- УТИЛИТАРНЫЕ ФУНКЦИИ ---
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
    else: return 0
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
    if not model_cfg or not model_cfg.get("is_limited"): return
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

# --- ФУНКЦИИ ДЛЯ РАБОТЫ С МЕНЮ ---
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
    if menu_key in [BotConstants.MENU_MAIN, BotConstants.MENU_MODELS_SUBMENU]:
        for i in range(0, len(items), 2):
            keyboard_rows.append(
                [KeyboardButton(items[j]["text"]) for j in range(i, min(i + 2, len(items)))]
            )
    else:
        for item in items: keyboard_rows.append([KeyboardButton(item["text"])])
    if menu_config.get("is_submenu", False):
        navigation_row = [KeyboardButton("🏠 Главное меню")]
        if menu_config.get("parent"): navigation_row.insert(0, KeyboardButton("⬅️ Назад"))
        keyboard_rows.append(navigation_row)
    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)
