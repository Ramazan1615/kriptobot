import sys
import ccxt
import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("BinanceSignals")

# Popüler vadeli ve spot pariteler (Listenin en başında yer alır)
POPULAR_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "SHIB/USDT", "1000SHIB/USDT", 
    "BONK/USDT", "1000BONK/USDT", "PEPE/USDT", "1000PEPE/USDT", "DOGE/USDT", 
    "FLOKI/USDT", "1000FLOKI/USDT", "BNB/USDT", "XRP/USDT", "AVAX/USDT", 
    "SUI/USDT", "NEAR/USDT", "WIF/USDT", "APT/USDT", "LINK/USDT", 
    "ADA/USDT", "FET/USDT", "RENDER/USDT", "TAO/USDT", "AR/USDT", "PENDLE/USDT"
]

# Binance Futures'taki 1000x / 1000000x çarpanlı meme coin haritası
FUTURES_MULTIPLIER_MAP = {
    'SHIB': '1000SHIB',
    'BONK': '1000BONK',
    'PEPE': '1000PEPE',
    'FLOKI': '1000FLOKI',
    'SATS': '1000SATS',
    'LUNC': '1000LUNC',
    'RATS': '1000RATS',
    'CAT': '1000CAT',
    'MOG': '1000000MOG',
    'BOB': '1000000BOB',
    'CHEEMS': '1000CHEEMS',
    'WHY': '1000WHY',
    'XEC': '1000XEC',
}

# Arama takma adları (Kullanıcı SHIBA veya BITCOIN yazsa da bulsun)
SEARCH_ALIASES = {
    "SHIBA": "SHIB",
    "SHIBAINU": "SHIB",
    "SHIB": "SHIB",
    "BONK": "BONK",
    "PEPE": "PEPE",
    "FLOKI": "FLOKI",
    "DOGECOIN": "DOGE",
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "SOLANA": "SOL",
    "RIPPLE": "XRP",
    "CARDANO": "ADA",
    "POLYGON": "MATIC",
    "AVALANCHE": "AVAX",
    "LUNC": "LUNC",
    "LUNA": "LUNC"
}

# Kripto Para Sektör / Kategori ve İsim Haritası (Binance Markets UI için)
COIN_METADATA = {
    'BTC': {'name': 'Bitcoin', 'categories': ['Layer 1 / Layer 2', 'bStocks 🔥', 'TradFi', 'Payments']},
    'ETH': {'name': 'Ethereum', 'categories': ['Layer 1 / Layer 2', 'bStocks 🔥', 'TradFi', 'DeFi']},
    'SOL': {'name': 'Solana', 'categories': ['Solana', 'Layer 1 / Layer 2', 'bStocks 🔥', 'DeFi']},
    'BNB': {'name': 'BNB Chain', 'categories': ['BSC', 'Layer 1 / Layer 2', 'bStocks 🔥', 'Launchpool']},
    'XRP': {'name': 'XRP', 'categories': ['Payments', 'Layer 1 / Layer 2', 'bStocks 🔥']},
    'USDT': {'name': 'Tether USD', 'categories': ['TradFi', 'Payments']},
    'USDC': {'name': 'USD Coin', 'categories': ['TradFi', 'Payments']},
    'DOGE': {'name': 'Dogecoin', 'categories': ['MEME', 'Payments', 'bStocks 🔥']},
    'SHIB': {'name': 'Shiba Inu', 'categories': ['MEME', 'bStocks 🔥']},
    '1000SHIB': {'name': '1000 Shiba Inu', 'categories': ['MEME', 'bStocks 🔥']},
    'PEPE': {'name': 'Pepe', 'categories': ['MEME', 'bStocks 🔥']},
    '1000PEPE': {'name': '1000 Pepe', 'categories': ['MEME', 'bStocks 🔥']},
    'BONK': {'name': 'Bonk', 'categories': ['MEME', 'Solana', 'bStocks 🔥']},
    '1000BONK': {'name': '1000 Bonk', 'categories': ['MEME', 'Solana', 'bStocks 🔥']},
    'FLOKI': {'name': 'Floki', 'categories': ['MEME', 'BSC', 'Gaming']},
    '1000FLOKI': {'name': '1000 Floki', 'categories': ['MEME', 'BSC', 'Gaming']},
    'WIF': {'name': 'dogwifhat', 'categories': ['MEME', 'Solana']},
    'BOME': {'name': 'BOOK OF MEME', 'categories': ['MEME', 'Solana']},
    'MEW': {'name': 'cat in a dogs world', 'categories': ['MEME', 'Solana']},
    '1000SATS': {'name': 'SATS Ordinals', 'categories': ['MEME', 'Layer 1 / Layer 2']},
    'NEIRO': {'name': 'Neiro First CT', 'categories': ['MEME']},
    'TURBO': {'name': 'Turbo', 'categories': ['MEME', 'AI']},
    'BABYDOGE': {'name': 'Baby Doge Coin', 'categories': ['MEME', 'BSC']},
    'MEME': {'name': 'Memecoin', 'categories': ['MEME', 'Launchpool']},
    'NEAR': {'name': 'NEAR Protocol', 'categories': ['AI', 'Layer 1 / Layer 2']},
    'RENDER': {'name': 'Render', 'categories': ['AI', 'Solana']},
    'FET': {'name': 'Artificial Superintelligence', 'categories': ['AI']},
    'TAO': {'name': 'Bittensor', 'categories': ['AI', 'Layer 1 / Layer 2']},
    'ICP': {'name': 'Internet Computer', 'categories': ['AI', 'Layer 1 / Layer 2']},
    'ARKM': {'name': 'Arkham', 'categories': ['AI']},
    'WLD': {'name': 'Worldcoin', 'categories': ['AI', 'Layer 1 / Layer 2']},
    'GRT': {'name': 'The Graph', 'categories': ['AI', 'DeFi']},
    'SUI': {'name': 'Sui Network', 'categories': ['Layer 1 / Layer 2', 'bStocks 🔥', 'Launchpool']},
    'APT': {'name': 'Aptos', 'categories': ['Layer 1 / Layer 2']},
    'AVAX': {'name': 'Avalanche', 'categories': ['Layer 1 / Layer 2', 'DeFi']},
    'ADA': {'name': 'Cardano', 'categories': ['Layer 1 / Layer 2']},
    'DOT': {'name': 'Polkadot', 'categories': ['Layer 1 / Layer 2']},
    'ATOM': {'name': 'Cosmos', 'categories': ['Layer 1 / Layer 2']},
    'LINK': {'name': 'Chainlink', 'categories': ['DeFi', 'RWA']},
    'UNI': {'name': 'Uniswap', 'categories': ['DeFi']},
    'AAVE': {'name': 'Aave', 'categories': ['DeFi']},
    'MKR': {'name': 'Maker', 'categories': ['DeFi', 'RWA']},
    'PENDLE': {'name': 'Pendle', 'categories': ['DeFi', 'RWA']},
    'ONDO': {'name': 'Ondo Finance', 'categories': ['RWA', 'DeFi']},
    'OM': {'name': 'MANTRA', 'categories': ['RWA', 'Layer 1 / Layer 2']},
    'JUP': {'name': 'Jupiter', 'categories': ['Solana', 'DeFi']},
    'RAY': {'name': 'Raydium', 'categories': ['Solana', 'DeFi']},
    'PYTH': {'name': 'Pyth Network', 'categories': ['Solana', 'DeFi']},
    'GALA': {'name': 'GALA Games', 'categories': ['Gaming']},
    'SAND': {'name': 'The Sandbox', 'categories': ['Gaming']},
    'AXS': {'name': 'Axie Infinity', 'categories': ['Gaming']},
    'MANA': {'name': 'Decentraland', 'categories': ['Gaming']},
    'PIXEL': {'name': 'Pixels', 'categories': ['Gaming', 'Launchpool']},
    'PORTAL': {'name': 'Portal', 'categories': ['Gaming', 'Launchpool']},
    'LTC': {'name': 'Litecoin', 'categories': ['Payments', 'Layer 1 / Layer 2']},
    'BCH': {'name': 'Bitcoin Cash', 'categories': ['Payments']},
    'XLM': {'name': 'Stellar', 'categories': ['Payments']},
    'TIA': {'name': 'Celestia', 'categories': ['Layer 1 / Layer 2', 'Launchpool']},
    'SEI': {'name': 'Sei', 'categories': ['Layer 1 / Layer 2', 'Launchpool']},
    'INJ': {'name': 'Injective', 'categories': ['Layer 1 / Layer 2', 'DeFi']},
    'ARB': {'name': 'Arbitrum', 'categories': ['Layer 1 / Layer 2']},
    'OP': {'name': 'Optimism', 'categories': ['Layer 1 / Layer 2']},
    'KAS': {'name': 'Kaspa', 'categories': ['Layer 1 / Layer 2']},
    'FTM': {'name': 'Fantom', 'categories': ['Layer 1 / Layer 2', 'DeFi']},
    'ALGO': {'name': 'Algorand', 'categories': ['Layer 1 / Layer 2']},
    'HBAR': {'name': 'Hedera', 'categories': ['Layer 1 / Layer 2']},
    'CAKE': {'name': 'PancakeSwap', 'categories': ['BSC', 'DeFi']},
    'CRV': {'name': 'Curve DAO', 'categories': ['DeFi']},
    'DYDX': {'name': 'dYdX', 'categories': ['DeFi']},
    'RUNE': {'name': 'THORChain', 'categories': ['DeFi']},
}


class BinanceDataFetcher:
    """
    Binance Futures (USDT-M) ve Spot üzerindeki 1,600+ coini eksiksiz çeken,
    SHIB, BONK, PEPE gibi çarpanlı vadeli coinleri akıllıca çözen ve canlı akış sağlayan servis.
    """

    def __init__(self):
        # 1. Binance Vadeli İşlemler (Futures USDT-M)
        self.futures_exchange = ccxt.binance({
            'enableRateLimit': True,
            'timeout': 5000,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True
            }
        })
        # 2. Binance Spot (Yedek & Spot-only coinler için)
        self.spot_exchange = ccxt.binance({
            'enableRateLimit': True,
            'timeout': 5000,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True
            }
        })
        self._cached_symbols: List[str] = []
        self._ticker_cache: Dict[str, Tuple[Any, str]] = {}
        self._ohlcv_cache: Dict[str, Tuple[Any, str]] = {}
        self._market_overview_cache: Optional[List[Dict[str, Any]]] = None
        self._market_overview_time: float = 0.0

    def _resolve_exchange_and_symbol(self, symbol: str) -> Tuple[ccxt.binance, str]:
        """
        Kullanıcının girdiği sembolü (örn: 'SHIB/USDT', 'BONK/USDT', '1000SHIB/USDT', 'BTC/USDT')
        Binance Futures'taki gerçek vadeli işlem kontratına veya Spot piyasasına yönlendirir.
        """
        sym = symbol.strip().upper()
        if ":" in sym:
            return self.futures_exchange, sym

        base = sym.split('/')[0]
        quote = sym.split('/')[1] if '/' in sym else 'USDT'

        candidates = []
        # 1. Eğer SHIB, BONK gibi bir meme coin ise 1000SHIB/USDT:USDT formatını öncelikli dene
        if base in FUTURES_MULTIPLIER_MAP:
            mult_base = FUTURES_MULTIPLIER_MAP[base]
            candidates.append((self.futures_exchange, f"{mult_base}/{quote}:USDT"))
            candidates.append((self.futures_exchange, f"{mult_base}/{quote}"))

        # 2. Standart Futures formatları
        candidates.append((self.futures_exchange, f"{base}/{quote}:USDT"))
        candidates.append((self.futures_exchange, f"{base}/{quote}"))

        # 3. Spot formatı
        candidates.append((self.spot_exchange, f"{base}/{quote}"))

        return candidates[0]

    def fetch_all_futures_symbols(self) -> List[str]:
        """
        Binance üzerindeki TÜM USDT paritelerini (Futures + Spot + Çarpanlı Meme Coinler) çeker.
        Hafif doğrudan REST sorgusu ile ccxt load_markets yükünü kaldırarak RAM tasarrufu sağlar.
        """
        if self._cached_symbols:
            return self._cached_symbols

        import requests
        import gc
        symbols_set = set()

        # 1. Futures paritelerini çek
        try:
            r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr', timeout=8).json()
            for item in r:
                s = item.get('symbol', '')
                if s.endswith('USDT'):
                    base = s[:-4]
                    symbols_set.add(f"{base}/USDT")
                    if base.startswith('1000') or base.startswith('1000000'):
                        clean_base = base.lstrip('0123456789')
                        symbols_set.add(f"{clean_base}/USDT")
            del r
            gc.collect()
        except Exception as e:
            logger.warning(f"Futures piyasaları yüklenirken hata: {e}")

        # 2. Spot paritelerini çek (Binance'deki tüm diğer coinler)
        try:
            r = requests.get('https://api.binance.com/api/v3/ticker/24hr', timeout=8).json()
            for item in r:
                s = item.get('symbol', '')
                if s.endswith('USDT'):
                    base = s[:-4]
                    symbols_set.add(f"{base}/USDT")
            del r
            gc.collect()
        except Exception as e:
            logger.warning(f"Spot piyasaları yüklenirken hata: {e}")

        # Popüler pariteleri en başa al
        ordered_symbols = []
        for p in POPULAR_PAIRS:
            if p in symbols_set:
                ordered_symbols.append(p)
                symbols_set.remove(p)

        # Kalanları alfabetik sırala
        ordered_symbols.extend(sorted(list(symbols_set)))
        self._cached_symbols = ordered_symbols
        return self._cached_symbols

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Herhangi bir Binance coini için anlık fiyat ve 24s istatistiğini çeker.
        SHIB/USDT ve BONK/USDT gibi sembolleri otomatik olarak vadeli kontrata bağlar.
        """
        sym = symbol.strip().upper()
        base = sym.split('/')[0]
        quote = sym.split('/')[1] if '/' in sym else 'USDT'

        # Denenecek aday semboller ve borsalar
        candidates = []
        if base in FUTURES_MULTIPLIER_MAP:
            mult_base = FUTURES_MULTIPLIER_MAP[base]
            candidates.append((self.futures_exchange, f"{mult_base}/{quote}:USDT"))
        candidates.append((self.futures_exchange, f"{base}/{quote}:USDT"))
        candidates.append((self.futures_exchange, f"{base}/{quote}"))
        candidates.append((self.spot_exchange, f"{base}/{quote}"))

        ticker = None
        used_symbol = sym

        # 1. Önbellekten dene
        if sym in self._ticker_cache:
            ex_cached, cand_cached = self._ticker_cache[sym]
            try:
                ticker = ex_cached.fetch_ticker(cand_cached)
                used_symbol = cand_cached
            except Exception:
                ticker = None

        # 2. Önbellekte yoksa veya başarısız olduysa adayları dene
        if not ticker:
            for ex, candidate in candidates:
                try:
                    ticker = ex.fetch_ticker(candidate)
                    used_symbol = candidate
                    self._ticker_cache[sym] = (ex, candidate)
                    break
                except Exception:
                    continue

        if not ticker:
            ticker = self.spot_exchange.fetch_ticker(f"{base}/{quote}")
            self._ticker_cache[sym] = (self.spot_exchange, f"{base}/{quote}")

        last_price = float(ticker.get('last') or 0.0)
        change_pct = float(ticker.get('percentage') or 0.0)
        high_24h = float(ticker.get('high') or 0.0)
        low_24h = float(ticker.get('low') or 0.0)
        volume_24h = float(ticker.get('quoteVolume') or ticker.get('baseVolume') or 0.0)

        return {
            "symbol": sym,
            "actual_symbol": used_symbol,
            "price": last_price,
            "change_pct": round(change_pct, 2),
            "high": high_24h,
            "low": low_24h,
            "volume": volume_24h
        }

    def fetch_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 100) -> Tuple[pd.DataFrame, str]:
        """
        Binance Vadeli veya Spot üzerinden son 'limit' adet mumu çeker.
        """
        sym = symbol.strip().upper()
        base = sym.split('/')[0]
        quote = sym.split('/')[1] if '/' in sym else 'USDT'

        candidates = []
        if base in FUTURES_MULTIPLIER_MAP:
            mult_base = FUTURES_MULTIPLIER_MAP[base]
            candidates.append((self.futures_exchange, f"{mult_base}/{quote}:USDT"))
        candidates.append((self.futures_exchange, f"{base}/{quote}:USDT"))
        candidates.append((self.futures_exchange, f"{base}/{quote}"))
        candidates.append((self.spot_exchange, f"{base}/{quote}"))

        ohlcv = None
        matched_symbol = sym

        # 1. Önbellekten dene
        if sym in self._ohlcv_cache:
            ex_cached, cand_cached = self._ohlcv_cache[sym]
            try:
                ohlcv = ex_cached.fetch_ohlcv(cand_cached, timeframe=timeframe, limit=limit)
                if ohlcv and len(ohlcv) >= 10:
                    matched_symbol = cand_cached
                else:
                    ohlcv = None
            except Exception:
                ohlcv = None

        # 2. Önbellek yoksa adayları tara
        if not ohlcv:
            for ex, candidate in candidates:
                try:
                    ohlcv = ex.fetch_ohlcv(candidate, timeframe=timeframe, limit=limit)
                    if ohlcv and len(ohlcv) >= 10:
                        matched_symbol = candidate
                        self._ohlcv_cache[sym] = (ex, candidate)
                        break
                except Exception:
                    continue

        if not ohlcv or len(ohlcv) < 10:
            raise ValueError(f"'{symbol}' için Binance üzerinde yeterli mum verisi bulunamadı.")

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        return df, matched_symbol

    def fetch_order_book(self, symbol: str, limit: int = 7) -> Dict[str, Any]:
        """Binance Futures anlık alış ve satış emir tahtasını çeker."""
        sym = symbol.strip().upper()
        if sym in self._ohlcv_cache:
            ex, cand = self._ohlcv_cache[sym]
            try:
                ob = ex.fetch_order_book(cand, limit=limit)
                return {
                    "bids": ob.get("bids", [])[:limit],
                    "asks": ob.get("asks", [])[:limit]
                }
            except Exception:
                pass
        try:
            ex, actual = self._resolve_exchange_and_symbol(sym)
            ob = ex.fetch_order_book(actual, limit=limit)
            return {
                "bids": ob.get("bids", [])[:limit],
                "asks": ob.get("asks", [])[:limit]
            }
        except Exception:
            return {"bids": [], "asks": []}

    def _calculate_indicators_pandas(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']

        # 1. EMA (50 ve 200)
        df['EMA_50'] = close.ewm(span=50, adjust=False, min_periods=5).mean()
        df['EMA_200'] = close.ewm(span=200, adjust=False, min_periods=5).mean()

        # 2. RSI (14) - Wilder's Smoothing
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()

        rs = avg_gain / (avg_loss + 1e-10)
        df['RSI_14'] = 100 - (100 / (1 + rs))

        # 3. MACD (12, 26, 9)
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_12 - ema_26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        # 4. ATR (14)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR_14'] = tr.ewm(span=14, adjust=False).mean()

        return df

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._calculate_indicators_pandas(df)

    def get_latest_market_summary(self, symbol: str, timeframe: str = '15m', limit: int = 100) -> Dict[str, Any]:
        df, actual_sym = self.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
        df = self.calculate_indicators(df)

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        current_price = float(latest['close'])
        open_price = float(latest['open'])
        high_price = float(latest['high'])
        low_price = float(latest['low'])
        volume = float(latest['volume'])

        rsi = float(latest.get('RSI_14', 50.0)) if not pd.isna(latest.get('RSI_14')) else 50.0
        macd = float(latest.get('MACD', 0.0)) if not pd.isna(latest.get('MACD')) else 0.0
        macd_signal = float(latest.get('MACD_Signal', 0.0)) if not pd.isna(latest.get('MACD_Signal')) else 0.0
        macd_hist = float(latest.get('MACD_Hist', 0.0)) if not pd.isna(latest.get('MACD_Hist')) else 0.0

        ema50 = float(latest.get('EMA_50', current_price)) if not pd.isna(latest.get('EMA_50')) else current_price
        ema200 = float(latest.get('EMA_200', current_price)) if not pd.isna(latest.get('EMA_200')) else current_price
        atr = float(latest.get('ATR_14', current_price * 0.01)) if not pd.isna(latest.get('ATR_14')) else current_price * 0.01

        summary = {
            "symbol": symbol.upper().split(':')[0],
            "actual_contract": actual_sym,
            "timeframe": timeframe,
            "candles_analyzed": len(df),
            "current_price": current_price,
            "candle_ohlcv": {
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": current_price,
                "volume": volume
            },
            "previous_close": float(prev['close']),
            "price_change_pct": round(((current_price - float(prev['close'])) / float(prev['close'])) * 100, 3),
            "indicators": {
                "rsi_14": round(rsi, 2),
                "macd": round(macd, 4),
                "macd_signal": round(macd_signal, 4),
                "macd_histogram": round(macd_hist, 4),
                "ema_50": round(ema50, 4),
                "ema_200": round(ema200, 4),
                "atr_14": round(atr, 4)
            },
            "recent_candles": df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(5).to_dict(orient='records')
        }

        return summary

    def fetch_candlestick_data(self, symbol: str, timeframe: str = '15m', limit: int = 80) -> pd.DataFrame:
        """
        Grafik çizimi için 1m, 2m, 3m, 5m, 15m, 30m, 1h, 2h, 5h, 15h, 1w, 1y, 5y
        zaman dilimlerini akıllıca çeker ve resample eder.
        """
        tf = timeframe.lower()
        
        direct_map = {
            '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', 
            '30m': '30m', '1h': '1h', '2h': '2h', '1w': '1w', '1m_month': '1M'
        }
        
        if tf in direct_map:
            df, _ = self.fetch_ohlcv(symbol, timeframe=direct_map[tf], limit=limit)
            return self.calculate_indicators(df)
            
        # Özel zaman dilimleri için akıllı resampling
        if tf == '2m':
            df, _ = self.fetch_ohlcv(symbol, timeframe='1m', limit=min(limit*2, 300))
            rule = '2min'
        elif tf == '5h':
            df, _ = self.fetch_ohlcv(symbol, timeframe='1h', limit=min(limit*5, 300))
            rule = '5h'
        elif tf == '15h':
            df, _ = self.fetch_ohlcv(symbol, timeframe='1h', limit=min(limit*15, 500))
            rule = '15h'
        elif tf in ['1y', '1senelik']:
            df, _ = self.fetch_ohlcv(symbol, timeframe='1w', limit=min(limit*52, 500))
            rule = '1YE'
        elif tf in ['5y', '5senelik']:
            df, _ = self.fetch_ohlcv(symbol, timeframe='1w', limit=min(limit*52, 500))
            rule = '5YE'
        else:
            df, _ = self.fetch_ohlcv(symbol, timeframe='15m', limit=limit)
            return self.calculate_indicators(df)
            
        # Resample işlemi
        df = df.copy()
        df.set_index('datetime', inplace=True)
        resampled = df.resample(rule).agg({
            'timestamp': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            resampled[col] = pd.to_numeric(resampled[col], errors='coerce')
            
        return self.calculate_indicators(resampled)

    def fetch_all_market_overview(self) -> List[Dict[str, Any]]:
        """
        Binance üzerindeki tüm USDT paritelerini (650+ token) 24s fiyat, değişim, hacim
        ve sektör kategorileriyle (MEME, AI, Solana, L1/L2, DeFi vb.) çeker.
        Doğrudan hafif REST API ve 20 saniyelik RAM önbelleği ile bellek tüketimini 5 MB altında tutar.
        """
        import time
        import requests
        import gc

        # 20 saniye önbellek geçerliyse anında döndür (RAM ve CPU tüketmez)
        now = time.time()
        if self._market_overview_cache and (now - self._market_overview_time) < 20.0:
            return self._market_overview_cache

        results = []
        raw_items = []
        try:
            raw_items = requests.get('https://api.binance.com/api/v3/ticker/24hr', timeout=8).json()
        except Exception as e:
            logger.warning(f"Spot tickers çekilemedi, vadeli deneniyor: {e}")
            try:
                raw_items = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr', timeout=8).json()
            except Exception as e2:
                logger.error(f"Piyasa verisi çekilemedi: {e2}")
                return self._market_overview_cache or []

        for item in raw_items:
            sym = item.get('symbol', '')
            if not sym.endswith('USDT'):
                continue
            last = float(item.get('lastPrice') or 0.0)
            if last <= 0:
                continue

            base = sym[:-4]
            pct = float(item.get('priceChangePercent') or 0.0)
            quote_vol = float(item.get('quoteVolume') or 0.0)
            high_24h = float(item.get('highPrice') or last)
            low_24h = float(item.get('lowPrice') or last)

            meta = COIN_METADATA.get(base, {})
            name = meta.get('name', base)
            categories = list(meta.get('categories', ['Layer 1 / Layer 2']))
            if 'All' not in categories:
                categories.append('All')

            # Tahmini Piyasa Değeri
            est_mcap = quote_vol * (15.0 if base in ['BTC', 'ETH'] else (8.0 if base in ['BNB', 'SOL', 'XRP'] else 3.5))

            results.append({
                'symbol': f"{base}/USDT",
                'base': base,
                'name': name,
                'price': last,
                'change_24h': pct,
                'volume_24h': quote_vol,
                'market_cap': est_mcap,
                'high_24h': high_24h,
                'low_24h': low_24h,
                'categories': categories,
            })

        del raw_items
        gc.collect()

        # Hacme göre azalan sırala (Top tokens by volume)
        results.sort(key=lambda x: x['volume_24h'], reverse=True)
        self._market_overview_cache = results
        self._market_overview_time = now
        return results

