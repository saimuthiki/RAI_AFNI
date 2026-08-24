package guardrails

import "math"

// roundConfidence limits confidence score to 2 decimal places
func roundConfidence(v float64) float64 {
	return math.Round(v*100) / 100
}
