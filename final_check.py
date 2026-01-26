import sys
import os
sys.path.append('.')
from app import app, db
from models import ExchangeAccount, get_encryption_key, decrypt_value

print("="*50)
print("ФИНАЛЬНАЯ ДИАГНОСТИКА КЛЮЧЕЙ В БАЗЕ")
print("="*50)

with app.app_context():
    # 1. Проверяем сам FLASK_SECRET_KEY
    secret_from_env = os.environ.get('FLASK_SECRET_KEY')
    print(f"1. FLASK_SECRET_KEY из .env (первые 10 символов): '{secret_from_env[:10] if secret_from_env else 'НЕТ КЛЮЧА!'}...'")
    print(f"   Длина ключа: {len(secret_from_env) if secret_from_env else 0}")
    if not secret_from_env or secret_from_env == 'ваш_секретный_ключ_шифрования':
        print("   ⚠️  КРИТИЧЕСКАЯ ОШИБКА: Ключ не установлен или остался шаблонным!")
    
    # 2. Проверяем ключи шифрования
    try:
        fernet = get_encryption_key()
        print(f"2. Объект для шифрования создан: {'ДА' if fernet else 'НЕТ'}")
    except Exception as e:
        print(f"2. Ошибка при создании объекта шифрования: {e}")
    
    # 3. Проверяем записи в БД
    accounts = ExchangeAccount.query.filter_by(is_active=True).all()
    print(f"3. Найдено активных записей в exchange_accounts: {len(accounts)}")
    
    for acc in accounts:
        print(f"\n   Проверяем аккаунт ID={acc.id}, Биржа='{acc.exchange_id}':")
        print(f"   - Зашифрованный API Key (первые 20 симв.): '{acc.api_key_encrypted[:20] if acc.api_key_encrypted else 'ПУСТО'}...'")
        print(f"   - Длина зашифрованного ключа: {len(acc.api_key_encrypted) if acc.api_key_encrypted else 0}")
        
        # 4. Пробуем расшифровать ПРЯМО через decrypt_value (минуя get_credentials)
        try:
            if acc.api_key_encrypted:
                decrypted_test = decrypt_value(acc.api_key_encrypted)
                print(f"   - ПРЯМАЯ расшифровка через decrypt_value(): УСПЕХ")
                print(f"     Расшифровано (первые 5 символов): '{decrypted_test[:5]}...'")
            else:
                print(f"   - ПРЯМАЯ расшифровка: Поле пустое")
        except Exception as e:
            print(f"   - ПРЯМАЯ расшифровка через decrypt_value(): ОШИБКА - {type(e).__name__}: {e}")
        
        # 5. Пробуем через get_credentials
        print(f"   - Вызов get_credentials()...")
        try:
            creds = acc.get_credentials()
            if creds:
                print(f"   - get_credentials() вернул: УСПЕХ")
            else:
                print(f"   - get_credentials() вернул: None (без ошибки)")
        except Exception as e:
            print(f"   - get_credentials() вызвал ИСКЛЮЧЕНИЕ: {type(e).__name__}: {e}")

print("\n" + "="*50)
print("ДИАГНОСТИКА ЗАВЕРШЕНА")
print("="*50)