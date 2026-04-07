from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

REPLY_USER_BTN = {
    "get_access": "🚀 Получить доступ",
    "my_keys": "🔑 Мои ключи",
    "video_inst": "🎥 Видео-инструкция",
    "support": "💬 Поддержка",
    "my_id": "🆔 Мой ID",
    "email": "📧 Указать почту",
    "test_sub": "🎁 Активировать бесплатный доступ",
    "bypass": "🛡 Обход белых списков",
    "admin_menu": "💿 Админ-меню"
}


def get_reply_user_btn(key: str) -> str:
    """Возвращает название кнопки по ключу"""
    return REPLY_USER_BTN.get(key, "❓ Неизвестная кнопка")


def get_start_menu(user_orm, admin_role=None):
    """Создает стартовое меню, принимает объект юзера орм и статус админки"""
    kb_list = [
        [KeyboardButton(text=get_reply_user_btn("get_access")), KeyboardButton(text=get_reply_user_btn("my_keys"))],
        [KeyboardButton(text=get_reply_user_btn("video_inst")), KeyboardButton(text=get_reply_user_btn("support"))],
        [KeyboardButton(text=get_reply_user_btn("my_id")), KeyboardButton(text=get_reply_user_btn("email"))],
        [KeyboardButton(text=get_reply_user_btn("bypass"))],
    ]
    if not user_orm.test_sub:
        kb_list.insert(0, [KeyboardButton(text=get_reply_user_btn("test_sub"))])

    if admin_role:
        kb_list.insert(0, [KeyboardButton(text=get_reply_user_btn("admin_menu"))])

    return ReplyKeyboardMarkup(keyboard=kb_list, resize_keyboard=True)
