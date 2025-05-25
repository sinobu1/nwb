# main.py
import asyncio
from telegram import BotCommand, Update, Message
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, PreCheckoutQueryHandler
)
# ИМПОРТИРУЕМ ФИЛЬТРЫ ИЗ ОТДЕЛЬНОГО МОДУЛЯ
from telegram.ext import filters
from telegram.ext.filters import BaseFilter

# Импортируем конфигурацию, логгер, и т.д.
from config import CONFIG, logger, firestore_service, genai
from handlers import (
    start, open_menu_command, usage_command,
    gems_info_command, get_news_bonus_info_command, help_command,
    open_mini_app_command,
    web_app_data_handler,
    menu_button_handler, handle_text, precheckout_callback,
    successful_payment_callback, error_handler,
    photo_handler
)

# НАШ КАСТОМНЫЙ ФИЛЬТР (оставляем как есть)
class WebAppDataFilter(BaseFilter):
    """Фильтр для сообщений, содержащих данные от Web App"""
    def filter(self, message: Message) -> bool:
        return message.web_app_data is not None


async def main():
    """Основная функция для запуска бота."""
    
    # Конфигурация Google Gemini API (используется для Vision агента Диетолога)
    if CONFIG.GOOGLE_GEMINI_API_KEY and \
       "YOUR_" not in CONFIG.GOOGLE_GEMINI_API_KEY and \
       CONFIG.GOOGLE_GEMINI_API_KEY.startswith("AIzaSy"): # Проверка ключа
        try:
            genai.configure(api_key=CONFIG.GOOGLE_GEMINI_API_KEY)
            logger.info("Google Gemini API (for Vision) successfully configured.")
        except Exception as e:
            logger.error(f"Failed to configure Google Gemini API (for Vision): {e}", exc_info=True)
    else:
        logger.warning("Google Gemini API key (for Vision) is not configured or is missing. Photo dietitian may not work as intended.")

    # Проверка Firestore
    if not firestore_service._db: # Используем _db для проверки инициализации
        logger.critical("Firestore (db) was NOT initialized successfully! Bot will not work correctly.")
        return

    # Сборка приложения
    app_builder = Application.builder().token(CONFIG.TELEGRAM_TOKEN)
    app_builder.read_timeout(30).connect_timeout(30) # Настройка таймаутов
    app = app_builder.build()

    # Регистрация обработчиков с группами для правильного порядка срабатывания
    # Группа 0: Самые приоритетные обработчики - команды и данные из WebApp
    app.add_handler(CommandHandler("start", start), group=0)
    app.add_handler(CommandHandler("app", open_mini_app_command), group=0)
    app.add_handler(CommandHandler("menu", open_menu_command), group=0)
    app.add_handler(CommandHandler("usage", usage_command), group=0)
    app.add_handler(CommandHandler("gems", gems_info_command), group=0)
    app.add_handler(CommandHandler("bonus", get_news_bonus_info_command), group=0)
    app.add_handler(CommandHandler("help", help_command), group=0)
    
    app.add_handler(MessageHandler(WebAppDataFilter(), web_app_data_handler), group=0)
    
    # Группа 1: Обработчики специфичного контента (фото, платежи)
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback), group=1)
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback), group=1)
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler), group=1)
    
    # Группа 2: Обработчики текста. Они должны идти после специфичных обработчиков.
    # ВАЖНО: Ваша функция menu_button_handler должна проверять, является ли текст кнопкой,
    # и если нет, то НЕ обрабатывать его, чтобы управление перешло к handle_text.
    # Судя по коду, вы так и делаете (is_menu_button_text).
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler), group=2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text), group=2)

    # Глобальный обработчик ошибок
    app.add_error_handler(error_handler)

    # Установка команд бота, видимых в меню Telegram
    bot_commands = [
        BotCommand("app", "🚀 Открыть приложение GemiO"),
        BotCommand("menu", "📋 Показать клавиатуру меню"),
        BotCommand("help", "❓ Помощь"),
        BotCommand("usage", "📊 Лимиты и баланс"),
        BotCommand("gems", "💎 Магазин Гемов"),
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
