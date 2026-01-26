"""
Модели базы данных для SpreadMaster с безопасным хранением API-ключей
и расширенной конфигурацией арбитража.
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import base64
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


# ==================== УТИЛИТЫ ШИФРОВАНИЯ ====================

def get_encryption_key(secret_key: str) -> bytes:
    """
    Генерирует ключ шифрования из Flask secret key.
    Использует PBKDF2 для безопасного преобразования.
    """
    salt = b'spreadmaster_salt_'
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return key


# ==================== МОДЕЛЬ ПОЛЬЗОВАТЕЛЯ ====================

class User(db.Model, UserMixin):
    """Модель пользователя для аутентификации через Flask-Login."""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Настройки пользователя
    enabled_exchanges = db.Column(db.Text, default='')
    enabled_pairs = db.Column(db.Text, default='')
    update_interval = db.Column(db.Integer, default=5000)
    
    # Токен для сброса пароля
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password: str):
        """Установка хэша пароля."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Проверка пароля."""
        return check_password_hash(self.password_hash, password)
    
    def generate_reset_token(self, expires_in: int = 3600) -> str:
        """Генерация токена для сброса пароля."""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
        return self.reset_token
    
    def verify_reset_token(self, token: str) -> bool:
        """Проверка токена сброса пароля."""
        if (self.reset_token == token and 
            self.reset_token_expiry and 
            self.reset_token_expiry > datetime.utcnow()):
            return True
        return False
    
    def clear_reset_token(self):
        """Очистка токена сброса пароля."""
        self.reset_token = None
        self.reset_token_expiry = None
    
    def get_enabled_exchanges(self) -> list:
        """Получение списка включённых бирж пользователя."""
        if not self.enabled_exchanges:
            return []
        return [ex.strip() for ex in self.enabled_exchanges.split(',') if ex.strip()]
    
    def get_enabled_pairs(self) -> list:
        """Получение списка включённых торговых пар пользователя."""
        if not self.enabled_pairs:
            return []
        return [pair.strip() for pair in self.enabled_pairs.split(',') if pair.strip()]
    
    def to_dict(self) -> dict:
        """Сериализация пользователя в словарь."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'enabled_exchanges': self.get_enabled_exchanges(),
            'enabled_pairs': self.get_enabled_pairs(),
            'update_interval': self.update_interval,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


# ==================== МОДЕЛЬ БИРЖИ ====================

class Exchange(db.Model):
    """Модель для хранения настроек бирж с шифрованием API-ключей."""
    
    __tablename__ = 'exchanges'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    display_name = db.Column(db.String(100), nullable=False)
    api_key_encrypted = db.Column(db.Text, nullable=True)
    api_secret_encrypted = db.Column(db.Text, nullable=True)
    password_encrypted = db.Column(db.Text, nullable=True)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Настройки конкретной биржи
    testnet = db.Column(db.Boolean, default=False)
    rate_limit = db.Column(db.Integer, default=1000)
    timeout = db.Column(db.Integer, default=30000)
    
    def __init__(self, *args, **kwargs):
        """Инициализация с автоматическим шифрованием ключей."""
        api_key = kwargs.pop('api_key', None)
        api_secret = kwargs.pop('api_secret', None)
        password = kwargs.pop('password', None)
        
        super().__init__(*args, **kwargs)
        
        if api_key:
            self.set_api_key(api_key)
        if api_secret:
            self.set_api_secret(api_secret)
        if password:
            self.set_password(password)
    
    @property
    def cipher(self):
        """Возвращает объект шифрования."""
        from flask import current_app
        secret_key = current_app.config.get('SECRET_KEY')
        
        if not secret_key:
            raise ValueError("SECRET_KEY не установлен в конфигурации Flask")
        
        encryption_key = get_encryption_key(secret_key)
        return Fernet(encryption_key)
    
    def set_api_key(self, api_key: str):
        """Шифрование и сохранение API ключа."""
        if not api_key:
            self.api_key_encrypted = None
            return
        
        try:
            self.api_key_encrypted = self.cipher.encrypt(api_key.encode()).decode()
        except Exception as e:
            from flask import current_app
            if current_app.config.get('DEBUG'):
                self.api_key_encrypted = api_key
            else:
                raise ValueError(f"Ошибка шифрования API ключа: {e}")
    
    def get_api_key(self) -> str:
        """Расшифровка API ключа."""
        if not self.api_key_encrypted:
            return ""
        
        try:
            if not self.api_key_encrypted.startswith('gAAA'):
                return self.api_key_encrypted
            
            decrypted = self.cipher.decrypt(self.api_key_encrypted.encode())
            return decrypted.decode()
        except Exception:
            return ""
    
    def set_api_secret(self, api_secret: str):
        """Шифрование и сохранение API секрета."""
        if not api_secret:
            self.api_secret_encrypted = None
            return
        
        try:
            self.api_secret_encrypted = self.cipher.encrypt(api_secret.encode()).decode()
        except Exception as e:
            from flask import current_app
            if current_app.config.get('DEBUG'):
                self.api_secret_encrypted = api_secret
            else:
                raise ValueError(f"Ошибка шифрования API секрета: {e}")
    
    def get_api_secret(self) -> str:
        """Расшифровка API секрета."""
        if not self.api_secret_encrypted:
            return ""
        
        try:
            if not self.api_secret_encrypted.startswith('gAAA'):
                return self.api_secret_encrypted
            
            decrypted = self.cipher.decrypt(self.api_secret_encrypted.encode())
            return decrypted.decode()
        except Exception:
            return ""
    
    def set_password(self, password: str):
        """Шифрование и сохранение пароля."""
        if not password:
            self.password_encrypted = None
            return
        
        try:
            self.password_encrypted = self.cipher.encrypt(password.encode()).decode()
        except Exception as e:
            from flask import current_app
            if current_app.config.get('DEBUG'):
                self.password_encrypted = password
            else:
                raise ValueError(f"Ошибка шифрования пароля: {e}")
    
    def get_password(self) -> str:
        """Расшифровка пароля."""
        if not self.password_encrypted:
            return ""
        
        try:
            if not self.password_encrypted.startswith('gAAA'):
                return self.password_encrypted
            
            decrypted = self.cipher.decrypt(self.password_encrypted.encode())
            return decrypted.decode()
        except Exception:
            return ""
    
    def to_dict(self, include_secrets: bool = False) -> dict:
        """Сериализация объекта в словарь."""
        data = {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'enabled': self.enabled,
            'testnet': self.testnet,
            'rate_limit': self.rate_limit,
            'timeout': self.timeout,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_secrets:
            data.update({
                'api_key': self.get_api_key(),
                'api_secret': '••••••••' if self.get_api_secret() else '',
                'password': '••••••••' if self.get_password() else ''
            })
        
        return data
    
    def __repr__(self):
        return f"<Exchange {self.name} ({'enabled' if self.enabled else 'disabled'})>"


# ==================== КОНФИГУРАЦИЯ АРБИТРАЖА ====================

class ArbitrageConfig(db.Model):
    """Модель для хранения настроек арбитражной стратегии."""
    
    __tablename__ = 'arbitrage_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    
    # Пороги арбитража
    open_threshold = db.Column(db.Float, default=1.5)
    close_threshold = db.Column(db.Float, default=0.3)
    min_spread = db.Column(db.Float, default=0.1)
    max_spread = db.Column(db.Float, default=10.0)
    
    # Таймауты и интервалы
    update_interval = db.Column(db.Integer, default=5)
    order_timeout = db.Column(db.Integer, default=30)
    recovery_delay = db.Column(db.Integer, default=60)
    
    # Риск-менеджмент
    max_position_size = db.Column(db.Float, default=0.1)
    stop_loss_threshold = db.Column(db.Float, default=2.0)
    take_profit_threshold = db.Column(db.Float, default=1.0)
    
    # Дополнительные настройки
    enable_telegram_alerts = db.Column(db.Boolean, default=False)
    telegram_chat_id = db.Column(db.String(50), nullable=True)
    telegram_bot_token_encrypted = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def to_dict(self) -> dict:
        """Сериализация объекта в словарь."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'open_threshold': self.open_threshold,
            'close_threshold': self.close_threshold,
            'min_spread': self.min_spread,
            'max_spread': self.max_spread,
            'update_interval': self.update_interval,
            'order_timeout': self.order_timeout,
            'recovery_delay': self.recovery_delay,
            'max_position_size': self.max_position_size,
            'stop_loss_threshold': self.stop_loss_threshold,
            'take_profit_threshold': self.take_profit_threshold,
            'enable_telegram_alerts': self.enable_telegram_alerts,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ==================== ТОРГОВЫЕ ПАРЫ ====================

class TradingPair(db.Model):
    """Модель для хранения торговых пар и их настроек."""
    
    __tablename__ = 'trading_pairs'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(50), nullable=False, unique=True)
    base_asset = db.Column(db.String(20), nullable=False)
    quote_asset = db.Column(db.String(20), nullable=False)
    
    # Настройки для этой пары
    enabled = db.Column(db.Boolean, default=True)
    min_amount = db.Column(db.Float, default=0.001)
    max_amount = db.Column(db.Float, default=10.0)
    precision = db.Column(db.Integer, default=8)
    
    # Приоритет (чем выше, тем важнее)
    priority = db.Column(db.Integer, default=1)
    
    # Категория пары
    category = db.Column(db.String(50), default='major')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Сериализация объекта в словарь."""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'base_asset': self.base_asset,
            'quote_asset': self.quote_asset,
            'enabled': self.enabled,
            'min_amount': self.min_amount,
            'max_amount': self.max_amount,
            'precision': self.precision,
            'priority': self.priority,
            'category': self.category,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def get_enabled_pairs(cls):
        """Получить все активные торговые пары."""
        return cls.query.filter_by(enabled=True).order_by(cls.priority.desc()).all()
    
    @classmethod
    def get_major_pairs(cls):
        """Получить только основные пары."""
        return cls.query.filter_by(enabled=True, category='major').order_by(cls.priority.desc()).all()


# ==================== ЛОГИ СДЕЛОК ====================

class TradeLog(db.Model):
    """Модель для логирования всех сделок."""
    
    __tablename__ = 'trade_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Информация о сделке
    pair = db.Column(db.String(50), nullable=False)
    exchange_buy = db.Column(db.String(50), nullable=False)
    exchange_sell = db.Column(db.String(50), nullable=False)
    
    # Цены и объемы
    buy_price = db.Column(db.Float, nullable=False)
    sell_price = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    
    # Результат
    spread_percent = db.Column(db.Float, nullable=False)
    profit = db.Column(db.Float, nullable=False)
    profit_percent = db.Column(db.Float, nullable=False)
    
    # Комиссии
    fee_buy = db.Column(db.Float, default=0.0)
    fee_sell = db.Column(db.Float, default=0.0)
    fee_total = db.Column(db.Float, default=0.0)
    
    # Время
    execution_time = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Статус
    status = db.Column(db.String(20), default='completed')
    
    # ID ордеров на биржах
    order_id_buy = db.Column(db.String(100), nullable=True)
    order_id_sell = db.Column(db.String(100), nullable=True)
    
    # Дополнительная информация
    notes = db.Column(db.Text, nullable=True)
    
    def to_dict(self) -> dict:
        """Сериализация объекта в словарь."""
        return {
            'id': self.id,
            'pair': self.pair,
            'exchange_buy': self.exchange_buy,
            'exchange_sell': self.exchange_sell,
            'buy_price': self.buy_price,
            'sell_price': self.sell_price,
            'amount': self.amount,
            'spread_percent': self.spread_percent,
            'profit': self.profit,
            'profit_percent': self.profit_percent,
            'fee_buy': self.fee_buy,
            'fee_sell': self.fee_sell,
            'fee_total': self.fee_total,
            'execution_time': self.execution_time,
            'status': self.status,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'notes': self.notes
        }


# ==================== ИНИЦИАЛИЗАЦИЯ ДАННЫХ ====================

def init_default_data():
    """Инициализация базовых данных при первом запуске."""
    # Конфигурация арбитража по умолчанию
    default_config = ArbitrageConfig.query.filter_by(name='default').first()
    if not default_config:
        default_config = ArbitrageConfig(
            name='default',
            description='Конфигурация арбитража по умолчанию'
        )
        db.session.add(default_config)
    
    # Основные торговые пары
    major_pairs = [
        ('BTC/USDT', 'BTC', 'USDT', 'major', 10),
        ('ETH/USDT', 'ETH', 'USDT', 'major', 9),
        ('BNB/USDT', 'BNB', 'USDT', 'major', 8),
        ('SOL/USDT', 'SOL', 'USDT', 'major', 7),
        ('XRP/USDT', 'XRP', 'USDT', 'major', 6),
        ('ADA/USDT', 'ADA', 'USDT', 'major', 5),
        ('AVAX/USDT', 'AVAX', 'USDT', 'major', 4),
        ('DOT/USDT', 'DOT', 'USDT', 'major', 3),
        ('MATIC/USDT', 'MATIC', 'USDT', 'major', 2),
        ('LINK/USDT', 'LINK', 'USDT', 'major', 1),
    ]
    
    for symbol, base, quote, category, priority in major_pairs:
        pair = TradingPair.query.filter_by(symbol=symbol).first()
        if not pair:
            pair = TradingPair(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
                category=category,
                priority=priority
            )
            db.session.add(pair)
    
    # Тестовый пользователь
    if User.query.count() == 0:
        test_user = User(
            username='admin',
            email='admin@example.com'
        )
        test_user.set_password('admin')
        db.session.add(test_user)
    
    db.session.commit()


# Для обратной совместимости с существующим кодом
ExchangeConfig = Exchange