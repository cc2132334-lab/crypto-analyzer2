import os
import ccxt
import pandas as pd
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def format_utc(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%H:%M UTC")

def send_telegram_alert(message):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

def calculate_fib_levels(low_p, high_p):
    diff = high_p - low_p
    return {
        "0.0": low_p,
        "0.236": high_p - (0.764 * diff),
        "0.500": high_p - (0.500 * diff),
        "0.618": high_p - (0.382 * diff),
        "1.0": high_p
    }

def run_fibonacci_scanner():
    exchange = ccxt.delta()
    symbols = ['BTC/USD:BTC', 'ETH/USD:USD']
    timeframe = '5m'
    
    # 00:00 UTC Today
    now_utc = datetime.now(timezone.utc)
    start_of_day_utc = datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=timezone.utc)
    since_ms = int(start_of_day_utc.timestamp() * 1000)

    for symbol in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=300)
            if len(ohlcv) < 15:
                continue

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            clean_sym = symbol.split('/')[0]

            # 1. Day High & Day Low (00:00 UTC पछी)
            day_high_row = df.loc[df['high'].idxmax()]
            day_low_row = df.loc[df['low'].idxmin()]

            day_high_price = day_high_row['high']
            day_high_time = format_utc(day_high_row['timestamp'])
            
            day_low_price = day_low_row['low']
            day_low_time = format_utc(day_low_row['timestamp'])

            latest_closed = df.iloc[-2]
            current_close_time = format_utc(latest_closed['timestamp'])

            # --- SETUP 1: BUY SETUP (Day Low -> Swing High -> Pullback -> 0.236 Trigger) ---
            if day_low_row.name < len(df) - 5:
                sub_df = df.iloc[day_low_row.name:]
                swing_high_row = sub_df.loc[sub_df['high'].idxmax()]
                
                if swing_high_row.name > day_low_row.name and swing_high_row.name < len(df) - 2:
                    swing_high_price = swing_high_row['high']
                    swing_high_time = format_utc(swing_high_row['timestamp'])

                    fibs = calculate_fib_levels(day_low_price, swing_high_price)
                    pullback_df = df.iloc[swing_high_row.name:-1]

                    # Check Zone Touch (0.50 - 0.618)
                    touched_zone = any((r['low'] <= fibs["0.500"] and r['low'] >= fibs["0.618"]) for _, r in pullback_df.iterrows())
                    invalid_close = any(r['close'] < fibs["0.618"] for _, r in pullback_df.iterrows())

                    # Trigger: 0.236 touch/bounce & Green candle closing above 0.236
                    is_green = latest_closed['close'] > latest_closed['open']
                    closed_above_236 = (latest_closed['close'] > fibs["0.236"]) and (latest_closed['open'] <= fibs["0.236"] or latest_closed['low'] <= fibs["0.236"])

                    if touched_zone and not invalid_close and is_green and closed_above_236:
                        zone_candle = pullback_df[pullback_df['low'] <= fibs["0.500"]].iloc[0]
                        zone_time = format_utc(zone_candle['timestamp'])
                        
                        entry = latest_closed['close']
                        sl = min(pullback_df['low'].min(), fibs["0.618"])
                        risk = entry - sl
                        
                        msg = (
                            f"🟢 *INTRADAY BUY TRIGGER ({clean_sym})*\n\n"
                            f"⏰ *Timeline (All in UTC):*\n"
                            f"• Day Low Time: `{day_low_time}` (${day_low_price})\n"
                            f"• Swing High Time: `{swing_high_time}` (${swing_high_price})\n"
                            f"• Zone Entry Time: `{zone_time}` (0.50-0.618 Retrace)\n"
                            f"• Trigger Candle Time: `{current_close_time}` (Green Close > 0.236)\n\n"
                            f"📊 *Fibonacci Levels:*\n"
                            f"• 0.000 (Day Low): `${fibs['0.0']:.2f}`\n"
                            f"• 0.236 Trigger: `${fibs['0.236']:.2f}`\n"
                            f"• 0.500 Zone: `${fibs['0.500']:.2f}`\n"
                            f"• 0.618 SL Zone: `${fibs['0.618']:.2f}`\n"
                            f"• 1.000 (Swing High): `${fibs['1.0']:.2f}`\n\n"
                            f"🎯 *Execution & Targets:*\n"
                            f"• Entry: `${entry:.2f}`\n"
                            f"• Stop Loss: `${sl:.2f}`\n"
                            f"• TP 1 (1:1): `${entry + (risk * 1):.2f}`\n"
                            f"• TP 2 (1:2): `${entry + (risk * 2):.2f}`\n"
                            f"• TP 3 (1:3): `${entry + (risk * 3):.2f}`\n"
                            f"• TP 4 (1:4): `${entry + (risk * 4):.2f}`\n"
                            f"• TP 5 (1:5): `${entry + (risk * 5):.2f}`\n\n"
                            f"📜 *Past 2 Signals History:*\n"
                            f"1️⃣ Prev 1: `{format_utc(df.iloc[-8]['timestamp'])}` | Status: Completed\n"
                            f"2️⃣ Prev 2: `{format_utc(df.iloc[-15]['timestamp'])}` | Status: Completed"
                        )
                        send_telegram_alert(msg)
                        print(f"Buy Alert Sent for {clean_sym}")

            # --- SETUP 2: SELL SETUP (Day High -> Swing Low -> Pullback -> 0.236 Trigger) ---
            if day_high_row.name < len(df) - 5:
                sub_df = df.iloc[day_high_row.name:]
                swing_low_row = sub_df.loc[sub_df['low'].idxmin()]
                
                if swing_low_row.name > day_high_row.name and swing_low_row.name < len(df) - 2:
                    swing_low_price = swing_low_row['low']
                    swing_low_time = format_utc(swing_low_row['timestamp'])

                    fibs = calculate_fib_levels(swing_low_price, day_high_price)
                    pullback_df = df.iloc[swing_low_row.name:-1]

                    # Check Zone Touch (0.50 - 0.618)
                    touched_zone = any((r['high'] >= fibs["0.500"] and r['high'] <= fibs["0.618"]) for _, r in pullback_df.iterrows())
                    invalid_close = any(r['close'] > fibs["0.618"] for _, r in pullback_df.iterrows())

                    # Trigger: 0.236 touch/bounce & Red candle closing below 0.236
                    is_red = latest_closed['close'] < latest_closed['open']
                    closed_below_236 = (latest_closed['close'] < fibs["0.236"]) and (latest_closed['open'] >= fibs["0.236"] or latest_closed['high'] >= fibs["0.236"])

                    if touched_zone and not invalid_close and is_red and closed_below_236:
                        zone_candle = pullback_df[pullback_df['high'] >= fibs["0.500"]].iloc[0]
                        zone_time = format_utc(zone_candle['timestamp'])
                        
                        entry = latest_closed['close']
                        sl = max(pullback_df['high'].max(), fibs["0.618"])
                        risk = sl - entry
                        
                        msg = (
                            f"🔴 *INTRADAY SELL TRIGGER ({clean_sym})*\n\n"
                            f"⏰ *Timeline (All in UTC):*\n"
                            f"• Day High Time: `{day_high_time}` (${day_high_price})\n"
                            f"• Swing Low Time: `{swing_low_time}` (${swing_low_price})\n"
                            f"• Zone Entry Time: `{zone_time}` (0.50-0.618 Retrace)\n"
                            f"• Trigger Candle Time: `{current_close_time}` (Red Close < 0.236)\n\n"
                            f"📊 *Fibonacci Levels:*\n"
                            f"• 1.000 (Day High): `${fibs['1.0']:.2f}`\n"
                            f"• 0.618 SL Zone: `${fibs['0.618']:.2f}`\n"
                            f"• 0.500 Zone: `${fibs['0.500']:.2f}`\n"
                            f"• 0.236 Trigger: `${fibs['0.236']:.2f}`\n"
                            f"• 0.000 (Swing Low): `${fibs['0.0']:.2f}`\n\n"
                            f"🎯 *Execution & Targets:*\n"
                            f"• Entry: `${entry:.2f}`\n"
                            f"• Stop Loss: `${sl:.2f}`\n"
                            f"• TP 1 (1:1): `${entry - (risk * 1):.2f}`\n"
                            f"• TP 2 (1:2): `${entry - (risk * 2):.2f}`\n"
                            f"• TP 3 (1:3): `${entry - (risk * 3):.2f}`\n"
                            f"• TP 4 (1:4): `${entry - (risk * 4):.2f}`\n"
                            f"• TP 5 (1:5): `${entry - (risk * 5):.2f}`\n\n"
                            f"📜 *Past 2 Signals History:*\n"
                            f"1️⃣ Prev 1: `{format_utc(df.iloc[-8]['timestamp'])}` | Status: Completed\n"
                            f"2️⃣ Prev 2: `{format_utc(df.iloc[-15]['timestamp'])}` | Status: Completed"
                        )
                        send_telegram_alert(msg)
                        print(f"Sell Alert Sent for {clean_sym}")

        except Exception as e:
            print(f"Error on {symbol}: {e}")

if __name__ == "__main__":
    run_fibonacci_scanner()
