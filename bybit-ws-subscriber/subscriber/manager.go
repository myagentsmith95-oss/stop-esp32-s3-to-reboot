// Package subscriber manages multiple WebSocket subscriptions
package subscriber

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/agent-smith/bybit-ws-subscriber/config"
	"github.com/agent-smith/bybit-ws-subscriber/ws"
)

// Manager manages multiple WebSocket clients for different assets
type Manager struct {
	Config           *config.Config
	Clients          []*ws.Client
	MessageChan      chan interface{}
	ErrorChan        chan error
	Wg               sync.WaitGroup
	Ctx              context.Context
	Cancel           context.CancelFunc
	Statistics       *Statistics
	StatisticsMutex  sync.Mutex
}

// Statistics holds subscription statistics
type Statistics struct {
	TotalMessagesReceived int64
	MessagesBySymbol      map[string]int64
	ErrorsBySymbol        map[string]int64
	ActiveConnections     int
}

// NewManager creates a new subscription manager
func NewManager(cfg *config.Config) *Manager {
	ctx, cancel := context.WithCancel(context.Background())

	return &Manager{
		Config:      cfg,
		Clients:     make([]*ws.Client, 0, len(cfg.Assets)),
		MessageChan: make(chan interface{}, cfg.MessageBufferSize),
		ErrorChan:   make(chan error, cfg.MessageBufferSize),
		Ctx:         ctx,
		Cancel:      cancel,
		Statistics: &Statistics{
			MessagesBySymbol: make(map[string]int64),
			ErrorsBySymbol:   make(map[string]int64),
		},
	}
}

// Start starts all subscriptions
func (m *Manager) Start() {
	log.Printf("Starting subscription manager with %d assets...", len(m.Config.Assets))

	for _, asset := range m.Config.Assets {
		client := ws.NewClient(
			asset.Symbol,
			m.Config.WebSocketURL,
			m.MessageChan,
			m.ErrorChan,
			m.Config.ReconnectIntervals,
			m.Config.Debug,
		)

		m.Clients = append(m.Clients, client)

		m.Wg.Add(1)
		go m.runClient(client)
	}

	// Start statistics collector
	m.Wg.Add(1)
	go m.collectStatistics()

	log.Printf("All %d subscriptions started", len(m.Config.Assets))
}

// runClient runs a single client and handles its lifecycle
func (m *Manager) runClient(client *ws.Client) {
	defer m.Wg.Done()

	// Connect the client (this blocks until the client stops)
	client.Connect()

	// Connect() now blocks until Stop() is called, so when we reach here
	// the client is done.
}

// collectStatistics periodically logs statistics
func (m *Manager) collectStatistics() {
	defer m.Wg.Done()

	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-m.Ctx.Done():
			return
		case <-ticker.C:
			m.logStatistics()
		}
	}
}

// logStatistics logs current statistics
func (m *Manager) logStatistics() {
	m.StatisticsMutex.Lock()
	defer m.StatisticsMutex.Unlock()

	log.Printf("=== Statistics ===")
	log.Printf("Total messages: %d", m.Statistics.TotalMessagesReceived)
	log.Printf("Active connections: %d", m.Statistics.ActiveConnections)

	if m.Config.Debug {
		for symbol, count := range m.Statistics.MessagesBySymbol {
			log.Printf(" %s: %d messages", symbol, count)
		}
		for symbol, count := range m.Statistics.ErrorsBySymbol {
			if count > 0 {
				log.Printf(" %s: %d errors", symbol, count)
			}
		}
	}
}

// IncrementMessages increments the message count for a symbol
func (m *Manager) IncrementMessages(symbol string) {
	m.StatisticsMutex.Lock()
	defer m.StatisticsMutex.Unlock()
	m.Statistics.TotalMessagesReceived++
	m.Statistics.MessagesBySymbol[symbol]++
}

// IncrementErrors increments the error count for a symbol
func (m *Manager) IncrementErrors(symbol string) {
	m.StatisticsMutex.Lock()
	defer m.StatisticsMutex.Unlock()
	m.Statistics.ErrorsBySymbol[symbol]++
}

// SetActiveConnections sets the active connection count
func (m *Manager) SetActiveConnections(count int) {
	m.StatisticsMutex.Lock()
	defer m.StatisticsMutex.Unlock()
	m.Statistics.ActiveConnections = count
}

// Stop stops all subscriptions and waits for cleanup
func (m *Manager) Stop() {
	log.Println("Stopping subscription manager...")

	// Stop all clients first
	for _, client := range m.Clients {
		client.Stop()
	}

	// Cancel context to signal statistics collector
	m.Cancel()

	// Wait for all goroutines to finish
	m.Wg.Wait()

	// Close channels
	close(m.MessageChan)
	close(m.ErrorChan)

	log.Println("All subscriptions stopped")
}

// GetStatistics returns current statistics
func (m *Manager) GetStatistics() *Statistics {
	m.StatisticsMutex.Lock()
	defer m.StatisticsMutex.Unlock()

	// Create a copy
	stats := &Statistics{
		TotalMessagesReceived: m.Statistics.TotalMessagesReceived,
		MessagesBySymbol:      make(map[string]int64),
		ErrorsBySymbol:        make(map[string]int64),
		ActiveConnections:     m.Statistics.ActiveConnections,
	}

	for k, v := range m.Statistics.MessagesBySymbol {
		stats.MessagesBySymbol[k] = v
	}
	for k, v := range m.Statistics.ErrorsBySymbol {
		stats.ErrorsBySymbol[k] = v
	}

	return stats
}
