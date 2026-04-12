-- ============================================
-- Схема базы данных маркетплейса
-- ============================================

-- Включаем расширение UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- Таблица статусов заказа
CREATE TABLE order_statuses (
    status VARCHAR(50) PRIMARY KEY,
    description VARCHAR(255)
);

-- Вставляем значения статусов
INSERT INTO order_statuses (status, description) VALUES
    ('created', 'Заказ создан'),
    ('paid', 'Заказ оплачен'),
    ('cancelled', 'Заказ отменён'),
    ('shipped', 'Заказ отправлен'),
    ('completed', 'Заказ завершён');


-- Таблица пользователей
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Email не может быть пустым
    CONSTRAINT email_not_empty CHECK (email != '' AND email !~ '^\s+$'),
    
    -- Email должен быть валидным
    CONSTRAINT email_valid CHECK (email ~ '^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+$')
);


-- Таблица заказов
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    total_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Внешние ключи
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_orders_status FOREIGN KEY (status) REFERENCES order_statuses(status),
    
    -- Сумма не может быть отрицательной
    CONSTRAINT total_amount_non_negative CHECK (total_amount >= 0)
);


-- Таблица товаров в заказе
CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    quantity INTEGER NOT NULL,
    
    -- Внешний ключ с каскадным удалением
    CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    
    -- Название товара не может быть пустым
    CONSTRAINT product_name_not_empty CHECK (product_name != '' AND product_name !~ '^\s+$'),
    
    -- Цена не может быть отрицательной
    CONSTRAINT price_non_negative CHECK (price >= 0),
    
    -- Количество должно быть положительным
    CONSTRAINT quantity_positive CHECK (quantity > 0)
);


-- Таблица истории изменения статусов
CREATE TABLE order_status_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL,
    status VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Внешние ключи
    CONSTRAINT fk_history_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_history_status FOREIGN KEY (status) REFERENCES order_statuses(status)
);


-- ============================================
-- КРИТИЧЕСКИЙ ИНВАРИАНТ: Нельзя оплатить заказ дважды
-- ============================================
-- В Lab 2 этот триггер отключен для демонстрации race condition
-- Защита от двойной оплаты реализуется на уровне транзакций


-- В Lab 2 история статусов записывается вручную в PaymentService,
-- поэтому триггер автоматической записи отключён во избежание дублей.


-- ============================================
-- БОНУС: Автоматический пересчёт total_amount
-- ============================================

CREATE OR REPLACE FUNCTION recalculate_order_total()
RETURNS TRIGGER AS $$
BEGIN
    -- Пересчитываем сумму заказа
    UPDATE orders
    SET total_amount = (
        SELECT COALESCE(SUM(price * quantity), 0)
        FROM order_items
        WHERE order_id = COALESCE(NEW.order_id, OLD.order_id)
    )
    WHERE id = COALESCE(NEW.order_id, OLD.order_id);
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_recalculate_order_total
    AFTER INSERT OR UPDATE OR DELETE ON order_items
    FOR EACH ROW
    EXECUTE FUNCTION recalculate_order_total();
