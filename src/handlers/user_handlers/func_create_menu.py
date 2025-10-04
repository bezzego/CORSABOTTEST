from typing import Optional

from aiogram.enums import ParseMode
from aiogram.types import Message
from src.database.crud import get_tariffs
from src.keyboards.inline_user import get_tariffs_buttons
from src.keyboards.reply_user import get_start_menu


async def create_menu_tariffs(message: Message, key_id=None):
    tariffs = await get_tariffs()
    if not tariffs:
        await message.answer(
            text="На данный момент нету доступных тарифов, попробуйте позже.",
            parse_mode=ParseMode.HTML)
        return

    kb, tariffs_text = get_tariffs_buttons(tariffs, key_id)
    text = "💸 Выберите желаемый тариф\n\n" + "\n".join(tariffs_text) + "\n\nВыберите тариф: ⬇️"
    await message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb)


async def create_start_menu(message: Message, user, admin_role: Optional[bool] = None):
    if admin_role:
        await message.answer(
            text="Вы успешно авторизовались как администратор, воспользуйтесь клавиатурой для работы с админ-меню. ⬇️",
            parse_mode=ParseMode.HTML,
            reply_markup=get_start_menu(user, admin_role))
        return

    await message.answer(
        text="Добро пожаловать, для того чтобы начать взаимодействие с ботом, воспользуйтесь клавиатурой. ⬇️",
        parse_mode=ParseMode.HTML,
        reply_markup=get_start_menu(user))
