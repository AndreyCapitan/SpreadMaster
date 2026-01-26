import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Создаем минимальное приложение, аналогичное app.py
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'temporary-secret-key-for-db-creation'

# Создаем отдельный экземпляр SQLAlchemy
db = SQLAlchemy(app)

# Определяем модели прямо здесь, чтобы избежать импорта из app.py
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120))
    password_hash = db.Column(db.String(200))
    enabled_exchanges = db.Column(db.Text, default='')
    enabled_pairs = db.Column(db.Text, default='')
    update_interval = db.Column(db.Integer, default=1000)
    reset_token = db.Column(db.String(100))

class ExchangeAccount(db.Model):
    __tablename__ = 'exchange_account'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    exchange_id = db.Column(db.String(50))
    name = db.Column(db.String(100))
    api_key_encrypted = db.Column(db.Text)
    api_secret_encrypted = db.Column(db.Text)
    passphrase_encrypted = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

class Contract(db.Model):
    __tablename__ = 'contract'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    contract_key = db.Column(db.String(100))
    pair = db.Column(db.String(20))
    buy_exchange = db.Column(db.String(50))
    sell_exchange = db.Column(db.String(50))
    entry_spread = db.Column(db.Float)
    current_spread = db.Column(db.Float)
    auto_close = db.Column(db.Boolean, default=False)
    close_threshold = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    open_time = db.Column(db.DateTime)
    close_time = db.Column(db.DateTime)

# Создаем таблицы
with app.app_context():
    db.create_all()
    print("✅ База данных 'app.db' успешно создана!")
    print("   Созданы таблицы: user, exchange_account, contract")