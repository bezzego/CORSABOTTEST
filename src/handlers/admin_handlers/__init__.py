from src.handlers.admin_handlers.admin import router as admin_router
from src.handlers.admin_handlers.edit_tariffs import router as tariff_router
from src.handlers.admin_handlers.edit_servers import router as server_router
from src.handlers.admin_handlers.statistics import router as stats_router
from src.handlers.admin_handlers.edit_instructions import router as inst_router
from src.handlers.admin_handlers.edit_users import router as user_router
from src.handlers.admin_handlers.edit_promo import router as promo_router
from src.handlers.admin_handlers.notifications import router as notifications_router

admin_routers = (admin_router, tariff_router, server_router, stats_router, inst_router, user_router, promo_router, notifications_router)
