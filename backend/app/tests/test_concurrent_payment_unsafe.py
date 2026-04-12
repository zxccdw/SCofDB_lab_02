"""
Тест для демонстрации ПРОБЛЕМЫ race condition.

Этот тест должен ПРОХОДИТЬ, подтверждая, что при использовании
pay_order_unsafe() возникает двойная оплата.
"""

import asyncio
import pytest
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.application.payment_service import PaymentService


DATABASE_URL = "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"


@pytest.fixture
async def db_session():
    """Создать сессию БД для тестов."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session_maker() as session:
        yield session
    
    await engine.dispose()


@pytest.fixture
async def test_order(db_session):
    """Создать тестовый заказ со статусом 'created'."""
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()
    
    await db_session.execute(
        text("""
            INSERT INTO users (id, email, name, created_at)
            VALUES (:id, :email, :name, NOW())
        """),
        {"id": user_id, "email": f"test_{user_id}@example.com", "name": "Test User"}
    )
    
    await db_session.execute(
        text("""
            INSERT INTO orders (id, user_id, status, total_amount, created_at)
            VALUES (:id, :user_id, 'created', 100.00, NOW())
        """),
        {"id": order_id, "user_id": user_id}
    )
    
    await db_session.execute(
        text("""
            INSERT INTO order_status_history (id, order_id, status, changed_at)
            VALUES (gen_random_uuid(), :order_id, 'created', NOW())
        """),
        {"order_id": order_id}
    )
    
    await db_session.commit()
    
    yield order_id
    
    await db_session.execute(
        text("DELETE FROM orders WHERE id = :order_id"),
        {"order_id": order_id}
    )
    await db_session.execute(
        text("DELETE FROM users WHERE id = :user_id"),
        {"user_id": user_id}
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_concurrent_payment_unsafe_demonstrates_race_condition(db_session, test_order):
    """Демонстрация race condition: обе транзакции успешно выполняются."""
    order_id = test_order
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async def payment_attempt_1():
        async with async_session_maker() as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_unsafe(order_id)
    
    async def payment_attempt_2():
        async with async_session_maker() as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_unsafe(order_id)
    
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )
    
    async with async_session_maker() as check_session:
        service = PaymentService(check_session)
        history = await service.get_payment_history(order_id)
    
    await engine.dispose()
    
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    
    assert success_count == 2, f"Ожидалось 2 успешных оплаты (RACE CONDITION!), получено: {success_count}"
    assert len(history) == 2, f"Ожидалось 2 записи об оплате (RACE CONDITION!), получено: {len(history)}"
    
    print(f"\n⚠️ RACE CONDITION DETECTED!")
    print(f"Обе транзакции успешно выполнились - нет защиты!")
    print(f"Успешных попыток: {success_count}")
    print(f"Записей в истории: {len(history)}")
    for record in history:
        print(f"  - {record['changed_at']}: status = {record['status']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
