-- ===============================================
-- HAWK SIGHT AI - MYSQL DATABASE SCHEMA
-- For use with XAMPP / phpMyAdmin
-- ===============================================
--
-- HOW TO USE:
-- 1. Start XAMPP, launch Apache + MySQL
-- 2. Open http://localhost/phpmyadmin
-- 3. Click "New" in the left sidebar → create database "hawk_sight"
--    (or just run the CREATE DATABASE below)
-- 4. Select hawk_sight database → click "Import" tab → upload this file
-- 5. Or paste this whole file into the SQL tab and click "Go"
-- ===============================================

CREATE DATABASE IF NOT EXISTS hawk_sight
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE hawk_sight;

-- -----------------------------------------------
-- Users table
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    balance DECIMAL(15, 2) DEFAULT 100000.00,
    auto_buy_enabled BOOLEAN DEFAULT FALSE,
    -- Emergency stop. Persisted (not in-memory) so it survives a server restart.
    kill_switch_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email (email)
) ENGINE=InnoDB;

-- Upgrading an EXISTING database (table already created before this column
-- existed)? The server auto-applies this on startup, but you can also run it
-- by hand. MySQL 8 has no "ADD COLUMN IF NOT EXISTS", so ignore error 1060
-- ("Duplicate column name") if it's already there:
-- ALTER TABLE users ADD COLUMN kill_switch_active BOOLEAN DEFAULT FALSE;

-- -----------------------------------------------
-- Portfolio (current holdings)
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    shares INT NOT NULL,
    avg_price DECIMAL(15, 4) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_symbol (user_id, symbol),
    INDEX idx_user (user_id)
) ENGINE=InnoDB;

-- -----------------------------------------------
-- Favorites (stocks user marked for auto-buy pool)
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS favorites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY unique_fav (user_id, symbol),
    INDEX idx_user (user_id)
) ENGINE=InnoDB;

-- -----------------------------------------------
-- Transaction log (audit trail of every buy/sell)
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    action ENUM('BUY', 'SELL') NOT NULL,
    shares INT NOT NULL,
    price DECIMAL(15, 4) NOT NULL,
    total_amount DECIMAL(15, 2) NOT NULL,
    is_auto BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_time (user_id, timestamp),
    INDEX idx_symbol_time (symbol, timestamp)
) ENGINE=InnoDB;

-- -----------------------------------------------
-- Auto-buy decision log (why the AI did what it did)
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS autobuy_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    predicted_return DECIMAL(8, 4),
    confidence DECIMAL(5, 4),
    volatility DECIMAL(8, 4),
    score DECIMAL(10, 6),
    action_taken VARCHAR(50),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_time (user_id, timestamp)
) ENGINE=InnoDB;

-- ===============================================
-- DONE. Verify with:
-- SHOW TABLES;
-- ===============================================
