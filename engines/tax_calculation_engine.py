"""
Tax Calculation Engine (TCE)

Calculates the client's tax obligation based on realized gains and losses.
Implements IRS capital gains netting rules exactly per PRD:

1. First Netting: Net STG with STL, net LTG with LTL
2. Second Netting: Apply carry-forward losses (CF-STL to STG, CF-LTL to LTG)
3. Third Netting: Cross ST/LT netting (6 cases per PRD table)
4. Calculate OID
5. Determine carry-forwards for next year
6. Calculate tax obligation

All formulas match the PRD Tax Calculation Engine section.
"""

from typing import List, Optional

try:
    from ..models import Sale, Parameters, TaxCalculationResult
except ImportError:
    from models import Sale, Parameters, TaxCalculationResult


class TaxCalculationEngine:
    """
    The Tax Calculation Engine computes the client's tax liability.
    
    It processes all sales to determine:
    - Net gains and losses by category
    - Ordinary Income Deduction usage
    - Carry-forward losses for next year
    - Total tax obligation
    
    All calculations follow the formulas specified in the PRD.
    """
    
    def calculate_taxes(self, sales: List[Sale], parameters: Parameters) -> TaxCalculationResult:
        """
        Calculate the complete tax position based on all sales.
        
        Per PRD TCE Algorithm:
        1. Sum totals by category (STG, STL, LTG, LTL)
        2. First Netting (same term)
        3. Second Netting (apply carry-forwards)
        4. Third Netting (cross ST/LT)
        5. Calculate OID
        6. Calculate carry-forwards for next year
        7. Calculate tax obligation
        
        Args:
            sales: List of all Sale records
            parameters: User parameters including tax rates
            
        Returns:
            TaxCalculationResult with complete tax analysis
        """
        result = TaxCalculationResult()
        
        # =====================================================================
        # Step 1: Sum the total values of the 4 different lot categories
        # Per PRD: STG = Sales_value,STG, etc.
        # =====================================================================
        for sale in sales:
            if sale.stlt == "ST":
                if sale.realized_cgl >= 0:
                    result.total_stg += sale.realized_cgl
                else:
                    result.total_stl += abs(sale.realized_cgl)  # Store as positive
            else:  # LT
                if sale.realized_cgl >= 0:
                    result.total_ltg += sale.realized_cgl
                else:
                    result.total_ltl += abs(sale.realized_cgl)  # Store as positive
        
        # Per PRD Step 2: Assign negative values to STL and LTL
        # STL = -1 x abs(Realized STL)
        # LTL = -1 x abs(Realized LTL)
        stl = -result.total_stl  # Now negative
        ltl = -result.total_ltl  # Now negative
        stg = result.total_stg   # Positive
        ltg = result.total_ltg   # Positive
        
        # Store in result (losses as negative)
        result.total_stl = stl
        result.total_ltl = ltl
        
        # =====================================================================
        # Step 3: First Netting - Net within same term
        # Per PRD:
        #   STG' = Max(STG + STL, 0)
        #   STL' = Min(0, STG + STL)
        #   LTG' = Max(LTG + LTL, 0)
        #   LTL' = Min(0, LTG + LTL)  [Note: PRD has typo, shows STG+STL]
        # =====================================================================
        stg_prime = max(stg + stl, 0)
        stl_prime = min(0, stg + stl)
        ltg_prime = max(ltg + ltl, 0)
        ltl_prime = min(0, ltg + ltl)
        
        # Store first netting results
        result.net_st = stg + stl  # Net ST position (could be + or -)
        result.net_lt = ltg + ltl  # Net LT position (could be + or -)
        result.first_net_stg = stg_prime
        result.first_net_stl = stl_prime
        result.first_net_ltg = ltg_prime
        result.first_net_ltl = ltl_prime
        
        # =====================================================================
        # Step 4: Second Netting - Apply Carry Forward losses
        # Per PRD:
        #   STG'' = If STG' >= 0:
        #             If STG' + CF_STL >= 0: STG'' = STG' + CF_STL
        #             Else: STG'' = 0
        #   STL'' = If STL' < 0: STL'' = STL'
        #           Elif STG' + CF_STL < 0: STL'' = STG' + CF_STL
        #           Else: STL'' = 0
        # (Same pattern for LT with CF_LTL)
        # =====================================================================
        cf_stl = parameters.cfstl  # Negative
        cf_ltl = parameters.cfltl  # Negative
        
        # Apply CF-STL to ST position
        if stg_prime >= 0:
            if stg_prime + cf_stl >= 0:
                stg_double_prime = stg_prime + cf_stl
            else:
                stg_double_prime = 0
        else:
            stg_double_prime = 0
        
        if stl_prime < 0:
            stl_double_prime = stl_prime
        elif stg_prime + cf_stl < 0:
            stl_double_prime = stg_prime + cf_stl
        else:
            stl_double_prime = 0
        
        # Apply CF-LTL to LT position
        if ltg_prime >= 0:
            if ltg_prime + cf_ltl >= 0:
                ltg_double_prime = ltg_prime + cf_ltl
            else:
                ltg_double_prime = 0
        else:
            ltg_double_prime = 0
        
        if ltl_prime < 0:
            ltl_double_prime = ltl_prime
        elif ltg_prime + cf_ltl < 0:
            ltl_double_prime = ltg_prime + cf_ltl
        else:
            ltl_double_prime = 0
        
        # Store after CF application
        result.net_st_after_cf = stg_double_prime + stl_double_prime
        result.net_lt_after_cf = ltg_double_prime + ltl_double_prime
        result.second_net_stg = stg_double_prime
        result.second_net_stl = stl_double_prime
        result.second_net_ltg = ltg_double_prime
        result.second_net_ltl = ltl_double_prime
        
        # =====================================================================
        # Step 5: Third Netting - Cross ST/LT per PRD table
        # Per PRD Table with 6 cases:
        #   Case 1: LTG & STG (both gains, keep separate)
        #   Case 2: STG (STG > 0, LTL < 0, STG wins)
        #   Case 3: LTG (LTG > 0, STL < 0, LTG wins)
        #   Case 4: STL (LTG > 0, STL < 0, STL wins)
        #   Case 5: LTL (STG > 0, LTL < 0, LTL wins)
        #   Case 6: STL & LTL (both losses, keep separate)
        # =====================================================================
        stg_triple_prime = 0
        stl_triple_prime = 0
        ltg_triple_prime = 0
        ltl_triple_prime = 0
        
        # Use the double-prime values
        STG = stg_double_prime
        STL = stl_double_prime
        LTG = ltg_double_prime
        LTL = ltl_double_prime
        
        # Case 1: Both are gains (LTG > 0, STG > 0, LTL = 0, STL = 0)
        if LTG > 0 and STG > 0 and LTL == 0 and STL == 0:
            stg_triple_prime = STG
            ltg_triple_prime = LTG
            stl_triple_prime = 0
            ltl_triple_prime = 0
        
        # Case 2: STG wins (LTG = 0, STG > 0, LTL < 0, STL = 0, LTL + STG > 0)
        elif LTG == 0 and STG > 0 and LTL < 0 and STL == 0 and (LTL + STG) > 0:
            stg_triple_prime = LTL + STG
            stl_triple_prime = 0
            ltg_triple_prime = 0
            ltl_triple_prime = 0
        
        # Case 3: LTG wins (LTG > 0, STG = 0, LTL = 0, STL < 0, LTG + STL > 0)
        elif LTG > 0 and STG == 0 and LTL == 0 and STL < 0 and (LTG + STL) > 0:
            stg_triple_prime = 0
            stl_triple_prime = 0
            ltg_triple_prime = STL + LTG
            ltl_triple_prime = 0
        
        # Case 4: STL wins (LTG > 0, STG = 0, LTL = 0, STL < 0, LTG + STL < 0)
        elif LTG > 0 and STG == 0 and LTL == 0 and STL < 0 and (LTG + STL) < 0:
            stg_triple_prime = 0
            stl_triple_prime = STL + LTG
            ltg_triple_prime = 0
            ltl_triple_prime = 0
        
        # Case 5: LTL wins (LTG = 0, STG > 0, LTL < 0, STL = 0, LTL + STG < 0)
        elif LTG == 0 and STG > 0 and LTL < 0 and STL == 0 and (LTL + STG) < 0:
            stg_triple_prime = 0
            stl_triple_prime = 0
            ltg_triple_prime = 0
            ltl_triple_prime = LTL + STG
        
        # Case 6: Both losses (LTG = 0, STG = 0, and either STL < 0 or LTL < 0)
        elif LTG == 0 and STG == 0 and (STL < 0 or LTL < 0 or (STL == 0 and LTL == 0)):
            stg_triple_prime = 0
            stl_triple_prime = STL
            ltg_triple_prime = 0
            ltl_triple_prime = LTL
        
        # Additional cases not explicitly in PRD table but logically needed:
        # Both gains but with some losses present
        elif STG > 0 and LTG > 0:
            # Net each pair
            if STL < 0:
                net_st = STG + STL
                stg_triple_prime = max(net_st, 0)
                stl_triple_prime = min(net_st, 0)
            else:
                stg_triple_prime = STG
                stl_triple_prime = 0
            
            if LTL < 0:
                net_lt = LTG + LTL
                ltg_triple_prime = max(net_lt, 0)
                ltl_triple_prime = min(net_lt, 0)
            else:
                ltg_triple_prime = LTG
                ltl_triple_prime = 0
        
        # STG vs LTL (STG > 0, LTL < 0, no STL, no LTG)
        elif STG > 0 and LTL < 0 and STL == 0 and LTG == 0:
            net = STG + LTL
            if net > 0:
                stg_triple_prime = net
                ltl_triple_prime = 0
            else:
                stg_triple_prime = 0
                ltl_triple_prime = net
            stl_triple_prime = 0
            ltg_triple_prime = 0
        
        # LTG vs STL (LTG > 0, STL < 0, no LTL, no STG)
        elif LTG > 0 and STL < 0 and LTL == 0 and STG == 0:
            net = LTG + STL
            if net > 0:
                ltg_triple_prime = net
                stl_triple_prime = 0
            else:
                ltg_triple_prime = 0
                stl_triple_prime = net
            stg_triple_prime = 0
            ltl_triple_prime = 0
        
        # Default fallback
        else:
            stg_triple_prime = STG
            stl_triple_prime = STL
            ltg_triple_prime = LTG
            ltl_triple_prime = LTL
        
        # Store final values
        result.final_stg = stg_triple_prime
        result.final_stl = stl_triple_prime
        result.final_ltg = ltg_triple_prime
        result.final_ltl = ltl_triple_prime
        
        # =====================================================================
        # Step 6: Calculate OID (Ordinary Income Deduction)
        # Per PRD:
        #   OID = Max(OID_Limit, STL''') + Max(OID_Limit - Max(OID_Limit, STL'''), LTL''')
        # =====================================================================
        oid_limit = parameters.oid_limit  # Negative (e.g., -3000)
        
        # First apply STL to OID
        oid_from_stl = max(oid_limit, stl_triple_prime)
        
        # Remaining OID capacity after STL
        remaining_oid_capacity = oid_limit - oid_from_stl
        
        # Then apply LTL to remaining OID
        oid_from_ltl = max(remaining_oid_capacity, ltl_triple_prime)
        
        # Total OID applied (will be negative or zero)
        result.oid_applied = oid_from_stl + oid_from_ltl
        
        # =====================================================================
        # Step 7: Calculate Carry-Forwards for next year
        # Per PRD:
        #   RemCFSTL = STL''' - Max(OID_Limit, STL''')
        #   RemCFLTL = LTL''' - Max(OID_Limit - Max(OID_Limit, STL'''), LTL''')
        # =====================================================================
        result.next_year_cfstl = stl_triple_prime - oid_from_stl
        result.next_year_cfltl = ltl_triple_prime - oid_from_ltl
        
        # =====================================================================
        # Step 8: Calculate Tax Obligation
        # Per PRD:
        #   TAX = ((STG''' + OID) x fed_OI_marginal_tax_rate) +
        #         (LTG''' x fed_CG_marginal_tax_rate) +
        #         (STG''' + LTG''') x state_income_marginal_tax_rate)
        # =====================================================================
        fed_oi_rate = parameters.fed_oi_marginal_tax_rate
        fed_cg_rate = parameters.fed_cg_marginal_tax_rate
        state_rate = parameters.state_income_marginal_tax_rate
        
        # Federal OI tax on STG (reduced by OID)
        # OID is negative, so this reduces the taxable amount
        taxable_stg = stg_triple_prime + result.oid_applied
        if taxable_stg < 0:
            taxable_stg = 0
        result.fed_oi_tax = taxable_stg * fed_oi_rate
        
        # Federal CG tax on LTG
        result.fed_cg_tax = ltg_triple_prime * fed_cg_rate
        
        # State tax on all gains
        result.state_tax = (stg_triple_prime + ltg_triple_prime) * state_rate
        
        # Total tax
        result.total_tax = result.fed_oi_tax + result.fed_cg_tax + result.state_tax
        
        return result
    
    def update_parameters_from_result(self, result: TaxCalculationResult,
                                      parameters: Parameters) -> Parameters:
        """
        Update the remaining carry-forward and OID values in parameters.

        This should be called after tax calculation to track running values
        for subsequent lot selection.

        Args:
            result: Tax calculation result
            parameters: Parameters to update

        Returns:
            Updated parameters
        """
        # Calculate how much CF was used
        # CF used = original CF - what's carried forward to next year

        # For CFSTL: used amount is original minus what's left
        if result.net_st > 0:
            # Had ST gains, some CF-STL was used
            used_cfstl = min(abs(parameters.cfstl), result.total_stg)
            parameters.rem_cfstl = parameters.cfstl + used_cfstl
        else:
            # No ST gains, CF-STL wasn't used
            parameters.rem_cfstl = parameters.cfstl

        # For CFLTL
        if result.net_lt > 0:
            used_cfltl = min(abs(parameters.cfltl), result.total_ltg)
            parameters.rem_cfltl = parameters.cfltl + used_cfltl
        else:
            parameters.rem_cfltl = parameters.cfltl

        # Update remaining OID
        parameters.rem_oid = parameters.oid_limit - result.oid_applied

        return parameters
    
    def get_tax_summary(self, result: TaxCalculationResult) -> dict:
        """
        Get a human-readable summary of the tax calculation.
        
        Args:
            result: Tax calculation result
            
        Returns:
            Dictionary with formatted summary values
        """
        return {
            "Realized Short-Term Gains": f"${result.total_stg:,.2f}",
            "Realized Short-Term Losses": f"${result.total_stl:,.2f}",
            "Realized Long-Term Gains": f"${result.total_ltg:,.2f}",
            "Realized Long-Term Losses": f"${result.total_ltl:,.2f}",
            "Net Short-Term": f"${result.net_st:,.2f}",
            "Net Long-Term": f"${result.net_lt:,.2f}",
            "Net ST after CF": f"${result.net_st_after_cf:,.2f}",
            "Net LT after CF": f"${result.net_lt_after_cf:,.2f}",
            "Final Taxable STG": f"${result.final_stg:,.2f}",
            "Final Taxable LTG": f"${result.final_ltg:,.2f}",
            "Final STL": f"${result.final_stl:,.2f}",
            "Final LTL": f"${result.final_ltl:,.2f}",
            "OID Applied": f"${result.oid_applied:,.2f}",
            "Next Year CF-STL": f"${result.next_year_cfstl:,.2f}",
            "Next Year CF-LTL": f"${result.next_year_cfltl:,.2f}",
            "Federal OI Tax": f"${result.fed_oi_tax:,.2f}",
            "Federal CG Tax": f"${result.fed_cg_tax:,.2f}",
            "State Tax": f"${result.state_tax:,.2f}",
            "Total Tax Obligation": f"${result.total_tax:,.2f}",
        }
