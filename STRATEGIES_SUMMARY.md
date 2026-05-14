# Trading Strategies Summary

## Quick Reference Table

| Strategy | Direction | Entry Conditions | Exit Conditions | SL/TP | Position Sizing |
|----------|-----------|-----------------|----------------|-------|----------------|
| **mgc_pullback** | Long | Close > SMA(200) AND RSI(2) < 30 | Close > SMA(32) | Bracket (risk-based) | Max position (1) |
| **mnq_condition1** | Long | High>H1 AND Low>L1 AND Close>Open (delayed) | SL/TP/Profitable closes/Time exit | Bracket (ATR-based) | Max position (1) |
| **mes_condition1** | Long | High>H1 AND Low>L1 AND Close>Open (delayed) | SL/TP/Profitable closes/Time exit | Bracket (ATR-based) | Max position (1) |
| **btc_rsi_meanrev** | Long | SMA50>SMA200 AND RSI2<30 AND VL5<VL5[6] | Time exit OR VL5>VL5[6] | None | Max position (1) |
| **btc2_valuelow_sma** | Long | SMA5<SMA200 AND RSI2<30 AND VL5<VO5 | Time exit OR SMA5>SMA5[2] | None | Max position (1) |
| **treasury_zn_eom** | Long | Last trading day of month | First trading day of month | None | Max position (1) |
| **treasury_30y_eom** | Long | Last trading day of month | First trading day of month | None | Max position (1) |
| **treasury_stoch_hurst** | Long | Stoch<20 AND Hurst<0.5 AND RSI2<30 | Time exit OR RSI2>=70 | None | Max position (1) |
| **rb_combined** | Long | N/A | N/A | N/A | Max position |
| **gold2_atr** | Long | ab=1 (Wed conditions OR Fri) | bars_held=2 AND ab=2 | None | ATR-based (risk $20K) |

---

## Detailed Parameters

| Strategy | Key Parameters | Max Bars | Delay | Risk USD |
|----------|---------------|----------|-------|---------|
| **mgc_pullback** | SMA200, RSI2(30), SMA32 | N/A | N/A | $11,000 |
| **mnq_condition1** | ATR14, mult2.0, max_time10, prof_close3 | 10 | 1 | $2,000 |
| **mes_condition1** | ATR14, mult2.0, max_time10, prof_close3 | 10 | 1 | $2,000 |
| **btc_rsi_meanrev** | SMA50/200, RSI2(30), VL5, max_time5 | 5 | 1 | N/A |
| **btc2_valuelow_sma** | SMA200, RSI2(30), VL5/VO5, max_time5 | 5 | 1 | N/A |
| **treasury_zn_eom** | None (time-based) | N/A | N/A | N/A |
| **treasury_30y_eom** | None (time-based) | N/A | N/A | N/A |
| **treasury_stoch_hurst** | Stoch(20), Hurst(0.5), RSI2(30/70), max_time5 | 5 | 1 | N/A |
| **rb_combined** | N/A | N/A | N/A | N/A |
| **gold2_atr** | ATR14, mult3.0, risk$20K | 2 | N/A | $20,000 |

---

## Exit Logic Summary

| Strategy | Primary Exit | Secondary Exit | Time Exit |
|----------|--------------|----------------|-----------|
| **mgc_pullback** | Close > SMA32 | N/A | N/A |
| **mnq_condition1** | SL / TP | Profitable closes | Max bars |
| **mes_condition1** | SL / TP | Profitable closes | Max bars |
| **btc_rsi_meanrev** | VL5 > VL5[6] | N/A | Max 5 bars |
| **btc2_valuelow_sma** | SMA5 > SMA5[2] | N/A | Max 5 bars |
| **treasury_zn_eom** | First trading day | N/A | N/A |
| **treasury_30y_eom** | First trading day | N/A | N/A |
| **treasury_stoch_hurst** | RSI2 >= 70 | N/A | Max 5 bars |
| **rb_combined** | N/A | N/A | N/A |
| **gold2_atr** | bars_held=2 AND ab=2 | N/A | N/A |

---

## Order Types

| Strategy | Entry Order | Exit Order | TIF |
|----------|-------------|-----------|-----|
| **mgc_pullback** | Bracket (Limit + SL + TP) | Cancel bracket | GTC |
| **mnq_condition1** | Bracket (Limit + SL + TP) | Cancel bracket | GTC |
| **mes_condition1** | Bracket (Limit + SL + TP) | Cancel bracket | GTC |
| **btc_rsi_meanrev** | Limit | Limit | GTC |
| **btc2_valuelow_sma** | Limit | Limit | GTC |
| **treasury_zn_eom** | Limit | Limit | GTC |
| **treasury_30y_eom** | Limit | Limit | GTC |
| **treasury_stoch_hurst** | Limit | Limit | GTC |
| **rb_combined** | N/A | N/A | GTC |
| **gold2_atr** | Limit (price+offset) | Limit (price-offset) | GTC |

---

## Common Features

**All Strategies:**
- ✅ Database position state tracking
- ✅ Mismatch detection (DB vs IBKR)
- ✅ Account-aware position queries
- ✅ TIF="GTC" (Good Till Cancelled)
- ✅ outsideRth=True (valid pre-market/after-hours)
- ✅ Position state persistence across runs

**Database Tables:**
- `position_state` - Strategy internal state
- `trades` - Trade history
- `positions` - IBKR snapshots (signals only)
- `orders` - Order history
