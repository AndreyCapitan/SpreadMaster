import ccxt
import json
import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# Настраиваем логирование, чтобы ВИДЕТЬ ошибки
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TickerData:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: int

@dataclass
class ExchangeConnection:
    """Объект для управления одним подключением к бирже."""
    config: dict
    exchange: Optional[ccxt.Exchange] = None
    last_ping: Optional[float] = None

    def connect(self, api_key: str = '', api_secret: str = '') -> bool:
        """Создаёт и проверяет подключение к бирже."""
        try:
            exchange_id = self.config['id']
            exchange_class = getattr(ccxt, exchange_id)
            
            # Конфигурация подключения
            exchange_config = {
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
                **self.config.get('ccxt_overrides', {})
            }
            
            # Удаляем пустые ключи, если они не были введены (для публичного доступа)
            if not api_key:
                exchange_config.pop('apiKey', None)
                exchange_config.pop('secret', None)
                logger.info(f"Создано ПУБЛИЧНОЕ подключение к {exchange_id}")
            else:
                logger.info(f"Создано ПРИВАТНОЕ подключение к {exchange_id} (с ключами API)")
            
            self.exchange = exchange_class(exchange_config)
            self.exchange.load_markets()
            logger.info(f"Подключение к {exchange_id} успешно. Доступно пар: {len(self.exchange.markets)}")
            return True
            
        except ccxt.AuthenticationError as e:
            logger.error(f"ОШИБКА АВТОРИЗАЦИИ на {self.config['id']}: Неверные ключи API.")
            return False
        except ccxt.NetworkError as e:
            logger.error(f"СЕТЕВАЯ ОШИБКА при подключении к {self.config['id']}: {e}")
            return False
        except Exception as e:
            logger.error(f"КРИТИЧЕСКАЯ ОШИБКА при создании биржи {self.config['id']}: {e}")
            return False

    def fetch_ticker(self, symbol: str) -> Optional[TickerData]:
        """Запрашивает тикер для указанной торговой пары."""
        if not self.exchange:
            logger.warning(f"Попытка запроса тикера без подключения к {self.config['id']}")
            return None
            
        try:
            # Приводим символ к формату биржи (например, BTC/USDT -> BTCUSDT)
            market_symbol = self.exchange.market_id(symbol) if hasattr(self.exchange, 'market_id') else symbol
            ticker = self.exchange.fetch_ticker(market_symbol)
            
            return TickerData(
                symbol=symbol,
                bid=ticker['bid'],
                ask=ticker['ask'],
                last=ticker['last'],
                timestamp=ticker['timestamp']
            )
        except Exception as e:
            logger.error(f"Ошибка при запросе тикера {symbol} с {self.config['id']}: {e}")
            return None

    def fetch_balance(self) -> Optional[Dict]:
        """Запрашивает баланс с биржи. Работает только с приватными ключами."""
        if not self.exchange:
            return None
            
        if not self.exchange.apiKey:
            logger.warning(f"Запрос баланса невозможен: нет приватных ключей для {self.config['id']}")
            return None
            
        try:
            balance = self.exchange.fetch_balance()
            # Фильтруем только ненулевые балансы для читаемости
            non_zero = {currency: total for currency, total in balance['total'].items() if total > 0}
            logger.info(f"Баланс на {self.config['id']}: {non_zero}")
            return non_zero
        except Exception as e:
            logger.error(f"Ошибка при запросе баланса с {self.config['id']}: {e}")
            return None

    def measure_ping(self) -> Optional[float]:
        """Измеряет пинг (задержку) до сервера биржи в миллисекундах."""
        if not self.exchange:
            return None
            
        try:
            start_time = time.time()
            # Используем простой публичный запрос для измерения времени
            self.exchange.fetch_time()
            end_time = time.time()
            
            ping_ms = round((end_time - start_time) * 1000, 2)
            self.last_ping = ping_ms
            logger.info(f"Пинг до {self.config['id']}: {ping_ms} мс")
            return ping_ms
        except Exception as e:
            logger.error(f"Ошибка при измерении пинга до {self.config['id']}: {e}")
            return None

class ExchangeManager:
    """Управляет подключениями ко всем биржам."""
    
    def __init__(self, config: dict):
        self.config = config
        self.exchanges: Dict[str, ExchangeConnection] = {}
        self._initialize_exchanges()
        
    def _initialize_exchanges(self):
        """Инициализирует все биржи из конфигурации в режиме публичного доступа."""
        exchanges_config = self.config.get('exchanges', {})
        for ex_id, ex_config in exchanges_config.items():
            # Копируем конфиг и добавляем идентификатор
            connection_config = {**ex_config, 'id': ex_id}
            connection = ExchangeConnection(connection_config)
            
            # Пробуем подключиться в публичном режиме (без ключей)
            if connection.connect():
                self.exchanges[ex_id] = connection
                logger.info(f"Биржа {ex_id} готова к работе.")
            else:
                logger.warning(f"Биржа {ex_id} пропущена из-за ошибки инициализации.")
    
    def get_exchange(self, exchange_id: str) -> Optional[ExchangeConnection]:
        """Возвращает объект подключения к бирже по её ID."""
        return self.exchanges.get(exchange_id)
    
    def set_exchange_credentials(self, exchange_id: str, api_key: str, api_secret: str) -> bool:
        """Обновляет биржу для работы с приватными ключами (для торговли)."""
        if exchange_id not in self.exchanges:
            logger.error(f"Биржа {exchange_id} не найдена для установки ключей.")
            return False
            
        connection = self.exchanges[exchange_id]
        # Переподключаемся с новыми ключами
        return connection.connect(api_key, api_secret)
    
    def fetch_all_prices(self, symbols: List[str]) -> Dict[str, Dict[str, TickerData]]:
        """Запрашивает цены для всех пар на всех биржах."""
        results = {}
        
        for ex_id, connection in self.exchanges.items():
            if not connection.exchange:
                continue
                
            results[ex_id] = {}
            for symbol in symbols:
                ticker = connection.fetch_ticker(symbol)
                if ticker:
                    results[ex_id][symbol] = ticker
                else:
                    logger.warning(f"Не удалось получить тикер {symbol} с {ex_id}")
        
        return results
    
    def get_exchange_status(self, exchange_id: str) -> Dict[str, Any]:
        """Возвращает статус биржи: пинг, доступность, тип подключения (публичное/приватное)."""
        connection = self.get_exchange(exchange_id)
        if not connection:
            return {"error": "Биржа не найдена"}
        
        # Измеряем пинг, если ещё не измеряли
        ping = connection.last_ping
        if ping is None:
            ping = connection.measure_ping()
        
        return {
            "id": exchange_id,
            "connected": connection.exchange is not None,
            "is_private": connection.exchange.apiKey is not None if connection.exchange else False,
            "ping_ms": ping,
            "last_checked": datetime.now().isoformat()
        }