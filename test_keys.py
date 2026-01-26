import sys
sys.path.append('.')
from exchanges import ExchangeManager
import json

# 1. Загружаем конфиг, как это делает app.py
with open('config.json', 'r') as f:
    config = json.load(f)

# 2. Создаём менеджер (как в app.py)
manager = ExchangeManager(config)

# 3. Пытаемся подключиться с вашими ключами (ВСТАВЬТЕ СВОИ ЗДЕСЬ)
YOUR_API_KEY = 'bg_901250e14d08aec8da5c94e5a7c53fe8'
YOUR_API_SECRET = '8ab3af91cf744463001b848f28c8116f1e0acdc34ece7b35a12ba663928b52f4'

print("Пробую подключиться к bitget с ключами...")
success = manager.set_exchange_credentials('bitget', YOUR_API_KEY, YOUR_API_SECRET)
print(f"Результат: {'УСПЕХ' if success else 'ПРОВАЛ'}")