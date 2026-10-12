"""
Base class for anomaly and corporate action integrity detectors.
"""

from abc import ABC, abstractmethod
from typing import List, Union
import polars as pl
from src.models.schemas import AnomalyAlert


class BaseDetector(ABC):
    """Abstract base class that all anomaly detection modules must implement."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run(self, data: Union[pl.DataFrame, pl.LazyFrame]) -> List[AnomalyAlert]:
        """
        Execute detection logic on input stock price data.
        Returns a list of AnomalyAlert objects.
        """
        pass
