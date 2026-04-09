"""
dashboard/app.py
────────────────
Streamlit dashboard for real-time monitoring of the trading framework.

Run:
    cd trading_framework
    streamlit run dashboard/app.py

Reads from the SQLite database independently of the trading loop.
Auto-refreshes every N seconds for a live-monitoring feel.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Resolve project root so imports work when Streamlit runs from /dashboard
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DB_PATH, DashboardConfig  # noqa: E402

CFG = DashboardConfig()

# ─────────────────────────────────────────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
#  AUTO-REFRESH (using streamlit-autorefresh if installed, else manual button)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=CFG.refresh_interval_ms, key="auto_refresh")
except ImportError:
    pass  # fallback: user clicks "Rerun" or presses R


# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def _get_connection() -> sqlite3.Connection:
    """Shared read-only connection, cached across reruns."""
    if not DB_PATH.exists():
        st.error(f"Database not found at `{DB_PATH}`.  Run the trading framework first.")
        st.stop()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Execute a read query and return a DataFrame."""
    conn = _get_connection()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception as exc:
        st.warning(f"Query error: {exc}")
        return pd.DataFrame()


def get_strategies() -> List[str]:
    df = _query("SELECT DISTINCT name FROM strategies ORDER BY name")
    return df["name"].tolist() if not df.empty else []


def get_signals(strategy: Optional[str], limit: int = 200) -> pd.DataFrame:
    if strategy and strategy != "All":
        return _query(
            "SELECT * FROM signals WHERE strategy_name = ? ORDER BY created_at DESC LIMIT ?",
            (strategy, limit),
        )
    return _query(
        "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
    )


def get_trades(
    strategy: Optional[str],
    status: Optional[str] = None,
    limit: int = 500,
) -> pd.DataFrame:
    q = "SELECT * FROM trades WHERE 1=1"
    params: list = []
    if strategy and strategy != "All":
        q += " AND strategy_name = ?"
        params.append(strategy)
    if status:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return _query(q, tuple(params))


def get_orders(strategy: Optional[str], limit: int = 200) -> pd.DataFrame:
    if strategy and strategy != "All":
        return _query(
            "SELECT * FROM orders WHERE strategy_name = ? ORDER BY created_at DESC LIMIT ?",
            (strategy, limit),
        )
    return _query(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
    )


def get_positions(strategy: Optional[str] = None) -> pd.DataFrame:
    if strategy and strategy != "All":
        return _query(
            """SELECT p.* FROM positions p
               INNER JOIN (
                   SELECT strategy_name, MAX(snapshot_time) AS mx
                   FROM positions GROUP BY strategy_name
               ) s ON p.strategy_name = s.strategy_name AND p.snapshot_time = s.mx
               WHERE p.strategy_name = ?""",
            (strategy,),
        )
    return _query(
        """SELECT p.* FROM positions p
           INNER JOIN (
               SELECT strategy_name, MAX(snapshot_time) AS mx
               FROM positions GROUP BY strategy_name
           ) s ON p.strategy_name = s.strategy_name AND p.snapshot_time = s.mx"""
    )


def get_equity_curve(strategy: Optional[str] = None) -> pd.DataFrame:
    q = """
        SELECT id, strategy_name, exit_time, pnl,
               SUM(pnl) OVER (ORDER BY exit_time) AS cum_pnl
        FROM trades
        WHERE status = 'CLOSED' AND pnl IS NOT NULL
    """
    params: list = []
    if strategy and strategy != "All":
        q += " AND strategy_name = ?"
        params.append(strategy)
    q += " ORDER BY exit_time"
    return _query(q, tuple(params))


# ─────────────────────────────────────────────────────────────────────────────
#  CHART BUILDERS
# ─────────────────────────────────────────────────────────────────────────────
def _equity_chart(df: pd.DataFrame) -> go.Figure:
    fig = px.line(
        df, x="exit_time", y="cum_pnl",
        title="Equity Curve",
        labels={"exit_time": "Date", "cum_pnl": "Cumulative PnL ($)"},
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=380,
    )
    return fig


def _drawdown_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()
    cum = df["cum_pnl"]
    running_max = cum.cummax()
    dd = cum - running_max
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["exit_time"], y=dd,
        fill="tozeroy",
        line=dict(color="#ef4444"),
        name="Drawdown",
    ))
    fig.update_layout(
        title="Drawdown Curve",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="Drawdown ($)",
        height=320,
    )
    return fig


def _pnl_distribution(df: pd.DataFrame) -> go.Figure:
    if df.empty or "pnl" not in df.columns:
        return go.Figure()
    fig = px.histogram(
        df.dropna(subset=["pnl"]),
        x="pnl", nbins=30,
        title="PnL Distribution",
        color_discrete_sequence=["#3b82f6"],
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=320,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Filters")

    strategies = get_strategies()
    strategy_options = ["All"] + strategies
    selected_strategy = st.selectbox("Strategy", strategy_options, index=0)

    st.markdown("---")
    st.caption(f"Database: `{DB_PATH.name}`")
    st.caption(f"Auto-refresh: {CFG.refresh_interval_ms / 1000:.0f}s")
    if st.button("🔄 Refresh Now"):
        st.cache_resource.clear()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("# 📈 Trading Framework Dashboard")
st.caption(f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ─────────────────────────────────────────────────────────────────────────────
#  TAB LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
tab_overview, tab_trades, tab_pnl, tab_orders, tab_signals = st.tabs(
    ["📋 Overview", "📊 Trades", "💰 PnL", "📦 Orders", "🔔 Signals"]
)

# ── TAB: Overview ────────────────────────────────────────────────────────────
with tab_overview:
    col1, col2, col3, col4 = st.columns(4)

    open_trades = get_trades(selected_strategy, status="OPEN")
    closed_trades = get_trades(selected_strategy, status="CLOSED")
    signals_df = get_signals(selected_strategy, limit=1)
    positions_df = get_positions(selected_strategy)

    realized = closed_trades["pnl"].sum() if not closed_trades.empty else 0
    total_trades = len(closed_trades)

    col1.metric("Open Trades", len(open_trades))
    col2.metric("Closed Trades", total_trades)
    col3.metric("Realized PnL", f"${realized:,.2f}")
    col4.metric(
        "Latest Signal",
        signals_df.iloc[0]["signal_type"] if not signals_df.empty else "—",
    )

    st.markdown("### Current Positions")
    if positions_df.empty:
        st.info("No position snapshots yet.")
    else:
        st.dataframe(
            positions_df[["strategy_name", "symbol", "quantity", "avg_cost",
                          "market_price", "unrealized_pnl", "snapshot_time"]],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("### Active Trades")
    if open_trades.empty:
        st.info("No open trades.")
    else:
        st.dataframe(
            open_trades[["strategy_name", "symbol", "direction", "quantity",
                         "entry_price", "tp_price", "sl_price", "entry_time"]],
            use_container_width=True,
            hide_index=True,
        )

# ── TAB: Trades ──────────────────────────────────────────────────────────────
with tab_trades:
    st.markdown("### Trade History")
    all_trades = get_trades(selected_strategy)
    if all_trades.empty:
        st.info("No trades recorded yet.")
    else:
        # Add duration column
        df_t = all_trades.copy()
        for col in ["entry_time", "exit_time"]:
            if col in df_t.columns:
                df_t[col] = pd.to_datetime(df_t[col], errors="coerce")
        if "entry_time" in df_t.columns and "exit_time" in df_t.columns:
            df_t["duration"] = (df_t["exit_time"] - df_t["entry_time"]).astype(str)

        display_cols = [
            "strategy_name", "symbol", "direction", "quantity",
            "entry_price", "exit_price", "pnl", "tp_price", "sl_price",
            "status", "entry_time", "exit_time",
        ]
        display_cols = [c for c in display_cols if c in df_t.columns]
        st.dataframe(df_t[display_cols], use_container_width=True, hide_index=True)

# ── TAB: PnL ────────────────────────────────────────────────────────────────
with tab_pnl:
    equity = get_equity_curve(selected_strategy)
    closed = get_trades(selected_strategy, status="CLOSED")

    c1, c2, c3 = st.columns(3)
    total_pnl = closed["pnl"].sum() if not closed.empty else 0
    win_count = (closed["pnl"] > 0).sum() if not closed.empty else 0
    loss_count = (closed["pnl"] <= 0).sum() if not closed.empty else 0
    win_rate = win_count / max(len(closed), 1) * 100

    c1.metric("Total Realized PnL", f"${total_pnl:,.2f}")
    c2.metric("Win Rate", f"{win_rate:.1f}%")
    c3.metric("W / L", f"{win_count} / {loss_count}")

    if not equity.empty:
        st.plotly_chart(_equity_chart(equity), use_container_width=True)
        st.plotly_chart(_drawdown_chart(equity), use_container_width=True)
    else:
        st.info("No closed trades to chart yet.")

    st.markdown("### PnL Distribution")
    if not closed.empty:
        st.plotly_chart(_pnl_distribution(closed), use_container_width=True)

# ── TAB: Orders ──────────────────────────────────────────────────────────────
with tab_orders:
    st.markdown("### Orders Monitor")
    orders_df = get_orders(selected_strategy)
    if orders_df.empty:
        st.info("No orders recorded yet.")
    else:
        # Status breakdown
        status_counts = orders_df["status"].value_counts()
        cols = st.columns(len(status_counts))
        for i, (stat, cnt) in enumerate(status_counts.items()):
            cols[i].metric(stat, cnt)

        st.dataframe(
            orders_df[["strategy_name", "symbol", "action", "order_type",
                        "quantity", "limit_price", "stop_price", "fill_price",
                        "status", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )

# ── TAB: Signals ─────────────────────────────────────────────────────────────
with tab_signals:
    st.markdown("### Signal Feed")
    st.caption("Refreshes automatically — most recent signals first.")
    signals = get_signals(selected_strategy, limit=CFG.max_signal_rows)
    if signals.empty:
        st.info("No signals recorded yet.")
    else:
        df_s = signals.copy()
        # Parse indicator JSON for display
        if "indicator_json" in df_s.columns:
            df_s["indicators"] = df_s["indicator_json"].apply(
                lambda x: json.loads(x) if x else {}
            )
        display_cols = ["strategy_name", "signal_date", "signal_type",
                        "close_price", "indicator_json", "created_at"]
        display_cols = [c for c in display_cols if c in df_s.columns]
        st.dataframe(df_s[display_cols], use_container_width=True, hide_index=True)
