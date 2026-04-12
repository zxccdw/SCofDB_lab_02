"""Доменные сущности заказа."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from .exceptions import (
    OrderAlreadyPaidError,
    OrderCancelledError,
    InvalidQuantityError,
    InvalidPriceError,
    InvalidAmountError,
)


class OrderStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    CANCELLED = "cancelled"
    SHIPPED = "shipped"
    COMPLETED = "completed"


@dataclass
class OrderItem:
    product_name: str
    price: Decimal
    quantity: int
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    order_id: Optional[uuid.UUID] = None
    
    def __post_init__(self):
        if self.quantity <= 0:
            raise InvalidQuantityError(self.quantity)
        
        if self.price < 0:
            raise InvalidPriceError(self.price)
    
    @property
    def subtotal(self) -> Decimal:
        return self.price * self.quantity


@dataclass
class OrderStatusChange:
    order_id: uuid.UUID
    status: OrderStatus
    changed_at: datetime = field(default_factory=datetime.now)
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class Order:
    user_id: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: OrderStatus = OrderStatus.CREATED
    total_amount: Decimal = field(default=Decimal("0"))
    created_at: datetime = field(default_factory=datetime.now)
    items: List[OrderItem] = field(default_factory=list)
    status_history: List[OrderStatusChange] = field(default_factory=list)
    
    def __post_init__(self):
        if self.total_amount < 0:
            raise InvalidAmountError(self.total_amount)
        
        if not self.status_history:
            self._record_status_change()
    
    def add_item(self, product_name: str, price: Decimal, quantity: int) -> OrderItem:
        if self.status == OrderStatus.CANCELLED:
            raise OrderCancelledError(self.id)
        
        if self.status == OrderStatus.PAID:
            raise OrderAlreadyPaidError(self.id)
        
        item = OrderItem(
            product_name=product_name,
            price=price,
            quantity=quantity,
            order_id=self.id,
        )
        
        self.items.append(item)
        self._recalculate_total()
        
        return item
    
    def pay(self) -> None:
        if self.status == OrderStatus.PAID:
            raise OrderAlreadyPaidError(self.id)
        
        if self.status == OrderStatus.CANCELLED:
            raise OrderCancelledError(self.id)
        
        self.status = OrderStatus.PAID
        self._record_status_change()
    
    def cancel(self) -> None:
        if self.status == OrderStatus.PAID:
            raise OrderAlreadyPaidError(self.id)
        
        self.status = OrderStatus.CANCELLED
        self._record_status_change()
    
    def ship(self) -> None:
        if self.status != OrderStatus.PAID:
            raise ValueError(f"Order must be paid before shipping, current status: {self.status}")
        
        self.status = OrderStatus.SHIPPED
        self._record_status_change()
    
    def complete(self) -> None:
        if self.status != OrderStatus.SHIPPED:
            raise ValueError(f"Order must be shipped before completing, current status: {self.status}")
        
        self.status = OrderStatus.COMPLETED
        self._record_status_change()
    
    def _recalculate_total(self) -> None:
        self.total_amount = sum(item.subtotal for item in self.items)
    
    def _record_status_change(self) -> None:
        change = OrderStatusChange(
            order_id=self.id,
            status=self.status,
        )
        self.status_history.append(change)
