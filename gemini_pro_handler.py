import logging
import os
import asyncio
import requests
from typing import Tuple

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация модели Gemini 2.5 Pro
GEMINI_PRO_CONFIG = {
    "name": "Gemini Pro",
    "id": "gemini-2.5-pro-preview-03-25",
    "api_type": "custom_http_api",
    "endpoint": os.getenv("CUSTOM_GEMINI_PRO_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/gemini-2-5-pro"),
    "api_key_var_name": "CUSTOM_GEMINI_PRO_API_KEY",
    "is_limited": True,
    "limit_type": "subscription_custom_pro",
    "limit_if_no_subscription": 0,
    "subscription_daily_limit": 25,
    "cost_category": "custom_api_pro_paid",
    "pricing_info": {}
}

# Ключ API для Gemini 2.5 Pro
CUSTOM_GEMINI_PRO_API_KEY = os.getenv("CUSTOM_GEMINI_PRO_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")

# Максимальная длина ответа
MAX_OUTPUT_TOKENS = 2048

async def query_gemini_pro(system_prompt: str, user_message: str) -> Tuple[str, bool]:
    """
    Отправка запроса к модели Gemini 2.5 Pro через HTTP API.
    Args:
        system_prompt: Системный промпт для модели.
        user_message: Сообщение пользователя.
    Returns:
        Текст ответа и флаг успешности запроса.
    """
    # Проверка валидности ключа API
    if not CUSTOM_GEMINI_PRO_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GEMINI_PRO_API_KEY or not CUSTOM_GEMINI_PRO_API_KEY.startswith("sk-"):
        logger.error("Invalid Gemini Pro API key.")
        return "Ошибка: Ключ API для Gemini Pro не настроен.", False

    headers = {
        "Authorization": f"Bearer {CUSTOM_GEMINI_PRO_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Формирование payload
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "model": GEMINI_PRO_CONFIG["id"],
        "is_sync": True,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 1.0,
        "top_p": 1.0,
        "n": 1,
        "stream": False
    }

    try:
        logger.info(f"Sending request to Gemini 2.5 Pro API: {GEMINI_PRO_CONFIG['endpoint']}")
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(GEMINI_PRO_CONFIG["endpoint"], headers=headers, json=payload, timeout=45)
        )
        response.raise_for_status()
        response_json = response.json()

        # Извлечение текста ответа
        extracted_text = response_json.get("text", "").strip()
        if not extracted_text:
            logger.warning(f"No text content in Gemini 2.5 Pro response: {response_json}")
            return "Ответ от API пуст или не удалось извлечь текст.", False

        logger.info(f"Gemini 2.5 Pro response received. Length: {len(extracted_text)}")
        return extracted_text, True

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTPError for Gemini 2.5 Pro API: {e}. Response: {e.response.text if e.response else 'No response'}")
        return f"Ошибка сети ({e.response.status_code}). Попробуйте позже.", False
    except requests.exceptions.RequestException as e:
        logger.error(f"RequestException for Gemini 2.5 Pro API: {e}")
        return f"Сетевая ошибка: {type(e).__name__}. Проверьте соединение.", False
    except Exception as e:
        logger.error(f"Unexpected error with Gemini 2.5 Pro API: {e}")
        return f"Неожиданная ошибка: {type(e).__name__}.", False
