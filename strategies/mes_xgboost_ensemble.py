# strategies/mes_xgboost_ensemble.py
"""
strategies/mes_xgboost_ensemble.py
──────────────────────────────────
MES XGBoost Ensemble Strategy

Multi-asset ML strategy using 30 pre-trained XGBoost models for ensemble voting.
Fetches data from multiple sources (futures, FX, ETFs, macro indicators) and
builds 840+ features for prediction.

Entry Logic:
    - Load 30 XGBoost models from pickle file
    - For each model, predict on latest feature vector
    - Count votes: class 3 = BUY, class 1 = SELL
    - Net votes = buy_votes - sell_votes
    - Direction: BUY if net > 0, SELL if net < 0, NONE if net == 0

Position Sizing:
    - max_lots = round(340 / ATR_30)
    - target_lots = round(5 * abs(net_votes) / 30 * max_lots)
    - desired_position = target_lots if BUY else -target_lots

Exit Logic:
    - Rebalance position on every signal
    - Delta = desired_position - current_position
    - Place orders to reach desired position
"""

import pandas as pd
import numpy as np
import pickle
import xgboost as xgb
from typing import Dict, Any, Optional
from collections import Counter
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.logger import get_logger
from ib_insync import Future, ContFuture, Forex, Stock, util


class MESXGBoostEnsembleStrategy(BaseStrategy):
    """
    MES XGBoost Ensemble Strategy
    
    Fetches multi-asset data, engineers 840+ features, and uses
    30 pre-trained XGBoost models for ensemble voting.
    """

    def __init__(
        self,
        params: StrategyParams,
        broker: Broker,
        order_mgr: OrderManager,
        db: DatabaseManager,
        account: str,
    ) -> None:
        super().__init__(params, broker, order_mgr, db, account)
        
        p = params.params
        self._model_pickle_path: str = p.get("model_pickle_path", "")
        self._atr_period: int = p.get("atr_period", 30)
        self._atr_5_period: int = p.get("atr_5_period", 5)
        self._risk_per_atr: float = p.get("risk_per_atr", 340.0)
        self._vote_scaling: float = p.get("vote_scaling", 5.0)
        self._max_lots: int = p.get("max_lots", 50)
        
        self._models: Dict[tuple, Any] = {}
        self._merged_df: Optional[pd.DataFrame] = None
        
        self.log.info("Initializing MES XGBoost Ensemble Strategy")
        self.log.info(f"Model path: {self._model_pickle_path}")
        self.log.info(f"ATR period: {self._atr_period}, ATR_5 period: {self._atr_5_period}")
        self.log.info(f"Risk per ATR: ${self._risk_per_atr}, Vote scaling: {self._vote_scaling}")
        
        self._load_models()

    def _load_models(self) -> None:
        """Load pre-trained XGBoost models from pickle file."""
        self.log.info("=" * 60)
        self.log.info("LOADING XGBOOST MODELS")
        self.log.info("=" * 60)
        
        try:
            with open(self._model_pickle_path, "rb") as f:
                all_models = pickle.load(f)
            
            self.log.info(f"Loaded {len(all_models)} models from pickle")
            
            for rep, model in all_models.items():
                model_feats = model.feature_names if hasattr(model, 'feature_names') else model.feature_names_
                self.log.info(f"Model {rep}: {len(model_feats)} features")
            
            self._models = all_models
            self.log.info(f"✅ Successfully loaded {len(self._models)} XGBoost models")
            
        except FileNotFoundError:
            self.log.error(f"❌ Model file not found: {self._model_pickle_path}")
            raise
        except Exception as e:
            self.log.error(f"❌ Error loading models: {e}")
            raise

    def fetch_data(self) -> pd.DataFrame:
        """
        Fetch multi-asset data and merge into single DataFrame.
        
        Data sources:
        1. MES (E-mini S&P 500) - primary contract
        2. Gold (GC) - commodity
        3. Copper (HG) - commodity
        4. EURUSD - forex
        5. USDJPY - forex
        6. Sector ETFs: XLV, XLK, XLP, XLF, XLI
        7. Macro: 10Y/2Y Treasuries, Dollar Index, VIX
        """
        self.log.info("=" * 60)
        self.log.info("FETCHING MULTI-ASSET DATA")
        self.log.info("=" * 60)
        
        ib = self.broker.ib
        
        contracts_info = {
            'Gold': ('GC', 'COMEX'),
            'Copper': ('HG', 'COMEX'),
            'MES': ('MES', 'CME')
        }
        
        active = {}
        today = datetime.now().strftime('%Y%m%d')
        
        self.log.info("Step 1: Qualifying futures contracts...")
        
        for name, (sym, exch) in contracts_info.items():
            self.log.info(f"Processing {name} ({sym} @ {exch})...")
            
            if name == 'MES':
                cf = ContFuture(symbol=sym, exchange=exch, currency='USD')
                ib.qualifyContracts(cf)
                details = ib.reqContractDetails(cf)
                if details:
                    c = details[0].contract
                    self.log.info(f"  MES mapped to: {c.localSymbol} (expiry {c.lastTradeDateOrContractMonth})")
                active[name] = cf
                
            elif name == 'Copper':
                c = Future('HG', self.spec.last_trade_date, exchange='COMEX', currency='USD')
                ib.qualifyContracts(c)
                ib.sleep(0.5)
                try:
                    bars = ib.reqHistoricalData(
                        c, endDateTime='', durationStr='12 Y',
                        barSizeSetting='1 day', whatToShow='TRADES',
                        useRTH=False, formatDate=1
                    )
                    if bars:
                        self.log.info(f"  Copper: Retrieved {len(bars)} bars")
                    else:
                        self.log.warning(f"  Copper: No data returned")
                    active[name] = c
                except Exception as e:
                    self.log.error(f"  Copper error: {e}")
                    
            else:
                base = Future(symbol=sym, exchange=exch, currency='USD')
                details = ib.reqContractDetails(base)
                valid = [d.contract for d in details if d.contract.lastTradeDateOrContractMonth > today]
                front5 = sorted(valid, key=lambda c: c.lastTradeDateOrContractMonth)[:5]
                vols = []
                for c in front5:
                    bars = ib.reqHistoricalData(c, '', '1 D', '1 day', 'TRADES', False, 1)
                    vols.append((c, bars[-1].volume if bars else 0))
                if vols:
                    active[name] = max(vols, key=lambda x: x[1])[0]
                    self.log.info(f"  {name}: Selected contract with highest volume")
        
        self.log.info(f"✅ Qualified {len(active)} futures contracts")
        
        self.log.info("Step 2: Downloading 10-year daily OHLC for futures...")
        dfs = {}
        for name, c in active.items():
            self.log.info(f"Fetching {name} data...")
            bars = ib.reqHistoricalData(c, '', '10 Y', '1 day', 'TRADES', False, 1)
            df = util.df(bars)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            dfs[name] = df
            self.log.info(f"  {name}: {len(df)} bars from {df.index[0]} to {df.index[-1]}")
        
        self.log.info("Step 3: Building merged DataFrame...")
        MES = dfs.pop('MES')
        merged = MES[['open', 'high', 'low', 'close']].rename(columns=lambda c: f'ES_{c}')
        
        for name, df in dfs.items():
            merged[f'{name}_close'] = df['close']
        
        self.log.info(f"  Merged shape after futures: {merged.shape}")
        
        self.log.info("Step 4: Fetching FX data (EURUSD, USDJPY)...")
        for pair in ['EURUSD', 'USDJPY']:
            self.log.info(f"Fetching {pair}...")
            fx = Forex(pair)
            fx.exchange = 'IDEALPRO'
            ib.qualifyContracts(fx)
            ib.sleep(0.5)
            try:
                bars = ib.reqHistoricalData(
                    fx, endDateTime='', durationStr='1 Y',
                    barSizeSetting='1 day', whatToShow='MIDPOINT',
                    useRTH=False, formatDate=1
                )
                if bars:
                    fx_df = util.df(bars)
                    fx_df['date'] = pd.to_datetime(fx_df['date'])
                    fx_df.set_index('date', inplace=True)
                    merged[pair] = fx_df['close']
                    self.log.info(f"  {pair}: {len(fx_df)} bars")
                else:
                    self.log.warning(f"  {pair}: No data returned")
            except Exception as e:
                self.log.error(f"  {pair} error: {e}")
        
        self.log.info("Step 5: Fetching sector ETFs...")
        for sym in ['XLV', 'XLK', 'XLP', 'XLF', 'XLI']:
            self.log.info(f"Fetching {sym}...")
            stk = Stock(sym, 'ARCA', 'USD')
            ib.qualifyContracts(stk)
            bars = ib.reqHistoricalData(stk, '', '1 Y', '1 day', 'TRADES', True, 1)
            s = util.df(bars).assign(
                date=lambda d: pd.to_datetime(d['date'])
            ).set_index('date')['close']
            merged[f'{sym}_close'] = s
            self.log.info(f"  {sym}: {len(s)} bars")
        
        self.log.info(f"  Merged shape after ETFs: {merged.shape}")
        
        self.log.info("Step 6: Fetching macro indicators (Treasuries, DXY, VIX)...")
        merged = self._fetch_macro_data(merged)
        
        self.log.info(f"✅ Final merged data shape: {merged.shape}")
        self.log.info(f"  Date range: {merged.index[0]} to {merged.index[-1]}")
        self.log.info(f"  Columns: {list(merged.columns)}")
        
        merged = merged.dropna()
        self.log.info(f"  After dropna: {merged.shape}")
        
        self._merged_df = merged
        return merged

    def _fetch_macro_data(self, sp500: pd.DataFrame) -> pd.DataFrame:
        """Fetch macro indicators using investiny library."""
        self.log.info("Fetching macro data from Investing.com...")
        
        try:
            from investiny import historical_data
            
            ID_US_2Y = 23706
            ID_US_10Y = 23705
            ID_DXY = 8827
            ID_VIX = 44336
            
            def _nonempty(df):
                return isinstance(df, pd.DataFrame) and not df.empty
            
            def call_with_timeout_thread(fn, timeout=10, **kwargs):
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(fn, **kwargs)
                    try:
                        return fut.result(timeout=timeout)
                    except FutureTimeoutError:
                        return None
                    except Exception:
                        return None
            
            def fetch_with_retries(fn, retries=2, backoff=2, timeout=10, **kwargs):
                for i in range(retries):
                    df = call_with_timeout_thread(fn, timeout=timeout, **kwargs)
                    if _nonempty(df):
                        return df
                    if i < retries - 1:
                        time.sleep(backoff ** i)
                return None
            
            def _to_daily_index(df):
                if not _nonempty(df):
                    return df
                out = df.copy()
                out.index = pd.to_datetime(out.index, errors="coerce").normalize()
                out = out[~out.index.isna()]
                out = out[~out.index.duplicated(keep="last")]
                return out.sort_index()
            
            def align_to_sp500_index_NO_NANS(sp500, df):
                if not _nonempty(df):
                    return df
                orig_idx = sp500.index
                sp_days = pd.to_datetime(orig_idx, errors="coerce").normalize()
                tmp = _to_daily_index(df)
                aligned = tmp.reindex(sp_days)
                aligned = aligned.ffill().bfill()
                aligned.index = orig_idx
                return aligned
            
            def pull_series(investing_id):
                from_date = "01/01/1995"
                to_date = pd.Timestamp.today().strftime("%m/%d/%Y")
                raw = historical_data(investing_id=investing_id, from_date=from_date, to_date=to_date)
                df = pd.DataFrame(raw)
                if df.empty or "date" not in df.columns or "close" not in df.columns:
                    return None
                df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
                df = df.dropna(subset=["date"]).set_index("date").sort_index()
                return df[["close"]].rename(columns={"close": "Close"})
            
            expected = {"bonds", "dxy", "vix"}
            max_runs = 3
            interval = 10
            
            candidate = sp500.copy()
            got = set()
            
            for attempt in range(1, max_runs + 1):
                self.log.info(f"  Macro fetch attempt {attempt}/{max_runs}...")
                
                b2 = fetch_with_retries(pull_series, retries=2, timeout=20, investing_id=ID_US_2Y)
                b10 = fetch_with_retries(pull_series, retries=2, timeout=20, investing_id=ID_US_10Y)
                
                if _nonempty(b2) and _nonempty(b10):
                    b2, b10 = _to_daily_index(b2), _to_daily_index(b10)
                    idx = b10.index.union(b2.index)
                    dfb = pd.DataFrame(index=idx)
                    dfb["10 Year Gov Bond"] = b10["Close"].reindex(idx)
                    dfb["2-10 Y Bon"] = b2["Close"].reindex(idx) - b10["Close"].reindex(idx)
                    
                    dfb = align_to_sp500_index_NO_NANS(candidate, dfb)
                    dfb = dfb.loc[:, ~dfb.columns.isin(candidate.columns)]
                    if dfb.shape[1] > 0:
                        candidate = candidate.join(dfb, how="left")
                        got.add("bonds")
                        self.log.info(f"    ✅ Bonds data fetched")
                
                dxy = fetch_with_retries(pull_series, retries=2, timeout=20, investing_id=ID_DXY)
                if _nonempty(dxy):
                    dxy = _to_daily_index(dxy)
                    dxy_df = pd.DataFrame({"Dollar index": dxy["Close"]})
                    dxy_df = align_to_sp500_index_NO_NANS(candidate, dxy_df)
                    dxy_df = dxy_df.loc[:, ~dxy_df.columns.isin(candidate.columns)]
                    if dxy_df.shape[1] > 0:
                        candidate = candidate.join(dxy_df, how="left")
                        got.add("dxy")
                        self.log.info(f"    ✅ Dollar Index fetched")
                
                vix = fetch_with_retries(pull_series, retries=2, timeout=20, investing_id=ID_VIX)
                if _nonempty(vix):
                    vix = _to_daily_index(vix)
                    vix_df = pd.DataFrame({"Vix": vix["Close"]})
                    vix_df = align_to_sp500_index_NO_NANS(candidate, vix_df)
                    vix_df = vix_df.loc[:, ~vix_df.columns.isin(candidate.columns)]
                    if vix_df.shape[1] > 0:
                        candidate = candidate.join(vix_df, how="left")
                        got.add("vix")
                        self.log.info(f"    ✅ VIX data fetched")
                
                if got.issuperset(expected):
                    new_cols = []
                    if "bonds" in got:
                        new_cols += ["10 Year Gov Bond", "2-10 Y Bon"]
                    if "dxy" in got:
                        new_cols += ["Dollar index"]
                    if "vix" in got:
                        new_cols += ["Vix"]
                    
                    new_cols = [c for c in new_cols if c in candidate.columns]
                    nan_counts = candidate[new_cols].isna().sum()
                    
                    if nan_counts.sum() == 0:
                        self.log.info(f"  ✅ All macro data fetched successfully (no NaNs)")
                        return candidate
                
                if attempt < max_runs:
                    time.sleep(interval)
            
            if not got.issuperset(expected):
                self.log.warning(f"  ⚠️ Failed to fetch all macro data. Got: {got}, Expected: {expected}")
            
            return candidate
            
        except ImportError:
            self.log.error("  ❌ investiny library not installed. Skipping macro data.")
            return sp500
        except Exception as e:
            self.log.error(f"  ❌ Error fetching macro data: {e}")
            return sp500

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute 840+ features from raw data.
        
        Features include:
        1. ATR (30 and 5 period)
        2. Lagged returns (0-3, 5, 10) with RSI and MACD
        3. Correlated asset indicators (RSI, MACD, pct_change)
        4. Calendar features (day of week, week of month)
        5. Pairwise price spreads (daily/weekly/monthly OHLC)
        """
        self.log.info("=" * 60)
        self.log.info("COMPUTING INDICATORS")
        self.log.info("=" * 60)
        
        df = df.copy()
        df.columns = ['Date' if c == 'date' else c for c in df.columns]
        
        if 'Date' not in df.columns:
            df['Date'] = df.index
        
        df = df.rename(columns={
            'ES_open': 'Open',
            'ES_high': 'High',
            'ES_low': 'Low',
            'ES_close': 'Close',
            'Gold_close': 'Gold',
            'Copper_close': 'Copper',
            'EURUSD': 'EUR',
            'USDJPY': 'YEN',
            'XLV_close': 'Health',
            'XLK_close': 'Tech',
            'XLP_close': 'Cons Stap',
            'XLF_close': 'Financials',
            'XLI_close': 'Industrials',
        })
        
        self.log.info("Step 1: Computing ATR features...")
        df = self._add_atr(df)
        self.log.info(f"  After ATR: {df.shape}")
        
        self.log.info("Step 2: Computing lagged return features...")
        df = self._add_lagged_returns(df)
        self.log.info(f"  After lagged returns: {df.shape}")
        
        self.log.info("Step 3: Computing correlated asset features...")
        df = self._add_correlated_features(df)
        self.log.info(f"  After correlated features: {df.shape}")
        
        self.log.info("Step 4: Computing pairwise spread features...")
        df = self._add_pairwise_spreads(df)
        self.log.info(f"  After pairwise spreads: {df.shape}")
        
        df = df.dropna()
        self.log.info(f"✅ Final feature set: {df.shape}")
        
        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ATR features."""
        df['prev_close'] = df['Close'].shift(1)
        df['TR'] = np.maximum.reduce([
            df['High'] - df['Low'],
            (df['High'] - df['prev_close']).abs(),
            (df['Low'] - df['prev_close']).abs()
        ])
        df['ATR_30'] = df['TR'].rolling(self._atr_period).mean()
        df['ATR_5'] = df['TR'].rolling(self._atr_5_period).mean()
        df = df.drop(['prev_close', 'TR'], axis=1)
        return df

    def _add_lagged_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add lagged return features with RSI and MACD."""
        for lag in range(0, 4):
            df[f'lagged_return{lag}'] = (df['Close'].shift(lag) - df['Close'].shift(lag+1)) / df['Close'].shift(lag)
            df[f'lagged_return{lag}_rsi'] = self._compute_rsi(df['Close'], window=5).shift(lag)
            df[f'lagged_return{lag}_macd'] = self._compute_macd_diff(df['Close'].shift(lag))
        
        df['5lagged_return'] = (df['Close'] - df['Close'].shift(5)) / df['Close'].shift(5)
        df['10lagged_return'] = (df['Close'] - df['Close'].shift(10)) / df['Close'].shift(10)
        df['5lagged_return_rsi'] = self._compute_rsi(df['Close'], window=5).shift(5)
        df['10lagged_return_rsi'] = self._compute_rsi(df['Close'], window=5).shift(10)
        df['5lagged_return_macd'] = self._compute_macd_diff(df['Close']).shift(5)
        df['10lagged_return_macd'] = self._compute_macd_diff(df['Close']).shift(10)
        
        df['ATR30_feature'] = df['ATR_30'] / df['Close']
        df['ATR30_feature_rsi'] = self._compute_rsi(df['ATR30_feature'], window=5)
        df['ATR30_feature_macd'] = self._compute_macd_diff(df['ATR30_feature'])
        
        return df

    def _add_correlated_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add correlated asset features."""
        change_cols = [
            'EUR', 'YEN', 'Gold', 'Copper', 'Tech', 'Health',
            'Cons Stap', 'Financials', 'Industrials', 'USDJPY'
        ]
        
        change_cols = [c for c in change_cols if c in df.columns and df[c].notna().sum() > 0]
        
        for col in change_cols:
            df[f'{col}_rsi'] = self._compute_rsi(df[col], window=5)
            df[f'{col}_macd'] = self._compute_macd_diff(df[col])
            df[col] = df[col].pct_change()
        
        df['dow_sin'] = np.sin(2 * np.pi * df.index.dayofweek / 7)
        df['dow_cos'] = np.cos(2 * np.pi * df.index.dayofweek / 7)
        wom = (df.index.day - 1) // 7 + 1
        df['wom_sin'] = np.sin(2 * np.pi * (wom - 1) / 5)
        df['wom_cos'] = np.cos(2 * np.pi * (wom - 1) / 5)
        
        if '10 Year Gov Bond' in df.columns:
            df['10 Year Gov Bond_rsi'] = self._compute_rsi(df['10 Year Gov Bond'], window=5)
            df['10 Year Gov Bond_macd'] = self._compute_macd_diff(df['10 Year Gov Bond'])
        
        if '2-10 Y Bon' in df.columns:
            df['2-10 Y Bon'] = df['2-10 Y Bon'].diff()
            df['2-10 Y Bon_rsi'] = self._compute_rsi(df['2-10 Y Bon'], window=5)
            df['2-10 Y Bon_macd'] = self._compute_macd_diff(df['2-10 Y Bon'])
        
        if 'Dollar index' in df.columns:
            df['Dollar index_rsi'] = self._compute_rsi(df['Dollar index'], window=5)
            df['Dollar index_macd'] = self._compute_macd_diff(df['Dollar index'])
        
        return df

    def _add_pairwise_spreads(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add pairwise spread features."""
        import itertools
        
        df2 = df.copy()
        if 'Date' in df2.columns:
            df2 = df2.drop(columns='Date')
        df2.index = pd.to_datetime(df2.index)
        df2.index.name = 'Date'
        
        for n in range(4):
            for C in ['Open', 'High', 'Low', 'Close']:
                df2[f'{C}_d{n}'] = df2[C].shift(n)
        
        df2['week'] = df2.index.to_period('W-FRI')
        df2['Open_w0'] = df2.groupby('week')['Open'].transform('first')
        df2['High_w0'] = df2.groupby('week')['High'].transform('cummax')
        df2['Low_w0'] = df2.groupby('week')['Low'].transform('cummin')
        df2['Close_w0'] = df2['Close']
        
        weekly_ohlc = df2.groupby('week').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'})
        for n in range(1, 4):
            shifted = weekly_ohlc.shift(n)
            df2[f'Open_w{n}'] = df2['week'].map(shifted['Open'])
            df2[f'High_w{n}'] = df2['week'].map(shifted['High'])
            df2[f'Low_w{n}'] = df2['week'].map(shifted['Low'])
            df2[f'Close_w{n}'] = df2['week'].map(shifted['Close'])
        
        df2['month'] = df2.index.to_period('M')
        df2['Open_m0'] = df2.groupby('month')['Open'].transform('first')
        df2['High_m0'] = df2.groupby('month')['High'].transform('cummax')
        df2['Low_m0'] = df2.groupby('month')['Low'].transform('cummin')
        df2['Close_m0'] = df2['Close']
        
        monthly_ohlc = df2.groupby('month').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'})
        for n in range(1, 2):
            shifted_m = monthly_ohlc.shift(n)
            df2[f'Open_m{n}'] = df2['month'].map(shifted_m['Open'])
            df2[f'High_m{n}'] = df2['month'].map(shifted_m['High'])
            df2[f'Low_m{n}'] = df2['month'].map(shifted_m['Low'])
            df2[f'Close_m{n}'] = df2['month'].map(shifted_m['Close'])
        
        scaffolding = []
        scaffolding += [f'{C}_d{n}' for n in range(4) for C in ['Open', 'High', 'Low', 'Close']]
        scaffolding += [f'{C}_w{n}' for n in range(4) for C in ['Open', 'High', 'Low', 'Close']]
        scaffolding += [f'{C}_m{n}' for n in range(2) for C in ['Open', 'High', 'Low', 'Close']]
        
        for A, B in itertools.combinations(scaffolding, 2):
            df2[f'{A}_minus_{B}_norm'] = (df2[A] - df2[B]) / df2['Close_d0']
        
        df2 = df2.drop(columns=scaffolding + ['week', 'month'])
        
        to_drop = [
            col for col in df2.columns
            if (('Open' in col and col != 'TradeOpen' and '_minus_' not in col))
               or ('_w0' in col and '_minus_' not in col)
               or ('_m0' in col and '_minus_' not in col)
        ]
        df2 = df2.drop(columns=to_drop)
        
        return df2

    def _compute_rsi(self, series: pd.Series, window: int = 5) -> pd.Series:
        """Compute RSI indicator."""
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window).mean()
        avg_loss = loss.rolling(window).mean()
        rs = avg_gain / avg_loss
        rsi = 50 - 100 / (1 + rs)
        return rsi

    def _compute_macd_diff(self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
        """Compute MACD difference."""
        fast_ema = series.ewm(span=fast, adjust=False).mean()
        slow_ema = series.ewm(span=slow, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        sig_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line - sig_line

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Generate trading signal using ensemble voting.
        
        Process:
        1. For each model, extract required features
        2. Predict class (1=SELL, 2=HOLD, 3=BUY)
        3. Count votes
        4. Calculate net votes (buy - sell)
        5. Determine direction and position size
        """
        self.log.info("=" * 60)
        self.log.info("GENERATING ENSEMBLE SIGNAL")
        self.log.info("=" * 60)
        
        if len(df) < 50:
            return Signal(
                signal_type="NONE",
                reason="Insufficient data for prediction",
                close_price=df.iloc[-1]['Close'],
                indicators={},
                meta={"date": str(df.index[-1])},
            )
        
        last = df.iloc[-1]
        close = float(last['Close'])
        atr_30 = float(last['ATR_30'])
        
        self.log.info(f"Latest data: Date={df.index[-1]}, Close={close:.2f}, ATR_30={atr_30:.2f}")
        
        signals = Counter()
        skipped = 0
        
        self.log.info(f"Running predictions on {len(self._models)} models...")
        
        for rep, model in self._models.items():
            feat_names = model.feature_names if hasattr(model, 'feature_names') else model.feature_names_
            
            missing = [f for f in feat_names if f not in df.columns]
            if missing:
                self.log.debug(f"  Model {rep}: Missing features {missing[:5]}...")
                skipped += 1
                continue
            
            X = df[feat_names].iloc[[-1]]
            if X.isna().any(axis=1).iloc[0]:
                self.log.debug(f"  Model {rep}: NaN values in features")
                skipped += 1
                continue
            
            dm = xgb.DMatrix(X, feature_names=feat_names)
            pred = int(np.argmax(model.predict(dm), axis=1)[0])
            signals[pred] += 1
        
        buy_votes = signals.get(3, 0)
        sell_votes = signals.get(1, 0)
        hold_votes = signals.get(2, 0)
        net = buy_votes - sell_votes
        
        self.log.info(f"Voting results:")
        self.log.info(f"  Models used: {sum(signals.values())}")
        self.log.info(f"  Skipped: {skipped}")
        self.log.info(f"  BUY votes: {buy_votes}")
        self.log.info(f"  SELL votes: {sell_votes}")
        self.log.info(f"  HOLD votes: {hold_votes}")
        self.log.info(f"  Net votes: {net}")
        
        direction = 'BUY' if net > 0 else ('SELL' if net < 0 else 'NONE')
        
        max_lots = round(self._risk_per_atr / atr_30)
        target = round(self._vote_scaling * abs(net) / 30 * max_lots)
        target = min(target, self._max_lots)
        
        desired_pos = target if direction == 'BUY' else (-target if direction == 'SELL' else 0)
        delta = desired_pos - current_pos
        
        self.log.info(f"Position sizing:")
        self.log.info(f"  Max lots (based on ATR): {max_lots}")
        self.log.info(f"  Target lots: {target}")
        self.log.info(f"  Direction: {direction}")
        self.log.info(f"  Desired position: {desired_pos}")
        self.log.info(f"  Current position: {current_pos}")
        self.log.info(f"  Delta: {delta:+}")
        
        indicators = {
            "buy_votes": buy_votes,
            "sell_votes": sell_votes,
            "hold_votes": hold_votes,
            "net_votes": net,
            "models_used": sum(signals.values()),
            "models_skipped": skipped,
            "atr_30": round(atr_30, 2),
            "max_lots": max_lots,
            "target_lots": target,
            "desired_position": desired_pos,
            "current_position": current_pos,
            "delta": delta,
        }
        
        meta = {
            "date": str(df.index[-1]),
            "direction": direction,
        }
        
        if delta == 0:
            self.log.info("✅ No position change required")
            return Signal(
                signal_type="NONE",
                reason=f"Position already at target ({current_pos} lots)",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        if delta > 0:
            self.log.info(f"✅ ENTRY_LONG signal: Buy {delta} lots")
            return Signal(
                signal_type="ENTRY_LONG",
                reason=f"Ensemble BUY: {buy_votes} votes, net={net}, target={desired_pos}",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        else:
            self.log.info(f"✅ ENTRY_SHORT signal: Sell {abs(delta)} lots")
            return Signal(
                signal_type="ENTRY_SHORT",
                reason=f"Ensemble SELL: {sell_votes} votes, net={net}, target={desired_pos}",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )

    def get_position_size(self, signal: Signal) -> int:
        """Return position size from signal indicators."""
        return abs(signal.indicators.get("delta", 1))

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """Execute trading signal with proper position management."""
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        self.log.info("=" * 60)
        self.log.info("EXECUTING SIGNAL")
        self.log.info("=" * 60)
        
        price, source = self.broker.get_indicative_price(contract, signal.close_price)
        self.log.info(f"Indicative price: {price:.2f} ({source})")
        
        delta = signal.indicators.get("delta", 0)
        
        if delta > 0:
            qty = abs(delta)
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
            self.log.info(f"Placing BUY order: {qty} lots @ {limit_px:.2f}")
            
            from ib_insync import LimitOrder
            order = LimitOrder("BUY", qty, limit_px)
            order.account = self.account
            order.tif = "GTC"
            order.outsideRth = True
            
            trade = self.order_mgr._ib.placeOrder(contract, order)
            self.order_mgr._ib.waitOnUpdate()
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="BUY",
                order_type="LIMIT",
                quantity=qty,
                limit_price=limit_px,
            )
            
            self.log.info(f"✅ BUY order placed: {qty} lots @ {limit_px:.2f}")
            
        elif delta < 0:
            qty = abs(delta)
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
            self.log.info(f"Placing SELL order: {qty} lots @ {limit_px:.2f}")
            
            from ib_insync import LimitOrder
            order = LimitOrder("SELL", qty, limit_px)
            order.account = self.account
            order.tif = "GTC"
            order.outsideRth = True
            
            trade = self.order_mgr._ib.placeOrder(contract, order)
            self.order_mgr._ib.waitOnUpdate()
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="SELL",
                order_type="LIMIT",
                quantity=qty,
                limit_price=limit_px,
            )
            
            self.log.info(f"✅ SELL order placed: {qty} lots @ {limit_px:.2f}")
