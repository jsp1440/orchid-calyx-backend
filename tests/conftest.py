import os

# Vendored harvesters.gbif_api raises at import when DATABASE_URL is unset, and
# state_helper builds a connection string from it. Offline tests never connect;
# a dummy URL keeps imports clean without any real database.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
