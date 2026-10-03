import json
import logging
from typing import Dict, Any, Optional, List
from groq import Groq, AuthenticationError, RateLimitError, APIConnectionError, APIError

logger = logging.getLogger("BinanceSignals")

SYSTEM_PROMPT = """Sen dünyanın en iyi hedge fonlarında ve algoritmik kripto para masalarında çalışmış Kıdemli Kripto Para Vadeli İşlemler (Binance Futures Long/Short) Trader ve Baş Stratejistisin.

Görevin:
Sana sağlanan Binance Futures paritesinin anlık mum verilerini ve teknik göstergelerini (RSI 14, MACD, MACD Signal, MACD Histogram, EMA 50, EMA 200, ATR 14) analiz ederek kullanıcıya "Şu fiyattan gir, şu fiyatta stop ol, şu fiyatta sat/kâr al" şeklinde KESİN VE NET BİR VADELİ İŞLEM EMİR TALİMATI vermektir.

VADELİ İŞLEM STRATEJİ VE KARAR KURALLARI:
1. LONG (Alım / Yükseliş Pozisyonu):
   - Fiyat EMA 50 ve/veya EMA 200 üzerindeyse veya belirgin bir destekten dönüyorsa,
   - RSI 50 seviyesini yukarı kırıyorsa veya 30 civarından yukarı sekiyorsa,
   - MACD al sinyali veriyorsa.
   - Giriş Fiyatı: Güncel piyasa fiyatı veya ufak bir geri çekilme seviyesi.
   - Stop Loss: Destek altı veya ATR bazlı (Giriş fiyatının altına).
   - Take Profit 1 & 2: Direnç seviyeleri veya ATR katları (Giriş fiyatının üstüne).

2. SHORT (Satım / Düşüş Pozisyonu):
   - Fiyat EMA 50 ve/veya EMA 200 altındaysa veya belirgin bir dirençten reddediliyorsa,
   - RSI 50 seviyesini aşağı kırıyorsa veya 70 civarından aşağı dönüyorsa,
   - MACD sat sinyali veriyorsa.
   - Giriş Fiyatı: Güncel piyasa fiyatı veya ufak bir yukarı sıçrama seviyesi.
   - Stop Loss: Direnç üstü veya ATR bazlı (Giriş fiyatının üstüne).
   - Take Profit 1 & 2: Destek seviyeleri veya ATR katları (Giriş fiyatının altına).

3. BEKLE (Piyasa Kararsız / İşleme Girme):
   - İndikatörler çelişkiliyse, piyasa testere (chop/range) modundaysa, risk/getiri oranı 1:1.5'in altındaysa "BEKLE" ver.

KESİN ÇIKTI KURALI (SADECE JSON):
Yanıtın SADECE ve SADECE aşağıdaki JSON şemasında olmalıdır. Markdown blokları (```) veya JSON dışı hiçbir metin ekleme.
{
  "Yon": "LONG" | "SHORT" | "BEKLE",
  "Giris_Fiyati": 0.0,
  "Stop_Loss": 0.0,
  "Take_Profit_1": 0.0,
  "Take_Profit_2": 0.0,
  "Take_Profit": 0.0,
  "Onerilen_Kaldirac": "5x - 10x",
  "Risk_Getiri_Orani": "1:2.5",
  "Net_Emir_Talimati": "Türkçe çok net talimat: [Giriş Seviyesi]'nden [LONG/SHORT] aç. [Stop Seviyesi]'ne Stop Loss koy. [TP1]'de yarısını sat, [TP2]'de tamamen kâr alarak pozisyonu kapat.",
  "Gerekce": "RSI, MACD ve EMA uyumunu açıklayan 2-3 cümlelik profesyonel teknik analiz özeti."
}

Eğer yön "BEKLE" ise:
- Giris_Fiyati güncel fiyattır, Stop_Loss ve Take_Profit 0.0 olabilir.
- Net_Emir_Talimati: Neden şu an vadeli işleme girilmemesi gerektiğini ve hangi kırılımın beklenmesi gerektiğini açıkça belirtmelidir.
"""

ACTIVE_GROQ_MODELS = [
    "openai/gpt-oss-120b",                         # En güçlü akıl yürütme modeli (500 t/s)
    "openai/gpt-oss-20b",                          # Ultra hızlı üretim modeli (1000 t/s)
    "qwen/qwen3.8-27b",                            # Yüksek başarımlı Qwen modeli (450 t/s)
    "meta-llama/llama-4-scout-17b-16e-instruct",   # Llama 4 Scout
    "meta-llama/llama-4-maverick-17b-128e-instruct", # Llama 4 Maverick
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant"
]

class AISignalEngine:
    """
    Groq LPU altyapısını kullanarak Binance Futures için
    kesin giriş, stop-loss ve take-profit emirleri üreten yapay zeka motoru.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "openai/gpt-oss-120b"):
        self.api_key = self._normalize_api_key(api_key) if api_key else ""
        self.model = model

    def _normalize_api_key(self, api_key: str) -> str:
        k = api_key.strip()
        p = "g" + "s" + "k_"
        if k and not k.startswith(p) and len(k) >= 20:
            return f"{p}{k}"
        return k

    def set_api_key(self, api_key: str):
        self.api_key = self._normalize_api_key(api_key)

    def set_model(self, model: str):
        self.model = model.strip()

    def get_account_models(self) -> List[str]:
        """
        Kullanıcının Groq hesabında erişilebilir olan aktif chat modellerini dinamik çeker.
        """
        if not self.api_key:
            return ACTIVE_GROQ_MODELS

        try:
            client = Groq(api_key=self.api_key, timeout=8.0)
            model_list = client.models.list()
            chat_models = []
            for m in model_list.data:
                mid = m.id.lower()
                if any(x in mid for x in ["whisper", "guard", "rerank", "embed", "safeguard"]):
                    continue
                chat_models.append(m.id)

            def sort_key(name):
                for i, pref in enumerate(ACTIVE_GROQ_MODELS):
                    if pref == name:
                        return i
                return 99

            chat_models.sort(key=sort_key)
            return chat_models if chat_models else ACTIVE_GROQ_MODELS
        except Exception as e:
            logger.warning(f"Groq API modelleri listelenemedi: {e}")
            return ACTIVE_GROQ_MODELS

    def _call_groq(self, client: Groq, model: str, user_content: str) -> Dict[str, Any]:
        """Groq API çağrısını gerçekleştirir ve JSON doğrulaması yapar."""
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        
        raw_text = response.choices[0].message.content
        if not raw_text:
            raise ValueError("Groq API'den boş yanıt döndü.")

        data = json.loads(raw_text)

        # Şema Tamamlama ve Doğrulama
        yon = str(data.get("Yon", "BEKLE")).upper().strip()
        if "BUY" in yon or "LONG" in yon:
            yon = "LONG"
        elif "SELL" in yon or "SHORT" in yon:
            yon = "SHORT"
        else:
            yon = "BEKLE"
        data["Yon"] = yon

        try:
            data["Giris_Fiyati"] = float(data.get("Giris_Fiyati", 0.0))
            data["Stop_Loss"] = float(data.get("Stop_Loss", 0.0))
            tp1 = float(data.get("Take_Profit_1") or data.get("Take_Profit", 0.0))
            tp2 = float(data.get("Take_Profit_2") or tp1)
            data["Take_Profit_1"] = tp1
            data["Take_Profit_2"] = tp2
            data["Take_Profit"] = tp1
        except (ValueError, TypeError):
            pass

        if "Onerilen_Kaldirac" not in data:
            data["Onerilen_Kaldirac"] = "5x - 10x" if yon != "BEKLE" else "N/A"
        if "Risk_Getiri_Orani" not in data:
            data["Risk_Getiri_Orani"] = "1:2.0" if yon != "BEKLE" else "N/A"
        if "Net_Emir_Talimati" not in data:
            data["Net_Emir_Talimati"] = data.get("Gerekce", "İşlem talimatı üretildi.")
        if "Gerekce" not in data:
            data["Gerekce"] = data.get("Net_Emir_Talimati", "Açıklama belirtilmedi.")

        return data

    def generate_signal(self, market_data: Dict[str, Any], on_fallback_callback=None) -> Dict[str, Any]:
        """
        Piyasa verilerini Groq LPU API'sine iletir.
        """
        if not self.api_key:
            raise ValueError(
                "Groq API Anahtarı eksik! Lütfen Render veya .env dosyasından geçerli bir Groq API anahtarı sağlayın."
            )

        client = Groq(api_key=self.api_key, timeout=20.0)

        symbol = market_data.get("symbol", "Bilinmeyen")
        timeframe = market_data.get("timeframe", "15m")
        current_price = market_data.get("current_price", 0.0)
        indicators = market_data.get("indicators", {})
        recent_candles = market_data.get("recent_candles", [])

        user_content = f"""Lütfen aşağıdaki Binance Vadeli İşlemler (Futures USDT-M) piyasa verisini analiz et ve kesin vadeli işlem emri (LONG/SHORT) üret:

[PARİTE]: {symbol} (Binance Futures USDT-M)
[ZAMAN DİLİMİ]: {timeframe}
[GÜNCEL FİYAT]: {current_price} USDT
[ÖNCEKİ KAPANIS]: {market_data.get('previous_close', 'N/A')} USDT
[FİYAT DEĞİŞİMİ (%)]: %{market_data.get('price_change_pct', 0.0)}

[TEKNİK GÖSTERGELER]:
- RSI (14): {indicators.get('rsi_14')}
- MACD: {indicators.get('macd')}
- MACD Signal: {indicators.get('macd_signal')}
- MACD Histogram: {indicators.get('macd_histogram')}
- EMA (50): {indicators.get('ema_50')} USDT
- EMA (200): {indicators.get('ema_200')} USDT
- ATR (14 - Volatilite): {indicators.get('atr_14')} USDT

[SON 5 MUM (OHLCV)]:
{json.dumps(recent_candles, indent=2)}

Vadeli işlem için net Giriş Fiyatı, kesin Stop Loss ve Take Profit (Satış) seviyelerini belirle. Sadece JSON dön."""

        account_models = self.get_account_models()
        candidate_models = []
        if self.model:
            candidate_models.append(self.model)
        for m in account_models:
            if m not in candidate_models:
                candidate_models.append(m)
        for m in ACTIVE_GROQ_MODELS:
            if m not in candidate_models:
                candidate_models.append(m)

        last_error = None
        for idx, model_candidate in enumerate(candidate_models):
            try:
                if idx > 0 and on_fallback_callback:
                    on_fallback_callback(model_candidate)
                
                result = self._call_groq(client, model_candidate, user_content)
                self.model = model_candidate
                return result

            except APIError as ae:
                last_error = ae
                err_text = str(ae).lower()
                if any(k in err_text for k in [
                    "model_decommissioned", 
                    "model_not_found", 
                    "does not exist", 
                    "no longer supported", 
                    "not have access", 
                    "decommissioned",
                    "404", 
                    "400"
                ]):
                    logger.warning(f"Groq modeli '{model_candidate}' kullanılamıyor, sıradaki model deneniyor...")
                    continue
                else:
                    raise ae
            except (AuthenticationError, RateLimitError, APIConnectionError):
                raise
            except Exception as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise RuntimeError("Groq modelleri denendi ancak yanıt alınamadı.")
