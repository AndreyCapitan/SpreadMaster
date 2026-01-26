from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class SpreadResult:
    pair: str
    exchange1: str
    exchange2: str
    spread_percent: float
    bid_exchange: str
    ask_exchange: str
    bid_price: float
    ask_price: float
    color: str


class SpreadCalculator:
    def __init__(self, thresholds: dict, colors: dict):
        self.thresholds = thresholds
        self.colors = colors

    def calculate_arbitrage_spread(self, buy_ask: float, sell_bid: float) -> float:
        """Calculate arbitrage spread: buy at ask on one exchange, sell at bid on another.
        Positive spread means profit opportunity."""
        if buy_ask <= 0:
            return 0.0
        return ((sell_bid - buy_ask) / buy_ask) * 100

    def get_color(self, spread_percent: float) -> str:
        if spread_percent >= self.thresholds.get('high', 1.0):
            return self.colors.get('high', '#22c55e')
        elif spread_percent >= self.thresholds.get('medium', 0.5):
            return self.colors.get('medium', '#eab308')
        else:
            return self.colors.get('low', '#6b7280')

    def calculate_spreads(self, prices: Dict[str, Dict[str, 'TickerData']], pairs: List[str]) -> List[SpreadResult]:
        results = []
        exchanges = list(prices.keys())
        
        for pair in pairs:
            for i, ex1 in enumerate(exchanges):
                for ex2 in exchanges[i+1:]:
                    ticker1 = prices.get(ex1, {}).get(pair)
                    ticker2 = prices.get(ex2, {}).get(pair)
                    
                    if not ticker1 or not ticker2:
                        continue
                    
                    spread1 = 0.0
                    spread2 = 0.0
                    
                    if ticker2.ask > 0 and ticker1.bid > 0:
                        spread1 = self.calculate_arbitrage_spread(ticker2.ask, ticker1.bid)
                        
                    if ticker1.ask > 0 and ticker2.bid > 0:
                        spread2 = self.calculate_arbitrage_spread(ticker1.ask, ticker2.bid)
                    
                    if spread1 > spread2:
                        spread = spread1
                        buy_ex, sell_ex = ex2, ex1
                        buy_price, sell_price = ticker2.ask, ticker1.bid
                    else:
                        spread = spread2
                        buy_ex, sell_ex = ex1, ex2
                        buy_price, sell_price = ticker1.ask, ticker2.bid
                    
                    results.append(SpreadResult(
                        pair=pair,
                        exchange1=ex1,
                        exchange2=ex2,
                        spread_percent=round(spread, 4),
                        bid_exchange=sell_ex,
                        ask_exchange=buy_ex,
                        bid_price=sell_price,
                        ask_price=buy_price,
                        color=self.get_color(spread)
                    ))
        
        return results


class StochasticCalculator:
    def __init__(self, k_period: int = 14, d_period: int = 3, smooth: int = 3):
        self.k_period = k_period
        self.d_period = d_period
        self.smooth = smooth

    def calculate(self, klines: List[dict]) -> Dict[str, List[float]]:
        if len(klines) < self.k_period:
            return {'k': [], 'd': [], 'timestamps': []}
        
        df = pd.DataFrame(klines)
        
        low_min = df['low'].rolling(window=self.k_period).min()
        high_max = df['high'].rolling(window=self.k_period).max()
        
        k_raw = 100 * (df['close'] - low_min) / (high_max - low_min)
        k = k_raw.rolling(window=self.smooth).mean()
        d = k.rolling(window=self.d_period).mean()
        
        valid_idx = max(self.k_period + self.smooth + self.d_period - 3, 0)
        
        return {
            'k': k.iloc[valid_idx:].fillna(50).tolist(),
            'd': d.iloc[valid_idx:].fillna(50).tolist(),
            'timestamps': df['timestamp'].iloc[valid_idx:].tolist(),
            'prices': df['close'].iloc[valid_idx:].tolist(),
            'ohlc': df.iloc[valid_idx:].to_dict('records')
        }
