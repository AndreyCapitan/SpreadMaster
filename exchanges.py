import requests
import json
import time
from typing import Dict, Optional, List
from dataclasses import dataclass
import threading


@dataclass
class TickerData:
    symbol: str
    bid: float
    ask: float
    last: float
    timestamp: float


class BaseExchange:
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get('name', 'Unknown')
        self.enabled = config.get('enabled', False)
        self.rest_url = config.get('rest_url', '')
        self._prices: Dict[str, TickerData] = {}
        self._lock = threading.Lock()

    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        raise NotImplementedError

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        raise NotImplementedError

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        raise NotImplementedError

    def format_symbol(self, symbol: str) -> str:
        return symbol.replace('/', '')

    def get_cached_price(self, symbol: str) -> Optional[TickerData]:
        with self._lock:
            return self._prices.get(symbol)

    def update_price(self, symbol: str, data: TickerData):
        with self._lock:
            self._prices[symbol] = data


class BybitExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = self.format_symbol(symbol)
            url = f"{self.rest_url}/v5/market/tickers"
            params = {'category': 'spot', 'symbol': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                ticker = data['result']['list'][0]
                return TickerData(
                    symbol=symbol,
                    bid=float(ticker.get('bid1Price', 0)),
                    ask=float(ticker.get('ask1Price', 0)),
                    last=float(ticker.get('lastPrice', 0)),
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"Bybit ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        try:
            formatted = self.format_symbol(symbol)
            interval_map = {'5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D'}
            bybit_interval = interval_map.get(interval, '15')
            
            url = f"{self.rest_url}/v5/market/kline"
            params = {'category': 'spot', 'symbol': formatted, 'interval': bybit_interval, 'limit': limit}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                klines = []
                for k in reversed(data['result']['list']):
                    klines.append({
                        'timestamp': int(k[0]),
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    })
                return klines
        except Exception as e:
            print(f"Bybit klines error: {e}")
        return []


class OKXExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = symbol.replace('/', '-')
            url = f"{self.rest_url}/api/v5/market/ticker"
            params = {'instId': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('code') == '0' and data.get('data'):
                ticker = data['data'][0]
                return TickerData(
                    symbol=symbol,
                    bid=float(ticker.get('bidPx', 0)),
                    ask=float(ticker.get('askPx', 0)),
                    last=float(ticker.get('last', 0)),
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"OKX ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        try:
            formatted = symbol.replace('/', '-')
            interval_map = {'5m': '5m', '15m': '15m', '1h': '1H', '4h': '4H', '1d': '1D'}
            okx_interval = interval_map.get(interval, '15m')
            
            url = f"{self.rest_url}/api/v5/market/candles"
            params = {'instId': formatted, 'bar': okx_interval, 'limit': limit}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('code') == '0' and data.get('data'):
                klines = []
                for k in reversed(data['data']):
                    klines.append({
                        'timestamp': int(k[0]),
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    })
                return klines
        except Exception as e:
            print(f"OKX klines error: {e}")
        return []


class HTXExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = self.format_symbol(symbol).lower()
            url = f"{self.rest_url}/market/detail/merged"
            params = {'symbol': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('status') == 'ok' and data.get('tick'):
                ticker = data['tick']
                bid = ticker.get('bid', [0])[0] if isinstance(ticker.get('bid'), list) else 0
                ask = ticker.get('ask', [0])[0] if isinstance(ticker.get('ask'), list) else 0
                return TickerData(
                    symbol=symbol,
                    bid=float(bid),
                    ask=float(ask),
                    last=float(ticker.get('close', 0)),
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"HTX ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        try:
            formatted = self.format_symbol(symbol).lower()
            interval_map = {'5m': '5min', '15m': '15min', '1h': '60min', '4h': '4hour', '1d': '1day'}
            htx_interval = interval_map.get(interval, '15min')
            
            url = f"{self.rest_url}/market/history/kline"
            params = {'symbol': formatted, 'period': htx_interval, 'size': limit}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('status') == 'ok' and data.get('data'):
                klines = []
                for k in reversed(data['data']):
                    klines.append({
                        'timestamp': int(k['id']) * 1000,
                        'open': float(k['open']),
                        'high': float(k['high']),
                        'low': float(k['low']),
                        'close': float(k['close']),
                        'volume': float(k['vol'])
                    })
                return klines
        except Exception as e:
            print(f"HTX klines error: {e}")
        return []


class ParadexExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            base = symbol.split('/')[0]
            formatted = f"{base}-USD-PERP"
            url = f"{self.rest_url}/bbo"
            params = {'market': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('results') and len(data['results']) > 0:
                ticker = data['results'][0]
                bid = float(ticker.get('bid', 0) or 0)
                ask = float(ticker.get('ask', 0) or 0)
                return TickerData(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    last=(bid + ask) / 2 if bid and ask else 0,
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"Paradex ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker and ticker.bid > 0:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        return []


class BinanceExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = self.format_symbol(symbol)
            url = f"{self.rest_url}/api/v3/ticker/bookTicker"
            params = {'symbol': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if 'bidPrice' in data:
                return TickerData(
                    symbol=symbol,
                    bid=float(data.get('bidPrice', 0)),
                    ask=float(data.get('askPrice', 0)),
                    last=(float(data.get('bidPrice', 0)) + float(data.get('askPrice', 0))) / 2,
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"Binance ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        try:
            formatted = self.format_symbol(symbol)
            interval_map = {'5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
            binance_interval = interval_map.get(interval, '15m')
            
            url = f"{self.rest_url}/api/v3/klines"
            params = {'symbol': formatted, 'interval': binance_interval, 'limit': limit}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            klines = []
            for k in data:
                klines.append({
                    'timestamp': int(k[0]),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5])
                })
            return klines
        except Exception as e:
            print(f"Binance klines error: {e}")
        return []


class KuCoinExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = symbol.replace('/', '-')
            url = f"{self.rest_url}/api/v1/market/orderbook/level1"
            params = {'symbol': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('code') == '200000' and data.get('data'):
                ticker = data['data']
                return TickerData(
                    symbol=symbol,
                    bid=float(ticker.get('bestBid', 0) or 0),
                    ask=float(ticker.get('bestAsk', 0) or 0),
                    last=float(ticker.get('price', 0) or 0),
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"KuCoin ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker and ticker.bid > 0:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        return []


class GateIOExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = symbol.replace('/', '_')
            url = f"{self.rest_url}/api/v4/spot/order_book"
            params = {'currency_pair': formatted, 'limit': 1}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if 'bids' in data and 'asks' in data and len(data['bids']) > 0 and len(data['asks']) > 0:
                bid = float(data['bids'][0][0])
                ask = float(data['asks'][0][0])
                return TickerData(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    last=(bid + ask) / 2,
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"Gate.io ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker and ticker.bid > 0:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        return []


class MEXCExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = self.format_symbol(symbol)
            url = f"{self.rest_url}/api/v3/ticker/bookTicker"
            params = {'symbol': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if 'bidPrice' in data:
                return TickerData(
                    symbol=symbol,
                    bid=float(data.get('bidPrice', 0)),
                    ask=float(data.get('askPrice', 0)),
                    last=(float(data.get('bidPrice', 0)) + float(data.get('askPrice', 0))) / 2,
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"MEXC ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker and ticker.bid > 0:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        return []


class BitgetExchange(BaseExchange):
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = self.format_symbol(symbol)
            url = f"{self.rest_url}/api/v2/spot/market/tickers"
            params = {'symbol': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('code') == '00000' and data.get('data'):
                ticker = data['data'][0]
                bid = float(ticker.get('bidPr', 0) or 0)
                ask = float(ticker.get('askPr', 0) or 0)
                return TickerData(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    last=float(ticker.get('lastPr', 0) or 0),
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"Bitget ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker and ticker.bid > 0:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        return []


class KrakenExchange(BaseExchange):
    KRAKEN_PAIRS = {
        'BTC/USDT': 'XBTUSDT', 'ETH/USDT': 'ETHUSDT', 'SOL/USDT': 'SOLUSDT',
        'XRP/USDT': 'XRPUSDT', 'DOGE/USDT': 'DOGEUSDT', 'ADA/USDT': 'ADAUSDT',
        'DOT/USDT': 'DOTUSDT', 'LINK/USDT': 'LINKUSDT', 'AVAX/USDT': 'AVAXUSDT',
        'LTC/USDT': 'LTCUSDT', 'ATOM/USDT': 'ATOMUSDT', 'UNI/USDT': 'UNIUSDT'
    }
    
    def get_ticker(self, symbol: str) -> Optional[TickerData]:
        try:
            formatted = self.KRAKEN_PAIRS.get(symbol, self.format_symbol(symbol))
            url = f"{self.rest_url}/0/public/Ticker"
            params = {'pair': formatted}
            response = requests.get(url, params=params, timeout=5)
            data = response.json()
            
            if data.get('error') == [] and data.get('result'):
                ticker = list(data['result'].values())[0]
                bid = float(ticker['b'][0])
                ask = float(ticker['a'][0])
                return TickerData(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    last=float(ticker['c'][0]),
                    timestamp=time.time()
                )
        except Exception as e:
            print(f"Kraken ticker error: {e}")
        return None

    def get_all_tickers(self, symbols: List[str]) -> Dict[str, TickerData]:
        result = {}
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker and ticker.bid > 0:
                result[symbol] = ticker
                self.update_price(symbol, ticker)
        return result

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[dict]:
        return []


class ExchangeManager:
    def __init__(self, config: dict):
        self.exchanges: Dict[str, BaseExchange] = {}
        self._init_exchanges(config.get('exchanges', {}))

    def _init_exchanges(self, exchanges_config: dict):
        exchange_classes = {
            'binance': BinanceExchange,
            'bybit': BybitExchange,
            'okx': OKXExchange,
            'htx': HTXExchange,
            'kucoin': KuCoinExchange,
            'gateio': GateIOExchange,
            'mexc': MEXCExchange,
            'kraken': KrakenExchange,
            'bitget': BitgetExchange
        }
        for ex_id, ex_config in exchanges_config.items():
            if ex_id in exchange_classes:
                self.exchanges[ex_id] = exchange_classes[ex_id](ex_config)

    def get_exchange(self, exchange_id: str) -> Optional[BaseExchange]:
        return self.exchanges.get(exchange_id)

    def get_enabled_exchanges(self) -> Dict[str, BaseExchange]:
        return {k: v for k, v in self.exchanges.items() if v.enabled}

    def set_exchange_enabled(self, exchange_id: str, enabled: bool):
        if exchange_id in self.exchanges:
            self.exchanges[exchange_id].enabled = enabled

    def fetch_all_prices(self, symbols: List[str]) -> Dict[str, Dict[str, TickerData]]:
        result = {}
        for ex_id, exchange in self.get_enabled_exchanges().items():
            result[ex_id] = exchange.get_all_tickers(symbols)
        return result
