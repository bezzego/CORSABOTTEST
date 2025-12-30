import asyncio

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.filters.logic import or_f
from sqlalchemy.util import await_only

from src.database.crud import get_user_by_id_or_username, ban_unban_user
from src.database.crud.keys import get_user_keys, get_key_by_id
from src.database.crud.servers import get_servers
from src.keyboards.admin_callback_datas import EditUserBanned, AddDaysKey, TransferKey, TransferKeyServer, SpamMessages
from src.keyboards.inline_admin import get_edit_ban_menu, get_confirm_buttons, get_keys_buttons, \
    get_transfer_server_buttons, get_spam_menu
from src.keyboards.reply_admin import get_reply_admin_btn
from src.logs import getLogger
from src.services.keys_manager import prolong_key, transfer_key_to_select_server, \
    transfer_all_keys_from_server_to_server
from src.states.admin_states import AdminMenu, AdminUsers
from src.utils.utils_async import auth_admin_role, send_message_safe, broadcast_message

router = Router(name=__name__)
logger = getLogger(__name__)


"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""


"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_admin_btn("adm_user_ban"), StateFilter(AdminMenu.users_menu))
@auth_admin_role
async def cmd_user_ban(message: Message, state: FSMContext):
    await message.answer(
        text="Действие над пользователем:",
        reply_markup=get_edit_ban_menu())


@router.message(F.text == get_reply_admin_btn("adm_user_add_days"), StateFilter(AdminMenu.users_menu))
@auth_admin_role
async def cmd_user_add_days(message: Message, state: FSMContext):
    await message.answer("Введите ID/username пользователя ⬇️")
    await state.set_state(AdminUsers.add_days_select_user)


@router.message(F.text == get_reply_admin_btn("adm_user_transfer_user_key"), StateFilter(AdminMenu.users_menu))
@auth_admin_role
async def cmd_user_transfer_key(message: Message, state: FSMContext):
    await message.answer("Введите ID/username пользователя ⬇️")
    await state.set_state(AdminUsers.transfer_key_select_user)


@router.message(F.text == get_reply_admin_btn("adm_user_transfer_keys"), StateFilter(AdminMenu.users_menu))
@auth_admin_role
async def cmd_transfer_keys(message: Message, state: FSMContext):
    servers = await get_servers()
    await message.answer(
        text="Выберите сервер, с которого будут перенесены ключи:",
        reply_markup=await get_transfer_server_buttons(TransferKeyServer, servers))
    await state.set_state(AdminUsers.transfer_all_keys_select_first)


@router.message(F.text == get_reply_admin_btn("adm_user_spam"), StateFilter(AdminMenu.users_menu))
@auth_admin_role
async def cmd_spam_messages(message: Message, state: FSMContext):
    await message.answer(
        text="Выберите тип интересующей вас рассылки:",
        reply_markup=get_spam_menu())


"""───────────────────────────────────────────── Callbacks ─────────────────────────────────────────────"""


@router.callback_query(or_f(
    EditUserBanned.filter(F.action == "back"), SpamMessages.filter(F.action == "back")))
async def clb_cancel(callback: CallbackQuery, callback_data: EditUserBanned):
    await callback.message.delete()


"""───────────────────────────────────────────── Callbacks Banned ─────────────────────────────────────────────"""


@router.callback_query(or_f(EditUserBanned.filter(F.action == "ban"), EditUserBanned.filter(F.action == "unban")))
async def clb_ban_or_unban_user(callback: CallbackQuery, callback_data: EditUserBanned, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите ID/username пользователя ⬇️")
    await state.set_state(AdminUsers.ban_or_unban)
    await state.update_data(callback_data=callback_data)


@router.message(AdminUsers.ban_or_unban)
async def get_text_ban_or_unban_user(message: Message, state: FSMContext):
    try:
        user = await get_user_by_id_or_username(message.text)
        if not user:
            await message.answer("Ошибка! Пользователь не был найден, попробуйте еще раз.")
            return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        action = callback_data.action
        await message.answer(
            text=f"""
Вы уверены что хотите {'забанить' if action == 'ban' else 'разбанить'} пользователя:

ID: <code>{user.id}</code>
Username: <code>{user.username}</code>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditUserBanned))

        await state.set_state(AdminUsers.ban_or_unban_confirm)
        await state.update_data(user_obj=user)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(or_f(
    EditUserBanned.filter(F.action == "cancel_change"),
    SpamMessages.filter(F.action == "cancel_change")
),
    StateFilter(AdminUsers.ban_or_unban_confirm, AdminUsers.spam_messages_confirm))
async def clb_change_cancel(callback: CallbackQuery, callback_data: EditUserBanned, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Успешно, отмена изменений!")
    await state.clear()
    await state.set_state(AdminMenu.users_menu)


@router.callback_query(EditUserBanned.filter(F.action == "confirm_change"), AdminUsers.ban_or_unban_confirm)
async def clb_ban_or_unban_user_confirm(callback: CallbackQuery, callback_data: EditUserBanned, state: FSMContext):
    state_data = await state.get_data()
    callback_data = state_data["callback_data"]
    user = state_data["user_obj"]
    await ban_unban_user(user, callback_data.action)
    await callback.answer()
    await callback.message.answer(
        text=f"Пользователь был успешно {'забанен' if callback_data.action == 'ban' else 'разбанен'}!",
        parse_mode=ParseMode.HTML)

    await state.set_state(AdminMenu.users_menu)


"""───────────────────────────────────────────── Add Days / Transfer Key ─────────────────────────────────────────────"""


@router.callback_query(or_f(
    AddDaysKey.filter(F.action == "pagination"), TransferKey.filter(F.action == "pagination")
),
    StateFilter(
        AdminUsers.add_days_select_key, AdminUsers.transfer_key_select_user
))
async def clb_paginate_user_keys(callback: CallbackQuery, callback_data: AddDaysKey, state: FSMContext):
    state_data = await state.get_data()
    keys = state_data["keys_obj"]
    current_state = await state.get_state()
    new_markup = None
    if current_state == AdminUsers.add_days_select_user:
        new_markup = await get_keys_buttons(AddDaysKey, keys, callback_data.page)

    elif current_state == AdminUsers.transfer_key_select_user:
        new_markup = await get_keys_buttons(TransferKey, keys, callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.message(StateFilter(AdminUsers.add_days_select_user, AdminUsers.transfer_key_select_user))
async def get_text_add_days_or_transfer_keys(message: Message, state: FSMContext):
    try:
        user = await get_user_by_id_or_username(message.text)
        if not user:
            await message.answer("Ошибка! Пользователь не был найден, попробуйте еще раз.")
            return

        keys = await get_user_keys(user.id)
        if not keys:
            await message.answer("У данного пользователя нету ключей.")
            await state.set_state(AdminMenu.users_menu)
            return
        current_state = await state.get_state()
        if current_state == AdminUsers.add_days_select_user:
            await message.answer(
                text="Выберите ключ, который хотите продлить.",
                reply_markup=await get_keys_buttons(AddDaysKey, keys))
            await state.set_state(AdminUsers.add_days_select_key)
            await state.update_data(keys_obj=keys)

        elif current_state == AdminUsers.transfer_key_select_user:
            await message.answer(
                text="Выберите ключ, который хотите перенести на другой сервер.",
                reply_markup=await get_keys_buttons(TransferKey, keys))
            await state.set_state(AdminUsers.transfer_key_select_key)
            await state.update_data(keys_obj=keys)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(or_f(
    AddDaysKey.filter(F.action == "select"), TransferKey.filter(F.action == "select")
),
    StateFilter(
        AdminUsers.add_days_select_key, AdminUsers.transfer_key_select_key))
async def clb_select_user_key(callback: CallbackQuery, callback_data: AddDaysKey, state: FSMContext):
    current_state = await state.get_state()
    if current_state == AdminUsers.add_days_select_key:
        await callback.answer()
        await callback.message.answer(
            text="Введите количество дней которое хотите добавить к ключу ⬇️")
        await state.set_state(AdminUsers.add_days_send)
        await state.update_data(key_id=callback_data.key_id)

    elif current_state == AdminUsers.transfer_key_select_key:
        servers = await get_servers()
        await callback.answer()
        await callback.message.answer(
            text="Выберите сервер, на который будет перенесен ключ.",
            reply_markup=await get_transfer_server_buttons(TransferKeyServer, servers))
        await state.set_state(AdminUsers.transfer_key_select_server)
        await state.update_data(key_id=callback_data.key_id)

"""───────────────────────────────────────────── Callbacks Add Days ─────────────────────────────────────────────"""


@router.message(AdminUsers.add_days_send)
async def get_text_get_days_count(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        state_data = await state.get_data()
        key = await get_key_by_id(int(state_data["key_id"]))
        await prolong_key(
            bot=message.bot,
            user_id=key.user_id,
            tariff=None,
            key_id=key.id,
            _admin_days=int(message.text))

        await message.answer(
            text="Ключ пользователя был успешно продлен. Пользователь получил уведомление.")
        await state.set_state(AdminMenu.users_menu)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


"""───────────────────────────────────────────── Callbacks Transfer Key ─────────────────────────────────────────────"""


@router.callback_query(TransferKeyServer.filter(F.action == "pagination"), AdminUsers.transfer_key_select_server)
async def clb_paginate_transfer_servers(callback: CallbackQuery, callback_data: TransferKeyServer, state: FSMContext):
    servers = await get_servers()
    new_markup = await get_transfer_server_buttons(TransferKeyServer, servers, page=callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(TransferKeyServer.filter(F.action == "pagination"), AdminUsers.transfer_all_keys_select_first)
async def clb_paginate_transfer_all_keys_first(callback: CallbackQuery, callback_data: TransferKeyServer, state: FSMContext):
    servers = await get_servers()
    new_markup = await get_transfer_server_buttons(TransferKeyServer, servers, page=callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(TransferKeyServer.filter(F.action == "pagination"), AdminUsers.transfer_all_keys_select_second)
async def clb_paginate_transfer_all_keys_second(callback: CallbackQuery, callback_data: TransferKeyServer, state: FSMContext):
    state_data = await state.get_data()
    first_server_id = int(state_data.get("server_id_first", 0))
    servers = await get_servers()
    # Remove the first selected server from the list
    servers = [s for s in servers if s.id != first_server_id]
    new_markup = await get_transfer_server_buttons(TransferKeyServer, servers, page=callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(TransferKeyServer.filter(F.action == "select"), AdminUsers.transfer_key_select_server)
async def clb_select_transfer_servers(callback: CallbackQuery, callback_data: TransferKeyServer, state: FSMContext):
    state_data = await state.get_data()
    key_id = int(state_data["key_id"])
    key = await get_key_by_id(key_id)
    server_id = int(callback_data.server_id)

    await callback.answer()
    if key.server_id == server_id:
        await callback.message.answer(
            text="Ключ уже находится на этом сервере.")
        await state.set_state(AdminMenu.users_menu)
        return

    await transfer_key_to_select_server(callback.bot, key_id, server_id)
    await callback.message.answer(
        text="Ключ успешно перенесен, пользователь был уведомлен.")
    await state.set_state(AdminMenu.users_menu)


"""───────────────────────────────────────────── Callbacks Transfer Key ─────────────────────────────────────────────"""


@router.callback_query(TransferKeyServer.filter(F.action == "select"), AdminUsers.transfer_all_keys_select_first)
async def clb_select_first_server_transfer_all_keys(callback: CallbackQuery, callback_data: TransferKeyServer, state: FSMContext):
    servers = await get_servers()
    # Remove the selected server from the list
    servers = [s for s in servers if s.id != int(callback_data.server_id)]
    await callback.answer()
    await callback.message.answer(
        text="Выберите сервер, на который будут перенесены все ключи:",
        reply_markup=await get_transfer_server_buttons(TransferKeyServer, servers))

    await state.set_state(AdminUsers.transfer_all_keys_select_second)
    await state.update_data(server_id_first=callback_data.server_id)


@router.callback_query(TransferKeyServer.filter(F.action == "select"), AdminUsers.transfer_all_keys_select_second)
async def clb_select_second_server_transfer_all_keys(callback: CallbackQuery, callback_data: TransferKeyServer, state: FSMContext):
    state_data = await state.get_data()
    await callback.answer()
    first_server_id = int(state_data["server_id_first"])
    second_server_id = int(callback_data.server_id)

    await callback.message.answer(
        text="Перенос всех ключей...")
    await state.set_state(AdminMenu.users_menu)

    await transfer_all_keys_from_server_to_server(callback.bot, first_server_id, second_server_id)
    await callback.message.answer(
        text="Все ключи были успешно перенесены, пользователи были уведомлены.")


"""───────────────────────────────────────────── Callbacks Spam ─────────────────────────────────────────────"""


@router.callback_query(SpamMessages.filter(F.action == "user"))
async def clb_spam_messages_user(callback: CallbackQuery, callback_data: SpamMessages, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите ID/username пользователя ⬇️")
    await state.set_state(AdminUsers.spam_messages_user_select)
    await state.update_data(callback_data=callback_data)


@router.message(StateFilter(AdminUsers.spam_messages_user_select))
async def get_text_user_spam(message: Message, state: FSMContext):
    try:
        user = await get_user_by_id_or_username(message.text)
        if not user:
            await message.answer("Ошибка! Пользователь не был найден, попробуйте еще раз.")
            return

        await message.answer("Отправьте сообщение которое будет использоваться для рассылки ⬇️")
        await state.set_state(AdminUsers.spam_messages_get_message)
        await state.update_data(user_obj=user)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(SpamMessages.filter(F.action == "all_users"))
async def clb_spam_messages_all_users(callback: CallbackQuery, callback_data: SpamMessages, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Отправьте сообщение которое будет использоваться для рассылки ⬇️")
    await state.set_state(AdminUsers.spam_messages_get_message)


@router.message(StateFilter(AdminUsers.spam_messages_get_message))
async def get_text_message_spam(message: Message, state: FSMContext):
    try:
        await message.answer(
            text="<b>Превью отправляемого сообщения \n\nПодтвердите рассылку  ⬇️</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(SpamMessages))
        await send_message_safe(message.bot, message.from_user.id, message)

        await state.set_state(AdminUsers.spam_messages_confirm)
        await state.update_data(message_obj=message)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(SpamMessages.filter(F.action == "confirm_change"), AdminUsers.spam_messages_confirm)
async def clb_spam_messages_confirm(callback: CallbackQuery, callback_data: SpamMessages, state: FSMContext):
    state_data = await state.get_data()
    user = state_data.get("user_obj")
    message_obj = state_data["message_obj"]
    await callback.answer()

    asyncio.create_task(broadcast_message(callback.bot, message_obj, callback.from_user.id, user))
    await state.set_state(AdminMenu.users_menu)
