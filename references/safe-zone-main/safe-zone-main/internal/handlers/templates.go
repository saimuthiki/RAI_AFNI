package handlers

import (
	"encoding/json"
	"net/http"
	"thyris-sz/internal/database"
	"thyris-sz/internal/models"
	"thyris-sz/internal/repository"
)

// ImportTemplateRequest represents the payload for importing a template
type ImportTemplateRequest struct {
	Template models.GuardrailTemplate `json:"template"`
}

// ImportTemplateHandler allows importing a full set of guardrails (patterns + validators)
func ImportTemplateHandler(w http.ResponseWriter, r *http.Request) {
	var req ImportTemplateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	db := database.DB
	tx := db.Begin()

	// 1. Import Patterns
	for _, p := range req.Template.Patterns {
		// Check if pattern exists by name
		var existing models.Pattern
		if result := tx.Where("name = ?", p.Name).First(&existing); result.Error == nil {
			// Update existing
			existing.Regex = p.Regex
			existing.Description = p.Description
			existing.Category = p.Category
			existing.IsActive = p.IsActive
			tx.Save(&existing)
		} else {
			// Create new
			tx.Create(&p)
		}
	}

	// 2. Import Validators
	for _, v := range req.Template.Validators {
		// Check if validator exists
		var existing models.FormatValidator
		if result := tx.Where("name = ?", v.Name).First(&existing); result.Error == nil {
			// Update existing
			existing.Type = v.Type
			existing.Rule = v.Rule
			existing.Description = v.Description
			tx.Save(&existing)
		} else {
			// Create new
			tx.Create(&v)
		}
	}

	if err := tx.Commit().Error; err != nil {
		http.Error(w, "Failed to import template: "+err.Error(), http.StatusInternalServerError)
		return
	}

	// Force reload of patterns cache
	repository.RefreshPatternsCache()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Template imported successfully",
		"name":    req.Template.Name,
	})
}
