import threading
import time
from datetime import datetime
from typing import Dict, List


class AutoTrader:
    def __init__(self, app, db, exchange_manager, spread_calculator):
        self.app = app
        self.db = db
        self.exchange_manager = exchange_manager
        self.spread_calculator = spread_calculator
        self.running = False
        self.thread = None
        self.check_interval = 5
    
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("AutoTrader started")
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        print("AutoTrader stopped")
    
    def _run_loop(self):
        while self.running:
            try:
                with self.app.app_context():
                    self._process_all_users()
            except Exception as e:
                print(f"AutoTrader error: {e}")
            time.sleep(self.check_interval)
    
    def _process_all_users(self):
        from models import AutoTradeSettings, Contract, User
        
        settings_list = AutoTradeSettings.query.filter_by(auto_enabled=True).all()
        
        for settings in settings_list:
            try:
                user = User.query.get(settings.user_id)
                if not user:
                    continue
                
                enabled_exchanges = user.get_enabled_exchanges()
                enabled_pairs = user.get_enabled_pairs()
                
                spreads = self._get_current_spreads(enabled_exchanges, enabled_pairs)
                
                self._auto_close_contracts(settings, spreads)
                
                self._auto_open_contracts(settings, user, spreads)
                
            except Exception as e:
                print(f"AutoTrader user {settings.user_id} error: {e}")
    
    def _get_current_spreads(self, enabled_exchanges: List[str], enabled_pairs: List[str]) -> List[Dict]:
        prices = self.exchange_manager.fetch_all_prices(enabled_pairs)
        spreads = self.spread_calculator.calculate_spreads(prices, enabled_pairs)
        
        filtered = [s for s in spreads 
                   if s.bid_exchange in enabled_exchanges 
                   and s.ask_exchange in enabled_exchanges]
        
        return sorted(filtered, key=lambda x: x.spread_percent, reverse=True)
    
    def _auto_close_contracts(self, settings, spreads: List[Dict]):
        from models import Contract
        
        active_contracts = Contract.query.filter_by(
            user_id=settings.user_id, 
            is_active=True
        ).all()
        
        spread_map = {}
        for s in spreads:
            key = f"{s.pair}-{s.bid_exchange}-{s.ask_exchange}"
            spread_map[key] = s.spread_percent
        
        for contract in active_contracts:
            current_spread = spread_map.get(contract.contract_key, contract.current_spread)
            contract.current_spread = current_spread
            
            if current_spread <= settings.close_threshold:
                contract.is_active = False
                contract.close_time = datetime.utcnow()
                contract.profit = contract.entry_spread - current_spread
                print(f"AutoTrader: Closed contract {contract.contract_key} at {current_spread:.3f}%")
        
        self.db.session.commit()
    
    def _auto_open_contracts(self, settings, user, spreads: List[Dict]):
        from models import Contract
        
        active_count = Contract.query.filter_by(
            user_id=settings.user_id, 
            is_active=True
        ).count()
        
        if active_count >= settings.max_contracts:
            return
        
        existing_keys = set()
        existing = Contract.query.filter_by(user_id=settings.user_id, is_active=True).all()
        for c in existing:
            existing_keys.add(c.contract_key)
        
        for spread in spreads:
            if active_count >= settings.max_contracts:
                break
            
            if spread.spread_percent < settings.open_threshold:
                break
            
            key = f"{spread.pair}-{spread.bid_exchange}-{spread.ask_exchange}"
            
            if key in existing_keys:
                continue
            
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
                open_time=datetime.utcnow()
            )
            
            self.db.session.add(contract)
            existing_keys.add(key)
            active_count += 1
            print(f"AutoTrader: Opened contract {key} at {spread.spread_percent:.3f}%")
        
        self.db.session.commit()
