package ai

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"thyris-sz/internal/config"
	"time"
)

// HybridConfidence combines REGEX + AI confidence in enterprise-safe way
func HybridConfidence(regexScore float64, aiScore float64) float64 {
	// Enterprise fusion: weighted, but never below strongest signal
	weighted := (regexScore * 0.45) + (aiScore * 0.55)

	if aiScore > weighted {
		return aiScore
	}
	if regexScore > weighted {
		return regexScore
	}
	return weighted
}

// ConfidenceWithAI asks the model to return a FLOAT confidence between 0 and 1
func ConfidenceWithAI(text string, label string) (float64, error) {
	prompt := "You are a data protection classifier. Return ONLY a number between 0 and 1.\n" +
		"How confident are you that the following text span is a " + label + "?\n" +
		"Text: " + text

	body, _ := json.Marshal(map[string]interface{}{
		"model": config.AppConfig.AIModelName,
		"messages": []map[string]string{{
			"role":    "user",
			"content": prompt,
		}},
		"stream": false,
	})

	url := config.AppConfig.AIModelURL + "/chat/completions"
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+config.AppConfig.AIAPIKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		log.Printf("AI confidence error: %s", string(b))
		return 0, errors.New("ai confidence call failed")
	}

	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if len(out.Choices) == 0 {
		return 0, errors.New("empty AI confidence")
	}

	v := strings.TrimSpace(out.Choices[0].Message.Content)
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return 0, err
	}

	if f < 0 {
		return 0, nil
	}
	if f > 1 {
		return 1, nil
	}
	// cache result for 24h
	SetCachedConfidence(label, text, f, 24*time.Hour)
	return f, nil
}
