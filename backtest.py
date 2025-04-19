# Gerekli kütüphaneleri import et
import ccxt
import pandas as pd
import ta # Teknik Analiz kütüphanesi
import time
import datetime
import os
# import numpy as np # İleri analizler için gerekebilir
# import matplotlib.pyplot as plt # Grafik çizimleri için gerekebilir

# --- YAPILANDIRMA (CONFIG) ---
# Binance bağlantısı
# Sadece tarihsel veri çekmek için kullanılacak, gerçek işlem yapmayacak.
# API anahtarlarına burada ihtiyacın yok.
exchange = ccxt.binance({'enableRateLimit': True})

# Backtest edilecek parite ve zaman dilimi
symbol = 'ETH/USDT' # Örneğin: 'BTC/USDT', 'ETH/USDT', 'AERGO/USDT' vb.
timeframe = '1m'    # Örneğin: '1m', '5m', '15m', '1h', '1d'

# Stratejiye ve backtest'e özel parametreler
leverage = 10       # Orijinal stratejinin P/L hesaplamasında kullandığı kaldıraç
initial_balance = 10 # Backtest'e başlanacak sanal bakiye
target_balance = 100 # Backtest hedefi (ulaşınca durur)

# --- BACKTEST'E ÖZEL YAPILANDIRMA ---
# Backtest yapmak istediğin tarih aralığını buraya gir!
# Format: 'YYYY-MM-DD HH:mm:ss'
start_date_str = '2024-01-01 00:00:00' # <-- BAŞLANGIÇ TARİHİ (ÖRNEK)
end_date_str = '2024-03-31 23:59:59'   # <-- BİTİŞ TARİHİ (ÖRNEK)
# Daha uzun bir aralık test etmek için bu tarihleri değiştirebilirsin.

# --- Tarihsel Veri Yükleme Fonksiyonu ---
def load_historical_data(symbol, timeframe, start_date_str, end_date_str):
    """
    Belirtilen tarih aralığı için tarihsel OHLCV verisini çeker.
    """
    print(f"{symbol} {timeframe} için {start_date_str} - {end_date_str} arası tarihsel veri çekiliyor...")

    # Tarih stringlerini milisaniye cinsinden zamana çevir
    try:
        start_date_ms = int(datetime.datetime.strptime(start_date_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        end_date_ms = int(datetime.datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
    except ValueError as e:
        print(f"Hata: Geçersiz tarih formatı. Lütfen 'YYYY-MM-DD HH:mm:ss' formatını kullanın. Hata: {e}")
        return pd.DataFrame() # Boş DataFrame döndür

    all_bars = []
    since = start_date_ms
    limit_per_request = 1000 # Her istekte çekilecek mum sayısı (API limitine göre ayarla)

    # Belirtilen bitiş tarihine kadar veriyi parça parça çek
    while since < end_date_ms:
        # Eğer çekilecek veri miktarı limit_per_request'ten az ise, kalan kadar çek
        # Ancak fetch_ohlcv 'since' ve 'limit' ile çalıştığı için,
        # döngü sonunda since'i bir sonraki bara ayarlamak daha sağlamdır.
        # Bitiş kontrolünü ise çekilen verinin zaman damgasına göre yaparız.

        try:
            # Veriyi çek (limit_per_request mum kadar veya kalan kadar)
            # 'since' parametresi milisaniye cinsindendir
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit_per_request)

            if not bars:
                # Veri gelmediyse veya bittiyse döngüden çık
                print("Veri çekme tamamlandı.")
                break

            all_bars.extend(bars)
            # Bir sonraki çekim için başlangıç noktasını son barın zaman damgasının bir fazlası yap
            since = bars[-1][0] + 1

            # İsteğe bağlı: API rate limitine takılmamak için kısa bir bekleme
            # time.sleep(exchange.rateLimit / 1000) # exchange.rateLimit ccxt'de tanımlı değilse kaldır
            # Alternatif olarak sabit bir bekleme: time.sleep(0.1)

            # Bilgi mesajı yazdır (Her N bar çekildiğinde veya her istekte)
            # print(f"Şu ana kadar çekildi: {len(all_bars)} bar. Son bar: {datetime.datetime.fromtimestamp(bars[-1][0] / 1000)}")

        except Exception as e:
            print(f"Veri çekme hatası: {e}. 10 saniye bekleniyor...")
            time.sleep(10) # Hata durumunda bekle ve tekrar dene
            continue # Hata olduğunda döngü başına dön

    # Çekilen veriyi pandas DataFrame'ine dönüştür
    df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    # Verinin zaman damgasına göre sıralı olduğundan emin ol
    df.sort_values('timestamp', inplace=True)
    df.set_index('timestamp', inplace=True)

    # Belirtilen bitiş tarihinden sonrasındaki barları sil (çekim sırasında fazladan gelmiş olabilir)
    # Timestamp indeksi üzerinde filtreleme
    df = df[df.index <= datetime.datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')]

    print(f"Toplam {len(df)} bar yüklendi ve backtest aralığına göre filtrelendi.")
    if df.empty:
        print("Uyarı: Belirtilen tarih aralığında veya paritede hiç veri çekilemedi.")
    return df

# --- Göstergeleri Uygulama Fonksiyonu ---
def apply_indicators(df):
    """
    DataFrame'e teknik göstergeleri uygular.
    """
    print("Göstergeler hesaplanıyor...")
    # Göstergeler için yeterli veri olduğundan emin ol
    # En büyük pencere boyutu (EMA200 = 200) kadar bar olmalı minimum
    min_data_needed = 200

    if len(df) < min_data_needed:
        print(f"Uyarı: Göstergeleri hesaplamak için yeterli veri yok. ({len(df)} bar, minimum {min_data_needed} bar gerekli)")
        return pd.DataFrame() # Boş DataFrame döndür

    # ta kütüphanesini kullanarak göstergeleri hesapla
    # .iloc[:] eklemek, pandas'ın eski versiyonlarında slice objesi döndürmesi durumuna karşı güvenliktir.
    # Yeni versiyonlarda doğrudan Series döndürür.
    df['EMA9'] = ta.trend.ema_indicator(df['close'], window=9)
    df['EMA21'] = ta.trend.ema_indicator(df['close'], window=21)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)
    df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200)
    df['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    # VWAP kümülatiftir, backtest sırasında her adımda yeniden hesaplanması veya özel ele alınması daha doğru olabilir.
    # Ancak basitleştirilmiş backtest için tüm data üzerinden hesaplayalım.
    df['VWAP'] = ta.volume.VolumeWeightedAveragePrice(df['high'], df['low'], df['close'], df['volume']).volume_weighted_average_price()
    df['ADX'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
    df['ATR'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
    df['VolumeMA'] = df['volume'].rolling(window=20).mean()

    # Göstergelerin başlangıcında oluşan NaN (geçersiz) satırları sil
    initial_nan_rows = df.isnull().any(axis=1).sum()
    df.dropna(inplace=True)
    print(f"Göstergeler uygulandı ve başlangıçtaki {initial_nan_rows} NaN satır silindi. Geriye {len(df)} bar kaldı.")
    if df.empty:
         print("Uyarı: Göstergeler uygulandıktan sonra backtest için hiç veri kalmadı.")
    return df

# --- Sinyal Üretme Fonksiyonu (Backtest Döngüsü İçin) ---
def signal_generator(df_indexed, i):
    """
    Belirtilen indeksteki çubuk için alım/satım sinyali üretir.
    Look-ahead bias'ı önlemek için sadece 'i' ve öncesindeki data kullanılır.
    """
    # i, df_indexed DataFrame'indeki mevcut çubuğun integer indeksidir.
    # Göstergeler zaten tüm df'e uygulandı ve NaN satırlar apply_indicators'ta atıldı.
    # Dolayısıyla df_indexed'in ilk indeksi (0) bile geçerli gösterge datasına sahiptir.
    # Ancak sinyal mantığı prev çubuğa bakıyorsa i==0 durumunu kontrol etmeliyiz.

    current = df_indexed.iloc[i]

    # Sinyal için önceki çubuğun değerlerine ihtiyacımız olabilir
    if i == 0:
        # İlk bar için önceki bar olmadığından sinyal üretilemez
        return None
    prev = df_indexed.iloc[i-1] # Önceki çubuğa erişim

    # İhtiyaç duyulan gösterge değerlerinin mevcut çubukta NaN olmadığını apply_indicators zaten garanti etti.

    # Balina tespiti (hacim spike) - Mevcut çubuğun hacim ve kapanış/açılış fiyatı kullanılır
    whale_buy = current['volume'] > 2 * current['VolumeMA'] and current['close'] > current['open']
    whale_sell = current['volume'] > 2 * current['VolumeMA'] and current['close'] < current['open']

    # Trend filtresi (ADX + EMA200) - Mevcut çubuğun gösterge değerleri kullanılır
    is_bull = current['EMA50'] > current['EMA200'] and current['ADX'] > 20
    is_bear = current['EMA50'] < current['EMA200'] and current['ADX'] > 20

    # Long Sinyali Mantığı (Orijinal kodundaki şartlar, mevcut çubuğun değerleriyle)
    if current['EMA9'] > current['EMA21'] and \
       current['EMA21'] > current['EMA50'] and \
       current['close'] > current['VWAP'] and \
       current['RSI'] < 70 and \
       is_bull and \
       whale_buy:
        return 'long'

    # Short Sinyali Mantığı (Orijinal kodundaki şartlar, mevcut çubuğun değerleriyle)
    if current['EMA9'] < current['EMA21'] and \
       current['EMA21'] < current['EMA50'] and \
       current['close'] < current['VWAP'] and \
       current['RSI'] > 30 and \
       is_bear and \
       whale_sell:
        return 'short'

    return None # Sinyal yok

# --- Backtest Çalıştırma Fonksiyonu ---
def run_backtest(df, initial_balance, leverage, target_balance):
    """
    Tarihsel veri üzerinde alım satım stratejisini simüle eder.
    """
    balance = initial_balance # Anlık sanal bakiye
    position = None # Açık pozisyon durumu ('long', 'short', None)
    entry_price = 0 # Pozisyona giriş fiyatı
    entry_time = None # Pozisyona giriş zamanı
    entry_atr = 0 # Pozisyona girildiği anki ATR değeri (P/L hesabı için)
    trades_history = [] # Tamamlanan işlemleri kaydeden liste
    peak_balance = initial_balance # Maksimum bakiye takibi (Drawdown için kullanılır)

    # DataFrame'i integer index ile kullanmak, döngüde iloc kullanırken kolaylık sağlar
    df_indexed = df.reset_index()

    print(f"\nBacktest simülasyonu başlatılıyor...")
    print(f"Başlangıç Bakiyesi: ${balance:.2f}")
    print(f"Test Edilen Aralığındaki Bar Sayısı: {len(df_indexed)}")


    # Backtest döngüsü: Her mum çubuğu üzerinde sırayla ilerle
    for i in range(len(df_indexed)):
        current_bar = df_indexed.iloc[i]
        current_time = current_bar['timestamp']
        current_price = current_bar['close']
        current_high = current_bar['high']
        current_low = current_bar['low']

        # İlerleme durumunu göster (örn: Her 1000 barda bir)
        # if i % 1000 == 0:
        #     print(f"Simülasyon İlerleme: {current_time}")

        # --- Pozisyon Yönetimi (Çıkış Kontrolü) ---
        if position is not None:
            # TP ve SL seviyelerini hesapla (Giriş anındaki ATR'ye göre)
            # Önemli: Kullanıcının orijinal kodundaki P/L hesaplama mantığına sadık kalıyoruz.
            # TP/SL mesafeleri ATR'nin katları, Kar/Zarar ise bu mesafenin kaldıraçla çarpımı gibi.
            tp_level = entry_price + (entry_atr * 2) if position == 'long' else entry_price - (entry_atr * 2)
            sl_level = entry_price - (entry_atr * 1.5) if position == 'long' else entry_price + (entry_atr * 1.5) # Short için SL girişe eklenir

            sl_hit = False
            tp_hit = False
            exit_price = None
            pnl = 0 # Bu işlemden elde edilen kar/zarar miktarı

            # SL/TP vuruldu mu kontrolü (Bu çubuğun HIGH/LOW aralığında)
            if position == 'long':
                # Long pozisyonda SL kontrolü (fiyat SL'nin altına düştüyse)
                if current_low <= sl_level:
                    sl_hit = True
                    exit_price = sl_level # Çıkış fiyatını SL seviyesi alalım
                    pnl = -(entry_atr * 1.5 * leverage) # Kayıp hesabı
                # SL vurulmadıysa TP kontrolü (fiyat TP'nin üzerine çıktıysa)
                elif current_high >= tp_level:
                    tp_hit = True
                    exit_price = tp_level # Çıkış fiyatını TP seviyesi alalım
                    pnl = (entry_atr * 2 * leverage) # Kar hesabı

            elif position == 'short':
                 # Short pozisyonda TP kontrolü (fiyat TP'nin altına düştüyse)
                 if current_low <= tp_level: # Short için TP giriş fiyatının altındadır
                      tp_hit = True
                      exit_price = tp_level # Çıkış fiyatını TP seviyesi alalım
                      pnl = (entry_atr * 2 * leverage) # Kar hesabı
                 # TP vurulmadıysa SL kontrolü (fiyat SL'nin üzerine çıktıysa)
                 elif current_high >= sl_level: # Short için SL giriş fiyatının üstündedir
                      sl_hit = True
                      exit_price = sl_level # Çıkış fiyatını SL seviyesi alalım
                      pnl = -(entry_atr * 1.5 * leverage) # Kayıp hesabı

            # ÖNEMLİ NOT: Eğer aynı çubuk içinde hem SL hem TP vurulma olasılığı varsa (low <= SL < TP <= high veya low <= TP < SL <= high),
            # bu basit model hangisinin önce vurulduğunu doğru tahmin edemez. Genellikle
            # giriş fiyatına göre hangisi daha yakınsa onun önce vurulduğu varsayılır veya
            # belirli bir sıra izlenir (örn: long için önce SL, sonra TP). Yukarıdaki kodda basit bir
            # if/elif yapısı ile bu sıra (long=SL öncelik, short=TP öncelik) simüle edildi.
            # Daha gelişmiş backtestlerde çubuğun içinde fiyat hareketi modellenir.

            # Eğer pozisyon kapandıysa (SL veya TP vurulduysa)
            if sl_hit or tp_hit:
                balance += pnl # Hesaplanan kar/zararı bakiyeye ekle

                # Tamamlanan işlemi kaydet
                trades_history.append({
                    'EntryTime': entry_time,
                    'EntryPrice': entry_price,
                    'Direction': position,
                    'ExitTime': current_time,
                    'ExitPrice': exit_price,
                    'PNL': pnl, # Dolar cinsinden Net Kar/Zarar
                    'Result': 'TP' if tp_hit else 'SL', # Sonuç (TP veya SL)
                    'BalanceAfter': balance, # Bu işlem sonrası bakiye
                    'EntryATR': entry_atr # İşleme girildiği anki ATR değeri
                })

                # Pozisyonu sıfırla, giriş bilgilerini temizle
                position = None
                entry_price = 0
                entry_time = None
                entry_atr = 0

                # Maksimum bakiye takibini güncelle (Drawdown hesaplaması için)
                peak_balance = max(peak_balance, balance)

        # --- Sinyal Kontrolü ve Pozisyon Açma ---
        # Sadece açık bir pozisyon yokken yeni sinyal kontrol et
        if position is None:
            # Sinyal üret (Mevcut çubuğa kadar olan veriyi kullanarak)
            signal = signal_generator(df_indexed, i)

            if signal:
                # Pozisyon açılışı simülasyonu
                entry_price = current_price # Sinyal çubuğunun kapanış fiyatından girişi varsayalım
                entry_time = current_time # Giriş zamanı
                position = signal # Pozisyon durumunu güncelle
                entry_atr = current_bar['ATR'] # İşleme girildiği anki ATR değerini kaydet

                # print(f"İşlem Açıldı: {current_time} | {signal.upper()} | Giriş: {entry_price:.4f} | ATR: {entry_atr:.4f}") # İsteğe bağlı log


        # --- Hedef Bakiyeye Ulaşıldı mı veya Bakiye Sıfırlandı mı Kontrolü ---
        if balance >= target_balance:
            print(f"\n🏆 HEDEF BAKİYEYE ULAŞILDI! | Son Bakiye: ${balance:.2f} | Zaman: {current_time}")
            break # Döngüyü sonlandır, backtest bitti
        elif balance <= 0:
            print(f"\n💀 BAKİYE SIFIRLANDI. | Zaman: {current_time}")
            balance = 0 # Bakiyeyi 0 yap
            break # Döngüyü sonlandır, backtest bitti


    # --- Backtest Sonuçlarının Analizi ---
    print("\n--- BACKTEST SONUÇLARI ---")
    final_balance = balance # Döngü sonunda ulaşılan bakiye
    total_trades = len(trades_history) # Toplam işlem sayısı
    winning_trades = sum(1 for trade in trades_history if trade['PNL'] > 0) # Kazanan işlemler
    losing_trades = total_trades - winning_trades # Kaybeden işlemler
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0 # Kazanma oranı
    total_pnl = sum(trade['PNL'] for trade in trades_history) # Toplam Net Kar/Zarar

    # Maksimum Düşüş (Drawdown) Hesaplaması (Her işlem kapandıktan sonraki bakiyeye göre)
    # Bu basit bir hesaplamadır. Daha doğru bir drawdown için her barın kapanışındaki veya
    # pozisyon açıkkenki anlık bakiyeyi takip etmek gerekir.
    max_drawdown_percentage = 0
    if len(trades_history) > 0:
        # İşlem geçmişindeki bakiyeleri al ve başına başlangıç bakiyesini ekle
        balance_history_after_trades = [initial_balance] + [trade['BalanceAfter'] for trade in trades_history]
        balance_series = pd.Series(balance_history_after_trades)
        peak_balance_series = balance_series.cummax() # Kümülatif (birikimli) maksimum bakiyeyi bul
        drawdown_series = peak_balance_series - balance_series # Her noktada peak'ten ne kadar düşüş var
        # Maksimum düşüş miktarını ve yüzdesini hesapla
        max_drawdown_value = drawdown_series.max()
        # peak_balance_series.replace(0, 1) bölenin 0 olmasını engeller
        max_drawdown_percentage = (max_drawdown_value / peak_balance_series.replace(0, 1).max()) * 100


    print(f"Başlangıç Bakiyesi: ${initial_balance:.2f}")
    print(f"Son Bakiye: ${final_balance:.2f}")
    print(f"Test Edilen Dönem: {df_indexed['timestamp'].iloc[0]} - {df_indexed['timestamp'].iloc[-1]}")
    print(f"Toplam Kar/Zarar: ${total_pnl:.2f}")
    print(f"Toplam İşlem Sayısı: {total_trades}")
    print(f"Kazanan İşlem Sayısı: {winning_trades}")
    print(f"Kaybeden İşlem Sayısı: {losing_trades}")
    print(f"Kazanma Oranı: {win_rate:.2f}%")
    # print(f"Maksimum Düşüş Miktarı: ${max_drawdown_value:.2f}") # İsteğe bağlı
    print(f"Maksimum Düşüş (Drawdown): {max_drawdown_percentage:.2f}%")

    # İsteğe bağlı: Detaylı işlem geçmişini yazdırma
    # print("\n--- İşlem Geçmişi Detayları ---")
    # for i, trade in enumerate(trades_history):
    #     print(f"{i+1}. | {trade['EntryTime']} -> {trade['ExitTime']} | {trade['Direction'].upper()} | Giriş: {trade['EntryPrice']:.4f} | Çıkış: {trade['ExitPrice']:.4f} | PNL: {trade['PNL']:.2f} | Sonuç: {trade['Result']} | Bakiye: {trade['BalanceAfter']:.2f}")


# --- Ana Çalıştırma Bloğu ---
# Script doğrudan çalıştırıldığında burası çalışır
if __name__ == "__main__":
    # --- 1. Tarihsel Veriyi Yükle ---
    # Buradaki tarihleri istediğin gibi değiştirerek farklı dönemleri test edebilirsin.
    start_date = '2024-01-01 00:00:00'
    end_date = '2024-03-31 23:59:59' # Örnek: 2024 yılının ilk 3 ayı

    historical_df = load_historical_data(symbol, timeframe, start_date, end_date)

    if not historical_df.empty:
        # 2. Göstergeleri Uygula
        historical_df = apply_indicators(historical_df)

        if not historical_df.empty: # Göstergelerden sonra data kaldıysa devam et
             # 3. Backtest Simülasyonunu Çalıştır
            run_backtest(historical_df, initial_balance, leverage, target_balance)
        else:
            print("Backtest başlatılamadı: Göstergeler uygulandıktan sonra geçerli veri kalmadı.")
    else:
        print("Backtest başlatılamadı: Tarihsel veri yüklenemedi veya belirtilen aralıkta geçerli veri bulunamadı.")