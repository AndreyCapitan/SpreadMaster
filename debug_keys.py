import sys
sys.path.append('.')
from app import app, db
from models import ExchangeAccount, encrypt_value, decrypt_value

print("=== ДИАГНОСТИКА СОХРАНЕННЫХ КЛЮЧЕЙ ===")
with app.app_context():
    # 1. Проверим все записи в таблице
    accounts = ExchangeAccount.query.all()
    print(f"Всего записей в exchange_accounts: {len(accounts)}")
    
    for acc in accounts:
        print(f"\n--- Аккаунт ID={acc.id} ({acc.exchange_id}, active={acc.is_active}) ---")
        print(f"Имя: {acc.name}")
        # Покажем длину зашифрованных данных
        print(f"Длина зашифр. API Key: {len(acc.api_key_encrypted) if acc.api_key_encrypted else 0}")
        print(f"Длина зашифр. Secret: {len(acc.api_secret_encrypted) if acc.api_secret_encrypted else 0}")
        print(f"Длина зашифр. Passphrase: {len(acc.passphrase_encrypted) if acc.passphrase_encrypted else 0}")
        
        # 2. Попробуем расшифровать напрямую с помощью функций из models.py
        try:
            if acc.api_key_encrypted:
                # ВАЖНО: используем decrypt_value, которая должна быть в models.py
                decrypted_key = decrypt_value(acc.api_key_encrypted)
                print(f"Прямая расшифровка API Key: УСПЕХ -> '{decrypted_key[:5]}...'")
            else:
                print("Поле API Key пустое!")
        except Exception as e:
            print(f"ОШИБКА при прямой расшифровке API Key: {type(e).__name__}: {e}")
        
        # 3. Протестируем функцию шифрования на тестовой строке
        print("Тест шифрования/расшифровки 'test_string'...")
        try:
            encrypted_test = encrypt_value("test_string")
            decrypted_test = decrypt_value(encrypted_test)
            print(f"Тест шифрования: УСПЕХ ('test_string' -> ... -> '{decrypted_test}')")
        except Exception as e:
            print(f"ТЕСТ шифрования ПРОВАЛЕН: {type(e).__name__}: {e}")

print("\n=== ДИАГНОСТИКА ЗАВЕРШЕНА ===")