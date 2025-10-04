from src.handlers.user_handlers.tariffs import router as tariff_router
from src.handlers.user_handlers.user import router as user_router
from src.handlers.user_handlers.my_keys import router as my_keys_router

user_routers = (tariff_router, user_router, my_keys_router)
