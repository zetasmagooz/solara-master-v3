"""Catálogo de unidades de medida y funciones de conversión."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitDef:
    key: str
    label: str
    to_base: float  # factor para convertir a unidad base


UNIT_TYPES: dict[str, dict] = {
    "weight": {
        "label": "Peso",
        "base_unit": "kg",
        "units": {
            "kg":  UnitDef(key="kg",  label="Kilogramo", to_base=1.0),
            "g":   UnitDef(key="g",   label="Gramo",     to_base=0.001),
            "mg":  UnitDef(key="mg",  label="Miligramo", to_base=0.000001),
            "lb":  UnitDef(key="lb",  label="Libra",     to_base=0.453592),
            "oz":  UnitDef(key="oz",  label="Onza",      to_base=0.0283495),
        },
    },
    "volume": {
        "label": "Volumen",
        "base_unit": "lt",
        "units": {
            "lt":    UnitDef(key="lt",    label="Litro",        to_base=1.0),
            "ml":    UnitDef(key="ml",    label="Mililitro",    to_base=0.001),
            "gal":   UnitDef(key="gal",   label="Galón",        to_base=3.78541),
            "fl_oz": UnitDef(key="fl_oz", label="Onza líquida", to_base=0.0295735),
        },
    },
    "piece": {
        "label": "Pieza",
        "base_unit": "pz",
        "units": {
            "pz": UnitDef(key="pz", label="Pieza", to_base=1.0),
        },
    },
}

# Set plano de todas las unidades válidas
ALL_UNITS: set[str] = set()
UNIT_TO_TYPE: dict[str, str] = {}
for _type_key, _type_def in UNIT_TYPES.items():
    for _unit_key in _type_def["units"]:
        ALL_UNITS.add(_unit_key)
        UNIT_TO_TYPE[_unit_key] = _type_key


def get_unit_def(unit_type: str, unit: str) -> UnitDef:
    """Obtener definición de unidad. Lanza ValueError si no existe."""
    type_def = UNIT_TYPES.get(unit_type)
    if not type_def:
        raise ValueError(f"Tipo de unidad inválido: {unit_type}")
    unit_def = type_def["units"].get(unit)
    if not unit_def:
        raise ValueError(f"Unidad '{unit}' no pertenece al tipo '{unit_type}'")
    return unit_def


def convert_to_base(quantity: float, unit_type: str, unit: str) -> float:
    """Convertir cantidad a unidad base. Ej: 30g → 0.03kg"""
    unit_def = get_unit_def(unit_type, unit)
    return round(quantity * unit_def.to_base, 6)


def calculate_cost(quantity: float, unit_type: str, unit: str, cost_per_base: float) -> float:
    """Calcular costo. Ej: 30g × $20/kg = 30×0.001×20 = $0.60"""
    qty_in_base = convert_to_base(quantity, unit_type, unit)
    return round(qty_in_base * cost_per_base, 4)


def get_base_unit(unit_type: str) -> str:
    """Obtener la unidad base de un tipo."""
    type_def = UNIT_TYPES.get(unit_type)
    if not type_def:
        raise ValueError(f"Tipo de unidad inválido: {unit_type}")
    return type_def["base_unit"]


def get_units_for_type(unit_type: str) -> list[dict]:
    """Retorna lista de unidades para un tipo dado."""
    type_def = UNIT_TYPES.get(unit_type)
    if not type_def:
        return []
    return [
        {"key": u.key, "label": u.label, "to_base": u.to_base}
        for u in type_def["units"].values()
    ]


def infer_unit_type(unit: str | None) -> str | None:
    """Inferir unit_type a partir de una unidad existente."""
    if not unit:
        return None
    normalized = unit.strip().lower()
    return UNIT_TO_TYPE.get(normalized)
