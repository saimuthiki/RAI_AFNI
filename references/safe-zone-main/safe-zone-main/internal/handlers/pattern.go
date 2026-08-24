package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"
	"thyris-sz/internal/cache"
	"thyris-sz/internal/database"
	"thyris-sz/internal/models"
)

func CreatePattern(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var pattern models.Pattern
	if err := json.NewDecoder(r.Body).Decode(&pattern); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if result := database.DB.Create(&pattern); result.Error != nil {
		http.Error(w, result.Error.Error(), http.StatusInternalServerError)
		return
	}

	// Invalidate cache
	cache.ClearCache(cache.KeyPatterns)

	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(pattern)
}

func ListPatterns(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var patterns []models.Pattern
	if result := database.DB.Find(&patterns); result.Error != nil {
		http.Error(w, result.Error.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(patterns)
}

func DeletePattern(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodDelete {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil {
		http.Error(w, "Invalid ID", http.StatusBadRequest)
		return
	}

	if result := database.DB.Delete(&models.Pattern{}, id); result.Error != nil {
		http.Error(w, result.Error.Error(), http.StatusInternalServerError)
		return
	}

	// Invalidate cache
	cache.ClearCache(cache.KeyPatterns)

	w.WriteHeader(http.StatusNoContent)
}
