package guardrails

import (
	"crypto/rand"
	"encoding/hex"
)

func generatePlaceholder(patternName, rid string) string {
	// Always generate a unique ID for the placeholder
	randomID := generateRandomString(16)

	if rid != "" {
		// Format: [RID]_[PATTERN_NAME]_[RANDOM_ID]
		return "[" + rid + "_" + patternName + "_" + randomID + "]"
	}

	// Format: [PATTERN_NAME]_[RANDOM_ID]
	return "[" + patternName + "_" + randomID + "]"
}

func generateRandomString(length int) string {
	bytes := make([]byte, length/2)
	if _, err := rand.Read(bytes); err != nil {
		return "randomid"
	}
	return hex.EncodeToString(bytes)
}

// ApplyRegexHitWeight increases confidence based on number of regex hits
func ApplyRegexHitWeight(base float64, hits int) float64 {
	if hits <= 1 {
		return base
	}

	var multiplier float64
	switch {
	case hits == 2:
		multiplier = 1.10
	case hits == 3:
		multiplier = 1.20
	default:
		multiplier = 1.30
	}

	score := base * multiplier
	if score > 1 {
		return 1
	}
	return score
}
