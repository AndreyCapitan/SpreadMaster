import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Импортируем ОРИГИНАЛЬНОЕ приложение и ВСЕ его компоненты напрямую
from app import app as main_app
from app import db

# Теперь создадим своё приложение, но КЛОНИРУЕМ в него все маршруты из оригинала
from flask import Flask
app = Flask(__name__)

# Копируем ВСЕ настройки из оригинального приложения
app.config.update(main_app.config)

# Инициализируем базу данных с ЭТИМ приложением
db.init_app(app)

# Теперь самое важное: КОПИРУЕМ ВСЕ МАРШРУТЫ из original_app в текущее app
for rule in main_app.url_map.iter_rules():
    # Пропускаем служебные и статические
    if not rule.endpoint.startswith('static'):
        # Связываем то же самое правило с той же функцией
        app.add_url_rule(
            rule.rule,
            endpoint=rule.endpoint,
            view_func=main_app.view_functions[rule.endpoint],
            methods=rule.methods
        )

from flask_login import LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Загружаем пользователя (функция из оригинала)
@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(int(user_id))

# Запускаем
if __name__ == '__main__':
    with app.app_context():
        # Создаём таблицы, если их нет
        db.create_all()
        print('✅ База данных проверена')
    
    print('🚀 Запуск SpreadMaster (через run_app.py)...')
    print('   Страница входа должна быть тут: http://127.0.0.1:5000/')
    app.run(debug=True, host='0.0.0.0', port=5000)