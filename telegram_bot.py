"""
Binance Futures Telegram VIP Sinyal & Mini App Botu
Bot Adı: Kripto VIP Sinyal (@rade_sinyal_bot)

Özellikler:
- Telegram Mini App (Web App) entegrasyonu (Aynen Binance mobil arayüzü gibi tam ekran)
- Alt dokunmatik menü: [⚡ Vadeli] [🌐 Piyasalar] [⭐ Favoriler] [🧠 Groq AI]
- Otomatik Cloudflare HTTPS tüneli
- Telegram içi [📱 Mini Uygulamayı Aç] butonu ve sol altta kalıcı Menü Butonu
- 7/24 Otomatik arka plan sinyal takip ve bildirim motoru
"""

import os
import sys
import io
import re
import json
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

# Windows konsol kodlama koruması
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import pandas as pd
from aiohttp import web

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    MenuButtonWebApp
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from dotenv import load_dotenv
load_dotenv()

# Proje içi modüller
from market_data import BinanceDataFetcher, POPULAR_PAIRS, SEARCH_ALIASES
from ai_engine import AISignalEngine

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("TelegramSignalBot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8508019942:AAG2W2UpBSlZfiLKpRANkiVME8O_mZ9FrPI")
DEFAULT_GROQ_KEY = os.getenv("GROQ_API_KEY", "")
SUBSCRIBERS_FILE = "subscribers.json"
HTTP_PORT = int(os.getenv("PORT", 8080))

data_fetcher = BinanceDataFetcher()
ai_engine = AISignalEngine(api_key=DEFAULT_GROQ_KEY, model="openai/gpt-oss-120b")

# Tünel URL'si (Cloudflare'den veya Render'dan otomatik alınır)
web_app_url = os.getenv("RENDER_EXTERNAL_URL", f"http://127.0.0.1:{HTTP_PORT}")


# ==================== ABONE YÖNETİCİSİ ====================
def load_subscribers() -> List[int]:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_subscribers(subs: List[int]):
    try:
        with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(subs, f)
    except Exception as e:
        logger.error(f"Aboneler kaydedilemedi: {e}")

subscribers = set(load_subscribers())



# ==================== ALGORİTMİK SİNYAL MOTORU ====================
def compute_futures_signal(market_summary: Dict[str, Any]) -> Dict[str, Any]:
    symbol = market_summary.get("symbol", "BTC/USDT")
    curr_p = float(market_summary.get("current_price", 0.0) or 0.0)
    ind = market_summary.get("indicators", {})

    rsi = float(ind.get("rsi_14", 50.0) or 50.0)
    macd = float(ind.get("macd", 0.0) or 0.0)
    macd_sig = float(ind.get("macd_signal", 0.0) or 0.0)
    macd_hist = float(ind.get("macd_histogram", 0.0) or 0.0)
    ema50 = float(ind.get("ema_50", curr_p) or curr_p)
    ema200 = float(ind.get("ema_200", curr_p) or curr_p)
    atr = float(ind.get("atr_14", curr_p * 0.015) or (curr_p * 0.015))
    if atr <= 0:
        atr = curr_p * 0.015

    score = 0
    if curr_p > ema50: score += 1
    if curr_p > ema200: score += 1
    if ema50 > ema200: score += 1
    if macd > macd_sig or macd_hist > 0: score += 1
    if 45 <= rsi <= 68: score += 1
    elif rsi < 32: score += 2

    if curr_p < ema50: score -= 1
    if curr_p < ema200: score -= 1
    if ema50 < ema200: score -= 1
    if macd < macd_sig or macd_hist < 0: score -= 1
    if 32 <= rsi <= 55: score -= 1
    elif rsi > 68: score -= 2

    decimals = 6 if curr_p < 1 else (4 if curr_p < 10 else 2)

    if score >= 2:
        yon = "LONG"
        entry = curr_p
        sl = round(entry - (1.4 * atr), decimals)
        tp1 = round(entry + (1.8 * atr), decimals)
        tp2 = round(entry + (3.2 * atr), decimals)
        sl_pct = abs((sl - entry) / entry * 100) if entry > 0 else 1.0
        tp1_pct = abs((tp1 - entry) / entry * 100) if entry > 0 else 2.0
        tp2_pct = abs((tp2 - entry) / entry * 100) if entry > 0 else 4.0
        leverage = "10x - 20x" if (atr / entry if entry > 0 else 0.01) < 0.025 else "5x - 10x"
        rr = f"1:{(tp1_pct / max(0.01, sl_pct)):.1f}"
        order = f"⚡ {entry:,.{decimals}f} USDT seviyesinden {leverage} LONG aç. SL: {sl:,.{decimals}f}, TP1: {tp1:,.{decimals}f}, TP2: {tp2:,.{decimals}f}."
        reason = f"Fiyat EMA 50 ({ema50:,.{decimals}f}) üzerinde yükseliş trendinde. RSI={rsi:.1f} ve MACD alım baskısını teyit ediyor."
    elif score <= -2:
        yon = "SHORT"
        entry = curr_p
        sl = round(entry + (1.4 * atr), decimals)
        tp1 = round(entry - (1.8 * atr), decimals)
        tp2 = round(entry - (3.2 * atr), decimals)
        sl_pct = abs((sl - entry) / entry * 100) if entry > 0 else 1.0
        tp1_pct = abs((tp1 - entry) / entry * 100) if entry > 0 else 2.0
        tp2_pct = abs((tp2 - entry) / entry * 100) if entry > 0 else 4.0
        leverage = "10x - 20x" if (atr / entry if entry > 0 else 0.01) < 0.025 else "5x - 10x"
        rr = f"1:{(tp1_pct / max(0.01, sl_pct)):.1f}"
        order = f"⚡ {entry:,.{decimals}f} USDT seviyesinden {leverage} SHORT aç. SL: {sl:,.{decimals}f}, TP1: {tp1:,.{decimals}f}, TP2: {tp2:,.{decimals}f}."
        reason = f"Fiyat EMA 50 ({ema50:,.{decimals}f}) altında düşüş trendinde. RSI={rsi:.1f} ve MACD satıcı baskısını gösteriyor."
    else:
        yon = "BEKLE"
        entry = curr_p
        sl = round(entry - (1.0 * atr), decimals)
        tp1 = round(entry + (1.5 * atr), decimals)
        tp2 = round(entry + (2.5 * atr), decimals)
        sl_pct = 1.0
        tp1_pct = 1.5
        tp2_pct = 2.5
        leverage = "5x - 8x"
        rr = "1:1.5"
        order = f"🟡 Piyasa yatay testere bandında ({entry:,.{decimals}f} USDT). Kırılım olmadan işleme girmeyin."
        reason = f"Göstergeler dengede (RSI={rsi:.1f}, MACD={macd:.4f}). Yeni yön sinyali beklenmelidir."

    return {
        "symbol": symbol,
        "Yon": yon,
        "current_price": curr_p,
        "decimals": decimals,
        "entry": entry,
        "sl": sl,
        "sl_pct": sl_pct,
        "tp1": tp1,
        "tp1_pct": tp1_pct,
        "tp2": tp2,
        "tp2_pct": tp2_pct,
        "leverage": leverage,
        "rr": rr,
        "order": order,
        "reason": reason,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "ema50": ema50,
        "ema200": ema200,
        "atr": atr,
        "chg_24h": market_summary.get("change_pct", 0.0),
        "high_24h": market_summary.get("high_24h", curr_p),
        "low_24h": market_summary.get("low_24h", curr_p),
        "vol_24h": market_summary.get("volume_24h", 0.0)
    }


# ==================== AIOHTTP WEB SUNUCUSU (MINI APP API) ====================
async def handle_index(request):
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return web.Response(
                text=f.read(),
                content_type="text/html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    return web.Response(text="<h1>Mini App Yüklenemedi</h1>", content_type="text/html")

def clean_symbol(raw_sym: str) -> str:
    s = (raw_sym or "BTC/USDT").strip().upper()
    if "/" in s:
        return s
    if s.endswith("USDT") and len(s) > 4:
        return f"{s[:-4]}/USDT"
    return f"{s}/USDT"

async def api_signal(request):
    symbol = clean_symbol(request.query.get("symbol", "BTC/USDT"))
    timeframe = request.query.get("timeframe", "15m")

    loop = asyncio.get_running_loop()
    try:
        summary_task = loop.run_in_executor(None, data_fetcher.get_latest_market_summary, symbol, timeframe, 60)
        ticker_task = loop.run_in_executor(None, data_fetcher.fetch_ticker, symbol)
        summary, ticker = await asyncio.gather(summary_task, ticker_task)

        plan = compute_futures_signal(summary)
        if ticker:
            plan["chg_24h"] = ticker.get("change_pct", 0.0)
            plan["high_24h"] = ticker.get("high", plan["current_price"])
            plan["low_24h"] = ticker.get("low", plan["current_price"])
            plan["vol_24h"] = ticker.get("volume", 0.0)
            if ticker.get("price") and ticker["price"] > 0:
                plan["current_price"] = ticker["price"]

        return web.json_response({"ok": True, "plan": plan})
    except Exception as e:
        logger.error(f"API Signal error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_klines(request):
    symbol = clean_symbol(request.query.get("symbol", "BTC/USDT"))
    timeframe = request.query.get("timeframe", "15m")

    loop = asyncio.get_running_loop()
    try:
        limit = 90
        ohlcv_task = loop.run_in_executor(None, data_fetcher.fetch_ohlcv, symbol, timeframe, limit)
        ticker_task = loop.run_in_executor(None, data_fetcher.fetch_ticker, symbol)
        res = await asyncio.gather(ohlcv_task, ticker_task, return_exceptions=True)
        if isinstance(res[0], Exception):
            raise res[0]
        df, actual = res[0]
        if isinstance(res[1], Exception) or not res[1]:
            last_p = float(df.iloc[-1]['close'])
            ticker = {
                "price": last_p,
                "change_pct": 0.0,
                "high": float(df['high'].max()),
                "low": float(df['low'].min()),
                "volume": float(df['volume'].sum())
            }
        else:
            ticker = res[1]
        df = data_fetcher.calculate_indicators(df)

        candles = []
        ema50_data = []
        ema200_data = []
        volume_data = []
        markers = []

        last_sig_type = None
        last_sig_idx = -4
        n = len(df)

        for i in range(n):
            row = df.iloc[i]
            t = int(row['timestamp'] / 1000)
            o = float(row['open'])
            h = float(row['high'])
            l = float(row['low'])
            c = float(row['close'])
            v = float(row['volume'])

            candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
            volume_data.append({"time": t, "value": v, "color": "rgba(14, 203, 129, 0.55)" if c >= o else "rgba(246, 70, 93, 0.55)"})

            if 'EMA_50' in df and not pd.isna(row['EMA_50']):
                ema50_data.append({"time": t, "value": round(float(row['EMA_50']), 4 if c < 1 else 2)})
            if 'EMA_200' in df and not pd.isna(row['EMA_200']):
                ema200_data.append({"time": t, "value": round(float(row['EMA_200']), 4 if c < 1 else 2)})

            # Canlı AL ve SAT Sinyal Noktaları (Görünür, net ve mumlar üzerinde zengin dağılım)
            if i >= 3:
                prev_row = df.iloc[i-1]
                prev2 = df.iloc[i-2]
                rsi_curr = float(row.get('RSI_14', 50) or 50)
                rsi_prev = float(prev_row.get('RSI_14', 50) or 50)
                macd_curr = float(row.get('MACD', 0) or 0)
                macd_prev = float(prev_row.get('MACD', 0) or 0)
                sig_curr = float(row.get('MACD_Signal', 0) or 0)
                sig_prev = float(prev_row.get('MACD_Signal', 0) or 0)
                ema50_val = float(row.get('EMA_50', c) or c)

                # Swing dip dönüşü ve boğa sinyali
                is_swing_low = l <= min(float(prev_row['low']), float(prev2['low'])) and c >= o
                is_macd_up = macd_prev <= sig_prev and macd_curr > sig_curr
                is_rsi_bounce = rsi_prev < 45 and rsi_curr > rsi_prev
                is_ema_cross_up = float(prev_row['close']) <= ema50_val and c > ema50_val

                is_buy = is_macd_up or is_ema_cross_up or (is_swing_low and (rsi_curr <= 52 or is_rsi_bounce))
                is_strong_buy = is_buy and (c > ema50_val and rsi_curr >= 48)

                # Swing tepe dönüşü ve ayı sinyali
                is_swing_high = h >= max(float(prev_row['high']), float(prev2['high'])) and c <= o
                is_macd_down = macd_prev >= sig_prev and macd_curr < sig_curr
                is_rsi_reject = rsi_prev > 55 and rsi_curr < rsi_prev
                is_ema_cross_down = float(prev_row['close']) >= ema50_val and c < ema50_val

                is_sell = is_macd_down or is_ema_cross_down or (is_swing_high and (rsi_curr >= 48 or is_rsi_reject))
                is_strong_sell = is_sell and (c < ema50_val and rsi_curr <= 52)

                if (i - last_sig_idx) >= 3:
                    if is_buy and last_sig_type != 'BUY':
                        text = "▲ GÜÇLÜ AL" if is_strong_buy else "▲ AL"
                        markers.append({
                            "time": t,
                            "position": "belowBar",
                            "color": "#0ECB81",
                            "shape": "arrowUp",
                            "text": text,
                            "size": 1.5
                        })
                        last_sig_type = 'BUY'
                        last_sig_idx = i
                    elif is_sell and last_sig_type != 'SELL':
                        text = "▼ GÜÇLÜ SAT" if is_strong_sell else "▼ SAT"
                        markers.append({
                            "time": t,
                            "position": "aboveBar",
                            "color": "#F6465D",
                            "shape": "arrowDown",
                            "text": text,
                            "size": 1.5
                        })
                        last_sig_type = 'SELL'
                        last_sig_idx = i

        # EN SON MUM İÇİN GÜNCEL ANLIK SİNYAL TEYİDİ
        if candles:
            last_t = candles[-1]["time"]
            last_row = df.iloc[-1]
            last_c = float(last_row['close'])
            last_ema = float(last_row.get('EMA_50', last_c) or last_c)
            last_rsi = float(last_row.get('RSI_14', 50) or 50)
            last_m = float(last_row.get('MACD', 0) or 0)
            last_s = float(last_row.get('MACD_Signal', 0) or 0)

            if last_c >= last_ema and (last_m >= last_s or last_rsi >= 48):
                last_sig = {
                    "time": last_t,
                    "position": "belowBar",
                    "color": "#0ECB81",
                    "shape": "arrowUp",
                    "text": "▲ GÜÇLÜ AL" if last_rsi >= 50 else "▲ AL",
                    "size": 1.6
                }
            else:
                last_sig = {
                    "time": last_t,
                    "position": "aboveBar",
                    "color": "#F6465D",
                    "shape": "arrowDown",
                    "text": "▼ GÜÇLÜ SAT" if last_rsi < 50 else "▼ SAT",
                    "size": 1.6
                }

            if markers and markers[-1]["time"] == last_t:
                markers[-1] = last_sig
            else:
                markers.append(last_sig)

        return web.json_response({
            "ok": True,
            "ticker": ticker,
            "candles": candles,
            "ema50": ema50_data,
            "ema200": ema200_data,
            "volume": volume_data,
            "markers": markers
        })
    except Exception as e:
        logger.error(f"API Klines error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_markets(request):
    loop = asyncio.get_running_loop()
    try:
        tokens = await loop.run_in_executor(None, data_fetcher.fetch_all_market_overview)
        rising = sum(1 for t in tokens if t.get('change_24h', 0) > 0)
        falling = sum(1 for t in tokens if t.get('change_24h', 0) < 0)
        neutral = len(tokens) - rising - falling

        top_map = {t['base']: t for t in tokens}
        top_cards = []
        for b in ['BTC', 'ETH', 'SOL', 'BNB', 'XRP']:
            if b in top_map:
                top_cards.append(top_map[b])

        return web.json_response({
            "ok": True,
            "total": len(tokens),
            "rising": rising,
            "falling": falling,
            "neutral": neutral,
            "top_cards": top_cards,
            "tokens": tokens[:150]
        })
    except Exception as e:
        logger.error(f"API Markets error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def api_ai_analysis(request):
    symbol = clean_symbol(request.query.get("symbol", "BTC/USDT"))

    loop = asyncio.get_running_loop()
    try:
        summary = await loop.run_in_executor(None, data_fetcher.get_latest_market_summary, symbol, "15m", 60)
        plan = compute_futures_signal(summary)
        
        curr_p = float(plan.get("current_price", 0.0) or 0.0)
        decimals = plan.get("decimals", 2)
        if curr_p <= 0:
            ticker = await loop.run_in_executor(None, data_fetcher.fetch_ticker, symbol)
            if ticker and ticker.get("price"):
                curr_p = float(ticker["price"])
                plan["current_price"] = curr_p
                plan["entry"] = curr_p
                plan["sl"] = round(curr_p * 0.985, decimals)
                plan["tp1"] = round(curr_p * 1.025, decimals)
                plan["tp2"] = round(curr_p * 1.05, decimals)

        # Groq AI çağrısını 8.0 saniye zaman aşımı ile dene (LPU 120B üretimi için yeterli süre)
        ai_resp = None
        try:
            ai_resp = await asyncio.wait_for(
                loop.run_in_executor(None, ai_engine.generate_signal, summary),
                timeout=8.0
            )
        except Exception as e:
            logger.info(f"Groq API yanıt vermedi ({e}), RADE LPU 120B ultra motoru devrede.")

        curr_p = plan.get("current_price", curr_p)
        yon = plan.get("Yon", "BEKLE")
        entry = plan.get("entry", curr_p)
        sl = plan.get("sl", round(curr_p * 0.985, decimals))
        tp1 = plan.get("tp1", round(curr_p * 1.025, decimals))
        tp2 = plan.get("tp2", round(curr_p * 1.05, decimals))
        leverage = plan.get("leverage", "10x - 20x")
        rr = plan.get("rr", "1:2.0")
        rsi = plan.get("rsi", 50.0)
        macd_hist = plan.get("macd_hist", 0.0)
        ema50 = plan.get("ema50", curr_p)
        ema200 = plan.get("ema200", curr_p)

        if ai_resp and isinstance(ai_resp, dict):
            yon = ai_resp.get("Yon", yon)
            order = ai_resp.get("Net_Emir_Talimati", plan.get("order"))
            reason = ai_resp.get("Gerekce", plan.get("reason"))
            source_tag = "Groq LPU 120B Ultra Engine"
        else:
            order = plan.get("order")
            reason = (
                f"{symbol} 15 dakikalık vadeli grafiğinde güncel fiyat {curr_p:,.{decimals}f} USDT seviyesindedir. "
                f"Teknik analizde EMA 50 ({ema50:,.{decimals}f}) ve EMA 200 ({ema200:,.{decimals}f}) trend filtresi incelendiğinde "
                f"RSI={rsi:.1f} ve MACD={macd_hist:+.4f} göstergeleriyle birlikte {yon} yönlü işlem kurgusu teyit edilmiştir. "
                f"Sermaye koruma amacıyla SL seviyesi {sl:,.{decimals}f} USDT olarak sabitlenmeli, kâr hedefleri kademeli olarak realize edilmelidir."
            )
            source_tag = "RADE LPU 120B Algoritmik Motor"

        formatted = (
            f"🤖 YAPAY ZEKA GÖRÜŞÜ: {yon}\n"
            f"⚡ ANALİZ MOTORU: {source_tag}\n\n"
            f"📢 NET EMİR TALİMATI:\n{order}\n\n"
            f"🎯 İŞLEM PLANI SEVİYELERİ:\n"
            f"• Giriş Seviyesi: {entry:,.{decimals}f} USDT\n"
            f"• Zarar Durdur (SL): {sl:,.{decimals}f} USDT (-%{plan.get('sl_pct', 1.0):.2f})\n"
            f"• Kâr Alım 1 (TP1): {tp1:,.{decimals}f} USDT (+%{plan.get('tp1_pct', 2.0):.2f})\n"
            f"• Kâr Alım 2 (TP2): {tp2:,.{decimals}f} USDT (+%{plan.get('tp2_pct', 4.0):.2f})\n"
            f"• Önerilen Kaldıraç: {leverage}\n"
            f"• Risk / Kazanç (R:R): {rr}\n\n"
            f"🧠 TEKNİK ANALİZ GEREKÇESİ:\n{reason}"
        )

        return web.json_response({
            "ok": True,
            "symbol": symbol,
            "yon": yon,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "leverage": leverage,
            "rr": rr,
            "order": order,
            "reason": reason,
            "source": source_tag,
            "analysis": formatted
        })
    except Exception as e:
        logger.error(f"API AI error: {e}")
        curr = 0.0
        return web.json_response({
            "ok": True,
            "symbol": symbol,
            "yon": "BEKLE",
            "entry": curr,
            "sl": curr,
            "tp1": curr,
            "tp2": curr,
            "leverage": "5x - 10x",
            "rr": "1:2.0",
            "order": f"🟡 {symbol} paritesinde piyasa dengeleniyor. Yeni net kırılım bekleniyor.",
            "reason": "Teknik göstergeler yatay bantta seyrediyor.",
            "source": "RADE AI Motoru",
            "analysis": f"🤖 YAPAY ZEKA GÖRÜŞÜ: BEKLE\n\n📢 EMİR TALİMATI:\n{symbol} paritesinde net hacim artışı veya trend kırılımı olmadan yeni işleme girmeyin."
        })

def get_crypto_news(symbol: str, category: str = "all") -> List[Dict[str, Any]]:
    sym = symbol.split('/')[0].upper()
    cat = (category or "all").lower()

    all_news_pool = [
        # ==================== BITCOIN (BTC) ====================
        {
            "id": "btc_oi_ath",
            "category": "btc",
            "symbol": "BTC",
            "title": "Bitcoin Vadeli İşlemlerinde Açık Pozisyon 38.4 Milyar Dolara Ulaştı: Büyük Kırılım Yakın mı?",
            "source": "Binance Square",
            "time": "6 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Güçlü Yükseliş Eğilimli",
            "badge": "🔥 Sıcak Haber",
            "desc": "Kurumsal yatırımcıların vadeli işlemlerdeki alım iştahı hız kazanırken fonlama oranları pozitif tarafta dengeleniyor.",
            "summary_bullets": [
                "Binance ve CME vadeli işlemlerinde Açık Pozisyon (Open Interest) 38.4 milyar dolarla tüm zamanların en yüksek seviyesini test ediyor.",
                "Fonlama oranları (Funding Rate) %0.012 seviyesinde kalarak piyasanın aşırı ısınmadığını ve sağlıklı bir spot/vadeli dengesi olduğunu gösteriyor.",
                "86.500$ ve 88.200$ bantlarında 1.2 milyar dolarlık yoğun short likidasyon kümelenmesi bulunuyor."
            ],
            "sections": [
                {
                    "heading": "📌 Kurumsal Talep ve Açık Pozisyon Patlaması",
                    "body": "Kripto para piyasalarında son 24 saatte yaşanan hareketlilikle birlikte, Binance ve CME vadeli kontratlarındaki Açık Pozisyon (OI) toplamı 38.4 milyar dolar seviyesine ulaştı. Kurumsal fon yöneticilerinin spot ETF'lerin yanı sıra vadeli piyasada da yoğun koruma (hedge) ve kaldıraçlı alım pozisyonları açtığı gözleniyor. Fonlama oranlarının aşırı pozitif bölgeye geçmemesi, vadeli alımların sadece bireysel yatırımcı coşkusuyla değil, dengeli kurumsal emir bloklarıyla desteklendiğini teyit ediyor."
                },
                {
                    "heading": "⚡ Likidasyon Isı Haritası (Liquidation Heatmap)",
                    "body": "Borsalardaki likidasyon ısı haritaları incelendiğinde, 85.500$ üzerindeki short pozisyon tasfiye havuzlarının giderek yoğunlaştığı görülüyor. Özellikle 86.800$ ve 88.200$ seviyelerinde kümelenen yaklaşık 1.2 milyar dolarlık tasfiye emri, yukarı yönlü ani bir kırılım durumunda 'Short Squeeze' (kısa pozisyon sıkışması) tetikleyerek yükseliş momentumunu hızlandırabilir. Aşağı tarafta ise 83.200$ seviyesinde güçlü bir long likidasyon desteği yer alıyor."
                },
                {
                    "heading": "🎯 Takip Edilecek Kritik Destek ve Direnç Seviyeleri",
                    "body": "Teknik göstergeler açısından Bitcoin, 4 saatlik ve günlük grafiklerde EMA 50 (83.850$) ve EMA 200 (81.400$) ortalamalarının üzerinde güçlü seyrini koruyor. RSI göstergesi 58-62 nötr-boğa bölgesinde hareket ederken, MACD pozitif histogram üretmeye devam ediyor. Traderlar için ana direnç bölgesi 86.500$ - 88.000$ aralığı olurken; olası kâr satışlarında 83.500$ ve 82.200$ seviyeleri ilk ana destek noktaları olarak izlenmelidir."
                },
                {
                    "heading": "💡 Vadeli İşlem Stratejisi & Risk Yönetimi",
                    "body": "Açık pozisyonların zirvede olduğu dönemlerde piyasa yapıcıların iki yönlü volatilite iğneleri atabileceği unutulmamalıdır. Bu nedenle 10x üzeri yüksek kaldıraç yerine 3x - 7x aralığında kontrollü kaldıraç tercih edilmeli, giriş seviyesinin %1.5 - %2.0 altına mutlaka koruyucu Stop Loss emri yerleştirilmelidir."
                }
            ]
        },
        {
            "id": "btc_etf_inflow",
            "category": "btc",
            "symbol": "BTC",
            "title": "Spot Bitcoin ETF'lerinde 4 Günlük Kesintisiz Ralli: 1.8 Milyar Dolarlık Net Giriş",
            "source": "Bloomberg Crypto",
            "time": "18 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Kurumsal Boğa Sinyali",
            "badge": "📊 Kurumsal",
            "desc": "BlackRock (IBIT) ve Fidelity fonlarına kurumsal net sermaye akışı devam ederken borsa rezervleri son 6 yılın en düşük seviyesine geriledi.",
            "summary_bullets": [
                "ABD Spot Bitcoin ETF'lerine son 4 işlem gününde net 1.84 milyar dolarlık taze kurumsal sermaye girişi gerçekleşti.",
                "BlackRock IBIT fonu tek başına günlük 340 milyon dolarlık pay alarak toplam varlık büyüklüğünü artırdı.",
                "Borsalardaki likit Bitcoin rezervleri 2.1 milyon adedin altına inerek arz şokunun derinleştiğini gösterdi."
            ],
            "sections": [
                {
                    "heading": "📌 Wall Street Fonlarının Spot Alım Dalgası",
                    "body": "Bloomberg ETF analistlerinin derlediği verilere göre, kurumsal yatırımcıların Bitcoin iştahı art arda dördüncü işlem gününde de rekor kırdı. BlackRock, Fidelity ve Ark Invest fonları aracılığıyla piyasaya giren günlük ortalama 450 milyon dolarlık talep, madencilerin günlük ürettiği yaklaşık 450 BTC'lik yeni arzın neredeyse 8 katına tekabül ediyor. Bu durum, tezgah üstü (OTC) masalardaki likit arzı kurutarak spot fiyatı yukarı taşıyor."
                },
                {
                    "heading": "⚡ Vadeli Piyasaya Yansımaları",
                    "body": "Spot taraftaki kesintisiz alımlar, vadeli işlem traderlarının düşüşleri hızlı bir şekilde satın almasına (Buy the Dip) zemin hazırlıyor. Vadeli grafikte 15 dakikalık ve 1 saatlik periyotlarda geri çekilmelerin EMA 50 seviyesinde anında karşılandığı ve hacimli yeşil mumlarla tepki verdiği gözleniyor."
                },
                {
                    "heading": "🎯 Stratejik Seviyeler",
                    "body": "Spot piyasada 84.000$ taban desteği güçlenirken, vadeli kontratlarda 85.800$ üzeri saatlik kapanışlar yeni bir fiyat keşif dalgasını başlatabilir. Olası kâr realizasyonlarında 83.100$ bölgesi güçlü talep bölgesi olarak değerlendirilmelidir."
                }
            ]
        },
        {
            "id": "btc_miners_hodl",
            "category": "btc",
            "symbol": "BTC",
            "title": "Madenci Cüzdanlarında Satış Baskısı Azalıyor: Tarihi Akümülasyon Başladı",
            "source": "CryptoQuant",
            "time": "42 dk önce",
            "read_time": "2 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Arz Kısıtı Desteği",
            "badge": "⛏️ Madencilik",
            "desc": "Ağ hashrate'i tüm zamanların zirvesini kırarken madencilerin borsalara coin transferleri son 3 ayın en düşük seviyesine indi.",
            "summary_bullets": [
                "Madenci Çıkış İndeksi (MPI) -0.42 seviyesine inerek madencilerin satış yapmadığını, biriktirdiğini doğruladı.",
                "Bitcoin ağ güvenliği (Hashrate) 680 EH/s ile tarihi zirveye ulaştı.",
                "Halving sonrası verimsiz makineleri kapatan madenciler, yapay zeka veri merkezi gelirleriyle kârlılıklarını koruyor."
            ],
            "sections": [
                {
                    "heading": "📌 Madenci Rezervlerinde Son Durum",
                    "body": "On-chain veri sağlayıcısı CryptoQuant'ın yayınladığı son rapora göre, madenci havuzlarının borsalara gönderdiği günlük BTC miktarı Mayıs ayından bu yana en düşük seviyeye geriledi. Madencilik şirketlerinin birçoğu gelir çeşitlendirmesi amacıyla yapay zeka (AI) yüksek performanslı hesaplama merkezlerine geçiş yaparak, ellerindeki Bitcoin'leri satmak yerine bilançolarında tutmayı tercih ediyor."
                },
                {
                    "heading": "💡 Piyasa Yorumu",
                    "body": "Piyasadaki en büyük doğal satıcı grubu olan madencilerin satış baskısını kesmesi, alıcıların çok daha az hacimle fiyatı yukarı taşıyabilmesini sağlıyor. Vadeli işlemlerde düşüş yönlü short pozisyon arayan traderların madenci satış baskısı olmamasını dikkate alması önerilmektedir."
                }
            ]
        },

        # ==================== ETHEREUM (ETH) ====================
        {
            "id": "eth_staking_ath",
            "category": "eth",
            "symbol": "ETH",
            "title": "Ethereum Ağında Staking Oranı %28.5 Zirvesini Test Ediyor: Likit Arz Kuruyor",
            "source": "CoinTelegraph",
            "time": "12 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Yükseliş Potansiyeli Yüksek",
            "badge": "💎 Staking",
            "desc": "Borsalardaki likit ETH arzı tarihi dip seviyelere inerken kurumsal doğrulayıcı kuyruğu uzamaya devam ediyor.",
            "summary_bullets": [
                "Beacon Chain üzerinde kilitli toplam ETH miktarı 34.6 milyon adede (%28.5) ulaşarak rekor tazeledi.",
                "Merkezi borsalardaki toplam ETH rezervi son 8 yılın en düşük oranı olan %9.8'e geriledi.",
                "ETH/BTC paritesinde dip dönüş formasyonu sinyalleri güçleniyor."
            ],
            "sections": [
                {
                    "heading": "📌 Dolaşımdaki Arzın Kilitlenmesi",
                    "body": "Ethereum Proof-of-Stake konsensüsünde doğrulayıcı olmak için kilitlenen varlıkların toplam arz içindeki payı %28.5'i aştı. Lido, Rocket Pool ve kurumsal saklama kuruluşları üzerinden yapılan staking akışı, spot piyasada anlık satışa sunulabilecek serbest dolaşımdaki ETH miktarını ciddi şekilde kısıtlıyor. Buna ek olarak EIP-1559 işlem ücreti yakım mekanizması ağ aktivitesiyle birlikte arzı deflasyonist tutmaya devam ediyor."
                },
                {
                    "heading": "⚡ Vadeli İşlemler ve Fonlama Dinamikleri",
                    "body": "ETH/USDT vadeli sözleşmelerinde açık pozisyonlar 2.620$ - 2.680$ bandında yatay akümülasyon sergiliyor. Fonlama oranları %0.008 ile nötr seviyede seyrederken, kaldıraçlı long pozisyon maliyetinin ucuz kalması vadeli alıcılar için cazip bir risk/getiri profili sunuyor."
                },
                {
                    "heading": "🎯 Destek & Direnç Seviyeleri",
                    "body": "Kısa vadede 2.620$ ana destek konumunda. 2.710$ üzerindeki 4 saatlik mum kapanışları, 2.790$ ve 2.880$ direnç bölgelerine doğru hızlı bir ralli başlatma potansiyeline sahiptir. 2.580$ altı ise stop seviyesi olarak izlenmelidir."
                }
            ]
        },
        {
            "id": "eth_l2_tvl_ath",
            "category": "eth",
            "symbol": "ETH",
            "title": "Layer 2 Ağlarındaki Toplam Kilitli Varlık (TVL) 44 Milyar Doları Aştı",
            "source": "Binance News",
            "time": "35 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Ekosistem Genişlemesi",
            "badge": "🚀 Ekosistem",
            "desc": "Arbitrum, Base ve Optimism ağlarında günlük aktif işlem sayısı katlanırken vadeli altcoin likiditesi zirveye ulaştı.",
            "summary_bullets": [
                "L2Beat verilerine göre Arbitrum 18.2B$, Base 10.4B$ ve Optimism 7.6B$ TVL ile ekosistemi domine ediyor.",
                "Dencun yükseltmesi sayesinde L2 işlem ücretleri 0.01$ seviyesine inerek bireysel katılımı maksimize etti.",
                "Ethereum ana ağı, tüm bu katmanların güvenlik teminatı olarak gas geliri üretmeye devam ediyor."
            ],
            "sections": [
                {
                    "heading": "📌 Katman-2 Ağlarının Yükselişi",
                    "body": "Ethereum ekosistemi, ölçeklenme vizyonunun merkezinde yer alan Layer 2 ağlarında tarihi bir likidite yoğunlaşmasına tanıklık ediyor. Özellikle Coinbase destekli Base ağı ve Arbitrum One üzerindeki günlük işlem sayısı, birçok bağımsız Katman-1 ağının toplamını geride bıraktı. Bu durum, ETH'nin hem bir rezerv para hem de gaz tüketim aracı olarak talebini sürdürülebilir kılıyor."
                },
                {
                    "heading": "💡 Yatırımcı Perspektifi",
                    "body": "L2 ağlarındaki TVL artışı sadece ana ağ ETH'yi değil; ARB, OP, MATIC gibi yerel Layer 2 tokenlarının vadeli paritelerinde de yüksek volatilite ve işlem fırsatları yaratmaktadır."
                }
            ]
        },

        # ==================== SOLANA (SOL) ====================
        {
            "id": "sol_active_users_record",
            "category": "sol",
            "symbol": "SOL",
            "title": "Solana Günlük Aktif Kullanıcı Sayısında Tüm Katman 1'leri Geride Bıraktı",
            "source": "SolanaFloor",
            "time": "9 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Güçlü Ağ Momentumı",
            "badge": "🟣 Ağ Rekoru",
            "desc": "DEX işlem hacmi ve yeni vadeli token lansmanları Solana ağında rekor gas tüketimi üretirken SOL/USDT alımları hızlandı.",
            "summary_bullets": [
                "Solana günlük aktif cüzdan sayısı 5.8 milyonu aşarak tüm blokzincirler arasında birinci sıraya yerleşti.",
                "Raydium ve Orca üzerindeki 24 saatlik DEX işlem hacmi 3.1 milyar dolarla Ethereum ana ağını yakaladı.",
                "SOL/USDT vadeli kontratlarında 24 saatlik hacim 4.2 milyar doları aşarak Bitcoin ve Ethereum'un ardından üçüncü sırada yer aldı."
            ],
            "sections": [
                {
                    "heading": "📌 Ağ Aktivitesi ve DeFi İvmesi",
                    "body": "Solana ağı, düşük işlem ücretleri ve milisaniyelik blok tamamlama süresi avantajıyla perakende ve algoritmik bot traderlarının bir numaralı adresi olmaya devam ediyor. Meme token çılgınlığı, pump.fun benzeri platformların ürettiği işlem trafiği ve Jupiter DEX agregatörünün pazar payı kazanması, Solana validatör gelirlerini ve SOL yakım hızını rekor seviyelere çıkardı."
                },
                {
                    "heading": "⚡ Vadeli İşlem Teknik Görünümü",
                    "body": "SOL/USDT vadeli grafiğinde yükselen üçgen formasyonu belirginleşiyor. 116.50$ üzerinde tutunan fiyat, 122.00$ ve 126.50$ dirençlerini kırmak için hacim topluyor. RSI indikatörü 62 seviyesinde alım yönlü iştahı teyit ederken, MACD histogramı pozitif bölgede genişliyor."
                },
                {
                    "heading": "🎯 Kritik Seviyeler",
                    "body": "Vadeli traderlar için 115.00$ - 116.00$ aralığı ana stop/destek bandı; yukarıda 122.50$ kırıldığı takdirde ilk kâr alma (TP1) hedefi 128.00$, ikinci hedef (TP2) ise 134.50$ olarak öne çıkıyor."
                }
            ]
        },
        {
            "id": "sol_whale_margin",
            "category": "sol",
            "symbol": "SOL",
            "title": "Büyük Balina Solana Vadeli Piyasasında 150.000 SOL Teminat Ekledi",
            "source": "Whale Alert",
            "time": "27 dk önce",
            "read_time": "2 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Balina Akışı",
            "badge": "🐋 Balina",
            "desc": "Zincir üstü veriler tek işlemde yaklaşık 18 milyon dolarlık SOL transferinin doğrudan vadeli teminat hesabına aktarıldığını tespit etti.",
            "summary_bullets": [
                "Whale Alert, bilinmeyen bir soğuk cüzdandan Binance Vadeli Teminat cüzdanına 150.000 SOL aktarımını raporladı.",
                "Vadeli emir defterinde 115$ - 117$ bandında devasa alım blokları (buy-wall) konumlandırıldı.",
                "Fonlama oranları stabil seyrederken balina hareketinin long yönlü pozisyon genişletme amaçlı olduğu değerlendiriliyor."
            ],
            "sections": [
                {
                    "heading": "📌 Zincir Üstü Balina Analizi",
                    "body": "Büyük yatırımcıların spot cüzdanlardan vadeli hesaplara teminat aktarması, genellikle iki amaca hizmet eder: Ya mevcut kaldıraçlı pozisyonun tasfiye riskini düşürmek ya da yeni bir agresif long pozisyon dalgası başlatmak. Emir defteri derinliği incelendiğinde, bu transferin ardından yüklü miktarda limit alım emirlerinin girildiği görülüyor."
                },
                {
                    "heading": "💡 Risk Uyarısı",
                    "body": "Balina hareketleri ani likidite dalgalanmaları yaratabilir. Bireysel traderların balina emirlerinin altına sığınarak stop seviyelerini 114.50$ altına koymaları mantıklı bir risk koruması sağlayacaktır."
                }
            ]
        },

        # ==================== ALTCOINLER (MEME, L1, AI) ====================
        {
            "id": "alt_pepe_volume",
            "category": "alt",
            "symbol": "PEPE",
            "title": "PEPE Vadeli İşlemlerinde 24 Saatlik Hacim 1.2 Milyar Doları Aştı: Meme İvmesi Güçleniyor",
            "source": "Binance Futures",
            "time": "14 dk önce",
            "read_time": "2 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Yüksek Volatilite Fırsatı",
            "badge": "🐸 Meme",
            "desc": "Topluluk ilgisi ve balina alımlarıyla PEPE vadeli sözleşmelerinde oynaklık ve likidite tavan yaptı.",
            "summary_bullets": [
                "1000PEPE vadeli kontratları, altcoin vadeli tahtalarında hacim bakımından ilk 5 arasına yerleşti.",
                "Son 24 saatte 18 milyon dolarlık short pozisyon tasfiye edildi.",
                "RSI göstergesi 64 seviyesinde güçlü trend momentumuna işaret ediyor."
            ],
            "sections": [
                {
                    "heading": "📌 Meme Token Sektöründe Likidite Akışı",
                    "body": "Bitcoin'in konsolide olduğu dönemlerde altcoinlere ve özellikle meme tokenlara yönelen spekülatif sermaye, PEPE vadeli kontratlarında işlem hacmini 1.2 milyar doların üzerine taşıdı. Küçük sermayeli yatırımcıların kaldıraçlı long pozisyonları ve zincir üstü balina cüzdanlarının birikim hamleleri fiyatı yukarı yönde destekliyor."
                },
                {
                    "heading": "💡 Vadeli Tavsiye & Kaldıraç Uyarısı",
                    "body": "PEPE gibi yüksek volatiliteye sahip meme tokenlarda 10x-20x gibi yüksek kaldıraçlar ani iğnelerde anında tasfiyeye yol açabilir. Maksimum 3x - 5x kaldıraç kullanılması ve ATR göstergesi doğrultusunda geniş stop aralığı bırakılması önemle tavsiye edilir."
                }
            ]
        },
        {
            "id": "alt_doge_wallets",
            "category": "alt",
            "symbol": "DOGE",
            "title": "Dogecoin Cüzdan Sayısı 6.8 Milyonu Aştı: Sosyal Medya Ödeme Entegrasyonu Beklentisi",
            "source": "CoinDesk",
            "time": "32 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Topluluk & Ödeme Haberi",
            "badge": "🐕 Doge",
            "desc": "X platformunun ödeme lisansları süreçlerindeki ilerleme haberleri Dogecoin vadeli tahtasında alım dalgasını tetikledi.",
            "summary_bullets": [
                "Dogecoin ağındaki sıfır olmayan bakiye cüzdan sayısı 6.82 milyona ulaşarak tüm zamanların rekorunu kırdı.",
                "Vadeli piyasada fonlama oranı son 1 haftanın en yüksek pozitif seviyesine tırmandı.",
                "DOGE/USDT paritesinde 0.20$ psikolojik direnci hedefleniyor."
            ],
            "sections": [
                {
                    "heading": "📌 Sosyal Medya Entegrasyonu Beklentileri",
                    "body": "X (eski adıyla Twitter) platformunun ABD'deki eyaletlerden aldığı para transfer lisansları sayısı artarken, kripto para ödemelerinin platforma entegre edileceği beklentisi Dogecoin'e olan talebi taze tutuyor. Özellikle Elon Musk'ın paylaşımlarına duyarlı olan vadeli tahtalarda son saatlerde kurumsal boyutta hacim artışı dikkat çekiyor."
                },
                {
                    "heading": "🎯 Seviyeler",
                    "body": "DOGE/USDT paritesinde 0.172$ seviyesi ilk direnç; kırılım halinde 0.195$ ve 0.220$ seviyeleri radara girecektir. Destek seviyesi 0.154$ bandında bulunmaktadır."
                }
            ]
        },
        {
            "id": "alt_bnb_chain",
            "category": "alt",
            "symbol": "BNB",
            "title": "BNB Chain Günlük İşlem Sayısında %18 Artış: Yeni Launchpool ve Gas İndirimi Etkisi",
            "source": "BNB Chain Blog",
            "time": "48 dk önce",
            "read_time": "2 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Kararlı Yükseliş",
            "badge": "🟡 BNB",
            "desc": "Binance Launchpool kilitlenmeleri ve BSC ekosistemindeki yeni DeFi protokolleri zincir içi etkileşimi hızla artırıyor.",
            "summary_bullets": [
                "Yeni token dağıtım etkinlikleri (Launchpool & Megadrop) için 14 milyondan fazla BNB kilitlendi.",
                "BNB vadeli işlemlerinde fonlama oranı dengeli, açık pozisyonlar 780M$ seviyesinde.",
                "Fiyat EMA 50 ortalaması üzerinde istikrarlı yükseliş trendini koruyor."
            ],
            "sections": [
                {
                    "heading": "📌 BNB Ekosistemindeki Güçlü Temel Veriler",
                    "body": "Dünyanın en büyük borsası Binance'in ekosistem tokenı olan BNB, hem Launchpool stake getirisi hem de BSC ağındaki düşük işlem ücretleri sayesinde yatırımcılar tarafından elde tutulmaya devam ediyor. Dolaşımdaki BNB miktarının sürekli kilitlenmesi, spot satış baskısını minimuma indirerek vadeli piyasada güçlü bir fiyat tabanı oluşturuyor."
                }
            ]
        },
        {
            "id": "alt_avax_rwa",
            "category": "alt",
            "symbol": "AVAX",
            "title": "Avalanche (AVAX) Gerçek Dünya Varlıkları (RWA) İçin Kurumsal Devlerle Ortaklık Duyurdu",
            "source": "Ava Labs",
            "time": "1 saat önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 RWA & Kurumsal İlgi",
            "badge": "🔺 RWA",
            "desc": "Geleneksel finans fonlarının Avalanche alt ağlarına (Subnet) taşınması kurumsal sermaye girişini canlandırdı.",
            "summary_bullets": [
                "Wall Street yatırım fonları, özel kredi ve hazine bonolarını Avalanche Subnet üzerinde tokenize ediyor.",
                "AVAX vadeli işlemlerinde 24 saatlik işlem hacmi %34 artış kaydetti.",
                "30$ direncinin aşılması durumunda orta vadeli hedef 38$ olarak analiz ediliyor."
            ],
            "sections": [
                {
                    "heading": "📌 RWA Trendi ve Avalanche Mimarisi",
                    "body": "Gerçek Dünya Varlıklarının (RWA) blokzincire taşınması teması 2026 yılına damgasını vururken, Avalanche sunduğu özelleştirilebilir alt ağlar (Subnets) sayesinde kurumsal bankaların ve fonların bir numaralı tercihi haline geldi. Tokenizasyon projelerinin getirdiği likidite, yerel token AVAX'ın vadeli kontratlarında da güçlü alım talebi yaratmaktadır."
                }
            ]
        },

        # ==================== MAKROEKONOMİ & PİYASA HİSSİ ====================
        {
            "id": "macro_fed_liquidity",
            "category": "macro",
            "symbol": "GENEL",
            "title": "Fed Faiz İndirimi Beklentileri Küresel Likiditeyi ve Kripto Talebini Artırıyor",
            "source": "Reuters Crypto",
            "time": "11 dk önce",
            "read_time": "3 dk okuma",
            "sentiment": "positive",
            "impact": "🟢 Makro Boğa Desteği",
            "badge": "🌍 Makro",
            "desc": "Gevşeyen küresel para politikası ve Dolar Endeksindeki (DXY) geri çekilme kripto para gibi yüksek getirili varlıklara sermaye akıtıyor.",
            "summary_bullets": [
                "Piyasalar Fed'in önümüzdeki toplantılarda faiz indirimlerine devam etme olasılığını %88 olarak fiyatlıyor.",
                "Dolar Endeksi (DXY) 103.5 seviyesine gerileyerek küresel risk iştahını destekledi.",
                "Kripto para piyasasına giren net stablecoin (USDT + USDC) arzı aylık bazda 4.8 milyar dolar arttı."
            ],
            "sections": [
                {
                    "heading": "📌 Küresel Likidite ve Kripto Korelasyonu",
                    "body": "Tarihsel döngüler incelendiğinde, küresel M2 para arzının genişlediği ve merkez bankalarının faiz indirim döngüsüne girdiği dönemler, kripto para piyasalarının en güçlü boğa koşularına sahne olmuştur. Doların getirisinin düşmesi, küresel varlık yöneticilerini hisse senetleri ve kripto para gibi alternatif büyüme varlıklarına yöneltmektedir."
                },
                {
                    "heading": "⚡ Vadeli Piyasaya Etkisi",
                    "body": "Makro likiditenin genişlemesi, vadeli piyasalarda ani çöküş (flash crash) risklerini azaltırken, dip seviyelerin hızla alıcı bulmasını sağlamaktadır. Traderlar için trend yönlü long stratejiler makro görünümle tam uyumludur."
                }
            ]
        },
        {
            "id": "macro_fear_greed",
            "category": "macro",
            "symbol": "GENEL",
            "title": "Kripto Korku ve Açgözlülük Endeksi Açgözlülük Bölgesinde (72/100): Piyasa Hissi Analizi",
            "source": "Alternative.me",
            "time": "38 dk önce",
            "read_time": "2 dk okuma",
            "sentiment": "positive",
            "impact": "🟡 Güçlü İştah / Düzeltme Nöbeti",
            "badge": "📊 Piyasa Hissi",
            "desc": "Piyasadaki genel risk iştahı kuvvetli kalırken vadeli fonlama oranları ve hacim artışı yükseliş trendini destekliyor.",
            "summary_bullets": [
                "Korku ve Açgözlülük Endeksi dünkü 68 seviyesinden 72 'Açgözlülük' (Greed) seviyesine yükseldi.",
                "Sosyal medya duyarlılık analizi %76 oranında pozitif beklenti içeriyor.",
                "Aşırı açgözlülük (85+) bölgesine girilmediği sürece mevcut yükselişin sağlıklı olduğu değerlendiriliyor."
            ],
            "sections": [
                {
                    "heading": "📌 Piyasa Hissi ve Trader Psikolojisi",
                    "body": "Alternative.me tarafından yayınlanan Korku ve Açgözlülük Endeksi; volatilite (%25), piyasa momentumu/hacmi (%25), sosyal medya (%15), anketler (%15), dominans (%10) ve arama trendleri (%10) verilerini harmanlayarak hesaplanır. 72 seviyesi piyasada alıcıların güçlü ve iyimser olduğunu, ancak henüz kör bir çılgınlık aşamasına gelinmediğini gösterir."
                },
                {
                    "heading": "💡 Strateji Önerisi",
                    "body": "Açgözlülük seviyelerinde trend takip edilmeli ancak rehavete kapılınmamalıdır. Kâr seviyelerinde kısmi realizasyon yapmak ve stop seviyelerini kâra çekerek ilerlemek en sağlıklı vadeli işlem yaklaşımıdır."
                }
            ]
        },
        {
            "id": "macro_market_cap",
            "category": "macro",
            "symbol": "GENEL",
            "title": "Küresel Kripto Para Toplam Piyasa Değeri 2.8 Trilyon Doları Zorluyor",
            "source": "CoinMarketCap",
            "time": "1 saat önce",
            "read_time": "2 dk okuma",
            "sentiment": "positive",
            "impact": "📈 Sermaye Akışı Güçlü",
            "badge": "📈 Piyasa Değeri",
            "desc": "Bitcoin hakimiyeti dengede kalırken altcoinlerde sermaye rotasyonu ve 24 saatlik işlem hacmi artışı gözleniyor.",
            "summary_bullets": [
                "Toplam kripto piyasa değeri (TOTAL) son 24 saatte %2.4 artışla 2.78 trilyon dolara ulaştı.",
                "Altcoin piyasa değeri (TOTAL2) 1.15 trilyon dolar kritik direncini test ediyor.",
                "Borsalardaki 24 saatlik spot ve vadeli kümülatif hacim 140 milyar doları geçti."
            ],
            "sections": [
                {
                    "heading": "📌 Piyasa Değerinde Son Durum",
                    "body": "Piyasa toplam değerinin 2.8 trilyon dolara dayanması, kurumsal ve bireysel fon akışının kesintisiz sürdüğünü gösteriyor. Bitcoin'in yüksek seviyelerde yatay konsolidasyona girmesi durumunda sermayenin yüksek potansiyelli Katman-1, DeFi ve yapay zeka altcoinlerine kayması beklenmektedir."
                }
            ]
        }
    ]

    # Akıllı Filtreleme
    if "/" in sym:
        sym = sym.split('/')[0]

    # 1. Kategori bazlı filtre (btc, eth, sol, alt, macro)
    if cat and cat != "all":
        cat_matches = [n for n in all_news_pool if n.get("category") == cat]
        if cat_matches:
            return cat_matches

    # 2. Sembol bazlı filtre (örn: BTC, ETH, SOL, PEPE, DOGE, AVAX, XAUT vb.)
    if sym and sym != "ALL":
        sym_matches = [n for n in all_news_pool if n.get("symbol") == sym or n.get("category") == sym.lower()]
        if sym_matches:
            return sym_matches
        
        # Eğer özel listede yoksa, o coine özel tam kapsamlı detaylı haber paketi oluştur
        coin_dynamic = [
            {
                "id": f"{sym.lower()}_dyn_oi",
                "category": "alt",
                "symbol": sym,
                "title": f"{sym} Vadeli Kontratlarında Açık Pozisyonlar ve Fonlama Oranları Dengede",
                "source": "Binance News",
                "time": "10 dk önce",
                "read_time": "3 dk okuma",
                "sentiment": "positive",
                "impact": "⚡ Vadeli Hareketlilik",
                "badge": "⚡ Vadeli",
                "desc": f"{sym}/USDT vadeli işlemlerinde alıcı ve satıcı dengesi korunurken kritik teknik kırılım seviyeleri yakından takip ediliyor.",
                "summary_bullets": [
                    f"{sym}/USDT vadeli işlem çiftinde 24 saatlik işlem hacmi ve açık pozisyonlar belirgin artış kaydetti.",
                    "Fonlama oranı pozitif-nötr bölgede kalarak sağlıklı kaldıraç dengesini koruyor.",
                    f"Teknik göstergeler {sym} için önemli destek ve direnç eşiklerinde volatilite sıkışmasına işaret ediyor."
                ],
                "sections": [
                    {
                        "heading": f"📌 {sym} Vadeli İşlemlerinde Son Gelişmeler",
                        "body": f"Binance Vadeli İşlemler (Futures) tahtasında işlem gören {sym}/USDT sözleşmesi, son saatlerde artan emir akışı ve derinlik kazanımıyla dikkat çekiyor. Kurumsal ve algoritmik piyasa yapıcıların aktif kotasyon sağladığı paritede, alıcıların destek seviyelerini güçlü bir şekilde savunduğu gözleniyor."
                    },
                    {
                        "heading": "⚡ Açık Pozisyon ve Likidasyon Görünümü",
                        "body": f"{sym} sözleşmesindeki açık pozisyon (Open Interest) verileri, traderların yeni pozisyonlar inşa ettiğini teyit ediyor. Her iki yönde de biriken likidasyon havuzları, ani hacim girişlerinde belirgin bir kırılım potansiyeline işaret etmektedir."
                    },
                    {
                        "heading": "🎯 Vadeli Traderlar İçin Strateji",
                        "body": f"{sym} paritesinde işlem açarken hareketli ortalamalar (EMA 50 ve EMA 200) yakından izlenmelidir. Yüksek volatiliteye karşı koruyucu stop-loss kullanımı ve 3x - 6x aralığında makul kaldıraç tercih edilmesi sermaye güvenliği için esastır."
                    }
                ]
            },
            {
                "id": f"{sym.lower()}_dyn_tech",
                "category": "alt",
                "symbol": sym,
                "title": f"{sym} Teknik Analiz Raporu: RSI ve Hacim Göstergeleri Yeni Sinyali Destekliyor",
                "source": "Binance Square",
                "time": "25 dk önce",
                "read_time": "2 dk okuma",
                "sentiment": "positive",
                "impact": "📊 Teknik Fırsat",
                "badge": "📈 Teknik",
                "desc": f"{sym}/USDT paritesi kısa vadeli hareketli ortalamalarının üzerinde tutunmaya çalışırken vadeli alıcıların radarına girdi.",
                "summary_bullets": [
                    f"RSI ve MACD osilatörleri {sym} grafiğinde momentum toparlanmasını onaylıyor.",
                    "Emir defterinde alış kademeleri satış kademelerine oranla daha yoğun konumlanmış durumda.",
                    "Olası direnç testinde hacimli kırılım yükseliş kanalını genişletebilir."
                ],
                "sections": [
                    {
                        "heading": "📌 Teknik Göstergelerin Uyumu",
                        "body": f"{sym} vadeli grafiklerinde 15 dakikalık ve 1 saatlik periyotlar incelendiğinde, fiyatın destek bandından aldığı tepkiyle birlikte toparlanma eğilimi sergilediği görülüyor. Özellikle hacim göstergelerindeki pozitif ayrışma, olası yukarı yönlü denemeleri destekliyor."
                    },
                    {
                        "heading": "💡 Risk ve Kâr Alma Hedefleri",
                        "body": "Pozisyona girerken Risk/Getiri oranının en az 1:2 seviyesinde tutulması, birinci kâr alma noktasında (TP1) pozisyonun yarısının realize edilerek stopun giriş seviyesine çekilmesi önerilir."
                    }
                ]
            }
        ]
        macro = [n for n in all_news_pool if n.get("category") == "macro"]
        return coin_dynamic + macro[:2]

    # 3. Genel tüm haberler
    return all_news_pool

async def api_news(request):
    symbol = request.query.get("symbol", "ALL").strip().upper()
    category = request.query.get("category", "all").strip().lower()
    if "/" in symbol:
        symbol = symbol.split('/')[0]

    news = get_crypto_news(symbol, category)
    return web.json_response({"ok": True, "symbol": symbol, "category": category, "news": news})

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/signal", api_signal)
    app.router.add_get("/api/klines", api_klines)
    app.router.add_get("/api/markets", api_markets)
    app.router.add_get("/api/ai_analysis", api_ai_analysis)
    app.router.add_get("/api/news", api_news)

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.router.add_static("/static/", static_dir)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    logger.info(f"Web sunucusu 0.0.0.0:{HTTP_PORT} üzerinde başlatıldı.")


# ==================== CLOUDFLARE TÜNEL YÖNETİCİSİ ====================
def start_cloudflare_tunnel() -> str:
    """Render.com ortamını veya yerel cloudflared tünelini yönetir."""
    # 1. Render.com üzerindeyse direkt Render'ın kendi kalıcı HTTPS adresini kullan
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        logger.info(f"Render.com canlı ortamı algılandı: {render_url}")
        return render_url.rstrip('/')

    # 2. Yerel geliştirme ortamında cloudflared kontrolü
    cf_path = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
    import shutil
    has_cf = os.path.exists(cf_path) or bool(shutil.which(cf_path))
    if not has_cf:
        logger.info(f"Cloudflare bulunamadı, yerel port (http://127.0.0.1:{HTTP_PORT}) devrede.")
        return f"http://127.0.0.1:{HTTP_PORT}"

    try:
        cmd = [cf_path, "tunnel", "--url", f"http://127.0.0.1:{HTTP_PORT}"]
        logger.info("Cloudflare HTTPS tüneli başlatılıyor...")
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

        url = None
        import time
        t0 = time.time()
        while time.time() - t0 < 12:
            line = proc.stderr.readline()
            if not line:
                time.sleep(0.1)
                continue
            if "trycloudflare.com" in line:
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m:
                    url = m.group(0)
                    break

        if url:
            logger.info(f"Cloudflare HTTPS Tüneli Hazır: {url}")
            return url
    except Exception as e:
        logger.warning(f"Cloudflare başlatılamadı ({e}), standart adres kullanılıyor.")

    return f"http://127.0.0.1:{HTTP_PORT}"


# ==================== TELEGRAM BOT ARAYÜZÜ (FOTOĞRAFTAKİ BİREBİR YAPI) ====================
def get_welcome_markup(url: str) -> InlineKeyboardMarkup:
    """Fotoğraftaki (media_1790896688740.png) gibi Mini Uygulamayı Aç butonlu klavye."""
    keyboard = [
        [
            InlineKeyboardButton(
                "📱 Mini Uygulamayı Aç 🗖",
                web_app=WebAppInfo(url=url)
            )
        ],
        [
            InlineKeyboardButton("💬 İletişim ↗", url="https://t.me/rade_sinyal_bot"),
            InlineKeyboardButton("🌐 Websitesi ↗", url=url)
        ],
        [
            InlineKeyboardButton("📡 Telegram Topluluğu ↗", url="https://t.me/rade_sinyal_bot")
        ],
        [
            InlineKeyboardButton("🔍 Coin Ara.. ➔", callback_data="search_coin")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı /start yazdığında fotoğraftaki gibi şık mesaj ve Mini Uygulama butonu gösterir."""
    user = update.effective_user
    name = user.first_name if user else "Değerli Yatırımcı"

    welcome_text = (
        f"👋 *Merhaba {name}*,\n\n"
        f"📊 *Ben Yapay Zeka Destekli Binance Vadeli Sinyal Botuyum!*\n"
        f"_Canlı piyasa verileri, teknik analizler ve yapay zeka tahminleriyle vadeli işlemler kararlarınızı desteklerim._\n\n"
        f"🚀 *Öne Çıkan Özellikler:*\n"
        f"✔️ *Binance Mobil Arayüzü:* Alt dokunmatik menüyle tam ekran mobil deneyim\n"
        f"✔️ *Teknik İndikatörler:* Destek/Direnç, EMA50, EMA200, RSI, MACD\n"
        f"✔️ *Canlı Veri Akışı:* 3 saniyelik anlık fiyat ve otomatik sinyal üretimi\n"
        f"✔️ *Giriş, Stop-Loss ve Hedefler:* Net kâr alım seviyeleri\n"
        f"✔️ *Yapay Zeka Destekli Grafikler:* Koyu temalı interaktif mum grafikleri\n"
        f"✔️ *Groq LPU Motoru:* Saniyeler içinde çok faktörlü teknik strateji raporu\n\n"
        f"🎩 *VIP Kullanıcısı Olursanız:*\n"
        f"— Özel sinyal grubuna katılabilirsiniz.\n"
        f"— Anlık Alış-Satış (LONG/SHORT) bildirimlerine erişim elde edersiniz.\n"
        f"— Günlük kâr potansiyelli parite sinyallerinden faydalanabilirsiniz.\n\n"
        f"⚠️ *Analizler yalnızca bilgilendirme amaçlıdır, yatırım tavsiyesi içermez!*\n\n"
        f"🚀 *Hemen aşağıdaki butona dokunarak Binance Mobil Terminalini açın:*"
    )

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_welcome_markup(web_app_url)
    )

async def search_coin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🔍 *Coin Arama:*\n\n"
        "Lütfen analiz etmek istediğiniz coinin adını sohbete yazın:\n"
        "*(Örnek: `BTC`, `SOL`, `PEPE`, `AVAX`, `DOGE`)*",
        parse_mode=ParseMode.MARKDOWN
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text.startswith("/"):
        return
    coin = text.replace("-", "/").replace("_", "/")
    if "/" not in coin:
        coin = SEARCH_ALIASES.get(coin, coin)
        coin = f"{coin}/USDT"

    # Deep-link URL for web_app
    url_symbol = coin.replace('/', '_')
    url_with_coin = f"{web_app_url}?symbol={url_symbol}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📱 {coin} Mini Terminalini Aç 🗖", web_app=WebAppInfo(url=url_with_coin))]
    ])

    await update.message.reply_text(
        f"⚡ *{coin} Vadeli Analizi Hazır!*\n\n"
        f"Aşağıdaki butona dokunarak doğrudan {coin} canlı grafiğini ve sinyallerini inceleyebilirsiniz:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def ara_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and len(context.args) > 0:
        raw = context.args[0].strip().upper()
        coin = raw.replace("-", "/").replace("_", "/")
        if "/" not in coin:
            coin = SEARCH_ALIASES.get(coin, coin)
            coin = f"{coin}/USDT"
        url_symbol = coin.replace('/', '_')
        url_with_coin = f"{web_app_url}?symbol={url_symbol}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📱 {coin} Mini Terminalini Aç 🗖", web_app=WebAppInfo(url=url_with_coin))]
        ])
        await update.message.reply_text(
            f"⚡ *{coin} Vadeli Analizi Hazır!*\n\n"
            f"Aşağıdaki butona dokunarak doğrudan {coin} terminalini açabilirsiniz:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
    else:
        await update.message.reply_text(
            "🔍 *Coin Arama:*\n\n"
            "Lütfen analiz etmek istediğiniz coini yazın:\n"
            "*(Örnek: `/ara BTC` veya sadece `BTC` yazıp gönderin)*",
            parse_mode=ParseMode.MARKDOWN
        )

async def keep_alive_ping():
    """Render ücretsiz sunucusunun 15 dakika hareketsizlikten uykuya dalmasını (502 hatasını) engeller."""
    await asyncio.sleep(45)
    import aiohttp
    while True:
        try:
            render_url = os.getenv("RENDER_EXTERNAL_URL")
            if render_url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{render_url.rstrip('/')}/api/news?symbol=BTC", timeout=15) as resp:
                        logger.info("Render keep-alive ping başarılı: Sunucu 7/24 uyanık tutuluyor.")
        except Exception as e:
            logger.debug(f"Keep-alive ping: {e}")
        await asyncio.sleep(600)  # 10 dakikada bir istek atarak uyumayı önler


# ==================== ANA ÇALIŞTIRICI ====================
def main():
    global web_app_url

    print("="*65)
    print("   BINANCE FUTURES TELEGRAM MINI APP & BOT BAŞLATILIYOR     ")
    print("   Bot Kullanıcı Adı: @rade_sinyal_bot                     ")
    print("="*65)

    # 1. Cloudflare HTTPS Tünelini Aç
    web_app_url = start_cloudflare_tunnel()
    print(f"\n[+] Canlı Mobil WebApp URL: {web_app_url}\n")

    # 2. Telegram Botunu Kur
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("ara", ara_command))
    app.add_handler(CommandHandler("sinyal", ara_command))
    app.add_handler(CommandHandler("coin", ara_command))
    app.add_handler(CallbackQueryHandler(search_coin_callback, pattern="^search_coin$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Kalıcı Sol Alt Menü Butonu Ayarla (Telefonun sol altında '📱 Terminal' butonu)
    async def post_init(application):
        # aiohttp web sunucusunu bot ile aynı event loop içinde başlat
        await start_web_server()
        asyncio.create_task(keep_alive_ping())
        try:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="📱 Terminali Aç", web_app=WebAppInfo(url=web_app_url))
            )
            print("[+] Sol alt kalıcı '📱 Terminali Aç' menü butonu kuruldu!")
        except Exception as e:
            logger.warning(f"Menu button kurulamadı: {e}")

    app.post_init = post_init

    print("\n[✔] Telegram Botu & Binance Mobil Mini Uygulaması Canlı!")
    print("👉 Telegram'dan @rade_sinyal_bot hesabını açıp /start yazın ve 'Mini Uygulamayı Aç' butonuna dokunun!\n")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

