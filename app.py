import os
import json
import time
import threading
from datetime import datetime

from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from exchanges import ExchangeManager
from spread_calculator import SpreadCalculator, StochasticCalculator
from models import db, User, Exchange, ArbitrageConfig, TradingPair, TradeLog
from auto_trader import AutoTrader 

# 1. First, create the Flask app
app = Flask(__name__)

# 2. Configure the app
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///' + os.path.join(os.path.dirname(__file__), 'app.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24).hex())

# 3. Initialize Extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 4. Create dependency instances
exchange_manager = ExchangeManager()
spread_calculator = SpreadCalculator()

# 5. FINALLY, initialize auto_trader now that app, db, etc. exist
auto_trader = AutoTrader(app, db, exchange_manager, spread_calculator)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Создание таблиц и инициализация базовых данных
with app.app_context():
    db.create_all()
    print("[STARTUP] Таблицы базы данных созданы.")
    
    # Инициализация базовых данных, если их нет
    from models import init_default_data
    init_default_data()
    print("[STARTUP] Базовая конфигурация проверена.")

# Загрузка конфигурации из файла
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
    print("[STARTUP] Конфигурационный файл config.json загружен.")
except FileNotFoundError:
    print("[ERROR] Файл config.json не найден. Создайте его на основе config.example.json")
    config = {}
except json.JSONDecodeError:
    print("[ERROR] Ошибка в формате config.json. Проверьте JSON-синтаксис.")
    config = {}

# Инициализация основных компонентов
exchange_manager = ExchangeManager(config)
spread_calculator = SpreadCalculator(
    config.get('spread_thresholds', {}),
    config.get('colors', {})
)
stochastic_calculator = StochasticCalculator(**config.get('stochastic_settings', {}))

# ==================== АКТИВАЦИЯ КЛЮЧЕЙ ИЗ БАЗЫ ДАННЫХ ====================

print("[STARTUP] Запуск активации API-ключей из БД...")
with app.app_context():
    # ВАЖНО: Используем новую модель Exchange вместо ExchangeAccount
    active_exchanges = Exchange.query.filter_by(enabled=True).all()
    print(f"[STARTUP] Найдено {len(active_exchanges)} активных бирж в БД.")

    for exchange_record in active_exchanges:
        print(f"[STARTUP] Активация: {exchange_record.name} (ID: {exchange_record.id})")
        
        # ВАЖНО: Используем новые методы get_api_key() и get_api_secret()
        api_key = exchange_record.get_api_key()
        api_secret = exchange_record.get_api_secret()
        
        if api_key and api_secret:
            # Имя биржи в lower case (bitget, mexc) должно соответствовать ключу в config['exchanges']
            success = exchange_manager.set_exchange_credentials(
                exchange_record.name.lower(),
                api_key,
                api_secret
            )
            status = "УСПЕХ" if success else "ПРОВАЛ"
            print(f"[STARTUP] Результат для {exchange_record.name}: {status}")
        else:
            print(f"[STARTUP] Пропуск {exchange_record.name}: нет ключей в БД.")

print("[STARTUP] Активация ключей завершена.")

# ==================== ГЛОБАЛЬНОЕ СОСТОЯНИЕ ПРИЛОЖЕНИЯ ====================

app_state = {
    'paused': False,
    'update_interval': config.get('update_interval_ms', 5000),
    'selected_pairs': ['BTC/USDT', 'ETH/USDT'],
    'enabled_exchanges': list(config.get('exchanges', {}).keys()),
    'prices': {},
    'spreads': [],
    'health_report': {}
}

def background_price_updater():
    """Фоновая задача для обновления цен и спредов."""
    print("[BACKGROUND] Фоновый поток ЗАПУЩЕН")
    iteration = 0
    while True:
        iteration += 1
        
        if not app_state['paused']:
            try:
                print(f"[BACKGROUND #{iteration}] Запрос цен...")
                prices = exchange_manager.fetch_all_prices(app_state['selected_pairs'])
                
                # ДИАГНОСТИКА: что пришло от бирж
                for ex_id, tickers in prices.items():
                    print(f"[DEBUG] Биржа {ex_id}: {len(tickers)} пар")
                    for pair, ticker in tickers.items():
                        if ticker:
                            print(f"  {pair}: bid={ticker.bid:.2f}, ask={ticker.ask:.2f}")
                        else:
                            print(f"  {pair}: НЕТ ДАННЫХ")
                
                
                # 4. РАСЧЁТ СПРЕДОВ (передаём исходные объекты TickerData)
                spreads = spread_calculator.calculate_spreads(prices, app_state['selected_pairs'])
                
                # 5. Сохраняем результаты в формате для API
                app_state['spreads'] = [
                    {
                        'pair': s.pair,
                        'exchange1': s.exchange1,
                        'exchange2': s.exchange2,
                        'spread_percent': s.spread_percent,
                        'bid_exchange': s.bid_exchange,
                        'ask_exchange': s.ask_exchange,
                        'bid_price': s.bid_price,
                        'ask_price': s.ask_price,
                        'color': s.color
                    } for s in spreads
                ]
                
                # 6. Отладочный вывод (можно убрать после проверки)
                print(f"[Background] Обновлено: {len(prices)} бирж, {len(spreads)} спредов")
                
            except Exception as e:
                print(f"[BACKGROUND ERROR] Ошибка обновления: {e}")
        
        # Пауза между итерациями
        time.sleep(app_state['update_interval'] / 1000)

# Запуск фонового потока
price_thread = threading.Thread(target=background_price_updater, daemon=True)
price_thread.start()
print("[STARTUP] Фоновый поток для обновления цен запущен.")

# Инициализация автотрейдера (пока отключён)
# auto_trader = AutoTrader(exchange_manager, config)  # Раскомментировать при готовности

# ==================== МАРШРУТЫ АУТЕНТИФИКАЦИИ ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Неверное имя пользователя или пароль')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')

        if User.query.filter_by(username=username).first():
            flash('Имя пользователя уже существует')
            return render_template('login.html', show_register=True)

        if email and User.query.filter_by(email=email).first():
            flash('Email уже зарегистрирован')
            return render_template('login.html', show_register=True)

        user = User(username=username, email=email if email else None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for('index'))

    return render_template('login.html', show_register=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
    
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Страница восстановления пароля."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()

        if user:
            token = user.generate_reset_token()
            db.session.commit()
            flash(f'Токен для сброса: {token[:8]}... (проверьте почту для полной ссылки)')
        else:
            flash('Email не найден')

    return render_template('login.html', show_forgot=True)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Страница сброса пароля по токену."""
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.verify_reset_token(token):
        flash('Неверная или устаревшая ссылка для сброса')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form.get('password')
        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()
        flash('Пароль успешно обновлён')
        return redirect(url_for('login'))

    return render_template('login.html', show_reset=True, token=token)

# ==================== ОСНОВНЫЕ МАРШРУТЫ И API ====================
@app.route('/api/auto_trade/status', methods=['GET'])
@login_required
def get_auto_trade_status():
    status = auto_trader.get_status()
    return jsonify(status)

@app.route('/api/auto_trade/toggle', methods=['POST'])
@login_required
def toggle_auto_trade():
    if auto_trader.running:
        auto_trader.stop()
        return jsonify({'running': False, 'message': 'AutoTrader остановлен'})
    else:
        auto_trader.start()
        return jsonify({'running': True, 'message': 'AutoTrader запущен'})

@app.route('/')
@login_required
def index():
    """Главная страница с дашбордом."""
    return render_template('index.html',
        exchanges=config.get('exchanges', {}),
        trading_pairs=config.get('trading_pairs', []),
        thresholds=config.get('spread_thresholds', {}),
        colors=config.get('colors', {}),
        user=current_user
    )

@app.route('/api/state')
@login_required
def get_state():
    """API для получения текущего состояния приложения."""
    # ВАЖНО: Используем методы User из новой модели
    user_pairs = current_user.get_enabled_pairs() if current_user.is_authenticated else []
    user_exchanges = current_user.get_enabled_exchanges() if current_user.is_authenticated else []
    
    # Формируем состояние бирж
    exchanges_state = {}
    for ex_id, exchange_obj in exchange_manager.exchanges.items():
        exchanges_state[ex_id] = {
            'name': exchange_obj.config.get('name', ex_id),
            'enabled': exchange_obj.exchange is not None,
            'is_private': exchange_obj.exchange.apiKey is not None if exchange_obj.exchange else False
        }
    
    return jsonify({
        'paused': app_state['paused'],
        'update_interval': app_state['update_interval'],
        'selected_pairs': user_pairs or app_state['selected_pairs'],
        'enabled_exchanges': user_exchanges or app_state['enabled_exchanges'],
        'prices': app_state['prices'],
        'spreads': app_state['spreads'],
        'exchanges': exchanges_state,
        # 'health_report': app_state.get('health_report', {}),  # Раскомментировать, если метод get_all_statuses работает
        'user': {
            'username': current_user.username if current_user.is_authenticated else '',
            'email': current_user.email or ''
        } if current_user.is_authenticated else {}
    })

@app.route('/api/toggle_pause', methods=['POST'])
@login_required
def toggle_pause():
    """Включение/выключение паузы обновления."""
    app_state['paused'] = not app_state['paused']
    return jsonify({'paused': app_state['paused']})

@app.route('/api/set_interval', methods=['POST'])
@login_required
def set_interval():
    """Установка интервала обновления (в мс)."""
    data = request.get_json()
    interval = data.get('interval', 5000)
    app_state['update_interval'] = max(2000, min(30000, int(interval)))
    return jsonify({'update_interval': app_state['update_interval']})

# ==================== API ДЛЯ УПРАВЛЕНИЯ БИРЖАМИ (Exchange) ====================

@app.route('/api/exchanges', methods=['GET'])
@login_required
def get_exchanges():
    """Получение списка всех бирж из базы данных (НОВЫЙ формат)."""
    exchanges = Exchange.query.all()
    # Не включаем секретные ключи в ответ
    return jsonify([{
        'id': ex.id,
        'name': ex.name,
        'display_name': ex.display_name,
        'enabled': ex.enabled,
        'testnet': ex.testnet,
        'created_at': ex.created_at.isoformat() if ex.created_at else None
    } for ex in exchanges])

@app.route('/api/exchanges', methods=['POST'])
@login_required
def add_exchange():
    """Добавление новой биржи с API-ключами (НОВЫЙ формат)."""
    try:
        data = request.get_json()
        print(f"[DEBUG /api/exchanges] Получены данные: { {k: '***' if 'secret' in k.lower() or 'key' in k.lower() else v for k, v in data.items()} }")
        
        # Проверяем обязательные поля
        if not data.get('name'):
            return jsonify({'error': 'Поле "name" обязательно'}), 400
        
        # Проверяем, существует ли уже такая биржа
        existing = Exchange.query.filter_by(name=data.get('name').lower()).first()
        if existing:
            return jsonify({'error': 'Биржа с таким именем уже существует'}), 400
        
        # Создаём новую запись
        exchange = Exchange(
            name=data.get('name').lower(),
            display_name=data.get('display_name', data.get('name').upper()),
            enabled=data.get('enabled', True),
            testnet=data.get('testnet', False)
        )
        
        # Устанавливаем зашифрованные ключи (если переданы)
        if data.get('api_key'):
            exchange.set_api_key(data.get('api_key'))
        if data.get('api_secret'):
            exchange.set_api_secret(data.get('api_secret'))
        if data.get('password'):
            exchange.set_password(data.get('password'))
        
        db.session.add(exchange)
        db.session.commit()
        print(f"[DEBUG] Биржа {exchange.name} создана в БД (ID: {exchange.id})")
        
        # Пытаемся сразу активировать подключение
        if exchange.enabled:
            api_key = exchange.get_api_key()
            api_secret = exchange.get_api_secret()
            if api_key and api_secret:
                success = exchange_manager.set_exchange_credentials(
                    exchange.name,
                    api_key,
                    api_secret
                )
                status = "УСПЕХ" if success else "ПРОВАЛ"
                print(f"[DEBUG] Активация {exchange.name}: {status}")
        
        return jsonify({
            'id': exchange.id,
            'name': exchange.name,
            'enabled': exchange.enabled,
            'created_at': exchange.created_at.isoformat() if exchange.created_at else None
        }), 201
        
    except Exception as e:
        print(f"[ERROR /api/exchanges] Ошибка: {e}")
        return jsonify({'error': f'Внутренняя ошибка: {str(e)}'}), 500

# ==================== СОВМЕСТИМЫЕ РОУТЫ ДЛЯ СТАРОГО ФРОНТЕНДА ====================

@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    """Совместимый роут для фронтенда (старый формат ExchangeAccount)."""
    print("[DEBUG /api/accounts] Запрос списка аккаунтов (старый формат)")
    exchanges = Exchange.query.all()
    
    # Преобразуем Exchange в старый формат ExchangeAccount
    accounts = []
    for ex in exchanges:
        accounts.append({
            'id': ex.id,
            'exchange_id': ex.name,
            'name': ex.display_name,
            'is_active': ex.enabled,
            'api_key': '••••••••' if ex.get_api_key() else '',
            'api_secret': '••••••••' if ex.get_api_secret() else '',
            'passphrase': '••••••••' if ex.get_password() else '',
            'created_at': ex.created_at.isoformat() if ex.created_at else None,
            'updated_at': ex.updated_at.isoformat() if ex.updated_at else None
        })
    
    return jsonify(accounts)

@app.route('/api/accounts', methods=['POST'])
@login_required
def add_account():
    """Совместимый роут для добавления биржи (старый формат)."""
    try:
        data = request.get_json()
        print(f"[DEBUG /api/accounts] Старый формат, данные: { {k: '***' if 'secret' in k.lower() or 'key' in k.lower() else v for k, v in data.items()} }")
        
        # Проверяем обязательные поля
        if not data.get('exchange_id'):
            return jsonify({'error': 'Поле "exchange_id" обязательно'}), 400
        
        exchange_name = data.get('exchange_id').lower()
        
        # Проверяем, существует ли уже такая биржа
        existing = Exchange.query.filter_by(name=exchange_name).first()
        if existing:
            return jsonify({'error': 'Биржа с таким именем уже существует'}), 400
        
        # Создаём новую запись в новом формате
        exchange = Exchange(
            name=exchange_name,
            display_name=data.get('name', exchange_name.upper()),
            enabled=data.get('is_active', True),
            testnet=data.get('testnet', False)
        )
        
        # Устанавливаем ключи
        exchange.set_api_key(data.get('api_key', ''))
        exchange.set_api_secret(data.get('api_secret', ''))
        
        if data.get('passphrase'):
            exchange.set_password(data.get('passphrase'))
        
        db.session.add(exchange)
        db.session.commit()
        print(f"[DEBUG] Биржа {exchange.name} создана через /api/accounts (ID: {exchange.id})")
        
        # Активируем подключение
        if exchange.enabled:
            api_key = exchange.get_api_key()
            api_secret = exchange.get_api_secret()
            if api_key and api_secret:
                success = exchange_manager.set_exchange_credentials(
                    exchange.name,
                    api_key,
                    api_secret
                )
                print(f"[DEBUG] Активация {exchange.name}: {'УСПЕХ' if success else 'ПРОВАЛ'}")
        
        # Возвращаем в старом формате
        return jsonify({
            'id': exchange.id,
            'exchange_id': exchange.name,
            'name': exchange.display_name,
            'is_active': exchange.enabled,
            'api_key': '••••••••' if exchange.get_api_key() else '',
            'api_secret': '••••••••' if exchange.get_api_secret() else '',
            'passphrase': '••••••••' if exchange.get_password() else '',
            'created_at': exchange.created_at.isoformat() if exchange.created_at else None
        }), 201
        
    except Exception as e:
        print(f"[ERROR /api/accounts] Ошибка: {e}")
        return jsonify({'error': f'Внутренняя ошибка: {str(e)}'}), 500

@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def delete_account(account_id):
    """Удаление биржи (старый формат)."""
    exchange = Exchange.query.filter_by(id=account_id).first()
    if not exchange:
        return jsonify({'error': 'Биржа не найдена'}), 404
    
    db.session.delete(exchange)
    db.session.commit()
    print(f"[DEBUG] Биржа {exchange.name} удалена")
    return jsonify({'success': True})

@app.route('/api/accounts/<int:account_id>/toggle', methods=['POST'])
@login_required
def toggle_account(account_id):
    """Включение/выключение биржи (старый формат)."""
    exchange = Exchange.query.filter_by(id=account_id).first()
    if not exchange:
        return jsonify({'error': 'Биржа не найдена'}), 404
    
    exchange.enabled = not exchange.enabled
    db.session.commit()
    print(f"[DEBUG] Биржа {exchange.name} {'включена' if exchange.enabled else 'выключена'}")
    
    # Если включили - активируем ключи
    if exchange.enabled:
        api_key = exchange.get_api_key()
        api_secret = exchange.get_api_secret()
        if api_key and api_secret:
            exchange_manager.set_exchange_credentials(
                exchange.name,
                api_key,
                api_secret
            )
    
    return jsonify({'is_active': exchange.enabled})

@app.route('/api/connected_exchanges', methods=['GET'])
@login_required
def get_connected_exchanges():
    """Список подключенных бирж (старый формат)."""
    connected = []
    for ex_id, conn in exchange_manager.exchanges.items():
        if conn.exchange and conn.exchange.apiKey:  # Есть приватные ключи
            connected.append(ex_id)
    
    print(f"[DEBUG /api/connected_exchanges] Подключено: {connected}")
    return jsonify({'connected': connected})

# ==================== ДОПОЛНИТЕЛЬНЫЕ СОВМЕСТИМЫЕ РОУТЫ ====================

@app.route('/api/contracts', methods=['GET'])
@login_required
def get_contracts():
    """Заглушка для контрактов (старый фронтенд)."""
    return jsonify([])

@app.route('/api/auto_trade', methods=['GET'])
@login_required
def get_auto_trade():
    """Заглушка для автотрейдинга (старый фронтенд)."""
    return jsonify({'enabled': False, 'status': 'disabled'})
# ==================== API ДЛЯ ТОРГОВЫХ ПАР ====================

@app.route('/api/trading_pairs', methods=['GET'])
@login_required
def get_trading_pairs():
    """Получение списка торговых пар из базы."""
    pairs = TradingPair.query.order_by(TradingPair.priority.desc()).all()
    return jsonify([pair.to_dict() for pair in pairs])

@app.route('/api/trading_pairs/update', methods=['POST'])
@login_required
def update_selected_pairs():
    """Обновление выбранных для мониторинга торговых пар."""
    data = request.get_json()
    pairs = data.get('pairs', [])
    
    # Проверяем, что пары существуют в базе
    valid_pairs = []
    for pair_symbol in pairs:
        if TradingPair.query.filter_by(symbol=pair_symbol, enabled=True).first():
            valid_pairs.append(pair_symbol)
    
    app_state['selected_pairs'] = valid_pairs[:10]
    return jsonify({'selected_pairs': app_state['selected_pairs']})

# ==================== API ДЛЯ КОНФИГУРАЦИИ АРБИТРАЖА ====================

@app.route('/api/config/arbitrage', methods=['GET'])
@login_required
def get_arbitrage_config():
    """Получение текущей конфигурации арбитража."""
    config_record = ArbitrageConfig.query.filter_by(name='default').first()
    if not config_record:
        # Создаём конфигурацию по умолчанию
        config_record = ArbitrageConfig(name='default', description='Конфигурация по умолчанию')
        db.session.add(config_record)
        db.session.commit()
    
    return jsonify(config_record.to_dict())

@app.route('/api/config/arbitrage', methods=['PUT'])
@login_required
def update_arbitrage_config():
    """Обновление конфигурации арбитража."""
    data = request.get_json()
    config_record = ArbitrageConfig.query.filter_by(name='default').first_or_404()
    
    # Обновляем поля
    for key, value in data.items():
        if hasattr(config_record, key) and key not in ['id', 'created_at', 'updated_at']:
            setattr(config_record, key, value)
    
    config_record.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify(config_record.to_dict())

# ==================== ЗАПУСК ПРИЛОЖЕНИЯ ====================
# ==================== ВРЕМЕННЫЕ ЗАГЛУШКИ ДЛЯ ФРОНТЕНДА ====================

@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts_stub():
    """Временная заглушка для фронтенда."""
    return jsonify([])

@app.route('/api/connected_exchanges', methods=['GET'])
@login_required
def get_connected_exchanges_stub():
    """Временная заглушка для фронтенда."""
    return jsonify({'connected': []})

@app.route('/api/contracts', methods=['GET'])
@login_required
def get_contracts_stub():
    """Временная заглушка для фронтенда."""
    return jsonify([])

@app.route('/api/auto_trade', methods=['GET'])
@login_required
def get_auto_trade_stub():
    """Временная заглушка для фронтенда."""
    return jsonify({'enabled': False, 'status': 'disabled'})

@app.route('/api/accounts', methods=['POST'])
@login_required
def add_account_stub():
    """Временная заглушка для фронтенда."""
    return jsonify({'error': 'API временно недоступен'}), 400
@app.route('/api/available_pairs')
@login_required
def get_available_pairs():
    """Получение списка доступных торговых пар."""
    exchanges_param = request.args.get('exchanges', '')
    selected_exchanges = [ex.strip() for ex in exchanges_param.split(',') if ex.strip()]

    if not selected_exchanges:
        return jsonify({'pairs': []})

    available_pairs = set()
    prices = app_state.get('prices', {})
    trading_pairs = config.get('trading_pairs', [])

    for pair in trading_pairs:
        for ex in selected_exchanges:
            if prices.get(ex, {}).get(pair):
                available_pairs.add(pair)
                break

    return jsonify({'pairs': list(available_pairs)})
if __name__ == '__main__':
    print(f"[STARTUP] SpreadMaster запускается...")
    print(f"[STARTUP] Доступные биржи: {list(exchange_manager.exchanges.keys())}")
    print(f"[STARTUP] Мониторинг пар: {app_state['selected_pairs']}")
    print(f"[STARTUP] Веб-интерфейс доступен по адресу: http://127.0.0.1:5000")
    
    auto_trader.start()
    print("[STARTUP] AutoTrader запущен")
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)