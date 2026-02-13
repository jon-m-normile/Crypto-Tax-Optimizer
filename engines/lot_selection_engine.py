"""
Lot Selection Engine (LSE)

Contains the Tax Waterfall Lot Selection Algorithm that determines
which lots to sell to minimize tax liability.

The 14-step Tax Waterfall per PRD v1.1:
1. STG offset vs. CF-STL
2. LTG offset vs. CF-LTL
3. STG offset vs. CF-LTL
4. LTG offset vs. CF-STL
5. STL allocated to OID
6. LTL allocated to OID
7. STG offset vs STL (2-way)
8. LTG offset vs LTL (2-way)
9. STG offset vs LTL (2-way)
10. LTG offset vs STL (2-way)
11. Realize STL
12. Realize LTL
13. Realize LTG
14. Realize STG

PTV (Preliminary Trade Value) Formulas per PRD v1.2:
- Steps 1-4: PTV = Min(RemainingCF / pnl_to_value, Lots.current_value)
- Steps 5-6: PTV = Min(ROID / pnl_to_value, Lots.current_value)
- Steps 7-10: target_pnl = min(abs(ur_pnl_gain), abs(ur_pnl_loss))
              PTVgain = target_pnl / abs(pnl_to_value_gain)
              PTVloss = target_pnl / abs(pnl_to_value_loss)
- Steps 11-14: PTV = Lots.current_value
"""

from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from copy import deepcopy

try:
    from ..models import (
        Lot, Parameters, TaxWaterfallStep, TAX_WATERFALL_CONFIG, LotType
    )
    from ..services.data_processing_service import DataProcessingService
except ImportError:
    from models import (
        Lot, Parameters, TaxWaterfallStep, TAX_WATERFALL_CONFIG, LotType
    )
    from services.data_processing_service import DataProcessingService


@dataclass
class LotSelectionResult:
    """
    Result from the Lot Selection Engine.
    
    Attributes:
        lots: List of (Lot, ptv) tuples - the Preliminary Trade Value for each lot
        tw_step: The Tax Waterfall step that was used
        is_two_way: Whether this is a 2-way allocation
    """
    lots: List[Tuple[Lot, float]]  # (lot, preliminary_trade_value)
    tw_step: int
    is_two_way: bool
    
    @property
    def lot_ids(self) -> List[str]:
        return [lot.lot_id for lot, _ in self.lots]


class LotSelectionEngine:
    """
    The Lot Selection Engine implements the Tax Waterfall algorithm.
    
    Per PRD v1.1:
    - Contains the Tax Waterfall Lot Selection Algorithm
    - Determines active Tax Waterfall Stage
    - Sorts and filters the Purchase Lot table
    - Identifies and returns to the Trade Engine the next Purchase Lot(s) to be sold
    - Determines & returns the PTV (Preliminary Trade Value)
    """
    
    def __init__(self, data_processing_service: Optional[DataProcessingService] = None):
        """
        Initialize the Lot Selection Engine.
        
        Args:
            data_processing_service: Optional DPS instance
        """
        self.dps = data_processing_service or DataProcessingService()
        self._sorted_lots: Optional[List[Lot]] = None
        self._lots_by_type: Optional[Dict[str, List[Lot]]] = None
    
    def select_lots(self, lots: List[Lot], parameters: Parameters,
                   rdcpa: float) -> Optional[LotSelectionResult]:
        """
        Select lots to sell using the Tax Waterfall algorithm.
        
        Per PRD v1.1 LSE Section:
        1. Sort the Lots table according to parameters (once per DC purchase)
        2. Determine the Active Tax Waterfall Step
        3. Filter lots by Return Type
        4. Select first lot(s) from sorted/filtered table
        5. Calculate PTV and return to Trade Engine
        
        Args:
            lots: List of all lots in the portfolio
            parameters: User parameters
            rdcpa: Remaining debit card purchase amount to cover
            
        Returns:
            LotSelectionResult with selected lots and PTV, or None if no lots available
        """
        # Filter for eligible lots
        eligible_lots = self.dps.filter_eligible_lots(
            lots, 
            min_value=parameters.min_lot_value
        )
        
        if not eligible_lots:
            return None
        
        # Sort lots according to parameters (per PRD: only sort once per DC purchase)
        self._sorted_lots = self.dps.sort_lots(eligible_lots, parameters)
        
        # Group by type
        self._lots_by_type = self.dps.get_lots_by_type(self._sorted_lots)
        
        # Find the first active Tax Waterfall step
        active_step = self._get_active_step(parameters)
        
        if active_step is None:
            return None
        
        # Select lots based on the active step
        if active_step.is_two_way():
            return self._select_two_way(active_step, parameters, rdcpa)
        else:
            return self._select_one_way(active_step, parameters, rdcpa)
    
    def _get_active_step(self, parameters: Parameters) -> Optional[TaxWaterfallStep]:
        """
        Determine which Tax Waterfall step is currently active.
        
        Per PRD: The LSE will select the first Tax Waterfall Step that is 
        Active=TRUE as the waterfall step that will be used.
        """
        for step_config in TAX_WATERFALL_CONFIG:
            step = deepcopy(step_config)
            
            if self._is_step_active(step, parameters):
                step.active = True
                return step
        
        return None
    
    def _is_step_active(self, step: TaxWaterfallStep, parameters: Parameters) -> bool:
        """
        Check if a Tax Waterfall step is currently active based on Activation Criteria.
        
        Per PRD v1.1 Tax Waterfall Table - Activation Criteria column.
        """
        step_num = step.step
        
        # Steps 1-4: Gain vs Carry-Forward Loss
        if step_num == 1:  # STG vs CF-STL
            # Client's portfolio must have STG lots with value > 0 AND RCFSTL != 0
            has_stg = len(self._lots_by_type.get("STG", [])) > 0
            has_rcfstl = parameters.rem_cfstl < 0  # CF is always negative
            return has_stg and has_rcfstl
        
        elif step_num == 2:  # LTG vs CF-LTL
            has_ltg = len(self._lots_by_type.get("LTG", [])) > 0
            has_rcfltl = parameters.rem_cfltl < 0
            return has_ltg and has_rcfltl
        
        elif step_num == 3:  # STG vs CF-LTL
            has_stg = len(self._lots_by_type.get("STG", [])) > 0
            has_rcfltl = parameters.rem_cfltl < 0
            return has_stg and has_rcfltl
        
        elif step_num == 4:  # LTG vs CF-STL
            has_ltg = len(self._lots_by_type.get("LTG", [])) > 0
            has_rcfstl = parameters.rem_cfstl < 0
            return has_ltg and has_rcfstl
        
        # Steps 5-6: Loss vs OID
        elif step_num == 5:  # STL vs OID
            # Must have STL lots with value > 0 AND ROID != 0
            has_stl = len(self._lots_by_type.get("STL", [])) > 0
            has_roid = parameters.rem_oid < 0  # OID is always negative
            return has_stl and has_roid
        
        elif step_num == 6:  # LTL vs OID
            has_ltl = len(self._lots_by_type.get("LTL", [])) > 0
            has_roid = parameters.rem_oid < 0
            return has_ltl and has_roid
        
        # Steps 7-10: 2-Way Offset
        elif step_num == 7:  # STG vs STL
            has_stg = len(self._lots_by_type.get("STG", [])) > 0
            has_stl = len(self._lots_by_type.get("STL", [])) > 0
            return has_stg and has_stl
        
        elif step_num == 8:  # LTG vs LTL
            has_ltg = len(self._lots_by_type.get("LTG", [])) > 0
            has_ltl = len(self._lots_by_type.get("LTL", [])) > 0
            return has_ltg and has_ltl
        
        elif step_num == 9:  # STG vs LTL
            has_stg = len(self._lots_by_type.get("STG", [])) > 0
            has_ltl = len(self._lots_by_type.get("LTL", [])) > 0
            return has_stg and has_ltl
        
        elif step_num == 10:  # LTG vs STL
            has_ltg = len(self._lots_by_type.get("LTG", [])) > 0
            has_stl = len(self._lots_by_type.get("STL", [])) > 0
            return has_ltg and has_stl
        
        # Steps 11-14: Realize gains/losses
        elif step_num == 11:  # Realize STL
            return len(self._lots_by_type.get("STL", [])) > 0
        
        elif step_num == 12:  # Realize LTL
            return len(self._lots_by_type.get("LTL", [])) > 0
        
        elif step_num == 13:  # Realize LTG
            return len(self._lots_by_type.get("LTG", [])) > 0
        
        elif step_num == 14:  # Realize STG
            return len(self._lots_by_type.get("STG", [])) > 0
        
        return False
    
    def _calculate_ptv_gain_vs_cf(self, lot: Lot, remaining_cf: float) -> float:
        """
        Calculate PTV for gain lots vs carry-forward loss (Steps 1-4).
        
        Per PRD v1.1:
        PTV = Min(RCFSTL / Lots.pnl_to_value, Lots.current_value)
        
        The formula calculates the lesser of:
        - The value needed to fully use remaining CF
        - The lot's current value (can't sell more than you have)
        """
        pnl_to_value = lot.pnl_to_value
        
        if pnl_to_value <= 0:
            # Gain lots should have positive pnl_to_value
            # If not, just return the lot value
            return lot.current_value
        
        # remaining_cf is already positive (abs value passed in)
        # Value to exhaust CF = CF / pnl_to_value
        cf_based_value = remaining_cf / pnl_to_value
        
        # PTV = Min(CF-based value, lot's current value)
        return min(cf_based_value, lot.current_value)
    
    def _calculate_ptv_loss_vs_oid(self, lot: Lot, remaining_oid: float) -> float:
        """
        Calculate PTV for loss lots vs OID (Steps 5-6).
        
        Per PRD v1.1:
        PTV = Min(ROID / Lots.pnl_to_value, Lots.current_value)
        
        Note: For loss lots, pnl_to_value is negative, so we use absolute value.
        """
        pnl_to_value = abs(lot.pnl_to_value)
        
        if pnl_to_value <= 0:
            return lot.current_value
        
        # remaining_oid is already positive (abs value passed in)
        oid_based_value = remaining_oid / pnl_to_value
        
        return min(oid_based_value, lot.current_value)
    
    def _calculate_ptv_two_way(self, gain_lot: Lot, loss_lot: Lot) -> Tuple[float, float]:
        """
        Calculate PTVs for 2-way allocation steps (Steps 7-10).

        Per PRD v1.2:
        The goal is to sell amounts from each lot that realize EQUAL and OFFSETTING P&Ls.

        target_pnl = min(abs(ur_pnl_gain), abs(ur_pnl_loss))
        PTVgain = target_pnl / abs(pnl_to_value_gain)
        PTVloss = target_pnl / abs(pnl_to_value_loss)

        The smaller P&L determines how much can be offset.
        """
        # Get pnl_to_value ratios (use absolute values)
        pnl_to_value_gain = abs(gain_lot.pnl_to_value) if gain_lot.pnl_to_value != 0 else 0.001
        pnl_to_value_loss = abs(loss_lot.pnl_to_value) if loss_lot.pnl_to_value != 0 else 0.001

        # Use minimum P&L (not value) to determine the offset target
        target_pnl = min(abs(gain_lot.ur_pnl), abs(loss_lot.ur_pnl))

        # Calculate PTVs - the trade values needed to realize the target P&L
        ptv_gain = target_pnl / pnl_to_value_gain
        ptv_loss = target_pnl / pnl_to_value_loss

        # Ensure PTVs don't exceed lot values
        ptv_gain = min(ptv_gain, gain_lot.current_value)
        ptv_loss = min(ptv_loss, loss_lot.current_value)

        return ptv_gain, ptv_loss
    
    def _get_first_lot_of_type(self, lot_type: str, parameters: Parameters) -> Optional[Lot]:
        """
        Get the first lot of a given type based on sorting preferences.
        
        Per PRD: "The LSE will go to the first record of the sorted and filtered 
        Lots table."
        """
        lots = self._lots_by_type.get(lot_type, [])
        if not lots:
            return None
        
        # Find the first lot of this type in the sorted list
        for lot in self._sorted_lots:
            if lot.remaining_quantity > 0:
                lt = lot.get_lot_type()
                if lt and lt.value == lot_type:
                    return lot
        
        return lots[0] if lots else None
    
    def _select_one_way(self, step: TaxWaterfallStep, parameters: Parameters,
                       rdcpa: float) -> Optional[LotSelectionResult]:
        """
        Select a single lot for 1-way allocation.
        
        Per PRD v1.1:
        - For steps 1-4: Return lot with PTV = Min(RCF/pnl_to_value, current_value)
        - For steps 5-6: Return lot with PTV = Min(ROID/pnl_to_value, current_value)
        - For steps 11-14: Return lot with PTV = current_value
        """
        lot_type = step.return_types[0]
        lot = self._get_first_lot_of_type(lot_type, parameters)
        
        if lot is None:
            return None
        
        # Calculate PTV based on step
        step_num = step.step
        
        if step_num == 1:  # STG vs CF-STL
            ptv = self._calculate_ptv_gain_vs_cf(lot, abs(parameters.rem_cfstl))
        elif step_num == 2:  # LTG vs CF-LTL
            ptv = self._calculate_ptv_gain_vs_cf(lot, abs(parameters.rem_cfltl))
        elif step_num == 3:  # STG vs CF-LTL
            ptv = self._calculate_ptv_gain_vs_cf(lot, abs(parameters.rem_cfltl))
        elif step_num == 4:  # LTG vs CF-STL
            ptv = self._calculate_ptv_gain_vs_cf(lot, abs(parameters.rem_cfstl))
        elif step_num == 5:  # STL vs OID
            ptv = self._calculate_ptv_loss_vs_oid(lot, abs(parameters.rem_oid))
        elif step_num == 6:  # LTL vs OID
            ptv = self._calculate_ptv_loss_vs_oid(lot, abs(parameters.rem_oid))
        elif step_num in [11, 12, 13, 14]:  # Realize steps
            # PTV = Lots.current_value
            ptv = lot.current_value
        else:
            ptv = lot.current_value
        
        return LotSelectionResult(
            lots=[(lot, ptv)],
            tw_step=step.step,
            is_two_way=False
        )
    
    def _select_two_way(self, step: TaxWaterfallStep, parameters: Parameters,
                       rdcpa: float) -> Optional[LotSelectionResult]:
        """
        Select two lots for 2-way allocation (Steps 7-10).
        
        Per PRD v1.1:
        - Go to first record of gains set and first record of losses set
        - Calculate PTVs using the 2-way formula
        - Return both lots with their PTVs
        """
        type1, type2 = step.return_types  # e.g., ["STG", "STL"]
        
        lot1 = self._get_first_lot_of_type(type1, parameters)
        lot2 = self._get_first_lot_of_type(type2, parameters)
        
        if lot1 is None or lot2 is None:
            return None
        
        # Determine which is gain and which is loss
        if lot1.ur_pnl >= 0:
            gain_lot = lot1
            loss_lot = lot2
        else:
            gain_lot = lot2
            loss_lot = lot1
        
        # Calculate PTVs using 2-way formula
        ptv_gain, ptv_loss = self._calculate_ptv_two_way(gain_lot, loss_lot)
        
        # Return lots in original order (type1, type2) with their PTVs
        if lot1.ur_pnl >= 0:
            result_lots = [(lot1, ptv_gain), (lot2, ptv_loss)]
        else:
            result_lots = [(lot1, ptv_loss), (lot2, ptv_gain)]
        
        return LotSelectionResult(
            lots=result_lots,
            tw_step=step.step,
            is_two_way=True
        )
    
    def get_waterfall_status(self, lots: List[Lot], parameters: Parameters) -> List[Dict]:
        """
        Get the current status of all Tax Waterfall steps.
        
        Returns a list of dictionaries with step information and active status.
        """
        eligible_lots = self.dps.filter_eligible_lots(
            lots, 
            min_value=parameters.min_lot_value
        )
        
        self._sorted_lots = self.dps.sort_lots(eligible_lots, parameters)
        self._lots_by_type = self.dps.get_lots_by_type(self._sorted_lots)
        
        status = []
        for step_config in TAX_WATERFALL_CONFIG:
            step = deepcopy(step_config)
            is_active = self._is_step_active(step, parameters)
            
            # Calculate PTV for display if active
            ptv = 0
            if is_active:
                if step.is_two_way():
                    # For 2-way, show combined PTV
                    result = self._select_two_way(step, parameters, float('inf'))
                    if result:
                        ptv = sum(p for _, p in result.lots)
                else:
                    result = self._select_one_way(step, parameters, float('inf'))
                    if result:
                        ptv = result.lots[0][1]
            
            status.append({
                "step": step.step,
                "title": step.title,
                "description": step.description,
                "return_types": step.return_types,
                "allocation_type": step.allocation_type,
                "active": is_active,
                "twsmv": ptv  # Using twsmv for backward compatibility with UI
            })
        
        return status
