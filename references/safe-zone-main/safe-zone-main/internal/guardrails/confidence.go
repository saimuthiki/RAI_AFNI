package guardrails

// ConfidenceContext holds explainable signals used for scoring
type ConfidenceContext struct {
	PatternCategory string
	PatternActive   bool
	AllowlistHit    bool
	BlacklistHit    bool
	Source          string // REGEX, AI, SCHEMA
}

// ComputeConfidence returns deterministic, enterprise-grade confidence score (0-1)
// ComputeConfidence computes heuristic confidence. For PII, prefer HybridConfidence.
func ComputeConfidence(ctx ConfidenceContext) float64 {
	// Hard blocks are absolute
	if ctx.BlacklistHit {
		return 1.0
	}

	// Allowlist strongly reduces confidence
	if ctx.AllowlistHit {
		return 0.1
	}

	score := 0.0

	// 1. Source reliability (primary signal)
	switch ctx.Source {
	case "AI":
		score += 0.4
	case "SCHEMA":
		score += 0.3
	case "REGEX":
		score += 0.2
	default:
		score += 0.1
	}

	// 2. Domain / category impact
	switch ctx.PatternCategory {
	case "SECRET":
		score += 0.35
	case "PII":
		score += 0.25
	case "INJECTION":
		score += 0.3
	default:
		score += 0.1
	}

	// 3. Pattern maturity signal
	if ctx.PatternActive {
		score += 0.1

		// Enterprise: active regex patterns get slight reliability boost
		if ctx.Source == "REGEX" {
			score += 0.05
		}
	} else {
		score -= 0.2
	}

	// Clamp to [0,1]
	if score < 0 {
		return 0
	}
	if score > 1 {
		return 1
	}

	return score
}
