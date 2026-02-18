"""
Simple Lot Selection Engine

Implements 4 common alternative lot selection strategies for comparison
against the 14-step Tax Waterfall:
- FIFO: First In, First Out (oldest lots first)
- LIFO: Last In, First Out (newest lots first)
- Max-Gain: Highest unrealized gain first
- Max-Loss: Highest unrealized loss first
"""

from enum import Enum
from typing import List, Optional

try:
    from ..models import Lot, Parameters
    from ..services.data_processing_service import DataProcessingService
    from .lot_selection_engine import LotSelectionResult
except ImportError:
    from models import Lot, Parameters
    from services.data_processing_service import DataProcessingService
    from engines.lot_selection_engine import LotSelectionResult


class SimpleStrategy(Enum):
    FIFO = "fifo"
    LIFO = "lifo"
    MAX_GAIN = "max_gain"
    MAX_LOSS = "max_loss"


class SimpleLotSelectionEngine:
    """
    A simple lot selection engine that picks lots using one of four
    common strategies: FIFO, LIFO, Max-Gain, or Max-Loss.

    Returns LotSelectionResult with tw_step=0 so TradeEngine uses
    PTV as-is (no CF/OID recalculation).
    """

    def __init__(self, strategy: SimpleStrategy,
                 data_processing_service: Optional[DataProcessingService] = None):
        self.strategy = strategy
        self.dps = data_processing_service or DataProcessingService()

    def select_lots(self, lots: List[Lot], parameters: Parameters,
                    rdcpa: float) -> Optional[LotSelectionResult]:
        eligible = self.dps.filter_eligible_lots(
            lots, min_value=parameters.min_lot_value
        )

        if not eligible:
            return None

        if self.strategy == SimpleStrategy.FIFO:
            eligible.sort(key=lambda lot: lot.timestamp)
        elif self.strategy == SimpleStrategy.LIFO:
            eligible.sort(key=lambda lot: lot.timestamp, reverse=True)
        elif self.strategy == SimpleStrategy.MAX_GAIN:
            eligible.sort(key=lambda lot: lot.ur_pnl, reverse=True)
        elif self.strategy == SimpleStrategy.MAX_LOSS:
            eligible.sort(key=lambda lot: lot.ur_pnl)

        lot = eligible[0]

        return LotSelectionResult(
            lots=[(lot, lot.current_value)],
            tw_step=0,
            is_two_way=False,
        )
