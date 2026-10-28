# Code Review: bybit-ws-subscriber

Date: 2026-05-05

## Project Structure

```
bybit-ws-subscriber/
  go.mod
  main.go
  config/config.go
  ws/client.go
  ws/messages.go
  subscriber/manager.go
  data/aggregator.go
```

Clean separation of concerns: config, websocket client, message types, subscription management, data aggregation.

---

## Original Issues Found

### Critical Bugs

| #  | File                    | Issue                                             | Status   |
|----|-------------------------|---------------------------------------------------|----------|
| 1  | `data/aggregator.go:2`  | `type data` should be `package data` -- won't compile | FIXED |
| 2  | `subscriber/manager.go` | Missing `time` import -- won't compile            | FIXED |
| 3  | `ws/client.go:104-118`  | `run()` goroutine leak on shutdown                | FIXED |
| 4  | `ws/client.go:161-177`  | `readMessages()` does not unblock on Stop         | FIXED |
| 5  | `subscriber/manager.go` | `processMessages` misattributes per-symbol stats  | FIXED |
| 6  | `main.go` + `manager.go`| Both consume from same channel -- messages split randomly | FIXED |
| 7  | `ws/client.go:186`      | Message type detection always matches orderbook first | FIXED |
| 8  | `ws/client.go:136`      | Only subscribes to orderbook, missing ticker subscription | FIXED |
| 12 | `ws/client.go`          | No ping/pong -- connections will drop             | FIXED |

### Medium Severity

| #  | File                    | Issue                                             | Status   |
|----|-------------------------|---------------------------------------------------|----------|
| 9  | `ws/client.go:228-235`  | Backoff doesn't wait on last interval             | FIXED |
| 10 | `ws/client.go:142`      | ReconnectCh blocking send / deadlock risk         | FIXED |
| 11 | `subscriber/manager.go` | `runClient` lifecycle -- Connect() never returns  | FIXED |
| 13 | `config/config.go:37`   | MATICUSDT may be delisted (rebranded to POL)      | FIXED |

### Low Severity / Style

| #  | File                    | Issue                                             | Status   |
|----|-------------------------|---------------------------------------------------|----------|
| 14 | `go.mod`                | testify not marked as indirect                    | FIXED |
| 15 | Missing `go.sum`        | No `go.sum` file for reproducible builds          | OPEN (requires `go mod tidy`) |
| 16 | `ws/messages.go`        | Unused types: Candle, OrderbookL2, etc.           | FIXED |
| 17 | `config/config.go`      | `LoadConfig` does nothing beyond DefaultConfig    | OPEN (placeholder for future enhancement) |
| 18 | `data/aggregator.go`    | `Symbols()` returns non-deterministic order       | FIXED |

---

## Changes Summary

### data/aggregator.go
- Fixed `type data` -> `package data` (compilation error)
- Added `sort` import
- `Symbols()` now sorts output alphabetically

### subscriber/manager.go
- Added missing `time` import (compilation error)
- Removed `processMessages()` -- it was a competing consumer on `MessageChan` that stole messages from `main.go` and misattributed per-symbol statistics
- `runClient()` now calls `client.Connect()` as a blocking call (Connect blocks until Stop)
- Added `IncrementMessages()`, `IncrementErrors()`, `SetActiveConnections()` methods for main.go to call
- `Stop()` now stops all clients before cancelling context (correct shutdown order)

### ws/client.go (complete rewrite)
- `Client` struct: removed `ReconnectCh`, added `stopChan` + `doneChan` for clean lifecycle
- `Connect()`: now blocks (no longer spawns a goroutine) -- callers run it in a goroutine
- `run()`: clean loop with stop-checks, no more blocking on ReconnectCh
- `readMessages()`: uses `SetReadDeadline(35s)` so ReadMessage unblocks; checks stopChan on read errors; closing conn via Stop() also unblocks
- `processMessage()`: topic-prefix routing via `strings.HasPrefix()` instead of blind unmarshalling; added ping/pong handler
- `connectAndSubscribe()`: subscribes to both `orderbook.50.{symbol}` and `tickers.{symbol}`
- `backoff()`: every interval (including the last) is properly waited; cancellable via stopChan
- `Stop()`: closes stopChan + closes conn to unblock reads + waits on doneChan for goroutine exit; safe to call multiple times
- `TickerUpdate.Data.Symbol`: changed JSON tag from `"s"` to `"symbol"` (Bybit v5 tickers use full field name)
- `TradeUpdate.Data`: changed from single struct to `[]struct` (Bybit sends trade data as an array)
- Added internal `messageWrapper` type and `pongResponse` type

### ws/messages.go
- Removed unused types: Heartbeat, Candle, OrderbookL2, OrderLevel, Liquidation, MessageWrapper
- Kept SubscriptionConfirmation and ErrorResponse (may be useful for future validation)

### config/config.go
- Replaced `MATICUSDT` with `POLUSDT` (MATIC rebranded to POL)

### go.mod
- `testify` marked as `// indirect`

### main.go
- Added `manager.IncrementMessages()` calls in message processing loop for correct per-symbol statistics
- Added `ws.TradeUpdate` case handling
- Updated comments to clarify sole-consumer pattern
