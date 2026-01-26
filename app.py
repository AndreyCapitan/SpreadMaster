"""
SpreadMaster - Основной файл приложения для арбитражного мониторинга
"""

import os
import json
import time
import threading
import traceback
from datetime import datetime, timedelta

from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from exchanges import ExchangeManager
from spread_calculator import SpreadCalculator, StochasticCalculator
from models import db, User, Exchange, ExchangeApiKey, ExchangeBalance, ExchangePing, ArbitrageConfig, TradingPair, TradeLog, AutoTradeSettings
from auto_trader import AutoTrader

# ==================== ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ ====================

app = Flask(__name__)

# Конфигурация приложения
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///' + os.path.join(os.path.dirname(__file__), 'spreadmaster.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24).hex())

# Инициализация расширений
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== ЗАГРУЗКА КОНФИГУРАЦИИ ====================

try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    print("[STARTUP] Конфигурационный файл config.json загружен.")
except FileNotFoundError:
    print("[ERROR] Файл config.json не найден.")
    config = {}
except json.JSONDecodeError as e:
    print(f"[ERROR] Ошибка в формате config.json: {e}")
    config = {}

# ==================== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ====================

def init_database():
    """Инициализация базы данных и создание стандартных записей"""
    with app.app_context():
        # Создание всех таблиц
        db.create_all()
        print("[STARTUP] Таблицы базы данных созданы.")
        
        # Инициализация стандартных данных
        from models import init_default_data
        init_default_data()
        print("[STARTUP] Базовая конфигурация проверена.")
        
        # Инициализация бирж из конфига
        init_exchanges_from_config()
        
        # Создание тестового пользователя, если нет пользователей
        if User.query.count() == 0:
            test_user = User(
                username='admin',
                email='admin@spreadmaster.com',
                role='admin'
            )
            test_user.set_password('admin123')
            db.session.add(test_user)
            db.session.commit()
            print("[STARTUP] Создан тестовый пользователь: admin/admin123")

def init_exchanges_from_config():
    """Создание записей бирж в БД из конфигурационного файла"""
    if 'exchanges' not in config:
        return
    
    added_count = 0
    for ex_name, ex_config in config['exchanges'].items():
        if ex_config.get('enabled', True):
            exchange = Exchange.query.filter_by(name=ex_name).first()
            if not exchange:
                exchange = Exchange(
                    name=ex_name,
                    display_name=ex_name.upper(),
                    enabled=True,
                    is_public=True,
                    created_at=datetime.utcnow()
                )
                db.session.add(exchange)
                added_count += 1
                print(f"[INIT] Добавлена биржа: {ex_name}")
    
    if added_count > 0:
        try:
            db.session.commit()
            print(f"[INIT] В БД добавлено {added_count} бирж из конфига")
        except Exception as e:
            db.session.rollback()
            print(f"[INIT] Ошибка добавления бирж: {e}")

# Выполняем инициализацию БД
init_database()

# ==================== ИНИЦИАЛИЗАЦИЯ КОМПОНЕНТОВ ====================

exchange_manager = ExchangeManager(config)
spread_calculator = SpreadCalculator(
    config.get('spread_thresholds', {}),
    config.get('colors', {})
)
stochastic_calculator = StochasticCalculator(**config.get('stochastic_settings', {}))
auto_trader = AutoTrader(app, db, ExchangeManager, SpreadCalculator)

# ==================== АКТИВАЦИЯ API-КЛЮЧЕЙ ====================

print("[STARTUP] Запуск активации API-ключей из БД...")
with app.app_context():
    exchanges_in_db = Exchange.query.filter_by(enabled=True).all()
    print(f"[STARTUP] Найдено {len(exchanges_in_db)} активных бирж в БД.")

    for exchange_record in exchanges_in_db:
        # Ищем API ключи для этой биржи
        api_record = ExchangeApiKey.query.filter_by(
            exchange_name=exchange_record.name
        ).first()
        
        if api_record and api_record.api_key and api_record.api_secret:
            success = exchange_manager.set_exchange_credentials(
                exchange_record.name,
                api_record.api_key,
                api_record.api_secret
            )
            status = "УСПЕХ" if success else "ПРОВАЛ"
            print(f"[STARTUP] Активированы ключи для {exchange_record.name}: {status}")
        else:
            # Публичное подключение без ключей
            print(f"[STARTUP] Публичное подключение к {exchange_record.name}")

print("[STARTUP] Активация ключей завершена.")

# ==================== ГЛОБАЛЬНОЕ СОСТОЯНИЕ ====================

app_state = {
    'paused': False,
    'update_interval': config.get('update_interval', 5000),
    'selected_pairs': config.get('monitoring', {}).get('pairs_to_monitor', ['BTC/USDT', 'ETH/USDT']),
    'enabled_exchanges': [ex for ex, cfg in config.get('exchanges', {}).items() if cfg.get('enabled', True)],
    'prices': {},
    'spreads': [],
    'exchange_statuses': {},
    'last_update': datetime.utcnow()
}

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

def background_price_updater():
    """Фоновая задача для обновления цен и спредов"""
    print("[BACKGROUND] Фоновый поток ЗАПУЩЕН")
    iteration = 0
    
    while True:
        iteration += 1
        time_str = datetime.now().strftime("%H:%M:%S")
        
        if not app_state['paused']:
            try:
                print(f"[BACKGROUND #{iteration}] Запрос цен ({time_str})...")
                
                # Получаем цены со всех бирж
                prices = exchange_manager.fetch_all_prices(app_state['selected_pairs'])
                
                # Рассчитываем спреды
                spreads = spread_calculator.calculate_spreads(prices, app_state['selected_pairs'])
                
                # Сохраняем в глобальное состояние
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
                        'color': s.color,
                        'timestamp': datetime.utcnow().isoformat()
                    } for s in spreads
                ]
                
                app_state['last_update'] = datetime.utcnow()
                app_state['prices'] = {
                    ex_id: {
                        pair: {
                            'bid': ticker.bid if ticker else None,
                            'ask': ticker.ask if ticker else None,
                            'last': ticker.last if ticker else None
                        } for pair, ticker in tickers.items()
                    } for ex_id, tickers in prices.items()
                }
                
                # Логируем обновление
                active_spreads = len([s for s in spreads if s.spread_percent > 0.1])
                print(f"[Background] Обновлено: {len(prices)} бирж, {len(spreads)} спредов ({active_spreads} активных)")
                
            except Exception as e:
                print(f"[BACKGROUND ERROR] Ошибка обновления: {e}")
                traceback.print_exc()
        
        # Пауза между итерациями
        time.sleep(app_state['update_interval'] / 1000)

def background_status_updater():
    """Фоновая задача для обновления статуса бирж и балансов"""
    print("[STATUS BACKGROUND] Фоновый поток статусов ЗАПУЩЕН")
    
    while True:
        try:
            with app.app_context():
                # Обновляем статусы всех бирж
                for ex_name, exchange_conn in exchange_manager.exchanges.items():
                    if exchange_conn.exchange:
                        # Обновляем пинг
                        ping = exchange_conn.measure_ping()
                        
                        # Получаем статус здоровья
                        health = exchange_conn.get_health_status()
                        
                        # Обновляем статус в глобальном состоянии
                        app_state['exchange_statuses'][ex_name] = {
                            'ping': ping,
                            'is_healthy': health['is_healthy'],
                            'last_error': health['last_error'],
                            'last_checked': datetime.utcnow().isoformat(),
                            'has_api_keys': exchange_conn.exchange.apiKey is not None
                        }
                        
                        # Если есть API ключи, пытаемся получить баланс
                        if exchange_conn.exchange.apiKey:
                            try:
                                balance = exchange_conn.fetch_balance()
                                if balance and 'total' in balance:
                                    # Сохраняем основные балансы
                                    important_assets = ['USDT', 'BTC', 'ETH', 'BNB']
                                    asset_balances = {}
                                    
                                    for asset in important_assets:
                                        if asset in balance['total']:
                                            total = balance['total'].get(asset, 0)
                                            free = balance['free'].get(asset, 0)
                                            if total > 0:
                                                asset_balances[asset] = {
                                                    'total': round(total, 4),
                                                    'free': round(free, 4),
                                                    'used': round(total - free, 4)
                                                }
                                    
                                    if asset_balances:
                                        app_state['exchange_statuses'][ex_name]['balances'] = asset_balances
                            except Exception as e:
                                # Не логируем ошибки баланса, чтобы не засорять логи
                                pass
            
            # Обновляем каждые 30 секунд
            time.sleep(30)
            
        except Exception as e:
            print(f"[STATUS BACKGROUND ERROR] Ошибка обновления статусов: {e}")
            time.sleep(60)

# Запуск фоновых потоков
price_thread = threading.Thread(target=background_price_updater, daemon=True)
price_thread.start()

status_thread = threading.Thread(target=background_status_updater, daemon=True)
status_thread.start()

print("[STARTUP] Фоновые потоки запущены.")

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
            login_user(user, remember=True)
            flash('Вход выполнен успешно', 'success')
            return redirect(url_for('index'))
        flash('Неверное имя пользователя или пароль', 'error')

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
            flash('Имя пользователя уже существует', 'error')
            return render_template('login.html', show_register=True)

        if email and User.query.filter_by(email=email).first():
            flash('Email уже зарегистрирован', 'error')
            return render_template('login.html', show_register=True)

        user = User(username=username, email=email if email else None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash('Регистрация прошла успешно', 'success')
        return redirect(url_for('index'))

    return render_template('login.html', show_register=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
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
            flash('Email не найден', 'error')

    return render_template('login.html', show_forgot=True)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Страница сброса пароля по токену."""
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.verify_reset_token(token):
        flash('Неверная или устаревшая ссылка для сброса', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form.get('password')
        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()
        flash('Пароль успешно обновлён', 'success')
        return redirect(url_for('login'))

    return render_template('login.html', show_reset=True, token=token)

# ==================== ОСНОВНЫЕ МАРШРУТЫ ====================

@app.route('/')
@login_required
def index():
    """Главная страница с дашбордом"""
    all_pairs = config.get('monitoring', {}).get('pairs_to_monitor', [])
    return render_template('index.html',
        pairs=all_pairs[:20],  # Первые 20 пар для отображения
        total_pairs=len(all_pairs),
        user=current_user,
        config=config
    )

@app.route('/settings')
@login_required
def settings():
    """Страница настроек бирж"""
    with app.app_context():
        # Получаем все биржи из БД
        exchanges_from_db = Exchange.query.order_by(Exchange.name).all()
        
        # Собираем информацию о каждой бирже
        exchanges_info = []
        for ex in exchanges_from_db:
            # Статус из менеджера
            status_info = app_state['exchange_statuses'].get(ex.name, {})
            
            # API ключи
            api_key = ExchangeApiKey.query.filter_by(exchange_name=ex.name).first()
            
            # Поддерживаемые пары из конфига
            supported_pairs = []
            if ex.name in config.get('exchanges', {}):
                supported = config['exchanges'][ex.name].get('supported_pairs', [])
                if supported:
                    supported_pairs = supported
                else:
                    # Берем первые 5 пар из общего списка
                    supported_pairs = config.get('monitoring', {}).get('pairs_to_monitor', [])[:5]
            
            exchanges_info.append({
                'id': ex.id,
                'name': ex.name,
                'display_name': ex.display_name or ex.name.upper(),
                'enabled': ex.enabled,
                'has_api_keys': api_key is not None,
                'ping': status_info.get('ping', 0),
                'is_healthy': status_info.get('is_healthy', False),
                'balances': status_info.get('balances', {}),
                'last_error': status_info.get('last_error', ''),
                'supported_pairs': supported_pairs[:8],  # Первые 8 пар для отображения
                'total_pairs': len(supported_pairs),
                'last_checked': status_info.get('last_checked', '')
            })
    
    return render_template('settings.html',
        exchanges=exchanges_info,
        all_pairs=config.get('monitoring', {}).get('pairs_to_monitor', []),
        config=config,
        user=current_user
    )

@app.route('/arbitrage')
@login_required
def arbitrage():
    """Страница арбитражных возможностей"""
    return render_template('arbitrage.html',
        spreads=app_state['spreads'][:50],  # Последние 50 спредов
        user=current_user
    )

# ==================== API МАРШРУТЫ ====================

@app.route('/api/state')
@login_required
def get_state():
    """Получение текущего состояния приложения"""
    return jsonify({
        'paused': app_state['paused'],
        'update_interval': app_state['update_interval'],
        'selected_pairs': app_state['selected_pairs'],
        'enabled_exchanges': app_state['enabled_exchanges'],
        'spreads_count': len(app_state['spreads']),
        'last_update': app_state['last_update'].isoformat() if isinstance(app_state['last_update'], datetime) else app_state['last_update'],
        'exchange_statuses': app_state['exchange_statuses'],
        'user': {
            'username': current_user.username,
            'email': current_user.email or '',
            'role': current_user.role
        }
    })

@app.route('/api/spreads')
@login_required
def get_spreads():
    """Получение текущих спредов"""
    return jsonify(app_state['spreads'])

@app.route('/api/exchanges/status')
@login_required
def get_exchanges_status():
    """Получение статуса всех бирж"""
    return jsonify(app_state['exchange_statuses'])

@app.route('/api/toggle_pause', methods=['POST'])
@login_required
def toggle_pause():
    """Включение/выключение паузы"""
    app_state['paused'] = not app_state['paused']
    return jsonify({'paused': app_state['paused']})

@app.route('/api/set_interval', methods=['POST'])
@login_required
def set_interval():
    """Установка интервала обновления"""
    data = request.get_json()
    interval = data.get('interval', 5000)
    app_state['update_interval'] = max(2000, min(30000, int(interval)))
    return jsonify({'update_interval': app_state['update_interval']})

@app.route('/api/exchanges', methods=['GET'])
@login_required
def get_exchanges():
    """Получение списка всех бирж"""
    exchanges = Exchange.query.all()
    return jsonify([{
        'id': ex.id,
        'name': ex.name,
        'display_name': ex.display_name or ex.name.upper(),
        'enabled': ex.enabled,
        'created_at': ex.created_at.isoformat() if ex.created_at else None
    } for ex in exchanges])

@app.route('/api/exchange/<exchange_name>/ping', methods=['GET'])
@login_required
def ping_exchange(exchange_name):
    """Проверка пинга до биржи"""
    exchange = exchange_manager.get_exchange(exchange_name)
    if exchange:
        ping = exchange.measure_ping()
        return jsonify({
            'exchange': exchange_name,
            'ping': ping,
            'timestamp': datetime.utcnow().isoformat()
        })
    return jsonify({'error': 'Биржа не найдена'}), 404

@app.route('/api/exchange/<exchange_name>/balance', methods=['GET'])
@login_required
def get_exchange_balance(exchange_name):
    """Получение баланса биржи"""
    exchange = exchange_manager.get_exchange(exchange_name)
    if exchange and exchange.exchange and exchange.exchange.apiKey:
        try:
            balance = exchange.fetch_balance()
            if balance:
                # Фильтруем только активы с ненулевым балансом
                nonzero_balances = {
                    asset: {
                        'total': round(amount, 4),
                        'free': round(balance.get('free', {}).get(asset, 0), 4),
                        'used': round(balance.get('used', {}).get(asset, 0), 4)
                    }
                    for asset, amount in balance.get('total', {}).items()
                    if amount > 0.0001
                }
                return jsonify({
                    'exchange': exchange_name,
                    'balances': nonzero_balances,
                    'timestamp': datetime.utcnow().isoformat()
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Баланс недоступен'}), 404

@app.route('/api/pairs', methods=['GET'])
@login_required
def get_pairs():
    """Получение списка всех торговых пар"""
    all_pairs = config.get('monitoring', {}).get('pairs_to_monitor', [])
    return jsonify({
        'pairs': all_pairs,
        'count': len(all_pairs)
    })

# ==================== API УПРАВЛЕНИЯ БИРЖАМИ ====================

@app.route('/api/exchanges', methods=['POST'])
@login_required
def add_exchange_api():
    """Добавление новой биржи с API-ключами"""
    try:
        data = request.get_json()
        
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
        
        # Сохраняем API ключи, если они предоставлены
        if data.get('api_key') and data.get('api_secret'):
            api_key = ExchangeApiKey(
                user_id=current_user.id,
                exchange_name=data.get('name').lower(),
                api_key=data.get('api_key'),
                api_secret=data.get('api_secret'),
                label=data.get('label', ''),
                is_active=True
            )
            db.session.add(api_key)
            
            # Активируем ключи в менеджере
            exchange_manager.set_exchange_credentials(
                data.get('name').lower(),
                data.get('api_key'),
                data.get('api_secret')
            )
        
        db.session.add(exchange)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Биржа {data.get("name")} успешно добавлена',
            'exchange': {
                'id': exchange.id,
                'name': exchange.name,
                'display_name': exchange.display_name
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/exchange/<int:exchange_id>', methods=['PUT'])
@login_required
def update_exchange(exchange_id):
    """Обновление настроек биржи"""
    try:
        exchange = Exchange.query.get_or_404(exchange_id)
        data = request.get_json()
        
        if 'enabled' in data:
            exchange.enabled = data['enabled']
            
        if 'display_name' in data:
            exchange.display_name = data['display_name']
            
        # Обновляем API ключи, если они предоставлены
        if 'api_key' in data or 'api_secret' in data:
            api_key = ExchangeApiKey.query.filter_by(
                exchange_name=exchange.name,
                user_id=current_user.id
            ).first()
            
            if not api_key:
                api_key = ExchangeApiKey(
                    user_id=current_user.id,
                    exchange_name=exchange.name,
                    api_key=data.get('api_key', ''),
                    api_secret=data.get('api_secret', ''),
                    label=data.get('label', ''),
                    is_active=True
                )
                db.session.add(api_key)
            else:
                if 'api_key' in data:
                    api_key.api_key = data['api_key']
                if 'api_secret' in data:
                    api_key.api_secret = data['api_secret']
                if 'label' in data:
                    api_key.label = data['label']
            
            # Активируем обновленные ключи
            exchange_manager.set_exchange_credentials(
                exchange.name,
                data.get('api_key', api_key.api_key),
                data.get('api_secret', api_key.api_secret)
            )
        
        exchange.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Настройки биржи обновлены'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==================== НОВЫЕ API ДЛЯ УПРАВЛЕНИЯ ====================

@app.route('/api/settings/pairs', methods=['POST'])
@login_required
def update_pairs_settings():
    """Обновление настроек пар пользователя"""
    try:
        data = request.get_json()
        user_id = current_user.id
        
        # Сохраняем настройки в БД или сессии
        # Временное решение - сохраняем в сессии
        session['enabled_pairs'] = data.get('enabled_pairs', [])
        session['enabled_exchanges'] = data.get('enabled_exchanges', [])
        
        # Обновляем глобальное состояние
        app_state['selected_pairs'] = session.get('enabled_pairs', 
            config.get('monitoring', {}).get('pairs_to_monitor', []))
        app_state['enabled_exchanges'] = session.get('enabled_exchanges',
            app_state['enabled_exchanges'])
        
        return jsonify({'success': True, 'message': 'Настройки сохранены'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/api_key', methods=['POST'])
@login_required
def save_api_key():
    """Сохранение API ключей для биржи"""
    try:
        data = request.get_json()
        exchange_name = data.get('exchange_name')
        api_key = data.get('api_key')
        api_secret = data.get('api_secret')
        
        if not all([exchange_name, api_key, api_secret]):
            return jsonify({'error': 'Все поля обязательны'}), 400
        
        # Сохраняем в БД
        api_record = ExchangeApiKey.query.filter_by(
            exchange_name=exchange_name,
            user_id=current_user.id
        ).first()
        
        if api_record:
            api_record.api_key = api_key
            api_record.api_secret = api_secret
            api_record.updated_at = datetime.utcnow()
        else:
            api_record = ExchangeApiKey(
                user_id=current_user.id,
                exchange_name=exchange_name,
                api_key=api_key,
                api_secret=api_secret,
                label=f'Ключ для {exchange_name}',
                is_active=True
            )
            db.session.add(api_record)
        
        db.session.commit()
        
        # Активируем ключи в менеджере
        exchange_manager.set_exchange_credentials(exchange_name, api_key, api_secret)
        
        return jsonify({'success': True, 'message': 'API ключи сохранены'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==================== ЗАПУСК СЕРВЕРА ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("SpreadMaster запускается...")
    print(f"Доступные биржи: {list(exchange_manager.exchanges.keys())}")
    
    pairs = config.get('monitoring', {}).get('pairs_to_monitor', ['BTC/USDT', 'ETH/USDT'])
    print(f"Мониторинг пар: {pairs[:5]}{'...' if len(pairs) > 5 else ''}")
    print(f"Всего пар: {len(pairs)}")
    
    print(f"Веб-интерфейс доступен по адресу: http://127.0.0.1:5000")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)