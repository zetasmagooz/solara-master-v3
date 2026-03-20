"""
Detección local de intents para consultas de lenguaje natural.

Detecta intents de venta conversacional, consultas SQL, operaciones
y periodos de tiempo sin llamadas a APIs externas.
"""

import re
from typing import Any, Dict, List, Optional


class IntentDetector:

    # ============================
    # SALE INTENT PATTERNS (ventas conversacionales)
    # ============================

    # Patrones que pueden INICIAR una venta nueva (sin sesion activa)
    # Numero: digito o palabra numerica
    _NUM_WORD = r"(\d+|una?|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"

    SALE_START_PATTERNS = [
        # ── Iniciar venta explícita ──
        (r"\b(haz|hacer|realiza|realizar|inicia|iniciar|registra|registrar|genera|generar|crea|crear|abre|abrir)\s+(una?\s+)?ventas?\b", True),
        (r"\bnueva\s+ventas?\b", True),
        (r"\biniciar?\s+ventas?\b", True),
        (r"\babrir?\s+ventas?\b", True),
        # ── Verbos de vender ──
        (r"\bvender\b", True),
        (r"\bvéndeme\b", True),
        (r"\bvendeme\b", True),
        (r"\bvendes?\b", True),  # "vende 2 coca colas"
        # ── Quiero + acción ──
        (r"\bquiero comprar\b", True),
        (r"\bquiero\s+vender\b", True),
        (r"\bquiero\s+hacer\s+(una?\s+)?ventas?\b", True),
        (r"\bquiero\s+" + _NUM_WORD, True),
        # ── Dame / me das ──
        (r"\bme das?\b", True),
        (r"\bdame\b", True),
        # ── Ponme / ponle ──
        (r"\bpónme\b", True),
        (r"\bponme\b", True),
        (r"\bponle\b", True),
        # ── Para llevar / aquí ──
        (r"\bpara llevar\b", True),
        (r"\bpara aqu[ií]\b", True),
        # ── Cobrar (inicio de venta cuando no hay sesión activa) ──
        (r"\b(cobra|cobrar|c[oó]brale)\b", True),
    ]

    # Patrones que solo aplican DURANTE una venta activa (cobro, modificacion, status)
    SALE_CONTINUATION_PATTERNS = [
        (r"\bsuman?\b.*\b(orden|pedido|cuenta)\b", True),
        (r"\bpaga\s+(con\s+)?(efectivo|tarjeta|transferencia)\b", True),
        (r"\b(efectivo|tarjeta)\s+con\s+\d+\b", True),
        (r"\bcon\s+\d+\s*(pesos)?\b.*\b(efectivo|cash)\b", True),
        (r"\bson\s+\d+\s*(pesos)?\b", True),
        (r"\bquita\b", True),
        (r"\bquitale\b", True),
        (r"\bquítale\b", True),
        (r"\bcancela\s+(la\s+)?(venta|orden|pedido)\b", True),
        (r"\belimina\b.*\b(producto|orden)\b", True),
        (r"\b(cuánto|cuanto)\s+(es|sale|seria|sería)\b", True),
        (r"\b(total|cuenta)\s+(por favor|porfavor)?\b", True),
        # Verbos de agregar (durante venta activa, sin requerir numero)
        (r"\b(agrega|agregale|agrégale|añade|añádele|mete|pido|pideme|pídeme)\s+", True),
        # "si" afirmativo + verbo de agregar
        (r"\bs[ií],?\s*(agrega|añade|ponle|dame|mete|pido|quiero)\b", True),
        # "si" afirmativo + numero (ej: "si, dos cafes")
        (r"\bs[ií],?\s*" + _NUM_WORD + r"\s+", True),
        # "tambien" / "otro" / "mas" (ej: "también un cafe", "otro cafe")
        (r"\b(tambi[eé]n|tambien|otro|otra|m[aá]s)\s+", True),
        # Respuestas de seleccion: "opción 5", "el 3", "la segunda", "5", "numero 2"
        (r"\bopci[oó]n\s*\d+\b", True),
        (r"\bn[uú]mero\s*\d+\b", True),
        (r"^\s*\d+\s*$", True),  # Solo un numero
        (r"^\s*(el|la)\s+(primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa])\s*$", True),
        # Respuestas si/no (confirmacion de stock, variante, etc.)
        (r"^\s*s[ií]\s*$", True),
        (r"^\s*no\s*$", True),
        (r"^\s*(dale|ok|claro|adelante|va|sale|listo|ninguno|saltar|nada)\s*$", True),
        # Nombres de variantes comunes (respuesta a "que tamaño?")
        (r"^\s*(chico|chica|mediano|mediana|grande|pequen[oa]|regular|xl|mini|mega|jumbo|normal|sencillo|doble|triple)\s*$", True),
    ]

    # Todos los patrones combinados (para sesiones activas)
    SALE_INTENT_PATTERNS = SALE_START_PATTERNS + SALE_CONTINUATION_PATTERNS

    # ============================
    # INTENT PATTERNS
    # ============================
    INTENT_PATTERNS = [
        # ── Específicos (deben ir ANTES de los catch-all) ──
        # Venta más alta del periodo
        (r"\b(venta|ticket)\s+(m[aá]s\s+alt[ao]|mayor|m[aá]s\s+grande)\b", "highest_sale_period"),
        (r"\b(m[aá]s\s+alt[ao]|mayor)\s+(venta|ticket)\b", "highest_sale_period"),
        # Primera venta del día
        (r"\b(primer[ao]?)\s+(venta|ticket|compra)\b", "first_sale_today"),
        (r"\b(venta|ticket)\s+(primer[ao]?)\b", "first_sale_today"),
        # Top clientes por gasto/ingresos
        (r"\b(mejores?|top)\s+\d*\s*clientes?\b", "top_customers_by_revenue_period"),
        (r"\bclientes?\b.*\b(m[aá]s\s+(compra[n]?|compr[oó]|gast[aoó]|ingres))\b", "top_customers_by_revenue_period"),
        (r"\bclientes?\b.*\b(compra[n]?|gast[aoó])\s+m[aá]s\b", "top_customers_by_revenue_period"),
        (r"\bcliente\b.*\bm[aá]s\s+ingres\b", "top_customers_by_revenue_period"),
        (r"\bcliente\b.*\b(que\s+)?gener[oó]\s+m[aá]s\b", "top_customers_by_revenue_period"),
        # Clientes que menos compran
        (r"\bclientes?\b.*\b(menos\s+(compra[n]?|compr[oó]|gast[aoó]))\b", "least_active_customers_period"),
        (r"\bclientes?\b.*\b(compra[n]?|gast[aoó])\s+menos\b", "least_active_customers_period"),
        (r"\bcliente\b.*\b(que\s+)?menos\s+(compra|gasta)\b", "least_active_customers_period"),
        # Ranking/listado de gastos
        (r"\b(gastos?\s+m[aá]s\s+altos?|mayores?\s+gastos?)\b", "expense_ranking_period"),
        (r"\b(ranking|listado|lista|desglose|resumen)\s+de\s+gastos\b", "expense_ranking_period"),
        # ── Insumos, variantes, categorías (ANTES de inventory_check_product) ──
        # Stock de insumos
        (r"\b(cu[aá]nt[oa]s?|qu[eé]\s+tanto)\b.*\b(queda|tengo|hay)\b.*\b(insumo|ingrediente)\b", "supply_stock_check"),
        (r"\b(stock|existencia|inventario)\s+de\s+(insumo|ingrediente)s?\b", "supply_stock_check"),
        (r"\b(insumo|ingrediente)s?\b.*\b(stock|existencia|queda|inventario)\b", "supply_stock_check"),
        # Costo de insumos por producto
        (r"\b(cu[aá]nto\s+(me\s+)?cuesta|costo)\b.*\b(hacer|preparar|producir)\b", "supply_cost_analysis"),
        (r"\b(costo\s+de\s+(producci[oó]n|preparaci[oó]n|insumos?))\b", "supply_cost_analysis"),
        (r"\b(receta|ingredientes?)\b.*\b(costo|precio|cu[aá]nto)\b", "supply_cost_analysis"),
        # Stock de variantes
        (r"\b(stock|existencia|inventario)\b.*\b(variantes?|tama[ñn]os?|presentaci[oó]n(es)?)\b", "variant_stock_check"),
        (r"\b(variantes?|tama[ñn]os?|presentaci[oó]n(es)?)\b.*\b(stock|existencia|queda|inventario)\b", "variant_stock_check"),
        (r"\b(cu[aá]nt[oa]s?)\b.*\b(chico|mediano|grande|regular|xl)\b.*\b(queda|tengo|hay)\b", "variant_stock_check"),
        # Productos por categoría
        (r"\b(productos?|art[ií]culos?)\b.*\b(categor[ií]a|subcategor[ií]a)\b", "products_by_category"),
        (r"\b(categor[ií]a|subcategor[ií]a)\b.*\b(productos?|art[ií]culos?|tiene|hay)\b", "products_by_category"),
        (r"\b(qu[eé]\s+hay\s+en|qu[eé]\s+tiene)\s+(la\s+)?categor[ií]a\b", "products_by_category"),
        # Stock/existencia de un producto (catch-all inventario)
        (r"\b(cu[aá]nt[ao]s?|qu[eé]\s+tanto)\b.*\b(tengo|hay|queda[n]?)\b.*\b(existencia|inventario|stock)\b", "inventory_check_product"),
        (r"\b(existencia[s]?|stock)\s+de\b", "inventory_check_product"),
        (r"\b(cu[aá]nto\s+inventario|cu[aá]nto\s+stock)\b.*\bde\b", "inventory_check_product"),
        # ── Fase 3 Nivel 1: Devoluciones detalladas ──
        # Cajero con más devoluciones (ANTES de top_returned y cancelled catch-all)
        (r"\b(cajero|emplead[oa])\b.*\b(devoluciones?|cancelaciones?)\b", "cashier_most_returns_period"),
        (r"\b(devoluciones?|cancelaciones?)\b.*\b(cajero|emplead[oa])\b", "cashier_most_returns_period"),
        # Productos con más devoluciones (ANTES de cancelled_sales_summary_period)
        (r"\b(productos?\s+con\s+m[aá]s\s+devoluciones?)\b", "top_returned_products_period"),
        (r"\b(m[aá]s\s+devueltos?|m[aá]s\s+devoluci[oó]n(es)?)\b", "top_returned_products_period"),
        # ── Fase 3 Nivel 1: Clientes avanzados ──
        # Cliente con más visitas (ANTES de customer_spending_period)
        (r"\bcliente\b.*\b(m[aá]s\s+visitas?|m[aá]s\s+frecuente)\b", "customer_most_visits_period"),
        (r"\b(m[aá]s\s+visitas?|m[aá]s\s+frecuente)\b.*\bcliente\b", "customer_most_visits_period"),
        # Clientes inactivos (ANTES de customers_list)
        (r"\bclientes?\b.*\b(no\s+ha[n]?\s+regresado|inactivos?|sin\s+comprar|no\s+ha[n]?\s+vuelto|no\s+ha[n]?\s+venido)\b", "inactive_customers_period"),
        (r"\b(no\s+ha[n]?\s+regresado|inactivos?)\b.*\bclientes?\b", "inactive_customers_period"),
        # Clientes que gastan más de X (ANTES de customer_spending_period)
        (r"\bclientes?\b.*\b(gast[ae]n?\s+m[aá]s\s+de|frecuentes?\b.*\bgast)", "high_spending_customers_period"),
        (r"\bclientes?\b.*\b(m[aá]s\s+de\s+\$?\d+)\b", "high_spending_customers_period"),
        # ── Fase 3 Nivel 1: Inventario avanzado ──
        # Días hasta agotarse
        (r"\b(cu[aá]ntos?\s+d[ií]as|quedar[eé]\s+sin|me\s+alcanza|me\s+dura[n]?)\b.*\b(inventario|stock|existencia|insumo|producto)?\b", "days_until_stockout"),
        (r"\b(d[ií]as\s+(restantes?|que\s+queda[n]?|de\s+inventario))\b", "days_until_stockout"),
        # Consumo de insumos
        (r"\b(cu[aá]nto\s+(inventario|insumo|stock)\s+se\s+(gast[oó]|us[oó]|consumi[oó]))\b", "supply_consumption_period"),
        (r"\b(consumo|uso|gasto)\s+de\s+(insumos?|inventario)\b", "supply_consumption_period"),
        # ── Fase 3 Nivel 2: Análisis compuestos ──
        # Resumen financiero (ANTES de catch-all ventas)
        (r"\b(resumen|reporte)\s+(financiero|de\s+ventas.*gastos|de\s+ventas.*utilidad)\b", "financial_summary_period"),
        (r"\b(ventas.*gastos.*utilidad|utilidad\s+(bruta|neta))\b", "financial_summary_period"),
        # Margen de ganancia (ANTES de catch-all utilidad/ganancia)
        (r"\b(margen\s+de\s+(ganancia|utilidad|rentabilidad))\b", "profit_margin_period"),
        (r"\b(rentabilidad|margen)\b.*\b(mes|semana|hoy|periodo)\b", "profit_margin_period"),
        # Comparativa de ventas (ANTES de catch-all ventas)
        (r"\b(comp[aá]ra(me)?|comparativa|diferencia)\b.*\b(ventas?|ingresos?)\b", "sales_comparison_periods"),
        (r"\b(ventas?)\b.*\b(contra|vs\.?|versus|comparad[ao])\b.*\b(ventas?|mes|semana)\b", "sales_comparison_periods"),
        # Mejor día de ingreso (ANTES de catch-all ventas)
        (r"\b(d[ií]a\s+(con\s+)?m[aá]s\s+(ingres[oa]s?|ventas?|facturaci[oó]n))\b", "best_revenue_day_period"),
        (r"\b(d[ií]a\b.*\bmayor\s+ingres[oa]?)\b", "best_revenue_day_period"),
        (r"\b(mejor\s+d[ií]a)\b.*\b(ventas?|ingres)\b", "best_revenue_day_period"),
        # Día que más se vende un producto (ANTES de product_sales_by_period)
        (r"\b(qu[eé]\s+d[ií]a)\b.*\b(vend[eo]|se\s+vende)\s+m[aá]s\b", "best_selling_day_product"),
        (r"\b(d[ií]a\s+que\s+m[aá]s\s+(vend[eo]|se\s+vende))\b", "best_selling_day_product"),
        (r"\b(d[ií]a\s+de\s+la\s+semana)\b.*\b(vend[oí]|m[aá]s)\b", "best_selling_day_product"),
        # ── Fase 2: Intents específicos adicionales ──
        # Productos menos vendidos
        (r"\b(producto|art[ií]culo)s?\s+(menos|peor)\s+(vendid[oa]s?|se\s+vende|vende)\b", "least_sold_products_period"),
        (r"\b(producto|art[ií]culo)s?\s+que\s+menos\s+(se\s+)?vende", "least_sold_products_period"),
        (r"\b(producto|art[ií]culo)s?\b.*\bvende[n]?\s+menos\b", "least_sold_products_period"),
        (r"\bqu[eé]\b.*\bvende[n]?\s+menos\b", "least_sold_products_period"),
        (r"\b(menos|peor)\s+vendid[oa]s?\b", "least_sold_products_period"),
        (r"\b(menos|peor)\s+(se\s+)?vende\b", "least_sold_products_period"),
        (r"\bqu[eé]\s+(?:no\s+se\s+vende|no\s+se\s+ha\s+vendido|menos\s+se\s+vende|menos\s+vende)\b", "least_sold_products_period"),
        # Productos con bajo inventario
        (r"\b(bajo\s+inventario|poco\s+stock|se\s+est[aá]n?\s+agotando|por\s+agotarse)\b", "low_inventory_items"),
        (r"\b(productos?\s+con\s+poc[oa]s?\s+(existencias?|stock|inventario))\b", "low_inventory_items"),
        (r"\b(qu[eé]\s+(productos?|insumos?)\s+se\s+est[aá]n?\s+acabando)\b", "low_inventory_items"),
        # Combos activos
        (r"\b(combos?|paquetes?|promociones?)\s+(activ[oa]s?|disponibles?|vigentes?)\b", "active_combos_list"),
        (r"\b(qu[eé]|cu[aá]les)\s+(combos?|paquetes?|promociones?)\s+tengo\b", "active_combos_list"),
        (r"\b(l[ií]sta|mu[eé]stra)(me)?\s+(los\s+)?(combos?|paquetes?|promociones?)\b", "active_combos_list"),
        # Propinas
        (r"\b(propinas?|tips?)\b", "tips_summary_period"),
        # Costo de envío / delivery
        (r"\b(env[ií]os?|delivery|domicilio)\b.*\b(cobr[oeé]|costo|total)\b", "delivery_fee_summary_period"),
        (r"\b(costo|total)\s+de\s+(env[ií]os?|delivery|domicilio)\b", "delivery_fee_summary_period"),
        # ── Específicos que DEBEN ir ANTES de catch-alls ──
        # Resumen de hoy (ANTES de sales_avg_ticket_period catch-all)
        (r"\b(cu[aá]nto\s+vend[ií]|cu[aá]nto\s+se\s+vendi[oó])\s+(hoy|ayer)\b", "sales_today_summary"),
        (r"\b(hoy|ayer)\b.*\b(cu[aá]nto\s+vend[ií]|ventas?|vend[ií]|ingres[eo])\b", "sales_today_summary"),
        (r"\b(ventas?\s+de\s+hoy|ventas?\s+de\s+ayer)\b", "sales_today_summary"),
        # Promedio de ticket (ANTES de sales_yesterday_tickets catch-all)
        (r"\b(promedio|media)\b.*\b(ticket|venta|ventas)\b", "sales_avg_ticket_period"),
        (r"\b(ticket|venta)\s+promedio\b", "sales_avg_ticket_period"),
        # Cajero que más vendió (ANTES del catch-all)
        (r"\b(qu[ií][eé]?n|cajero|emplead[oa]|vendedor(a)?)\b.*(vend(i[oó])|m[aá]s\s+vend)\b", "top_cashier_by_sales"),
        (r"\b(cajero|emplead[oa])\b.*\bm[aá]s\b", "top_cashier_by_sales"),
        # Desglose/método de pago (ANTES del catch-all efectivo/tarjeta)
        (r"\b(desglose|distribuci[oó]n)\b.*\b(pago|m[eé]todo|forma)\b", "sales_payment_type_tickets_amount"),
        (r"\b(m[eé]todo|forma|tipo)\s+de\s+pago\b", "sales_payment_type_tickets_amount"),
        # Porcentaje de gastos sobre ventas (ANTES de catch-all ventas)
        (r"\b(porcentaje|%|porciento)\b.*\b(gastos?)\b.*\b(ventas?)\b", "expense_percentage_over_sales"),
        (r"\b(gastos?\s+sobre\s+ventas)\b", "expense_percentage_over_sales"),
        # Efectivo en caja / corte (ANTES de catch-all efectivo)
        (r"\b(efectivo\s+en\s+caja|caja\s+actual|dinero\s+en\s+caja)\b", "current_cash_in_drawer"),
        (r"\b(caja|corte)\b", "current_cash_in_drawer"),
        # Ventas de un producto específico (ANTES de catch-all ventas)
        (r"\b(ventas?|vend[ií])\s+(de(l)?|en)\s+([a-záéíóúñü\-\s]{2,})\b", "product_sales_by_period"),
        (r"\b(de|del|en)\s+([a-z0-9ñáéíóúü\-\s]{3,})\b.*\b(ventas?|vend[ií])\b", "product_sales_by_period"),
        # ── Catch-all de ventas ──
        (r"\b(ventas?|vend[ií]|ingres[eo]|factur(é|ado)|monto)\b", "sales_avg_ticket_period"),
        (r"\b(tickets?|tikets?|comprobantes?)\b", "sales_yesterday_tickets"),
        # Ventas por método de pago específico
        (r"\b(cu[aá]nto\s+(se\s+)?vendi[oó]?\s+(en\s+)?(efectivo|tarjeta|transferencia))\b", "sales_cash_summary_period"),
        (r"\b(efectivo|tarjeta|plataformas?|mixto|transferencia)\b", "sales_payment_type_tickets_amount"),
        (r"\b(producto|art[ií]culo).*(m[aá]s\s+(vendido|vende[n]?|se\s+vende))\b", "top_product_by_units_period"),
        (r"\b(m[aá]s\s+(vendido|vende[n]?|se\s+vende))\b.*\b(producto|art[ií]culo)\b", "top_product_by_units_period"),
        (r"\b(producto|art[ií]culo)s?\b.*\bvende[n]?\s+m[aá]s\b", "top_product_by_units_period"),
        (r"\bqu[eé]\b.*\bvende[n]?\s+m[aá]s\b", "top_product_by_units_period"),
        (r"\bproducto\s+estrella\b", "top_product_by_units_period"),
        (r"\bbest\s*seller\b", "top_product_by_units_period"),
        (r"\b(ranking|top\s?10|top\s?5|lista de productos|trending|populares|m[aá]s\s+populares)\b", "top_products_ranking_period"),
        (r"\b(utilidad|rentable|ganancia)\b", "top_product_by_profit_period"),
        # Clientes: primero los más específicos, luego el catch-all
        (r"\b(clientes?\s+nuev[oa]s?|registrad[oa]s?)\b", "customer_registration_summary_period"),
        (r"\b(cu[aá]nto gast[oó] .* cliente|gasto del cliente)\b", "customer_spending_period"),
        (r"\b(primera compra|primer[oa]?\s+vez)\b.*\bclientes?\b", "customer_first_purchase_period"),
        (r"\bclientes?\b.*\b(primera compra|primer[oa]?\s+vez)\b", "customer_first_purchase_period"),
        (r"\b(g[eé]nero|hombres?|mujeres?)\b.*\bclientes?\b", "customers_by_gender_period"),
        (r"\bclientes?\b.*\b(g[eé]nero|hombres?|mujeres?)\b", "customers_by_gender_period"),
        # Historial de compras de un cliente (antes de customer_information_extended)
        (r"\b(historial|compras?|pedidos?)\s+(de(l)?\s+)?cliente\b", "customer_purchase_history"),
        (r"\bcliente\b.*\b(historial|compras?|pedidos?|ha\s+comprado)\b", "customer_purchase_history"),
        (r"\bqu[eé]\s+ha\s+comprado\b", "customer_purchase_history"),
        (r"\b(informaci[oó]n|datos?|detalle)\b.*\bcliente\b", "customer_information_extended"),
        (r"\bcliente\b.*\b(informaci[oó]n|datos?|detalle)\b", "customer_information_extended"),
        # Productos favoritos de un cliente (antes de customers_list)
        (r"\b(productos?\s+favorit[oa]s?|m[aá]s\s+compra)\b.*\bcliente\b", "customer_top_products"),
        (r"\bcliente\b.*\b(productos?\s+favorit[oa]s?|m[aá]s\s+compra|qu[eé]\s+m[aá]s\s+compra)\b", "customer_top_products"),
        (r"\b(qui[eé]nes son|lista de|ver|mu[eé]strame|dime)\b.*\bclientes?\b", "customers_list"),
        (r"\bclientes?\b.*\b(lista|ver|mostrar|todos)\b", "customers_list"),
        (r"\bcu[aá]ntos\s+clientes\b", "customers_list"),
        (r"\bmis\s+clientes\b", "customers_list"),
        # Total de gastos del periodo (antes del catch-all de gastos)
        (r"\b(total|cu[aá]nto)\s+(de\s+)?gastos?\b", "total_expenses_period"),
        (r"\b(cu[aá]nto\s+gast[eé])\b", "total_expenses_period"),
        (r"\b(gastos?|publicidad|n[oó]mina|energ[ií]a|electricidad|papeler[ií]a)\b", "expense_by_description_period"),
        (r"\b(devoluciones?|ventas? cancelad(as|os))\b", "cancelled_sales_summary_period"),
    ]

    # ============================
    # PERIOD PATTERNS
    # ============================
    PERIOD_PATTERNS = [
        (r"\b(hoy)\b", "today"),
        (r"\b(ayer)\b", "yesterday"),
        (r"\b(esta semana|semana actual)\b", "this_week"),
        (r"\b(semana pasada)\b", "last_week"),
        (r"\b(este mes|mes actual)\b", "this_month"),
        (r"\b(mes pasado)\b", "last_month"),
        (r"\b(este trimestre|trimestre actual)\b", "this_quarter"),
        (r"\b([uú]ltimo trimestre|trimestre pasado|trimestre anterior)\b", "last_quarter"),
        (r"\b(este año|año actual)\b", "this_year"),
        (r"\b(año pasado)\b", "last_year"),
        (r"\b(últim[oa]s?|ultim[oa]s?)\s+(\d{1,3})\s+d[ií]as\b", "last_n_days"),
        (r"\b(\d{2}/\d{2}/\d{4})\b", "explicit_date_slash"),
        (r"\b(\d{4}-\d{2}-\d{2})\b", "explicit_date_dash"),
        (r"\b(\d{2}/\d{2}/\d{4})\s*(a|al|-)\s*(\d{2}/\d{2}/\d{4})\b", "range_slash"),
        (r"\b(\d{4}-\d{2}-\d{2})\s*(a|al|-)\s*(\d{4}-\d{2}-\d{2})\b", "range_dash"),
        (r"\b(fin de semana|finde)\b", "weekend"),
    ]

    # ============================
    # DETECTAR VENTA CONVERSACIONAL
    # ============================
    def is_sale_intent(self, q: str, has_active_session: bool = True) -> bool:
        """Detecta si el usuario quiere realizar una venta conversacional.

        Args:
            q: Texto del usuario.
            has_active_session: Si True, usa todos los patrones (start + continuation).
                               Si False, solo usa patrones que pueden INICIAR una venta.
        """
        text = q.lower().strip()
        patterns = self.SALE_INTENT_PATTERNS if has_active_session else self.SALE_START_PATTERNS
        for pattern, _ in patterns:
            if re.search(pattern, text):
                return True
        return False

    def is_sale_start(self, q: str) -> bool:
        """Detecta si el mensaje INICIA una venta nueva (no continuación).

        Usa solo SALE_START_PATTERNS: 'vende', 'dame', 'quiero comprar', etc.
        Útil para saber si el usuario quiere una venta nueva cuando ya hay sesión activa.
        """
        text = q.lower().strip()
        for pattern, _ in self.SALE_START_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    def get_sale_context(self, q: str) -> dict:
        """Extrae contexto adicional para ventas."""
        text = q.lower().strip()
        context: Dict[str, Any] = {"action": "add"}

        if re.search(r"\b(quita|quitale|quítale|elimina|cancela)\b", text):
            context["action"] = "remove"
        elif re.search(r"\b(cobra|cobrar|paga|efectivo|tarjeta|transferencia)\b", text):
            context["action"] = "pay"
            if re.search(r"\befectivo\b", text):
                context["payment_type"] = 1
            elif re.search(r"\btarjeta\b", text):
                context["payment_type"] = 2
            elif re.search(r"\bplataforma\b", text):
                context["payment_type"] = 4
            elif re.search(r"\btransferencia\b", text):
                context["payment_type"] = 5
            amount_match = re.search(r"\b(\d+)\s*(pesos)?\b", text)
            if amount_match:
                context["amount"] = float(amount_match.group(1))
        elif re.search(r"\bcancela\s+(la\s+)?(venta|orden|pedido)\b", text):
            context["action"] = "cancel"
        elif re.search(r"\b(cuánto|cuanto|total|cuenta)\b", text):
            context["action"] = "status"

        return context

    # ============================
    # DETECTAR CREACIÓN DE PRODUCTO (OPS)
    # ============================
    def is_product_creation(self, q: str) -> bool:
        text = q.lower()
        patterns = [
            r"\b(agrega|agregar|añade|añadir|ingresa|ingresar|crea|crear|registra|registrar)\b.*\b(producto|art[ií]culo)\b",
            r"\b(nuevo producto)\b",
            r"\b(dar de alta)\b.*\b(producto|art[ií]culo)\b",
            r"\b(agregar|crear|añadir)\s+(un\s+)?(producto|art[ií]culo)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    # ============================
    # QUICK FILTERS
    # ============================
    def extract_filters(self, q: str) -> Dict[str, Any]:
        text = q.lower()
        out: Dict[str, Any] = {}

        if re.search(r"\befectivo\b", text):
            out["payment_type"] = "efectivo"
        elif re.search(r"\btarjeta\b", text):
            out["payment_type"] = "tarjeta"
        elif re.search(r"\bplataformas?\b", text):
            out["payment_type"] = "plataformas"
        elif re.search(r"\bmixto\b", text):
            out["payment_type"] = "mixto"
        elif re.search(r"\btransferencia\b", text):
            out["payment_type"] = "transferencia"

        m = re.search(r"[\"\u201c\u201d''']([^\"\u201c\u201d''']{2,})[\"\u201c\u201d''']", text)
        if m:
            out["product"] = m.group(1).strip()

        if "venta" in text or "vend" in text:
            md = re.search(r"\bde\s+([a-z0-9ñáéíóúü\-\s]{3,})", text)
            if md and "product" not in out:
                out["product"] = md.group(1).strip()

        me = re.search(r"\bemplead[oa]\b\s*(?:llamad[oa]\s*)?([a-zñáéíóúü\s]{3,})", text)
        if me:
            out["employee"] = me.group(1).strip()

        mc = re.search(r"\bcliente\b\s*(?:llamad[oa]\s*)?([a-zñáéíóúü\s]{3,})", text)
        if mc:
            out["client"] = mc.group(1).strip()

        return out

    # ============================
    # DETECTAR INTENT PRINCIPAL
    # ============================
    def detect_intent(self, q: str) -> Optional[str]:
        text = q.lower()
        if "cumple" in text or "birthday" in text:
            return "customer_birthdays_period"
        for pat, intent in self.INTENT_PATTERNS:
            if re.search(pat, text):
                return intent
        return None

    # ============================
    # EXPANSIÓN DE INTENT
    # ============================
    def expand_intent(self, intent: Optional[str], q: str) -> Optional[str]:
        if not intent:
            return None
        text = q.lower()
        if re.search(r"\b(efectivo|tarjeta|plataformas?|mixto|transferencia)\b", text):
            return "sales_payment_type_tickets_amount"
        if re.search(r"\b(ayer|hoy)\b", text) and re.search(r"\b(ventas?|vend[ií]|ingreso)\b", text):
            return "sales_today_summary"
        return intent

    # ============================
    # NORMALIZAR PERIODO
    # ============================
    def normalize_period(self, q: str) -> Optional[Dict[str, Any]]:
        t = q.lower()
        for pat, tag in self.PERIOD_PATTERNS:
            m = re.search(pat, t)
            if not m:
                continue
            if tag in ("today", "yesterday", "this_week", "last_week", "this_month",
                       "last_month", "this_year", "last_year", "weekend",
                       "this_quarter", "last_quarter"):
                return {"type": tag}
            if tag == "last_n_days":
                return {"type": "last_n_days", "value": int(m.group(2))}
            if tag == "explicit_date_slash":
                d, m_, y = m.group(1).split("/")
                return {"type": "explicit_date", "value": f"{y}-{m_}-{d}"}
            if tag == "explicit_date_dash":
                return {"type": "explicit_date", "value": m.group(1)}
            if tag == "range_slash":
                d1, d2 = m.group(1), m.group(3)
                dd1, mm1, yyyy1 = d1.split("/")
                dd2, mm2, yyyy2 = d2.split("/")
                return {"type": "range", "start": f"{yyyy1}-{mm1}-{dd1}", "end": f"{yyyy2}-{mm2}-{dd2}"}
            if tag == "range_dash":
                return {"type": "range", "start": m.group(1), "end": m.group(3)}
        return None

    # ============================
    # DETECTAR TIPO DE CONSULTA
    # ============================
    # Activar/desactivar superpoderes (ultra instinto)
    _SUPERPOWER_RE = re.compile(
        r"\bactiva\b.*\bultra\s*instinto\b",
        re.IGNORECASE,
    )
    _DEACTIVATE_SUPERPOWER_RE = re.compile(
        r"\b(apaga|desactiva)\b.*\bultra\s*instinto\b",
        re.IGNORECASE,
    )

    # Preguntas de consejo/sugerencia → siempre general (no SQL analytics)
    _ADVICE_RE = re.compile(
        r"\b(c[oó]mo\s+(puedo|podr[ií]a|hago|logro|consigo|mejoro|aumento|incremento))\b"
        r"|\b(sugerencia|consejo|tip|estrategia|recomendaci[oó]n)\b"
        r"|\b(dame\s+(un|una)\s+(tip|consejo|sugerencia|idea|estrategia))\b"
        r"|\b(qu[eé]\s+(puedo|debo)\s+hacer\s+para)\b"
        r"|\b(ayuda(me)?\s+(a|para)\s+(mejorar|incrementar|aumentar|subir|crecer))\b"
        r"|\b(mejorar|optimizar)\s+(mis\s+)?(ventas|negocio|ingresos)\b",
        re.IGNORECASE,
    )

    # Consulta de precio de producto → busqueda fuzzy + lista de precios
    _PRICE_INQUIRY_RE = re.compile(
        r"\b(cu[aá]nto\s+(cuesta|vale|sale|est[aá]))\b"
        r"|\b(precio\s+de(l)?)\b"
        r"|\b(a\s+cu[aá]nto\s+(est[aá]|se\s+vende|tengo))\b"
        r"|\b(qu[eé]\s+precio\s+tiene)\b"
        r"|\b(cu[aá]l\s+es\s+el\s+precio)\b"
        r"|\b(a\s+c[oó]mo\s+(est[aá]|tengo|sale))\b",
        re.IGNORECASE,
    )

    # Listado de productos → busqueda amplia (catálogo, inventario, "listame mis productos")
    _PRODUCT_LIST_RE = re.compile(
        r"\b(l[ií]sta(me|los)?|mu[eé]stra(me)?|ense[ñn]a(me)?|dime)\s+(de\s+)?(mis\s+)?(tod[oa]s?\s+)?(los\s+)?(productos|art[ií]culos|items)\b"
        r"|\bqu[eé]\s+productos\s+tengo\b"
        r"|\b(l[ií]sta(me)?|mu[eé]stra(me)?)\s+(?:de\s+)?(?:tod[oa]s?\s+)?(?:mis\s+)?(?:los\s+|las\s+)?(?:caf[eé]s?|bebidas|galletas|refrescos|postres|comidas|snacks)(?:\s+\w+)*\b"
        r"|\b(l[ií]sta(me)?|mu[eé]stra(me)?)\s+(?:los\s+)?productos\s+de\s+(?:la\s+)?(?:marca|categor[ií]a)\b"
        r"|\b(l[ií]sta(me)?|mu[eé]stra(me)?)\s+(?:de\s+)?(?:tod[oa]s?\s+)?mis\s+(?:los\s+|las\s+)?\w+"
        r"|\b(cu[aá]les|qu[eé])\s+(son\s+)?(mis\s+)?productos\b"
        r"|\bcat[aá]logo\s+de\s+productos\b"
        r"|\binventario\s+de\s+productos\b"
        r"|\bmis\s+productos\b",
        re.IGNORECASE,
    )

    def extract_product_list_filter(self, q: str) -> Optional[str]:
        """Extrae filtro opcional de una consulta de listado de productos.

        Ej: 'listame todos los cafes' → 'cafes'
            'muéstrame los productos de la marca Bimbo' → 'Bimbo'
            'listame mis bebidas calientes' → 'bebidas calientes'
            'listame mis productos' → None (sin filtro, listar todos)
        """
        text = q.lower().strip()

        # "productos de la categoría/categoria X"
        m = re.search(r"productos\s+de\s+(?:la\s+)?categor[ií]a\s+(.+)", text)
        if m:
            return m.group(1).strip().rstrip("?. ")

        # "productos de la marca X"
        m = re.search(r"productos\s+de\s+(?:la\s+)?marca\s+(.+)", text)
        if m:
            return m.group(1).strip().rstrip("?. ")

        # "listame todos los cafes calientes" / "muéstrame las bebidas calientes"
        m = re.search(
            r"(?:l[ií]sta(?:me)?|mu[eé]stra(?:me)?|ense[ñn]a(?:me)?)\s+"
            r"(?:de\s+)?(?:tod[oa]s?\s+)?(?:mis\s+)?(?:los\s+|las\s+)?"
            r"((?:caf[eé]s?|bebidas?|galletas?|refrescos?|postres?|comidas?|snacks?)(?:\s+\w+)*)",
            text,
        )
        if m:
            return m.group(1).strip().rstrip("?. ")

        # "listame mis [algo que no sea productos/artículos]"
        m = re.search(
            r"(?:l[ií]sta(?:me)?|mu[eé]stra(?:me)?|ense[ñn]a(?:me)?)\s+"
            r"(?:de\s+)?(?:tod[oa]s?\s+)?mis\s+(?:los\s+|las\s+)?(.+)",
            text,
        )
        if m:
            captured = m.group(1).strip().rstrip("?. ")
            # Excluir si es genérico ("mis productos", "mis artículos")
            if not re.match(r"^(?:productos|art[ií]culos|items)$", captured, re.IGNORECASE):
                return captured

        # Si matchea el patrón genérico ("listame mis productos"), no hay filtro
        return None

    # Patrón para detectar consultas analíticas ("más/menos" + verbo de negocio)
    _ANALYTICS_QUERY_RE = re.compile(
        r"\b(m[aá]s|menos|mejor|peor)\s+(se\s+)?(vende|vendid[oa]s?|compra|gasta|visita|frecuente)\b"
        r"|\b(vende|vendid[oa]s?|compra|gasta)\s+(m[aá]s|menos)\b"
        r"|\b(cu[aá]l|qu[eé]|qui[eé]n)\b.*\b(m[aá]s|menos)\s+(se\s+)?(vende|vendid[oa]|compra|gasta|visita)\b"
        r"|\b(top|ranking|trending|populares|mejores?|peores?)\s+\d*\s*(productos?|clientes?|art[ií]culos?)\b"
        r"|\b(productos?|art[ií]culos?)\s+(trending|populares)\b"
        r"|\bproducto\s+estrella\b"
        r"|\bbest\s*seller\b",
        re.IGNORECASE,
    )

    def _is_analytics_query(self, q: str) -> bool:
        """Detecta si es una consulta analítica que no debería ser venta."""
        return bool(self._ANALYTICS_QUERY_RE.search(q))

    # Contexto geográfico/general que indica pregunta de conocimiento, no de inventario
    _GENERAL_CONTEXT_RE = re.compile(
        r"\ben\s+(m[eé]xico|estados\s+unidos|eeuu|usa|espa[ñn]a|colombia|argentina|chile|per[uú]|europa|latinoam[eé]rica"
        r"|la\s+ciudad|el\s+pa[ií]s|el\s+mundo|el\s+mercado|general|promedio|la\s+calle|otros?\s+lados?"
        r"|otros?\s+negocios?|otros?\s+tiendas?|otros?\s+restaurantes?|la\s+competencia)\b"
        r"|\b(normalmente|generalmente|en\s+promedio|precio\s+promedio|precio\s+normal"
        r"|precio\s+justo|precio\s+de\s+mercado|precio\s+real)\b",
        re.IGNORECASE,
    )

    def extract_price_inquiry_product(self, q: str) -> Optional[str]:
        """Extrae el nombre del producto de una consulta de precio.

        Ej: 'cuanto cuesta un cafe' → 'cafe'
            'precio del latte' → 'latte'
            'a como esta la coca' → 'coca'

        Retorna None si la pregunta tiene contexto geográfico/general
        (ej: 'cuanto cuesta un taco en mexico') → debe ir a general.
        """
        text = q.lower().strip()

        # Si contiene contexto geográfico/general → NO es price_inquiry local
        if self._GENERAL_CONTEXT_RE.search(text):
            return None

        # Cada patrón captura TODO antes del producto, para que group(1) sea el producto
        patterns = [
            r"(?:cu[aá]nto\s+(?:cuesta|vale|sale|est[aá]))\s+(?:(?:un|una|el|la|los|las)\s+)?(.+)",
            r"(?:precio\s+de(?:l)?)\s+(?:(?:un|una|el|la|los|las)\s+)?(.+)",
            r"(?:a\s+cu[aá]nto\s+(?:est[aá]|se\s+vende|tengo))\s+(?:(?:un|una|el|la|los|las)\s+)?(.+)",
            r"(?:qu[eé]\s+precio\s+tiene)\s+(?:(?:un|una|el|la|los|las)\s+)?(.+)",
            r"(?:cu[aá]l\s+es\s+el\s+precio)\s+(?:de(?:l)?\s+)?(?:(?:un|una|el|la|los|las)\s+)?(.+)",
            r"(?:a\s+c[oó]mo\s+(?:est[aá]|tengo|sale))\s+(?:(?:un|una|el|la|los|las)\s+)?(.+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                product = m.group(1).strip()
                # Quitar sufijos comunes
                product = re.sub(r"\s+(?:en\s+mi\s+tienda|aqu[ií])\s*\??$", "", product).strip()
                product = re.sub(r"\s*\?\s*$", "", product).strip()
                if product and len(product) >= 2:
                    return product
        return None

    def detect_query_type(self, question: str) -> Dict[str, Any]:
        """
        Clasifica la consulta en: ops, sql, price_inquiry, product_list o general.

        Para ops devuelve el subtipo especifico:
        - expense, withdrawal, loan, cash_deposit, initial, checkout_cut
        - product, insert_customer
        """
        q = question.lower().strip()

        # Superpower mode (activar/desactivar) → antes de todo
        if self._DEACTIVATE_SUPERPOWER_RE.search(q):
            return {"type": "superpower", "data": "deactivate"}
        if self._SUPERPOWER_RE.search(q):
            return {"type": "superpower", "data": "activate"}

        # Preguntas de consejo/sugerencia → general (no SQL)
        if self._ADVICE_RE.search(q):
            return {"type": "general", "data": None}

        # Consultas analíticas con "más/menos" tienen prioridad sobre venta
        # Ej: "producto que más vende", "cliente que menos compra"
        if self._is_analytics_query(q):
            intent = self.detect_intent(q)
            if intent:
                return {"type": "sql", "data": intent}

        # VENTA conversacional (ANTES de descuento/price_change)
        if self.is_sale_start(q):
            return {"type": "sale", "data": "start"}

        # OPS: Descuento (ANTES de price_change para que
        # "aplica un descuento" no se confunda con cambio de precio)
        if self.is_discount(q):
            return {"type": "ops", "data": "discount"}

        # OPS: Cambio de precio (ANTES de price_inquiry para que
        # "sube el precio del cafe a 60" no se confunda con consulta de precio)
        if self.is_price_change(q):
            return {"type": "ops", "data": "price_change"}

        # OPS: Actualizacion de inventario
        if self.is_inventory_update(q):
            return {"type": "ops", "data": "inventory_update"}

        # OPS: Creacion de producto
        if self.is_product_creation(q):
            return {"type": "ops", "data": "product"}

        # Consulta de precio → busqueda fuzzy de productos
        if self._PRICE_INQUIRY_RE.search(q):
            product_name = self.extract_price_inquiry_product(q)
            if product_name:
                return {"type": "price_inquiry", "data": product_name}

        # Listado de productos → búsqueda amplia
        # Pero NO si detect_intent() detecta un SQL intent (ej: "listame mis clientes"
        # debe ir a customers_list, no a product_list)
        if self._PRODUCT_LIST_RE.search(q):
            pre_intent = self.detect_intent(q)
            if not pre_intent:
                filter_term = self.extract_product_list_filter(q)
                return {"type": "product_list", "data": filter_term}

        # Creacion de cliente
        if self.is_customer_creation(q):
            return {"type": "ops", "data": "insert_customer"}

        # Cierre / corte de caja
        if any(p in q for p in ["cierre de caja", "corte de caja", "corte de turno"]):
            return {"type": "ops", "data": "checkout_cut"}

        # Abono a caja / deposito
        if re.search(r"\b(abona|abono|abonar)\b", q) or re.search(r"\bdep[oó]sit[oa]r?\b", q):
            return {"type": "ops", "data": "cash_deposit"}
        if re.search(r"\b(mete|meter|pon|poner)\b.*\b(caja|efectivo)\b", q):
            return {"type": "ops", "data": "cash_deposit"}

        # Retiro
        if any(p in q for p in ["retiro", "sacar efectivo", "sacar dinero"]):
            return {"type": "ops", "data": "withdrawal"}
        if re.search(r"\b(retira|retirar|saca|sacar)\b.*\b(de\s+caja|efectivo|dinero)\b", q):
            return {"type": "ops", "data": "withdrawal"}
        if re.search(r"\bhaz\s+un\s+retiro\b", q):
            return {"type": "ops", "data": "withdrawal"}

        # Prestamo
        if re.search(r"\bpr[eé]sta(mo|le|me|r)\b", q):
            return {"type": "ops", "data": "loan"}

        # Fondo inicial
        if any(p in q for p in ["fondo inicial", "inicio de caja", "abrir caja"]):
            return {"type": "ops", "data": "initial"}

        # Gasto (catch-all para ops)
        if re.search(r"\bgastos?\b", q) and re.search(r"\b(registra|realiza|haz|hacer|nuevo|crea|agrega|mete|genera|aplica)\b", q):
            return {"type": "ops", "data": "expense"}
        if re.search(r"\b(registra|realiza|haz|hacer|genera)\s+(un\s+)?gastos?\b", q):
            return {"type": "ops", "data": "expense"}
        if "solara registra" in q:
            return {"type": "ops", "data": "expense"}

        # SQL (analytics)
        intent = self.detect_intent(q)
        if intent:
            return {"type": "sql", "data": intent}

        # General (conversacional)
        return {"type": "general", "data": None}

    # ============================
    # DETECTAR DESCUENTO (OPS)
    # ============================
    def is_discount(self, q: str) -> bool:
        """Detecta si el usuario quiere aplicar un descuento a productos.

        Requiere verbo de aplicación + "descuento" o patrón de porcentaje de descuento
        para no colisionar con consultas SQL analíticas.
        """
        text = q.lower()
        patterns = [
            r"\b(aplic[aá]r?|pon(er|le)?|haz|hacer|crea|crear|registra|configura)\b.*\b(descuento|promoci[oó]n|promo|rebaja|oferta)\b",
            r"\b(descuento|promoci[oó]n|promo|rebaja|oferta)\b.*\b(aplic[aá]r?|pon(er|le)?|a\s+esos)\b",
            r"\bdescuento\s+de(l)?\s+\d+\s*%",
            r"\b\d+\s*%\s+de\s+descuento\b",
            r"\baplic[aá]r?\s+\d+\s*%\b",
            r"\bpon(le|er)?\s+\d+\s*%\b.*\b(descuento|rebaja)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    # ============================
    # DETECTAR CAMBIO DE PRECIO (OPS)
    # ============================
    def is_price_change(self, q: str) -> bool:
        """Detecta si el usuario quiere cambiar precios de productos.

        Requiere verbo de modificación + "precio" para no colisionar con
        consultas SQL analíticas como "cuál es el precio de X".
        """
        text = q.lower()
        patterns = [
            r"\b(cambia|cambiar|modifica|modificar|actualiza|actualizar)\b.*\bprecios?\b",
            r"\bprecios?\b.*\b(cambia|cambiar|modifica|modificar|actualiza|actualizar)\b",
            r"\b(aumenta|aumentar|sube|subir|incrementa|incrementar)\b.*\bprecios?\b",
            r"\bprecios?\b.*\b(aumenta|aumentar|sube|subir|incrementa|incrementar)\b",
            r"\b(reduce|reducir|baja|bajar|rebaja|rebajar|disminuye|disminuir)\b.*\bprecios?\b",
            r"\bprecios?\b.*\b(reduce|reducir|baja|bajar|rebaja|rebajar|disminuye|disminuir)\b",
            r"\b(pon|ponle|poner|fija|fijar|establece|establecer)\b.*\bprecios?\b",
            r"\bprecios?\b.*\ba\s+\$\d+",
            r"\bprecios?\b.*\ben\s+\$?\d+",
        ]
        return any(re.search(p, text) for p in patterns)

    # ============================
    # DETECTAR ACTUALIZACIÓN DE INVENTARIO (OPS)
    # ============================
    def is_inventory_update(self, q: str) -> bool:
        """Detecta si el usuario quiere actualizar el inventario/stock de productos.

        Requiere verbo de modificación + inventario/stock/unidades para no
        colisionar con consultas SQL analíticas como "cuánto inventario tengo".
        """
        text = q.lower()
        patterns = [
            r"\b(ajusta|ajustar|actualiza|actualizar|modifica|modificar)\b.*\b(inventario|stock|existencias)\b",
            r"\b(inventario|stock|existencias)\b.*\b(ajusta|ajustar|actualiza|actualizar)\b",
            r"\b(suma|sumar|agrega|agregar|a[ñn]ade|a[ñn]adir)\b.*\b(unidades|piezas|inventario|stock)\b",
            r"\b(resta|restar|descuenta|descontar|quita|quitar|reduce|reducir)\b.*\b(unidades|piezas|inventario|stock)\b",
            r"\b(pon|poner|ponle|fija|fijar|establece|establecer)\b.*\b(inventario|stock|existencias)\b",
            r"\b(inventario|stock)\b.*\ba\s+\d+\s*(unidades|piezas)?\b",
            r"\+\d+\s*(unidades|piezas)\b",
            r"\b(mete|meter)\b.*\b(unidades|piezas|inventario|stock)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    # ============================
    # DETECTAR CREACIÓN DE CLIENTE
    # ============================
    def is_customer_creation(self, q: str) -> bool:
        text = q.lower()
        patterns = [
            r"\b(registra|registrar|agrega|agregar|añade|crear|crea|alta)\b.*\b(cliente)\b",
            r"\bnuevo cliente\b",
            r"\bdar de alta un cliente\b",
            r"\bcrear cliente\b",
            r"\bagregar cliente\b",
        ]
        return any(re.search(p, text) for p in patterns)
