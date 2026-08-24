package database

import (
	"log"
	"thyris-sz/internal/config"
	"thyris-sz/internal/models"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

var DB *gorm.DB

func InitDB() {
	dsn := config.GetDSN()

	var err error
	DB, err = gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}

	log.Println("Database connection established")

	// Auto Migrate
	log.Println("Running AutoMigrate...")
	err = DB.AutoMigrate(
		&models.Pattern{},
		&models.AllowlistItem{},
		&models.BlacklistItem{},
		&models.FormatValidator{},
	)
	if err != nil {
		// Log error but don't crash. This can happen during constraint updates.
		log.Printf("Warning: Database migration encountered an error (check constraints): %v", err)
	} else {
		log.Println("Database migration completed")
	}
}
