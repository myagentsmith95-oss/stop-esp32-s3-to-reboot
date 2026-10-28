// Package ws provides WebSocket client functionality for Bybit
// This file contains ancillary message types for Bybit WebSocket API.

package ws

// SubscriptionConfirmation represents a successful subscription response
type SubscriptionConfirmation struct {
	Success bool     `json:"success"`
	RetMsg  string   `json:"ret_msg"`
	ConnID  string   `json:"conn_id"`
	ReqID   string   `json:"req_id,omitempty"`
	Op      string   `json:"op,omitempty"`
	Topics  []string `json:"topics,omitempty"`
}

// ErrorResponse represents an error message from Bybit
type ErrorResponse struct {
	Success bool   `json:"success"`
	RetMsg  string `json:"ret_msg"`
	ConnID  string `json:"conn_id,omitempty"`
	ReqID   string `json:"req_id,omitempty"`
	Op      string `json:"op,omitempty"`
}
