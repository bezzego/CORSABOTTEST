from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, BufferedInputFile
from src.keyboards.reply_admin import get_reply_admin_btn
from src.logs import getLogger
from src.states.admin_states import AdminMenu
from src.utils.utils_async import export_users_to_excel, export_promos_to_excel, export_keys_to_excel

router = Router(name=__name__)
logger = getLogger(__name__)

"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""

"""───────────────────────────────────────────── Callbacks ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_admin_btn("adm_stats_users"), AdminMenu.statistics_menu)
async def cmd_stats_users(message: Message, state: FSMContext):
    await message.answer(
        text="Идет выгрузка пользователь, подождите")

    users_xlsx = await export_users_to_excel()
    users_xlsx.seek(0)
    document = BufferedInputFile(file=users_xlsx.read(), filename="users.xlsx")
    await message.answer_document(
        document=document,
        caption="База пользователей")


@router.message(F.text == get_reply_admin_btn("adm_stats_promo"), AdminMenu.statistics_menu)
async def cmd_stats_promos(message: Message, state: FSMContext):
    await message.answer(
        text="Идет выгрузка промокодов, подождите")

    promos_xlsx = await export_promos_to_excel()
    promos_xlsx.seek(0)
    document = BufferedInputFile(file=promos_xlsx.read(), filename="promos.xlsx")
    await message.answer_document(
        document=document,
        caption="База промокодов")


@router.message(F.text == get_reply_admin_btn("adm_stats_keys"), AdminMenu.statistics_menu)
async def cmd_stats_keys(message: Message, state: FSMContext):
    await message.answer(
        text="Идет выгрузка ключей, подождите")

    keys_xlsx = await export_keys_to_excel()
    keys_xlsx.seek(0)
    document = BufferedInputFile(file=keys_xlsx.read(), filename="keys.xlsx")
    await message.answer_document(
        document=document,
        caption="База ключей")
