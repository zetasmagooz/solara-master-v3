from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func, case, exists, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checkout import CheckoutCut, CheckoutDeposit, CheckoutExpense, CheckoutWithdrawal
from app.models.sale import Sale, SaleItem, Payment, SaleReturn
from app.models.store import Store
from app.models.user import User, Person
from app.schemas.checkout import (
    CashStatusResponse,
    CutCreate,
    CutResponse,
    DepositCreate,
    ExpenseCreate,
    MovementResponse,
    WithdrawalCreate,
)


class CheckoutService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _owner_exclusion_filter(self, store_id: UUID, owner_user_id: UUID, entity_user_col, entity_created_col):
        """Build a WHERE clause that excludes activities by other users that were already
        closed in their own cortes. For the owner's view only.
        Returns a clause: entity belongs to owner OR hasn't been closed by another user's cut."""
        other_user_cut_exists = exists(
            select(CheckoutCut.id).where(
                CheckoutCut.store_id == store_id,
                CheckoutCut.user_id == entity_user_col,
                CheckoutCut.user_id != owner_user_id,
                CheckoutCut.created_at >= entity_created_col,
            )
        )
        return or_(
            entity_user_col == owner_user_id,
            entity_user_col.is_(None),
            ~other_user_cut_exists,
        )

    async def _get_period_start(self, store_id: UUID, user_id: UUID | None = None, is_owner: bool = True) -> datetime:
        """Get period start: last cut's created_at or store's created_at.
        Always scoped to the user's own cuts — owner uses owner's cuts, cajero uses cajero's cuts."""
        stmt = (
            select(CheckoutCut.created_at)
            .where(CheckoutCut.store_id == store_id)
            .order_by(CheckoutCut.created_at.desc())
            .limit(1)
        )
        if user_id:
            stmt = stmt.where(CheckoutCut.user_id == user_id)
        result = await self.db.execute(stmt)
        last_cut_date = result.scalar_one_or_none()
        if last_cut_date:
            return last_cut_date

        result = await self.db.execute(
            select(Store.created_at).where(Store.id == store_id)
        )
        return result.scalar_one()

    async def get_cash_status(self, store_id: UUID, user_id: UUID | None = None, is_owner: bool = True) -> CashStatusResponse:
        period_start = await self._get_period_start(store_id, user_id=user_id, is_owner=is_owner)

        # ── Sales aggregation by payment method ──
        sales_stmt = (
            select(
                func.coalesce(
                    func.sum(case((Payment.method == "cash", Payment.amount), else_=0)), 0
                ).label("cash_sales"),
                func.coalesce(
                    func.sum(case((Payment.method == "card", Payment.amount), else_=0)), 0
                ).label("card_sales"),
                func.coalesce(
                    func.sum(case((Payment.method == "transfer", Payment.amount), else_=0)), 0
                ).label("transfer_sales"),
                func.coalesce(
                    func.sum(case((Payment.method == "platform", Payment.amount), else_=0)), 0
                ).label("platform_sales"),
                func.coalesce(func.sum(Payment.amount), 0).label("total_sales"),
            )
            .join(Sale, Payment.sale_id == Sale.id)
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                Sale.created_at >= period_start,
            )
        )
        if not is_owner and user_id:
            sales_stmt = sales_stmt.where(Sale.user_id == user_id)
        elif is_owner and user_id:
            sales_stmt = sales_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, Sale.user_id, Sale.created_at)
            )
        sales_row = (await self.db.execute(sales_stmt)).one()

        # ── Tips & Shipping ──
        tips_stmt = (
            select(
                func.coalesce(func.sum(Sale.tip), 0).label("tips"),
                func.coalesce(func.sum(Sale.shipping), 0).label("shipping"),
            )
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                Sale.created_at >= period_start,
            )
        )
        if not is_owner and user_id:
            tips_stmt = tips_stmt.where(Sale.user_id == user_id)
        elif is_owner and user_id:
            tips_stmt = tips_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, Sale.user_id, Sale.created_at)
            )
        tips_row = (await self.db.execute(tips_stmt)).one()

        # ── Deposits ──
        dep_stmt = select(func.coalesce(func.sum(CheckoutDeposit.amount), 0)).where(
            CheckoutDeposit.store_id == store_id,
            CheckoutDeposit.created_at >= period_start,
        )
        if not is_owner and user_id:
            dep_stmt = dep_stmt.where(CheckoutDeposit.user_id == user_id)
        elif is_owner and user_id:
            dep_stmt = dep_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutDeposit.user_id, CheckoutDeposit.created_at)
            )
        deposits = float((await self.db.execute(dep_stmt)).scalar_one())

        # ── Expenses ──
        exp_stmt = select(func.coalesce(func.sum(CheckoutExpense.amount), 0)).where(
            CheckoutExpense.store_id == store_id,
            CheckoutExpense.created_at >= period_start,
        )
        if not is_owner and user_id:
            exp_stmt = exp_stmt.where(CheckoutExpense.user_id == user_id)
        elif is_owner and user_id:
            exp_stmt = exp_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutExpense.user_id, CheckoutExpense.created_at)
            )
        expenses = float((await self.db.execute(exp_stmt)).scalar_one())

        # ── Withdrawals ──
        wit_stmt = select(func.coalesce(func.sum(CheckoutWithdrawal.amount), 0)).where(
            CheckoutWithdrawal.store_id == store_id,
            CheckoutWithdrawal.created_at >= period_start,
        )
        if not is_owner and user_id:
            wit_stmt = wit_stmt.where(CheckoutWithdrawal.user_id == user_id)
        elif is_owner and user_id:
            wit_stmt = wit_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutWithdrawal.user_id, CheckoutWithdrawal.created_at)
            )
        withdrawals = float((await self.db.execute(wit_stmt)).scalar_one())

        # ── Returns ──
        ret_stmt = select(func.coalesce(func.sum(SaleReturn.total_refund), 0)).where(
            SaleReturn.store_id == store_id,
            SaleReturn.created_at >= period_start,
        )
        if not is_owner and user_id:
            ret_stmt = ret_stmt.where(SaleReturn.user_id == user_id)
        elif is_owner and user_id:
            ret_stmt = ret_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, SaleReturn.user_id, SaleReturn.created_at)
            )
        returns = float((await self.db.execute(ret_stmt)).scalar_one())

        # ── Compute totals ──
        cash_sales = float(sales_row.cash_sales)
        card_sales = float(sales_row.card_sales)
        transfer_sales = float(sales_row.transfer_sales)
        platform_sales = float(sales_row.platform_sales)
        total_sales = float(sales_row.total_sales)
        tips = float(tips_row.tips)
        shipping = float(tips_row.shipping)

        total_income = cash_sales + deposits
        total_outcome = expenses + withdrawals + returns
        cash_in_register = total_income - total_outcome

        # ── Movements list ──
        movements = await self._get_movements(store_id, period_start, user_id=user_id, is_owner=is_owner)

        return CashStatusResponse(
            period_start=period_start,
            cash_in_register=cash_in_register,
            cash_sales=cash_sales,
            deposits=deposits,
            total_income=total_income,
            expenses=expenses,
            withdrawals=withdrawals,
            returns=returns,
            total_outcome=total_outcome,
            card_sales=card_sales,
            transfer_sales=transfer_sales,
            platform_sales=platform_sales,
            tips=tips,
            shipping=shipping,
            total_sales_all_methods=total_sales,
            movements=movements,
        )

    async def _get_movements(self, store_id: UUID, period_start: datetime, period_end: datetime | None = None, user_id: UUID | None = None, is_owner: bool = True) -> list[MovementResponse]:
        movements: list[MovementResponse] = []

        # Pre-load user_id → first_name map for this store's users
        user_name_map: dict[UUID, str] = {}
        if is_owner:
            names_stmt = (
                select(User.id, Person.first_name)
                .join(Person, User.person_id == Person.id)
                .where(User.default_store_id == store_id)
            )
            for row in (await self.db.execute(names_stmt)).all():
                user_name_map[row.id] = row.first_name

        def _time_filter(col):
            filters = [col >= period_start]
            if period_end:
                filters.append(col <= period_end)
            return filters

        # Cash sales as movements
        # Sub-query: detect free sale items (product_id IS NULL)
        # Una venta es "libre" si tiene al menos un item sin product_id Y sin combo_id
        # (un combo tiene product_id=NULL pero combo_id seteado — no es venta libre).
        free_sale_ids_stmt = (
            select(SaleItem.sale_id)
            .where(SaleItem.product_id.is_(None), SaleItem.combo_id.is_(None))
            .distinct()
        )
        free_sale_ids = set(
            (await self.db.execute(free_sale_ids_stmt)).scalars().all()
        )

        sales_stmt = (
            select(Sale.id, Sale.sale_number, Sale.total, Sale.discount, Sale.created_at, Sale.user_id, Sale.platform)
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                *_time_filter(Sale.created_at),
            )
            .order_by(Sale.created_at.desc())
        )
        if not is_owner and user_id:
            sales_stmt = sales_stmt.where(Sale.user_id == user_id)
        elif is_owner and user_id:
            sales_stmt = sales_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, Sale.user_id, Sale.created_at)
            )
        for row in (await self.db.execute(sales_stmt)).all():
            movements.append(MovementResponse(
                id=row.id,
                type="sale",
                description=f"Venta {row.sale_number or ''}".strip(),
                amount=float(row.total),
                created_at=row.created_at,
                user_name=user_name_map.get(row.user_id) if row.user_id else None,
                has_free_sale=row.id in free_sale_ids,
                discount=float(row.discount or 0),
                platform=row.platform,
            ))

        # Deposits
        dep_stmt = (
            select(CheckoutDeposit)
            .where(CheckoutDeposit.store_id == store_id, *_time_filter(CheckoutDeposit.created_at))
        )
        if not is_owner and user_id:
            dep_stmt = dep_stmt.where(CheckoutDeposit.user_id == user_id)
        elif is_owner and user_id:
            dep_stmt = dep_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutDeposit.user_id, CheckoutDeposit.created_at)
            )
        for dep in (await self.db.execute(dep_stmt)).scalars().all():
            movements.append(MovementResponse(
                id=dep.id,
                type="deposit",
                description=dep.description or "Fondo/Abono",
                amount=float(dep.amount),
                created_at=dep.created_at,
                user_name=user_name_map.get(dep.user_id) if dep.user_id else None,
            ))

        # Expenses
        exp_stmt = (
            select(CheckoutExpense)
            .where(CheckoutExpense.store_id == store_id, *_time_filter(CheckoutExpense.created_at))
        )
        if not is_owner and user_id:
            exp_stmt = exp_stmt.where(CheckoutExpense.user_id == user_id)
        elif is_owner and user_id:
            exp_stmt = exp_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutExpense.user_id, CheckoutExpense.created_at)
            )
        for exp in (await self.db.execute(exp_stmt)).scalars().all():
            movements.append(MovementResponse(
                id=exp.id,
                type="expense",
                description=exp.description,
                amount=-float(exp.amount),
                created_at=exp.created_at,
                user_name=user_name_map.get(exp.user_id) if exp.user_id else None,
            ))

        # Withdrawals
        wit_stmt = (
            select(CheckoutWithdrawal)
            .where(CheckoutWithdrawal.store_id == store_id, *_time_filter(CheckoutWithdrawal.created_at))
        )
        if not is_owner and user_id:
            wit_stmt = wit_stmt.where(CheckoutWithdrawal.user_id == user_id)
        elif is_owner and user_id:
            wit_stmt = wit_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutWithdrawal.user_id, CheckoutWithdrawal.created_at)
            )
        for wit in (await self.db.execute(wit_stmt)).scalars().all():
            movements.append(MovementResponse(
                id=wit.id,
                type="withdrawal",
                description=wit.reason or "Retiro",
                amount=-float(wit.amount),
                created_at=wit.created_at,
                user_name=user_name_map.get(wit.user_id) if wit.user_id else None,
            ))

        # Returns
        ret_stmt = (
            select(SaleReturn)
            .where(SaleReturn.store_id == store_id, *_time_filter(SaleReturn.created_at))
        )
        if not is_owner and user_id:
            ret_stmt = ret_stmt.where(SaleReturn.user_id == user_id)
        elif is_owner and user_id:
            ret_stmt = ret_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, SaleReturn.user_id, SaleReturn.created_at)
            )
        for ret in (await self.db.execute(ret_stmt)).scalars().all():
            movements.append(MovementResponse(
                id=ret.id,
                type="return",
                description=f"Devolución {ret.return_number}",
                amount=-float(ret.total_refund),
                created_at=ret.created_at,
                user_name=user_name_map.get(ret.user_id) if ret.user_id else None,
            ))

        # Sort by date desc
        movements.sort(key=lambda m: m.created_at, reverse=True)
        return movements

    async def get_cut_movements(self, cut_id: UUID) -> list[MovementResponse]:
        """Get movements for a specific cut's period."""
        # Find this cut
        result = await self.db.execute(
            select(CheckoutCut).where(CheckoutCut.id == cut_id)
        )
        cut = result.scalar_one_or_none()
        if not cut:
            return []

        # Determine if this cut belongs to an owner or a cajero
        cut_user_id = cut.user_id
        cut_is_owner = False
        if cut_user_id:
            user_result = await self.db.execute(
                select(User.is_owner).where(User.id == cut_user_id)
            )
            cut_is_owner = bool(user_result.scalar_one_or_none())

        # Find previous cut to determine period_start (scoped to same user)
        prev_stmt = (
            select(CheckoutCut.created_at)
            .where(
                CheckoutCut.store_id == cut.store_id,
                CheckoutCut.created_at < cut.created_at,
            )
            .order_by(CheckoutCut.created_at.desc())
            .limit(1)
        )
        if not cut_is_owner and cut_user_id:
            prev_stmt = prev_stmt.where(CheckoutCut.user_id == cut_user_id)
        prev_result = await self.db.execute(prev_stmt)
        prev_date = prev_result.scalar_one_or_none()
        if not prev_date:
            store_result = await self.db.execute(
                select(Store.created_at).where(Store.id == cut.store_id)
            )
            prev_date = store_result.scalar_one()

        return await self._get_movements(
            cut.store_id, prev_date, cut.created_at,
            user_id=cut_user_id, is_owner=cut_is_owner,
        )

    async def _get_cash_in_register(self, store_id: UUID, user_id: UUID | None = None, is_owner: bool = True) -> float:
        """Calcula el efectivo en caja actual (desde el último corte)."""
        period_start = await self._get_period_start(store_id, user_id=user_id, is_owner=is_owner)

        # Ventas en efectivo
        cash_stmt = (
            select(func.coalesce(func.sum(
                case((Payment.method == "cash", Payment.amount), else_=0)
            ), 0))
            .join(Sale, Payment.sale_id == Sale.id)
            .where(Sale.store_id == store_id, Sale.status != "cancelled", Sale.created_at >= period_start)
        )
        if not is_owner and user_id:
            cash_stmt = cash_stmt.where(Sale.user_id == user_id)
        elif is_owner and user_id:
            cash_stmt = cash_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, Sale.user_id, Sale.created_at)
            )
        cash_sales = float((await self.db.execute(cash_stmt)).scalar_one())

        # Depósitos
        dep_stmt = select(func.coalesce(func.sum(CheckoutDeposit.amount), 0)).where(
            CheckoutDeposit.store_id == store_id, CheckoutDeposit.created_at >= period_start,
        )
        if not is_owner and user_id:
            dep_stmt = dep_stmt.where(CheckoutDeposit.user_id == user_id)
        elif is_owner and user_id:
            dep_stmt = dep_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutDeposit.user_id, CheckoutDeposit.created_at)
            )
        deposits = float((await self.db.execute(dep_stmt)).scalar_one())

        # Gastos
        exp_stmt = select(func.coalesce(func.sum(CheckoutExpense.amount), 0)).where(
            CheckoutExpense.store_id == store_id, CheckoutExpense.created_at >= period_start,
        )
        if not is_owner and user_id:
            exp_stmt = exp_stmt.where(CheckoutExpense.user_id == user_id)
        elif is_owner and user_id:
            exp_stmt = exp_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutExpense.user_id, CheckoutExpense.created_at)
            )
        expenses = float((await self.db.execute(exp_stmt)).scalar_one())

        # Retiros
        wit_stmt = select(func.coalesce(func.sum(CheckoutWithdrawal.amount), 0)).where(
            CheckoutWithdrawal.store_id == store_id, CheckoutWithdrawal.created_at >= period_start,
        )
        if not is_owner and user_id:
            wit_stmt = wit_stmt.where(CheckoutWithdrawal.user_id == user_id)
        elif is_owner and user_id:
            wit_stmt = wit_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, CheckoutWithdrawal.user_id, CheckoutWithdrawal.created_at)
            )
        withdrawals = float((await self.db.execute(wit_stmt)).scalar_one())

        # Devoluciones
        ret_stmt = select(func.coalesce(func.sum(SaleReturn.total_refund), 0)).where(
            SaleReturn.store_id == store_id, SaleReturn.created_at >= period_start,
        )
        if not is_owner and user_id:
            ret_stmt = ret_stmt.where(SaleReturn.user_id == user_id)
        elif is_owner and user_id:
            ret_stmt = ret_stmt.where(
                self._owner_exclusion_filter(store_id, user_id, SaleReturn.user_id, SaleReturn.created_at)
            )
        returns = float((await self.db.execute(ret_stmt)).scalar_one())

        return (cash_sales + deposits) - (expenses + withdrawals + returns)

    async def _validate_cash_sufficient(self, amount: float, store_id: UUID, user_id: UUID | None = None, is_owner: bool = True) -> None:
        """Valida que haya suficiente efectivo en caja para la operación."""
        cash = await self._get_cash_in_register(store_id, user_id=user_id, is_owner=is_owner)
        if cash < amount:
            raise HTTPException(
                status_code=400,
                detail=f"Efectivo insuficiente en caja. Disponible: ${cash:,.2f}, solicitado: ${amount:,.2f}",
            )

    async def create_deposit(self, data: DepositCreate, store_id: UUID, user_id: UUID | None) -> CheckoutDeposit:
        deposit = CheckoutDeposit(
            store_id=store_id,
            user_id=user_id,
            amount=data.amount,
            description=data.description,
        )
        self.db.add(deposit)
        await self.db.flush()
        return deposit

    async def create_expense(self, data: ExpenseCreate, store_id: UUID, user_id: UUID | None, is_owner: bool = True) -> CheckoutExpense:
        # Owner puede registrar gastos sin necesidad de tener efectivo en caja
        # (gastos fijos como renta, sueldos, etc. no salen del efectivo de caja)
        if not is_owner:
            await self._validate_cash_sufficient(float(data.amount), store_id, user_id=user_id, is_owner=is_owner)
        expense = CheckoutExpense(
            store_id=store_id,
            user_id=user_id,
            description=data.description,
            amount=data.amount,
            category=data.category,
        )
        self.db.add(expense)
        await self.db.flush()
        return expense

    async def create_withdrawal(self, data: WithdrawalCreate, store_id: UUID, user_id: UUID | None, is_owner: bool = True) -> CheckoutWithdrawal:
        await self._validate_cash_sufficient(float(data.amount), store_id, user_id=user_id, is_owner=is_owner)
        withdrawal = CheckoutWithdrawal(
            store_id=store_id,
            user_id=user_id,
            amount=data.amount,
            reason=data.reason,
        )
        self.db.add(withdrawal)
        await self.db.flush()
        return withdrawal

    async def create_cut(self, data: CutCreate, store_id: UUID, user_id: UUID | None, is_owner: bool = True) -> CheckoutCut:
        status = await self.get_cash_status(store_id, user_id=user_id, is_owner=is_owner)

        cash_expected = status.cash_in_register
        cash_actual = data.cash_actual
        difference = (cash_actual - cash_expected) if cash_actual is not None else None

        cut = CheckoutCut(
            store_id=store_id,
            user_id=user_id,
            cut_type="full",
            total_sales=status.total_sales_all_methods,
            total_expenses=status.expenses,
            total_withdrawals=status.withdrawals,
            cash_expected=cash_expected,
            cash_actual=cash_actual,
            difference=difference,
            summary={
                "period_start": status.period_start.isoformat(),
                "cash_in_register": status.cash_in_register,
                "cash_sales": status.cash_sales,
                "card_sales": status.card_sales,
                "transfer_sales": status.transfer_sales,
                "platform_sales": status.platform_sales,
                "deposits": status.deposits,
                "expenses": status.expenses,
                "withdrawals": status.withdrawals,
                "returns": status.returns,
                "tips": status.tips,
                "shipping": status.shipping,
                "total_income": status.total_income,
                "total_outcome": status.total_outcome,
            },
        )
        self.db.add(cut)
        await self.db.flush()
        return cut

    async def list_expenses(
        self,
        store_id: UUID,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List expenses with filters, pagination, and total count."""
        from sqlalchemy import func as sa_func

        base_filters = [CheckoutExpense.store_id == store_id]
        if date_from:
            base_filters.append(CheckoutExpense.created_at >= date_from)
        if date_to:
            base_filters.append(CheckoutExpense.created_at <= date_to)
        if category:
            base_filters.append(CheckoutExpense.category == category)

        # Total count
        count_stmt = select(sa_func.count(CheckoutExpense.id)).where(*base_filters)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginated data
        stmt = (
            select(CheckoutExpense)
            .where(*base_filters)
            .order_by(CheckoutExpense.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        expenses = list(result.scalars().all())

        # Enrich with user names
        user_ids = {e.user_id for e in expenses if e.user_id}
        name_map: dict = {}
        if user_ids:
            names_stmt = (
                select(User.id, Person.first_name, Person.last_name)
                .join(Person, User.person_id == Person.id)
                .where(User.id.in_(user_ids))
            )
            name_map = {
                row.id: f"{row.first_name} {row.last_name}".strip()
                for row in (await self.db.execute(names_stmt)).all()
            }

        records = [
            {
                "id": e.id,
                "date": e.created_at,
                "category": e.category,
                "description": e.description,
                "amount": float(e.amount),
                "user_name": name_map.get(e.user_id) if e.user_id else None,
            }
            for e in expenses
        ]
        return records, total

    async def get_cuts(self, store_id: UUID, user_id: UUID | None = None, is_owner: bool = True, limit: int = 20) -> list:
        stmt = (
            select(CheckoutCut)
            .where(CheckoutCut.store_id == store_id)
            .order_by(CheckoutCut.created_at.desc())
            .limit(limit)
        )
        # Non-owner users only see their own cuts
        if not is_owner and user_id:
            stmt = stmt.where(CheckoutCut.user_id == user_id)
        result = await self.db.execute(stmt)
        cuts = list(result.scalars().all())

        # Enrich with user names
        if cuts:
            user_ids = {c.user_id for c in cuts if c.user_id}
            if user_ids:
                names_stmt = (
                    select(User.id, Person.first_name, Person.last_name)
                    .join(Person, User.person_id == Person.id)
                    .where(User.id.in_(user_ids))
                )
                name_map = {
                    row.id: f"{row.first_name} {row.last_name}".strip()
                    for row in (await self.db.execute(names_stmt)).all()
                }
                for c in cuts:
                    c.user_name = name_map.get(c.user_id) if c.user_id else None

        return cuts
