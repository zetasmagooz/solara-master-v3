from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.store import Store, StoreConfig
from app.models.user import User

router = APIRouter(prefix="/stores", tags=["stores"])


class StoreCreate(BaseModel):
    name: str
    business_type_id: int | None = None
    currency_id: int | None = None
    country_id: int | None = None
    tax_rate: float = 0


class StoreUpdate(BaseModel):
    tax_rate: float | None = None


class StoreResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    business_type_id: int | None = None
    tax_rate: float
    is_active: bool

    model_config = {"from_attributes": True}


class StoreConfigResponse(BaseModel):
    id: UUID
    store_id: UUID
    sales_without_stock: bool
    tax_included: bool
    kiosk_enabled: bool

    model_config = {"from_attributes": True}


class StoreConfigUpdate(BaseModel):
    sales_without_stock: bool | None = None
    tax_included: bool | None = None


@router.post("/", response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    data: StoreCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    store = Store(owner_id=current_user.id, **data.model_dump())
    db.add(store)
    await db.flush()

    config = StoreConfig(store_id=store.id)
    db.add(config)
    await db.flush()

    return store


@router.get("/", response_model=list[StoreResponse])
async def list_stores(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Store).where(Store.owner_id == current_user.id, Store.is_active.is_(True))
    )
    return result.scalars().all()


@router.get("/{store_id}", response_model=StoreResponse)
async def get_store(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    return store


@router.patch("/{store_id}", response_model=StoreResponse)
async def update_store(
    store_id: UUID,
    data: StoreUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    if store.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(store, key, value)

    await db.flush()
    return store


@router.get("/{store_id}/config", response_model=StoreConfigResponse)
async def get_store_config(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Auto-create default config if it doesn't exist yet
        config = StoreConfig(store_id=store_id)
        db.add(config)
        await db.flush()
    return config


@router.patch("/{store_id}/config", response_model=StoreConfigResponse)
async def update_store_config(
    store_id: UUID,
    data: StoreConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    # Verify store exists and user belongs to it
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    if store.owner_id != current_user.id and current_user.default_store_id != store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    result = await db.execute(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Auto-create config if it doesn't exist yet
        config = StoreConfig(store_id=store_id)
        db.add(config)
        await db.flush()

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(config, key, value)

    await db.flush()
    return config
