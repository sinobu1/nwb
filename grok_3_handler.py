import logging
import os
import asyncio
import requests
from typing import Tuple

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация модели Grok 3
GROK_3_CONFIG = {
    "name": "Grok 3",
    "id": "grok-3-beta",
    "api_type": "custom_http_api",
    "endpoint": os.getenv("GROK_3_ENDPOINT", "https://api.gen-api.ru/api/v1/networks/grok-3"),
    "api_key_var_name": "CUSTOM_GROK_3_API_KEY",
    "is_limited": True,
    "limit_type": "subscription_custom_pro",
    "limit_if_no_subscription": 3,
    "subscription_daily_limit": 25,
    "cost_category": "custom_api_grok_3_paid",
    "pricing_info": {}
}

# Ключ API для Grok 3
CUSTOM_GROK_3_API_KEY = os.getenv("CUSTOM_GROK_3_API_KEY", "sk-MHulnEHU3bRxsnDjr0nq68lTcRYa5IpQATY1pUG4NaxpWSMJzvzsJ4KCVu0P")

# Максимальная длина ответа
MAX_OUTPUT_TOKENS = 2048

async def query_grok_3(system_prompt: str, user_message: str) -> Tuple[str, bool]:
    """
    Отправка запроса к модели Grok 3 через HTTP API.
    Args:
        system_prompt: Системный промпт для модели.
        user_message: Сообщение пользователя.
    Returns:
        Текст ответа и флаг успешности запроса.
    """
    # Проверка валидности ключа API
    if not CUSTOM_GROK_3_API_KEY or "YOUR_CUSTOM_KEY" in CUSTOM_GROK_3_API_KEY or not CUSTOM_GROK_3_API_KEY.startswith("sk-"):
        logger.error("Invalid Grok 3 API key.")
        return "Ошибка: Ключ API для Grok 3 не настроен.", False

    headers = {
        "Authorization": f"Bearer {CUSTOM_GROK_3_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Формирование payloads
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "model": GROK_3_CONFIG["id"],
        "is_sync": True,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 1.0,
        "top_p": 1.0,
        "n": 1,
        "stream": False
    }

    try:
        logger.info(f"Sending request to Grok 3 API: {GROK_3_CONFIG['endpoint']}")
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(GROK_3_CONFIG["endpoint"], headers=headers, json=payload, timeout=45)
        )
        response.raise_for_status()
        response_json = response.json()

        # Извлечение текста ответа
        extracted_text = None
        if "response" in response_json and isinstance(response_json["response"], list) and response_json["response"]:
            completion = response_json["response"][0]
            if "choices" in completion and isinstance(completion["choices"], list) and completion["choices"]:
                choice = completion["choices"][0]
                if "message" in choice and isinstance(choice["message"], dict):
                    extracted_text = choice["message"].get("content", "").strip()

        if not extracted_text:
            logger.warning(f"No text content in Grok 3 response: {response_json}")
            return "Ответ от API пуст или не удалось извлечь текст.", False

        logger.info(f"Grok 3 response received. Length: {len(extracted_text)}")
        return extracted_text, True

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTPError for Grok 3 API: {e}. Response: {e.response.text if e.response else 'No response'}")
        return f"Ошибка сети ({e.response.status_code}). Попробуйте позже.", False
    except requests.exceptions.RequestException as e:
        logger.error(f"RequestException for Grok 3 API: {e}")
        return f"Сетевая ошибка: {type(e).__name__}. Проверьте соединение.", False
    except Exception as e:
        logger.error(f"Unexpected error with Grok 3 API: {e}")
        return f"Неожиданная ошибка: {type(e).__name__}.", False
