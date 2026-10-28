// Package config holds application configuration for the Bybit WebSocket subscriber
package config

// Asset represents a trading pair to subscribe to
type Asset struct {
	Symbol string // e.g., "BTCUSDT", "ETHUSDT"
}

// Config holds all application configuration
type Config struct {
	// Assets to subscribe to (25 separate connections)
	Assets []Asset
	// Bybit WebSocket endpoint
	WebSocketURL string
	// Reconnection settings
	ReconnectIntervals []int // exponential backoff in milliseconds: [1000, 2000, 5000, 10000]
	MaxReconnectAttempts int
	// Buffer sizes
	MessageBufferSize int
	// Debug mode
	Debug bool
}

// DefaultConfig returns a default configuration with sample assets
func DefaultConfig() *Config {
	return &Config{
		Assets: []Asset{
			{Symbol: "BTCUSDT"},
			{Symbol: "ETHUSDT"},
			{Symbol: "SOLUSDT"},
			{Symbol: "XRPUSDT"},
			{Symbol: "ADAUSDT"},
			{Symbol: "DOGEUSDT"},
			{Symbol: "DOTUSDT"},
			{Symbol: "AVAXUSDT"},
			{Symbol: "SHIBUSDT"},
			{Symbol: "POLUSDT"},
			{Symbol: "LTCUSDT"},
			{Symbol: "BCHUSDT"},
			{Symbol: "UNIUSDT"},
			{Symbol: "LINKUSDT"},
			{Symbol: "ATOMUSDT"},
			{Symbol: "XLMUSDT"},
			{Symbol: "ALGOUSDT"},
			{Symbol: "VETUSDT"},
			{Symbol: "TRXUSDT"},
			{Symbol: "FILUSDT"},
			{Symbol: "THETAUSDT"},
			{Symbol: "EOSUSDT"},
			{Symbol: "XTZUSDT"},
			{Symbol: "KSMUSDT"},
			{Symbol: "FLOWUSDT"},
		},
		WebSocketURL:      "wss://stream.bybit.com/v5/public/linear",
		ReconnectIntervals: []int{1000, 2000, 5000, 10000, 30000},
		MaxReconnectAttempts: 10,
		MessageBufferSize:   1000,
		Debug:              false,
	}
}

// LoadConfig creates and validates configuration
func LoadConfig() *Config {
	cfg := DefaultConfig()
	// Add validation if needed
	return cfg
}
