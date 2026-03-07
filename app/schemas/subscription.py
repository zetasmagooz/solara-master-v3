from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PlanResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    price_monthly: float
    features: dict | None = None
    is_active: bool
    sort_order: int

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    plan_id: UUID
    status: str
    started_at: datetime
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    plan: PlanResponse | None = None

    model_config = {"from_attributes": True}


class ActivatePlanRequest(BaseModel):
    plan_slug: str
