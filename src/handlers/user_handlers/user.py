from datetime import datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from src.database.crud import get_text_settings
from src.database.crud.keys import get_user_keys
from src.handlers.user_handlers.func_create_menu import create_menu_tariffs, create_start_menu
from src.keyboards.inline_user import get_select_device_buttons, get_inline_markup_with_url, \
    edit_inline_keyboard_select_device, get_inline_markup_my_keys
from src.keyboards.user_callback_datas import VideoInstruction, TestSub
from src.keyboards.reply_user import get_reply_user_btn
from src.services.keys_manager import create_key
from src.states.user_states import TestSubState
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
