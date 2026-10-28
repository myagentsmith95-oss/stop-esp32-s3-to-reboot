// Package ws provides WebSocket client functionality for Bybit
package ws

import (
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

// Message types from Bybit WebSocket API
type MessageType string

const (
	MessageTypeOrderbook MessageType = "orderbook.50"
	MessageTypeTicker    MessageType = "tickers"
	MessageTypeTrade     MessageType = "publicTrade"
)

// pongResponse is the response to a Bybit ping
type pongResponse struct {
	Op   string `json:"op"`
	Args []int  `json:"args"`
}

// SubscriptionRequest represents a Bybit WebSocket subscription request
type SubscriptionRequest struct {
	Op   string   `json:"op"`
	Args []string `json:"args"`
}

// OrderbookUpdate represents an orderbook update message from Bybit
type OrderbookUpdate struct {
	Topic string `json:"topic"`
	Type  string `json:"type"`
	Data  struct {
		Symbol string     `json:"s"`
		Bids   [][]string `json:"b"`
		Asks   [][]string `json:"a"`
		TS     int64      `json:"ts"`
		U      int64      `json:"u"`
	} `json:"data"`
	TS int64 `json:"ts"`
}

// TickerUpdate represents a ticker update message from Bybit
type TickerUpdate struct {
	Topic string `json:"topic"`
	Type  string `json:"type"`
	Data  struct {
		Symbol      string `json:"symbol"`
		LastPrice   string `json:"lastPrice"`
		Volume24h   string `json:"volume24h"`
		Turnover24h string `json:"turnover24h"`
		TS          int64  `json:"ts"`
	} `json:"data"`
	TS int64 `json:"ts"`
}

// TradeUpdate represents a public trade message from Bybit
type TradeUpdate struct {
	Topic string `json:"topic"`
	Type  string `json:"type"`
	Data  []struct {
		Symbol string `json:"s"`
		Price  string `json:"p"`
		Size   string `json:"v"`
		Side   string `json:"S"`
		TS     int64  `json:"T"`
	} `json:"data"`
	TS int64 `json:"ts"`
}

// messageWrapper is used only internally to detect the topic before full parsing
type messageWrapper struct {
	Topic string `json:"topic"`
	Op    string `json:"op"`
}

// Client represents a WebSocket client for a single asset.
// It handles connection, subscription, and message processing.
type Client struct {
	Symbol             string
	URL                string
	conn               *websocket.Conn
	MessageChan        chan<- interface{}
	ErrorChan          chan<- error
	ReconnectIntervals []int
	Debug              bool
	stopChan           chan struct{}
	doneChan           chan struct{} // closed when the run goroutine exits
}

// NewClient creates a new WebSocket client for a specific asset
func NewClient(symbol, url string, messageChan chan<- interface{}, errorChan chan<- error, reconnectIntervals []int, debug bool) *Client {
	return &Client{
		Symbol:             symbol,
		URL:                url,
		MessageChan:        messageChan,
		ErrorChan:          errorChan,
		ReconnectIntervals: reconnectIntervals,
		Debug:              debug,
		stopChan:           make(chan struct{}),
		doneChan:           make(chan struct{}),
	}
}

// Connect starts the client and blocks until Stop() is called.
// This is the main entry point -- callers should run it in a goroutine
// if they need non-blocking behavior.
func (c *Client) Connect() {
	c.run()
}

// run handles the main client loop with reconnection.
// It blocks until Stop() is called.
func (c *Client) run() {
	defer close(c.doneChan)

	for {
		select {
		case <-c.stopChan:
			return
		default:
		}

		err := c.connectAndSubscribe()
		if err != nil {
			c.ErrorChan <- fmt.Errorf("symbol=%s: %w", c.Symbol, err)
		}

		// Check if we were told to stop before reconnecting
		select {
		case <-c.stopChan:
			return
		default:
		}

		// Apply exponential backoff before reconnecting
		if !c.backoff() {
			// Stop was requested during backoff
			return
		}
	}
}

// connectAndSubscribe establishes connection and subscribes to the asset.
// Returns nil when the connection drops normally, or an error on failure.
// Blocks until the connection is closed or Stop() is called.
func (c *Client) connectAndSubscribe() error {
	var dialer websocket.Dialer

	conn, _, err := dialer.Dial(c.URL, nil)
	if err != nil {
		return fmt.Errorf("dial failed: %w", err)
	}

	c.conn = conn

	// Set a read deadline so ReadMessage doesn't block forever.
	// Bybit sends ping every ~20s, so 35s is a safe upper bound.
	conn.SetReadDeadline(time.Now().Add(35 * time.Second))

	// Subscribe to orderbook and ticker
	subscription := SubscriptionRequest{
		Op: "subscribe",
		Args: []string{
			fmt.Sprintf("orderbook.50.%s", c.Symbol),
			fmt.Sprintf("tickers.%s", c.Symbol),
		},
	}

	subBytes, err := json.Marshal(subscription)
	if err != nil {
		c.closeConn()
		return fmt.Errorf("failed to marshal subscription: %w", err)
	}

	if c.Debug {
		log.Printf("symbol=%s: sending subscription: %s", c.Symbol, string(subBytes))
	}

	err = conn.WriteMessage(websocket.TextMessage, subBytes)
	if err != nil {
		c.closeConn()
		return fmt.Errorf("failed to send subscription: %w", err)
	}

	// Read messages until disconnect or stop
	c.readMessages()
	return nil
}

// readMessages reads messages from the WebSocket connection.
// Returns when the connection drops or Stop() is called.
func (c *Client) readMessages() {
	for {
		select {
		case <-c.stopChan:
			c.closeConn()
			return
		default:
		}

		// Reset read deadline before each read; the ping handler
		// will also reset it when a pong is received.
		c.conn.SetReadDeadline(time.Now().Add(35 * time.Second))

		_, message, err := c.conn.ReadMessage()
		if err != nil {
			// Check if stop was requested
			select {
			case <-c.stopChan:
				c.closeConn()
				return
			default:
			}
			// Connection error -- will reconnect
			if c.Debug {
				log.Printf("symbol=%s: read error: %v", c.Symbol, err)
			}
			c.closeConn()
			return
		}

		c.processMessage(message)
	}
}

// processMessage parses and forwards messages to the message channel.
// Uses topic-prefix routing instead of blind unmarshalling.
func (c *Client) processMessage(message []byte) {
	if c.Debug {
		log.Printf("symbol=%s: received: %s", c.Symbol, string(message))
	}

	// First, detect the topic or op to route the message
	var wrapper messageWrapper
	if err := json.Unmarshal(message, &wrapper); err != nil {
		if c.Debug {
			log.Printf("symbol=%s: failed to parse message wrapper: %v", c.Symbol, err)
		}
		return
	}

	// Handle ping -- Bybit sends {"op":"ping"} and expects {"op":"pong"}
	if wrapper.Op == "ping" {
		pong, _ := json.Marshal(pongResponse{Op: "pong", Args: []int{int(time.Now().UnixMilli())}})
		err := c.conn.WriteMessage(websocket.TextMessage, pong)
		if err != nil {
			if c.Debug {
				log.Printf("symbol=%s: failed to send pong: %v", c.Symbol, err)
			}
		} else if c.Debug {
			log.Printf("symbol=%s: sent pong", c.Symbol)
		}
		// Reset read deadline since we know the server is alive
		c.conn.SetReadDeadline(time.Now().Add(35 * time.Second))
		return
	}

	// Route based on topic prefix
	switch {
	case strings.HasPrefix(wrapper.Topic, string(MessageTypeOrderbook)):
		var orderbook OrderbookUpdate
		if err := json.Unmarshal(message, &orderbook); err != nil {
			if c.Debug {
				log.Printf("symbol=%s: failed to parse orderbook: %v", c.Symbol, err)
			}
			return
		}
		c.MessageChan <- orderbook

	case strings.HasPrefix(wrapper.Topic, string(MessageTypeTicker)):
		var ticker TickerUpdate
		if err := json.Unmarshal(message, &ticker); err != nil {
			if c.Debug {
				log.Printf("symbol=%s: failed to parse ticker: %v", c.Symbol, err)
			}
			return
		}
		c.MessageChan <- ticker

	case strings.HasPrefix(wrapper.Topic, string(MessageTypeTrade)):
		var trade TradeUpdate
		if err := json.Unmarshal(message, &trade); err != nil {
			if c.Debug {
				log.Printf("symbol=%s: failed to parse trade: %v", c.Symbol, err)
			}
			return
		}
		c.MessageChan <- trade

	default:
		if c.Debug {
			log.Printf("symbol=%s: unhandled message (topic=%q op=%q): %s",
				c.Symbol, wrapper.Topic, wrapper.Op, string(message))
		}
	}
}

// backoff applies exponential backoff with cancellation.
// Returns true if we should proceed to reconnect, false if Stop was requested.
func (c *Client) backoff() bool {
	intervals := c.ReconnectIntervals
	if len(intervals) == 0 {
		intervals = []int{1000, 2000, 5000, 10000, 30000}
	}

	for i, interval := range intervals {
		select {
		case <-c.stopChan:
			return false
		case <-time.After(time.Duration(interval) * time.Millisecond):
			// Waited the backoff interval, continue to next or reconnect
		}

		// After the last interval, proceed to reconnect
		if i == len(intervals)-1 {
			return true
		}
	}

	return true
}

// closeConn safely closes the underlying WebSocket connection
func (c *Client) closeConn() {
	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
}

// Stop stops the client and unblocks any pending reads.
// It is safe to call Stop() multiple times.
func (c *Client) Stop() {
	select {
	case <-c.stopChan:
		// Already closed
		return
	default:
		close(c.stopChan)
	}

	// Close the connection to unblock any pending ReadMessage call
	c.closeConn()

	// Wait for the run goroutine to exit
	<-c.doneChan
}
