import sys
sys.path.append('.')
from app import app, db
from models import ExchangeAccount

with app.app_context():
    account = ExchangeAccount.query.get(2)  # id вашего аккаунта OKX
    if account:
        print(f"Аккаунт найден: {account.exchange_id}, активен: {account.is_active}")
        # Пробуем получить ключи напрямую
        print("Пробую получить api_key...")
        try:
            key = account.get_api_key()
            print(f"Ключ (первые 5 символов): {key[:5] if key else 'Пусто'}")
        except Exception as e:
            print(f"Ошибка при расшифровке api_key: {e}")
    else:
        print("Аккаунт с id=2 не найден.")