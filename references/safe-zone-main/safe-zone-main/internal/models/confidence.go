package models

import (
	"fmt"
)

// Confidence is a float64 serialized with exactly 2 decimal places
type Confidence float64

func (c Confidence) MarshalJSON() ([]byte, error) {
	return []byte(fmt.Sprintf("\"%.2f\"", float64(c))), nil
}
