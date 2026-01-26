"""
Модуль для работы с криптобиржами через CCXT с улучшенной обработкой ошибок,
кэшированием и мониторингом здоровья.
"""

import ccxt
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

logger = logging.getLogger(__name__)

# Конфигурация лимитов запросов (запросов в секунду)
RATE_LIMITS = {
    'bitget': 10,
    'mexc': 20,
    'okx': 5
}

# Время жизни кэша тикеров (секунды)
TICKER_CACHE_TTL = 2

@dataclass
class TickerData:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: int

@dataclass
class ExchangeHealth:
    """Данные о здоровье подключения к бирже."""
    is_healthy: bool = True
    last_error: Optional[str] = None
    error_count_1h: int = 0
    success_count_1h: int = 0
    avg_ping_ms: Optional[float] = None
    last_checked: Optional[datetime] = None

class RobustExchangeConnection:
    """
    Улучшенный объект для управления подключением к одной бирже.
    Включает кэширование, повторы при ошибках и сбор метрик.
    """

    def __init__(self, config: dict):
        self.config = config
        self.exchange_id = config['id']
        self.exchange: Optional[ccxt.Exchange] = None
        self.health = ExchangeHealth()
        self._ticker_cache: Dict[str, Tuple[TickerData, float]] = {}
        self._last_ping: Optional[float] = None
        self._error_timestamps: List[datetime] = []
        self._success_timestamps: List[datetime] = []

    def _should_retry(self, error: Exception, attempt: int) -> Tuple[bool, float]:
        """
        Определяет, нужно ли повторять запрос и какую задержку использовать.
        Возвращает (нужно_ли_повторять, задержка_в_секундах).
        """
        max_attempts = 3
        if attempt >= max_attempts:
            return False, 0

        error_msg = str(error)

        # Критические ошибки, которые не стоит повторять
        critical_errors = [
            'Invalid API key',
            'AuthenticationError',
            'Permission denied',
            'Insufficient funds',
            'Market does not exist',
            'pair not found'
        ]
        for critical in critical_errors:
            if critical.lower() in error_msg.lower():
                logger.error(f"Критическая ошибка {self.exchange_id}: {critical}. Повтор не требуется.")
                return False, 0

        # Определяем тип ошибки для выбора задержки
        if '502' in error_msg or 'Bad Gateway' in error_msg:
            return True, 30.0  # 30 секунд для 502 ошибок
        elif '429' in error_msg or 'rate limit' in error_msg:
            return True, 60.0  # 60 секунд при лимите запросов
        elif '500' in error_msg or 'Internal server error' in error_msg:
            return True, 15.0  # 15 секунд для 500 ошибок
        elif 'NetworkError' in error_msg or 'timed out' in error_msg:
            return True, 5.0   # 5 секунд для сетевых ошибок
        else:
            # Для прочих ошибок биржи используем экспоненциальную задержку
            delay = 2.0 * (2 ** attempt)  # 2, 4, 8 секунд
            return True, min(delay, 30)   # Максимум 30 секунд

    def _safe_request(self, request_func, *args, **kwargs):
        """
        Обертка для запросов к API биржи с повторными попытками и обработкой ошибок.
        """
        last_exception = None

        for attempt in range(3):
            try:
                result = request_func(*args, **kwargs)
                self._record_success()
                return result
            except Exception as e:
                last_exception = e
                self._record_error(e)

                # Решаем, повторять ли запрос
                should_retry, delay = self._should_retry(e, attempt)
                if not should_retry:
                    break

                # Если это HTML-ответ (как от Cloudflare), логируем сокращенно
                error_msg = str(e)
                if '<!DOCTYPE html>' in error_msg:
                    log_msg = error_msg.split('\n')[0][:150]
                    logger.warning(f"Повтор {attempt+1}/3 для {self.exchange_id}: Получен HTML. Жду {delay:.1f}с. Ошибка: {log_msg}...")
                else:
                    logger.warning(f"Повтор {attempt+1}/3 для {self.exchange_id}. Жду {delay:.1f}с. Ошибка: {error_msg[:150]}")

                time.sleep(delay)

        # Если все попытки исчерпаны
        if last_exception:
            # Сокращаем HTML для логов
            error_msg = str(last_exception)
            if '<!DOCTYPE html>' in error_msg:
                error_msg = "Ошибка биржи (HTML-ответ, вероятно 502/500)"
            logger.error(f"Запрос к {self.exchange_id} провалился после 3 попыток. Финальная ошибка: {error_msg[:200]}")
        return None

    def _record_error(self, error: Exception):
        """Записывает ошибку в историю и обновляет статус здоровья."""
        self.health.last_error = str(error)[:200]
        self.health.is_healthy = False
        now = datetime.now()
        self._error_timestamps.append(now)

        # Очищаем старые ошибки (старше 1 часа)
        hour_ago = now - timedelta(hours=1)
        self._error_timestamps = [ts for ts in self._error_timestamps if ts > hour_ago]
        self.health.error_count_1h = len(self._error_timestamps)

    def _record_success(self):
        """Отмечает успешный запрос и обновляет здоровье."""
        now = datetime.now()
        self._success_timestamps.append(now)
        # Очищаем старые успехи (старше 1 часа)
        hour_ago = now - timedelta(hours=1)
        self._success_timestamps = [ts for ts in self._success_timestamps if ts > hour_ago]
        self.health.success_count_1h = len(self._success_timestamps)
        self.health.last_checked = now

        # Если подряд было несколько успехов, считаем биржу здоровой
        if self.health.success_count_1h > 5:
            self.health.is_healthy = True
            self.health.last_error = None

    def connect(self, api_key: str = '', api_secret: str = '') -> bool:
        """Создаёт и проверяет подключение к бирже."""
        try:
            exchange_class = getattr(ccxt, self.exchange_id)
            exchange_config = {
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'},
                'timeout': 30000,
                **self.config.get('ccxt_overrides', {})
            }

            if not api_key:
                exchange_config.pop('apiKey', None)
                exchange_config.pop('secret', None)
                logger.info(f"Создано публичное подключение к {self.exchange_id}")
            else:
                logger.info(f"Создано приватное подключение к {self.exchange_id}")

            self.exchange = exchange_class(exchange_config)
            self._record_success()
            return True

        except Exception as e:
            self._record_error(e)
            logger.error(f"Ошибка подключения к {self.exchange_id}: {e}")
            return False

    def fetch_ticker(self, symbol: str) -> Optional[TickerData]:
        """Запрашивает тикер для пары с использованием кэша."""
        # Проверяем кэш
        cache_key = symbol
        if cache_key in self._ticker_cache:
            ticker, timestamp = self._ticker_cache[cache_key]
            if time.time() - timestamp < TICKER_CACHE_TTL:
                return ticker

        if not self.exchange:
            logger.warning(f"Нет подключения к {self.exchange_id} для запроса тикера {symbol}")
            return None

        # Убедимся, что рынки загружены
        try:
            if not hasattr(self.exchange, 'markets') or not self.exchange.markets:
                self.exchange.load_markets()
        except Exception as e:
            logger.warning(f"Не удалось загрузить рынки для {self.exchange_id}: {e}")

        # Выполняем безопасный запрос
        try:
            market_symbol = symbol
            if hasattr(self.exchange, 'market_id'):
                # Пробуем получить ID рынка, если метод существует
                try:
                    market_symbol = self.exchange.market_id(symbol)
                except:
                    pass  # Оставляем исходный символ

            raw_ticker = self._safe_request(self.exchange.fetch_ticker, market_symbol)
            if not raw_ticker:
                return None

            ticker = TickerData(
                symbol=symbol,
                bid=raw_ticker.get('bid'),
                ask=raw_ticker.get('ask'),
                last=raw_ticker.get('last'),
                timestamp=raw_ticker.get('timestamp', int(time.time() * 1000))
            )

            # Сохраняем в кэш
            self._ticker_cache[cache_key] = (ticker, time.time())
            return ticker

        except Exception as e:
            # Ошибка уже обработана в _safe_request
            return None

    def fetch_balance(self) -> Optional[Dict]:
        """Запрашивает баланс с биржи."""
        if not self.exchange or not self.exchange.apiKey:
            return None
        return self._safe_request(self.exchange.fetch_balance)

    def measure_ping(self) -> Optional[float]:
        """Измеряет пинг до сервера биржи."""
        if not self.exchange:
            return None

        try:
            start = time.time()
            self.exchange.fetch_time()
            ping_ms = round((time.time() - start) * 1000, 2)
            self._last_ping = ping_ms
            self.health.avg_ping_ms = ping_ms if not self.health.avg_ping_ms else (self.health.avg_ping_ms * 0.7 + ping_ms * 0.3)
            return ping_ms
        except Exception as e:
            logger.warning(f"Не удалось измерить пинг для {self.exchange_id}: {e}")
            return None

    def get_health_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус здоровья биржи."""
        return {
            "id": self.exchange_id,
            "is_healthy": self.health.is_healthy,
            "last_error": self.health.last_error,
            "error_count_1h": self.health.error_count_1h,
            "success_count_1h": self.health.success_count_1h,
            "avg_ping_ms": self.health.avg_ping_ms,
            "last_checked": self.health.last_checked.isoformat() if self.health.last_checked else None,
            "is_private": self.exchange.apiKey is not None if self.exchange else False
        }

# ==================== Менеджер бирж (сохранен публичный API) ====================

class ExchangeManager:
    """Управляет подключениями ко всем биржам."""

    def __init__(self, config: dict):
        self.config = config
        self.exchanges: Dict[str, RobustExchangeConnection] = {}
        self._initialize_exchanges()

    def _initialize_exchanges(self):
        """Инициализирует все биржи из конфигурации в режиме публичного доступа."""
        exchanges_config = self.config.get('exchanges', {})
        for ex_id, ex_config in exchanges_config.items():
            connection_config = {**ex_config, 'id': ex_id}
            connection = RobustExchangeConnection(connection_config)

            if connection.connect():  # Публичное подключение без ключей
                self.exchanges[ex_id] = connection
                logger.info(f"Биржа {ex_id} готова к работе.")
            else:
                logger.warning(f"Биржа {ex_id} пропущена из-за ошибки инициализации.")

    def get_exchange(self, exchange_id: str) -> Optional[RobustExchangeConnection]:
        """Возвращает объект подключения к бирже по её ID."""
        return self.exchanges.get(exchange_id)

    def set_exchange_credentials(self, exchange_id: str, api_key: str, api_secret: str) -> bool:
        """Обновляет биржу для работы с приватными ключами."""
        if exchange_id not in self.exchanges:
            logger.error(f"Биржа {exchange_id} не найдена.")
            return False

        # Закрываем старое подключение, если оно было
        old_connection = self.exchanges[exchange_id]
        # Создаем новое подключение с теми же настройками, но новыми ключами
        new_connection = RobustExchangeConnection(old_connection.config)
        success = new_connection.connect(api_key, api_secret)

        if success:
            self.exchanges[exchange_id] = new_connection
            logger.info(f"Приватные ключи для {exchange_id} успешно установлены.")
        else:
            logger.error(f"Не удалось установить приватные ключи для {exchange_id}.")
            # Оставляем старую публичную сессию
            old_connection.connect()  # Переподключаемся в публичном режиме

        return success

    def fetch_all_prices(self, symbols: List[str]) -> Dict[str, Dict[str, TickerData]]:
        """
        Запрашивает цены для всех пар на всех биржах.
        Возвращает словарь: {exchange_id: {symbol: TickerData}}
        """
        results = {}

        for ex_id, connection in self.exchanges.items():
            if not connection.exchange:
                continue

            results[ex_id] = {}
            for symbol in symbols:
                ticker = connection.fetch_ticker(symbol)
                if ticker:
                    results[ex_id][symbol] = ticker
                # Если тикер не получен, просто не добавляем его. Ошибка уже залогирована.

            # Небольшая пауза между запросами к разным биржам, чтобы снизить нагрузку
            time.sleep(0.1)

        return results

    def get_exchange_status(self, exchange_id: str) -> Dict[str, Any]:
        """Возвращает детальный статус биржи."""
        connection = self.get_exchange(exchange_id)
        if not connection:
            return {"error": "Биржа не найдена"}

        # Если пинг не измерялся, измеряем
        if connection.health.avg_ping_ms is None:
            connection.measure_ping()

        return connection.get_health_status()

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Возвращает статус всех бирж."""
        return {ex_id: self.get_exchange_status(ex_id) for ex_id in self.exchanges}