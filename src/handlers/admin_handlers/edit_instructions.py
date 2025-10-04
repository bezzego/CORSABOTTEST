from aiogram import Router, F
from aiogram.filters.logic import or_f
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from src.database.crud import change_settings_value
from src.keyboards.admin_callback_datas import EditServers, EditInst
from src.keyboards.inline_admin import get_edit_inst_menu
from src.keyboards.reply_admin import get_reply_admin_btn
from src.logs import getLogger
from src.states.admin_states import AdminMenu, AdminInst
from src.utils.utils_async import auth_admin_role, show_device_inst

router = Router(name=__name__)
logger = getLogger(__name__)

"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""


"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(
    or_f(
        F.text == get_reply_admin_btn("adm_inst_iphone"),
        F.text == get_reply_admin_btn("adm_inst_windows"),
        F.text == get_reply_admin_btn("adm_inst_android"),
        F.text == get_reply_admin_btn("adm_inst_macos"),
         ), AdminMenu.inst_menu)
@auth_admin_role
async def cmd_admin_select_device(message: Message, state: FSMContext):
    device_list = {
        "iPhone": "iphone",
        "Windows": "windows",
        "Android": "android",
        "Mac OS": "macos"
    }
    device = device_list.get(message.text)
    await message.answer(
        text=f"Выбранный девайс: <b>{message.text}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_edit_inst_menu(device))


"""───────────────────────────────────────────── Callbacks ─────────────────────────────────────────────"""


@router.callback_query(EditInst.filter(F.action == "show"))
async def clb_show_device_inst(callback: CallbackQuery, callback_data: EditServers):
    await callback.answer()
    await show_device_inst(callback.message, callback_data)


@router.callback_query(EditInst.filter(F.action == "change_video"))
async def clb_change_device_video(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Отправьте новое видео для инструкции  ⬇️")
    await state.set_state(AdminInst.change_video)
    await state.update_data(callback_data=callback_data)


@router.callback_query(EditInst.filter(F.action == "change_link"))
async def clb_change_device_link(callback: CallbackQuery, callback_data: EditServers, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Отправьте новую ссылку для инструкции  ⬇️")
    await state.set_state(AdminInst.change_link)
    await state.update_data(callback_data=callback_data)


"""───────────────────────────────────────────── Edit video ─────────────────────────────────────────────"""


@router.message(F.video, AdminInst.change_video)
async def get_text_change_video(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        kwargs = {f"{callback_data.device}_video": message.video.file_id}
        await change_settings_value(**kwargs)
        await message.answer(
            text=f"Видео было успешно изменено!",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminMenu.inst_menu)
        await show_device_inst(message, callback_data)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()

"""───────────────────────────────────────────── Edit link ─────────────────────────────────────────────"""


@router.message(AdminInst.change_link)
async def get_text_change_link(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        kwargs = {f"{callback_data.device}_url": message.text}
        await change_settings_value(**kwargs)
        await message.answer(
            text=f"Ссылка была успешно изменена!",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminMenu.inst_menu)
        await show_device_inst(message, callback_data)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()
