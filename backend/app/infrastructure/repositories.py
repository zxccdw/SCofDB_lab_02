"""Реализация репозиториев с использованием SQLAlchemy."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user import User
from app.domain.order import Order, OrderItem, OrderStatus, OrderStatusChange


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, user: User) -> None:
        await self.session.execute(
            text("""
                INSERT INTO users (id, email, name, created_at)
                VALUES (:id, :email, :name, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name
            """),
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "created_at": user.created_at,
            }
        )
        await self.session.commit()

    async def find_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.session.execute(
            text("SELECT id, email, name, created_at FROM users WHERE id = :id"),
            {"id": user_id}
        )
        row = result.fetchone()
        
        if not row:
            return None
        
        return User(
            id=row.id,
            email=row.email,
            name=row.name,
            created_at=row.created_at,
        )

    async def find_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            text("SELECT id, email, name, created_at FROM users WHERE email = :email"),
            {"email": email}
        )
        row = result.fetchone()
        
        if not row:
            return None
        
        return User(
            id=row.id,
            email=row.email,
            name=row.name,
            created_at=row.created_at,
        )

    async def find_all(self) -> List[User]:
        result = await self.session.execute(
            text("SELECT id, email, name, created_at FROM users ORDER BY created_at DESC")
        )
        rows = result.fetchall()
        
        return [
            User(
                id=row.id,
                email=row.email,
                name=row.name,
                created_at=row.created_at,
            )
            for row in rows
        ]


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, order: Order) -> None:
        await self.session.execute(
            text("""
                INSERT INTO orders (id, user_id, status, total_amount, created_at)
                VALUES (:id, :user_id, :status, :total_amount, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    total_amount = EXCLUDED.total_amount
            """),
            {
                "id": order.id,
                "user_id": order.user_id,
                "status": order.status.value,
                "total_amount": order.total_amount,
                "created_at": order.created_at,
            }
        )
        
        await self.session.execute(
            text("DELETE FROM order_items WHERE order_id = :order_id"),
            {"order_id": order.id}
        )
        
        for item in order.items:
            await self.session.execute(
                text("""
                    INSERT INTO order_items (id, order_id, product_name, price, quantity)
                    VALUES (:id, :order_id, :product_name, :price, :quantity)
                """),
                {
                    "id": item.id,
                    "order_id": order.id,
                    "product_name": item.product_name,
                    "price": item.price,
                    "quantity": item.quantity,
                }
            )
        
        # История статусов — append-only лог: не удаляем существующие записи,
        # только добавляем новые. ON CONFLICT DO NOTHING защищает от дублей
        # при повторном сохранении одного и того же объекта Order.
        for change in order.status_history:
            await self.session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (:id, :order_id, :status, :changed_at)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": change.id,
                    "order_id": order.id,
                    "status": change.status.value,
                    "changed_at": change.changed_at,
                }
            )
        
        await self.session.commit()

    async def find_by_id(self, order_id: uuid.UUID) -> Optional[Order]:
        result = await self.session.execute(
            text("SELECT id, user_id, status, total_amount, created_at FROM orders WHERE id = :id"),
            {"id": order_id}
        )
        row = result.fetchone()
        
        if not row:
            return None
        
        items_result = await self.session.execute(
            text("""
                SELECT id, order_id, product_name, price, quantity 
                FROM order_items 
                WHERE order_id = :order_id
            """),
            {"order_id": order_id}
        )
        items_rows = items_result.fetchall()
        
        history_result = await self.session.execute(
            text("""
                SELECT id, order_id, status, changed_at 
                FROM order_status_history 
                WHERE order_id = :order_id
                ORDER BY changed_at
            """),
            {"order_id": order_id}
        )
        history_rows = history_result.fetchall()
        
        # Используем object.__new__() чтобы избежать __post_init__
        order = object.__new__(Order)
        order.id = row.id
        order.user_id = row.user_id
        order.status = OrderStatus(row.status)
        order.total_amount = row.total_amount
        order.created_at = row.created_at
        
        order.items = [
            OrderItem(
                id=item_row.id,
                order_id=item_row.order_id,
                product_name=item_row.product_name,
                price=item_row.price,
                quantity=item_row.quantity,
            )
            for item_row in items_rows
        ]
        
        order.status_history = [
            OrderStatusChange(
                id=hist_row.id,
                order_id=hist_row.order_id,
                status=OrderStatus(hist_row.status),
                changed_at=hist_row.changed_at,
            )
            for hist_row in history_rows
        ]
        
        return order

    async def find_by_user(self, user_id: uuid.UUID) -> List[Order]:
        result = await self.session.execute(
            text("""
                SELECT id, user_id, status, total_amount, created_at 
                FROM orders 
                WHERE user_id = :user_id
                ORDER BY created_at DESC
            """),
            {"user_id": user_id}
        )
        rows = result.fetchall()
        
        orders = []
        for row in rows:
            order = await self.find_by_id(row.id)
            if order:
                orders.append(order)
        
        return orders

    async def find_all(self) -> List[Order]:
        result = await self.session.execute(
            text("SELECT id FROM orders ORDER BY created_at DESC")
        )
        rows = result.fetchall()
        
        orders = []
        for row in rows:
            order = await self.find_by_id(row.id)
            if order:
                orders.append(order)
        
        return orders
