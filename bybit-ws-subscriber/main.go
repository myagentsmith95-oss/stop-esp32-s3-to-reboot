package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/agent-smith/bybit-ws-subscriber/config"
	"github.com/agent-smith/bybit-ws-subscriber/data"
	"github.com/agent-smith/bybit-ws-subscriber/subscriber"
	"github.com/agent-smith/bybit-ws-subscriber/ws"
)

func main() {
	log.Println("Starting Bybit WebSocket Subscriber...")
	log.Println("======================================")

	// Load configuration
	cfg := config.LoadConfig()
	log.Printf("Loaded %d assets to subscribe to", len(cfg.Assets))
	log.Printf("WebSocket URL: %s", cfg.WebSocketURL)
	log.Printf("Debug mode: %v", cfg.Debug)

	// Create data aggregator
	dataAggregator := data.NewDataAggregator(cfg.Debug)

	// Create subscription manager
	manager := subscriber.NewManager(cfg)

	// Start a goroutine to process incoming messages.
	// This is the sole consumer of MessageChan -- no competing readers.
	go func() {
		for msg := range manager.MessageChan {
			switch m := msg.(type) {
			case ws.OrderbookUpdate:
				if len(m.Data.Bids) > 0 {
					bestBid := m.Data.Bids[0]
					bidPrice, bidVol := bestBid[0], bestBid[1]
					if len(m.Data.Asks) > 0 {
						bestAsk := m.Data.Asks[0]
						askPrice, askVol := bestAsk[0], bestAsk[1]
						dataAggregator.UpdateOrderbook(
							m.Data.Symbol,
							bidPrice, askPrice,
							bidVol, askVol,
							m.Data.TS,
						)
					}
				}
				manager.IncrementMessages(m.Data.Symbol)
			case ws.TickerUpdate:
				dataAggregator.UpdateTicker(
					m.Data.Symbol,
					m.Data.LastPrice,
					m.Data.Volume24h,
					m.Data.Turnover24h,
					m.Data.TS,
				)
				manager.IncrementMessages(m.Data.Symbol)
			case ws.TradeUpdate:
				// Count trade messages but don't aggregate them yet
				if len(m.Data) > 0 {
					manager.IncrementMessages(m.Data[0].Symbol)
				}
			}
		}
	}()

	// Start a goroutine to handle errors
	go func() {
		for err := range manager.ErrorChan {
			log.Printf("Error: %v", err)
		}
	}()

	// Start subscriptions
	manager.Start()

	// Periodically print data summary
	go func() {
		ticker := time.NewTicker(60 * time.Second)
		defer ticker.Stop()

		for range ticker.C {
			allData := dataAggregator.GetAllData()
			log.Printf("\n=== Market Data Summary (%d symbols) ===", len(allData))
			for symbol, d := range allData {
				log.Printf(" %s: Price=%s | Bid=%s/%s | Ask=%s/%s",
					symbol, d.LastPrice, d.BestBid, d.BidVolume, d.BestAsk, d.AskVolume)
			}
		}
	}()

	// Wait for interrupt signal
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	log.Println("\nReceived interrupt signal, shutting down...")

	// Stop the manager
	manager.Stop()

	// Print final statistics
	stats := manager.GetStatistics()
	log.Printf("\n=== Final Statistics ===")
	log.Printf("Total messages received: %d", stats.TotalMessagesReceived)
	for symbol, count := range stats.MessagesBySymbol {
		log.Printf(" %s: %d messages", symbol, count)
	}
	for symbol, count := range stats.ErrorsBySymbol {
		if count > 0 {
			log.Printf(" %s: %d errors", symbol, count)
		}
	}

	log.Println("Shutdown complete.")
}
