import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from .bot import get_user_data, set_user_data, NEWS_CHANNEL_USERNAME, NEWS_CHANNEL_LINK, NEWS_CHANNEL_BONUS_MODEL_KEY, NEWS_CHANNEL_BONUS_GENERATIONS, AVAILABLE_TEXT_MODELS, MENU_STRUCTURE

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def claim_news_bonus_logic(update: Update, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка получения бонуса за подписку на новостной канал.
    Проверяет подписку, начисляет бонусные генерации, если пользователь подписан.
    """
    user = update.effective_user
    user_data = await get_user_data(user_id)

    # Сохранение и удаление сообщения пользователя
    if update.message:
        user_data['user_command_message'] = {
            'message_id': update.message.message_id,
            'timestamp': datetime.now().isoformat()
        }
        await set_user_data(user_id, user_data)
        await try_delete_user_message(update, user_id)

    # Определение меню для возврата
    parent_menu_key = user_data.get('current_menu', 'bonus_submenu')
    if parent_menu_key not in MENU_STRUCTURE:
        parent_menu_key = 'main_menu'

    # Проверка настройки канала
    if not NEWS_CHANNEL_USERNAME or NEWS_CHANNEL_USERNAME == "@YourNewsChannelHandle":
        await update.message.reply_text(
            "Функция бонуса за подписку на канал не настроена.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            parse_mode=None,
            disable_web_page_preview=True
        )
        logger.info(f"Bonus feature not configured for user {user_id}.")
        return

    # Проверка конфигурации бонусной модели
    bonus_model_config = AVAILABLE_TEXT_MODELS.get(NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text(
            "Ошибка: Бонусная модель не найдена. Обратитесь к администратору.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            parse_mode=None,
            disable_web_page_preview=True
        )
        logger.error(f"Bonus model '{NEWS_CHANNEL_BONUS_MODEL_KEY}' not found.")
        return

    bonus_model_name = bonus_model_config['name']

    # Проверка статуса бонуса
    if user_data.get('claimed_news_bonus', False):
        uses_left = user_data.get('news_bonus_uses_left', 0)
        reply_text = (
            f"Вы уже активировали бонус за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал</a>. "
            f"Осталось <b>{uses_left}</b> бонусных генераций для модели {bonus_model_name}."
        ) if uses_left > 0 else (
            f"Бонус за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал</a> для модели {bonus_model_name} использован."
        )
        await update.message.reply_text(
            reply_text,
            parse_mode=ParseMode.HTML,
            reply_markup=generate_menu_keyboard(parent_menu_key),
            disable_web_page_preview=True
        )
        logger.info(f"User {user_id} checked bonus status: {uses_left} uses left.")
        return

    # Проверка подписки на канал
    try:
        channel = NEWS_CHANNEL_USERNAME if NEWS_CHANNEL_USERNAME.startswith('@') else f"@{NEWS_CHANNEL_USERNAME}"
        member_status = await context.bot.get_chat_member(chat_id=channel, user_id=user.id)

        if member_status.status in ['member', 'administrator', 'creator']:
            user_data['claimed_news_bonus'] = True
            user_data['news_bonus_uses_left'] = NEWS_CHANNEL_BONUS_GENERATIONS
            await set_user_data(user_id, user_data)
            await update.message.reply_text(
                f"🎉 Спасибо за подписку на <a href='{NEWS_CHANNEL_LINK}'>канал {channel}</a>! "
                f"Начислено <b>{NEWS_CHANNEL_BONUS_GENERATIONS}</b> бонусных генераций для модели {bonus_model_name}.",
                parse_mode=ParseMode.HTML,
                reply_markup=generate_menu_keyboard('main_menu'),
                disable_web_page_preview=True
            )
            logger.info(f"User {user_id} claimed bonus for {bonus_model_name}.")
        else:
            await update.message.reply_text(
                f"Подпишитесь на <a href='{NEWS_CHANNEL_LINK}'>канал {channel}</a> и нажмите «🎁 Получить» в меню «Бонус».",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"📢 Перейти в канал {channel}", url=NEWS_CHANNEL_LINK)
                ]]),
                disable_web_page_preview=True
            )
            logger.info(f"User {user_id} not subscribed to {channel}.")
    except BadRequest as e:
        logger.error(f"Error checking channel membership for {NEWS_CHANNEL_USERNAME}: {e}")
        await update.message.reply_text(
            f"Не удалось проверить подписку на <a href='{NEWS_CHANNEL_LINK}'>канал {NEWS_CHANNEL_USERNAME}</a>. "
            f"Попробуйте позже.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📢 Перейти в {NEWS_CHANNEL_USERNAME}", url=NEWS_CHANNEL_LINK)
            ]]),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Unexpected error in bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Ошибка при получении бонуса. Попробуйте позже.",
            reply_markup=generate_menu_keyboard(parent_menu_key),
            parse_mode=None,
            disable_web_page_preview=True
        )

async def try_delete_user_message(update: Update, user_id: int):
    """Удаление сообщения пользователя, если оно не старше 48 часов."""
    if not update.message:
        return

    user_data = await get_user_data(user_id)
    message_data = user_data.get('user_command_message', {})
    message_id = message_data.get('message_id')
    timestamp = message_data.get('timestamp')

    if not message_id or not timestamp:
        return

    try:
        from datetime import datetime, timedelta
        msg_time = datetime.fromisoformat(timestamp)
        if datetime.now(msg_time.tzinfo) - msg_time > timedelta(hours=48):
            logger.info(f"Message {message_id} is too old, clearing record.")
            user_data.pop('user_command_message', None)
            await set_user_data(user_id, user_data)
            return
        await update.get_bot().delete_message(chat_id=update.effective_chat.id, message_id=message_id)
        logger.info(f"Deleted message {message_id} for user {user_id}.")
    except BadRequest as e:
        logger.warning(f"Failed to delete message {message_id}: {e}")
    finally:
        user_data.pop('user_command_message', None)
        await set_user_data(user_id, user_data)
