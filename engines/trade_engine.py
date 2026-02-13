"""
Trade Engine (TE)

The main orchestrator for Debit Card Purchase Operations (DCPO).
Coordinates the Lot Selection Engine, Market Data Service, and Tax Calculation Engine.

Per PRD v1.1 TE Functionality:
1. Validates portfolio can cover the purchase (DCPA)
2. Calls LSE to get lot(s) and PTV (Preliminary Trade Value)
3. Calculates ATV (Adjusted Trade Value) from PTV
4. Executes sales and updates portfolio
5. Calls TCE to recalculate tax obligation
6. Loops until RDCPA = 0 or no more lots

ATV Formulas (per PRD v1.2):
- 1-way: ATV = Min(RDCPA, Designated_Lot_value, PTV)
- 2-way: If (PTV1 + PTV2) <= RDCPA: use PTVs as-is
         Else: scale both by (RDCPA / total_PTV) to maintain P&L balance
"""

from typing import List, Optional, Tuple
from datetime import datetime
import uuid

try:
    from ..models import (
        Lot, Sale, Purchase, Parameters, TaxCalculationResult, PurchaseStatus
    )
    from ..services.market_data_service import MarketDataService, get_market_data_service
    from ..services.data_processing_service import DataProcessingService, get_data_processing_service
    from .lot_selection_engine import LotSelectionEngine, LotSelectionResult
    from .tax_calculation_engine import TaxCalculationEngine
except ImportError:
    from models import (
        Lot, Sale, Purchase, Parameters, TaxCalculationResult, PurchaseStatus
    )
    from services.market_data_service import MarketDataService, get_market_data_service
    from services.data_processing_service import DataProcessingService, get_data_processing_service
    from engines.lot_selection_engine import LotSelectionEngine, LotSelectionResult
    from engines.tax_calculation_engine import TaxCalculationEngine


class TradeEngine:
    """
    The Trade Engine orchestrates Debit Card Purchase Operations (DCPO).
    
    Per PRD v1.1:
    - Reads client's DCPA which initiates the DCPO
    - Calls the Lot Selection Engine
    - Receives lot_id(s) and PTV from LSE
    - Calculates ATV (Adjusted Trade Value)
    - Creates Sell Orders/Trades
    - Updates lots with reduced quantities
    - Writes to Sales table
    - Writes to Purchases table
    """
    
    def __init__(self, 
                 market_data_service: Optional[MarketDataService] = None,
                 data_processing_service: Optional[DataProcessingService] = None):
        """
        Initialize the Trade Engine.
        
        Args:
            market_data_service: Optional MDS instance
            data_processing_service: Optional DPS instance
        """
        self.mds = market_data_service or get_market_data_service()
        self.dps = data_processing_service or get_data_processing_service()
        self.lse = LotSelectionEngine(self.dps)
        self.tce = TaxCalculationEngine()
    
    def validate_purchase(self, lots: List[Lot], dcpa: float, 
                         parameters: Parameters) -> Tuple[bool, str]:
        """
        Validate that a debit card purchase can be fulfilled.
        
        Per PRD v1.1 TE Step 2-3:
        "If the sum of the current value of all eligible lots is less than DCPA,
        then the DCPA is rejected."
        
        Args:
            lots: List of available lots
            dcpa: Debit card purchase amount
            parameters: User parameters
            
        Returns:
            Tuple of (is_valid, message)
        """
        # Refresh lot valuations
        self.dps.enrich_lots(lots, use_cache=False)
        
        # Filter for eligible lots
        eligible_lots = self.dps.filter_eligible_lots(
            lots, 
            min_value=parameters.min_lot_value
        )
        
        if not eligible_lots:
            return False, "No eligible lots available in portfolio"
        
        # Calculate total available value
        # Per PRD: If Lots.current_value > RemDCPA then Transaction Approval = TRUE
        total_value = sum(lot.current_value for lot in eligible_lots)
        
        if total_value < dcpa:
            return False, f"Insufficient funds: Portfolio value ${total_value:,.2f} < Purchase ${dcpa:,.2f}"
        
        return True, f"Purchase approved. Available: ${total_value:,.2f}"
    
    def _calculate_atv_one_way(self, rdcpa: float, lot_value: float, ptv: float) -> float:
        """
        Calculate Adjusted Trade Value for 1-way allocation.
        
        Per PRD v1.1:
        ATV = Minimum(RDCPA, Designated_Lot_value, PTV)
        """
        return min(rdcpa, lot_value, ptv)
    
    def _calculate_atv_two_way(self, rdcpa: float, ptv1: float, ptv2: float) -> Tuple[float, float]:
        """
        Calculate Adjusted Trade Values for 2-way allocation.

        Per PRD v1.2:
        The PTVs are calculated by LSE to produce equal and offsetting P&Ls.
        When constrained by RDCPA, we must scale BOTH proportionally to maintain
        the P&L balance (not cap each independently at RDCPA/2).

        If total PTV fits within RDCPA: use PTVs as-is
        If total PTV exceeds RDCPA: scale both by (RDCPA / total_ptv)
        """
        total_ptv = ptv1 + ptv2

        if total_ptv <= rdcpa:
            # We can afford both PTVs, use them as-is to maintain P&L balance
            return ptv1, ptv2
        else:
            # Scale down proportionally to maintain equal P&L ratio
            scale_factor = rdcpa / total_ptv
            return ptv1 * scale_factor, ptv2 * scale_factor
    
    def process_purchase(self, lots: List[Lot], parameters: Parameters,
                        dcpa: float, description: str = "", 
                        category: str = "",
                        existing_sales: List[Sale] = None) -> Tuple[Purchase, List[Sale], TaxCalculationResult]:
        """
        Process a complete debit card purchase operation (DCPO).
        
        Per PRD v1.1 DCPO Flow:
        1. Validate portfolio can afford the purchase
        2. Call Trade Engine which creates an order
        3. Trade Engine calls LSE to get lot(s) and PTV
        4. TE calculates ATV from PTV
        5. TE creates and executes sell orders
        6. TE decrements lot quantities and RDCPA
        7. TE calls TCE to recalculate tax obligation
        8. Loop until RDCPA = 0 or no more lots
        
        Args:
            lots: List of all lots in portfolio
            parameters: User parameters
            dcpa: Debit card purchase amount (DCPA)
            description: Optional purchase description
            category: Optional purchase category
            existing_sales: List of existing sales for tax calculation
            
        Returns:
            Tuple of (Purchase record, List of new Sales, TaxCalculationResult)
        """
        if existing_sales is None:
            existing_sales = []
        
        # Step 1-3: Validate purchase
        is_valid, message = self.validate_purchase(lots, dcpa, parameters)
        if not is_valid:
            # Return incomplete purchase
            purchase = Purchase(
                purchase_id=str(uuid.uuid4())[:8],
                dcpa=dcpa,
                status=PurchaseStatus.INCOMPLETE,
                description=description,
                category=category
            )
            return purchase, [], self.tce.calculate_taxes(existing_sales, parameters)
        
        # Create purchase record
        purchase = Purchase(
            purchase_id=str(uuid.uuid4())[:8],
            dcpa=dcpa,
            status=PurchaseStatus.PROCESSING,
            description=description,
            category=category
        )
        
        new_sales = []
        iteration_limit = 100  # Pause point for user confirmation
        iteration = 0
        hit_iteration_limit = False

        # Per PRD: Loop while RDCPA > 0 and Lots_value > 0
        while purchase.rdcpa > 0.01 and iteration < iteration_limit:
            iteration += 1
            
            # Refresh lot data with current prices
            self.dps.enrich_lots(lots, use_cache=False)
            
            # Step 4-5: Call LSE to select lots and get PTV
            selection = self.lse.select_lots(lots, parameters, purchase.rdcpa)
            
            if selection is None:
                # No more eligible lots
                purchase.status = PurchaseStatus.INCOMPLETE
                break
            
            # Step 6: Process selected lot(s)
            if selection.is_two_way:
                # 2-way allocation
                sales = self._process_two_way_selection(
                    selection, purchase, lots, parameters
                )
                new_sales.extend(sales)
            else:
                # 1-way allocation
                sale = self._process_one_way_selection(
                    selection, purchase, lots, parameters
                )
                if sale:
                    new_sales.append(sale)
            
            # NOTE: rem_cfstl, rem_cfltl, and rem_oid are now updated directly
            # in _process_one_way_selection based on raw gains/losses.
            # This ensures proper TWS 1-6 to TWS 7-10 transitions without
            # being affected by third netting in TCE calculations.

        # Check if we hit the iteration limit with remaining amount
        if iteration >= iteration_limit and purchase.rdcpa > 0.01:
            hit_iteration_limit = True
            purchase.status = PurchaseStatus.PROCESSING  # Still processing

        # Final status update
        if purchase.rdcpa <= 0.01:
            purchase.status = PurchaseStatus.COMPLETED
            purchase.rdcpa = 0

        # Step 7: Calculate taxes on all sales (existing + new)
        all_sales = existing_sales + new_sales
        tax_result = self.tce.calculate_taxes(all_sales, parameters)

        # Update parameters with remaining CF values
        self.tce.update_parameters_from_result(tax_result, parameters)

        return purchase, new_sales, tax_result, hit_iteration_limit
    
    def _process_one_way_selection(self, selection: LotSelectionResult,
                                   purchase: Purchase, lots: List[Lot],
                                   parameters: Parameters) -> Optional[Sale]:
        """
        Process a 1-way lot selection.

        Per PRD v1.1:
        ATV = Minimum(RDCPA, Designated_Lot_value, PTV)
        """
        lot, ptv = selection.lots[0]

        if purchase.rdcpa <= 0.01:
            return None

        # Get fresh price from MDS
        price = self.mds.get_price(lot.currency, use_cache=False)
        if price is None or price <= 0:
            return None

        # Update lot's calculated fields with fresh price
        lot.update_calculated_fields(price)

        # Recalculate PTV with fresh pnl_to_value for steps that depend on it
        # The original PTV was calculated with stale price data
        tw_step = selection.tw_step

        if tw_step in [1, 2, 3, 4]:
            # Steps 1-4: Gain vs Carry-Forward Loss
            # PTV = Min(remaining_cf / pnl_to_value, current_value)
            pnl_to_value = lot.pnl_to_value
            if pnl_to_value > 0:
                if tw_step in [1, 3]:  # STG vs CF-STL or CF-LTL
                    remaining_cf = abs(parameters.rem_cfstl) if tw_step == 1 else abs(parameters.rem_cfltl)
                else:  # LTG vs CF-LTL or CF-STL
                    remaining_cf = abs(parameters.rem_cfltl) if tw_step == 2 else abs(parameters.rem_cfstl)
                cf_based_value = remaining_cf / pnl_to_value
                ptv = min(cf_based_value, lot.current_value)

        elif tw_step in [5, 6]:
            # Steps 5-6: Loss vs OID
            # PTV = Min(remaining_oid / pnl_to_value, current_value)
            pnl_to_value = abs(lot.pnl_to_value)
            if pnl_to_value > 0:
                remaining_oid = abs(parameters.rem_oid)
                oid_based_value = remaining_oid / pnl_to_value
                ptv = min(oid_based_value, lot.current_value)

        # Calculate ATV per PRD formula
        atv = self._calculate_atv_one_way(purchase.rdcpa, lot.current_value, ptv)
        
        # Calculate quantity from ATV
        quantity_to_sell = atv / price
        
        # Ensure we don't sell more than remaining
        quantity_to_sell = min(quantity_to_sell, lot.remaining_quantity)
        
        if quantity_to_sell <= 0:
            return None
        
        # Create sale record
        sale = Sale.create(
            purchase_id=purchase.purchase_id,
            lot=lot,
            tw_step=selection.tw_step,
            quantity_sold=quantity_to_sell,
            price=price
        )

        # Update lot quantity
        lot.remaining_quantity -= quantity_to_sell

        # Update purchase totals
        purchase.add_sale(sale)

        # For TWS 1-4, directly update rem_cf based on raw realized gains
        # This ensures proper transition without being affected by netting
        if tw_step in [1, 3]:  # STG vs CF-STL or CF-LTL
            raw_gain = sale.realized_cgl  # positive for gains
            if tw_step == 1:
                parameters.rem_cfstl = parameters.rem_cfstl + raw_gain  # cfstl is negative, gain is positive
                if parameters.rem_cfstl > 0:
                    parameters.rem_cfstl = 0
            else:  # step 3
                parameters.rem_cfltl = parameters.rem_cfltl + raw_gain
                if parameters.rem_cfltl > 0:
                    parameters.rem_cfltl = 0
        elif tw_step in [2, 4]:  # LTG vs CF-LTL or CF-STL
            raw_gain = sale.realized_cgl
            if tw_step == 2:
                parameters.rem_cfltl = parameters.rem_cfltl + raw_gain
                if parameters.rem_cfltl > 0:
                    parameters.rem_cfltl = 0
            else:  # step 4
                parameters.rem_cfstl = parameters.rem_cfstl + raw_gain
                if parameters.rem_cfstl > 0:
                    parameters.rem_cfstl = 0

        # For TWS 5-6, directly update rem_oid based on raw realized loss
        # This ensures proper transition to TWS 7-10 without being affected
        # by third netting that might reduce the effective OID in TCE calculations
        elif tw_step in [5, 6]:
            raw_loss = abs(sale.realized_cgl)  # realized_cgl is negative for losses
            parameters.rem_oid = parameters.rem_oid + raw_loss  # rem_oid is negative, loss is positive
            # Ensure rem_oid doesn't go above 0
            if parameters.rem_oid > 0:
                parameters.rem_oid = 0

        return sale
    
    def _process_two_way_selection(self, selection: LotSelectionResult,
                                   purchase: Purchase, lots: List[Lot],
                                   parameters: Parameters) -> List[Sale]:
        """
        Process a 2-way lot selection.
        
        Per PRD v1.1:
        ATV_lot1 = Minimum(RDCPA/2, PTV_lot1)
        ATV_lot2 = Minimum(RDCPA/2, PTV_lot2)
        """
        sales = []
        
        if len(selection.lots) < 2:
            return sales
        
        lot1, ptv1 = selection.lots[0]
        lot2, ptv2 = selection.lots[1]
        
        if purchase.rdcpa <= 0.01:
            return sales
        
        # Get fresh prices for both lots
        price1 = self.mds.get_price(lot1.currency, use_cache=False)
        price2 = self.mds.get_price(lot2.currency, use_cache=False)
        
        if not price1 or price1 <= 0 or not price2 or price2 <= 0:
            return sales
        
        # Update calculated fields
        lot1.update_calculated_fields(price1)
        lot2.update_calculated_fields(price2)
        
        # Calculate ATVs per PRD formula
        atv1, atv2 = self._calculate_atv_two_way(purchase.rdcpa, ptv1, ptv2)
        
        # Process first lot
        quantity1 = atv1 / price1
        quantity1 = min(quantity1, lot1.remaining_quantity)
        
        if quantity1 > 0:
            sale1 = Sale.create(
                purchase_id=purchase.purchase_id,
                lot=lot1,
                tw_step=selection.tw_step,
                quantity_sold=quantity1,
                price=price1
            )
            lot1.remaining_quantity -= quantity1
            purchase.add_sale(sale1)
            sales.append(sale1)
        
        # Process second lot
        quantity2 = atv2 / price2
        quantity2 = min(quantity2, lot2.remaining_quantity)
        
        if quantity2 > 0:
            sale2 = Sale.create(
                purchase_id=purchase.purchase_id,
                lot=lot2,
                tw_step=selection.tw_step,
                quantity_sold=quantity2,
                price=price2
            )
            lot2.remaining_quantity -= quantity2
            purchase.add_sale(sale2)
            sales.append(sale2)
        
        return sales
    
    def process_single_sale(self, lot: Lot, quantity: float, price: float,
                           purchase: Purchase, tw_step: int) -> Sale:
        """
        Process a single lot sale.
        
        Args:
            lot: Lot to sell from
            quantity: Quantity to sell
            price: Sale price
            purchase: Associated Purchase record
            tw_step: Tax Waterfall step
            
        Returns:
            Sale record
        """
        # Refresh lot calculations
        lot.update_calculated_fields(price)
        
        # Create sale
        sale = Sale.create(
            purchase_id=purchase.purchase_id,
            lot=lot,
            tw_step=tw_step,
            quantity_sold=quantity,
            price=price
        )
        
        # Update lot
        lot.remaining_quantity -= quantity
        
        # Update purchase
        purchase.add_sale(sale)
        
        return sale
    
    def get_portfolio_value(self, lots: List[Lot]) -> float:
        """
        Get the total current value of all lots.
        
        Args:
            lots: List of lots
            
        Returns:
            Total portfolio value in USD
        """
        self.dps.enrich_lots(lots, use_cache=True)
        return sum(lot.current_value for lot in lots if lot.remaining_quantity > 0)
    
    def simulate_purchase(self, lots: List[Lot], parameters: Parameters,
                         dcpa: float) -> List[dict]:
        """
        Simulate a purchase without actually executing it.
        
        Useful for showing the user what sales would be made.
        
        Args:
            lots: List of lots (will not be modified)
            parameters: User parameters
            dcpa: Debit card purchase amount
            
        Returns:
            List of dictionaries describing proposed sales
        """
        from copy import deepcopy
        
        # Work with copies
        lots_copy = [deepcopy(lot) for lot in lots]
        params_copy = deepcopy(parameters)
        
        self.dps.enrich_lots(lots_copy, use_cache=True)
        
        proposed_sales = []
        remaining = dcpa
        max_iterations = 50
        iteration = 0
        
        while remaining > 0.01 and iteration < max_iterations:
            iteration += 1
            
            selection = self.lse.select_lots(lots_copy, params_copy, remaining)
            
            if selection is None:
                break
            
            for lot, ptv in selection.lots:
                if remaining <= 0.01:
                    break
                
                # Calculate ATV based on allocation type
                if selection.is_two_way:
                    sell_value = min(remaining / 2, ptv)
                else:
                    sell_value = min(remaining, lot.current_value, ptv)
                
                quantity = sell_value / lot.current_mkt_price if lot.current_mkt_price > 0 else 0
                quantity = min(quantity, lot.remaining_quantity)
                
                if quantity <= 0:
                    continue
                
                # Calculate realized CGL
                realized_cgl = sell_value * lot.pnl_to_value
                
                proposed_sales.append({
                    "lot_id": lot.lot_id,
                    "currency": lot.currency,
                    "quantity": quantity,
                    "price": lot.current_mkt_price,
                    "value": sell_value,
                    "realized_cgl": realized_cgl,
                    "stlt": lot.stlt,
                    "tw_step": selection.tw_step
                })
                
                # Update copies
                lot.remaining_quantity -= quantity
                remaining -= sell_value
        
        return proposed_sales
