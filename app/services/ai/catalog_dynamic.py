"""
Catálogo Dinámico por Intent.

Reduce el consumo de tokens enviando SOLO las tablas relevantes
para cada intent. Ahorro estimado: 60-70% de tokens.

Adaptado al nuevo schema (public, sin prefijo sx_).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# Mapeo de intents a tablas requeridas (schema solara_dev)
INTENT_TABLE_MAP: Dict[str, List[str]] = {
    # Ventas
    "sales_today_summary": ["sales", "sale_items", "products"],
    "sales_yesterday_tickets": ["sales"],
    "sales_avg_ticket_period": ["sales"],
    "sales_payment_type_tickets_amount": ["sales", "payments"],
    "highest_sale_period": ["sales", "sale_items", "products", "users", "persons"],
    "sales_cashier_top_period": ["sales", "users", "persons"],
    "sales_cash_summary_period": ["sales", "payments"],
    # Productos
    "top_product_by_units_period": ["sales", "sale_items", "products"],
    "top_products_ranking_period": ["sales", "sale_items", "products"],
    "top_product_by_profit_period": ["sales", "sale_items", "products"],
    "product_sales_by_period": ["sales", "sale_items", "products"],
    "least_sold_products_period": ["sales", "sale_items", "products"],
    "low_inventory_items": ["products", "supplies"],
    # Clientes (datos directos en customers, NO usan persons)
    "customer_spending_period": ["sales", "sale_items", "products", "customers"],
    "customer_purchase_history": ["sales", "sale_items", "products", "customers"],
    "customer_top_products": ["sales", "sale_items", "products", "customers"],
    "customer_information_extended": ["customers"],
    "customer_birthdays_period": ["customers"],
    "customer_registration_summary_period": ["customers"],
    "customers_by_gender_period": ["customers"],
    "customers_list": ["customers"],
    "customer_first_purchase_period": ["sales", "customers"],
    "top_customers_by_revenue_period": ["sales", "customers"],
    "least_active_customers_period": ["sales", "customers"],
    # Empleados (users→persons para nombre)
    "top_cashier_by_sales": ["sales", "users", "persons", "employees"],
    # Gastos y Caja
    "expense_ranking_period": ["checkout_expenses"],
    "expense_by_description_period": ["checkout_expenses"],
    "expense_percentage_over_sales": ["checkout_expenses", "sales"],
    "total_expenses_period": ["checkout_expenses"],
    "current_cash_in_drawer": ["checkout_cuts", "checkout_expenses", "checkout_withdrawals", "checkout_deposits", "sales", "payments"],
    # Devoluciones
    "cancelled_sales_summary_period": ["sales", "sale_items", "products"],
    "top_returned_products_period": ["sale_returns", "sale_return_items", "sales", "products"],
    "cashier_most_returns_period": ["sale_returns", "users", "persons"],
    # Clientes avanzados
    "customer_most_visits_period": ["customers"],
    "inactive_customers_period": ["sales", "customers"],
    "high_spending_customers_period": ["sales", "customers"],
    # Inventario avanzado
    "inventory_check_product": ["products", "product_variants"],
    "days_until_stockout": ["products", "sales", "sale_items"],
    "supply_consumption_period": ["supplies", "product_supplies", "sales", "sale_items"],
    # Análisis compuestos
    "financial_summary_period": ["sales", "sale_items", "products", "checkout_expenses", "checkout_deposits"],
    "profit_margin_period": ["sales", "sale_items", "products", "checkout_expenses"],
    "sales_comparison_periods": ["sales"],
    "best_revenue_day_period": ["sales"],
    "best_selling_day_product": ["sales", "sale_items", "products"],
    # Combos
    "active_combos_list": ["combos"],
    # Primera venta
    "first_sale_today": ["sales", "sale_items", "products", "users", "persons", "customers"],
    # Propinas/delivery
    "tips_summary_period": ["sales"],
    "delivery_fee_summary_period": ["sales"],
    # Insumos
    "supply_stock_check": ["supplies"],
    "supply_cost_analysis": ["supplies", "product_supplies", "products"],
    # Variantes
    "variant_stock_check": ["products", "product_variants", "variant_options", "variant_groups"],
    # Categorías
    "products_by_category": ["products", "categories", "subcategories"],
    # Fecha/hora
    "datetime_now": [],
}

BASE_TABLES = ["sales", "stores"]


class DynamicCatalog:
    """Genera catálogos reducidos basados en el intent detectado."""

    def __init__(self, full_catalog_path: Optional[str] = None):
        self._full_catalog: Optional[Dict[str, Any]] = None
        self._catalog_path = full_catalog_path

    def _load_full_catalog(self) -> Dict[str, Any]:
        if self._full_catalog:
            return self._full_catalog

        candidates = [
            self._catalog_path,
            Path(__file__).parent.parent.parent / "prompts" / "solara_sql_catalog.json",
        ]

        for path in candidates:
            if path and Path(path).exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self._full_catalog = json.load(f)
                        logger.info(f"Catálogo cargado desde: {path}")
                        return self._full_catalog
                except Exception as e:
                    logger.warning(f"Error leyendo catálogo de {path}: {e}")

        raise FileNotFoundError("No se encontró el archivo de catálogo")

    def get_tables_for_intent(self, intent: str) -> List[str]:
        tables = INTENT_TABLE_MAP.get(intent, [])
        if tables:
            return list(set(BASE_TABLES) | set(tables))
        return []

    def get_filtered_catalog(
        self,
        intent: Optional[str] = None,
        tables: Optional[List[str]] = None,
        include_metadata: bool = True,
    ) -> Dict[str, Any]:
        full = self._load_full_catalog()

        if tables:
            required_tables = set(tables)
        elif intent:
            required_tables = set(self.get_tables_for_intent(intent))
        else:
            return full

        if not required_tables:
            logger.warning(f"Intent '{intent}' sin mapeo de tablas, usando catálogo completo")
            return full

        filtered: Dict[str, Any] = {}

        if include_metadata:
            for key in ["version", "timezone_local", "db", "schema", "enums", "derived_rules"]:
                if key in full:
                    filtered[key] = full[key]

        filtered["tables"] = {}
        all_tables = full.get("tables", {})

        for table_name in required_tables:
            if table_name in all_tables:
                filtered["tables"][table_name] = all_tables[table_name]

        if "synonyms" in full:
            filtered["synonyms"] = full["synonyms"]

        return filtered

    def get_catalog_stats(self, catalog: Dict[str, Any]) -> Dict[str, int]:
        tables = catalog.get("tables", {})
        total_columns = sum(len(t.get("columns", {})) for t in tables.values())
        return {
            "tables_count": len(tables),
            "columns_count": total_columns,
            "estimated_tokens": self._estimate_tokens(catalog),
        }

    def _estimate_tokens(self, catalog: Dict[str, Any]) -> int:
        return len(json.dumps(catalog, ensure_ascii=False)) // 4

    def compare_catalogs(self, intent: str) -> Dict[str, Any]:
        full = self._load_full_catalog()
        filtered = self.get_filtered_catalog(intent=intent)

        full_stats = self.get_catalog_stats(full)
        filtered_stats = self.get_catalog_stats(filtered)

        token_savings = full_stats["estimated_tokens"] - filtered_stats["estimated_tokens"]
        savings_pct = (
            (token_savings / full_stats["estimated_tokens"]) * 100
            if full_stats["estimated_tokens"] > 0
            else 0
        )

        return {
            "intent": intent,
            "full_catalog": full_stats,
            "filtered_catalog": filtered_stats,
            "token_savings": token_savings,
            "savings_percentage": round(savings_pct, 1),
        }


_dynamic_catalog: Optional[DynamicCatalog] = None


def get_dynamic_catalog() -> DynamicCatalog:
    global _dynamic_catalog
    if _dynamic_catalog is None:
        _dynamic_catalog = DynamicCatalog()
    return _dynamic_catalog
