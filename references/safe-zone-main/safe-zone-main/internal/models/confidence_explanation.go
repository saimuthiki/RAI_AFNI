package models

// ConfidenceExplanation explains how a confidence score was produced
type ConfidenceExplanation struct {
	Source   string `json:"source"`
	Category string `json:"category,omitempty"`

	// Raw signals
	RegexScore    Confidence `json:"regex_score,omitempty"`
	AIScore       Confidence `json:"ai_score,omitempty"`
	RegexHitCount int        `json:"regex_hit_count,omitempty"`
	PatternActive bool       `json:"pattern_active,omitempty"`

	// Policy resolution
	BlockThreshold  *float64 `json:"block_threshold,omitempty"`
	AllowThreshold  *float64 `json:"allow_threshold,omitempty"`
	ThresholdSource string   `json:"threshold_source,omitempty"` // PATTERN / ENV / DEFAULT

	// Fusion
	HybridApplied bool       `json:"hybrid_applied"`
	FinalScore    Confidence `json:"final_score"`
}
