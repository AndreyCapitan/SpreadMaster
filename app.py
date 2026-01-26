import os
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import json
import threading
import time
#from openai import OpenAI
from exchanges import ExchangeManager
from spread_calculator import SpreadCalculator, StochasticCalculator
from models import db, ExchangeAccount, UserSettings, User, Contract, AutoTradeSettings
from datetime import datetime

#ai_client = OpenAI(
#    api_key=os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY"),
#   base_url=os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
#)

app = Flask(__name__)
# Настройки базы данных - ОДНА строка URI
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(os.path.dirname(__file__), 'app.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24).hex())

# Инициализация расширений
db.init_app(app)  # <-- Теперь эта строка выполнится без ошибки

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
#db.init_app(app)

with app.app_context():
    db.create_all()
    print("[STARTUP] Таблицы базы данных созданы (если не существовали).")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with open('config.json', 'r') as f:
    config = json.load(f)

exchange_manager = ExchangeManager(config)
spread_calculator = SpreadCalculator(
    config.get('spread_thresholds', {}),
    config.get('colors', {})
)
stochastic_calculator = StochasticCalculator(**config.get('stochastic_settings', {}))

# ============= НАЧАЛО НОВОГО КОДА ДЛЯ АКТИВАЦИИ КЛЮЧЕЙ =============
# Этот код загружает активные ключи из базы данных при запуске приложения
print("[STARTUP] Запуск активации сохранённых API-ключей из БД...")
with app.app_context():
    # Импортируем модель здесь, чтобы избежать циклических зависимостей
    from models import ExchangeAccount
    active_accounts = ExchangeAccount.query.filter_by(is_active=True).all()
    print(f"[STARTUP] Найдено {len(active_accounts)} активных ключей в БД.")
    
    for account in active_accounts:
        print(f"[STARTUP] Пробую активировать ключ для биржи: {account.exchange_id}")
        # Получаем расшифрованные ключи из модели
        creds = account.get_credentials()
        if creds and creds.get('api_key'):
            success = exchange_manager.set_exchange_credentials(
                account.exchange_id,
                creds['api_key'],
                creds['api_secret']
            )
            status = "УСПЕХ" if success else "ПРОВАЛ"
            print(f"[STARTUP] Результат активации {account.exchange_id}: {status}")
        else:
            print(f"[STARTUP] Не удалось получить ключи для {account.exchange_id} из БД.")
print("[STARTUP] Завершение активации ключей.")
# ============= КОНЕЦ НОВОГО КОДА =============

app_state = {
    'paused': False,
    'update_interval': config.get('update_interval_ms', 1000),
    'selected_pairs': config.get('trading_pairs', [])[:5],
    'enabled_exchanges': list(config.get('exchanges', {}).keys()),
    'prices': {},
    'spreads': []
}


def update_prices():
    global app_state
    while True:
        if not app_state['paused']:
            try:
                prices = exchange_manager.fetch_all_prices(app_state['selected_pairs'])
                app_state['prices'] = {
                    ex: {
                        pair: {
                            'bid': t.bid,
                            'ask': t.ask,
                            'last': t.last,
                            'timestamp': t.timestamp
                        } for pair, t in tickers.items()
                    } for ex, tickers in prices.items()
                }
                
                spreads = spread_calculator.calculate_spreads(prices, app_state['selected_pairs'])
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
            except Exception as e:
                print(f"Update error: {e}")
        
        time.sleep(app_state['update_interval'] / 1000)


from auto_trader import AutoTrader

auto_trader = None



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
        flash('Invalid username or password')
    
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
            flash('Username already exists')
            return render_template('login.html', show_register=True)
        
        if email and User.query.filter_by(email=email).first():
            flash('Email already registered')
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
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            token = user.generate_reset_token()
            db.session.commit()
            flash(f'Reset token: {token[:8]}... (check email for full link)')
        else:
            flash('Email not found')
    
    return render_template('login.html', show_forgot=True)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or not user.verify_reset_token(token):
        flash('Invalid or expired reset link')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()
        flash('Password updated successfully')
        return redirect(url_for('login'))
    
    return render_template('login.html', show_reset=True, token=token)


@app.route('/')
@login_required
def index():
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
    exchanges_state = {}
    for ex_id, exchange in exchange_manager.exchanges.items():
        exchanges_state[ex_id] = {
            'name': exchange.config.get('name', exchange.config.get('id', 'Unknown')),
            'enabled': exchange.exchange is not None
        }
    
    user_exchanges = current_user.get_enabled_exchanges()
    user_pairs = current_user.get_enabled_pairs()
    
    return jsonify({
        'paused': app_state['paused'],
        'update_interval': current_user.update_interval,
        'selected_pairs': user_pairs,
        'enabled_exchanges': user_exchanges,
        'prices': app_state['prices'],
        'spreads': app_state['spreads'],
        'exchanges': exchanges_state,
        'user': {
            'username': current_user.username,
            'email': current_user.email or ''
        }
    })


@app.route('/api/toggle_pause', methods=['POST'])
@login_required
def toggle_pause():
    app_state['paused'] = not app_state['paused']
    return jsonify({'paused': app_state['paused']})


@app.route('/api/set_interval', methods=['POST'])
@login_required
def set_interval():
    data = request.json
    interval = data.get('interval', 1000)
    app_state['update_interval'] = max(500, min(10000, interval))
    return jsonify({'update_interval': app_state['update_interval']})


@app.route('/api/available_pairs')
@login_required
def get_available_pairs():
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


@app.route('/api/toggle_exchange', methods=['POST'])
@login_required
def toggle_exchange():
    data = request.json
    exchange_id = data.get('exchange_id')
    enabled = data.get('enabled', True)
    # УДАЛЕНО: exchange_manager.set_exchange_enabled(exchange_id, enabled)

    user_exchanges = current_user.get_enabled_exchanges()
    if enabled and exchange_id not in user_exchanges:
        user_exchanges.append(exchange_id)
    elif not enabled and exchange_id in user_exchanges:
        user_exchanges.remove(exchange_id)

    current_user.enabled_exchanges = ','.join(user_exchanges)
    db.session.commit()

    return jsonify({'success': True, 'enabled_exchanges': user_exchanges})

@app.route('/api/toggle_pair', methods=['POST'])
@login_required
def toggle_pair():
    data = request.json
    pair = data.get('pair')
    user_pairs = current_user.get_enabled_pairs()
    
    if pair in user_pairs:
        user_pairs.remove(pair)
    else:
        user_pairs.append(pair)
    
    current_user.enabled_pairs = ','.join(user_pairs)
    db.session.commit()
    
    return jsonify({'selected_pairs': user_pairs})


@app.route('/api/user/email', methods=['POST'])
@login_required
def update_email():
    data = request.json
    email = data.get('email', '').strip()
    
    if email and User.query.filter(User.email == email, User.id != current_user.id).first():
        return jsonify({'error': 'Email already in use'}), 400
    
    current_user.email = email if email else None
    db.session.commit()
    return jsonify({'success': True, 'email': current_user.email or ''})


@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    accounts = ExchangeAccount.query.filter_by(user_id=current_user.id).all()
    return jsonify([a.to_dict() for a in accounts])


@app.route('/api/connected_exchanges', methods=['GET'])
@login_required
def get_connected_exchanges():
    accounts = ExchangeAccount.query.filter_by(user_id=current_user.id, is_active=True).all()
    connected = list(set([a.exchange_id for a in accounts]))
    return jsonify({'connected': connected})


@app.route('/api/accounts', methods=['POST'])
@login_required
def add_account():
    data = request.json
    account = ExchangeAccount(
        user_id=current_user.id,
        exchange_id=data.get('exchange_id'),
        name=data.get('name')
    )
    account.set_credentials(
        api_key=data.get('api_key'),
        api_secret=data.get('api_secret'),
        passphrase=data.get('passphrase')
    )
    db.session.add(account)
    db.session.commit()
    return jsonify(account.to_dict())


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def delete_account(account_id):
    account = ExchangeAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    db.session.delete(account)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/accounts/<int:account_id>/toggle', methods=['POST'])
@login_required
def toggle_account(account_id):
    account = ExchangeAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    account.is_active = not account.is_active
    db.session.commit()
    return jsonify(account.to_dict())


@app.route('/api/stochastic/<exchange>/<path:pair>')
@login_required
def get_stochastic(exchange, pair):
    interval = request.args.get('interval', '15m')
    limit = int(request.args.get('limit', 100))
    
    ex = exchange_manager.get_exchange(exchange)
    if not ex:
        return jsonify({'error': 'Exchange not found'}), 404
    
    klines = ex.get_klines(pair, interval, limit)
    if not klines:
        return jsonify({'error': 'No data available'}), 404
    
    result = stochastic_calculator.calculate(klines)
    return jsonify({
        'pair': pair,
        'exchange': exchange,
        'interval': interval,
        'stochastic': result
    })


@app.route('/api/contracts', methods=['GET'])
@login_required
def get_contracts():
    active = Contract.query.filter_by(user_id=current_user.id, is_active=True).order_by(Contract.open_time.desc()).all()
    limit = request.args.get('limit', 100, type=int)
    closed = Contract.query.filter_by(user_id=current_user.id, is_active=False).order_by(Contract.close_time.desc()).limit(limit).all()
    return jsonify({
        'active': [c.to_dict() for c in active],
        'closed': [c.to_dict() for c in closed]
    })


@app.route('/api/contracts', methods=['POST'])
@login_required
def save_contract():
    data = request.json
    existing = Contract.query.filter_by(
        user_id=current_user.id, 
        contract_key=data.get('key'),
        is_active=True
    ).first()
    
    if existing:
        existing.current_spread = data.get('currentSpread', existing.current_spread)
        existing.auto_close = data.get('autoClose', existing.auto_close)
        existing.close_threshold = data.get('closeThreshold', existing.close_threshold)
    else:
        existing = Contract(
            user_id=current_user.id,
            contract_key=data.get('key'),
            pair=data.get('pair'),
            buy_exchange=data.get('buyEx'),
            sell_exchange=data.get('sellEx'),
            entry_spread=data.get('entrySpread'),
            current_spread=data.get('currentSpread', data.get('entrySpread')),
            auto_close=data.get('autoClose', False),
            close_threshold=data.get('closeThreshold', 0),
            open_time=datetime.fromisoformat(data.get('openTime')) if data.get('openTime') else datetime.utcnow()
        )
        db.session.add(existing)
    
    db.session.commit()
    return jsonify(existing.to_dict())


@app.route('/api/contracts/<int:contract_id>/close', methods=['POST'])
@login_required
def close_contract_api(contract_id):
    contract = Contract.query.filter_by(id=contract_id, user_id=current_user.id).first_or_404()
    data = request.json
    
    contract.is_active = False
    contract.current_spread = data.get('currentSpread', contract.current_spread)
    contract.profit = contract.entry_spread - contract.current_spread
    contract.close_time = datetime.utcnow()
    
    db.session.commit()
    return jsonify(contract.to_dict())


@app.route('/api/contracts/close-by-key', methods=['POST'])
@login_required
def close_contract_by_key():
    data = request.json
    contract = Contract.query.filter_by(
        user_id=current_user.id, 
        contract_key=data.get('key'),
        is_active=True
    ).first()
    
    if contract:
        contract.is_active = False
        contract.current_spread = data.get('currentSpread', contract.current_spread)
        contract.profit = contract.entry_spread - contract.current_spread
        contract.close_time = datetime.utcnow()
        db.session.commit()
        return jsonify(contract.to_dict())
    
    return jsonify({'error': 'Contract not found'}), 404


@app.route('/api/auto_trade', methods=['GET'])
@login_required
def get_auto_trade_settings():
    settings = AutoTradeSettings.query.filter_by(user_id=current_user.id).first()
    if not settings:
        settings = AutoTradeSettings(
            user_id=current_user.id,
            auto_enabled=False,
            open_threshold=0.5,
            close_threshold=0.1,
            max_contracts=5
        )
        db.session.add(settings)
        db.session.commit()
    return jsonify(settings.to_dict())


@app.route('/api/auto_trade', methods=['POST'])
@login_required
def update_auto_trade_settings():
    data = request.json
    settings = AutoTradeSettings.query.filter_by(user_id=current_user.id).first()
    
    if not settings:
        settings = AutoTradeSettings(user_id=current_user.id)
        db.session.add(settings)
    
    if 'auto_enabled' in data:
        settings.auto_enabled = data['auto_enabled']
    if 'open_threshold' in data:
        settings.open_threshold = float(data['open_threshold'])
    if 'close_threshold' in data:
        settings.close_threshold = float(data['close_threshold'])
    if 'max_contracts' in data:
        settings.max_contracts = int(data['max_contracts'])
    if 'bank_percent' in data:
        settings.bank_percent = int(data['bank_percent'])
    
    db.session.commit()
    return jsonify(settings.to_dict())


@app.route('/api/contracts/history', methods=['DELETE'])
@login_required
def clear_contract_history():
    Contract.query.filter_by(user_id=current_user.id, is_active=False).delete()
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/ai/chat', methods=['POST'])
@login_required
def ai_chat():
    try:
        data = request.json
        message = data.get('message', '')
        context = data.get('context', {})
        
        system_prompt = """Ты полезный помощник для торговой платформы спред-арбитража.
        Помогаешь пользователям понимать спред-торговлю между криптобиржами.
        Отвечай кратко (2-3 предложения максимум). Будь практичным и полезным.
        Всегда отвечай на русском языке.
        Пользователь отслеживает спреды цен между биржами для арбитражных возможностей."""
        
        context_info = f"Current context: {context.get('activeContracts', 0)} active contracts, mode: {context.get('mode', 'demo')}"
        
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{context_info}\n\nUser question: {message}"}
            ],
            max_tokens=150
        )
        
        return jsonify({'response': response.choices[0].message.content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/strategy', methods=['POST'])
@login_required
def ai_strategy():
    try:
        data = request.json
        spreads = data.get('spreads', [])
        active_contracts = data.get('activeContracts', [])
        settings = data.get('settings', {})
        
        spread_summary = ""
        if spreads:
            top_spreads = sorted(spreads, key=lambda x: abs(x[1]) if len(x) > 1 else 0, reverse=True)[:5]
            spread_summary = f"Top spreads: {top_spreads}"
        
        contract_summary = ""
        if active_contracts:
            total_profit = sum(c.get('profit', 0) for c in active_contracts)
            contract_summary = f"Active contracts: {len(active_contracts)}, total profit: {total_profit:.3f}%"
        
        system_prompt = """Ты AI-стратег для спред-трейдинга. Всегда отвечай на русском языке.
        Анализируй текущие рыночные условия и предлагай оптимальные настройки.
        Будь краток (3-4 предложения). Предлагай конкретные значения порогов.
        
        Рекомендации:
        - Выше open_threshold (0.3-0.8%) = более избирательные входы
        - Ниже close_threshold (0.05-0.2%) = более точные выходы  
        - max_contracts зависит от риска (обычно 3-10)
        
        Дай краткую рекомендацию по стратегии с конкретными числами."""
        
        user_prompt = f"""Current settings: open_threshold={settings.get('autoEntryThreshold', 0.5)}%, 
        close_threshold={settings.get('autoCloseThreshold', 0.1)}%, 
        max_contracts={settings.get('maxContracts', 5)}
        
        {spread_summary}
        {contract_summary}
        
        Analyze and suggest optimal strategy."""
        
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=200
        )
        
        strategy_text = response.choices[0].message.content
        
        suggestions = None
        if spreads and len(spreads) > 0:
            avg_spread = sum(abs(s[1]) for s in spreads if len(s) > 1) / max(len(spreads), 1)
            if avg_spread > 0:
                suggestions = {
                    'openThreshold': round(min(max(avg_spread * 0.7, 0.2), 1.0), 2),
                    'closeThreshold': round(min(max(avg_spread * 0.2, 0.05), 0.3), 2),
                    'maxContracts': 5 if avg_spread < 0.5 else 3
                }
        
        return jsonify({
            'strategy': strategy_text,
            'suggestions': suggestions
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


update_thread = threading.Thread(target=update_prices, daemon=True)
update_thread.start()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        auto_trader = AutoTrader(app, db, exchange_manager, spread_calculator)
        auto_trader.start()
    app.run(debug=False)