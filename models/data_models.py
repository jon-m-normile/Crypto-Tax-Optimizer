"""
Data Models for the Crypto Tax Optimization Demonstration System

This module defines the core data structures used throughout the system:
- Lot: Individual cryptocurrency purchase lots
- Sale: Records of lot sales
- Purchase: Debit card purchase records
- Parameters: User configuration settings
- TaxWaterfallStep: Configuration for each step in the tax waterfall
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Literal
from enum import Enum
import uuid


class LotType(Enum):
    """Classification of lots by holding period and gain/loss status"""
    STG = "STG"  # Short-term gain
    STL = "STL"  # Short-term loss
    LTG = "LTG"  # Long-term gain
    LTL = "LTL"  # Long-term loss


class PurchaseStatus(Enum):
    """Status of a debit card purchase"""
    NEW = "New"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    INCOMPLETE = "Incomplete"


@dataclass
class Lot:
    """
    Represents a single cryptocurrency purchase lot.
    
    Attributes:
        lot_id: Unique identifier for the lot
        timestamp: When the lot was purchased
        currency: Cryptocurrency ticker (BTC, ETH, etc.)
        quantity: Original quantity purchased
        cost_basis: Total USD cost including fees
        remaining_quantity: Current quantity after sales
        eligible_currency: Whether this currency can be sold (for future use)
    
    Calculated fields (set by DataProcessingService):
        stlt: Short-term or long-term classification
        current_mkt_price: Real-time market price
        current_value: remaining_quantity * current_mkt_price
        ur_pnl: Unrealized P&L
        pnl_to_value: Ratio of P&L to value
    """
    lot_id: str
    timestamp: datetime
    currency: str
    quantity: float
    cost_basis: float
    remaining_quantity: float = None
    eligible_currency: bool = True
    
    # Calculated fields
    stlt: Optional[Literal["ST", "LT"]] = None
    current_mkt_price: float = 0.0
    current_value: float = 0.0
    ur_pnl: float = 0.0
    pnl_to_value: float = 0.0
    cost_basis_price: float = 0.0  # cost_basis / quantity
    
    def __post_init__(self):
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity
        if self.quantity > 0:
            self.cost_basis_price = self.cost_basis / self.quantity
    
    def get_lot_type(self) -> Optional[LotType]:
        """Determine the lot type based on ST/LT status and gain/loss"""
        if self.stlt is None or self.current_value == 0:
            return None
        
        is_gain = self.ur_pnl >= 0
        if self.stlt == "ST":
            return LotType.STG if is_gain else LotType.STL
        else:
            return LotType.LTG if is_gain else LotType.LTL
    
    def update_calculated_fields(self, current_price: float, current_date: datetime = None):
        """Update all calculated fields based on current market price"""
        if current_date is None:
            current_date = datetime.now()
        
        # Determine ST/LT status
        days_held = (current_date - self.timestamp).days
        self.stlt = "LT" if days_held > 365 else "ST"
        
        # Update market-based calculations
        self.current_mkt_price = current_price
        self.current_value = self.remaining_quantity * current_price
        
        # Calculate unrealized P&L
        # ur_pnl = current_value - (cost_basis * remaining_quantity / quantity)
        if self.quantity > 0:
            proportional_cost_basis = self.cost_basis * (self.remaining_quantity / self.quantity)
            self.ur_pnl = self.current_value - proportional_cost_basis
        else:
            self.ur_pnl = 0.0
        
        # Calculate P&L to value ratio
        if self.current_value > 0:
            self.pnl_to_value = self.ur_pnl / self.current_value
        else:
            self.pnl_to_value = 0.0


@dataclass
class Sale:
    """
    Records a single sale transaction executed by the Trade Engine.
    
    Attributes:
        sales_id: Unique identifier for the sale
        purchase_id: Links to the Purchase that triggered this sale
        lot_id: Links to the Lot being sold
        tw_step: Tax Waterfall step that selected this lot (1-14)
        quantity_sold: Amount of cryptocurrency sold
        quantity_remaining: Lot's remaining quantity after this sale
        currency: Cryptocurrency ticker
        price: USD price at time of sale (from Kraken API)
        settlement_amount: USD value received (price * quantity_sold)
        realized_cgl: Capital gain/loss realized
        stlt: ST or LT at time of sale
    """
    sales_id: str
    purchase_id: str
    lot_id: str
    tw_step: int
    quantity_sold: float
    quantity_remaining: float
    currency: str
    price: float
    settlement_amount: float
    realized_cgl: float
    stlt: Literal["ST", "LT"]
    timestamp: datetime = field(default_factory=datetime.now)
    
    @staticmethod
    def create(purchase_id: str, lot: 'Lot', tw_step: int, 
               quantity_sold: float, price: float) -> 'Sale':
        """Factory method to create a Sale from a Lot"""
        settlement_amount = price * quantity_sold
        
        # Calculate realized CGL using the lot's pnl_to_value ratio
        realized_cgl = settlement_amount * lot.pnl_to_value
        
        return Sale(
            sales_id=str(uuid.uuid4())[:8],
            purchase_id=purchase_id,
            lot_id=lot.lot_id,
            tw_step=tw_step,
            quantity_sold=quantity_sold,
            quantity_remaining=lot.remaining_quantity - quantity_sold,
            currency=lot.currency,
            price=price,
            settlement_amount=settlement_amount,
            realized_cgl=realized_cgl,
            stlt=lot.stlt
        )


@dataclass
class Purchase:
    """
    Records a debit card purchase and tracks its processing status.
    
    Attributes:
        purchase_id: Unique identifier
        status: Current processing status
        dcpa: Original Debit Card Purchase Amount
        rdcpa: Remaining amount to be settled
        total_settlement_amount: Sum of all sales for this purchase
        num_sales: Count of sales executed
        total_stl/ltl/stg/ltg: Realized gains/losses by category
        description: Optional purchase description
        category: Optional purchase category
    """
    purchase_id: str
    dcpa: float
    status: PurchaseStatus = PurchaseStatus.NEW
    rdcpa: float = None
    total_settlement_amount: float = 0.0
    num_sales: int = 0
    total_stl: float = 0.0
    total_ltl: float = 0.0
    total_stg: float = 0.0
    total_ltg: float = 0.0
    description: str = ""
    category: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if self.rdcpa is None:
            self.rdcpa = self.dcpa
    
    def add_sale(self, sale: Sale):
        """Update purchase totals when a sale is added"""
        self.total_settlement_amount += sale.settlement_amount
        self.rdcpa = self.dcpa - self.total_settlement_amount
        self.num_sales += 1
        
        # Categorize the realized CGL
        if sale.stlt == "ST":
            if sale.realized_cgl >= 0:
                self.total_stg += sale.realized_cgl
            else:
                self.total_stl += sale.realized_cgl
        else:  # LT
            if sale.realized_cgl >= 0:
                self.total_ltg += sale.realized_cgl
            else:
                self.total_ltl += sale.realized_cgl
        
        # Update status
        if self.rdcpa <= 0.01:  # Small threshold for floating point
            self.status = PurchaseStatus.COMPLETED
            self.rdcpa = 0.0
        else:
            self.status = PurchaseStatus.PROCESSING


@dataclass
class Parameters:
    """
    User configuration parameters for the tax optimization system.
    
    Attributes:
        lot_order_index: Sort by "pnl" or "value"
        gain_lot_ordering: "high-to-low" or "low-to-high"
        loss_lot_ordering: "high-to-low" or "low-to-high"
        min_lot_value: Minimum value for a lot to be eligible
        cfstl: Carry-forward short-term loss (always negative)
        cfltl: Carry-forward long-term loss (always negative)
        rem_cfstl: Remaining CFSTL after gains applied
        rem_cfltl: Remaining CFLTL after gains applied
        oid_limit: Ordinary income deduction limit (-3000 or -6000)
        rem_oid: Remaining OID after losses applied
        fed_oi_marginal_tax_rate: Federal ordinary income tax rate
        fed_cg_marginal_tax_rate: Federal capital gains tax rate
        state_income_marginal_tax_rate: State income tax rate
    """
    lot_order_index: Literal["pnl", "value"] = "pnl"
    gain_lot_ordering: Literal["high-to-low", "low-to-high"] = "high-to-low"
    loss_lot_ordering: Literal["high-to-low", "low-to-high"] = "high-to-low"
    min_lot_value: float = 10.0
    cfstl: float = 0.0  # Always negative or zero
    cfltl: float = 0.0  # Always negative or zero
    rem_cfstl: float = None
    rem_cfltl: float = None
    oid_limit: float = -3000.0  # Always negative
    rem_oid: float = None
    fed_oi_marginal_tax_rate: float = 0.24
    fed_cg_marginal_tax_rate: float = 0.15
    state_income_marginal_tax_rate: float = 0.05
    
    def __post_init__(self):
        # Ensure CF values are negative
        self.cfstl = -abs(self.cfstl) if self.cfstl != 0 else 0.0
        self.cfltl = -abs(self.cfltl) if self.cfltl != 0 else 0.0
        self.oid_limit = -abs(self.oid_limit) if self.oid_limit != 0 else -3000.0
        
        # Initialize remaining values
        if self.rem_cfstl is None:
            self.rem_cfstl = self.cfstl
        if self.rem_cfltl is None:
            self.rem_cfltl = self.cfltl
        if self.rem_oid is None:
            self.rem_oid = self.oid_limit
    
    def reset_remaining_values(self):
        """Reset remaining values to initial carry-forward amounts"""
        self.rem_cfstl = self.cfstl
        self.rem_cfltl = self.cfltl
        self.rem_oid = self.oid_limit


@dataclass
class TaxWaterfallStep:
    """
    Configuration for a single step in the Tax Waterfall.
    
    Attributes:
        step: Step number (1-14)
        title: Short title for the step
        description: Detailed description
        return_types: List of lot types this step returns (e.g., ["STG"] or ["STG", "STL"])
        allocation_type: "1-way" or "2-way"
        active: Whether this step is currently active
        twsmv: Tax Waterfall Step Maximum Value
    """
    step: int
    title: str
    description: str
    return_types: List[str]  # e.g., ["STG"] or ["STG", "STL"]
    allocation_type: Literal["1-way", "2-way"]
    active: bool = False
    twsmv: float = 0.0
    
    def is_two_way(self) -> bool:
        return self.allocation_type == "2-way"


# Define the 14-step Tax Waterfall configuration
TAX_WATERFALL_CONFIG = [
    TaxWaterfallStep(
        step=1,
        title="STG offset vs. CF-STL",
        description="Sell available STG lots and allocate resulting gain against remaining Carry Forward Short Term Loss",
        return_types=["STG"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=2,
        title="LTG offset vs. CF-LTL",
        description="Sell available LTG lots and allocate resulting gain against remaining Carry Forward Long Term Loss",
        return_types=["LTG"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=3,
        title="STG offset vs. CF-LTL",
        description="Sell available STG lots and allocate resulting gain against remaining Carry Forward Long Term Loss",
        return_types=["STG"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=4,
        title="LTG offset vs. CF-STL",
        description="Sell available LTG lots and allocate resulting gain against remaining Carry Forward Short Term Loss",
        return_types=["LTG"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=5,
        title="STL allocated to OID",
        description="Sell available STL lots and allocate against remaining Ordinary Income Deduction",
        return_types=["STL"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=6,
        title="LTL allocated to OID",
        description="Sell available LTL lots and allocate against remaining Ordinary Income Deduction",
        return_types=["LTL"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=7,
        title="STG offset vs STL",
        description="Simultaneously sell STG & STL lots such that P&L offsets to zero",
        return_types=["STG", "STL"],
        allocation_type="2-way"
    ),
    TaxWaterfallStep(
        step=8,
        title="LTG offset vs LTL",
        description="Simultaneously sell LTG & LTL lots such that P&L offsets to zero",
        return_types=["LTG", "LTL"],
        allocation_type="2-way"
    ),
    TaxWaterfallStep(
        step=9,
        title="STG offset vs LTL",
        description="Simultaneously sell STG & LTL lots such that P&L offsets to zero",
        return_types=["STG", "LTL"],
        allocation_type="2-way"
    ),
    TaxWaterfallStep(
        step=10,
        title="LTG offset vs STL",
        description="Simultaneously sell LTG & STL lots such that P&L offsets to zero",
        return_types=["LTG", "STL"],
        allocation_type="2-way"
    ),
    TaxWaterfallStep(
        step=11,
        title="Realize STL",
        description="Sell available STL lots and accrue to CF-STL for next year",
        return_types=["STL"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=12,
        title="Realize LTL",
        description="Sell available LTL lots and accrue to CF-LTL for next year",
        return_types=["LTL"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=13,
        title="Realize LTG",
        description="Sell LTG lots taxed at capital gains rate",
        return_types=["LTG"],
        allocation_type="1-way"
    ),
    TaxWaterfallStep(
        step=14,
        title="Realize STG",
        description="Sell STG lots taxed at ordinary income rate",
        return_types=["STG"],
        allocation_type="1-way"
    ),
]


@dataclass
class TaxCalculationResult:
    """
    Results from the Tax Calculation Engine.
    
    Contains the complete tax position including:
    - Realized gains/losses by category
    - Net positions after netting
    - OID applied
    - Carry-forward amounts for next year
    - Total tax obligation
    """
    # Raw totals from sales
    total_stg: float = 0.0
    total_stl: float = 0.0
    total_ltg: float = 0.0
    total_ltl: float = 0.0
    
    # After first netting (ST vs ST, LT vs LT)
    net_st: float = 0.0  # Positive = gain, negative = loss
    net_lt: float = 0.0
    first_net_stg: float = 0.0
    first_net_stl: float = 0.0
    first_net_ltg: float = 0.0
    first_net_ltl: float = 0.0

    # After second netting (with carry-forwards)
    net_st_after_cf: float = 0.0
    net_lt_after_cf: float = 0.0
    second_net_stg: float = 0.0
    second_net_stl: float = 0.0
    second_net_ltg: float = 0.0
    second_net_ltl: float = 0.0
    
    # After third netting (cross ST/LT)
    final_stg: float = 0.0
    final_stl: float = 0.0
    final_ltg: float = 0.0
    final_ltl: float = 0.0
    
    # OID applied
    oid_applied: float = 0.0
    
    # Carry-forward for next year
    next_year_cfstl: float = 0.0
    next_year_cfltl: float = 0.0
    
    # Tax calculations
    fed_oi_tax: float = 0.0
    fed_cg_tax: float = 0.0
    state_tax: float = 0.0
    total_tax: float = 0.0
