package repository

import (
	"thyris-sz/internal/database"
	"thyris-sz/internal/models"
)

// GetValidatorByName retrieves a validator by its name
func GetValidatorByName(name string) (*models.FormatValidator, error) {
	var validator models.FormatValidator
	result := database.DB.Where("name = ?", name).First(&validator)
	if result.Error != nil {
		return nil, result.Error
	}
	return &validator, nil
}

// CreateFormatValidator adds a new validator to the database
func CreateFormatValidator(validator *models.FormatValidator) error {
	return database.DB.Create(validator).Error
}

// ListFormatValidators retrieves all validators
func ListFormatValidators() ([]models.FormatValidator, error) {
	var validators []models.FormatValidator
	result := database.DB.Find(&validators)
	return validators, result.Error
}

// DeleteFormatValidator deletes a validator by ID
func DeleteFormatValidator(id uint) error {
	return database.DB.Delete(&models.FormatValidator{}, id).Error
}
