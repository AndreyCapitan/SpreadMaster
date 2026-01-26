"""
Улучшенный модуль автотрейдинга для SpreadMaster.
Добавлен риск-менеджмент, обработка ошибок API и расширенное логирование.
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Настройка логирования для автотрейдера
logger = logging.getLogger('auto_trader')

@dataclass
class TradeDecision:
    """Результат анализа для принятия торгового решения."""
    action: str  # 'open', 'close', 'hold', 'skip'
    spread: float
    pair: str
    buy_exchange: str
    sell_exchange: str
    reason: str
    confidence: float = 1.0  # Уверенность в решении (0.0-1.0)

class RiskManager:
    """Менеджер рисков для контроля размера позиций и лимитов."""
    
    def __init__(self, max_position_percent: float = 10.0, max_daily_loss: float = 5.0):
        self.max_position_percent = max_position_percent
        self.max_daily_loss = max_daily_loss
        self.daily_trades = []
        self.daily_start_balance = 0.0
        
    def can_open_trade(self, estimated_cost: float, current_balance: float, pair: str) -> Tuple[bool, str]:
        """Проверка возможности открытия новой позиции."""
        # Проверка размера позиции
        position_percent = (estimated_cost / current_balance) * 100
        if position_percent > self.max_position_percent:
            return False, f"Размер позиции {position_percent:.1f}% превышает лимит {self.max_position_percent}%"
        
        # Проверка дневного лимита убытков
        daily_pnl = self.calculate_daily_pnl()
        if daily_pnl < -self.max_daily_loss:
            return False, f"Достигнут дневной лимит убытков: {daily_pnl:.1f}%"
        
        # Проверка на частые сделки с одной парой
        recent_trades = [t for t in self.daily_trades 
                        if t['pair'] == pair and 
                        t['time'] > datetime.now() - timedelta(minutes=5)]
        if len(recent_trades) >= 3:
            return False, f"Слишком много сделок с {pair} за последние 5 минут"
        
        return True, "OK"
    
    def calculate_daily_pnl(self) -> float:
        """Расчёт дневного P&L в процентах."""
        if not self.daily_trades:
            return 0.0
        
        total_pnl = sum(t.get('pnl', 0) for t in self.daily_trades)
        return (total_pnl / self.daily_start_balance) * 100 if self.daily_start_balance else 0.0
    
    def record_trade(self, trade_data: dict):
        """Запись информации о сделке."""
        self.daily_trades.append({
            **trade_data,
            'time': datetime.now()
        })

class AutoTrader:
    def __init__(self, app, db, exchange_manager, spread_calculator):
        self.app = app
        self.db = db
        self.exchange_manager = exchange_manager
        self.spread_calculator = spread_calculator
        self.running = False
        self.thread = None
        self.check_interval = 3  # Уменьшен интервал для более оперативной реакции
        self.risk_manager = RiskManager()
        
        # Кэш для предотвращения частых операций с одним спредом
        self.recent_actions = {}
        
        # Статистика работы
        self.stats = {
            'cycles_completed': 0,
            'trades_opened': 0,
            'trades_closed': 0,
            'errors': 0,
            'last_activity': None
        }
        
        logger.info("AutoTrader инициализирован с RiskManager")

    def start(self):
        """Запуск автотрейдера."""
        if self.running:
            logger.warning("AutoTrader уже запущен")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="AutoTrader-Thread")
        self.thread.start()
        logger.info("✅ AutoTrader запущен")

    def stop(self):
        """Остановка автотрейдера."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("⏹️ AutoTrader остановлен")

    def _run_loop(self):
        """Основной цикл работы автотрейдера."""
        logger.info("🔄 Цикл автотрейдера начал работу")
        
        while self.running:
            cycle_start = time.time()
            self.stats['cycles_completed'] += 1
            
            try:
                with self.app.app_context():
                    self._process_all_users()
                    
            except Exception as e:
                self.stats['errors'] += 1
                logger.error(f"❌ Ошибка в цикле автотрейдера: {e}", exc_info=True)
                
            # Динамический интервал на основе загрузки
            cycle_time = time.time() - cycle_start
            sleep_time = max(1.0, self.check_interval - cycle_time)
            
            if cycle_time > 5:
                logger.warning(f"Цикл занял {cycle_time:.2f}с, что много для интервала {self.check_interval}с")
                
            time.sleep(sleep_time)
            
            # Периодический вывод статистики
            if self.stats['cycles_completed'] % 20 == 0:
                self._log_statistics()

    def _process_all_users(self):
        """Обработка всех пользователей с включенным автотрейдингом."""
        from models import AutoTradeSettings, User
        
        settings_list = AutoTradeSettings.query.filter_by(auto_enabled=True).all()
        logger.debug(f"Найдено {len(settings_list)} пользователей с включенным автотрейдингом")
        
        for settings in settings_list:
            try:
                user = User.query.get(settings.user_id)
                if not user:
                    logger.warning(f"Пользователь с ID {settings.user_id} не найден")
                    continue
                
                # Получаем спреды для пользователя
                enabled_exchanges = user.get_enabled_exchanges()
                enabled_pairs = user.get_enabled_pairs()
                
                if not enabled_exchanges or not enabled_pairs:
                    logger.debug(f"У пользователя {user.username} нет включенных бирж или пар")
                    continue
                
                spreads = self._get_current_spreads(enabled_exchanges, enabled_pairs)
                
                if not spreads:
                    continue
                
                # Принимаем решения по открытию/закрытию
                self._make_trading_decisions(settings, user, spreads)
                
            except Exception as e:
                logger.error(f"Ошибка обработки пользователя {settings.user_id}: {e}")

    def _get_current_spreads(self, enabled_exchanges: List[str], enabled_pairs: List[str]) -> List[Dict]:
        """Получение и фильтрация текущих спредов."""
        try:
            prices = self.exchange_manager.fetch_all_prices(enabled_pairs)
            
            if not prices:
                logger.debug("Нет данных о ценах от бирж")
                return []
            
            spreads = self.spread_calculator.calculate_spreads(prices, enabled_pairs)
            
            # Фильтрация по включенным биржам и минимальному спреду
            filtered = []
            for s in spreads:
                if (s.bid_exchange in enabled_exchanges and 
                    s.ask_exchange in enabled_exchanges and
                    s.spread_percent > 0.05):  # Минимальный спред 0.05%
                    
                    # Проверяем ликвидность (разница между bid и ask не слишком большая)
                    spread_to_ask_ratio = (s.ask_price - s.bid_price) / s.ask_price * 100
                    if spread_to_ask_ratio < 5:  # Максимальный спред внутри биржи 5%
                        filtered.append(s)
            
            # Сортировка по потенциалу прибыли с учетом комиссий
            sorted_spreads = sorted(filtered, 
                                  key=lambda x: x.spread_percent * 0.85,  # Учёт примерных комиссий (~15%)
                                  reverse=True)
            
            logger.debug(f"Получено {len(sorted_spreads)} спредов после фильтрации")
            return sorted_spreads
            
        except Exception as e:
            logger.error(f"Ошибка получения спредов: {e}")
            return []

    def _make_trading_decisions(self, settings, user, spreads: List[Dict]):
        """Принятие торговых решений на основе спредов."""
        from models import Contract
        
        # 1. Закрытие позиций
        active_contracts = Contract.query.filter_by(
            user_id=settings.user_id, 
            is_active=True
        ).all()
        
        # Создаем карту текущих спредов для быстрого доступа
        spread_map = {}
        for s in spreads:
            key = f"{s.pair}-{s.bid_exchange}-{s.ask_exchange}"
            spread_map[key] = s.spread_percent
        
        # Обрабатываем каждую активную позицию
        for contract in active_contracts:
            current_spread = spread_map.get(contract.contract_key, contract.current_spread)
            
            # Обновляем текущий спред в контракте
            contract.current_spread = current_spread
            
            # ПРИНЦИП "СУЖЕНИЯ": когда текущий спред УМЕНЬШАЕТСЯ относительно entry
            spread_change_pct = ((contract.entry_spread - current_spread) / contract.entry_spread) * 100
            
            # Условие закрытия: спред упал ниже порога ИЛИ уменьшился значительно
            should_close = False
            close_reason = ""
            
            if current_spread <= settings.close_threshold:
                should_close = True
                close_reason = f"Достигнут порог закрытия ({current_spread:.3f}% <= {settings.close_threshold}%)"
            elif spread_change_pct >= 30:  # Если спред уменьшился на 30% от начального
                should_close = True
                close_reason = f"Спред уменьшился на {spread_change_pct:.1f}% от начального"
            elif current_spread < contract.entry_spread * 0.5:  # Упал в 2 раза
                should_close = True
                close_reason = f"Спред упал более чем в 2 раза ({current_spread:.3f}% vs {contract.entry_spread:.3f}%)"
            
            if should_close:
                contract.is_active = False
                contract.close_time = datetime.utcnow()
                # Более точный расчёт прибыли (в процентах от сделки)
                contract.profit = contract.entry_spread - current_spread
                
                logger.info(f"🔒 Закрытие контракта {contract.contract_key}: {close_reason}")
                self.stats['trades_closed'] += 1
        
        self.db.session.commit()
        
        # 2. Открытие новых позиций
        active_count = Contract.query.filter_by(
            user_id=settings.user_id, 
            is_active=True
        ).count()
        
        if active_count >= settings.max_contracts:
            logger.debug(f"Достигнут лимит контрактов: {active_count}/{settings.max_contracts}")
            return
        
        # Получаем ключи существующих активных контрактов
        existing_keys = {c.contract_key for c in active_contracts}
        
        # ПРИНЦИП "РАЗЛЕТА": ищем лучшие спреды для открытия
        for spread in spreads:
            if active_count >= settings.max_contracts:
                break
            
            # Пропускаем если спред ниже порога открытия
            if spread.spread_percent < settings.open_threshold:
                continue
            
            key = f"{spair}-{spread.bid_exchange}-{spread.ask_exchange}"
            
            # Проверяем, нет ли уже такого контракта
            if key in existing_keys:
                continue
            
            # Проверяем кэш недавних действий (чтобы не открывать часто одно и то же)
            cache_key = f"open_{key}"
            if cache_key in self.recent_actions:
                last_time = self.recent_actions[cache_key]
                if datetime.now() - last_time < timedelta(minutes=10):
                    logger.debug(f"Пропускаем {key} - недавно уже открывали")
                    continue
            
            # Дополнительная проверка качества спреда
            # 1. Объём должен быть достаточным (если есть данные)
            # 2. Спред должен быть стабильным (не "всплеск")
            
            # Создаём контракт
            contract = Contract(
                user_id=settings.user_id,
                contract_key=key,
                pair=spread.pair,
                buy_exchange=spread.ask_exchange,
                sell_exchange=spread.bid_exchange,
                entry_spread=spread.spread_percent,
                current_spread=spread.spread_percent,
                auto_close=True,
                close_threshold=settings.close_threshold,
                is_active=True,
                open_time=datetime.utcnow(),
                bid_price=spread.bid_price,  # Сохраняем цены для анализа
                ask_price=spread.ask_price
            )
            
            self.db.session.add(contract)
            existing_keys.add(key)
            active_count += 1
            
            # Сохраняем в кэш
            self.recent_actions[cache_key] = datetime.now()
            
            logger.info(f"🔓 Открытие контракта {key} при спреде {spread.spread_percent:.3f}%")
            self.stats['trades_opened'] += 1
        
        self.db.session.commit()
        self.stats['last_activity'] = datetime.now()

    def _log_statistics(self):
        """Логирование статистики работы."""
        stats = self.stats
        logger.info(
            f"📊 Статистика AutoTrader: "
            f"Циклы: {stats['cycles_completed']}, "
            f"Открыто: {stats['trades_opened']}, "
            f"Закрыто: {stats['trades_closed']}, "
            f"Ошибки: {stats['errors']}"
        )

    def get_status(self) -> Dict:
        """Получение текущего статуса автотрейдера."""
        return {
            'running': self.running,
            'stats': self.stats,
            'risk_manager': {
                'daily_pnl': self.risk_manager.calculate_daily_pnl(),
                'max_position_percent': self.risk_manager.max_position_percent
            },
            'last_activity': self.stats['last_activity'].isoformat() if self.stats['last_activity'] else None
        }

    def update_settings(self, check_interval: Optional[int] = None, 
                       max_position_percent: Optional[float] = None):
        """Обновление настроек автотрейдера на лету."""
        if check_interval is not None and 1 <= check_interval <= 60:
            self.check_interval = check_interval
            logger.info(f"Интервал проверки обновлён: {check_interval}с")
        
        if max_position_percent is not None and 0 < max_position_percent <= 100:
            self.risk_manager.max_position_percent = max_position_percent
            logger.info(f"Максимальный размер позиции обновлён: {max_position_percent}%")