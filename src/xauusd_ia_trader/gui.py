from __future__ import annotations

import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yaml

from .config import load_config
from .notifier import CallbackSink, NotificationEvent
from .models import TradeIdea
from .trader import XAUUSDAutonomousTrader


def _now_text() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except Exception:
        return default


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


class ScrollableFrame(ttk.Frame):
    def __init__(self, master: tk.Widget, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg="#0f172a")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Card.TFrame")

        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.window_id, width=event.width),
        )

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")


class XAUUSDControlPanel:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self.root = tk.Tk()
        self.root.title("XAUUSD IA Trader")
        self.root.geometry("1520x980")
        self.root.minsize(1320, 860)
        self.root.configure(bg="#0b1220")

        self._lock = threading.Lock()
        self._auto_running = False
        self._auto_thread: threading.Thread | None = None
        self._event_queue: queue.Queue[NotificationEvent] = queue.Queue()
        self._status_queue: queue.Queue[str] = queue.Queue()
        self._last_manual_result: dict[str, Any] | None = None

        self._build_style()
        self._build_vars()
        self.trader = self._build_trader()
        self._build_layout()
        self._bind_shortcuts()
        self._refresh_all()
        self.root.after(250, self._poll_events)
        self.root.after(1000, self._tick)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background="#0b1220")
        style.configure("Panel.TFrame", background="#111827")
        style.configure("Card.TFrame", background="#111827", relief="flat")
        style.configure("Dark.TLabelframe", background="#111827", foreground="#e5e7eb")
        style.configure("Dark.TLabelframe.Label", background="#111827", foreground="#93c5fd", font=("Segoe UI Semibold", 10))
        style.configure("Dark.TLabel", background="#111827", foreground="#e5e7eb")
        style.configure("Title.TLabel", background="#0b1220", foreground="#f8fafc", font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background="#0b1220", foreground="#94a3b8", font=("Segoe UI", 10))
        style.configure("MetricTitle.TLabel", background="#111827", foreground="#94a3b8", font=("Segoe UI", 9))
        style.configure("MetricValue.TLabel", background="#111827", foreground="#f8fafc", font=("Segoe UI Semibold", 18))
        style.configure("Section.TLabel", background="#0b1220", foreground="#cbd5e1", font=("Segoe UI Semibold", 12))
        style.configure("Accent.TButton", padding=(12, 8), background="#2563eb", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Danger.TButton", padding=(12, 8), background="#b91c1c", foreground="white")
        style.map("Danger.TButton", background=[("active", "#991b1b")])
        style.configure("Success.TButton", padding=(12, 8), background="#15803d", foreground="white")
        style.map("Success.TButton", background=[("active", "#166534")])
        style.configure("Info.TButton", padding=(12, 8), background="#0f766e", foreground="white")
        style.map("Info.TButton", background=[("active", "#115e59")])
        style.configure("Dark.TEntry", fieldbackground="#0f172a", background="#0f172a", foreground="#e5e7eb")
        style.configure("Dark.TCombobox", fieldbackground="#0f172a", background="#0f172a", foreground="#e5e7eb")
        style.configure("Dark.Treeview", background="#0f172a", fieldbackground="#0f172a", foreground="#e5e7eb", rowheight=26)
        style.map("Dark.Treeview", background=[("selected", "#1d4ed8")])

    def _build_vars(self) -> None:
        app = self.config.get("app", {})
        broker = self.config.get("broker", {})
        risk = self.config.get("risk", {})
        ai = self.config.get("ai", {})

        self.symbol_var = tk.StringVar(value=str(app.get("symbol", "XAUUSD")))
        self.mode_var = tk.StringVar(value=str(app.get("mode", "live")).lower())
        self.cycle_var = tk.StringVar(value=str(app.get("cycle_seconds", 30)))
        self.position_state_var = tk.StringVar(value=str(app.get("position_state_path", "runtime/position_state.json")))

        self.terminal_path_var = tk.StringVar(value=str(broker.get("terminal_path", "")))
        self.login_var = tk.StringVar(value=str(broker.get("login", "")))
        self.password_var = tk.StringVar(value=str(broker.get("password", "")))
        self.server_var = tk.StringVar(value=str(broker.get("server", "")))
        self.deviation_var = tk.StringVar(value=str(broker.get("deviation", 20)))
        self.magic_var = tk.StringVar(value=str(broker.get("magic", 2401001)))

        self.risk_var = tk.StringVar(value=f"{float(risk.get('risk_per_trade', 0.005)) * 100:.2f}")
        self.daily_loss_var = tk.StringVar(value=f"{float(risk.get('daily_loss_limit', 0.02)) * 100:.2f}")
        self.max_consecutive_var = tk.StringVar(value=str(risk.get("max_consecutive_losses", 3)))
        self.max_trades_var = tk.StringVar(value=str(risk.get("max_trades_per_day", 5)))
        self.max_open_var = tk.StringVar(value=str(risk.get("max_open_positions", 1)))
        self.max_spread_var = tk.StringVar(value=str(risk.get("max_spread_points", 80)))
        self.session_start_var = tk.StringVar(value=str(risk.get("session_start", "07:00")))
        self.session_end_var = tk.StringVar(value=str(risk.get("session_end", "20:30")))
        self.be_var = tk.StringVar(value=str(risk.get("breakeven_trigger_r", 0.9)))
        self.partial_var = tk.StringVar(value=str(risk.get("partial_take_profit_r", 1.0)))
        self.final_tp_var = tk.StringVar(value=str(risk.get("final_take_profit_r", 2.0)))
        self.partial_ratio_var = tk.StringVar(value=str(risk.get("partial_close_ratio", 0.5)))
        self.trailing_start_var = tk.StringVar(value=str(risk.get("trailing_start_r", 1.2)))
        self.trailing_atr_var = tk.StringVar(value=str(risk.get("trailing_atr_mult", 1.2)))
        self.trailing_step_var = tk.StringVar(value=str(risk.get("trailing_step_points", 10.0)))
        self.min_rr_var = tk.StringVar(value=str(risk.get("min_rr", 1.2)))

        self.ai_enabled_var = tk.BooleanVar(value=bool(ai.get("enabled", False)))
        self.ai_model_var = tk.StringVar(value=str(ai.get("hf_model", "")))
        self.queue_file_var = tk.StringVar(value=str(self.config.get("notifications", {}).get("queue_file", "xauusd_push_queue.txt")))

        self.side_var = tk.StringVar(value="buy")
        self.manual_volume_var = tk.StringVar(value="")
        self.manual_price_var = tk.StringVar(value="")
        self.manual_sl_var = tk.StringVar(value="")
        self.manual_tp_var = tk.StringVar(value="")
        self.manual_lot_preview_var = tk.StringVar(value="Lote sugerido: -")
        self.current_price_var = tk.StringVar(value="-")
        self.spread_var = tk.StringVar(value="-")
        self.account_balance_var = tk.StringVar(value="-")
        self.account_equity_var = tk.StringVar(value="-")
        self.account_free_margin_var = tk.StringVar(value="-")
        self.account_margin_level_var = tk.StringVar(value="-")
        self.daily_pnl_var = tk.StringVar(value="-")
        self.open_pnl_var = tk.StringVar(value="-")
        self.open_positions_var = tk.StringVar(value="-")
        self.trades_today_var = tk.StringVar(value="-")
        self.session_status_var = tk.StringVar(value="-")
        self.lock_status_var = tk.StringVar(value="-")
        self.regime_var = tk.StringVar(value="-")
        self.last_result_var = tk.StringVar(value="Pronto")
        self.connection_var = tk.StringVar(value="Desconectado")
        self.status_var = tk.StringVar(value="Pronto para operar")
        self.live_mode_var = tk.StringVar(value=self.mode_var.get().title())

    def _set_vars_from_config(self) -> None:
        app = self.config.get("app", {})
        broker = self.config.get("broker", {})
        risk = self.config.get("risk", {})
        ai = self.config.get("ai", {})

        self.symbol_var.set(str(app.get("symbol", "XAUUSD")))
        self.mode_var.set(str(app.get("mode", "live")).lower())
        self.cycle_var.set(str(app.get("cycle_seconds", 30)))
        self.position_state_var.set(str(app.get("position_state_path", "runtime/position_state.json")))

        self.terminal_path_var.set(str(broker.get("terminal_path", "")))
        self.login_var.set(str(broker.get("login", "")))
        self.password_var.set(str(broker.get("password", "")))
        self.server_var.set(str(broker.get("server", "")))
        self.deviation_var.set(str(broker.get("deviation", 20)))
        self.magic_var.set(str(broker.get("magic", 2401001)))

        self.risk_var.set(f"{float(risk.get('risk_per_trade', 0.005)) * 100:.2f}")
        self.daily_loss_var.set(f"{float(risk.get('daily_loss_limit', 0.02)) * 100:.2f}")
        self.max_consecutive_var.set(str(risk.get("max_consecutive_losses", 3)))
        self.max_trades_var.set(str(risk.get("max_trades_per_day", 5)))
        self.max_open_var.set(str(risk.get("max_open_positions", 1)))
        self.max_spread_var.set(str(risk.get("max_spread_points", 80)))
        self.session_start_var.set(str(risk.get("session_start", "07:00")))
        self.session_end_var.set(str(risk.get("session_end", "20:30")))
        self.be_var.set(str(risk.get("breakeven_trigger_r", 0.9)))
        self.partial_var.set(str(risk.get("partial_take_profit_r", 1.0)))
        self.final_tp_var.set(str(risk.get("final_take_profit_r", 2.0)))
        self.partial_ratio_var.set(str(risk.get("partial_close_ratio", 0.5)))
        self.trailing_start_var.set(str(risk.get("trailing_start_r", 1.2)))
        self.trailing_atr_var.set(str(risk.get("trailing_atr_mult", 1.2)))
        self.trailing_step_var.set(str(risk.get("trailing_step_points", 10.0)))
        self.min_rr_var.set(str(risk.get("min_rr", 1.2)))

        self.ai_enabled_var.set(bool(ai.get("enabled", False)))
        self.ai_model_var.set(str(ai.get("hf_model", "")))
        self.queue_file_var.set(str(self.config.get("notifications", {}).get("queue_file", "xauusd_push_queue.txt")))
        self.live_mode_var.set("Live" if self.mode_var.get().lower() == "live" else "Paper")

    def _build_trader(self) -> XAUUSDAutonomousTrader:
        trader = XAUUSDAutonomousTrader(self.config)
        trader.notifier.sinks.append(CallbackSink(self._handle_notification))
        return trader

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="XAUUSD IA Trader", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Painel operacional para MT5 com controle manual, automação, risco, posições e performance.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        toolbar = ttk.Frame(outer, style="App.TFrame")
        toolbar.pack(fill="x", pady=(0, 12))
        for label, command, style in [
            ("Aplicar", self._apply_settings, "Accent.TButton"),
            ("Iniciar Auto", self._start_auto, "Success.TButton"),
            ("Parar Auto", self._stop_auto, "Danger.TButton"),
            ("Atualizar", self._refresh_now, "Info.TButton"),
            ("Fechar Todas", self._close_all_positions, "Danger.TButton"),
        ]:
            ttk.Button(toolbar, text=label, command=command, style=style).pack(side="left", padx=(0, 10))

        self.status_badge = ttk.Label(toolbar, textvariable=self.status_var, style="Section.TLabel")
        self.status_badge.pack(side="right")

        metrics = ttk.Frame(outer, style="App.TFrame")
        metrics.pack(fill="x", pady=(0, 14))
        self.metric_cards = {}
        for index, (key, title) in enumerate([
            ("balance", "Saldo"),
            ("equity", "Capital líquido"),
            ("free_margin", "Margem livre"),
            ("daily_pnl", "PnL do dia"),
            ("open_pnl", "PnL aberto"),
            ("open_positions", "Posições"),
        ]):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=14)
            card.grid(row=0, column=index, padx=6, sticky="nsew")
            metrics.columnconfigure(index, weight=1)
            ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            self.metric_cards[key] = var
            ttk.Label(card, textvariable=var, style="MetricValue.TLabel").pack(anchor="w", pady=(6, 0))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)

        self.dashboard_tab = ttk.Frame(self.notebook, style="App.TFrame")
        self.manual_tab = ttk.Frame(self.notebook, style="App.TFrame")
        self.positions_tab = ttk.Frame(self.notebook, style="App.TFrame")
        self.settings_tab = ttk.Frame(self.notebook, style="App.TFrame")
        self.logs_tab = ttk.Frame(self.notebook, style="App.TFrame")

        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.add(self.manual_tab, text="Manual")
        self.notebook.add(self.positions_tab, text="Posições")
        self.notebook.add(self.settings_tab, text="Config")
        self.notebook.add(self.logs_tab, text="Logs")

        self._build_dashboard_tab()
        self._build_manual_tab()
        self._build_positions_tab()
        self._build_settings_tab()
        self._build_logs_tab()

        self._build_status_bar(outer)

    def _build_status_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="Card.TFrame", padding=(12, 8))
        bar.pack(fill="x", pady=(10, 0))
        left = ttk.Frame(bar, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True)
        right = ttk.Frame(bar, style="Card.TFrame")
        right.pack(side="right")
        for label, var in [
            ("Conexão", self.connection_var),
            ("Modo", self.live_mode_var),
            ("Regime", self.regime_var),
            ("Sessão", self.session_status_var),
            ("Bloqueio", self.lock_status_var),
        ]:
            row = ttk.Frame(left, style="Card.TFrame")
            row.pack(side="left", padx=(0, 20))
            ttk.Label(row, text=f"{label}:", style="MetricTitle.TLabel").pack(anchor="w")
            ttk.Label(row, textvariable=var, style="Dark.TLabel").pack(anchor="w")

        ttk.Label(right, textvariable=self.last_result_var, style="Dark.TLabel").pack(anchor="e")

    def _build_dashboard_tab(self) -> None:
        top = ttk.Frame(self.dashboard_tab, style="App.TFrame", padding=12)
        top.pack(fill="both", expand=True)

        left = ttk.Frame(top, style="App.TFrame")
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(top, style="App.TFrame", width=360)
        right.pack(side="right", fill="y", padx=(12, 0))

        perf = ttk.LabelFrame(left, text="Performance", style="Dark.TLabelframe", padding=12)
        perf.pack(fill="x", pady=(0, 12))
        grid = ttk.Frame(perf, style="Card.TFrame")
        grid.pack(fill="x")
        self.performance_labels = {}
        for idx, (key, title) in enumerate([
            ("day_pnl", "Lucro do dia"),
            ("open_pnl", "PnL aberto"),
            ("trades_today", "Trades hoje"),
            ("consecutive_losses", "Perdas seguidas"),
            ("daily_limit", "Limite diário"),
            ("risk_trade", "Risco por trade"),
        ]):
            cell = ttk.Frame(grid, style="Card.TFrame", padding=10)
            cell.grid(row=idx // 3, column=idx % 3, padx=6, pady=6, sticky="nsew")
            grid.columnconfigure(idx % 3, weight=1)
            grid.rowconfigure(idx // 3, weight=1)
            ttk.Label(cell, text=title, style="MetricTitle.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            self.performance_labels[key] = var
            ttk.Label(cell, textvariable=var, style="MetricValue.TLabel").pack(anchor="w", pady=(4, 0))

        market = ttk.LabelFrame(left, text="Mercado e sessão", style="Dark.TLabelframe", padding=12)
        market.pack(fill="x")
        for label, var in [
            ("Preço atual", self.current_price_var),
            ("Spread atual", self.spread_var),
            ("Posições abertas", self.open_positions_var),
            ("Status da conta", self.connection_var),
        ]:
            row = ttk.Frame(market, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, style="MetricTitle.TLabel", width=20).pack(side="left")
            ttk.Label(row, textvariable=var, style="Dark.TLabel").pack(side="left")

        quick = ttk.LabelFrame(right, text="Ações rápidas", style="Dark.TLabelframe", padding=12)
        quick.pack(fill="both", expand=True)
        ttk.Label(quick, text="Use a aba Manual para enviar ordens com preço, SL e TP.", style="Dark.TLabel", wraplength=320, justify="left").pack(anchor="w", pady=(0, 10))
        ttk.Button(quick, text="Atualizar agora", command=self._refresh_now, style="Info.TButton").pack(fill="x", pady=4)
        ttk.Button(quick, text="Abrir compra manual", command=lambda: self._manual_trade("buy"), style="Success.TButton").pack(fill="x", pady=4)
        ttk.Button(quick, text="Abrir venda manual", command=lambda: self._manual_trade("sell"), style="Danger.TButton").pack(fill="x", pady=4)
        ttk.Button(quick, text="Fechar todas", command=self._close_all_positions, style="Danger.TButton").pack(fill="x", pady=4)

    def _build_manual_tab(self) -> None:
        outer = ttk.Frame(self.manual_tab, style="App.TFrame", padding=12)
        outer.pack(fill="both", expand=True)

        left = ttk.LabelFrame(outer, text="Ordem manual", style="Dark.TLabelframe", padding=14)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.LabelFrame(outer, text="Resumo", style="Dark.TLabelframe", padding=14)
        right.pack(side="right", fill="y", padx=(12, 0))

        fields = ttk.Frame(left, style="Card.TFrame")
        fields.pack(fill="x")
        rows = [
            ("Símbolo", self.symbol_var),
            ("Lado", self.side_var),
            ("Modo", self.mode_var),
            ("Preço atual", self.current_price_var),
            ("Lote manual", self.manual_volume_var),
            ("SL", self.manual_sl_var),
            ("TP", self.manual_tp_var),
            ("Lote sugerido", self.manual_lot_preview_var),
        ]
        for idx, (label, var) in enumerate(rows):
            row = ttk.Frame(fields, style="Card.TFrame")
            row.grid(row=idx, column=0, sticky="ew", pady=5)
            fields.columnconfigure(0, weight=1)
            ttk.Label(row, text=label, style="MetricTitle.TLabel", width=18).pack(side="left")
            if label == "Lado":
                widget = ttk.Combobox(row, textvariable=var, values=["buy", "sell"], width=18, state="readonly", style="Dark.TCombobox")
                widget.pack(side="left", fill="x", expand=True)
            elif label == "Modo":
                widget = ttk.Combobox(row, textvariable=var, values=["live", "paper"], width=18, state="readonly", style="Dark.TCombobox")
                widget.pack(side="left", fill="x", expand=True)
            elif label == "Preço atual":
                entry = ttk.Entry(row, textvariable=var, style="Dark.TEntry", state="readonly")
                entry.pack(side="left", fill="x", expand=True)
            else:
                entry = ttk.Entry(row, textvariable=var, style="Dark.TEntry")
                entry.pack(side="left", fill="x", expand=True)

        button_row = ttk.Frame(left, style="Card.TFrame")
        button_row.pack(fill="x", pady=(14, 0))
        ttk.Button(button_row, text="Abrir Compra", command=lambda: self._manual_trade("buy"), style="Success.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="Abrir Venda", command=lambda: self._manual_trade("sell"), style="Danger.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="Atualizar preço", command=self._refresh_price_only, style="Info.TButton").pack(side="left")

        ttk.Label(
            left,
            text="Se o lote manual estiver vazio ou zero, o robô calcula automaticamente pelo risco por trade.",
            style="Subtitle.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        for label, var in [
            ("Saldo", self.account_balance_var),
            ("Equity", self.account_equity_var),
            ("Margem livre", self.account_free_margin_var),
            ("Margem %", self.account_margin_level_var),
            ("PnL do dia", self.daily_pnl_var),
            ("PnL aberto", self.open_pnl_var),
            ("Trades hoje", self.trades_today_var),
            ("Risco por trade", self.risk_var),
        ]:
            row = ttk.Frame(right, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, style="MetricTitle.TLabel", width=18).pack(side="left")
            ttk.Label(row, textvariable=var, style="Dark.TLabel").pack(side="left")

    def _build_positions_tab(self) -> None:
        outer = ttk.Frame(self.positions_tab, style="App.TFrame", padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Posições abertas", style="Section.TLabel").pack(side="left")
        ttk.Button(header, text="Fechar Todas", command=self._close_all_positions, style="Danger.TButton").pack(side="right")
        ttk.Button(header, text="Atualizar", command=self._refresh_now, style="Info.TButton").pack(side="right", padx=(0, 8))

        self.positions_scroll = ScrollableFrame(outer)
        self.positions_scroll.pack(fill="both", expand=True)

    def _build_settings_tab(self) -> None:
        outer = ttk.Frame(self.settings_tab, style="App.TFrame", padding=12)
        outer.pack(fill="both", expand=True)

        columns = ttk.Frame(outer, style="App.TFrame")
        columns.pack(fill="both", expand=True)
        left = ttk.LabelFrame(columns, text="Operação", style="Dark.TLabelframe", padding=14)
        left.pack(side="left", fill="both", expand=True)
        middle = ttk.LabelFrame(columns, text="Risco e sessão", style="Dark.TLabelframe", padding=14)
        middle.pack(side="left", fill="both", expand=True, padx=12)
        right = ttk.LabelFrame(columns, text="Conexão e IA", style="Dark.TLabelframe", padding=14)
        right.pack(side="left", fill="both", expand=True)

        self._settings_form(left, [
            ("Símbolo", self.symbol_var),
            ("Modo", self.mode_var),
            ("Cycle seconds", self.cycle_var),
            ("Position state", self.position_state_var),
        ])
        self._settings_form(middle, [
            ("Risco por trade %", self.risk_var),
            ("Limite diário %", self.daily_loss_var),
            ("Máx. perdas seguidas", self.max_consecutive_var),
            ("Máx. trades/dia", self.max_trades_var),
            ("Máx. posições", self.max_open_var),
            ("Spread máximo", self.max_spread_var),
            ("Início sessão", self.session_start_var),
            ("Fim sessão", self.session_end_var),
            ("Break-even R", self.be_var),
            ("Parcial R", self.partial_var),
            ("TP final R", self.final_tp_var),
            ("Parcial %", self.partial_ratio_var),
            ("Trailing start R", self.trailing_start_var),
            ("Trailing ATR mult", self.trailing_atr_var),
            ("Trailing step pts", self.trailing_step_var),
            ("RR mínimo", self.min_rr_var),
        ])
        self._settings_form(right, [
            ("Terminal MT5", self.terminal_path_var),
            ("Login", self.login_var),
            ("Senha", self.password_var),
            ("Servidor", self.server_var),
            ("Desvio", self.deviation_var),
            ("Magic", self.magic_var),
            ("Arquivo fila", self.queue_file_var),
            ("IA habilitada", self.ai_enabled_var),
            ("Modelo HF", self.ai_model_var),
        ])

        bottom = ttk.Frame(outer, style="App.TFrame")
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="Salvar e aplicar", command=self._apply_settings, style="Accent.TButton").pack(side="left")
        ttk.Button(bottom, text="Carregar arquivo...", command=self._load_config_file_dialog, style="Info.TButton").pack(side="left", padx=(8, 0))

    def _settings_form(self, parent: ttk.LabelFrame, fields: list[tuple[str, tk.Variable]]) -> None:
        for idx, (label, var) in enumerate(fields):
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, style="MetricTitle.TLabel", width=20).pack(side="left")
            if isinstance(var, tk.BooleanVar):
                widget = ttk.Checkbutton(row, variable=var)
                widget.pack(side="left", anchor="w")
            elif label == "Modo":
                widget = ttk.Combobox(row, textvariable=var, values=["live", "paper"], state="readonly", style="Dark.TCombobox")
                widget.pack(side="left", fill="x", expand=True)
            else:
                entry = ttk.Entry(row, textvariable=var, style="Dark.TEntry")
                entry.pack(side="left", fill="x", expand=True)

    def _build_logs_tab(self) -> None:
        outer = ttk.Frame(self.logs_tab, style="App.TFrame", padding=12)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Eventos e logs em tempo real", style="Section.TLabel").pack(side="left")
        ttk.Button(header, text="Limpar", command=self._clear_logs, style="Info.TButton").pack(side="right")

        self.log_text = tk.Text(
            outer,
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            height=24,
            wrap="word",
            font=("Consolas", 10),
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("info", foreground="#cbd5e1")
        self.log_text.tag_configure("warn", foreground="#fbbf24")
        self.log_text.tag_configure("error", foreground="#f87171")
        self.log_text.configure(state="disabled")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F5>", lambda _event: self._refresh_now())
        self.root.bind("<F9>", lambda _event: self._manual_trade("buy"))
        self.root.bind("<F10>", lambda _event: self._manual_trade("sell"))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _handle_notification(self, event: NotificationEvent) -> None:
        self._event_queue.put(event)

    def _append_log(self, text: str, tag: str = "info") -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _refresh_now(self) -> None:
        self._refresh_all()
        self._append_log(f"[{_now_text()}] atualização manual concluída", "info")

    def _refresh_price_only(self) -> None:
        self._update_market_data()
        self._append_log(f"[{_now_text()}] preço atualizado", "info")

    def _load_config_file_dialog(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecionar configuração",
            filetypes=[("YAML", "*.yaml *.yml"), ("Todos os arquivos", "*.*")],
            initialdir=str(self.config_path.parent),
        )
        if not selected:
            return
        self.config_path = Path(selected)
        self.config = load_config(self.config_path)
        self._sync_form_from_config()
        self.trader = self._build_trader()
        self._refresh_all()
        self._append_log(f"[{_now_text()}] configuração carregada de {self.config_path}", "info")

    def _collect_config_from_form(self) -> dict[str, Any]:
        config = {
            "app": {
                "symbol": self.symbol_var.get().strip() or "XAUUSD",
                "timeframes": list(self.config.get("app", {}).get("timeframes", ["M1", "M5", "M15"])),
                "mode": self.mode_var.get().strip().lower() or "live",
                "cycle_seconds": max(1, _to_int(self.cycle_var.get(), 30)),
                "position_state_path": self.position_state_var.get().strip() or "runtime/position_state.json",
            },
            "broker": {
                "terminal_path": self.terminal_path_var.get().strip(),
                "login": _to_int(self.login_var.get(), 0),
                "password": self.password_var.get(),
                "server": self.server_var.get().strip(),
                "deviation": _to_int(self.deviation_var.get(), 20),
                "magic": _to_int(self.magic_var.get(), 2401001),
            },
            "risk": {
                "risk_per_trade": max(0.0, _to_float(self.risk_var.get(), 0.5) / 100.0),
                "daily_loss_limit": max(0.0, _to_float(self.daily_loss_var.get(), 2.0) / 100.0),
                "max_consecutive_losses": max(1, _to_int(self.max_consecutive_var.get(), 3)),
                "max_trades_per_day": max(1, _to_int(self.max_trades_var.get(), 5)),
                "max_open_positions": max(1, _to_int(self.max_open_var.get(), 1)),
                "max_spread_points": max(1.0, _to_float(self.max_spread_var.get(), 80.0)),
                "breakeven_trigger_r": max(0.1, _to_float(self.be_var.get(), 0.9)),
                "partial_take_profit_r": max(0.1, _to_float(self.partial_var.get(), 1.0)),
                "final_take_profit_r": max(0.1, _to_float(self.final_tp_var.get(), 2.0)),
                "partial_close_ratio": min(1.0, max(0.1, _to_float(self.partial_ratio_var.get(), 0.5))),
                "trailing_start_r": max(0.1, _to_float(self.trailing_start_var.get(), 1.2)),
                "trailing_atr_mult": max(0.1, _to_float(self.trailing_atr_var.get(), 1.2)),
                "trailing_step_points": max(0.1, _to_float(self.trailing_step_var.get(), 10.0)),
                "min_rr": max(0.1, _to_float(self.min_rr_var.get(), 1.2)),
                "session_start": self.session_start_var.get().strip() or "07:00",
                "session_end": self.session_end_var.get().strip() or "20:30",
            },
            "strategy": copy_dict(self.config.get("strategy", {})),
            "ai": {
                "enabled": bool(self.ai_enabled_var.get()),
                "hf_model": self.ai_model_var.get().strip(),
                "timeout_seconds": int(self.config.get("ai", {}).get("timeout_seconds", 12)),
            },
            "notifications": {
                "enabled": True,
                "queue_file": self.queue_file_var.get().strip() or "xauusd_push_queue.txt",
                "min_priority": int(self.config.get("notifications", {}).get("min_priority", 1)),
            },
        }
        return config

    def _sync_form_from_config(self) -> None:
        self._set_vars_from_config()
        self._refresh_all()

    def _persist_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self.config, handle, sort_keys=False, allow_unicode=True)

    def _apply_settings(self) -> None:
        with self._lock:
            self.config = self._collect_config_from_form()
            self._persist_config()
            self.trader = self._build_trader()
        self.status_var.set("Configuração aplicada")
        self._append_log(f"[{_now_text()}] configurações aplicadas e salvas", "info")
        self._refresh_all()

    def _update_market_data(self) -> None:
        with self._lock:
            trader = self.trader
        if not trader.broker.connect():
            self.connection_var.set("Desconectado")
            self.status_var.set("Falha na conexão MT5")
            return

        symbol = self.symbol_var.get().strip() or "XAUUSD"
        tick = None
        try:
            trader.broker.ensure_symbol(symbol)
            from_meta = trader.broker.symbol_info(symbol)
            tick = None
            if from_meta:
                import MetaTrader5 as mt5  # type: ignore
                tick = mt5.symbol_info_tick(symbol)
        except Exception:
            tick = None

        if tick is not None:
            price = float(tick.ask if self.side_var.get().lower() == "buy" else tick.bid)
            self.current_price_var.set(f"{price:.2f}")
            spread = trader.broker.current_spread_points(symbol)
            self.spread_var.set(f"{spread:.1f} pts")
        else:
            self.current_price_var.set("-")
            self.spread_var.set("-")

    def _update_performance(self) -> None:
        with self._lock:
            trader = self.trader
        symbol = self.symbol_var.get().strip() or "XAUUSD"
        if not trader.broker.connect():
            self.connection_var.set("Desconectado")
            self.account_balance_var.set("-")
            self.account_equity_var.set("-")
            self.account_free_margin_var.set("-")
            self.account_margin_level_var.set("-")
            return
        account = trader.broker.account_info()
        balance = float(account.get("balance") or 0.0)
        equity = float(account.get("equity") or balance)
        free_margin = float(account.get("margin_free") or account.get("free_margin") or 0.0)
        margin_level = float(account.get("margin_level") or 0.0)
        spread = trader.broker.current_spread_points(symbol)
        positions = trader.engine.list_positions(symbol)
        open_pnl = sum(float(pos.profit) for pos in positions)
        daily_pnl = trader.risk.daily_pnl_from_equity(equity)

        self.metric_cards["balance"].set(f"{balance:,.2f}")
        self.metric_cards["equity"].set(f"{equity:,.2f}")
        self.metric_cards["free_margin"].set(f"{free_margin:,.2f}")
        self.metric_cards["daily_pnl"].set(f"{daily_pnl:,.2f}")
        self.metric_cards["open_pnl"].set(f"{open_pnl:,.2f}")
        self.metric_cards["open_positions"].set(str(len(positions)))

        self.account_balance_var.set(f"{balance:,.2f}")
        self.account_equity_var.set(f"{equity:,.2f}")
        self.account_free_margin_var.set(f"{free_margin:,.2f}")
        self.account_margin_level_var.set(f"{margin_level:.1f}%")
        self.daily_pnl_var.set(f"{daily_pnl:,.2f}")
        self.open_pnl_var.set(f"{open_pnl:,.2f}")
        self.open_positions_var.set(str(len(positions)))
        self.trades_today_var.set(str(trader.risk.state.trades_today))
        self.regime_var.set(self.regime_var.get() if self.regime_var.get() != "-" else "-")
        self.session_status_var.set("Ativa" if trader.risk.session_allowed() else "Fora da janela")
        self.lock_status_var.set("Bloqueado" if trader.risk.state.locked else "Liberado")
        self.live_mode_var.set("Live" if not trader.paper_mode else "Paper")
        self.connection_var.set(f"Conectado | spread={spread:.1f} pts")
        self.risk_var.set(f"{float(trader.config['risk'].get('risk_per_trade', 0.005)) * 100:.2f}")
        self.performance_labels["day_pnl"].set(f"{daily_pnl:,.2f}")
        self.performance_labels["open_pnl"].set(f"{open_pnl:,.2f}")
        self.performance_labels["trades_today"].set(str(trader.risk.state.trades_today))
        self.performance_labels["consecutive_losses"].set(str(trader.risk.state.consecutive_losses))
        self.performance_labels["daily_limit"].set(f"{float(trader.config['risk'].get('daily_loss_limit', 0.02)) * 100:.2f}%")
        self.performance_labels["risk_trade"].set(f"{float(trader.config['risk'].get('risk_per_trade', 0.005)) * 100:.2f}%")

        self._refresh_positions_list(positions)
        self._update_manual_preview()

    def _refresh_positions_list(self, positions: list[Any]) -> None:
        for child in self.positions_scroll.inner.winfo_children():
            child.destroy()

        if not positions:
            ttk.Label(self.positions_scroll.inner, text="Nenhuma posição aberta.", style="Subtitle.TLabel").pack(anchor="w", pady=8)
            return

        for position in positions:
            card = ttk.Frame(self.positions_scroll.inner, style="Card.TFrame", padding=14)
            card.pack(fill="x", pady=8)
            top = ttk.Frame(card, style="Card.TFrame")
            top.pack(fill="x")
            title = f"Ticket {position.ticket} | {position.symbol} | {position.side.upper()} | {position.volume:.2f} lot"
            ttk.Label(top, text=title, style="Section.TLabel").pack(side="left")
            ttk.Label(top, text=f"PnL {position.profit:,.2f}", style="Dark.TLabel").pack(side="right")

            details = ttk.Frame(card, style="Card.TFrame")
            details.pack(fill="x", pady=(8, 0))
            fields = [
                ("Entrada", f"{position.price_open:.2f}"),
                ("Preço atual", f"{position.current_price:.2f}"),
                ("SL", f"{position.stop_loss:.2f}"),
                ("TP", f"{position.take_profit:.2f}"),
                ("Magic", str(position.magic)),
                ("Comentário", position.comment or "-"),
            ]
            for idx, (label, value) in enumerate(fields):
                box = ttk.Frame(details, style="Card.TFrame")
                box.grid(row=0, column=idx, padx=6, sticky="nsew")
                details.columnconfigure(idx, weight=1)
                ttk.Label(box, text=label, style="MetricTitle.TLabel").pack(anchor="w")
                ttk.Label(box, text=value, style="Dark.TLabel").pack(anchor="w")

            actions = ttk.Frame(card, style="Card.TFrame")
            actions.pack(fill="x", pady=(10, 0))
            ttk.Button(actions, text="Fechar", command=lambda p=position: self._close_position(p, p.volume), style="Danger.TButton").pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="Fechar 50%", command=lambda p=position: self._partial_close_position(p), style="Info.TButton").pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="Atualizar", command=self._refresh_now, style="Accent.TButton").pack(side="left")

    def _update_manual_preview(self) -> None:
        symbol = self.symbol_var.get().strip() or "XAUUSD"
        price = _to_float(self.current_price_var.get(), 0.0)
        sl = _to_float(self.manual_sl_var.get(), 0.0)
        volume = _to_float(self.manual_volume_var.get(), 0.0)
        if price <= 0 or sl <= 0:
            self.manual_lot_preview_var.set("Lote sugerido: -")
            return
        with self._lock:
            trader = self.trader
        info = trader.broker.symbol_info(symbol)
        equity = float(trader.broker.account_info().get("equity") or trader.broker.account_info().get("balance") or 0.0)
        lots = trader.risk.calculate_lots(
            equity=equity,
            entry_price=price,
            stop_loss=sl,
            symbol_info=info,
            manual_lots=volume if volume > 0 else None,
        )
        self.manual_lot_preview_var.set(f"Lote sugerido: {lots:.2f}")

    def _refresh_all(self) -> None:
        self._update_market_data()
        self._update_performance()
        self._update_session_snapshot()

    def _update_session_snapshot(self) -> None:
        with self._lock:
            trader = self.trader
        self.session_status_var.set("Ativa" if trader.risk.session_allowed() else "Fora da janela")
        self.lock_status_var.set("Bloqueado" if trader.risk.state.locked else "Liberado")
        self.live_mode_var.set("Live" if not trader.paper_mode else "Paper")
        self.symbol_var.set(self.symbol_var.get().strip() or "XAUUSD")

    def _update_status_from_result(self, result: dict[str, Any]) -> None:
        self._last_manual_result = result
        if result.get("success"):
            self.last_result_var.set("Última ação: sucesso")
        else:
            self.last_result_var.set("Última ação: falha")

    def _manual_trade(self, side: str) -> None:
        try:
            with self._lock:
                trader = self.trader
            symbol = self.symbol_var.get().strip() or "XAUUSD"
            if not trader.broker.connect():
                messagebox.showerror("MT5", "Não foi possível conectar ao terminal MT5.")
                return
            trader.broker.ensure_symbol(symbol)
            price = self._get_live_price(symbol, side)
            if price <= 0:
                messagebox.showerror("Preço", "Não foi possível obter o preço atual do símbolo.")
                return
            sl = _to_float(self.manual_sl_var.get(), 0.0)
            tp = _to_float(self.manual_tp_var.get(), 0.0)
            if sl <= 0 or tp <= 0:
                messagebox.showwarning("SL/TP", "Preencha SL e TP antes de abrir a ordem manual.")
                return
            volume = _to_float(self.manual_volume_var.get(), 0.0)
            idea = TradeIdea(
                symbol=symbol,
                side=side,
                entry_mode="market",
                entry_price=price,
                stop_loss=sl,
                take_profit=tp,
                lots=volume,
                confidence=0.95,
                regime="manual",
                reason=f"manual {side}",
                partial_take_profit=None,
                trailing_start_r=None,
                max_hold_bars=0,
            )
            equity = float(trader.broker.account_info().get("equity") or trader.broker.account_info().get("balance") or 0.0)
            spread = trader.broker.current_spread_points(symbol)
            decision, order = trader.engine.place_trade(idea, equity=equity, spread_points=spread)
            result = {
                "decision": decision.reason,
                "success": bool(order and order.success),
                "order": order.raw if order else None,
                "manual": True,
            }
            self._update_status_from_result(result)
            self._append_log(
                f"[{_now_text()}] manual {side.upper()} | approved={decision.approved} | lot={decision.lots:.2f} | result={result.get('success')} | retcode={result.get('order', {}).get('retcode') if result.get('order') else None}",
                "info" if result.get("success") else "warn",
            )
            if not result.get("success"):
                messagebox.showwarning("Ordem manual", f"A ordem foi recusada: {result.get('order')}")
            else:
                self._refresh_all()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def _get_live_price(self, symbol: str, side: str) -> float:
        with self._lock:
            trader = self.trader
        try:
            trader.broker.ensure_symbol(symbol)
            import MetaTrader5 as mt5  # type: ignore

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return 0.0
            return float(tick.ask if side.lower() == "buy" else tick.bid)
        except Exception:
            return 0.0

    def _close_position(self, position: Any, volume: float) -> None:
        with self._lock:
            trader = self.trader
        result = trader.engine.close_single_position(
            ticket=position.ticket,
            symbol=position.symbol,
            side=position.side,
            volume=volume,
        )
        self._update_status_from_result(result)
        self._append_log(f"[{_now_text()}] fechar ticket={position.ticket} | result={result}", "info" if result.get("success") else "warn")
        self._refresh_all()

    def _partial_close_position(self, position: Any) -> None:
        with self._lock:
            trader = self.trader
        result = trader.engine.partial_close_position(
            ticket=position.ticket,
            symbol=position.symbol,
            side=position.side,
            volume=position.volume,
            ratio=0.5,
        )
        self._update_status_from_result(result)
        self._append_log(f"[{_now_text()}] parcial 50% ticket={position.ticket} | result={result}", "info" if result.get("success") else "warn")
        self._refresh_all()

    def _close_all_positions(self) -> None:
        if not messagebox.askyesno("Fechar todas", "Deseja fechar todas as posições abertas agora?"):
            return
        with self._lock:
            trader = self.trader
        results = trader.engine.close_all_positions(self.symbol_var.get().strip() or None)
        self._append_log(f"[{_now_text()}] fechar todas | results={results}", "info")
        self._refresh_all()

    def _start_auto(self) -> None:
        if self._auto_running:
            return
        self._auto_running = True
        self.status_var.set("Automação iniciada")
        self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self._auto_thread.start()
        self._append_log(f"[{_now_text()}] automação iniciada", "info")

    def _stop_auto(self) -> None:
        self._auto_running = False
        self.status_var.set("Automação parada")
        self._append_log(f"[{_now_text()}] automação parada", "warn")

    def _auto_loop(self) -> None:
        while self._auto_running:
            try:
                with self._lock:
                    trader = self.trader
                result = trader.run_once()
                self._status_queue.put(str(result))
            except Exception as exc:
                self._status_queue.put(f"erro: {exc}")
                self._event_queue.put(NotificationEvent(title="Erro", message=str(exc), priority=0, kind="error"))
            time.sleep(max(5, int(self.cycle_var.get() or 30)))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self._event_queue.get_nowait()
                tag = "info"
                if event.kind == "warn":
                    tag = "warn"
                elif event.kind == "error":
                    tag = "error"
                self._append_log(f"[{event.created_at or _now_text()}] {event.kind.upper()} {event.title} | {event.message}", tag)
                self.last_result_var.set(f"Último evento: {event.title}")
        except queue.Empty:
            pass
        try:
            while True:
                status = self._status_queue.get_nowait()
                self.last_result_var.set(status[:120])
        except queue.Empty:
            pass
        self.root.after(250, self._poll_events)

    def _tick(self) -> None:
        try:
            self._refresh_all()
        finally:
            self.root.after(1000, self._tick)

    def _on_close(self) -> None:
        self._auto_running = False
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


def copy_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items()}


def launch_gui(config_path: Path) -> None:
    panel = XAUUSDControlPanel(config_path)
    panel.run()
