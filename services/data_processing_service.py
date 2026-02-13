"""
Data Processing Service

Enriches raw lot data with calculated fields:
- ST/LT classification based on holding period
- Current market values from price data
- Unrealized P&L calculations
- P&L to value ratios
"""

from datetime import datetime
from typing import List, Dict, Optional
try:
    from ..models import Lot, Parameters, LotType
    from .market_data_service import MarketDataService, get_market_data_service
except ImportError:
    from models import Lot, Parameters, LotType
    from services.market_data_service import MarketDataService, get_market_data_service


class DataProcessingService:
    """
    Service for enriching lot data with calculated fields.
    
    This service is responsible for:
    - Fetching current market prices
    - Calculating ST/LT status
    - Computing unrealized P&L
    - Computing P&L to value ratios
    """
    
    def __init__(self, market_data_service: Optional[MarketDataService] = None):
        """
        Initialize the Data Processing Service.
        
        Args:
            market_data_service: Optional MarketDataService instance.
                               Uses singleton if not provided.
        """
        self.mds = market_data_service or get_market_data_service()
    
    def enrich_lots(self, lots: List[Lot], use_cache: bool = False) -> List[Lot]:
        """
        Enrich a list of lots with current market data and calculations.
        
        Args:
            lots: List of Lot objects to enrich
            use_cache: Whether to use cached prices
            
        Returns:
            The same list of lots with updated calculated fields
        """
        if not lots:
            return lots
        
        # Get unique currencies
        currencies = list(set(lot.currency for lot in lots))
        
        # Fetch all prices in batch
        prices = self.mds.get_prices(currencies, use_cache=use_cache)
        
        current_date = datetime.now()
        
        # Update each lot
        for lot in lots:
            price = prices.get(lot.currency, 0.0)
            if price and price > 0:
                lot.update_calculated_fields(price, current_date)
            else:
                # If no price available, still calculate ST/LT
                days_held = (current_date - lot.timestamp).days
                lot.stlt = "LT" if days_held > 365 else "ST"
                lot.current_mkt_price = 0.0
                lot.current_value = 0.0
                lot.ur_pnl = 0.0
                lot.pnl_to_value = 0.0
        
        return lots
    
    def enrich_single_lot(self, lot: Lot, use_cache: bool = True) -> Lot:
        """
        Enrich a single lot with current market data.
        
        Args:
            lot: Lot object to enrich
            use_cache: Whether to use cached price
            
        Returns:
            The lot with updated calculated fields
        """
        price = self.mds.get_price(lot.currency, use_cache=use_cache)
        if price and price > 0:
            lot.update_calculated_fields(price)
        return lot
    
    def get_current_price(self, currency: str, use_cache: bool = False) -> float:
        """
        Get the current price for a currency.
        
        Args:
            currency: Cryptocurrency symbol
            use_cache: Whether to use cached price
            
        Returns:
            Current USD price
        """
        return self.mds.get_price(currency, use_cache=use_cache) or 0.0
    
    def filter_eligible_lots(self, lots: List[Lot], 
                            min_value: float = 0.0,
                            lot_types: Optional[List[str]] = None) -> List[Lot]:
        """
        Filter lots based on eligibility criteria.
        
        Args:
            lots: List of lots to filter
            min_value: Minimum current value for eligibility
            lot_types: List of lot types to include (e.g., ["STG", "LTL"])
            
        Returns:
            Filtered list of eligible lots
        """
        filtered = []
        
        for lot in lots:
            # Check if lot has remaining quantity
            if lot.remaining_quantity <= 0:
                continue
            
            # Check minimum value
            if lot.current_value < min_value:
                continue
            
            # Check eligible currency flag
            if not lot.eligible_currency:
                continue
            
            # Check lot type if specified
            if lot_types:
                lot_type = lot.get_lot_type()
                if lot_type is None or lot_type.value not in lot_types:
                    continue
            
            filtered.append(lot)
        
        return filtered
    
    def sort_lots(self, lots: List[Lot], parameters: Parameters) -> List[Lot]:
        """
        Sort lots according to user parameters.
        
        The sorting logic:
        1. Separate gains and losses
        2. Sort each group by the specified index (pnl or value)
        3. Apply ascending/descending based on gain_lot_ordering and loss_lot_ordering
        4. Concatenate: gains first, then losses
        
        Args:
            lots: List of lots to sort
            parameters: User parameters with sorting preferences
            
        Returns:
            Sorted list of lots
        """
        # Separate gains and losses
        gains = [lot for lot in lots if lot.ur_pnl >= 0]
        losses = [lot for lot in lots if lot.ur_pnl < 0]
        
        # Determine sort key
        if parameters.lot_order_index == "pnl":
            key_func = lambda lot: abs(lot.ur_pnl)
        else:  # value
            key_func = lambda lot: lot.current_value
        
        # Sort gains
        gain_reverse = parameters.gain_lot_ordering == "high-to-low"
        gains.sort(key=key_func, reverse=gain_reverse)
        
        # Sort losses (use absolute value for sorting)
        loss_reverse = parameters.loss_lot_ordering == "high-to-low"
        losses.sort(key=key_func, reverse=loss_reverse)
        
        # Concatenate: gains first, then losses
        return gains + losses
    
    def get_lots_by_type(self, lots: List[Lot]) -> Dict[str, List[Lot]]:
        """
        Group lots by their type (STG, STL, LTG, LTL).
        
        Args:
            lots: List of lots to group
            
        Returns:
            Dictionary mapping lot type strings to lists of lots
        """
        result = {
            "STG": [],
            "STL": [],
            "LTG": [],
            "LTL": []
        }
        
        for lot in lots:
            if lot.remaining_quantity <= 0:
                continue
            
            lot_type = lot.get_lot_type()
            if lot_type:
                result[lot_type.value].append(lot)
        
        return result
    
    def get_portfolio_summary(self, lots: List[Lot]) -> Dict:
        """
        Calculate summary statistics for a portfolio of lots.
        
        Args:
            lots: List of lots
            
        Returns:
            Dictionary with portfolio summary statistics
        """
        active_lots = [lot for lot in lots if lot.remaining_quantity > 0]
        
        total_value = sum(lot.current_value for lot in active_lots)
        total_ur_pnl = sum(lot.ur_pnl for lot in active_lots)
        
        # Group by type
        lots_by_type = self.get_lots_by_type(active_lots)
        
        # Calculate values by type
        stg_value = sum(lot.current_value for lot in lots_by_type["STG"])
        stl_value = sum(lot.current_value for lot in lots_by_type["STL"])
        ltg_value = sum(lot.current_value for lot in lots_by_type["LTG"])
        ltl_value = sum(lot.current_value for lot in lots_by_type["LTL"])
        
        stg_pnl = sum(lot.ur_pnl for lot in lots_by_type["STG"])
        stl_pnl = sum(lot.ur_pnl for lot in lots_by_type["STL"])
        ltg_pnl = sum(lot.ur_pnl for lot in lots_by_type["LTG"])
        ltl_pnl = sum(lot.ur_pnl for lot in lots_by_type["LTL"])
        
        # Group by currency
        currencies = {}
        for lot in active_lots:
            if lot.currency not in currencies:
                currencies[lot.currency] = {"value": 0, "pnl": 0, "quantity": 0}
            currencies[lot.currency]["value"] += lot.current_value
            currencies[lot.currency]["pnl"] += lot.ur_pnl
            currencies[lot.currency]["quantity"] += lot.remaining_quantity
        
        return {
            "total_lots": len(active_lots),
            "total_value": total_value,
            "total_ur_pnl": total_ur_pnl,
            "stg_count": len(lots_by_type["STG"]),
            "stl_count": len(lots_by_type["STL"]),
            "ltg_count": len(lots_by_type["LTG"]),
            "ltl_count": len(lots_by_type["LTL"]),
            "stg_value": stg_value,
            "stl_value": stl_value,
            "ltg_value": ltg_value,
            "ltl_value": ltl_value,
            "stg_pnl": stg_pnl,
            "stl_pnl": stl_pnl,
            "ltg_pnl": ltg_pnl,
            "ltl_pnl": ltl_pnl,
            "by_currency": currencies
        }


# Singleton instance
_data_processing_service: Optional[DataProcessingService] = None


def get_data_processing_service() -> DataProcessingService:
    """Get the singleton DataProcessingService instance"""
    global _data_processing_service
    if _data_processing_service is None:
        _data_processing_service = DataProcessingService()
    return _data_processing_service
