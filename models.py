import json
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

# ==================== МОДЕЛЬ ПОЛЬЗОВАТЕЛЯ ====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)

    # Настройки пользователя
    auto_trade_enabled = db.Column(db.Boolean, default=False)
    auto_trade_settings = db.Column(db.Text, default='{}')  # JSON настройки

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self, length=32):
        import secrets
        self.reset_token = secrets.token_hex(length)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
        return self.reset_token

    def verify_reset_token(self, token):
        if self.reset_token == token and self.reset_token_expiry > datetime.utcnow():
            return True
        return False

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expiry = None

    def get_enabled_pairs(self):
        # Возвращает список пар, которые пользователь хочет мониторить
        # Пока возвращаем все пары из конфига, но можно сделать настройку на пользователя
        return []

    def get_enabled_exchanges(self):
        # Возвращает список бирж, которые пользователь хочет использовать
        # Пока возвращаем все биржи из конфига, но можно сделать настройку на пользователя
        return []

    def __repr__(self):
        return f'<User {self.username}>'

# ==================== МОДЕЛЬ БИРЖИ ====================

class Exchange(db.Model):
    __tablename__ = 'exchanges'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # bitget, mexc, etc.
    display_name = db.Column(db.String(100), nullable=True)
    enabled = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)  # Публичный доступ без ключей
    testnet = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Поля для API ключей (опционально, можно хранить в отдельной таблице)
    api_key = db.Column(db.String(255), nullable=True)
    api_secret = db.Column(db.String(255), nullable=True)

    def get_api_key(self):
        return self.api_key

    def get_api_secret(self):
        return self.api_secret

    def __repr__(self):
        return f'<Exchange {self.name}>'

# ==================== МОДЕЛЬ API КЛЮЧЕЙ БИРЖИ ====================

class ExchangeApiKey(db.Model):
    __tablename__ = 'exchange_api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exchange_name = db.Column(db.String(50), nullable=False)  # bitget, mexc, etc.
    api_key = db.Column(db.String(255), nullable=False)
    api_secret = db.Column(db.String(255), nullable=False)
    label = db.Column(db.String(100))  # Произвольная метка для ключа
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связь с пользователем
    user = db.relationship('User', backref=db.backref('exchange_api_keys', lazy=True))

    def __repr__(self):
        return f'<ExchangeApiKey {self.exchange_name} for user {self.user_id}>'

    # Метод для безопасного отображения (например, в логах)
    def masked_key(self):
        if self.api_key:
            return self.api_key[:4] + '...' + self.api_key[-4:]
        return ''

    def masked_secret(self):
        if self.api_secret:
            return self.api_secret[:4] + '...' + self.api_secret[-4:]
        return ''

# ==================== МОДЕЛЬ БАЛАНСА БИРЖИ ====================

class ExchangeBalance(db.Model):
    __tablename__ = 'exchange_balances'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exchange_name = db.Column(db.String(50), nullable=False)
    asset = db.Column(db.String(20), nullable=False)  # BTC, USDT, etc.
    free = db.Column(db.Float, default=0.0)
    used = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    # Связь с пользователем
    user = db.relationship('User', backref=db.backref('exchange_balances', lazy=True))

    def __repr__(self):
        return f'<ExchangeBalance {self.exchange_name}:{self.asset} free={self.free} used={self.used}>'

# ==================== МОДЕЛЬ ПИНГА БИРЖИ ====================

class ExchangePing(db.Model):
    __tablename__ = 'exchange_pings'

    id = db.Column(db.Integer, primary_key=True)
    exchange_name = db.Column(db.String(50), nullable=False)
    ping_ms = db.Column(db.Float, nullable=False)  # Пинг в миллисекундах
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ExchangePing {self.exchange_name}: {self.ping_ms}ms at {self.checked_at}>'

# ==================== МОДЕЛЬ КОНФИГУРАЦИИ АРБИТРАЖА ====================

class ArbitrageConfig(db.Model):
    __tablename__ = 'arbitrage_configs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    pair = db.Column(db.String(20), nullable=False)  # BTC/USDT
    min_spread = db.Column(db.Float, default=0.5)  # Минимальный спред для арбитража
    max_spread = db.Column(db.Float, default=5.0)  # Максимальный спред для арбитража
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('arbitrage_configs', lazy=True))

    def __repr__(self):
        return f'<ArbitrageConfig {self.pair} for user {self.user_id}>'

# ==================== МОДЕЛЬ ТОРГОВОЙ ПАРЫ ====================

class TradingPair(db.Model):
    __tablename__ = 'trading_pairs'

    id = db.Column(db.Integer, primary_key=True)
    pair = db.Column(db.String(20), unique=True, nullable=False)  # BTC/USDT
    base_asset = db.Column(db.String(10), nullable=False)  # BTC
    quote_asset = db.Column(db.String(10), nullable=False)  # USDT
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<TradingPair {self.pair}>'

# ==================== МОДЕЛЬ ЛОГА ТОРГОВЛИ ====================

class TradeLog(db.Model):
    __tablename__ = 'trade_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exchange_buy = db.Column(db.String(50), nullable=False)
    exchange_sell = db.Column(db.String(50), nullable=False)
    pair = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    price_buy = db.Column(db.Float, nullable=False)
    price_sell = db.Column(db.Float, nullable=False)
    spread = db.Column(db.Float, nullable=False)
    profit = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='completed')  # completed, failed, pending
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('trade_logs', lazy=True))

    def __repr__(self):
        return f'<TradeLog {self.pair} profit={self.profit}>'

# ==================== МОДЕЛЬ НАСТРОЕК АВТОТРЕЙДИНГА ====================

class AutoTradeSettings(db.Model):
    __tablename__ = 'autotrade_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Настройки торговли
    auto_enabled = db.Column(db.Boolean, default=False)
    trade_amount = db.Column(db.Float, default=0.0)
    min_spread = db.Column(db.Float, default=0.0)
    target_profit = db.Column(db.Float, default=0.0)
    max_loss = db.Column(db.Float, default=0.0)
    
    # Торговые пары и биржи
    trade_pairs = db.Column(db.String(500), default='[]')  # JSON список пар
    exchanges = db.Column(db.String(500), default='[]')    # JSON список бирж
    
    # Интервалы и лимиты
    check_interval = db.Column(db.Integer, default=60)  # секунды
    max_open_orders = db.Column(db.Integer, default=5)
    
    # Риск-менеджмент
    use_stop_loss = db.Column(db.Boolean, default=True)
    use_take_profit = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связь с пользователем
    user = db.relationship('User', backref=db.backref('autotrade_settings', lazy=True))
    
    def __repr__(self):
        return f'<AutoTradeSettings {self.id} User:{self.user_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'auto_enabled': self.auto_enabled,
            'trade_amount': self.trade_amount,
            'min_spread': self.min_spread,
            'target_profit': self.target_profit,
            'max_loss': self.max_loss,
            'trade_pairs': json.loads(self.trade_pairs),
            'exchanges': json.loads(self.exchanges),
            'check_interval': self.check_interval,
            'max_open_orders': self.max_open_orders,
            'use_stop_loss': self.use_stop_loss,
            'use_take_profit': self.use_take_profit
        }

# ==================== ФУНКЦИЯ ИНИЦИАЛИЗАЦИИ БАЗОВЫХ ДАННЫХ ====================

def init_default_data():
    """Инициализация базовых данных в базе данных"""
    # Добавление бирж, если их нет
    exchanges = ['bitget', 'mexc', 'bybit', 'okx', 'binance', 'bingx', 'kucoin']
    
    for ex in exchanges:
        if not Exchange.query.filter_by(name=ex).first():
            exchange = Exchange(
                name=ex,
                display_name=ex.upper(),
                enabled=True,
                is_public=True,
                created_at=datetime.utcnow()
            )
            db.session.add(exchange)
            print(f"[INIT] Добавлена биржа: {ex}")
    
    # Добавление торговых пар, если их нет
    pairs = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT',
             'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'DOGE/USDT', 'MATIC/USDT',
             'LINK/USDT', 'LTC/USDT', 'UNI/USDT', 'ATOM/USDT', 'FIL/USDT']
    
    for pair in pairs:
        if not TradingPair.query.filter_by(pair=pair).first():
            base, quote = pair.split('/')
            trading_pair = TradingPair(
                pair=pair,
                base_asset=base,
                quote_asset=quote,
                enabled=True,
                created_at=datetime.utcnow()
            )
            db.session.add(trading_pair)
            print(f"[INIT] Добавлена пара: {pair}")
    
    try:
        db.session.commit()
        print(f"[INIT] В БД добавлено {len(exchanges)} бирж и {len(pairs)} торговых пар")
    except Exception as e:
        db.session.rollback()
        print(f"[INIT] Ошибка инициализации данных: {e}")