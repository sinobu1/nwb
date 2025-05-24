# main.py
import asyncio
from telegram import BotCommand, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
)

# Импортируем конфигурацию, логгер, сервисы и глобальные объекты из config.py
from config import CONFIG, logger, firestore_service, genai

# Импортируем все наши обработчики из handlers.py
from handlers import (
    start, open_menu_command, usage_command,
    subscribe_info_command, get_news_bonus_info_command, help_command,
    menu_button_handler, handle_text, precheckout_callback,
    successful_payment_callback, error_handler
)

async def main():
    """Основная функция для запуска бота."""
    
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
        logger.warning("Google Gemini API key is not configured correctly or is missing.")

    # Проверка других ключей API
    for key_name in ["CUSTOM_GEMINI_PRO_API_KEY", "CUSTOM_GROK_3_API_KEY", "CUSTOM_GPT4O_MINI_API_KEY"]:
        key_value = getattr(CONFIG, key_name, "")
        if not key_value or "YOUR_" in key_value or not (key_value.startswith("sk-")):
            logger.warning(f"API key {key_name} seems incorrect or is missing.")
    
    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN:
        logger.warning("Payment Provider Token is not configured. Payment functionality will not work.")

    if not firestore_service._db:
        logger.critical("Firestore (db) was NOT initialized successfully! Bot will not work correctly.")
        return

    # Сборка приложения
    app_builder = Application.builder().token(CONFIG.TELEGRAM_TOKEN)
    app_builder.read_timeout(30).connect_timeout(30)
    app = app_builder.build()

    # Регистрация обработчиков с группами для правильного порядка срабатывания
    # Группа 0: Команды
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("subscribe", subscribe_info_command), group=0)
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    # Группа 1: Обработчик кнопок меню
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    
    # Группа 2: Общий обработчик текстовых сообщений (запросы к ИИ)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    # Обработчики платежей
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Глобальный обработчик ошибок
    app.add_error_handler(error_handler)

    # Установка команд бота
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
    await app.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)

if __name__ == '__main__':
    asyncio.run(main())
