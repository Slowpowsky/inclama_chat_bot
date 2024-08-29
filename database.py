import sqlite3
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
def create_tables():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Обновленная таблица пользователей с полем подписки
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE,
            role TEXT,
            name TEXT,
            experience TEXT,
            portfolio TEXT,
            username TEXT,
            subscription_status TEXT DEFAULT 'inactive',
            subscription_end_date DATE
        )
    ''')

    # Создание таблицы заказов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            details TEXT,
            status TEXT,
            FOREIGN KEY (customer_id) REFERENCES users(id)
        )
    ''')

    # Создание таблицы откликов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            executor_id INTEGER,
            status TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (executor_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()


def add_user(telegram_id, role, name, experience, portfolio, username, subscription_status='inactive'):
    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (telegram_id, role, name, experience, portfolio, username, subscription_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (telegram_id, role, name, experience, portfolio, username, subscription_status))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error adding user to database: {e}")
    finally:
        conn.close()

def get_user_by_telegram_id(telegram_id):
    conn = None
    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        return user
    except sqlite3.Error as e:
        logging.error(f"Error retrieving user from database: {e}")
        return None
    finally:
        if conn:
            conn.close()

def add_order(customer_id, details):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (customer_id, details, status)
        VALUES (?, ?, 'free')
    ''', (customer_id, details))
    conn.commit()
    conn.close()


def get_free_orders():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM orders WHERE status = "free"')
    orders = cursor.fetchall()
    conn.close()
    return orders

def update_order_status(order_id, status):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))
    conn.commit()
    conn.close()

def add_response(order_id, executor_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO responses (order_id, executor_id, status)
        VALUES (?, ?, 'pending')
    ''', (order_id, executor_id))
    conn.commit()
    conn.close()

def get_responses_by_order_id(order_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM responses WHERE order_id = ?', (order_id,))
    responses = cursor.fetchall()
    conn.close()
    return responses

def update_response_status(response_id, status):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE responses SET status = ? WHERE id = ?', (status, response_id))
    conn.commit()
    conn.close()

def update_subscription_status(telegram_id, status):
    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users
            SET subscription_status = ?, subscription_end_date = DATE('now', '+1 month')
            WHERE telegram_id = ?
        ''', (status, telegram_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error updating subscription status: {e}")
    finally:
        conn.close()