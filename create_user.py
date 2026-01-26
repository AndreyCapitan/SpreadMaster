from app import app, db
from models import User

with app.app_context():
    # Проверяем, есть ли уже пользователь daomileh
    user = User.query.filter_by(username='daomileh').first()
    
    if user:
        print('Пользователь daomileh уже существует. Сбрасываю пароль.')
        user.set_password('280612')
    else:
        print('Создаю нового пользователя daomileh.')
        user = User(username='daomileh')
        user.set_password('280612')
        db.session.add(user)
    
    # Сохраняем изменения в базе
    db.session.commit()
    print('✅ Готово! Пароль для daomileh установлен.')