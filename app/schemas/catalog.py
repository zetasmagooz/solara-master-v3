from datetime import date, datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, model_validator

T = TypeVar("T")


# --- Pagination ---
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int


# --- Brands ---
class BrandCreate(BaseModel):
    name: str
    image_url: str | None = None
    is_active: bool = True
    show_in_kiosk: bool = True


class BrandUpdate(BaseModel):
    name: str | None = None
    image_url: str | None = None
    is_active: bool | None = None
    show_in_kiosk: bool | None = None


class BrandResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    image_url: str | None = None
    is_active: bool
    show_in_kiosk: bool = True

    model_config = {"from_attributes": True}


# --- Attribute Definitions ---
class AttributeDefinitionCreate(BaseModel):
    name: str
    data_type: str = "text"
    options: dict | None = None
    is_required: bool = False
    sort_order: int = 0
    applicable_product_types: dict | None = None
    applicable_category_ids: dict | None = None
    generates_variants: bool = False


class AttributeDefinitionUpdate(BaseModel):
    name: str | None = None
    data_type: str | None = None
    options: dict | None = None
    is_required: bool | None = None
    sort_order: int | None = None
    applicable_product_types: dict | None = None
    applicable_category_ids: dict | None = None
    generates_variants: bool | None = None
    is_active: bool | None = None


class AttributeDefinitionResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    data_type: str
    options: dict | None = None
    is_required: bool
    sort_order: int
    applicable_product_types: dict | None = None
    applicable_category_ids: dict | None = None
    generates_variants: bool
    is_active: bool

    model_config = {"from_attributes": True}


# --- Product Attributes ---
class ProductAttributeCreate(BaseModel):
    attribute_definition_id: UUID
    value_text: str | None = None
    value_number: float | None = None
    value_boolean: bool | None = None
    value_date: date | None = None


class ProductAttributeResponse(BaseModel):
    id: UUID
    product_id: UUID
    attribute_definition_id: UUID
    value_text: str | None = None
    value_number: float | None = None
    value_boolean: bool | None = None
    value_date: date | None = None
    definition: AttributeDefinitionResponse | None = None

    model_config = {"from_attributes": True}


# --- Categories ---
class CategoryCreate(BaseModel):
    name: str
    description: str | None = None
    image_url: str | None = None
    brand_id: UUID | None = None
    sort_order: int = 0
    is_active: bool = True
    show_in_kiosk: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    brand_id: UUID | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    show_in_kiosk: bool | None = None


class CategoryResponse(BaseModel):
    id: UUID
    store_id: UUID
    brand_id: UUID | None = None
    name: str
    description: str | None = None
    image_url: str | None = None
    sort_order: int
    is_active: bool
    show_in_kiosk: bool
    created_at: datetime
    brand: BrandResponse | None = None

    model_config = {"from_attributes": True}


# --- Subcategories ---
class SubcategoryCreate(BaseModel):
    category_id: UUID
    name: str
    description: str | None = None
    image_url: str | None = None
    sort_order: int = 0
    is_active: bool = True
    show_in_kiosk: bool = True


class SubcategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    show_in_kiosk: bool | None = None


class SubcategoryResponse(BaseModel):
    id: UUID
    category_id: UUID
    store_id: UUID
    name: str
    description: str | None = None
    image_url: str | None = None
    sort_order: int
    is_active: bool
    show_in_kiosk: bool

    model_config = {"from_attributes": True}


class CategoryWithSubcategories(CategoryResponse):
    subcategories: list[SubcategoryResponse] = []


# --- Unit of Measure (catálogo global) ---
class UnitOfMeasureResponse(BaseModel):
    id: int
    code: str
    name: str
    symbol: str
    category: str
    decimals: int

    model_config = {"from_attributes": True}


# --- Products ---
class ProductCreate(BaseModel):
    category_id: UUID | None = None
    subcategory_id: UUID | None = None
    product_type_id: int = 1
    brand_id: UUID | None = None
    name: str
    description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    base_price: float
    cost_price: float | None = None
    stock: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    expiry_date: date | None = None
    has_variants: bool = False
    has_supplies: bool = False
    has_modifiers: bool = False
    show_in_pos: bool = True
    show_in_kiosk: bool = True
    can_return_to_inventory: bool = True
    sort_order: int = 0
    preparation_time: int | None = None
    attributes: list[ProductAttributeCreate] = []
    # ── Venta a granel (opcional, default off) ──
    is_bulk: bool = False
    unit_id: int | None = None
    bulk_min_quantity: float | None = None
    bulk_step: float | None = None


class ProductUpdate(BaseModel):
    category_id: UUID | None = None
    subcategory_id: UUID | None = None
    brand_id: UUID | None = None
    name: str | None = None
    description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    base_price: float | None = None
    cost_price: float | None = None
    stock: float | None = None
    min_stock: float | None = None
    max_stock: float | None = None
    expiry_date: date | None = None
    has_variants: bool | None = None
    has_supplies: bool | None = None
    has_modifiers: bool | None = None
    is_active: bool | None = None
    show_in_pos: bool | None = None
    show_in_kiosk: bool | None = None
    can_return_to_inventory: bool | None = None
    sort_order: int | None = None
    is_favorite: bool | None = None
    preparation_time: int | None = None
    # ── Venta a granel ──
    is_bulk: bool | None = None
    unit_id: int | None = None
    bulk_min_quantity: float | None = None
    bulk_step: float | None = None


class ProductResponse(BaseModel):
    id: UUID
    store_id: UUID
    category_id: UUID | None = None
    subcategory_id: UUID | None = None
    product_type_id: int
    brand_id: UUID | None = None
    name: str
    description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    base_price: float
    cost_price: float | None = None
    stock: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    expiry_date: date | None = None
    has_variants: bool
    has_supplies: bool
    has_modifiers: bool
    is_active: bool
    show_in_pos: bool
    show_in_kiosk: bool
    can_return_to_inventory: bool = True
    sort_order: int
    is_favorite: bool = False
    preparation_time: int | None = None
    created_at: datetime
    category: CategoryResponse | None = None
    brand: BrandResponse | None = None
    attributes: list[ProductAttributeResponse] = []
    images: list["ProductImageResponse"] = []
    # ── Venta a granel ──
    is_bulk: bool = False
    unit_id: int | None = None
    unit: UnitOfMeasureResponse | None = None
    bulk_min_quantity: float | None = None
    bulk_step: float | None = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def margin_percent(self) -> float | None:
        if self.cost_price and self.cost_price > 0:
            return round(((self.base_price - self.cost_price) / self.cost_price) * 100, 2)
        return None


# --- Variants ---
class VariantGroupCreate(BaseModel):
    name: str


class VariantGroupUpdate(BaseModel):
    name: str | None = None


class VariantGroupResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    attribute_definition_id: UUID | None = None
    options: list["VariantOptionResponse"] = []

    model_config = {"from_attributes": True}


class VariantOptionCreate(BaseModel):
    variant_group_id: UUID
    name: str
    sort_order: int = 0


class VariantOptionResponse(BaseModel):
    id: UUID
    variant_group_id: UUID
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


class ProductVariantCreate(BaseModel):
    variant_option_id: UUID
    sku: str | None = None
    barcode: str | None = None
    price: float
    cost_price: float | None = None
    description: str | None = None
    stock: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    can_return_to_inventory: bool = True


class ProductVariantUpdate(BaseModel):
    sku: str | None = None
    barcode: str | None = None
    price: float | None = None
    cost_price: float | None = None
    description: str | None = None
    stock: float | None = None
    min_stock: float | None = None
    max_stock: float | None = None
    can_return_to_inventory: bool | None = None
    is_active: bool | None = None


class VariantCombinationValueResponse(BaseModel):
    variant_group_id: UUID
    variant_option_id: UUID
    group_name: str | None = None
    option_name: str | None = None

    model_config = {"from_attributes": True}


class ProductVariantResponse(BaseModel):
    id: UUID
    product_id: UUID
    variant_option_id: UUID | None = None
    sku: str | None = None
    barcode: str | None = None
    price: float
    cost_price: float | None = None
    description: str | None = None
    stock: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    can_return_to_inventory: bool = True
    is_active: bool
    variant_option: VariantOptionResponse | None = None
    combination_values: list[VariantCombinationValueResponse] = []

    model_config = {"from_attributes": True}


# --- Disponibilidad cross-store ---
class AvailabilityRow(BaseModel):
    store_id: UUID
    store_name: str
    product_id: UUID
    product_name: str
    variant_id: UUID | None = None
    variant_label: str | None = None
    sku: str | None = None
    barcode: str | None = None
    stock: float
    min_stock: float
    image_url: str | None = None


# --- Variante explícita (una fila por combinación) ---
class ExplicitVariantCreate(BaseModel):
    """Crea una variante específica con sus dimensiones y stock/precio propios."""
    options: dict[UUID, UUID]  # variant_group_id → variant_option_id
    sku: str | None = None
    barcode: str | None = None
    price: float
    cost_price: float | None = None
    stock: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    can_return_to_inventory: bool = True


# --- Combinaciones multi-dimensión ---
class GenerateCombinationsDimension(BaseModel):
    """Una dimensión a usar al generar combinaciones (un atributo-variante con sus opciones)."""
    variant_group_id: UUID
    variant_option_ids: list[UUID]


class GenerateCombinationsRequest(BaseModel):
    dimensions: list[GenerateCombinationsDimension]
    default_price: float | None = None
    default_cost_price: float | None = None
    default_stock: float = 0
    default_min_stock: float = 0
    replace_existing: bool = False


class VariantMatrixDimension(BaseModel):
    variant_group_id: UUID
    group_name: str
    options: list[VariantOptionResponse] = []


class VariantMatrixResponse(BaseModel):
    product_id: UUID
    dimensions: list[VariantMatrixDimension] = []
    variants: list[ProductVariantResponse] = []


# --- Supplies ---
class SupplyCreate(BaseModel):
    name: str
    category_id: UUID | None = None
    brand_id: UUID | None = None
    unit: str | None = None
    unit_type: str | None = None
    cost_per_unit: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    current_stock: float = 0
    image_url: str | None = None
    description: str | None = None
    is_perishable: bool = False
    can_return_to_inventory: bool = True


class SupplyUpdate(BaseModel):
    name: str | None = None
    category_id: UUID | None = None
    brand_id: UUID | None = None
    unit: str | None = None
    unit_type: str | None = None
    cost_per_unit: float | None = None
    min_stock: float | None = None
    max_stock: float | None = None
    current_stock: float | None = None
    image_url: str | None = None
    description: str | None = None
    is_perishable: bool | None = None
    can_return_to_inventory: bool | None = None
    is_active: bool | None = None


class SupplyResponse(BaseModel):
    id: UUID
    store_id: UUID
    category_id: UUID | None = None
    brand_id: UUID | None = None
    category_name: str | None = None
    brand_name: str | None = None
    name: str
    unit: str | None = None
    unit_type: str | None = None
    cost_per_unit: float
    min_stock: float
    max_stock: float | None = None
    current_stock: float
    image_url: str | None = None
    description: str | None = None
    is_perishable: bool = False
    can_return_to_inventory: bool = True
    is_active: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProductSupplyCreate(BaseModel):
    supply_id: UUID
    quantity: float
    unit: str | None = None
    is_optional: bool = False
    is_default: bool = True


class ProductSupplyUpdate(BaseModel):
    quantity: float | None = None
    unit: str | None = None
    is_optional: bool | None = None
    is_default: bool | None = None


class ProductSupplyResponse(BaseModel):
    id: UUID
    product_id: UUID
    supply_id: UUID
    quantity: float
    unit: str | None = None
    quantity_in_base: float | None = None
    cost_per_product: float | None = None
    is_optional: bool
    is_default: bool
    supply: SupplyResponse | None = None

    model_config = {"from_attributes": True}


# --- Unit Types ---
class UnitDefResponse(BaseModel):
    key: str
    label: str
    to_base: float


class UnitTypeResponse(BaseModel):
    key: str
    label: str
    base_unit: str
    units: list[UnitDefResponse]


# --- Modifiers ---
class ModifierGroupCreate(BaseModel):
    name: str
    selection_type: str = "multiple"
    min_selections: int = 0
    max_selections: int | None = None
    is_required: bool = False


class ModifierGroupResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    selection_type: str
    min_selections: int
    max_selections: int | None = None
    is_required: bool
    options: list["ModifierOptionResponse"] = []

    model_config = {"from_attributes": True}


class ModifierGroupUpdate(BaseModel):
    name: str | None = None
    selection_type: str | None = None
    min_selections: int | None = None
    max_selections: int | None = None
    is_required: bool | None = None


class ModifierOptionCreate(BaseModel):
    name: str
    extra_price: float = 0
    sort_order: int = 0


class ModifierOptionUpdate(BaseModel):
    name: str | None = None
    extra_price: float | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class ModifierOptionResponse(BaseModel):
    id: UUID
    modifier_group_id: UUID
    name: str
    extra_price: float
    is_active: bool
    sort_order: int

    model_config = {"from_attributes": True}


# --- Combos ---
# --- Product Images ---
class ProductImageUpload(BaseModel):
    base64_data: str
    is_primary: bool = False


class ProductImageResponse(BaseModel):
    id: UUID
    product_id: UUID
    image_url: str
    is_primary: bool
    sort_order: int

    model_config = {"from_attributes": True}


class ProductImageUpdate(BaseModel):
    is_primary: bool


# --- Combos ---
class ComboCreate(BaseModel):
    name: str
    description: str | None = None
    price: float
    image_url: str | None = None
    show_in_kiosk: bool = True


class ComboUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    image_url: str | None = None
    show_in_kiosk: bool | None = None
    is_active: bool | None = None
    is_favorite: bool | None = None


class ComboItemCreate(BaseModel):
    product_id: UUID
    quantity: int = 1
    allows_variant_choice: bool = False
    allows_modifier_choice: bool = False


class ComboItemUpdate(BaseModel):
    quantity: int | None = None
    allows_variant_choice: bool | None = None
    allows_modifier_choice: bool | None = None


class ComboItemResponse(BaseModel):
    id: UUID
    combo_id: UUID
    product_id: UUID
    product_name: str | None = None
    product_has_variants: bool = False
    quantity: int
    allows_variant_choice: bool
    allows_modifier_choice: bool

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def resolve_product(cls, data):
        if hasattr(data, "product") and data.product:
            data.product_name = data.product.name
            data.product_has_variants = data.product.has_variants
        return data


class ComboResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    description: str | None = None
    price: float
    image_url: str | None = None
    is_active: bool
    is_favorite: bool = False
    show_in_kiosk: bool
    created_at: datetime | None = None
    items: list[ComboItemResponse] = []

    model_config = {"from_attributes": True}


# --- Bulk Import ---
class BulkImportProductRow(BaseModel):
    row_number: int
    product_id: UUID | None = None  # Si viene, es update; si no, es insert
    name: str
    base_price: float
    description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    cost_price: float | None = None
    stock: float = 0
    min_stock: float = 0
    max_stock: float | None = None
    category_name: str | None = None
    subcategory_name: str | None = None
    brand_name: str | None = None
    expiry_date: date | None = None
    show_in_pos: bool = True
    show_in_kiosk: bool = True


class BulkImportRequest(BaseModel):
    products: list[BulkImportProductRow] = Field(..., max_length=10000)
    generate_images: bool = False


class BulkImportRowError(BaseModel):
    row_number: int
    field: str
    message: str


class BulkImportResponse(BaseModel):
    total_rows: int
    success_count: int
    created_count: int = 0
    updated_count: int = 0
    error_count: int
    errors: list[BulkImportRowError]
    created_product_ids: list[str]
