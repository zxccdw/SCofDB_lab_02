"""Сервис для демонстрации конкурентных оплат.

Этот модуль содержит два метода оплаты:
1. pay_order_unsafe() - небезопасная реализация (READ COMMITTED без блокировок)
2. pay_order_safe() - безопасная реализация (REPEATABLE READ + FOR UPDATE)
"""

import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import OrderAlreadyPaidError, OrderNotFoundError


class PaymentService:
    """Сервис для обработки платежей с разными уровнями изоляции."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def pay_order_unsafe(self, order_id: uuid.UUID) -> dict:
        """
        НЕБЕЗОПАСНАЯ реализация оплаты заказа.
        
        Использует READ COMMITTED (по умолчанию) без блокировок.
        ЛОМАЕТСЯ при конкурентных запросах - может привести к двойной оплате!
        """
        result = await self.session.execute(
            text("SELECT id FROM orders WHERE id = :order_id"),
            {"order_id": order_id}
        )
        row = result.fetchone()
        
        if not row:
            raise OrderNotFoundError(order_id)
        
        await self.session.execute(
            text("""
                UPDATE orders 
                SET status = 'paid' 
                WHERE id = :order_id
            """),
            {"order_id": order_id}
        )
        
        await self.session.execute(
            text("""
                INSERT INTO order_status_history (id, order_id, status, changed_at)
                VALUES (gen_random_uuid(), :order_id, 'paid', NOW())
            """),
            {"order_id": order_id}
        )
        
        await self.session.commit()
        
        return {"order_id": str(order_id), "status": "paid"}

    async def pay_order_safe(self, order_id: uuid.UUID) -> dict:
        """
        БЕЗОПАСНАЯ реализация оплаты заказа.

        Использует REPEATABLE READ + FOR UPDATE для предотвращения race condition.
        Корректно работает при конкурентных запросах.
        """
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )

        result = await self.session.execute(
            text("SELECT id, status FROM orders WHERE id = :order_id FOR UPDATE"),
            {"order_id": order_id}
        )
        row = result.fetchone()

        if not row:
            raise OrderNotFoundError(order_id)

        if row.status != 'created':
            raise OrderAlreadyPaidError(order_id)

        await self.session.execute(
            text("""
                UPDATE orders
                SET status = 'paid'
                WHERE id = :order_id AND status = 'created'
            """),
            {"order_id": order_id}
        )

        await self.session.execute(
            text("""
                INSERT INTO order_status_history (id, order_id, status, changed_at)
                VALUES (gen_random_uuid(), :order_id, 'paid', NOW())
            """),
            {"order_id": order_id}
        )

        await self.session.commit()

        return {"order_id": str(order_id), "status": "paid"}

    async def get_payment_history(self, order_id: uuid.UUID) -> list[dict]:
        """
        Получить историю оплат для заказа.

        Используется для проверки, сколько раз был оплачен заказ.
        """
        result = await self.session.execute(
            text("""
                SELECT id, order_id, status, changed_at
                FROM order_status_history
                WHERE order_id = :order_id AND status = 'paid'
                ORDER BY changed_at
            """),
            {"order_id": order_id}
        )
        rows = result.fetchall()

        return [
            {
                "id": str(row.id),
                "order_id": str(row.order_id),
                "status": row.status,
                "changed_at": row.changed_at,
            }
            for row in rows
        ]
