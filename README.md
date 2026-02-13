# 3F Crypto Tax Optimization Demonstration System

A comprehensive Python/Streamlit application demonstrating intelligent tax-optimized cryptocurrency lot selection using the 14-step Tax Waterfall methodology.

## Overview

This system allows clients to:
- Upload their cryptocurrency portfolio (purchase lots)
- Configure tax parameters (carry-forward losses, tax rates, etc.)
- Process simulated debit card purchases
- See real-time lot selection based on tax optimization
- Track cumulative tax obligations

## Key Features

### 14-Step Tax Waterfall Algorithm

The system implements a sophisticated lot selection algorithm that minimizes tax liability:

1. **Steps 1-4**: Offset gains against carry-forward losses (STG vs CF-STL, LTG vs CF-LTL, etc.)
2. **Steps 5-6**: Allocate losses to Ordinary Income Deduction ($3,000 limit)
3. **Steps 7-10**: 2-way allocation to offset gains against losses (net to zero)
4. **Steps 11-12**: Realize losses for carry-forward to next year
5. **Steps 13-14**: Realize gains (LTG first for lower tax rate)

### Real-Time Price Integration

- Connects to Kraken API for live cryptocurrency prices
- Supports major cryptocurrencies (BTC, ETH, SOL, ADA, LINK, etc.)
- Price caching for performance

### Persistent State

- Session state persists between browser refreshes
- Save/load functionality for long-term persistence
- Export capabilities for audit trails

## Installation

```bash
# Clone or copy the project
cd tax_optimizer

# Install dependencies
pip install -r requirements.txt

# Run the application
streamlit run app.py
```

## Project Structure

```
tax_optimizer/
├── app.py                 # Main Streamlit application
├── requirements.txt       # Python dependencies
├── models/
│   ├── __init__.py
│   └── data_models.py     # Lot, Sale, Purchase, Parameters, etc.
├── services/
│   ├── __init__.py
│   ├── data_input_service.py     # CSV parsing
│   ├── data_processing_service.py # Lot enrichment
│   ├── market_data_service.py    # Kraken API integration
│   └── state_manager.py          # Persistence
├── engines/
│   ├── __init__.py
│   ├── lot_selection_engine.py   # Tax Waterfall algorithm
│   ├── tax_calculation_engine.py # IRS netting rules
│   └── trade_engine.py           # DCPO orchestration
└── data/
    ├── sample_purchase_lots.csv
    └── sample_user_parameters.csv
```

## Data Files

### Purchase_Lots.csv

Each row represents a cryptocurrency purchase lot:

| Column | Description |
|--------|-------------|
| lot_id | Unique identifier |
| timestamp | Purchase date/time (YYYY-MM-DD HH:MM:SS) |
| currency | Crypto symbol (BTC, ETH, SOL, etc.) |
| quantity | Amount purchased |
| cost_basis | Total USD cost including fees |

### User_Parameters.csv

Configuration settings:

| Parameter | Description | Valid Values |
|-----------|-------------|--------------|
| lot_order_index | Sort criteria | "pnl" or "value" |
| gain_lot_ordering | Gain sort direction | "high-to-low" or "low-to-high" |
| loss_lot_ordering | Loss sort direction | "high-to-low" or "low-to-high" |
| min_lot_value | Minimum trade value | Numeric |
| carry_forward_stl | CF short-term loss | Numeric (positive) |
| carry_forward_ltl | CF long-term loss | Numeric (positive) |
| oid_limit | OI deduction limit | 3000 or 6000 |
| fed_oi_marginal_tax_rate | Federal OI rate | 0.00-1.00 |
| fed_cg_marginal_tax_rate | Federal CG rate | 0.00-1.00 |
| state_income_marginal_tax_rate | State rate | 0.00-1.00 |

## Usage

1. **Load Data**: Upload CSV files or click "Load Sample Data"
2. **Configure Parameters**: Adjust tax rates and preferences in sidebar
3. **Process Purchase**: Enter amount and click "Process"
4. **Review Results**: Check Tax Status, Portfolio, and Tax Detail tabs

## Tax Calculation Logic

The Tax Calculation Engine implements IRS capital gains netting rules:

1. **First Netting**: Net ST gains/losses together, LT gains/losses together
2. **Second Netting**: Apply carry-forward losses to net gains
3. **Third Netting**: Cross-net remaining ST/LT positions
4. **OID Application**: Apply up to $3,000 of losses against ordinary income
5. **Carry-Forward**: Calculate losses to carry forward to next year
6. **Tax Calculation**: Apply appropriate tax rates

## API Reference

### Trade Engine

```python
trade_engine = TradeEngine()

# Validate a purchase
is_valid, message = trade_engine.validate_purchase(lots, dcpa, parameters)

# Process a purchase
purchase, sales, tax_result = trade_engine.process_purchase(
    lots=lots,
    parameters=parameters,
    dcpa=500.0,
    description="Test purchase",
    category="General",
    existing_sales=[]
)
```

### Lot Selection Engine

```python
lse = LotSelectionEngine()

# Get selected lots
result = lse.select_lots(lots, parameters, rdcpa=500.0)
# result.lots = [(Lot, max_sell_value), ...]
# result.tw_step = 7  # Tax Waterfall step used
# result.is_two_way = True  # 2-way allocation

# Get waterfall status
status = lse.get_waterfall_status(lots, parameters)
```

### Tax Calculation Engine

```python
tce = TaxCalculationEngine()

# Calculate taxes
result = tce.calculate_taxes(sales, parameters)
# result.total_tax
# result.fed_oi_tax
# result.fed_cg_tax
# result.next_year_cfstl
# result.next_year_cfltl
```

## License

Proprietary - 3F Payments

## Version History

- **2.0.0** - Complete rewrite with modular architecture and Streamlit UI
- **1.0.0** - Initial Google Apps Script implementation
