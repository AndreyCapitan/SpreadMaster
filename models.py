import os
import base64
import secrets
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def get_encryption_key():
    secret = os.environ.get('FLASK_SECRET_KEY', 'spreadmaster-dev-key')
    salt = b'spreadmaster_salt'
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return Fernet(key)


def encrypt_value(value: str) -> str:
    if not value:
        return ''
    f = get_encryption_key()
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    if not encrypted:
        return ''
    f = get_encryption_key()
    return f.decrypt(encrypted.encode()).decode()


class ExchangeAccount(db.Model):
    __tablename__ = 'exchange_accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exchange_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    api_key_encrypted = db.Column(db.String(512), nullable=False)
    api_secret_encrypted = db.Column(db.String(512), nullable=False)
    passphrase_encrypted = db.Column(db.String(512), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_credentials(self, api_key: str, api_secret: str, passphrase: str | None = None):
        self.api_key_encrypted = encrypt_value(api_key)
        self.api_secret_encrypted = encrypt_value(api_secret)
        if passphrase:
            self.passphrase_encrypted = encrypt_value(passphrase)
    
    def get_api_key(self) -> str:
        return decrypt_value(self.api_key_encrypted)
    
    def get_api_secret(self) -> str:
        return decrypt_value(self.api_secret_encrypted)
    
    def get_passphrase(self) -> str | None:
        return decrypt_value(self.passphrase_encrypted) if self.passphrase_encrypted else None
    
    def to_dict(self):
        api_key = self.get_api_key()
        return {
            'id': self.id,
            'exchange_id': self.exchange_id,
            'name': self.name,
            'api_key_masked': api_key[:4] + '****' + api_key[-4:] if len(api_key) > 8 else '****',
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat()
        }


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    enabled_exchanges = db.Column(db.Text, default='binance,bybit,okx,htx,kucoin,gateio,mexc,kraken,bitget')
    enabled_pairs = db.Column(db.Text, default='BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,DOGE/USDT')
    update_interval = db.Column(db.Integer, default=1000)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        from datetime import timedelta
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token
    
    def verify_reset_token(self, token):
        if self.reset_token != token:
            return False
        if self.reset_token_expires and datetime.utcnow() > self.reset_token_expires:
            return False
        return True
    
    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expires = None
    
    def get_enabled_exchanges(self):
        return self.enabled_exchanges.split(',') if self.enabled_exchanges else []
    
    def get_enabled_pairs(self):
        return self.enabled_pairs.split(',') if self.enabled_pairs else []


class UserSettings(db.Model):
    __tablename__ = 'user_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    enabled_exchanges = db.Column(db.Text, default='')
    enabled_pairs = db.Column(db.Text, default='')
    update_interval = db.Column(db.Integer, default=1000)


class AutoTradeSettings(db.Model):
    __tablename__ = 'auto_trade_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    auto_enabled = db.Column(db.Boolean, default=False)
    open_threshold = db.Column(db.Float, default=0.5)
    close_threshold = db.Column(db.Float, default=0.1)
    max_contracts = db.Column(db.Integer, default=5)
    bank_percent = db.Column(db.Integer, default=10)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'auto_enabled': self.auto_enabled,
            'open_threshold': self.open_threshold,
            'close_threshold': self.close_threshold,
            'max_contracts': self.max_contracts,
            'bank_percent': self.bank_percent
        }


class Contract(db.Model):
    __tablename__ = 'contracts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contract_key = db.Column(db.String(200), nullable=False)
    pair = db.Column(db.String(50), nullable=False)
    buy_exchange = db.Column(db.String(50), nullable=False)
    sell_exchange = db.Column(db.String(50), nullable=False)
    entry_spread = db.Column(db.Float, nullable=False)
    current_spread = db.Column(db.Float, nullable=False)
    auto_close = db.Column(db.Boolean, default=False)
    close_threshold = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    profit = db.Column(db.Float, nullable=True)
    open_time = db.Column(db.DateTime, default=datetime.utcnow)
    close_time = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.contract_key,
            'pair': self.pair,
            'buyEx': self.buy_exchange,
            'sellEx': self.sell_exchange,
            'entrySpread': self.entry_spread,
            'currentSpread': self.current_spread,
            'autoClose': self.auto_close,
            'closeThreshold': self.close_threshold,
            'isActive': self.is_active,
            'profit': self.profit,
            'openTime': self.open_time.isoformat() if self.open_time else None,
            'closeTime': self.close_time.isoformat() if self.close_time else None
        }
