"""
Market Data Service

Fetches real-time cryptocurrency prices from the Kraken API.
Handles currency symbol mapping and provides price caching.
"""

import requests
from typing import Dict, Optional
from datetime import datetime, timedelta
import time


class MarketDataService:
    """
    Service for fetching real-time cryptocurrency prices from Kraken.
    
    The Kraken API uses specific pair formatting:
    - Bitcoin: XXBTZUSD
    - Ethereum: XETHZUSD  
    - Most altcoins: {SYMBOL}USD
    
    This service handles the mapping from standard symbols to Kraken pairs.
    """
    
    KRAKEN_API_URL = "https://api.kraken.com/0/public/Ticker"
    
    # Mapping from standard symbols to Kraken pair names
    SYMBOL_TO_KRAKEN = {
        "BTC": "XXBTZUSD",
        "ETH": "XETHZUSD",
        "XRP": "XXRPZUSD",
        "LTC": "XLTCZUSD",
        "XLM": "XXLMZUSD",
        "XMR": "XXMRZUSD",
        "ETC": "XETCZUSD",
        "ZEC": "XZECZUSD",
        "REP": "XREPZUSD",
        "DOGE": "XDGZUSD",  # Note: Kraken uses XDG for DOGE
        # Most other coins use simple format
        "SOL": "SOLUSD",
        "ADA": "ADAUSD",
        "DOT": "DOTUSD",
        "LINK": "LINKUSD",
        "MATIC": "MATICUSD",
        "AVAX": "AVAXUSD",
        "UNI": "UNIUSD",
        "ATOM": "ATOMUSD",
        "FIL": "FILUSD",
        "AAVE": "AAVEUSD",
        "ALGO": "ALGOUSD",
        "APE": "APEUSD",
        "ARB": "ARBUSD",
        "NEAR": "NEARUSD",
        "OP": "OPUSD",
        "SHIB": "SHIBUSD",
        "TRX": "TRXUSD",
    }
    
    # Reverse mapping for response parsing
    KRAKEN_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_KRAKEN.items()}
    
    def __init__(self, cache_duration_seconds: int = 30):
        """
        Initialize the Market Data Service.
        
        Args:
            cache_duration_seconds: How long to cache prices before refreshing
        """
        self.cache_duration = timedelta(seconds=cache_duration_seconds)
        self.price_cache: Dict[str, tuple[float, datetime]] = {}
        self.last_api_call: Optional[datetime] = None
        self.min_api_interval = timedelta(seconds=1)  # Rate limiting
    
    def _get_kraken_pair(self, symbol: str) -> str:
        """Convert a standard symbol to Kraken pair format"""
        symbol = symbol.upper().strip()
        if symbol in self.SYMBOL_TO_KRAKEN:
            return self.SYMBOL_TO_KRAKEN[symbol]
        # Default format for unknown symbols
        return f"{symbol}USD"
    
    def _respect_rate_limit(self):
        """Ensure we don't exceed Kraken's rate limits"""
        if self.last_api_call:
            elapsed = datetime.now() - self.last_api_call
            if elapsed < self.min_api_interval:
                sleep_time = (self.min_api_interval - elapsed).total_seconds()
                time.sleep(sleep_time)
        self.last_api_call = datetime.now()
    
    def get_price(self, symbol: str, use_cache: bool = True) -> Optional[float]:
        """
        Get the current USD price for a cryptocurrency.
        
        Args:
            symbol: Standard cryptocurrency symbol (BTC, ETH, SOL, etc.)
            use_cache: Whether to use cached prices if available
            
        Returns:
            Current USD price or None if unavailable
        """
        symbol = symbol.upper().strip()
        
        # Check cache first
        if use_cache and symbol in self.price_cache:
            cached_price, cached_time = self.price_cache[symbol]
            if datetime.now() - cached_time < self.cache_duration:
                return cached_price
        
        # Fetch from API
        kraken_pair = self._get_kraken_pair(symbol)
        
        try:
            self._respect_rate_limit()
            
            response = requests.get(
                self.KRAKEN_API_URL,
                params={"pair": kraken_pair},
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("error"):
                print(f"Kraken API error for {symbol}: {data['error']}")
                return self._get_fallback_price(symbol)
            
            result = data.get("result", {})
            
            # Kraken returns the pair data with the pair name as key
            # The key might be slightly different than what we sent
            for pair_key, pair_data in result.items():
                # 'c' is the last trade closed [price, lot volume]
                if 'c' in pair_data:
                    price = float(pair_data['c'][0])
                    self.price_cache[symbol] = (price, datetime.now())
                    return price
            
            print(f"No price data found for {symbol}")
            return self._get_fallback_price(symbol)
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching price for {symbol}: {e}")
            return self._get_fallback_price(symbol)
        except (KeyError, ValueError, IndexError) as e:
            print(f"Error parsing price for {symbol}: {e}")
            return self._get_fallback_price(symbol)
    
    def get_prices(self, symbols: list[str], use_cache: bool = True) -> Dict[str, float]:
        """
        Get current USD prices for multiple cryptocurrencies.
        
        Args:
            symbols: List of standard cryptocurrency symbols
            use_cache: Whether to use cached prices
            
        Returns:
            Dictionary mapping symbols to their USD prices
        """
        prices = {}
        
        # Check which symbols need fetching
        symbols_to_fetch = []
        for symbol in symbols:
            symbol = symbol.upper().strip()
            if use_cache and symbol in self.price_cache:
                cached_price, cached_time = self.price_cache[symbol]
                if datetime.now() - cached_time < self.cache_duration:
                    prices[symbol] = cached_price
                    continue
            symbols_to_fetch.append(symbol)
        
        if not symbols_to_fetch:
            return prices
        
        # Batch fetch - Kraken supports multiple pairs in one request
        kraken_pairs = [self._get_kraken_pair(s) for s in symbols_to_fetch]
        
        try:
            self._respect_rate_limit()
            
            response = requests.get(
                self.KRAKEN_API_URL,
                params={"pair": ",".join(kraken_pairs)},
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("error"):
                print(f"Kraken API error: {data['error']}")
            
            result = data.get("result", {})
            
            # Map results back to our symbols
            for pair_key, pair_data in result.items():
                if 'c' in pair_data:
                    price = float(pair_data['c'][0])
                    # Find which symbol this corresponds to
                    for symbol in symbols_to_fetch:
                        kraken_pair = self._get_kraken_pair(symbol)
                        # Kraken sometimes uses alternative pair names
                        if kraken_pair in pair_key or pair_key in kraken_pair:
                            prices[symbol] = price
                            self.price_cache[symbol] = (price, datetime.now())
                            break
            
            # Fill in any missing with fallback prices
            for symbol in symbols_to_fetch:
                if symbol not in prices:
                    fallback = self._get_fallback_price(symbol)
                    if fallback:
                        prices[symbol] = fallback
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching prices: {e}")
            # Use fallback prices
            for symbol in symbols_to_fetch:
                fallback = self._get_fallback_price(symbol)
                if fallback:
                    prices[symbol] = fallback
        
        return prices
    
    def _get_fallback_price(self, symbol: str) -> Optional[float]:
        """
        Get a fallback price when API is unavailable.
        Uses cached price if available, otherwise returns a static estimate.
        
        This is for demo purposes - in production, you'd want better handling.
        """
        symbol = symbol.upper()
        
        # Return cached price regardless of age
        if symbol in self.price_cache:
            return self.price_cache[symbol][0]
        
        # Static fallback prices for common coins (approximate)
        # These are just for demo purposes when API is unavailable
        FALLBACK_PRICES = {
            "BTC": 95000.0,
            "ETH": 3200.0,
            "SOL": 180.0,
            "ADA": 0.90,
            "DOT": 7.0,
            "LINK": 20.0,
            "MATIC": 0.50,
            "AVAX": 35.0,
            "DOGE": 0.35,
            "XRP": 2.30,
            "LTC": 100.0,
            "ATOM": 8.0,
            "UNI": 12.0,
            "AAVE": 280.0,
        }
        
        return FALLBACK_PRICES.get(symbol)
    
    def clear_cache(self):
        """Clear the price cache"""
        self.price_cache.clear()
    
    def get_cached_prices(self) -> Dict[str, float]:
        """Get all currently cached prices"""
        return {symbol: price for symbol, (price, _) in self.price_cache.items()}


# Singleton instance for the application
_market_data_service: Optional[MarketDataService] = None


def get_market_data_service() -> MarketDataService:
    """Get the singleton MarketDataService instance"""
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
