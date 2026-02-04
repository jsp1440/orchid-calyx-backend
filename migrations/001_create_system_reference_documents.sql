-- Migration: Create system_reference_documents table
-- Version: 001
-- Date: 2026-02-04

CREATE TABLE IF NOT EXISTS system_reference_documents (
    id VARCHAR(36) PRIMARY KEY,
    document_type VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    version_label VARCHAR(50) NOT NULL,
    source_org VARCHAR(100) DEFAULT 'AOS',
    source_url VARCHAR(500),
    file_path VARCHAR(500) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_srd_document_type ON system_reference_documents(document_type);
CREATE INDEX IF NOT EXISTS idx_srd_is_active ON system_reference_documents(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_srd_sha256_type_version ON system_reference_documents(sha256, document_type, version_label);
