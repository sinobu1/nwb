# main.py
import asyncio
from telegram import BotCommand, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PreCheckoutQueryHandler
)

# Импортируем конфигурацию, логгер, сервисы и глобальные объекты из config.py
from config import CONFIG, logger, firestore_service, genai # genai импортируется для настройки в main

# Импортируем все наши обработчики из handlers.py
from handlers import (
    start, open_menu_command, usage_command,
    gems_info_command, get_news_bonus_info_command, help_command, # Используем gems_info_command
    menu_button_handler, handle_text, precheckout_callback,
    successful_payment_callback, error_handler,
    photo_handler # Добавлен обработчик фото
)

async def main():
    """Основная функция для запуска бота."""
    
    # Конфигурация Google Gemini API (используется для Vision агента)
    if CONFIG.GOOGLE_GEMINI_API_KEY and \
       "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY and \
       CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"): # Проверка ключа
        try:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API (for Vision) successfully configured.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API (for Vision): {e}", exc_info=True)
    else:
        logger.warning("Google Gemini API key (for Vision) is not configured or is missing. Photo dietitian may not work.")

    # ... (остальные проверки API ключей и Firestore как были) ...
    if not firestore_service._db:
        logger.critical("Firestore (db) was NOT initialized successfully! Bot will not work correctly.")
        return

    app_builder = Application.builder().token(CONFIG.TELEGRAM_TOKEN)
    app_builder.read_timeout(30).connect_timeout(30)
    app = app_builder.build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("gems", gems_info_command), group=0) # Изменено с subscribe на gems
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler), group=1) # Обработчик фото
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    app.add_error_handler(error_handler)

    bot_commands = [
        BotCommand("menu", "📋 Открыть главное меню"),
        BotCommand("usage", "📊 Лимиты и баланс гемов"),
        BotCommand("gems", "💎 Магазин Гемов"),
        BotCommand("bonus", "🎁 Бонус канала"),
        BotCommand("help", "❓ Помощь")
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
