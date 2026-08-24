package guardrails

import (
	"os"
	"strconv"
)

func getAllowThreshold() float64 {
	if v := os.Getenv("CONFIDENCE_ALLOW_THRESHOLD"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return 0.30
}

func getBlockThreshold() float64 {
	if v := os.Getenv("CONFIDENCE_BLOCK_THRESHOLD"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return 0.85
}

// Enterprise: category based threshold resolver
func GetCategoryThreshold(category string) float64 {
	key := "CONFIDENCE_" + category + "_THRESHOLD"
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}

	// fallback to global block threshold
	return getBlockThreshold()
}
