# В начало файла handlers.py
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes
from datetime import datetime, timezone

# Импортируем всё необходимое из главного файла
from main import (
    firestore_service,
    CONFIG,
    BotConstants,
    AVAILABLE_TEXT_MODELS,
    AI_MODES,
    MENU_STRUCTURE,
    auto_delete_message_decorator,
    get_current_model_key,
    get_current_mode_details,
    get_user_actual_limit_for_model,
    show_limits,
    claim_news_bonus_logic,
    show_subscription,
    show_help,
    is_menu_button_text,
    generate_menu_keyboard,
    _store_and_try_delete_message, # Если используется напрямую, хотя он внутри декоратора
    check_and_log_request_attempt,
    get_ai_service,
    smart_truncate,
    increment_request_count,
    is_user_profi_subscriber,
    logger # Важно импортировать логгер
)

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
