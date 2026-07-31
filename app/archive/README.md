# Institutional Archive Manager

This package implements BUILD-080. Import and resume mutations are authenticated. Read APIs expose operational and registry data. The package owns archive-local storage only and must not write directly to canonical Knowledge Graph tables.

Default checkpoint interval: 100 files.

Supported extraction: PDF, DOCX, Markdown, text, HTML, CSV, JSON and YAML. Image OCR is provider-based and remains inactive until configured.
