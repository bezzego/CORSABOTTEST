import re
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from src.database.crud import get_text_settings, get_user
from src.database.crud.keys import get_user_keys, get_user_active_keys
from src.database.crud.servers import get_bypass_servers
from src.database.crud.users import update_user_email
from src.handlers.user_handlers.func_create_menu import create_menu_tariffs, create_start_menu
from src.keyboards.inline_user import get_select_device_buttons, get_inline_markup_with_url, \
    edit_inline_keyboard_select_device, get_inline_markup_my_keys
from src.keyboards.user_callback_datas import VideoInstruction, TestSub, BypassKey
from src.keyboards.reply_user import get_reply_user_btn
from src.services.keys_manager import create_key, create_bypass_key
from src.states.user_states import TestSubState, EmailState, BypassKeyState
from src.utils.utils_async import auth_user_role, update_inline_reply_markup, check_have_servers, show_device_inst
from src.logs import getLogger

router = Router(name=__name__)
logger = getLogger(__name__)


"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(CommandStart())
@auth_user_role
async def cmd_start(message: Message, user, admin_role: Optional[bool] = None):
    await create_start_menu(message, user, admin_role)


@router.message(F.text == get_reply_user_btn("my_id"))
@auth_user_role
async def cmd_my_id(message: Message):
    await message.answer(
        text=f"Ваш ID в Telegram: <code>{message.from_user.id}</code>",
        parse_mode=ParseMode.HTML)


@router.message(F.text == get_reply_user_btn("support"))
@auth_user_role
async def cmd_support(message: Message):
    text_settings = await get_text_settings()
    if len(text_settings.faq_list) < 1:
        await message.answer(
            text="В настоящий момент нету контактов для обратной связи, попробуйте позже",
            parse_mode=ParseMode.HTML)
        return

    faq_list = ", ".join(text_settings.faq_list)
    await message.answer(
        text=f"Для обратной связи обратитесь к одному из менеджеров:\n{faq_list}",
        parse_mode=ParseMode.HTML)


@router.message(F.text == get_reply_user_btn("video_inst"))
@auth_user_role
async def cmd_video_inst(message: Message):
    await message.answer(
        text="Выберите тип вашего устройства:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_select_device_buttons(VideoInstruction))


@router.message(F.text == get_reply_user_btn("my_keys"))
@auth_user_role
async def cmd_my_keys(message: Message):
    keys = await get_user_keys(message.from_user.id)
    logger.debug(f"cmd_my_keys: {keys}")
    if not keys:
        await message.answer(
            text=f"У вас нету активных ключей, нажмите на <b>{get_reply_user_btn('get_access')}</b>",
            parse_mode=ParseMode.HTML)
        return

    await message.answer(
        text="<b>Ваши ключи:</b>\n\nВоспользуйтесь кнопками для взаимодействия с определенными ключами ⬇️",
        parse_mode=ParseMode.HTML,
        reply_markup=await get_inline_markup_my_keys(keys))


@router.message(F.text == get_reply_user_btn("email"))
@auth_user_role
async def cmd_email(message: Message, state: FSMContext):
    user = await get_user(message.from_user)
    if user and user.email:
        await message.answer(
            text=f"Ваша текущая почта: <code>{user.email}</code>\n\nОтправьте новый адрес, чтобы изменить, или /cancel для отмены.",
            parse_mode=ParseMode.HTML)
    else:
        await message.answer("Отправьте ваш email адрес ⬇️\n\nДля отмены отправьте /cancel")
    await state.set_state(EmailState.waiting_for_email)


@router.message(EmailState.waiting_for_email, F.text == "/cancel")
async def cmd_email_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ввод почты отменён.")


@router.message(EmailState.waiting_for_email)
async def process_email_input(message: Message, state: FSMContext):
    email = message.text.strip() if message.text else ""
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        await message.answer("Некорректный email. Попробуйте ещё раз или отправьте /cancel для отмены.")
        return

    await update_user_email(message.from_user.id, email)
    await state.clear()
    await message.answer(
        text=f"Почта <code>{email}</code> успешно сохранена!",
        parse_mode=ParseMode.HTML)


@router.message(F.text == get_reply_user_btn("get_access"))
@auth_user_role
@check_have_servers
async def cmd_get_access(message: Message):
    await create_menu_tariffs(message)


@router.message(F.text == get_reply_user_btn("test_sub"))
@auth_user_role
@check_have_servers
async def cmd_test_sub(message: Message, user, state: FSMContext, admin_role: Optional[bool] = None):
    logger.debug(f"cmd_test_sub: {user}")
    current_state = await state.get_state()
    if current_state and current_state == TestSubState.create_key:
        return

    if user.test_sub:
        await create_start_menu(message, user, admin_role)

    elif not user.test_sub:
        await message.answer(
            text="Выберите тип Вашего устройства, для которого будет использован ключ",
            parse_mode=ParseMode.HTML,
            reply_markup=get_select_device_buttons(TestSub))

        await state.set_state(TestSubState.select_device)
        await state.update_data(user_obj=user)

"""───────────────────────────────────────────── Bypass Key ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_user_btn("bypass"))
@auth_user_role
async def cmd_bypass_key(message: Message, state: FSMContext):
    bypass_servers = await get_bypass_servers()
    if not bypass_servers:
        await message.answer("Функция временно недоступна.")
        return

    active_keys = await get_user_active_keys(message.from_user.id)
    if not active_keys:
        await message.answer(
            text="Эта функция доступна только пользователям с активным ключом.",
            parse_mode=ParseMode.HTML)
        return

    finish_date = max(k.finish for k in active_keys)
    await message.answer(
        text="Выберите тип устройства для ключа обхода белых списков:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_select_device_buttons(BypassKey))

    await state.set_state(BypassKeyState.select_device)
    await state.update_data(finish_date=finish_date)


@router.callback_query(BypassKey.filter(F.action == "select_device"), BypassKeyState.select_device)
async def clb_bypass_key_select_device(callback: CallbackQuery, callback_data: BypassKey, state: FSMContext):
    await callback.answer()
    await state.set_state(BypassKeyState.create_key)

    state_data = await state.get_data()
    finish_date = state_data["finish_date"]

    await update_inline_reply_markup(callback, edit_inline_keyboard_select_device)

    await create_bypass_key(
        bot=callback.bot,
        user_id=callback.from_user.id,
        finish_date=finish_date,
        device=callback_data.device)

    await state.clear()


"""───────────────────────────────────────────── Callbacks Video Inst ─────────────────────────────────────────────"""


@router.callback_query(VideoInstruction.filter(F.action == "select_device"))
async def clb_video_inst(callback: CallbackQuery, callback_data: VideoInstruction):
    await callback.answer()
    await show_device_inst(callback.message, callback_data)


"""───────────────────────────────────────────── Callbacks Test_sub ─────────────────────────────────────────────"""


@router.callback_query(TestSub.filter(F.action == "select_device"), TestSubState.select_device)
async def clb_test_sub_select_device(callback: CallbackQuery, callback_data: TestSub, state: FSMContext):
    await callback.answer()
    await state.set_state(TestSubState.create_key)

    state_data = await state.get_data()
    user = state_data.get("user_obj")
    logger.debug(f"clb_test_sub_select_device: user: {user} | data: {callback_data}")

    await update_inline_reply_markup(callback, edit_inline_keyboard_select_device)
    text_settings = await get_text_settings()

    await create_key(
        bot=callback.bot,
        user_id=callback.from_user.id,
        finish_date=datetime.now() + timedelta(hours=text_settings.test_hours),
        tariff_id=None,
        device=callback_data.device,
        is_test=True)

    await state.clear()
