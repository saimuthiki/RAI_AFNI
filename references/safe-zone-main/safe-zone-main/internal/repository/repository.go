package repository

import (
	"log"
	"thyris-sz/internal/cache"
	"thyris-sz/internal/database"
	"thyris-sz/internal/models"
)

// GetActivePatterns retrieves all active regex patterns with caching
func GetActivePatterns() ([]models.Pattern, error) {
	// Try cache first
	patterns, err := cache.GetPatterns()
	if err == nil && len(patterns) > 0 {
		return patterns, nil
	}

	// Fallback to DB
	result := database.DB.Where("is_active = ?", true).Find(&patterns)
	if result.Error != nil {
		return nil, result.Error
	}

	// Update cache
	if err := cache.SetPatterns(patterns); err != nil {
		log.Printf("Failed to cache patterns: %v", err)
	}

	return patterns, nil
}

// CountActivePatterns counts the number of active patterns (direct DB query for init)
func CountActivePatterns() (int64, error) {
	var count int64
	result := database.DB.Model(&models.Pattern{}).Where("is_active = ?", true).Count(&count)
	return count, result.Error
}

// RefreshPatternsCache forces a reload of patterns from DB to Cache
func RefreshPatternsCache() error {
	var patterns []models.Pattern
	result := database.DB.Where("is_active = ?", true).Find(&patterns)
	if result.Error != nil {
		return result.Error
	}

	if err := cache.SetPatterns(patterns); err != nil {
		log.Printf("Failed to cache patterns during refresh: %v", err)
		return err
	}
	return nil
}

// GetAllowlistMap retrieves all allowlist items with caching
func GetAllowlistMap() (map[string]bool, error) {
	// Try cache first
	allowlistMap, err := cache.GetAllowlist()
	if err == nil && len(allowlistMap) > 0 {
		return allowlistMap, nil
	}

	var items []models.AllowlistItem
	result := database.DB.Find(&items)
	if result.Error != nil {
		return nil, result.Error
	}

	allowlistMap = make(map[string]bool)
	for _, item := range items {
		allowlistMap[item.Value] = true
	}

	// Update cache
	if err := cache.SetAllowlist(allowlistMap); err != nil {
		log.Printf("Failed to cache allowlist: %v", err)
	}

	return allowlistMap, nil
}

// GetBlocklistMap retrieves all blocklist items with caching
func GetBlocklistMap() (map[string]bool, error) {
	// Try cache first
	blocklistMap, err := cache.GetBlocklist()
	if err == nil && len(blocklistMap) > 0 {
		return blocklistMap, nil
	}

	var items []models.BlacklistItem
	result := database.DB.Find(&items)
	if result.Error != nil {
		return nil, result.Error
	}

	blocklistMap = make(map[string]bool)
	for _, item := range items {
		blocklistMap[item.Value] = true
	}

	// Update cache
	if err := cache.SetBlocklist(blocklistMap); err != nil {
		log.Printf("Failed to cache blocklist: %v", err)
	}

	return blocklistMap, nil
}

// GetPatternByID retrieves a pattern by its primary key ID
func GetPatternByID(id uint) (*models.Pattern, error) {
	var pattern models.Pattern
	result := database.DB.First(&pattern, id)
	if result.Error != nil {
		return nil, result.Error
	}
	return &pattern, nil
}

// UpdatePattern persists updates to an existing pattern
func UpdatePattern(pattern *models.Pattern) error {
	return database.DB.Save(pattern).Error
}
