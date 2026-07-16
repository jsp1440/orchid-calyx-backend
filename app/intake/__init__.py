"""BUILD-070 knowledge intake pipeline.

Routers are imported explicitly from ``app.intake.routes`` by the application so
standalone extraction and validation do not initialize database dependencies.
"""
