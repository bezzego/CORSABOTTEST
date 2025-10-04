from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from src.database.crud import get_user, get_text_settings, update_faq_list, update_test_sub
from src.handlers.user_handlers.func_create_menu import create_start_menu
from src.handlers.admin_handlers.notifications import open_notifications_menu
from src.keyboards.reply_admin import get_admin_menu, get_reply_admin_btn, get_admin_edit_add_menu, \
    get_admin_only_back_menu, get_admin_stats_menu, get_admin_inst_menu, get_admin_user_menu
from src.keyboards.reply_user import get_reply_user_btn
from src.logs import getLogger
from src.states.admin_states import AdminMenu
from src.utils.utils import get_host_stats
from src.utils.utils_async import auth_admin_role

router = Router(name=__name__)
logger = getLogger(__name__)

"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""


async def create_admin_menu(message: Message):
    await message.answer(
        text="💿 Админ-меню",
        reply_markup=get_admin_menu())

"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_user_btn("admin_menu"))
@auth_admin_role
async def cmd_admin_menu(message: Message, state: FSMContext):
    await create_admin_menu(message)
    await state.set_state(AdminMenu.main_menu)


@router.message(F.text == get_reply_admin_btn("back"))
@auth_admin_role
async def cmd_admin_back(message: Message, state: FSMContext):
    current_state = await state.get_state()
    logger.debug(f"cmd_admin_back: current_state: {current_state}")

    if current_state == AdminMenu.main_menu or not current_state:
        user = await get_user(message.from_user)
        await create_start_menu(message, user=user, admin_role=True)
        await state.clear()

    else:
        await create_admin_menu(message)
        await state.set_state(AdminMenu.main_menu)


@router.message(F.text == get_reply_admin_btn("adm_host_stats"))
@auth_admin_role
async def cmd_host_stats(message: Message):
    await message.answer(
        text=get_host_stats())


@router.message(F.text == get_reply_admin_btn("adm_tariffs"))
@auth_admin_role
async def cmd_tariffs(message: Message, state: FSMContext):
    await state.set_state(AdminMenu.tariffs_menu)
    await message.answer(
        text="Управление тарифами:",
        reply_markup=get_admin_edit_add_menu())


@router.message(F.text == get_reply_admin_btn("adm_servers"))
@auth_admin_role
async def cmd_servers(message: Message, state: FSMContext):
    await state.set_state(AdminMenu.servers_menu)
    await message.answer(
        text="Управление серверами:",
        reply_markup=get_admin_edit_add_menu())


@router.message(F.text == get_reply_admin_btn("adm_support"))
@auth_admin_role
async def cmd_support(message: Message, state: FSMContext):
    support_list = await get_text_settings()
    await message.answer(
        text=f"Список аккаунтов поддержки сейчас: {','.join(support_list.faq_list)}\n\nУкажите новый список аккаунтов поддержки через запятую  ⬇️",
        reply_markup=get_admin_only_back_menu())
    await state.set_state(AdminMenu.support_menu)


@router.message(F.text == get_reply_admin_btn("adm_test_sub"))
@auth_admin_role
async def cmd_test_sub(message: Message, state: FSMContext):
    test_sub_hours = await get_text_settings()
    await message.answer(
        text=f"Введите новое кол-во часов тестовой подписки  ⬇️\nТекущее время: {test_sub_hours.test_hours} часов.",
        reply_markup=get_admin_only_back_menu())
    await state.set_state(AdminMenu.test_sub_menu)


@router.message(F.text == get_reply_admin_btn("adm_statistics"))
@auth_admin_role
async def cmd_stats(message: Message, state: FSMContext):
    await message.answer(
        text="Выберите интересующую вас статистику  ⬇️",
        reply_markup=get_admin_stats_menu())
    await state.set_state(AdminMenu.statistics_menu)


@router.message(F.text == get_reply_admin_btn("adm_users"))
@auth_admin_role
async def cmd_edit_users(message: Message, state: FSMContext):
    await message.answer(
        text="Выберите интересующую вас панель  ⬇️",
        reply_markup=get_admin_user_menu())
    await state.set_state(AdminMenu.users_menu)


@router.message(F.text == get_reply_admin_btn("adm_instructions"))
@auth_admin_role
async def cmd_instructions(message: Message, state: FSMContext):
    await message.answer(
        text="Выберите интересующую вас девайс  ⬇️",
        reply_markup=get_admin_inst_menu())
    await state.set_state(AdminMenu.inst_menu)



@router.message(F.text == get_reply_admin_btn("adm_notifications"))
@auth_admin_role
async def cmd_notifications(message: Message, state: FSMContext):
    await open_notifications_menu(message, state)

@router.message(F.text == get_reply_admin_btn("adm_promo"))
@auth_admin_role
async def cmd_edit_promo(message: Message, state: FSMContext):
    await state.set_state(AdminMenu.tariffs_menu)
    await message.answer(
        text="Управление промокодами:",
        reply_markup=get_admin_edit_add_menu())

    await state.set_state(AdminMenu.promo_menu)

"""───────────────────────────────────────────── Faq Update ─────────────────────────────────────────────"""


@router.message(AdminMenu.support_menu)
async def get_text_update_faq_list(message: Message, state: FSMContext):
    try:
        new_list = message.text.split(",")
        await update_faq_list(new_list)
        await message.answer("Успешно! Список аккаунтов поддержки был обновлен.")
        await state.clear()

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)


"""───────────────────────────────────────────── Test Sub Update ─────────────────────────────────────────────"""


@router.message(AdminMenu.test_sub_menu)
async def get_text_update_test_sub(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return
        await update_test_sub(int(message.text))
        await message.answer(
            text=f"Успешно! Новое время тестовой подписки: <b>{message.text}</b> часов.",
            parse_mode=ParseMode.HTML)
        await state.clear()

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)


