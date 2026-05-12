from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from queue import Queue, Empty
from tkinter import ttk, messagebox

import yaml

from .config import load_config
from .notifier import CallbackSink, NotificationEvent
from .trader import XAUUSDAutonomousTrader


class XAUUSDTraderGUI:
    def __init__(self, config_path: str | Path = "configs/default.yaml"):
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        self.trader = XAUUSDAutonomousTrader(self.config)
        self.event_queue: Queue[NotificationEvent] = Queue()
        self.result_queue: Queue[dict] = Queue()
        self.running = False
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()

        self.trader.notifier.sinks.append(CallbackSink(self.event_queue.put))

        self.root = tk.Tk()
        self.root.title("XAUUSD IA Trader")
        self.root.geometry("1280x860")
        self.root.minsize(1100, 760)

        self._build_ui()
        self._bind_hotkeys()
        self._schedule_refresh()
        self.refresh_status()

    def _bind_hotkeys(self) -> None:
        self.root.bind("<F5>", lambda _event: self.refresh_status())
        self.root.bind("<F9>", lambda _event: self.force_trade("buy"))
        self.root.bind("<F10>", lambda _event: self.force_trade("sell"))

    def _build_ui(self) -> None:
        self.root.configure(bg="#111318")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#111318")
        style.configure("TLabel", background="#111318", foreground="#E6E6E6")
        style.configure("TLabelframe", background="#111318", foreground="#E6E6E6")
        style.configure("TLabelframe.Label", background="#111318", foreground="#E6E6E6")
        style.configure("TButton", padding=8)

        self.symbol_var = tk.StringVar(value=self.config["app"]["symbol"])
        self.mode_var = tk.StringVar(value=self.config["app"].get("mode", "paper"))
        self.cycle_var = tk.StringVar(value=str(self.config["app"].get("cycle_seconds", 30)))
        self.spread_var = tk.StringVar(value=str(self.config["risk"].get("max_spread_points", 80)))
        self.risk_var = tk.StringVar(value=str(self.config["risk"].get("risk_per_trade", 0.005)))
        self.terminal_var = tk.StringVar(value=self.config["broker"].get("terminal_path", ""))
        self.login_var = tk.StringVar(value=str(self.config["broker"].get("login", 0)))
        self.server_var = tk.StringVar(value=self.config["broker"].get("server", ""))
        self.password_var = tk.StringVar(value=self.config["broker"].get("password", ""))
        self.side_var = tk.StringVar(value="buy")

        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=12)

        controls = ttk.LabelFrame(top, text="Controle")
        controls.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._add_field(controls, "Símbolo", self.symbol_var, 0, 0)
        self._add_field(controls, "Modo", self.mode_var, 0, 1)
        self._add_field(controls, "Ciclo s", self.cycle_var, 0, 2)
        self._add_field(controls, "Spread máx", self.spread_var, 1, 0)
        self._add_field(controls, "Risco/trade", self.risk_var, 1, 1)
        self._add_field(controls, "Terminal", self.terminal_var, 1, 2, width=40)
        self._add_field(controls, "Login", self.login_var, 2, 0)
        self._add_field(controls, "Servidor", self.server_var, 2, 1)
        self._add_field(controls, "Senha", self.password_var, 2, 2, show="*")

        button_row = ttk.Frame(controls)
        button_row.grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(6, 8))
        button_row.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        ttk.Button(button_row, text="Aplicar", command=self.apply_settings).grid(row=0, column=0, padx=4, sticky="ew")
        ttk.Button(button_row, text="Iniciar Auto", command=self.start_auto).grid(row=0, column=1, padx=4, sticky="ew")
        ttk.Button(button_row, text="Parar Auto", command=self.stop_auto).grid(row=0, column=2, padx=4, sticky="ew")
        ttk.Button(button_row, text="Forçar Compra", command=lambda: self.force_trade("buy")).grid(row=0, column=3, padx=4, sticky="ew")
        ttk.Button(button_row, text="Forçar Venda", command=lambda: self.force_trade("sell")).grid(row=0, column=4, padx=4, sticky="ew")
        ttk.Button(button_row, text="Atualizar", command=self.refresh_status).grid(row=0, column=5, padx=4, sticky="ew")

        status = ttk.LabelFrame(top, text="Status")
        status.pack(side="right", fill="y", padx=(8, 0))
        self.status_text = tk.StringVar(value="desconectado")
        self.last_text = tk.StringVar(value="-")
        self.spread_text = tk.StringVar(value="-")
        self.equity_text = tk.StringVar(value="-")
        self.regime_text = tk.StringVar(value="-")
        self.open_text = tk.StringVar(value="-")

        for row, (label, var) in enumerate([
            ("Conexão", self.status_text),
            ("Último", self.last_text),
            ("Spread", self.spread_text),
            ("Equity", self.equity_text),
            ("Regime", self.regime_text),
            ("Posições", self.open_text),
        ]):
            ttk.Label(status, text=label + ":").grid(row=row, column=0, sticky="w", padx=8, pady=3)
            ttk.Label(status, textvariable=var, width=28).grid(row=row, column=1, sticky="w", padx=8, pady=3)

        middle = ttk.Frame(self.root)
        middle.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        positions_box = ttk.LabelFrame(middle, text="Posições")
        positions_box.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.positions = ttk.Treeview(positions_box, columns=("ticket", "side", "volume", "open", "sl", "tp", "profit"), show="headings", height=12)
        for col, heading, width in [
            ("ticket", "Ticket", 90),
            ("side", "Lado", 70),
            ("volume", "Vol", 70),
            ("open", "Abertura", 110),
            ("sl", "S/L", 110),
            ("tp", "T/P", 110),
            ("profit", "Lucro", 90),
        ]:
            self.positions.heading(col, text=heading)
            self.positions.column(col, width=width, anchor="center")
        self.positions.pack(fill="both", expand=True, padx=8, pady=8)

        logs_box = ttk.LabelFrame(middle, text="Logs")
        logs_box.pack(side="right", fill="both", expand=True, padx=(8, 0))
        self.log_text = tk.Text(logs_box, height=20, wrap="word", bg="#0D1117", fg="#E6EDF3", insertbackground="#E6EDF3")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.configure(state="disabled")

        footer = ttk.Frame(self.root)
        footer.pack(fill="x", padx=12, pady=(0, 10))
        self.footer_var = tk.StringVar(value=str(self.config_path))
        ttk.Label(footer, textvariable=self.footer_var).pack(side="left")
        ttk.Label(footer, text="F5 atualiza | F9 compra | F10 venda").pack(side="right")

    def _add_field(self, parent: ttk.Frame, label: str, var: tk.StringVar, row: int, col: int, width: int = 18, show: str | None = None) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=col, sticky="ew", padx=8, pady=4)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=label, width=12).grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(frame, textvariable=var, width=width, show=show)
        entry.grid(row=0, column=1, sticky="ew")

    def _append_log(self, event: NotificationEvent) -> None:
        line = f"[{event.kind.upper()}] {event.title} | {event.message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _schedule_refresh(self) -> None:
        self.root.after(200, self._poll_queues)
        self.root.after(5000, self._auto_refresh)

    def _poll_queues(self) -> None:
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._append_log(event)
        except Empty:
            pass

        try:
            while True:
                result = self.result_queue.get_nowait()
                self._update_result(result)
        except Empty:
            pass

        self.root.after(200, self._poll_queues)

    def _auto_refresh(self) -> None:
        self.refresh_status()
        self.root.after(5000, self._auto_refresh)

    def _update_result(self, result: dict) -> None:
        success = bool(result.get("success"))
        mode = "FORCED" if result.get("forced") else "AUTO"
        self.last_text.set(f"{mode} {'OK' if success else 'FAIL'}")
        if not success:
            self.status_text.set("erro")
        self.refresh_positions()

    def refresh_positions(self) -> None:
        for item in self.positions.get_children():
            self.positions.delete(item)
        try:
            if self.trader.paper_mode:
                positions = self.trader.engine.state_store.active_items(self.trader.symbol)
                rows = [
                    (p.ticket, p.side, f"{p.remaining_volume:.2f}", f"{p.price_open:.2f}", f"{p.stop_loss:.2f}", f"{p.take_profit:.2f}", "-")
                    for p in positions
                ]
            else:
                payloads = self.trader.broker.positions_get(symbol=self.trader.symbol, magic=int(self.trader.config["broker"].get("magic", 2401001)))
                rows = []
                for p in payloads:
                    rows.append(
                        (
                            p.get("ticket", "-"),
                            "buy" if int(p.get("type", 0)) == 0 else "sell",
                            f"{float(p.get('volume', 0.0)):.2f}",
                            f"{float(p.get('price_open', 0.0)):.2f}",
                            f"{float(p.get('sl', 0.0)):.2f}",
                            f"{float(p.get('tp', 0.0)):.2f}",
                            f"{float(p.get('profit', 0.0)):.2f}",
                        )
                    )
            for row in rows:
                self.positions.insert("", "end", values=row)
            self.open_text.set(str(len(rows)))
        except Exception as exc:
            self._append_log(NotificationEvent(title="Positions error", message=str(exc), kind="error", priority=0))

    def refresh_status(self) -> None:
        try:
            if not self.trader.broker.connected:
                self.trader.broker.connect()
            account = self.trader.broker.account_info()
            equity = float(account.get("equity") or account.get("balance") or 0.0)
            spread = self.trader.broker.current_spread_points(self.trader.symbol)
            info = self.trader.broker.symbol_info(self.trader.symbol)
            self.status_text.set("conectado" if self.trader.broker.connected else "desconectado")
            self.spread_text.set(f"{spread:.1f} pts")
            self.equity_text.set(f"{equity:.2f}")
            self.regime_text.set(f"digits={info.get('digits', '-')}")
            self.refresh_positions()
        except Exception as exc:
            self.status_text.set("erro")
            self._append_log(NotificationEvent(title="Status error", message=str(exc), kind="error", priority=0))

    def apply_settings(self) -> None:
        if self.running:
            messagebox.showwarning("Em execução", "Pare o modo automático antes de aplicar as configurações.")
            return

        self.config["app"]["symbol"] = self.symbol_var.get().strip() or "XAUUSD"
        self.config["app"]["mode"] = self.mode_var.get().strip() or "paper"
        self.config["app"]["cycle_seconds"] = int(self.cycle_var.get() or 30)
        self.config["risk"]["max_spread_points"] = float(self.spread_var.get() or 80)
        self.config["risk"]["risk_per_trade"] = float(self.risk_var.get() or 0.005)
        self.config["broker"]["terminal_path"] = self.terminal_var.get().strip()
        self.config["broker"]["login"] = int(self.login_var.get() or 0)
        self.config["broker"]["server"] = self.server_var.get().strip()
        self.config["broker"]["password"] = self.password_var.get()

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(yaml.safe_dump(self.config, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.trader = XAUUSDAutonomousTrader(self.config)
        self.trader.notifier.sinks.append(CallbackSink(self.event_queue.put))
        self.footer_var.set(f"Config salvo em {self.config_path}")
        self.refresh_status()
        self._append_log(NotificationEvent(title="Config aplicada", message="configuração atualizada e re-salva", kind="info", priority=1))

    def start_auto(self) -> None:
        if self.running:
            return
        self.stop_event.clear()
        self.running = True
        self.status_text.set("rodando")

        def worker() -> None:
            while not self.stop_event.is_set():
                try:
                    result = self.trader.run_once()
                    self.result_queue.put(result)
                except Exception as exc:
                    self.result_queue.put({"success": False, "error": str(exc)})
                    self.event_queue.put(NotificationEvent(title="Auto error", message=str(exc), kind="error", priority=0))
                time.sleep(max(5, int(self.cycle_var.get() or 30)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()
        self._append_log(NotificationEvent(title="Auto iniciado", message="loop automático ativado", kind="info", priority=1))

    def stop_auto(self) -> None:
        self.stop_event.set()
        self.running = False
        self.status_text.set("parado")
        self._append_log(NotificationEvent(title="Auto parado", message="loop automático desativado", kind="info", priority=1))

    def force_trade(self, side: str) -> None:
        def task() -> None:
            try:
                result = self.trader.run_once(force_side=side)
                self.result_queue.put(result)
                self.event_queue.put(
                    NotificationEvent(
                        title="Trade forçado",
                        message=f"{side.upper()} | success={result.get('success')} | order={result.get('order')}",
                        kind="info" if result.get("success") else "warn",
                        priority=1,
                    )
                )
            except Exception as exc:
                self.result_queue.put({"success": False, "error": str(exc)})
                self.event_queue.put(NotificationEvent(title="Force error", message=str(exc), kind="error", priority=0))

        threading.Thread(target=task, daemon=True).start()

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def on_close(self) -> None:
        self.stop_auto()
        self.root.destroy()


def launch_gui(config_path: str | Path = "configs/default.yaml") -> None:
    XAUUSDTraderGUI(config_path).run()
