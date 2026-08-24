package models

// SecurityEvent represents an auditable security decision/event
// Suitable for SIEM / webhook / audit log export
type SecurityEvent struct {
	Type            string  `json:"type"`     // BLOCK, MASK, ALLOW
	Category        string  `json:"category"` // PII, SECRET, etc.
	Pattern         string  `json:"pattern"`  // pattern name
	ConfidenceScore float64 `json:"confidence_score"`
	Threshold       float64 `json:"threshold"`
	Action          string  `json:"action"`
	RequestID       string  `json:"request_id,omitempty"`
	Timestamp       int64   `json:"timestamp"`
}
