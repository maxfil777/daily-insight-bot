### это консольный вывод из базы
## 

import sqlite3
import os

# Путь к базе данных
DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_users.db')

def check_database():
    if not os.path.exists(DB_PATH):
        print(f"❌ Файл базы данных не найден по пути: {DB_PATH}")
        return

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # Получаем список всех пользователей
            cursor.execute("SELECT user_id, city FROM users")
            users = cursor.fetchall()

            print("="*30)
            print(f"📊 ВСЕГО ПОДПИСЧИКОВ: {len(users)}")
            print("="*30)

            if not users:
                print("Список пуст.")
            else:
                print(f"{'TG ID':<15} | {'ГОРОД':<20}")
                print("-" * 38)
                for user_id, city in users:
                    print(f"{user_id:<15} | {city:<20}")
            print("="*30)

    except sqlite3.OperationalError as e:
        print(f"❌ Ошибка базы данных: {e}")
        print("Возможно, таблица еще не создана или миграция не прошла.")

if __name__ == "__main__":
    check_database()


