import os
import sys
from datetime import datetime, timezone
import ccxt
import pandas as pd
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def format_utc(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%H:%M UTC")

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing BOT_TOKEN or CHAT_ID in Secrets")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("Telegram alert sent successfully.")
        else:
            print(f"Telegram API Error: {res.text}")
    except Exception as e:
        print(f"Telegram request failed: {e}")

def calculate_fib_levels(low_p, high_p):
    diff = high_p - low_p
    return {
        "0.0": low_p,
        "0.236": high_p - (0.764 * diff),
        "0.500": high_p - (0.500 * diff),
        "0.618": high_p - (0.382 * diff),
        "1.0": high_p
    }

def run_scanners():
    try:
        exchange = ccxt.delta()
        symbols = ['BTC/USD:BTC', 'ETH/USD:USD']
        timeframe = '5m'
        
        now_utc = datetime.now(timezone.utc)
        start_of_day_utc = datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=timezone.utc)
        since_ms = int(start_of_day_utc.timestamp() * 1000)

        for symbol in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=300)
                if not ohlcv or len(ohlcv) < 15:
                    print(f"Not enough data for {symbol}")
                    continue

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                clean_sym = symbol.split('/')[0]

                day_high_row = df.loc[df['high'].idxmax()]
                day_low_row = df.loc[df['low'].idxmin()]

                day_high_price = day_high_row['high']
                day_high_time = format_utc(day_high_row['timestamp'])
                day_low_price = day_low_row['low']
                day_low_time = format_utc(day_low_row['timestamp'])

                latest_candle = df.iloc[-2]
                curr_time = format_utc(latest_candle['timestamp'])
                is_green = latest_candle['close'] >= latest_candle['open']
                is_red = latest_candle['close'] < latest_candle['open']

                # ==========================================
                # 1. BUY SCENARIOS (Day Low -> Swing High)
                # ==========================================
                if day_low_row.name < len(df) - 4:
                    sub_df = df.iloc[day_low_row.name:]
                    swing_high_row = sub_df.loc[sub_df['high'].idxmax()]

                    if swing_high_row.name > day_low_row.name and swing_high_row.name < len(df) - 2:
                        swing_high_price = swing_high_row['high']
                        swing_high_time = format_utc(swing_high_row['timestamp'])
                        fibs = calculate_fib_levels(day_low_price, swing_high_price)
                        pullback_df = df.iloc[swing_high_row.name:-1]

                        # --- SETUP 1: Golden Zone Pullback (0.50 - 0.618) ---
                        in_golden_zone = any((r['low'] <= fibs["0.500"] and r['low'] >= fibs["0.618"]) for _, r in pullback_df.iterrows())
                        invalid_gz = any(r['close'] < fibs["0.618"] for _, r in pullback_df.iterrows())

                        if in_golden_zone and not invalid_gz and is_green and latest_candle['close'] > fibs["0.500"]:
                            entry = latest_candle['close']
                            sl = min(pullback_df['low'].min(), fibs["0.618"])
                            risk = entry - sl
                            msg_lines = [
                                f"🟡 *[SETUP 1] GOLDEN ZONE REVERSAL BUY ({clean_sym})*",
                                "",
                                "⏰ *Timeline (UTC):*",
                                f"• Day Low: `{day_low_time}` (${day_low_price:.2f})",
                                f"• Swing High: `{swing_high_time}` (${swing_high_price:.2f})",
                                f"• Trigger Time: `{curr_time}` (Green Bounce)",
                                "",
                                "📊 *Levels:*",
                                f"• 0.500 Zone: `${fibs['0.500']:.2f}`",
                                f"• 0.618 Zone: `${fibs['0.618']:.2f}`",
                                f"• Entry: `${entry:.2f}` | SL: `${sl:.2f}`",
                                f"• TP 1: `${entry + risk:.2f}` | TP 2: `${entry + (risk * 2):.2f}`"
                            ]
                            send_telegram("\n".join(msg_lines))

                        # --- SETUP 2: Deep Retrace to 0.236 Level ---
                        went_below_gz = any(r['low'] < fibs["0.618"] for _, r in pullback_df.iterrows())
                        touched_236 = any(r['low'] <= fibs["0.236"] for _, r in pullback_df.iterrows())

                        if went_below_gz and touched_236 and is_green and latest_candle['close'] > fibs["0.236"]:
                            entry = latest_candle['close']
                            sl = pullback_df['low'].min()
                            risk = entry - sl
                            msg_lines = [
                                f"🔵 *[SETUP 2] 0.236 DEEP RETRACE BUY ({clean_sym})*",
                                "",
                                "⏰ *Timeline (UTC):*",
                                f"• Day Low: `{day_low_time}` (${day_low_price:.2f})",
                                f"• Swing High: `{swing_high_time}` (${swing_high_price:.2f})",
                                f"• Trigger Time: `{curr_time}` (Green Close > 0.236)",
                                "",
                                "📊 *Levels:*",
                                f"• 0.236 Level: `${fibs['0.236']:.2f}`",
                                f"• Entry: `${entry:.2f}` | SL: `${sl:.2f}`",
                                f"• TP 1: `${entry + risk:.2f}` | TP 2: `${entry + (risk * 2):.2f}`"
                            ]
                            send_telegram("\n".join(msg_lines))

                # ==========================================
                # 2. SELL SCENARIOS (Day High -> Swing Low)
                # ==========================================
                if day_high_row.name < len(df) - 4:
                    sub_df = df.iloc[day_high_row.name:]
                    swing_low_row = sub_df.loc[sub_df['low'].idxmin()]

                    if swing_low_row.name > day_high_row.name and swing_low_row.name < len(df) - 2:
                        swing_low_price = swing_low_row['low']
                        swing_low_time = format_utc(swing_low_row['timestamp'])
                        fibs = calculate_fib_levels(swing_low_price, day_high_price)
                        pullback_df = df.iloc[swing_low_row.name:-1]

                        # --- SETUP 1: Golden Zone Pullback (0.50 - 0.618) ---
                        in_golden_zone = any((r['high'] >= fibs["0.500"] and r['high'] <= fibs["0.618"]) for _, r in pullback_df.iterrows())
                        invalid_gz = any(r['close'] > fibs["0.618"] for _, r in pullback_df.iterrows())

                        if in_golden_zone and not invalid_gz and is_red and latest_candle['close'] < fibs["0.500"]:
                            entry = latest_candle['close']
                            sl = max(pullback_df['high'].max(), fibs["0.618"])
                            risk = sl - entry
                            msg_lines = [
                                f"🟡 *[SETUP 1] GOLDEN ZONE REVERSAL SELL ({clean_sym})*",
                                "",
                                "⏰ *Timeline (UTC):*",
                                f"• Day High: `{day_high_time}` (${day_high_price:.2f})",
                                f"• Swing Low: `{swing_low_time}` (${swing_low_price:.2f})",
                                f"• Trigger Time: `{curr_time}` (Red Rejection)",
                                "",
                                "📊 *Levels:*",
                                f"• 0.500 Zone: `${fibs['0.500']:.2f}`",
                                f"• 0.618 Zone: `${fibs['0.618']:.2f}`",
                                f"• Entry: `${entry:.2f}` | SL: `${sl:.2f}`",
                                f"• TP 1: `${entry - risk:.2f}` | TP 2: `${entry - (risk * 2):.2f}`"
                            ]
                            send_telegram("\n".join(msg_lines))

                        # --- SETUP 2: Deep Retrace to 0.236 Level ---
                        went_above_gz = any(r['high'] > fibs["0.618"] for _, r in pullback_df.iterrows())
                        touched_236 = any(r['high'] >= fibs["0.236"] for _, r in pullback_df.iterrows())

                        if went_above_gz and touched_236 and is_red and latest_candle['close'] < fibs["0.236"]:
                            entry = latest_candle['close']
                            sl = pullback_df['high'].max()
                            risk = sl - entry
                            msg_lines = [
                                f"🔵 *[SETUP 2] 0.236 DEEP RETRACE SELL ({clean_sym})*",
                                "",
                                "⏰ *Timeline (UTC):*",
                                f"• Day High: `{day_high_time}` (${day_high_price:.2f})",
                                f"• Swing Low: `{swing_low_time}` (${swing_low_price:.2f})",
                                f"• Trigger Time: `{curr_time}` (Red Close < 0.236)",
                                "",
                                "📊 *Levels:*",
                                f"• 0.236 Level: `${fibs['0.236']:.2f}`",
                                f"• Entry: `${entry:.2f}` | SL: `${sl:.2f}`",
                                f"• TP 1: `${entry - risk:.2f}` | TP 2: `${entry - (risk * 2):.2f}`"
                            ]
                            send_telegram("\n".join(msg_lines))

            except Exception as e:
                print(f"Error on {symbol}: {e}")

    except Exception as e:
        print(f"Runner error: {e}")

if __name__ == "__main__":
    run_scanners()
