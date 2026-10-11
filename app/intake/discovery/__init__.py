"""Native Global Intelligence Discovery for the Calyx intelligence ledger.

Discovery pulls bounded, incremental metadata from free scholarly registries,
normalizes it deterministically, deduplicates it against the existing
``oc_intake.intelligence_items`` ledger, and leaves verification, comparison,
routing and every canonical/scientific promotion to the existing governed
stages.  It never contacts external parties, never publishes to canonical
stores, and never treats registry metadata as proof of a scientific claim.
"""

DISCOVERY_VERSION = "oc.native-discovery.v1"
