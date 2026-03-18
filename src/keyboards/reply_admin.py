from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

REPLY_ADMIN_BTN = {
    "back": "◀️ Назад",
    "adm_tariffs": "💰 Управление тарифами",
    "adm_servers": "🖥️ Управление серверами",
    "adm_users": "👥 Управление пользователями",
    "adm_statistics": "📊 Статистика",
    "adm_support": "🆘 Аккаунты поддержки",
    "adm_promo": "🎟️ Промокоды",
    "adm_instructions": "📜 Настройка инструкций",
    "adm_test_sub": "🆓 Настройка тестовой подписки",
    "adm_host_stats": "🖥️📡Состояние сервера",
    "adm_notifications": "🔔 Уведомления",

    "adm_show": "Посмотреть",
    "adm_edit": "Редактирование",
    "adm_add": "Добавление",

    "adm_stats_users": "Пользователи",
    "adm_stats_promo": "Промокоды",
    "adm_stats_keys": "Ключи",

    "adm_inst_iphone": "iPhone",
    "adm_inst_android": "Android",
    "adm_inst_windows": "Windows",
    "adm_inst_macos": "Mac OS",
    "adm_inst_tv": "TV",

    "adm_user_add_days": "Добавление дней к ключу пользователя",
    "adm_user_transfer_user_key": "Перенос ключа пользователя",
    "adm_user_transfer_keys": "Перенос всех ключей",
    "adm_user_ban": "Блокировка пользователей",
    "adm_user_spam": "Рассылка сообщений"


}


def get_reply_admin_btn(key: str) -> str:
    """Возвращает название кнопки по ключу"""
    return REPLY_ADMIN_BTN.get(key, "❓ Неизвестная кнопка")


def get_admin_menu():
    """Создает клавиатуру админа"""
    kb_list = [
        [KeyboardButton(text=get_reply_admin_btn("back"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_tariffs")), KeyboardButton(text=get_reply_admin_btn("adm_servers"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_users")), KeyboardButton(text=get_reply_admin_btn("adm_statistics"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_support")), KeyboardButton(text=get_reply_admin_btn("adm_promo"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_instructions")), KeyboardButton(text=get_reply_admin_btn("adm_test_sub"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_notifications"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_host_stats"))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)


def get_admin_edit_add_menu():
    """Создает клавиатуру админа для управления тарифами/серверами"""
    kb_list = [
        [KeyboardButton(text=get_reply_admin_btn("back"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_edit"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_add"))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)


def get_admin_only_back_menu():
    """Создает клавиатуру админа с кнопкой назад"""
    kb_list = [
        [KeyboardButton(text=get_reply_admin_btn("back"))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)


def get_admin_stats_menu():
    """Создает клавиатуру админа для статистики"""
    kb_list = [
        [KeyboardButton(text=get_reply_admin_btn("back"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_stats_users")),
         KeyboardButton(text=get_reply_admin_btn("adm_stats_promo"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_stats_keys"))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)


def get_admin_user_menu():
    """Создает клавиатуру админа для юзер"""
    kb_list = [
        [KeyboardButton(text=get_reply_admin_btn("back"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_user_spam")),
         KeyboardButton(text=get_reply_admin_btn("adm_user_ban"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_user_transfer_user_key")),
         KeyboardButton(text=get_reply_admin_btn("adm_user_transfer_keys"))
         ],
         [KeyboardButton(text=get_reply_admin_btn("adm_user_add_days"))
    ]
    ]
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)


def get_admin_inst_menu():
    """Создает клавиатуру админа для видео инструкций"""
    kb_list = [
        [KeyboardButton(text=get_reply_admin_btn("back"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_inst_iphone")),
         KeyboardButton(text=get_reply_admin_btn("adm_inst_android"))],
        [KeyboardButton(text=get_reply_admin_btn("adm_inst_macos")),
         KeyboardButton(text=get_reply_admin_btn("adm_inst_windows"))
         ],
        [KeyboardButton(text=get_reply_admin_btn("adm_inst_tv"))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)
