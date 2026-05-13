"""Normalización de nombres de productos para detección de duplicados.

Convierte nombres como "Coca-Cola 600 ml", "coca cola 600ML", "COCA-COLA  600ml"
en una representación canónica comparable: "coca cola 600ml".

También extrae cantidad + unidad para usarse como guardrail anti-falsos-positivos
en el matching fuzzy (pg_trgm).
"""
from __future__ import annotations

import re
import unicodedata

# Equivalencias canónicas de unidades comunes.
# Todas las variantes de la misma unidad colapsan al mismo símbolo.
_UNIT_ALIASES: dict[str, str] = {
    "ml": "ml", "mililitro": "ml", "mililitros": "ml",
    "l": "l", "lt": "l", "lts": "l", "litro": "l", "litros": "l",
    "g": "g", "gr": "g", "grs": "g", "gramo": "g", "gramos": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogramo": "kg", "kilogramos": "kg",
    "oz": "oz", "onza": "oz", "onzas": "oz",
    "pz": "pz", "pza": "pz", "pzas": "pz", "pieza": "pz", "piezas": "pz",
    "un": "un", "und": "un", "unid": "un", "unidad": "un", "unidades": "un",
    "pk": "pk", "pack": "pk", "paquete": "pk",
}

# Regex para detectar "<número> <unidad>" o "<número><unidad>".
# Cantidad puede ser entero o decimal (con . o ,).
_QTY_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*("
    + "|".join(sorted(_UNIT_ALIASES.keys(), key=len, reverse=True))
    + r")\b",
    flags=re.IGNORECASE,
)

# Separadores que se aplanan a espacio (guion, guion bajo, slash, punto, coma, etc.).
_SEPARATORS_RE = re.compile(r"[-_/\\.,;:|·•]+")

# Cualquier carácter que no sea letra, dígito o espacio se elimina.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")

# Espacios múltiples → uno solo.
_MULTI_SPACE_RE = re.compile(r"\s+")


def _strip_accents(value: str) -> str:
    """Elimina diacríticos (NFD + filtrar combining marks). 'café' → 'cafe'."""
    nfd = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def _canonicalize_units(value: str) -> str:
    """Reemplaza '600 ml', '600ml', '600 ML' → '600ml' (unidad canónica pegada al número)."""
    def _sub(match: re.Match[str]) -> str:
        qty_raw, unit_raw = match.group(1), match.group(2).lower()
        # Normaliza coma decimal a punto y elimina ceros decimales sobrantes.
        qty = qty_raw.replace(",", ".")
        if "." in qty:
            qty = qty.rstrip("0").rstrip(".") or "0"
        canonical_unit = _UNIT_ALIASES.get(unit_raw, unit_raw)
        return f"{qty}{canonical_unit}"

    return _QTY_UNIT_RE.sub(_sub, value)


def normalize_product_name(name: str | None) -> str:
    """Devuelve la forma canónica de un nombre de producto para matching.

    - lowercase
    - sin acentos
    - separadores (-_./, etc.) → espacio
    - unidades canónicas (600 ml → 600ml, 1 LT → 1l)
    - sin caracteres no alfanuméricos
    - espacios colapsados y recortados
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = _strip_accents(s)
    s = _SEPARATORS_RE.sub(" ", s)
    s = _canonicalize_units(s)
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def extract_quantity_unit(name: str | None) -> tuple[float, str] | None:
    """Extrae la primera coincidencia '<cantidad> <unidad>' de un nombre.

    Se usa como guardrail: si dos productos tienen cantidad+unidad explícitas y
    difieren (600ml vs 1l), no son el mismo producto aunque pg_trgm diga lo contrario.
    Devuelve None si no se detecta cantidad+unidad.

    Internamente colapsa separadores y acentos primero para tolerar variantes
    como 'cafe-con-leche-250-ml' o 'café con leche 250ml'.
    """
    if not name:
        return None
    pre = _SEPARATORS_RE.sub(" ", _strip_accents(name.lower()))
    match = _QTY_UNIT_RE.search(pre)
    if not match:
        return None
    qty_raw = match.group(1).replace(",", ".")
    try:
        qty = float(qty_raw)
    except ValueError:
        return None
    unit = _UNIT_ALIASES.get(match.group(2).lower(), match.group(2).lower())
    # Convertir a unidad base para comparar: 1l == 1000ml, 1kg == 1000g.
    if unit == "l":
        qty, unit = qty * 1000, "ml"
    elif unit == "kg":
        qty, unit = qty * 1000, "g"
    return qty, unit


def quantities_conflict(a: str | None, b: str | None) -> bool:
    """True si ambos nombres exponen cantidad+unidad y son distintas.

    Si uno (o ambos) no tiene cantidad+unidad explícita, devuelve False
    (no hay conflicto detectable; deja pasar la sugerencia).
    """
    qa = extract_quantity_unit(a)
    qb = extract_quantity_unit(b)
    if qa is None or qb is None:
        return False
    qty_a, unit_a = qa
    qty_b, unit_b = qb
    if unit_a != unit_b:
        return True
    # Tolerancia mínima por floats (0.01 g/ml).
    return abs(qty_a - qty_b) > 0.01
