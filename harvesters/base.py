# harvesters/base.py
# Minimal shared base class for all harvesters.

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseHarvester(ABC):
    def __init__(self, source_name: str):
        self.source_name = source_name

    @abstractmethod
    def harvest_metadata(self, limit=None):
        """Return a list of metadata records (dicts)."""
        raise NotImplementedError

    def harvest_images(self, limit=None):
        """Return a list of image records (dicts). Optional."""
        return []

    def harvest_full(self, limit=None):
        """Default full-mode: metadata + images."""
        metadata = self.harvest_metadata(limit)
        images = self.harvest_images(limit)
        return {
            "metadata": metadata,
            "images": images,
        }