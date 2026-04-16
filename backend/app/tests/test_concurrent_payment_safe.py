"""
Тест для демонстрации РЕШЕНИЯ проблемы race condition.

Этот тест должен ПРОХОДИТЬ, подтверждая, что при использовании
pay_order_safe() заказ оплачивается только один раз.
"""

import asyncio
import time
import pytest
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.application.payment_service import PaymentService
from app.domain.exceptions import OrderAlreadyPaidError


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
async def test_concurrent_payment_safe_prevents_race_condition(db_session, test_order):
    """Решение race condition: заказ оплачивается только один раз."""
    order_id = test_order
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async def payment_attempt_1():
        async with async_session_maker() as session1:
            service1 = PaymentService(session1)
            return await service1.pay_order_safe(order_id)
    
    async def payment_attempt_2():
        async with async_session_maker() as session2:
            service2 = PaymentService(session2)
            return await service2.pay_order_safe(order_id)
    
    results = await asyncio.gather(
        payment_attempt_1(),
        payment_attempt_2(),
        return_exceptions=True
    )
    
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    errors = [r for r in results if isinstance(r, Exception)]

    assert success_count == 1, f"Ожидалась одна успешная оплата, получено: {success_count}"
    assert len(errors) == 1, f"Ожидалась одна неудачная попытка, получено: {len(errors)}"
    assert isinstance(errors[0], OrderAlreadyPaidError), (
        f"Проигравшая транзакция должна поднять OrderAlreadyPaidError, "
        f"получено: {type(errors[0])}: {errors[0]}"
    )
    
    async with async_session_maker() as check_session:
        service = PaymentService(check_session)
        history = await service.get_payment_history(order_id)
    
    await engine.dispose()
    
    assert len(history) == 1, f"Ожидалась 1 запись об оплате (БЕЗ RACE CONDITION!), получено: {len(history)}"
    
    print(f"\n✅ RACE CONDITION PREVENTED!")
    print(f"Order {order_id} was paid only ONCE:")
    print(f"  - {history[0]['changed_at']}: status = {history[0]['status']}")
    error_result = next((r for r in results if isinstance(r, Exception)), None)
    print(f"Second attempt was rejected: {error_result}")


@pytest.mark.asyncio
async def test_concurrent_payment_safe_with_explicit_timing(db_session, test_order):
    """Проверка работы блокировок с явной задержкой."""
    order_id = test_order
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    timestamps = {}
    
    async def payment_attempt_with_delay():
        timestamps['start_1'] = time.time()
        async with async_session_maker() as session1:
            await session1.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            )
            
            await session1.execute(
                text("SELECT id, status FROM orders WHERE id = :order_id FOR UPDATE"),
                {"order_id": order_id}
            )
            
            await asyncio.sleep(1)
            
            await session1.execute(
                text("UPDATE orders SET status = 'paid' WHERE id = :order_id AND status = 'created'"),
                {"order_id": order_id}
            )
            
            await session1.execute(
                text("INSERT INTO order_status_history (id, order_id, status, changed_at) VALUES (gen_random_uuid(), :order_id, 'paid', NOW())"),
                {"order_id": order_id}
            )
            
            await session1.commit()
        timestamps['end_1'] = time.time()
        return {"status": "paid"}
    
    async def payment_attempt_delayed_start():
        await asyncio.sleep(0.1)
        timestamps['start_2'] = time.time()
        try:
            async with async_session_maker() as session2:
                service2 = PaymentService(session2)
                result = await service2.pay_order_safe(order_id)
            return result
        finally:
            timestamps['end_2'] = time.time()
    
    results = await asyncio.gather(
        payment_attempt_with_delay(),
        payment_attempt_delayed_start(),
        return_exceptions=True
    )
    
    await engine.dispose()
    
    time_diff = timestamps['end_2'] - timestamps['start_2']
    assert time_diff >= 0.9, f"Вторая транзакция должна была ждать >= 0.9 сек, получено: {time_diff:.2f} сек"
    
    print(f"\n⏱️ Временные метки:")
    print(f"  Транзакция 1: {timestamps['end_1'] - timestamps['start_1']:.2f} сек")
    print(f"  Транзакция 2: {time_diff:.2f} сек (ждала блокировки)")


@pytest.mark.asyncio
async def test_concurrent_payment_safe_multiple_orders(db_session):
    """Проверка, что блокировки не мешают разным заказам."""
    user_id = uuid.uuid4()
    order_id_1 = uuid.uuid4()
    order_id_2 = uuid.uuid4()
    
    await db_session.execute(
        text("INSERT INTO users (id, email, name, created_at) VALUES (:id, :email, :name, NOW())"),
        {"id": user_id, "email": f"test_{user_id}@example.com", "name": "Test User"}
    )
    
    for order_id in [order_id_1, order_id_2]:
        await db_session.execute(
            text("INSERT INTO orders (id, user_id, status, total_amount, created_at) VALUES (:id, :user_id, 'created', 100.00, NOW())"),
            {"id": order_id, "user_id": user_id}
        )
        await db_session.execute(
            text("INSERT INTO order_status_history (id, order_id, status, changed_at) VALUES (gen_random_uuid(), :order_id, 'created', NOW())"),
            {"order_id": order_id}
        )
    
    await db_session.commit()
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async def pay_order(order_id):
        async with async_session_maker() as session:
            service = PaymentService(session)
            return await service.pay_order_safe(order_id)
    
    results = await asyncio.gather(
        pay_order(order_id_1),
        pay_order(order_id_2),
        return_exceptions=True
    )
    
    await engine.dispose()
    
    success_count = sum(1 for r in results if not isinstance(r, Exception))
    assert success_count == 2, f"Ожидалось две успешные оплаты, получено: {success_count}"
    
    for oid in [order_id_1, order_id_2]:
        await db_session.execute(
            text("DELETE FROM orders WHERE id = :order_id"),
            {"order_id": oid}
        )
    await db_session.execute(
        text("DELETE FROM users WHERE id = :user_id"),
        {"user_id": user_id}
    )
    await db_session.commit()
    
    print(f"\n✅ Оба заказа успешно оплачены параллельно (блокировки не конфликтуют)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
