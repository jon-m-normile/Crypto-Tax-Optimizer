"""
Engines package for the Crypto Tax Optimization System
"""

try:
    from .lot_selection_engine import LotSelectionEngine, LotSelectionResult
    from .tax_calculation_engine import TaxCalculationEngine
    from .trade_engine import TradeEngine
    from .simple_lot_selection_engine import SimpleLotSelectionEngine, SimpleStrategy
except ImportError:
    from engines.lot_selection_engine import LotSelectionEngine, LotSelectionResult
    from engines.tax_calculation_engine import TaxCalculationEngine
    from engines.trade_engine import TradeEngine
    from engines.simple_lot_selection_engine import SimpleLotSelectionEngine, SimpleStrategy

__all__ = [
    'LotSelectionEngine',
    'LotSelectionResult',
    'TaxCalculationEngine',
    'TradeEngine',
    'SimpleLotSelectionEngine',
    'SimpleStrategy',
]
