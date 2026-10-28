// Package data provides data aggregation and processing for market data
package data

import (
	"log"
	"sort"
	"sync"
)

// MarketData holds aggregated market data for an asset
type MarketData struct {
	Symbol       string
	LastPrice    string
	Volume24h    string
	Turnover24h  string
	BestBid      string
	BestAsk      string
	BidVolume    string
	AskVolume    string
	LastUpdateTS int64
}

// DataAggregator aggregates market data from multiple sources
type DataAggregator struct {
	Data      map[string]*MarketData
	DataMutex sync.RWMutex
	Debug     bool
}

// NewDataAggregator creates a new data aggregator
func NewDataAggregator(debug bool) *DataAggregator {
	return &DataAggregator{
		Data:  make(map[string]*MarketData),
		Debug: debug,
	}
}

// UpdateOrderbook updates orderbook data for an asset
func (da *DataAggregator) UpdateOrderbook(symbol, bestBid, bestAsk, bidVolume, askVolume string, ts int64) {
	da.DataMutex.Lock()
	defer da.DataMutex.Unlock()

	if _, exists := da.Data[symbol]; !exists {
		da.Data[symbol] = &MarketData{
			Symbol: symbol,
		}
	}

	data := da.Data[symbol]
	data.BestBid = bestBid
	data.BestAsk = bestAsk
	data.BidVolume = bidVolume
	data.AskVolume = askVolume
	data.LastUpdateTS = ts

	if da.Debug {
		log.Printf("Updated orderbook for %s: bid=%s/%s, ask=%s/%s",
			symbol, bestBid, bidVolume, bestAsk, askVolume)
	}
}

// UpdateTicker updates ticker data for an asset
func (da *DataAggregator) UpdateTicker(symbol, lastPrice, volume24h, turnover24h string, ts int64) {
	da.DataMutex.Lock()
	defer da.DataMutex.Unlock()

	if _, exists := da.Data[symbol]; !exists {
		da.Data[symbol] = &MarketData{
			Symbol: symbol,
		}
	}

	data := da.Data[symbol]
	data.LastPrice = lastPrice
	data.Volume24h = volume24h
	data.Turnover24h = turnover24h
	data.LastUpdateTS = ts

	if da.Debug {
		log.Printf("Updated ticker for %s: price=%s, vol=%s, turnover=%s",
			symbol, lastPrice, volume24h, turnover24h)
	}
}

// GetData returns market data for a specific asset
func (da *DataAggregator) GetData(symbol string) *MarketData {
	da.DataMutex.RLock()
	defer da.DataMutex.RUnlock()

	if data, exists := da.Data[symbol]; exists {
		// Return a copy to prevent race conditions
		return &MarketData{
			Symbol:       data.Symbol,
			LastPrice:    data.LastPrice,
			Volume24h:    data.Volume24h,
			Turnover24h:  data.Turnover24h,
			BestBid:      data.BestBid,
			BestAsk:      data.BestAsk,
			BidVolume:    data.BidVolume,
			AskVolume:    data.AskVolume,
			LastUpdateTS: data.LastUpdateTS,
		}
	}
	return nil
}

// GetAllData returns market data for all assets
func (da *DataAggregator) GetAllData() map[string]*MarketData {
	da.DataMutex.RLock()
	defer da.DataMutex.RUnlock()

	result := make(map[string]*MarketData)
	for symbol, data := range da.Data {
		result[symbol] = &MarketData{
			Symbol:       data.Symbol,
			LastPrice:    data.LastPrice,
			Volume24h:    data.Volume24h,
			Turnover24h:  data.Turnover24h,
			BestBid:      data.BestBid,
			BestAsk:      data.BestAsk,
			BidVolume:    data.BidVolume,
			AskVolume:    data.AskVolume,
			LastUpdateTS: data.LastUpdateTS,
		}
	}
	return result
}

// Symbols returns all symbol names being tracked, sorted alphabetically
func (da *DataAggregator) Symbols() []string {
	da.DataMutex.RLock()
	defer da.DataMutex.RUnlock()

	symbols := make([]string, 0, len(da.Data))
	for symbol := range da.Data {
		symbols = append(symbols, symbol)
	}
	sort.Strings(symbols)
	return symbols
}
