from fastapi import APIRouter

from app.api.v1 import ai, auth, catalog, checkout, combos, customers, kiosk, modifiers, orders, restaurant, returns, roles, sales, stores, supplies, sync, users, variants

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(stores.router)
api_router.include_router(catalog.router)
api_router.include_router(variants.router)
api_router.include_router(supplies.router)
api_router.include_router(combos.router)
api_router.include_router(modifiers.router)
api_router.include_router(orders.router)
api_router.include_router(sales.router)
api_router.include_router(returns.router)
api_router.include_router(checkout.router)
api_router.include_router(customers.router)
api_router.include_router(kiosk.router)
api_router.include_router(sync.router)
api_router.include_router(restaurant.router)
api_router.include_router(ai.router)
