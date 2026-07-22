# harvesters/traitbank.py

import os
import csv
import gzip
import json
import time
import certifi
import requests

from .base import BaseHarvester

# Canonical EOL TraitBank dataset (gzipped TSV)
# This is what your logs show you were trying to hit.
DEFAULT_TRAITBANK_URL = "https://opendata.eol.org/dataset/eol-traitbank/resource/traitbank.tsv.gz"

# Local cache locations (harvester will prefer local if present)
DEFAULT_LOCAL_DIR = "data"
LOCAL_CANDIDATES = [
    "traitbank.tsv.gz",
    "traitbank.tsv",
    "traitbank.csv.gz",
    "traitbank.csv",
    "traitbank.jsonl.gz",
    "traitbank.jsonl",
]

class TraitBankHarvester(BaseHarvester):
    """
    TraitBank harvester:
      - Prefers local cached files under /data
      - If missing, can optionally download from EOL canonical URL
      - Parses TSV/CSV/JSONL (gz or plain)
      - Yields normalized records (still includes raw fields)
    """

    def __init__(self):
        super().__init__("TRAITBANK")

    # ----------------------------
    # Public API expected by pipeline
    # ----------------------------

    def harvest_metadata(self, limit=None, allow_download=True):
        """
        Returns a list of normalized trait records.
        """
        records = []
        for rec in self.iter_records(limit=limit, allow_download=allow_download):
            records.append(rec)
        return records

    def harvest_full(self, limit=None, persist_to_db=False, allow_download=True):
        """
        TraitBank full harvest == traits only (no images).
        persist_to_db is accepted for compatibility with orchestrators,
        but actual DB persistence should happen in your pipeline layer.
        """
        return {
            "metadata": self.harvest_metadata(limit=limit, allow_download=allow_download),
            "images": []
        }

    # ----------------------------
    # Core iteration + parsing
    # ----------------------------

    def iter_records(self, limit=None, allow_download=True):
        """
        Generator yielding normalized records.
        """
        local_path = self._find_local_file()

        if not local_path and allow_download:
            local_path = self._download_to_local_cache()

        if not local_path:
            raise RuntimeError(
                "TraitBank dataset not found locally and download disabled/failed.\n"
                "Expected one of:\n"
                f"  data/{', data/'.join(LOCAL_CANDIDATES)}\n"
                "Fix: run scripts/fetch_traitbank_from_eol.py (replacement provided) "
                "or place the downloaded file under /data."
            )

        parser = self._choose_parser(local_path)

        count = 0
        for raw in parser(local_path):
            norm = self._normalize(raw, source_path=local_path)

            # Skip obvious empties (your header-only stub case)
            if self._is_effectively_empty(norm):
                continue

            yield norm
            count += 1
            if limit and count >= limit:
                break

    # ----------------------------
    # Local file resolution
    # ----------------------------

    def _find_local_file(self):
        os.makedirs(DEFAULT_LOCAL_DIR, exist_ok=True)
        for fname in LOCAL_CANDIDATES:
            path = os.path.join(DEFAULT_LOCAL_DIR, fname)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        return None

    def _choose_parser(self, path):
        lower = path.lower()
        if lower.endswith(".jsonl") or lower.endswith(".jsonl.gz"):
            return self._parse_jsonl
        if lower.endswith(".tsv") or lower.endswith(".tsv.gz"):
            return self._parse_tsv
        if lower.endswith(".csv") or lower.endswith(".csv.gz"):
            return self._parse_csv
        # Fallback: try TSV
        return self._parse_tsv

    # ----------------------------
    # Download (EOL canonical)
    # ----------------------------

    def _download_to_local_cache(self):
        """
        Downloads the canonical EOL traitbank.tsv.gz to data/traitbank.tsv.gz
        Uses certifi bundle for SSL. If Replit SSL breaks, you may override via:
          OC_INSECURE_SSL=1  (NOT recommended, but pragmatic in some envs)
        """
        url = os.getenv("TRAITBANK_URL", DEFAULT_TRAITBANK_URL)
        out_path = os.path.join(DEFAULT_LOCAL_DIR, "traitbank.tsv.gz")

        # If already downloaded, reuse
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path

        insecure = os.getenv("OC_INSECURE_SSL", "").strip() == "1"
        verify = False if insecure else certifi.where()

        if insecure:
            print("[TraitBank] WARNING: OC_INSECURE_SSL=1 set. SSL verification is DISABLED.")

        print(f"[TraitBank] Downloading TraitBank dataset...")
        print(f"[TraitBank] URL: {url}")
        print(f"[TraitBank] Saving to: {out_path}")

        with requests.get(url, stream=True, timeout=600, verify=verify) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0") or "0")
            downloaded = 0
            t0 = time.time()

            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    # lightweight progress
                    if total > 0:
                        pct = (downloaded / total) * 100
                        if int(pct) % 10 == 0:
                            elapsed = max(time.time() - t0, 0.001)
                            mbps = (downloaded / (1024 * 1024)) / elapsed
                            print(f"[TraitBank] {pct:.0f}% ({downloaded/1024/1024:.1f} MB) @ {mbps:.1f} MB/s")

        if os.path.getsize(out_path) == 0:
            raise RuntimeError("TraitBank download completed but produced empty file.")

        return out_path

    # ----------------------------
    # Parsers
    # ----------------------------

    def _parse_tsv(self, path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                yield row

    def _parse_csv(self, path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter=",")
            for row in reader:
                yield row

    def _parse_jsonl(self, path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue

    # ----------------------------
    # Normalization
    # ----------------------------

    def _normalize(self, raw, source_path):
        """
        Normalizes *common* TraitBank fields without assuming a single schema.
        Keeps raw fields so you can later map to your Trait Definition Registry.
        """
        if isinstance(raw, dict):
            # Try common keys from TraitBank-like exports
            sci = raw.get("scientificName") or raw.get("scientific_name") or raw.get("taxon") or raw.get("species") or ""
            trait = raw.get("trait") or raw.get("predicate") or raw.get("measurementType") or raw.get("attribute") or ""
            val = raw.get("value") or raw.get("measurementValue") or raw.get("object") or raw.get("val") or ""
            units = raw.get("units") or raw.get("measurementUnit") or ""
            source_url = raw.get("source") or raw.get("source_url") or raw.get("reference") or raw.get("citation") or ""
        else:
            sci, trait, val, units, source_url = "", "", "", "", ""

        return {
            "source_key": "TRAITBANK",
            "source_path": source_path,
            "scientific_name": (sci or "").strip(),
            "trait_raw": (trait or "").strip(),
            "value_raw": (val or "").strip() if isinstance(val, str) else val,
            "units_raw": (units or "").strip(),
            "reference_raw": (source_url or "").strip(),
            "raw": raw,
        }

    def _is_effectively_empty(self, rec):
        # Header-only stub or blank rows
        return (
            not rec.get("scientific_name")
            and not rec.get("trait_raw")
            and (rec.get("value_raw") in ("", None))
        )