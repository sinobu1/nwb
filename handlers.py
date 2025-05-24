# handlers.py
import traceback
from datetime import datetime, timezone, timedelta
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes

# Импортируем всё необходимое из общего файла config.py
from config import (
    firestore_service, CONFIG, BotConstants, AVAILABLE_TEXT_MODELS,
    AI_MODES, MENU_STRUCTURE, auto_delete_message_decorator,
    get_current_model_key, get_current_mode_details,
    is_menu_button_text, generate_menu_keyboard, _store_and_try_delete_message,
    check_and_log_request_attempt, get_ai_service, smart_truncate,
    increment_request_count, logger, show_menu,
    get_user_gem_balance, update_user_gem_balance, get_daily_usage_for_model
)

# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---

@auto_delete_message_decorator(is_command_to_keep=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_first_name = update.effective_user.first_name
    
    user_data_loc = await firestore_service.get_user_data(user_id)
    updates_to_user_data = {} 

    if 'current_ai_mode' not in user_data_loc:
        updates_to_user_data['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
    if 'current_menu' not in user_data_loc:
        updates_to_user_data['current_menu'] = BotConstants.MENU_MAIN
        
    default_model_config = AVAILABLE_TEXT_MODELS[CONFIG.DEFAULT_MODEL_KEY]
    if 'selected_model_id' not in user_data_loc:
        updates_to_user_data['selected_model_id'] = default_model_config["id"]
    if 'selected_api_type' not in user_data_loc:
        updates_to_user_data['selected_api_type'] = default_model_config.get("api_type")

    if 'gem_balance' not in user_data_loc:
        updates_to_user_data['gem_balance'] = CONFIG.GEMS_FOR_NEW_USER 

    if updates_to_user_data:
        await firestore_service.set_user_data(user_id, updates_to_user_data)
        user_data_loc.update(updates_to_user_data)

    current_model_key_val = await get_current_model_key(user_id, user_data_loc)
    mode_details_res = await get_current_mode_details(user_id, user_data_loc)
    model_details_res = AVAILABLE_TEXT_MODELS.get(current_model_key_val)

    mode_name = mode_details_res.get('name', 'N/A')
    model_name = model_details_res.get('name', 'N/A')

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
    
    if user_data_loc.get('current_menu') != BotConstants.MENU_MAIN:
         await firestore_service.set_user_data(user_id, {'current_menu': BotConstants.MENU_MAIN})
    
    logger.info(f"User {user_id} ({user_first_name}) started or restarted the bot.")

@auto_delete_message_decorator()
async def open_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, update.effective_user.id, BotConstants.MENU_MAIN)

@auto_delete_message_decorator()
async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_limits(update, update.effective_user.id)

@auto_delete_message_decorator()
async def gems_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает меню покупки гемов."""
    await show_menu(update, update.effective_user.id, BotConstants.MENU_GEMS_SUBMENU)

@auto_delete_message_decorator()
async def get_news_bonus_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await claim_news_bonus_logic(update, update.effective_user.id)

@auto_delete_message_decorator()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_help(update, update.effective_user.id)

# --- ЛОГИКА ОТОБРАЖЕНИЯ ИНФОРМАЦИИ ---

async def show_limits(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    bot_data_loc = await firestore_service.get_bot_data()
    
    user_gem_balance = await get_user_gem_balance(user_id, user_data_loc)

    parts = [f"<b>💎 Ваш баланс: {user_gem_balance:.1f} гемов</b>\n"]
    parts.append("<b>📊 Ваши дневные бесплатные лимиты и стоимость:</b>\n")

    for model_key, model_config in AVAILABLE_TEXT_MODELS.items():
        if model_config.get("is_limited", True): # Считаем все модели лимитированными по умолчанию
            current_free_usage = await get_daily_usage_for_model(user_id, model_key, bot_data_loc)
            free_daily_limit = model_config.get('free_daily_limit', 0)
            gem_cost = model_config.get('gem_cost', 0.0)

            usage_display = f"Бесплатно сегодня: {current_free_usage}/{free_daily_limit}"
            cost_display = f"Стоимость: {gem_cost:.1f} гемов" if gem_cost > 0 else "Только бесплатно"
            
            bonus_notification = ""
            if model_key == CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY and \
               user_data_loc.get('claimed_news_bonus', False) and \
               (bonus_left := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
                bonus_notification = f" (еще <b>{bonus_left}</b> бонусных)"
            
            parts.append(f"▫️ {model_config['name']}: {usage_display}{bonus_notification}. {cost_display}")

    parts.append("")
    bonus_model_cfg = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if bonus_model_cfg:
        bonus_model_name_display = bonus_model_cfg['name']
        if not user_data_loc.get('claimed_news_bonus', False):
            parts.append(f'🎁 Подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">канал новостей</a>, чтобы получить {CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS} бонусных генераций для {bonus_model_name_display}! Нажмите «🎁 Бонус» в меню.')
        elif (bonus_left_val := user_data_loc.get('news_bonus_uses_left', 0)) > 0:
            parts.append(f"✅ У вас есть <b>{bonus_left_val}</b> бонусных генераций для {bonus_model_name_display}.")
        else:
            parts.append(f"ℹ️ Бонус с канала новостей для {bonus_model_name_display} был использован.")
    
    parts.append("\n💎 Пополнить баланс гемов можно через меню «💎 Гемы».")
        
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        "\n".join(parts), 
        parse_mode=ParseMode.HTML, 
        reply_markup=generate_menu_keyboard(current_menu_for_reply),
        disable_web_page_preview=True
    )

async def claim_news_bonus_logic(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    parent_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN) # Откуда пришел пользователь
    # Определяем, куда вернуть пользователя после действия
    current_menu_config = MENU_STRUCTURE.get(parent_menu_key, MENU_STRUCTURE[BotConstants.MENU_MAIN])
    reply_menu_key = current_menu_config.get("parent", BotConstants.MENU_MAIN) if current_menu_config.get("is_submenu") else parent_menu_key


    bonus_model_config = AVAILABLE_TEXT_MODELS.get(CONFIG.NEWS_CHANNEL_BONUS_MODEL_KEY)
    if not bonus_model_config:
        await update.message.reply_text("Ошибка: Бонусная модель не настроена.", reply_markup=generate_menu_keyboard(reply_menu_key))
        return
        
    bonus_model_name = bonus_model_config['name']

    if user_data_loc.get('claimed_news_bonus', False):
        uses_left = user_data_loc.get('news_bonus_uses_left', 0)
        reply_text = f"Вы уже активировали бонус. " + (f"У вас осталось: <b>{uses_left}</b> бонусных генераций для {bonus_model_name}." if uses_left > 0 else f"Бонусные генерации для {bonus_model_name} использованы.")
        await update.message.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key))
        return

    try:
        member_status = await update.get_bot().get_chat_member(chat_id=CONFIG.NEWS_CHANNEL_USERNAME, user_id=user_id)
        if member_status.status in ['member', 'administrator', 'creator']:
            await firestore_service.set_user_data(user_id, {
                'claimed_news_bonus': True, 
                'news_bonus_uses_left': CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS
            })
            success_text = (f'🎉 Спасибо за подписку на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>! '
                            f"Вам начислен бонус: <b>{CONFIG.NEWS_CHANNEL_BONUS_GENERATIONS}</b> генераций для модели {bonus_model_name}.")
            # После успешного получения бонуса, возвращаем в то меню, откуда пришли, или в главное
            await update.message.reply_text(success_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_key), disable_web_page_preview=True)
            # Обновляем current_menu на то, куда вернули
            await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_key}) 
        else:
            fail_text = (f'Сначала подпишитесь на <a href="{CONFIG.NEWS_CHANNEL_LINK}">{CONFIG.NEWS_CHANNEL_USERNAME}</a>, '
                         f'а затем вернитесь и нажмите кнопку еще раз.')
            inline_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"📢 Перейти на канал {CONFIG.NEWS_CHANNEL_USERNAME}", url=CONFIG.NEWS_CHANNEL_LINK)]])
            await update.message.reply_text(fail_text, parse_mode=ParseMode.HTML, reply_markup=inline_keyboard, disable_web_page_preview=True)
    except telegram.error.TelegramError as e:
        logger.error(f"Bonus claim error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при проверке подписки. Попробуйте позже.", reply_markup=generate_menu_keyboard(reply_menu_key))
    except Exception as e:
        logger.error(f"Unexpected error during news bonus claim for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Произошла непредвиденная ошибка.", reply_markup=generate_menu_keyboard(reply_menu_key))


async def show_help(update: Update, user_id: int):
    user_data_loc = await firestore_service.get_user_data(user_id)
    help_text = (
        "<b>❓ Справка по использованию бота</b>\n\n"
        "1.  <b>Запросы к ИИ</b>: Просто напишите ваш вопрос или задачу в чат.\n"
        "2.  <b>Меню</b>: Используйте кнопки для доступа ко всем функциям:\n"
        "    ▫️ «🤖 Агенты ИИ»: Выберите роль для ИИ.\n"
        "    ▫️ «⚙️ Модели ИИ»: Переключайтесь между моделями.\n"
        "    ▫️ «📊 Лимиты»: Проверьте дневные бесплатные лимиты, баланс гемов и стоимость моделей.\n"
        "    ▫️ «🎁 Бонус»: Получите бонусные генерации за подписку на новостной канал.\n"
        "    ▫️ «💎 Гемы»: Просмотр и покупка пакетов гемов.\n"
        "    ▫️ «❓ Помощь»: Этот раздел справки.\n\n"
        "3.  <b>Основные команды</b> (дублируют функции меню):\n"
        "    ▫️ /start - Перезапуск бота и отображение приветственного сообщения.\n"
        "    ▫️ /menu - Открыть главное меню.\n"
        "    ▫️ /usage - Показать лимиты и баланс гемов.\n"
        "    ▫️ /gems - Открыть магазин гемов.\n"
        "    ▫️ /bonus - Получить бонус за подписку на канал.\n"
        "    ▫️ /help - Показать эту справку."
    )
    current_menu_for_reply = user_data_loc.get('current_menu', BotConstants.MENU_HELP_SUBMENU) # или MENU_MAIN
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(current_menu_for_reply), disable_web_page_preview=True)

async def send_gem_purchase_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, package_key: str):
    user_id = update.effective_user.id
    package_info = CONFIG.GEM_PACKAGES.get(package_key)

    if not package_info:
        logger.error(f"User {user_id} tried to buy non-existent gem package: {package_key}")
        await update.message.reply_text("Ошибка: Выбранный пакет гемов не найден.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return

    title = package_info["title"]
    description = package_info["description"]
    payload = f"gems_{package_key}_user_{user_id}_{int(datetime.now().timestamp())}"
    currency = package_info["currency"]
    price_units = package_info["price_units"]

    prices = [LabeledPrice(label=f"{package_info['gems']} Гемов", amount=price_units)]

    if not CONFIG.PAYMENT_PROVIDER_TOKEN or "YOUR_" in CONFIG.PAYMENT_PROVIDER_TOKEN:
        logger.error("Payment provider token is not configured for sending invoice.")
        await update.message.reply_text("К сожалению, система оплаты временно недоступна.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))
        return
        
    try:
        # Сначала отправляем сообщение о том, что сейчас будет счет
        await update.message.reply_text(
            f"Вы выбрали пакет «{title}». Сейчас я отправлю вам счет для оплаты.",
            reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU) # Остаемся в меню гемов
        )
        await context.bot.send_invoice(
            chat_id=user_id, title=title, description=description, payload=payload,
            provider_token=CONFIG.PAYMENT_PROVIDER_TOKEN, currency=currency, prices=prices
        )
        logger.info(f"Invoice for package '{package_key}' sent to user {user_id}.")
    except Exception as e:
        logger.error(f"Failed to send invoice to user {user_id} for package {package_key}: {e}", exc_info=True)
        await update.message.reply_text("Ошибка при формировании счета. Попробуйте позже.",
                                        reply_markup=generate_menu_keyboard(BotConstants.MENU_GEMS_SUBMENU))

# --- ОБРАБОТЧИК КНОПОК МЕНЮ ---
async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    button_text = update.message.text.strip()
    if not is_menu_button_text(button_text):
        return

    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed menu button: '{button_text}'")
    
    try:
        await update.message.delete()
    except telegram.error.TelegramError as e:
        logger.warning(f"Failed to delete menu button message '{button_text}': {e}")

    user_data_loc = await firestore_service.get_user_data(user_id)
    current_menu_key = user_data_loc.get('current_menu', BotConstants.MENU_MAIN)

    if button_text == "⬅️ Назад":
        parent_key = MENU_STRUCTURE.get(current_menu_key, {}).get("parent", BotConstants.MENU_MAIN)
        await show_menu(update, user_id, parent_key)
        return
    elif button_text == "🏠 Главное меню":
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_item_found = None
    search_order = [current_menu_key] + [key for key in MENU_STRUCTURE if key != current_menu_key]
    
    for menu_key_search_loop in search_order:
        for item in MENU_STRUCTURE.get(menu_key_search_loop, {}).get("items", []):
            if item["text"] == button_text:
                action_item_found = item
                # Важно: current_menu_key используем тот, где реально нашли кнопку, для правильного возврата
                current_menu_key = menu_key_search_loop 
                break
        if action_item_found:
            break
    
    if not action_item_found:
        logger.error(f"Button '{button_text}' was identified as menu button, but no action found. Current menu: '{user_data_loc.get('current_menu', 'N/A')}'")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)
        return

    action_type = action_item_found["action"]
    action_target = action_item_found["target"]

    if action_type == BotConstants.CALLBACK_ACTION_SUBMENU:
        await show_menu(update, user_id, action_target)
    
    elif action_type == BotConstants.CALLBACK_ACTION_SET_AGENT:
        await firestore_service.set_user_data(user_id, {'current_ai_mode': action_target})
        agent_name = AI_MODES.get(action_target, {}).get('name', 'N/A')
        response_text = f"🤖 Агент ИИ изменен на: <b>{agent_name}</b>."
        reply_menu_after_action = current_menu_key # Остаемся в меню выбора агентов
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_action))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_action})

    elif action_type == BotConstants.CALLBACK_ACTION_SET_MODEL:
        model_info = AVAILABLE_TEXT_MODELS.get(action_target, {})
        update_payload = {
            'selected_model_id': model_info.get("id"), 
            'selected_api_type': model_info.get("api_type")
        }
        if action_target in ["custom_api_grok_3", "custom_api_gpt_4o_mini"] and \
           user_data_loc.get('current_ai_mode') == "gemini_pro_custom_mode":
            update_payload['current_ai_mode'] = CONFIG.DEFAULT_AI_MODE_KEY
            logger.info(f"User {user_id} selected model {action_target}, AI mode reset from gemini_pro_custom_mode to default.")
        
        await firestore_service.set_user_data(user_id, update_payload)
        user_data_loc.update(update_payload) 
        
        bot_data_cache = await firestore_service.get_bot_data()
        today_string_val = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        user_model_counts = bot_data_cache.get(BotConstants.FS_ALL_USER_DAILY_COUNTS_KEY, {}).get(str(user_id), {})
        model_daily_usage = user_model_counts.get(action_target, {'date': '', 'count': 0})
        current_usage_string = str(model_daily_usage['count']) if model_daily_usage.get('date') == today_string_val else "0"
        
        # Для отображения лимита после смены модели, используем get_daily_usage_for_model
        current_free_usage_for_selected = await get_daily_usage_for_model(user_id, action_target, bot_data_cache)
        free_daily_limit_for_selected = model_info.get('free_daily_limit',0)
        gem_cost_for_selected = model_info.get('gem_cost',0.0)

        response_text = (f"⚙️ Модель ИИ изменена на: <b>{model_info.get('name', 'N/A')}</b>.\n"
                         f"Бесплатно сегодня: {current_free_usage_for_selected}/{free_daily_limit_for_selected}.\n"
                         f"Стоимость: {gem_cost_for_selected:.1f} гемов.")
        
        reply_menu_after_action = current_menu_key # Остаемся в меню выбора моделей
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML, reply_markup=generate_menu_keyboard(reply_menu_after_action))
        await firestore_service.set_user_data(user_id, {'current_menu': reply_menu_after_action})

    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_LIMITS:
        await show_limits(update, user_id) # show_limits покажет свое меню
    elif action_type == BotConstants.CALLBACK_ACTION_CHECK_BONUS:
        await claim_news_bonus_logic(update, user_id) # claim_news_bonus_logic решит куда вернуть
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_GEMS_STORE:
        await show_menu(update, user_id, BotConstants.MENU_GEMS_SUBMENU)
    elif action_type == BotConstants.CALLBACK_ACTION_BUY_GEM_PACKAGE:
        package_key_to_buy = action_target
        await send_gem_purchase_invoice(update, context, package_key_to_buy)
    elif action_type == BotConstants.CALLBACK_ACTION_SHOW_HELP:
        await show_help(update, user_id) # show_help покажет свое меню
    else:
        logger.warning(f"Unknown action type '{action_type}' for button '{button_text}'")
        await show_menu(update, user_id, BotConstants.MENU_MAIN)



# --- >>> НОВЫЙ ОБРАБОТЧИК ФОТО <<< ---
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await firestore_service.get_user_data(user_id)
    current_ai_mode_key = user_data.get('current_ai_mode')
    active_agent_config = AI_MODES.get(current_ai_mode_key)

    if active_agent_config and active_agent_config.get("multimodal_capable"):
        # Предполагаем, что этот агент 'photo_dietitian_analyzer'
        # и он будет использовать свою "forced_model_key"
        model_to_use = active_agent_config.get("forced_model_key", CONFIG.DEFAULT_MODEL_KEY) # Берем модель агента
        model_cfg = AVAILABLE_TEXT_MODELS.get(model_to_use)

        if not model_cfg:
            await update.message.reply_text("Ошибка: Модель для этого агента не найдена.")
            return
            
        # Проверяем возможность использования (бесплатно или за гемы)
        # bot_data_cache нужен для get_daily_usage_for_model внутри check_and_log_request_attempt
        bot_data_cache = await firestore_service.get_bot_data()
        can_proceed, check_message, usage_type, gem_cost = await check_and_log_request_attempt(
            user_id, model_to_use, user_data, bot_data_cache
        )

        if not can_proceed:
            await update.message.reply_text(check_message, parse_mode=ParseMode.HTML)
            return
        
        # Если можем продолжить (есть лимит или гемы)
        # Не списываем гемы/лимиты сразу, это произойдет после ответа от ИИ в handle_text
        # Сохраняем информацию о фото и ставим состояние ожидания веса
        
        photo_file_id = update.message.photo[-1].file_id # Берем фото лучшего качества
        context.user_data['dietitian_pending_photo_id'] = photo_file_id
        context.user_data['dietitian_model_to_use'] = model_to_use # Сохраняем модель для использования
        context.user_data['dietitian_usage_type'] = usage_type     # Тип использования (free, bonus, gem)
        context.user_data['dietitian_gem_cost'] = gem_cost         # Стоимость в гемах, если это gem usage
        
        context.user_data['dietitian_state'] = 'awaiting_weight'
        
        logger.info(f"User {user_id} (agent {current_ai_mode_key}) sent photo {photo_file_id}. Awaiting weight. Usage check passed ({usage_type}).")
        
        # Промпт для запроса веса из системного промпта агента (часть после "Пример твоего ответа:")
        # Это немного упрощенно, лучше иметь отдельное поле в конфиге агента для этого промпта
        await update.message.reply_text(
            "Отличное фото! Чтобы я мог точно рассчитать КБЖУ, пожалуйста, укажите примерный вес этой порции в граммах."
        )
    else:
        # Если активен другой агент или это обычное фото
        # Можно просто проигнорировать или ответить, что фото принимаются только в режиме диетолога
        if update.message: # Проверяем, что update.message существует
             await update.message.reply_text(
                "Чтобы анализировать фото еды, пожалуйста, выберите агента '🥑 Диетолог (анализ фото)' в меню '🤖 Агенты ИИ'."
            )

# Модифицируем начало функции handle_text
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return
        
    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()
    user_data_cache = await firestore_service.get_user_data(user_id)
    current_ai_mode_key = user_data_cache.get('current_ai_mode', CONFIG.DEFAULT_AI_MODE_KEY)
    active_agent_config = AI_MODES.get(current_ai_mode_key)

    # --- >>> ИСПРАВЛЕННАЯ ЛОГИКА для диетолога с фото <<< ---
    if active_agent_config and \
       active_agent_config.get("multimodal_capable") and \
       context.user_data.get('dietitian_state') == 'awaiting_weight' and \
       'dietitian_pending_photo_id' in context.user_data:

        photo_file_id = context.user_data['dietitian_pending_photo_id']
        # Используем модель, принудительно заданную для агента
        model_to_use = active_agent_config.get("forced_model_key")
        
        if not model_to_use or model_to_use not in AVAILABLE_TEXT_MODELS:
            logger.error(f"Dietitian agent '{current_ai_mode_key}' has invalid or missing 'forced_model_key': {model_to_use}")
            await update.message.reply_text("Ошибка конфигурации модели для агента-диетолога. Сообщите администратору.")
            # Очистка состояния
            context.user_data.pop('dietitian_state', None)
            context.user_data.pop('dietitian_pending_photo_id', None)
            context.user_data.pop('dietitian_model_to_use', None) # На случай если оно там было
            context.user_data.pop('dietitian_usage_type', None)
            context.user_data.pop('dietitian_gem_cost', None)
            return

        # ПРОВЕРКА ЛИМИТОВ И ГЕМОВ ДЛЯ ПРИНУДИТЕЛЬНОЙ МОДЕЛИ (повторяем из photo_handler, но это важно)
        # так как с момента отправки фото до отправки веса мог пройти день или баланс измениться
        bot_data_cache = await firestore_service.get_bot_data()
        can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
            user_id, model_to_use, user_data_cache, bot_data_cache
        )

        if not can_proceed:
            await update.message.reply_text(limit_or_gem_message, parse_mode=ParseMode.HTML)
            # Состояние не сбрасываем, чтобы пользователь мог пополнить гемы и попробовать снова с тем же фото
            return
        
        logger.info(f"User {user_id} (agent {current_ai_mode_key}) provided weight: '{user_message_text}' for photo {photo_file_id}. Model: {model_to_use}. Usage: {usage_type}")
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        ai_service = get_ai_service(model_to_use)
        if not ai_service:
            logger.critical(f"Could not get AI service for dietitian model key '{model_to_use}'")
            await update.message.reply_text("Критическая ошибка при выборе AI модели для диетолога.")
            return

        # ---- TODO: Реализация отправки фото и текста в AI ----
        # Эта часть по-прежнему требует вашей реализации или уточнения формата API gen-api.ru
        photo_file = await context.bot.get_file(photo_file_id)
        # photo_url = photo_file.file_path # Это не прямой URL, а путь для скачивания с токеном
        # Для передачи в gen-api.ru нужен либо прямой публичный URL, либо base64
        # Пример, если бы вы загрузили фото на хостинг и получили URL:
        # image_data_for_api = {"type": "url", "value": "ПУБЛИЧНЫЙ_URL_ИЗОБРАЖЕНИЯ"}
        # Или, если передаете base64 (формат JSON для gen-api.ru нужно уточнить!):
        # file_bytes = await photo_file.download_as_bytearray()
        # import base64
        # photo_base64 = base64.b64encode(bytes(file_bytes)).decode('utf-8')
        # image_data_for_api = {"type": "base64", "value": photo_base64, "mime_type": "image/jpeg"}

        user_prompt_for_multimodal = f"Вес порции: {user_message_text}. Проанализируй фото и рассчитай КБЖУ."
        system_prompt_for_dietitian = active_agent_config["prompt"]
        
        ai_response_text = "ЗАГЛУШКА: Мультимодальный запрос еще не реализован до конца."
        try:
            # Замените эту заглушку на реальный вызов, когда будете готовы:
            # ai_response_text = await ai_service.generate_response(
            #     system_prompt=system_prompt_for_dietitian, 
            #     user_prompt=user_prompt_for_multimodal,
            #     image_data=image_data_for_api # <--- передаем данные изображения
            # )
            logger.warning(f"User {user_id} dietitian multimodal call STUBBED. Photo: {photo_file_id}, Weight: {user_message_text}")
            ai_response_text = (f"Получил фото ID: {photo_file_id} и вес: {user_message_text}. "
                                f"Модель: {model_to_use}. Тип: {usage_type}. "
                                "Расчет КБЖУ будет здесь, когда мультимодальность будет полностью интегрирована с вашим API.")

        except Exception as e:
            logger.error(f"Error during dietitian multimodal AI call for user {user_id}: {e}", exc_info=True)
            ai_response_text = "Произошла ошибка при обработке вашего запроса с изображением."
        
        await increment_request_count(user_id, model_to_use, usage_type, gem_cost_for_request)
        
        final_reply_text, _ = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_GEMS_SUBMENU) # Возвращаем в меню гемов или агентов
        await update.message.reply_text(final_reply_text, reply_markup=generate_menu_keyboard(current_menu))
        
        context.user_data.pop('dietitian_state', None)
        context.user_data.pop('dietitian_pending_photo_id', None)
        context.user_data.pop('dietitian_model_to_use', None)
        context.user_data.pop('dietitian_usage_type', None)
        context.user_data.pop('dietitian_gem_cost', None)
        return 
    
    # --- КОНЕЦ ИСПРАВЛЕННОЙ ЛОГИКИ для диетолога с фото ---

    # Обычная обработка текста для других агентов или текстовых запросов к диетологу (без фото)
    # или если агент диетолога не в состоянии ожидания веса.
    
    final_model_key_for_request = ""
    if active_agent_config and active_agent_config.get("forced_model_key"):
        final_model_key_for_request = active_agent_config.get("forced_model_key")
        logger.info(f"Agent '{current_ai_mode_key}' forcing model to '{final_model_key_for_request}' for text request.")
    else:
        final_model_key_for_request = await get_current_model_key(user_id, user_data_cache)

    # Проверка лимитов/гемов для выбранной (или принудительной) модели
    bot_data_cache_for_check = await firestore_service.get_bot_data()
    can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
        user_id, final_model_key_for_request, user_data_cache, bot_data_cache_for_check
    )
        
    if not can_proceed:
        await update.message.reply_text(
            limit_or_gem_message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
            disable_web_page_preview=True
        )
        return

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Ваш запрос слишком короткий.", reply_markup=generate_menu_keyboard(current_menu))
        return

    logger.info(f"User {user_id} (agent: {current_ai_mode_key}, model: {final_model_key_for_request}) sent AI request: '{user_message_text[:100]}...'")

    ai_service = get_ai_service(final_model_key_for_request)
    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{final_model_key_for_request}'.")
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Критическая ошибка при выборе AI модели.", reply_markup=generate_menu_keyboard(current_menu))
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Для текстовых запросов к диетологу (без фото) используется его же промпт
    system_prompt_to_use = active_agent_config["prompt"] if active_agent_config else AI_MODES[CONFIG.DEFAULT_AI_MODE_KEY]["prompt"]
    
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ."
    try:
        ai_response_text = await ai_service.generate_response(system_prompt_to_use, user_message_text)
    except Exception as e:
        model_name_for_error = AVAILABLE_TEXT_MODELS.get(final_model_key_for_request, {}).get('name', final_model_key_for_request)
        logger.error(f"Unhandled exception in AI service for model {model_name_for_error}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса моделью {model_name_for_error}."
    
    await increment_request_count(user_id, final_model_key_for_request, usage_type, gem_cost_for_request)

    final_reply_text, was_truncated = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"AI response for user {user_id} was truncated.")
    
    current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(current_menu), 
        disable_web_page_preview=True
    )
    logger.info(f"Successfully sent AI response (model: {final_model_key_for_request}, usage: {usage_type}) to user {user_id}.")
    else:
        current_model_key = await get_current_model_key(user_id, user_data_cache) # Глобальная модель

    # ... (остальной код функции handle_text: проверка лимитов, вызов ИИ, отправка ответа)
    # Важно: check_and_log_request_attempt и increment_request_count будут использовать current_model_key
    # (который может быть принудительно установлен агентом диетолога)

    bot_data_cache_for_check = await firestore_service.get_bot_data()
    can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
        user_id, current_model_key, user_data_cache, bot_data_cache_for_check
    )



# --- ОБРАБОТЧИК ТЕКСТА (ЗАПРОСЫ К AI) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or is_menu_button_text(update.message.text.strip()):
        return
        
    user_id = update.effective_user.id
    user_message_text = update.message.text.strip()

    if len(user_message_text) < CONFIG.MIN_AI_REQUEST_LENGTH:
        user_data_cache = await firestore_service.get_user_data(user_id)
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Ваш запрос слишком короткий.", reply_markup=generate_menu_keyboard(current_menu))
        return

    logger.info(f"User {user_id} sent AI request: '{user_message_text[:100]}...'")
    
    user_data_cache = await firestore_service.get_user_data(user_id) 
    bot_data_cache_for_check = await firestore_service.get_bot_data() 
    current_model_key = await get_current_model_key(user_id, user_data_cache)
    
    can_proceed, limit_or_gem_message, usage_type, gem_cost_for_request = await check_and_log_request_attempt(
        user_id, current_model_key, user_data_cache, bot_data_cache_for_check
    )
        
    if not can_proceed:
        await update.message.reply_text(
            limit_or_gem_message, 
            parse_mode=ParseMode.HTML, 
            reply_markup=generate_menu_keyboard(user_data_cache.get('current_menu', BotConstants.MENU_MAIN)), 
            disable_web_page_preview=True
        )
        return

    # current_model_key мог измениться, если check_and_log_request_attempt его сбросил (хотя при can_proceed=True это маловероятно)
    # Но user_data_cache мог измениться (например, бонусные попытки), поэтому лучше перечитать или обновить current_model_key
    current_model_key = await get_current_model_key(user_id, await firestore_service.get_user_data(user_id))
    ai_service = get_ai_service(current_model_key)

    if not ai_service:
        logger.critical(f"Could not get AI service for model key '{current_model_key}' after successful check.")
        current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN)
        await update.message.reply_text("Критическая ошибка при выборе AI модели.", reply_markup=generate_menu_keyboard(current_menu))
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    mode_details = await get_current_mode_details(user_id, user_data_cache) # user_data_cache все еще актуален для режима
    system_prompt = mode_details["prompt"]
    
    ai_response_text = "К сожалению, не удалось получить ответ от ИИ."
    try:
        ai_response_text = await ai_service.generate_response(system_prompt, user_message_text)
    except Exception as e:
        logger.error(f"Unhandled exception in AI service for model {current_model_key}: {e}", exc_info=True)
        ai_response_text = f"Произошла внутренняя ошибка при обработке вашего запроса моделью {ai_service.model_config.get('name', current_model_key)}."
    
    await increment_request_count(user_id, current_model_key, usage_type, gem_cost_for_request)

    final_reply_text, was_truncated = smart_truncate(ai_response_text, CONFIG.MAX_MESSAGE_LENGTH_TELEGRAM)
    if was_truncated:
        logger.info(f"AI response for user {user_id} was truncated.")
    
    current_menu = user_data_cache.get('current_menu', BotConstants.MENU_MAIN) # Для клавиатуры после ответа
    await update.message.reply_text(
        final_reply_text, 
        reply_markup=generate_menu_keyboard(current_menu), 
        disable_web_page_preview=True
    )
    logger.info(f"Successfully sent AI response (model: {current_model_key}, usage: {usage_type}) to user {user_id}.")


# --- ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ---
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload and query.invoice_payload.startswith("gems_"):
        payload_parts = query.invoice_payload.split('_')
        # Ожидаемый формат: "gems_{pack_key_part1}_{pack_key_part2...}_user_{user_id_from_payload}_{timestamp}"
        user_part_index = -1
        for i, part in enumerate(payload_parts):
            if part == "user":
                user_part_index = i
                break
        
        if user_part_index > 1 and len(payload_parts) > user_part_index + 1 : # Убедимся, что есть ключ пакета и user_id
            package_key_from_payload = "_".join(payload_parts[1:user_part_index])
            if package_key_from_payload in CONFIG.GEM_PACKAGES:
                 # Дополнительная проверка: user_id из payload должен совпадать с user_id, совершающим платеж
                try:
                    user_id_in_payload = int(payload_parts[user_part_index + 1])
                    if query.from_user.id == user_id_in_payload:
                        await query.answer(ok=True)
                        logger.info(f"PreCheckoutQuery OK for gems payload: {query.invoice_payload}")
                        return
                    else:
                        logger.error(f"PreCheckoutQuery FAILED. User ID mismatch. Payload User: {user_id_in_payload}, Query User: {query.from_user.id}")
                        await query.answer(ok=False, error_message="Ошибка проверки пользователя.")
                        return
                except (ValueError, IndexError):
                    logger.error(f"PreCheckoutQuery FAILED. Error parsing user_id from payload: {query.invoice_payload}")
                    await query.answer(ok=False, error_message="Ошибка в данных платежа.")
                    return    
            else:
                logger.warning(f"PreCheckoutQuery FAILED. Unknown gem package in payload: {query.invoice_payload}")
                await query.answer(ok=False, error_message="Выбранный пакет гемов больше не доступен.")    
                return
        
    logger.warning(f"PreCheckoutQuery FAILED. Invalid payload format or type: {query.invoice_payload}")
    await query.answer(ok=False, error_message="Неверный или устаревший запрос на оплату.")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    invoice_payload = payment_info.invoice_payload

    logger.info(f"Successful payment received from user {user_id}. Amount: {payment_info.total_amount} {payment_info.currency}. Payload: {invoice_payload}")

    if invoice_payload and invoice_payload.startswith("gems_"):
        try:
            payload_parts = invoice_payload.split('_')
            user_part_index = -1
            for i, part in enumerate(payload_parts):
                if part == "user":
                    user_part_index = i
                    break
            
            if user_part_index == -1 or user_part_index <= 1 or len(payload_parts) <= user_part_index + 1:
                raise ValueError("Invalid payload structure: missing user or package info")

            package_key = "_".join(payload_parts[1:user_part_index])
            user_id_from_payload = int(payload_parts[user_part_index + 1])

            if user_id != user_id_from_payload:
                logger.error(f"Security alert: Payload user ID {user_id_from_payload} != message user ID {user_id} for invoice {invoice_payload}")
                await update.message.reply_text("Произошла ошибка при обработке вашего платежа. Свяжитесь с поддержкой.")
                if CONFIG.ADMIN_ID: await context.bot.send_message(CONFIG.ADMIN_ID, f"⚠️ Ошибка User ID в платеже! Payload: {invoice_payload}, User: {user_id}")
                return

            package_info = CONFIG.GEM_PACKAGES.get(package_key)
            if not package_info:
                logger.error(f"Successful payment for UNKNOWN gem package '{package_key}' by user {user_id}")
                await update.message.reply_text("Ошибка: купленный пакет не найден. Свяжитесь с поддержкой.")
                return

            gems_to_add = float(package_info["gems"])
            current_gem_balance = await get_user_gem_balance(user_id)
            new_gem_balance = current_gem_balance + gems_to_add
            await update_user_gem_balance(user_id, new_gem_balance)

            confirmation_message = (
                f"🎉 Оплата прошла успешно! Вам начислено <b>{gems_to_add:.1f} гемов</b>.\n"
                f"Ваш новый баланс: <b>{new_gem_balance:.1f} гемов</b>.\n\n"
                "Спасибо за покупку!"
            )
            user_data_for_reply_menu = await firestore_service.get_user_data(user_id)
            await update.message.reply_text(
                confirmation_message, parse_mode=ParseMode.HTML, 
                reply_markup=generate_menu_keyboard(user_data_for_reply_menu.get('current_menu', BotConstants.MENU_GEMS_SUBMENU))
            )

            if CONFIG.ADMIN_ID:
                admin_message = (
                    f"💎 Новая покупка гемов!\n"
                    f"Пользователь: {user_id} ({update.effective_user.full_name if update.effective_user else 'N/A'})\n"
                    f"Пакет: {package_info['title']} ({gems_to_add:.1f} гемов)\n"
                    f"Сумма: {payment_info.total_amount / 100.0:.2f} {payment_info.currency}\n" # Для корректного отображения рублей
                    f"Новый баланс: {new_gem_balance:.1f} гемов\n"
                    f"Payload: {invoice_payload}"
                )
                await context.bot.send_message(CONFIG.ADMIN_ID, admin_message)

        except Exception as e:
            logger.error(f"Error processing successful gem payment for user {user_id}, payload {invoice_payload}: {e}", exc_info=True)
            await update.message.reply_text("Произошла ошибка при начислении гемов. Свяжитесь с поддержкой.")
    else:
        logger.warning(f"Successful payment received with unknown payload type from user {user_id}: {invoice_payload}")

# --- ОБРАБОТЧИК ОШИБОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))

    if isinstance(update, Update) and update.effective_chat:
        user_data = {}
        if update.effective_user:
             user_data = await firestore_service.get_user_data(update.effective_user.id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Произошла внутренняя ошибка. Разработчики уже уведомлены.",
                reply_markup=generate_menu_keyboard(user_data.get('current_menu', BotConstants.MENU_MAIN))
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {update.effective_chat.id}: {e}")

    if CONFIG.ADMIN_ID and isinstance(update, Update) and update.effective_user:
        error_details = (
            f"🤖 Ошибка в боте:\n"
            f"Пользователь: ID {update.effective_user.id} (@{update.effective_user.username if update.effective_user.username else 'N/A'})\n"
            f"Сообщение: {update.message.text if update.message and update.message.text else 'N/A (нет текста или не сообщение)'}\n"
            f"Ошибка: {context.error}\n\n"
            f"Traceback:\n```\n{tb_string[:3000]}\n```" 
        )
        try:
            await context.bot.send_message(CONFIG.ADMIN_ID, error_details, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.TelegramError as e_md:
            logger.error(f"Failed to send detailed error report to admin with MarkdownV2: {e_md}. Sending as plain text.")
            try:
                 plain_error_details = f"PLAIN TEXT FALLBACK:\n{error_details.replace('```', '')}"
                 await context.bot.send_message(CONFIG.ADMIN_ID, plain_error_details)
            except Exception as e_plain:
                 logger.error(f"Failed to send plain text detailed error report to admin: {e_plain}")
