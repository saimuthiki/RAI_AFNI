package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"
	"thyris-sz/internal/models"
	"thyris-sz/internal/repository"
)

// CreateValidator handles the creation of a new format validator
func CreateValidator(w http.ResponseWriter, r *http.Request) {
	var validator models.FormatValidator
	if err := json.NewDecoder(r.Body).Decode(&validator); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if err := repository.CreateFormatValidator(&validator); err != nil {
		http.Error(w, "Failed to create validator: "+err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(validator)
}

// ListValidators returns all format validators
func ListValidators(w http.ResponseWriter, r *http.Request) {
	validators, err := repository.ListFormatValidators()
	if err != nil {
		http.Error(w, "Failed to list validators", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(validators)
}

// DeleteValidator removes a validator by ID
func DeleteValidator(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil {
		http.Error(w, "Invalid ID", http.StatusBadRequest)
		return
	}

	if err := repository.DeleteFormatValidator(uint(id)); err != nil {
		http.Error(w, "Failed to delete validator", http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}
