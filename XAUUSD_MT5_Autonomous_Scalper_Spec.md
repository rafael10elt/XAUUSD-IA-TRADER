# XAUUSD MT5 Autonomous Scalper - Project Spec

## Goal
Build an autonomous XAUUSD scalping system for MetaTrader 5 that:
- Adapts to the current market regime.
- Uses fast local execution.
- Enforces strict prop firm risk limits.
- Sends push notifications during the full trade lifecycle.
- Remains auditable and easy to pause or disable.

## Core Principle
This should not be a "fully free-form AI trader".
The best approach is:
- AI for context and adaptation.
- Deterministic rules for execution and risk.
- Hard safety limits that cannot be overridden by model output.

## Target Outcome
The bot should be able to:
- Detect market regime.
- Decide whether to trade or stay flat.
- Choose market or pending entry.
- Set dynamic SL and TP.
- Move stop to breakeven.
- Trail profit when conditions allow.
- Respect daily loss, drawdown, spread, and trade-count limits.
- Notify the user through MT5 push messages at each key step.

## Recommended Base
Use `ForexScalperAI` as the implementation base.
Why:
- It already has MT5 connection logic.
- It already has execution and risk layers.
- It already has multi-component architecture.
- It is closer to live trading than the other repos.

## System Architecture

### 1. Market Data Layer
Responsible for:
- Reading MT5 candles and ticks.
- Calculating spreads and session state.
- Building higher timeframe context.
- Detecting volatility bursts and compression.
- Detecting news-risk windows if available.

Suggested inputs:
- M1 for entry timing.
- M5 for structure and confirmation.
- M15 for regime context.

Suggested indicators:
- ATR
- VWAP
- EMA 20 / EMA 50
- RSI
- ADX
- Previous day high/low
- Session high/low
- Candle body / wick ratios
- Spread in points
- Recent tick momentum

### 2. Regime Classifier
This layer decides which state the market is in.

Possible regimes:
- Trend continuation
- Trend pullback
- Range mean reversion
- Breakout expansion
- No trade

This can be implemented as:
- A simple rules engine first.
- Later, a lightweight classifier.

For the first version, rules are enough:
- Trend if EMA alignment + ADX + directional candle structure.
- Range if ADX is weak and price is mean-reverting around VWAP or mid-band.
- Breakout if compression is followed by range expansion and volume/tick impulse.

### 3. Decision Engine
The decision engine chooses:
- Direction: buy / sell / no trade.
- Entry mode: market or pending.
- Initial stop loss.
- Initial take profit.
- Whether to allow partial exit.
- Whether to allow trailing stop.

Important:
- The AI should not be allowed to bypass risk limits.
- The AI can suggest, but the risk layer approves or rejects.

### 4. Execution Engine
Responsible for:
- Sending orders to MT5.
- Handling slippage limits.
- Validating symbol availability.
- Verifying spread before entry.
- Re-quoting or canceling if conditions changed.
- Managing order states and fills.

Execution modes:
- Market order for fast continuation or breakout entries.
- Pending order for pullback or retest setups.

### 5. Risk Engine
This is the most important part for prop firm use.

Hard limits suggested for the first version:
- Risk per trade: 0.25% to 0.5%
- Daily max loss: 1% to 2%
- Max open positions: 1
- Max losses in a row: 2 or 3
- Max trades per day: 3 to 6
- Max spread threshold: dynamic, based on ATR and recent median spread
- No trading during major news windows
- No trading when spread spikes abnormally
- No trading when drawdown is near the daily cap
- No trading when the market is too quiet or too chaotic

Risk logic should enforce:
- Position size from stop distance.
- Lot size rounded to broker step.
- Hard stop loss on every trade.
- Daily lockout if limits are hit.
- Emergency close if overall drawdown exceeds a threshold.

### 6. Position Management
After entry, the bot should be able to:
- Move SL to breakeven after the trade validates.
- Partially close at 1R if the strategy supports it.
- Trail the stop once momentum is confirmed.
- Exit if regime changes against the trade.
- Exit if time-in-trade exceeds the max holding window.

Suggested management rules:
- Breakeven trigger: around 0.8R to 1R.
- Partial take profit: 25% to 50% at 1R.
- Final target: 1.5R to 2.5R depending on regime.
- Time stop: close stale trades after a defined bar count.

## XAUUSD-Specific Strategy Logic

### Trend Scalping
Use when:
- EMA 20 > EMA 50 for buys, or reverse for sells.
- ADX confirms directional movement.
- Price holds above/below VWAP.
- Spread is acceptable.

Entry ideas:
- Breakout with confirmation candle.
- Pullback to EMA or VWAP with rejection.

### Range Scalping
Use when:
- ADX is weak.
- Price repeatedly reverts around VWAP.
- Market is not expanding.

Entry ideas:
- Fade extremes near session range.
- Take smaller targets and tighter time stop.

### Breakout Scalping
Use when:
- Compression is visible.
- Session open or high-liquidity window is active.
- Price breaks a key intraday level.

Entry ideas:
- Market order after confirmation.
- Pending stop order beyond the breakout level.

### No-Trade Mode
The bot should immediately switch to no-trade if:
- News risk is high.
- Spread is too large.
- Volatility is too erratic.
- The bot has hit a daily limit.
- The market structure is unclear.

## Dynamic SL and TP Design

### Stop Loss
Best approaches:
- ATR-based stop.
- Structure-based stop.
- Hybrid stop: the wider of ATR and structure, capped by risk budget.

Recommended behavior:
- Initial SL must be present before entry.
- SL distance should reflect current volatility.
- If the stop becomes too wide, skip the trade.

### Take Profit
Best approaches:
- Fixed R multiple.
- Liquidity target.
- Hybrid target with partial exit.

Recommended behavior:
- TP1 at 1R or near first liquidity pocket.
- TP2 at 1.5R to 2.5R depending on regime.
- Optional trailing for the remainder.

### Entry Mode
Market order if:
- Momentum is already confirmed.
- The move is already underway.
- The setup has a strong probability of continuation.

Pending order if:
- A retest is expected.
- Liquidity sweep or pullback is preferred.
- You want better fill quality.

## Model / AI Layer

### What AI Should Do
Use AI for:
- Regime classification support.
- Context interpretation.
- Parameter adaptation.
- Filtering bad conditions.
- Summarizing market state for logs and alerts.

### What AI Should Not Do
Do not let AI:
- Bypass a daily loss limit.
- Remove a stop loss.
- Increase lot size beyond policy.
- Trade during blocked sessions.
- Send order directly without risk approval.

### Hugging Face API
Useful for:
- Secondary analysis.
- Regime summaries.
- Sentiment or contextual scoring.

Not ideal for:
- Tick-level critical decision making.
- Millisecond-sensitive entry execution.

Recommendation:
- Keep execution local.
- Use Hugging Face only as an auxiliary intelligence layer.

## Push Notifications in MT5

### Important Constraint
MT5 Python integration alone is not enough for native push notifications.
The clean solution is:
- Run an EA or MQL5 helper inside MT5 terminal.
- Use `SendNotification()` from MQL5.

### Required Setup
On the MT5 terminal:
- Enable push notifications in Options.
- Enter the MetaQuotes ID of the mobile app.
- Confirm the terminal can send test notifications.

### Notification Flow
The system should notify at:
- Bot start.
- Data loaded.
- Regime detected.
- Trade signal generated.
- Trade approved by risk.
- Order submitted.
- Order filled.
- Order rejected.
- SL/TP updated.
- Breakeven moved.
- Trailing activated.
- Partial close executed.
- Trade closed.
- Daily limit reached.
- Trading paused.
- Trading resumed.
- Fatal error or disconnect.

### Notification Policy
To avoid spam:
- Coalesce repeated alerts.
- Use priority levels.
- Send only important state transitions.
- Throttle repetitive messages.

Suggested priority levels:
- P0: emergency stop, disconnect, limit hit.
- P1: entry, fill, exit, position management changes.
- P2: regime change, pre-trade context.
- P3: diagnostic logs.

### Recommended Message Format
Each push should be short and structured.

Example:
- `XAUUSD BUY approved | lot=0.10 | SL=2318.4 | TP=2324.1 | regime=trend`
- `XAUUSD SL moved to BE | ticket=12345`
- `Daily loss limit reached | trading paused`

## Safety and Prop Firm Rules
This project must be built around constraints first.

Minimum safety requirements:
- One open trade at a time.
- No martingale.
- No grid.
- No averaging down.
- No widening SL after entry.
- No trading after daily loss limit.
- No revenge re-entry after a loss.
- No trade if spread exceeds threshold.
- No trade during blocked news windows.
- No trade if latency is unstable.

Recommended extra limits:
- Daily session cap.
- Cooldown after loss.
- Pause after two consecutive losses.
- Pause after slippage spike.
- Pause if market conditions become unmodelable.

## Operational Flow
1. Load config.
2. Connect to MT5.
3. Verify symbol, spread, and terminal health.
4. Read candles and compute context.
5. Classify regime.
6. Build setup proposal.
7. Validate with risk engine.
8. Submit order.
9. Monitor fill.
10. Manage position.
11. Notify each major state change.
12. Lock out trading if rules are hit.

## Recommended Project Structure

If we extend `ForexScalperAI`, I would organize the XAUUSD logic like this:

- `src/mt5/`
  - connection, data feed, execution, notifications
- `src/strategy/`
  - regime logic, entry models, exit models
- `src/risk/`
  - trade limits, drawdown, sizing, spread filters
- `src/ai/`
  - Hugging Face adapter and regime assistant
- `src/alerts/`
  - MT5 notification formatting and throttling
- `src/monitoring/`
  - session status, logging, metrics

## Suggested MVP Phases

### Phase 1
- MT5 connection
- XAUUSD symbol handling
- data feed
- risk gate
- push notifications
- paper trading only

### Phase 2
- regime classifier
- market vs pending entry selection
- dynamic SL and TP
- breakeven logic
- basic trailing stop

### Phase 3
- prop-firm hardening
- news filter
- spread filter
- trade cooldowns
- daily lockout logic

### Phase 4
- AI regime assistant
- Hugging Face contextual layer
- adaptive parameter tuning
- better monitoring and alerts

### Phase 5
- live demo validation
- forward test
- calibration for prop rules
- only then consider live funding rules

## Backlog of Implementation

### P0 - Must Have
1. Define the XAUUSD trading contract and broker symbol mapping.
2. Implement MT5 connection health checks.
3. Add push notification helper using MQL5 `SendNotification()`.
4. Add notification throttling and priority levels.
5. Add daily loss limit, drawdown limit, and trade-count limits.
6. Add spread filter and session filter.
7. Add one-position-at-a-time enforcement.
8. Add mandatory SL on every order.
9. Add emergency shutdown and lockout.

### P1 - Core Trading Logic
1. Implement market-state detection.
2. Implement trend/range/breakout regime classification.
3. Implement setup generation for XAUUSD.
4. Implement market vs pending order selection.
5. Implement ATR/structure-based dynamic SL.
6. Implement RR-based TP selection.
7. Implement breakeven management.
8. Implement trailing stop after validation.

### P2 - Intelligence Layer
1. Add Hugging Face adapter.
2. Add AI-assisted regime summary.
3. Add adaptive parameter suggestions.
4. Add pre-trade quality scoring.
5. Add post-trade review summary.

### P3 - Monitoring and Reliability
1. Add structured logs.
2. Add session dashboard or console monitor.
3. Add reconnect and recovery flows.
4. Add position reconciliation with MT5.
5. Add alert deduplication.
6. Add performance metrics.

### P4 - Prop Firm Hardening
1. Add time-of-day lockouts.
2. Add news blackout windows.
3. Add volatility spike protection.
4. Add loss-streak cooldown.
5. Add weekly review mode.
6. Add compliance report for each session.

### P5 - Validation
1. Backtest on historical XAUUSD data.
2. Forward test on demo.
3. Simulate prop firm rule set.
4. Measure slippage, fill rate, win rate, and drawdown.
5. Only then consider live deployment.

## Final Recommendation
Yes, this is feasible.

But for a prop-firm target, the winning formula is:
- simple and fast execution,
- strong risk control,
- limited AI in the critical path,
- disciplined notification and monitoring,
- gradual rollout from demo to live.

The system should be designed to survive bad market conditions, not just look intelligent in good ones.
