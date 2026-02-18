"""
Crypto Tax Optimization Demonstration System
Streamlit Application

A web-based interface for demonstrating cryptocurrency tax optimization
using the 14-step Tax Waterfall methodology.

Version 2.5.0 - Comparison tab: side-by-side FIFO/LIFO/Max-Gain/Max-Loss vs Tax Waterfall
- Fixed rem_oid/rem_cf being reset on every page rerun (now only resets on user change)
- Fixed TWS 1-6 to 7-10 transition: removed TCE override of raw CF/OID tracking
- Portfolio Detail TWS filter now checks if step is active before showing next lots
- Fixed PTV display for Steps 1-6 to use correct formulas (CF/OID based)
- Fixed TWS 1-6 transition: CF/OID now tracked from raw gains/losses (not netted)
- Fixed TWS 1-6 transition: PTV now recalculated with fresh price data
- Next Lot(s) now shown on Portfolio Detail page load (uses active TWS)
- Added PTV column to Next Lot(s) display
- Fixed lot remaining_quantity not persisting after sales
- Fixed OID display (now shows consumed amount as "Ordinary Income Deduction")
- Fixed Tax Waterfall activation logic for steps 5 & 6
- Enhanced Portfolio Detail with lot type values and P&L
- Added TWS filter dropdown to Lot Detail
- Added timestamp and improved field names in Sales History
- Fixed price refresh functionality
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from typing import List, Optional, Dict

# Add parent directory to path for imports
import sys
import base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    Lot, Sale, Purchase, Parameters, TaxCalculationResult,
    PurchaseStatus, TAX_WATERFALL_CONFIG
)
from services import (
    DataInputService, load_sample_lots, load_sample_parameters,
    get_data_processing_service, get_market_data_service
)
from services.state_manager import get_state_manager
from copy import deepcopy
from engines import TradeEngine, TaxCalculationEngine, LotSelectionEngine
from engines import SimpleLotSelectionEngine, SimpleStrategy

COMPARISON_STRATEGIES = [
    SimpleStrategy.FIFO, SimpleStrategy.LIFO,
    SimpleStrategy.MAX_GAIN, SimpleStrategy.MAX_LOSS,
]
STRATEGY_LABELS = {
    SimpleStrategy.FIFO: "FIFO",
    SimpleStrategy.LIFO: "LIFO",
    SimpleStrategy.MAX_GAIN: "Max-Gain",
    SimpleStrategy.MAX_LOSS: "Max-Loss",
}

# Page configuration
st.set_page_config(
    page_title="3F Crypto Tax Optimizer",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    .tax-positive { color: #dc3545; }
    .tax-negative { color: #28a745; }
    .status-completed { color: #28a745; font-weight: bold; }
    .status-processing { color: #ffc107; font-weight: bold; }
    .status-incomplete { color: #dc3545; font-weight: bold; }
    .lot-type-tile {
        padding: 15px;
        border-radius: 8px;
        background-color: #e8eef4;
        border: 1px solid #c0c8d0;
        margin-bottom: 5px;
        font-size: 14px;
    }
    .lot-type-tile .lot-title {
        font-size: 16px;
        font-weight: bold;
        margin-bottom: 8px;
    }
    .summary-tile {
        padding: 15px;
        border-radius: 8px;
        background-color: #e8eef4;
        border: 1px solid #c0c8d0;
        margin-bottom: 10px;
        text-align: left;
    }
    .summary-tile .tile-label {
        font-size: 16px;
        font-weight: bold;
        color: #1a3a5c;
        margin-bottom: 8px;
    }
    .summary-tile .tile-value {
        font-size: 24px;
        font-weight: bold;
        color: #333;
    }
    .dashboard-tile {
        padding: 12px;
        border-radius: 8px;
        background-color: #f8f9fa;
        border: 1px solid #c0c8d0;
        margin-bottom: 5px;
        text-align: left;
    }
    .dashboard-tile .tile-label {
        font-size: 12px;
        color: #666;
        margin-bottom: 4px;
    }
    .dashboard-tile .tile-value {
        font-size: 20px;
        font-weight: bold;
        color: #333;
    }
    .tax-summary-panel {
        padding: 15px;
        border-radius: 8px;
        background-color: #f8f9fa;
        border: 1px solid #c0c8d0;
    }
    .tax-summary-panel .panel-title {
        font-size: 16px;
        font-weight: bold;
        color: #1a3a5c;
        margin-bottom: 12px;
    }
    .tax-summary-panel .summary-row {
        display: flex;
        justify-content: space-between;
        padding: 4px 0;
        font-size: 14px;
    }
    .tax-summary-panel .summary-row .label {
        color: #666;
    }
    .tax-summary-panel .summary-row .value {
        font-weight: bold;
        color: #333;
    }
    .tax-summary-panel .total-row {
        display: flex;
        justify-content: space-between;
        padding: 8px 0 4px 0;
        font-size: 16px;
        border-top: 2px solid #333;
        margin-top: 8px;
    }
    .tax-summary-panel .total-row .label {
        font-weight: bold;
        color: #1a3a5c;
    }
    .tax-summary-panel .total-row .value {
        font-weight: bold;
        color: #333;
    }
    /* Add a visual separator line below the tab bar */
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 1px solid rgba(49, 51, 63, 0.2);
        padding-bottom: 10px;
    }
    /* Add margin above tab content for visual separation */
    .stTabs [data-baseweb="tab-panel"] {
        padding-top: 15px;
    }
    /* Header section styling */
    .header-section {
        border-bottom: 1px solid rgba(49, 51, 63, 0.2);
        padding-bottom: 10px;
        margin-bottom: 15px;
    }
    /* Reduce default Streamlit padding to minimize white space */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    /* Tighten the top header/banner area */
    header[data-testid="stHeader"] {
        height: 2.5rem;
    }
    /* Hide multi-page navigation links */
    [data-testid="stSidebarNav"] {
        display: none !important;
    }

    /* --- Pentathlon Sport Loader (replaces default spinner icon) --- */
    /* Hide the default spinning circle */
    [data-testid="stSpinnerIcon"],
    .stSpinner [data-testid="stSpinnerIcon"] {
        border: none !important;
        border-radius: 0 !important;
        animation: none !important;
        width: 36px !important;
        height: 36px !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        animation: st-sport-cycle 5s infinite !important;
    }

    @keyframes st-sport-cycle {
        0%, 19.9%   { background-image: url("data:image/png;base64,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"); }
        20%, 39.9%  { background-image: url("data:image/png;base64,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"); }
        40%, 59.9%  { background-image: url("data:image/png;base64,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"); }
        60%, 79.9%  { background-image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEgAAABFCAYAAADpc6CZAAAQAUlEQVR4Xu2bebSN1RvHH1MiQgMpJZJI5gY0IGUpGTIVKkmSajUYK9UfRYOQVhkqlRQKoaSJBiFDKjJEyNAklXGlSf1+ffbyPWuf977nvOeec27d3/rZa911Ofd99/vu736G7/N99inwn7+HHRwJEShwEKDk1pGnAP31119WsGDB0DdI9rf8ZNB5BhCeW6BAAdu+fbu98MIL9umnn9pvv/1mNWvWtCuuuMIqVapk/wsg5QlAAmfhwoV25ZVX2qZNm+KM4qijjrInnnjC2rVrZ7o2P1mN/y5ZB0gL/vrrr61evXr2ww8/2CGHHOKshYHL/f7773booYfa4sWLrXbt2vnakrIOkNzmzjvvtAceeMCB88cffzhwBF6RIkUcSFdddZU999xz+dqKsg6QzLNp06b2wQcfOIvZv3+/i0cCqVChQs5qTjnlFPvss88MwPLryDOAGjVq5FwIgP7888/Y+gGKH6ypYsWKtnbtWitatGh+xceyDpBc7Oqrr7YJEyZY4cKFnQX5g88A7YILLrC33nor34LDi+UZQPPmzbMmTZo4gBiyItwLCyIuvfTSS9apUyf3Nz7PjyPrAPmLvO++++yee+4JXXevXr1s9OjRscymi3A9/0efyzUTEc+8AjfPAFLGevnll+2xxx6z5cuXO0upVq2a3XLLLY4spjME3j8FVJ4B5Kd1/g0fgvuULFnSudf06dNtyZIltmHDBvvxxx8dViVKlHA/hx9+uLuOH/5fqlQpK168uNWpU8fq1q3rriXWyarSATrVe/IUIMUedpvFfPXVVzZ8+HBXevz000+pvmPsOuIZ7HvgwIGOhP4TQOU5QFrd2LFj7e67745ZC6ARmOUyfqzh3+JNskSuU6AHKEqYvn37Wo0aNdyt/E0bkWvkk9yQpwDJDW666aZYQIYUspigDOX/XzxJC+Y3c/EDqKINxYoVs+7du1u/fv1c8SugspkR8wwg8aHrr7/eFaYCRjWZQEi0eWF/F2BBoMqUKWPXXXed3XjjjXb88cdn04Cyz4P8XRwxYoRzAx8cv+QIW4nKkLPPPttuu+02F9x37dpls2fPtvnz57tbfNf0LeqYY46xW2+91fr06ZO18iXrFiTLeffdd61FixbOlfhMLqT0n0jplTuddNJJLsP5Y+rUqfbwww/bRx995D4mFmlu/q2iGKsdM2ZMVorgrAKkxX/77bd25pln2jfffON2W0zZByqZaykwv//++3bOOee4mKN6jTmef/55GzZsmK1atSoOKHEjruXZ0INMR9YA8i0Fy3nnnXfcDgMObqXYowyVyIK4VvXbvffea3fddVcMYL8k+eWXX+yZZ56xRx55xDZu3BgDCjCJQ+vWrTOCeKYjY4AEjDJH//793e4Sd3hZVfNnnXWWrVy50vbt2xcnfYQtQMCef/75Nnfu3ByX+EARn0gCo0aNMkS6I444wrlXx44d/10XCzJZFg7XISgr0Aoc3O311183Au8XX3yRQwLxERA7Zn6YNNcTfMOGDxTEE22pSpUqWc1kubKgoLXw0pjy5MmTbeLEiS6oAgrX6TdxYMGCBXbqqacaBepTTz0Vc6FkgRqgAEAVfzKBP6gGpKJzi3hKXUgYE1Pti/kP5YXQcZBLZ82aZcQDhkBhcTyYrDJt2jRr3769A23mzJmuVPDTdBhIfhy64YYb7PHHH4/UrcXIU6nPUgFQgOXKgnbs2OFAIYvQxtFQuhVHAUB2/I477rD777/fxSKu4f6TTz7Z/VY6T7RzclMsb8WKFVnTiwTO6tWrbdKkSY5gomwmAi0SIN24detWu/DCC11MUCbSIkT+VCsh1ONOI0eOzGFZWBCWpPSfyIKU6gH2k08+cf203Ox8GPC6H+nloosusm3btlnnzp0dUGkDJP+m0Bw8eLCTLHAdxRm/rjrxxBPdA9F62Hl/KN2TYajNlKmSpXux5EcffdRuvvnmjJVHnkUyadiwocuoZNoTTjjBPv/884TMO9KCBNDtt99uDz30kNNlaNmoYMRV6GCgQbdt29bpN9p9v6xQ/QSBgyXTZU3mZopjPB+rI5ZlYkEK8vAmShE2mnWgLy1dujRhizwSIL0UrgUvYYEMuqMdOnSwbt26WYMGDWLG4ssOCpxiuMQtONKLL74YV3oki0PMR9wiZmTaHsJ6kEdYA4AxN7Jv7969EyaBSID8l9+8ebPbydKlS1urVq2sXLlyccCILAaBWbNmjRPKCO64Z1TBqhgnBg4Pgi1jvekMeQEb06VLF7c5hx12mA0ZMsTJv8lGygCFmbffTpZbyZX4P4ACDCUBu8fw20BRkoeSAAGaQJ2uzqN3p4NCwXv66afbk08+6dwrym1TBkgAKNgG1TufyFGsElghhTt37owBo4Duq4XaPT9Y6++q0MmIsPRMToPs3r3bypcv74posihekEq7KVcAJTJF7QLaDTURmYpjL7IYHxgt3i9eNW+wPa3PCaJo0OkApHuwGM4KEAcBJ9W5sgIQCyG+cGCBgtEHxgfVF7eOO+44Rxh//fXXONxFH9TTp6KHYqj28y1N/xZ7TmSZfM5RHGq7WrVqxYHjzxFmABkBpF1YtGiR0Ytn+JqzLCsIDIGSe+jdB8U0xR3uFROPihPBhSUT8JVAuCeV3lpGAOnFxY4BRyRSPEZ8iV7Xtdde6xaNpRGffDAELvfDUai/evToEVs7QZ44Qg8NV8byBC4uc+SRR7oqHivR8N0omFC4hhqSCoGCOpFikDZAAgdGSlYACL9glOkiWkEiIWdIEfTGqH0YvpAm0gizRR3AIgERHZpsSJoHIMidpFXfcihv0IJwoebNmzt+BlcLDggqx3JI+WhNlBu8I2yaIB4caQOk3SHDEAAlkGnhLJgDUgCj3hULY7GkbRaqIXAAZfz48Q5IrO3pp58OCwtxPTMuCCtXKleu7BqUlBV+nCEbQg55j71797r5Sf/EUNYQjGNpAeQXsCyWB4nTKN5AwnAlBsCIBRMf4B/oyb48wuevvPKKtW7d2hXF7K7ukSslqtuEooI178AG0CvDwiGFGrgV8zIX77Bnzx5r3Lhx6Ea4zf77wlwfJJf1DBo0yMkZvvbMdEcffbQrDYgL2hHiBt2Iiy++2FkVlb7uE6hQfg46IM+Sjrk3eDot0Upy7PwBHRyKcMYZZ0QSwoTzpgMQk0EAcR18OGg96NJDhw51i6P9M2XKFGcdBFik0Y8//tjFCV99xILU6nnwwQed9Yl1p7qHeg/NS2yhzEmk94QF7oxjkKwHC6CxF7QeMtD69evt559/tssuu8wde/FdgBhz+eWXuzoOwV2L0TUsCPfg9Ktcxk/NySwoSCtwVzYmtzTBf0ZaLkaKJVtIg1b9hcWQPQABcLAcxREWSyyCAxE827Rp4+TaoMBPYxDhH21py5YtMWEtYZAgThw488g1knOxHrgWMTJV1hz2jFwBpAch0COKaXEumP39klgDnQWCYtWqVWOpX/fxG75BrUY2QW+WXKsOSLNmzWzOnDkui1HkRrlZWHmCuyINk0UzASetIM0D0X+WLVsW210tggD82muvOfWPYCv3E4D85n529thjjzVSsYpfcSLA/f777+3NN990epMsIqp28xVK3B8ZI1NwcgWQHvbGG2+4TOTHDi0OUofUysJJnz4R5N8CkuzH+UXMn2wnHiQrmjFjhmFJWBsMOqg8+lajeXFfWs4UyhyJyQY4uQJIgY628ttvvx3Xc8cKkBGordCtKS5961EWkkvCvEm/nOtBAvX798QxjrFggVyHDiTgfEsMFrWQS1zy3HPPzRo4uQKIi1kU3VGZu14SgNh1OgVYz3fffRd6gJw5uAfwiEMQNWRcFbgClUDOGWsIHFYpAHV/sM4jK3LUhlIhFY0nWcBPK81D8iB/Xbt2dS0Sv+8OWARkTsxTO9FnCrMe7b5IIf10rkVvJhv6mYiTsUi6LBjeJBcTMNKX2Awslk6K4lsqFXpWASLlwidYCC8ERwkSQy22evXqrhWtBQUJnr/A0047zQV6ilBiBs1BUjPcChfV4SsFabkZcxJrqAEhk/CpKE0nN4CkZEE8EMuA05DSAYVijtQrc1eQ5gW//PJL14qm7ROUMHI88AAdwArgSs8++6wDBmaO7MC89OOvueYa1xpSC1sg0MYGGJ1yzbZLRQKk6A84xAGYMTGFAwiYvb77hRtBGKX46csrwXgRx0oPEDpxJrV0OLFK2YI7QRNeffXVOHEf0C655BJHIM8777yYO4lpZ2IhUfeGEkVqIYQtwAEEmDGA1a9f32UVDTIHRSU/vLisKlntFGS9aleHvSjPv/TSS11WIzkoSCs5RC0uG3/PARC1E9aAW0kXpogkheP7WAzXEG/gMyiFHJMDJF9a1ctF1UFYIvfhTgKW4pLMhNDGVxf+DWD0/jkAQuaET8h8WQBgYT2QMKQDDQpLdpezhL5r6e/+IUt/N9Uy8r8mhbXQwibFU6dJOlWhmu3slKp15QAIa8CNiEXsanAAEBaFlots4V9DfFKQ9j/nM7mW71JcT7AlS/Ij5ZFn6vheKsD4gpriW1AfSgSIEpJPPOPiZlAPohXDwWyyCgIXXzqh+g6j/ExUtmxZV7iyQL5sQiYCHHgRqiCyKXqvBocbYN0wcn4oTRJ1TNXqSbTYqAyWrNxIlRrksCB4DKI2CyfwAhayAwe06Uj6A3dEGEMsRzgj0wEsaRuXJE4xkDDQiPiCHXNWqFAhbh6ENGIcPTXAQLinIObZjCAQ/uIAAYtHWiWhsEFYObyNEQayPx+ewLeOIMO8G/wsqQXxUghZDA4LtGzZ0shqkET0G6psdpxWDwsmOHNU97333osdxeNe2DbFKKQPfhQ2ABPwkCYoPfxBtU+QHjBgQMLzzjBuNgiS6bs0VkoJQxLBWsMG8ZOEw+FSifdsdPBbSDksCCn0ww8/dIqgBqCR9qUg8jmT0sql2PS7o8HzQ1yLbMHLkpHIhFwP0HwbUYfBuY5AzfDnY0ep/HFHHd7CZWkKIMhpsCH86JAEn2PJ6N/oTigDWCebQhJi030wkFnI3hTiSS0I84X+4xL0p2DQGridNBzqJx1MINj27NnTcRaad1ggWjTNP50n4mX5GjgugCvp8Ddzs9vcj0rJwCKo67BKDRIDrklvjDCgg6N8xok15mBu+m7EzXHjxsVaS/TH4GxYPqwf4quBqAalwCV5Rg7xP0q0R/9h9/1Dmz7CZD0sid/BQe+JsoAjJ8FvPnMt/XlcCIEtbHBCBBcKuh/XQiHoZ9FVUSPSn4N4iNXzO2zQeuJeLDPZCGXS4h7iQohRxB+kByyCz7EURC0kDoYkEKVz5lB2Ihvi61gl7kM7CK0HvoNVMtRP11y6F3WR0oPCFpfAEtltRDvm0L2+wM9nogc8F2vGsngnNgXNiLJJ/TGR2bBsGalJR6VSLSiMr6SSSpOl4ihVMNn8UfcK2KhDWZEAJbW//4M/HgQoYpMPAhQB0H8B2aNQ5qUn21wAAAAASUVORK5CYII="); }
        80%, 100%   { background-image: url("data:image/png;base64,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"); }
    }
</style>
""", unsafe_allow_html=True)

# Purchase categories
PURCHASE_CATEGORIES = [
    "General", "Groceries - Supermarket", "Groceries - Convenience Store",
    "Dining - Restaurant", "Dining - Fast Food", "Dining - Coffee Shop",
    "Transportation - Gas/Fuel", "Transportation - Parking", "Transportation - Rideshare/Taxi",
    "Entertainment - Movies/Theater", "Entertainment - Streaming Services",
    "Shopping - Clothing/Apparel", "Shopping - Electronics", "Shopping - Online Retail",
    "Bills - Utilities", "Bills - Phone/Mobile", "Bills - Internet/Cable",
    "Health - Pharmacy", "Health - Doctor/Medical", "Travel - Flights", "Travel - Hotels",
    "Other - Miscellaneous",
]


def initialize_session_state():
    """Initialize all session state variables"""
    state_manager = get_state_manager()

    if 'initialized' not in st.session_state:
        saved_state = state_manager.load_all()

        st.session_state.lots = saved_state.get("lots", [])
        st.session_state.parameters = saved_state.get("parameters") or Parameters()
        st.session_state.purchases = saved_state.get("purchases", [])
        st.session_state.sales = saved_state.get("sales", [])
        st.session_state.tax_result = None
        st.session_state.initialized = True
        st.session_state.last_price_refresh = None
        st.session_state.upload_errors = []
        st.session_state.upload_success = None
        st.session_state.pending_continuation = None

        # Enrich lots with current prices if we have any
        if st.session_state.lots:
            mds = get_market_data_service()
            currencies = list(set(lot.currency for lot in st.session_state.lots))
            new_prices = {}
            for currency in currencies:
                price = mds.get_price(currency, use_cache=False)
                if price:
                    new_prices[currency] = price
            current_date = datetime.now()
            for lot in st.session_state.lots:
                if lot.currency in new_prices:
                    lot.update_calculated_fields(new_prices[lot.currency], current_date)
            st.session_state.last_price_refresh = datetime.now()

        # Initialize comparison books if lots exist
        if st.session_state.lots and 'comparison_books' not in st.session_state:
            initialize_comparison_books()

        # Recalculate taxes and remaining CF/OID if we have sales
        if st.session_state.sales:
            tce = TaxCalculationEngine()
            st.session_state.tax_result = tce.calculate_taxes(
                st.session_state.sales,
                st.session_state.parameters
            )
            # Update parameters (this sets rem_* from netted values)
            tce.update_parameters_from_result(
                st.session_state.tax_result,
                st.session_state.parameters
            )

            # NOW override rem_* with RAW gains/losses from TWS 1-6 sales
            # (the netted amounts from TCE are affected by third netting,
            # but for TWS activation we need raw consumption)
            params = st.session_state.parameters
            raw_cfstl_used = 0.0
            raw_cfltl_used = 0.0
            raw_oid_used = 0.0

            for sale in st.session_state.sales:
                if sale.tw_step in [1, 3]:  # STG vs CF-STL or CF-LTL
                    if sale.tw_step == 1:
                        raw_cfstl_used += sale.realized_cgl  # gains are positive
                    else:
                        raw_cfltl_used += sale.realized_cgl
                elif sale.tw_step in [2, 4]:  # LTG vs CF-LTL or CF-STL
                    if sale.tw_step == 2:
                        raw_cfltl_used += sale.realized_cgl
                    else:
                        raw_cfstl_used += sale.realized_cgl
                elif sale.tw_step in [5, 6]:  # Loss vs OID
                    raw_oid_used += abs(sale.realized_cgl)  # losses are negative, take abs

            # Update remaining values based on raw consumption
            params.rem_cfstl = params.cfstl + raw_cfstl_used
            if params.rem_cfstl > 0:
                params.rem_cfstl = 0
            params.rem_cfltl = params.cfltl + raw_cfltl_used
            if params.rem_cfltl > 0:
                params.rem_cfltl = 0
            params.rem_oid = params.oid_limit + raw_oid_used
            if params.rem_oid > 0:
                params.rem_oid = 0

    # Recalculate tax_result if it's stale (e.g., after a code change + Streamlit rerun)
    if (st.session_state.tax_result is not None
            and not hasattr(st.session_state.tax_result, 'first_net_stg')):
        tce = TaxCalculationEngine()
        st.session_state.tax_result = tce.calculate_taxes(
            st.session_state.sales,
            st.session_state.parameters,
        )


def save_state():
    """Save current state to disk"""
    state_manager = get_state_manager()
    state_manager.save_all(
        st.session_state.lots,
        st.session_state.parameters,
        st.session_state.purchases,
        st.session_state.sales
    )


def reset_system():
    """Reset all data and state"""
    state_manager = get_state_manager()
    state_manager.clear_all()

    mds = get_market_data_service()
    mds.clear_cache()

    st.session_state.lots = []
    st.session_state.parameters = Parameters()
    st.session_state.purchases = []
    st.session_state.sales = []
    st.session_state.tax_result = None
    st.session_state.last_price_refresh = None
    st.session_state.comparison_books = {}


def reload_from_disk():
    """Reload all state from disk without clearing files"""
    state_manager = get_state_manager()
    saved_state = state_manager.load_all()

    st.session_state.lots = saved_state.get("lots", [])
    st.session_state.parameters = saved_state.get("parameters") or Parameters()
    st.session_state.purchases = saved_state.get("purchases", [])
    st.session_state.sales = saved_state.get("sales", [])

    # Enrich lots with current prices
    if st.session_state.lots:
        mds = get_market_data_service()
        currencies = list(set(lot.currency for lot in st.session_state.lots))
        new_prices = {}
        for currency in currencies:
            price = mds.get_price(currency, use_cache=False)
            if price:
                new_prices[currency] = price
        current_date = datetime.now()
        for lot in st.session_state.lots:
            if lot.currency in new_prices:
                lot.update_calculated_fields(new_prices[lot.currency], current_date)
        st.session_state.last_price_refresh = datetime.now()

    # Re-initialize comparison books on reload
    if st.session_state.lots:
        initialize_comparison_books()

    # Recalculate taxes and remaining values if we have sales
    if st.session_state.sales:
        tce = TaxCalculationEngine()
        st.session_state.tax_result = tce.calculate_taxes(
            st.session_state.sales,
            st.session_state.parameters
        )

        # CRITICAL: Recalculate rem_* from RAW sales data
        params = st.session_state.parameters

        # rem_cfstl from TWS 1 and 4 sales
        raw_cfstl_used = sum(s.realized_cgl for s in st.session_state.sales if s.tw_step in [1, 4])
        params.rem_cfstl = params.cfstl + raw_cfstl_used
        if params.rem_cfstl > 0:
            params.rem_cfstl = 0

        # rem_cfltl from TWS 2 and 3 sales
        raw_cfltl_used = sum(s.realized_cgl for s in st.session_state.sales if s.tw_step in [2, 3])
        params.rem_cfltl = params.cfltl + raw_cfltl_used
        if params.rem_cfltl > 0:
            params.rem_cfltl = 0

        # rem_oid from TWS 5 and 6 sales
        raw_oid_used = sum(abs(s.realized_cgl) for s in st.session_state.sales if s.tw_step in [5, 6])
        params.rem_oid = params.oid_limit + raw_oid_used
        if params.rem_oid > 0:
            params.rem_oid = 0


def refresh_prices():
    """Manually refresh all lot prices from Market Data API"""
    if not st.session_state.lots:
        return False, "No lots to refresh"
    
    # Clear cache to force fresh prices
    mds = get_market_data_service()
    mds.clear_cache()
    
    # Get unique currencies from lots
    currencies = list(set(lot.currency for lot in st.session_state.lots if lot.remaining_quantity > 0))
    
    # Force fetch new prices (bypassing cache completely)
    new_prices = {}
    for currency in currencies:
        price = mds.get_price(currency, use_cache=False)
        if price:
            new_prices[currency] = price
    
    # Update all lots with the fresh prices
    current_date = datetime.now()
    for lot in st.session_state.lots:
        if lot.remaining_quantity > 0 and lot.currency in new_prices:
            lot.update_calculated_fields(new_prices[lot.currency], current_date)
    
    st.session_state.last_price_refresh = datetime.now()
    save_state()
    
    return True, f"Prices refreshed at {st.session_state.last_price_refresh.strftime('%H:%M:%S')} - Updated {len(new_prices)} currencies"


def get_oid_consumed(tax_result: TaxCalculationResult, params: Parameters) -> float:
    """Calculate the consumed OID amount (positive value for display)"""
    if tax_result is None:
        return 0.0
    return abs(tax_result.oid_applied)


def render_tax_status_panel():
    """Render the tax status summary panel"""
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    params = st.session_state.parameters

    if st.session_state.tax_result is None:
        oid_consumed = 0.0
        fed_oi = 0.0
        fed_cg = 0.0
        state = 0.0
        total = 0.0
    else:
        result = st.session_state.tax_result
        oid_consumed = abs(result.oid_applied)
        fed_oi = result.fed_oi_tax
        fed_cg = result.fed_cg_tax
        state = result.state_tax
        total = result.total_tax

    st.markdown(f"""<div class="tax-summary-panel">
        <div class="panel-title">Tax Status</div>
        <div class="summary-row"><span class="label">Ordinary Income Deduction:</span><span class="value">${oid_consumed:,.2f}</span></div>
        <div style="height: 24px;"></div>
        <div class="summary-row"><span class="label">Federal OI Tax:</span><span class="value">${fed_oi:,.2f}</span></div>
        <div class="summary-row"><span class="label">Federal CG Tax:</span><span class="value">${fed_cg:,.2f}</span></div>
        <div class="summary-row"><span class="label">State Tax:</span><span class="value">${state:,.2f}</span></div>
        <div class="total-row"><span class="label">Total Tax:</span><span class="value">${total:,.2f}</span></div>
    </div>""", unsafe_allow_html=True)


def render_cash_yield_panel():
    """Render the cash yield summary panel"""
    params = st.session_state.parameters
    result = st.session_state.tax_result
    pre_tax = sum(s.settlement_amount for s in st.session_state.sales)
    if result is not None:
        oid_credit = abs(result.oid_applied) * params.fed_oi_marginal_tax_rate
        total_tax = result.total_tax
    else:
        oid_credit = 0.0
        total_tax = 0.0
    after_tax = pre_tax - total_tax + oid_credit
    if pre_tax > 0:
        effective_rate = (1 - after_tax / pre_tax) * 100
    else:
        effective_rate = 0.0

    st.markdown(f"""<div class="tax-summary-panel" style="margin-top: 10px;">
        <div class="panel-title">Cash Yield</div>
        <div class="summary-row"><span class="label">Pre-Tax Proceeds:</span><span class="value">${pre_tax:,.2f}</span></div>
        <div class="summary-row"><span class="label">OID Credit:</span><span class="value">${oid_credit:,.2f}</span></div>
        <div class="summary-row"><span class="label">After-Tax Proceeds:</span><span class="value">${after_tax:,.2f}</span></div>
        <div class="total-row"><span class="label">Effective Tax Rate:</span><span class="value">{effective_rate:,.1f}%</span></div>
    </div>""", unsafe_allow_html=True)


def render_market_prices_panel():
    """Render the market prices panel"""

    if st.session_state.lots:
        # Get unique currencies and their prices
        mds = get_market_data_service()
        currencies = sorted(set(lot.currency for lot in st.session_state.lots if lot.remaining_quantity > 0))

        # Build price rows HTML
        price_rows = ""
        for currency in currencies:
            price = mds.get_price(currency, use_cache=True)
            if price:
                price_rows += f'<div class="summary-row"><span class="label">{currency}:</span><span class="value">${price:,.2f}</span></div>'

        # Last refresh time
        refresh_time = ""
        if st.session_state.last_price_refresh:
            refresh_time = f'<div style="font-size: 11px; color: #888; margin-top: 8px;">Last refresh: {st.session_state.last_price_refresh.strftime("%H:%M:%S")}</div>'

        st.markdown(f"""<div class="tax-summary-panel">
            <div class="panel-title">Market Prices</div>
            {price_rows}
            {refresh_time}
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""<div class="tax-summary-panel">
            <div class="panel-title">Market Prices</div>
            <div style="color: #888; font-size: 14px;">No portfolio loaded</div>
        </div>""", unsafe_allow_html=True)


def initialize_comparison_books():
    """Deep-copy current TW lots and parameters into 4 independent comparison books."""
    books = {}
    for strategy in COMPARISON_STRATEGIES:
        label = STRATEGY_LABELS[strategy]
        books[label] = {
            'lots': deepcopy(st.session_state.lots),
            'parameters': deepcopy(st.session_state.parameters),
            'sales': [],
            'tax_result': None,
        }
    st.session_state.comparison_books = books


def process_comparison_purchase(dcpa, category):
    """Execute the same purchase on all 4 comparison books."""
    books = st.session_state.get('comparison_books')
    if not books:
        return

    for strategy in COMPARISON_STRATEGIES:
        label = STRATEGY_LABELS[strategy]
        book = books[label]

        lse = SimpleLotSelectionEngine(strategy)
        te = TradeEngine(lot_selection_engine=lse)

        purchase, new_sales, tax_result, _ = te.process_purchase(
            lots=book['lots'],
            parameters=book['parameters'],
            dcpa=dcpa,
            description=category,
            category=category,
            existing_sales=book['sales'],
        )

        book['sales'].extend(new_sales)
        book['tax_result'] = tax_result

        # Sync lot remaining_quantity from sale records
        for sale in new_sales:
            for lot in book['lots']:
                if lot.lot_id == sale.lot_id:
                    lot.remaining_quantity = sale.quantity_remaining
                    break


def sync_parameters_to_comparison_books():
    """Propagate tax rates, CF base values, and OID limit to comparison books."""
    books = st.session_state.get('comparison_books')
    if not books:
        return

    tw_params = st.session_state.parameters
    for label, book in books.items():
        p = book['parameters']
        p.fed_oi_marginal_tax_rate = tw_params.fed_oi_marginal_tax_rate
        p.fed_cg_marginal_tax_rate = tw_params.fed_cg_marginal_tax_rate
        p.state_income_marginal_tax_rate = tw_params.state_income_marginal_tax_rate

        # If user changed CF base values, update comparison books too
        if p.cfstl != tw_params.cfstl:
            p.cfstl = tw_params.cfstl
            p.rem_cfstl = tw_params.cfstl
        if p.cfltl != tw_params.cfltl:
            p.cfltl = tw_params.cfltl
            p.rem_cfltl = tw_params.cfltl
        if p.oid_limit != tw_params.oid_limit:
            p.oid_limit = tw_params.oid_limit
            p.rem_oid = tw_params.oid_limit

        # Recalculate taxes with updated rates if sales exist
        if book['sales']:
            tce = TaxCalculationEngine()
            book['tax_result'] = tce.calculate_taxes(book['sales'], p)
            tce.update_parameters_from_result(book['tax_result'], p)


def render_comparison_tab():
    """Render the Comparison tab showing FIFO/LIFO/Max-Gain/Max-Loss vs Tax Waterfall."""
    st.markdown("### ⚖️ Comparison: Tax Waterfall vs Alternative Strategies")

    books = st.session_state.get('comparison_books', {})
    if not books:
        st.info("Load portfolio data to enable comparison.")
        return

    has_any_sales = any(book['tax_result'] is not None for book in books.values())
    if not has_any_sales:
        st.info("Process a purchase on the Purchase tab to see how alternative strategies compare.")
        return

    tw_params = st.session_state.parameters

    cols = st.columns(4)

    for i, strategy in enumerate(COMPARISON_STRATEGIES):
        label = STRATEGY_LABELS[strategy]
        book = books.get(label, {})
        result = book.get('tax_result')
        params = book.get('parameters', tw_params)

        with cols[i]:
            st.markdown(f"**{label}**")

            if result is not None:
                oid = abs(result.oid_applied)
                fed_oi = result.fed_oi_tax
                fed_cg = result.fed_cg_tax
                state_tax = result.state_tax
                total = result.total_tax
            else:
                oid = fed_oi = fed_cg = state_tax = total = 0.0

            st.markdown(f"""<div class="tax-summary-panel">
                <div class="panel-title">Tax Status</div>
                <div class="summary-row"><span class="label">OID:</span><span class="value">${oid:,.2f}</span></div>
                <div style="height: 24px;"></div>
                <div class="summary-row"><span class="label">Fed OI Tax:</span><span class="value">${fed_oi:,.2f}</span></div>
                <div class="summary-row"><span class="label">Fed CG Tax:</span><span class="value">${fed_cg:,.2f}</span></div>
                <div class="summary-row"><span class="label">State Tax:</span><span class="value">${state_tax:,.2f}</span></div>
                <div class="total-row"><span class="label">Total Tax:</span><span class="value">${total:,.2f}</span></div>
            </div>""", unsafe_allow_html=True)

            # Cash yield
            sales_list = book.get('sales', [])
            pre_tax = sum(s.settlement_amount for s in sales_list)
            if result is not None:
                oid_credit = abs(result.oid_applied) * params.fed_oi_marginal_tax_rate
            else:
                oid_credit = 0.0
            after_tax = pre_tax - total + oid_credit
            eff_rate = (1 - after_tax / pre_tax) * 100 if pre_tax > 0 else 0.0

            st.markdown(f"""<div class="tax-summary-panel" style="margin-top: 10px;">
                <div class="panel-title">Cash Yield</div>
                <div class="summary-row"><span class="label">Pre-Tax:</span><span class="value">${pre_tax:,.2f}</span></div>
                <div class="summary-row"><span class="label">OID Credit:</span><span class="value">${oid_credit:,.2f}</span></div>
                <div class="summary-row"><span class="label">After-Tax:</span><span class="value">${after_tax:,.2f}</span></div>
                <div class="total-row"><span class="label">Eff. Rate:</span><span class="value">{eff_rate:,.1f}%</span></div>
            </div>""", unsafe_allow_html=True)

            # Sales detail expander
            if sales_list:
                with st.expander("Sales Detail"):
                    for s in sales_list:
                        lot_type = ("STG" if s.realized_cgl >= 0 else "STL") if s.stlt == "ST" else ("LTG" if s.realized_cgl >= 0 else "LTL")
                        cgl_color = "#28a745" if s.realized_cgl >= 0 else "#dc3545"
                        cgl_prefix = "+" if s.realized_cgl >= 0 else "-"
                        st.markdown(f"""<div class="tax-summary-panel" style="padding: 8px 12px; margin-bottom: 6px;">
                            <div style="font-weight: bold;">{s.currency}</div>
                            <div class="label" style="margin-bottom: 4px;">{s.lot_id}</div>
                            <div class="summary-row"><span class="label">${s.settlement_amount:,.2f}</span><span class="value" style="color: {cgl_color};">{lot_type} {cgl_prefix}${abs(s.realized_cgl):,.2f}</span></div>
                        </div>""", unsafe_allow_html=True)


def render_sidebar():
    """Render the input sidebar"""
    with st.sidebar:
        st.title("⚙️ Configuration")
        
        st.markdown("### 🔧 System Controls")
        if st.button("💾 Save", use_container_width=True):
            save_state()
            st.success("Saved!")
        if st.button("🔃 Reload", use_container_width=True):
            reload_from_disk()
            st.rerun()
        if st.button("🔄 Reset", use_container_width=True, type="secondary"):
            reset_system()
            st.rerun()
        if st.button("💲 Refresh Prices", use_container_width=True):
            success, message = refresh_prices()
            if success:
                st.rerun()

        st.divider()
        st.markdown("### 📂 Data Upload")
        def process_lots_upload():
            """Callback to process uploaded lots file"""
            lots_file = st.session_state.lots_upload
            if lots_file is not None:
                content = DataInputService.read_uploaded_file(lots_file)
                lots, errors = DataInputService.parse_purchase_lots_csv(content)
                if errors:
                    st.session_state.upload_errors = errors
                else:
                    st.session_state.upload_errors = []
                if lots:
                    st.session_state.lots = lots
                    # Fetch fresh prices
                    mds = get_market_data_service()
                    mds.clear_cache()
                    currencies = list(set(lot.currency for lot in lots))
                    new_prices = {}
                    for currency in currencies:
                        price = mds.get_price(currency, use_cache=False)
                        if price:
                            new_prices[currency] = price
                    # Update all lots with fresh prices
                    current_date = datetime.now()
                    for lot in st.session_state.lots:
                        if lot.currency in new_prices:
                            lot.update_calculated_fields(new_prices[lot.currency], current_date)
                    st.session_state.last_price_refresh = datetime.now()
                    st.session_state.upload_success = f"Loaded {len(lots)} lots with current prices ({len(new_prices)} currencies fetched)"
                    initialize_comparison_books()
                    save_state()

        st.file_uploader("Upload a CSV file containing your purchase lots", type=['csv'], key="lots_upload", on_change=process_lots_upload)

        # Show upload results
        if st.session_state.get('upload_errors'):
            for error in st.session_state.upload_errors:
                st.error(error)
            st.session_state.upload_errors = []
        if st.session_state.get('upload_success'):
            st.success(st.session_state.upload_success)
            st.session_state.upload_success = None
        
        if st.button("📋 Create Sample Data", use_container_width=True):
            st.session_state.lots = load_sample_lots()
            st.session_state.parameters = load_sample_parameters()
            # Fetch fresh prices
            mds = get_market_data_service()
            mds.clear_cache()
            currencies = list(set(lot.currency for lot in st.session_state.lots))
            new_prices = {}
            for currency in currencies:
                price = mds.get_price(currency, use_cache=False)
                if price:
                    new_prices[currency] = price
            # Update all lots with fresh prices
            current_date = datetime.now()
            for lot in st.session_state.lots:
                if lot.currency in new_prices:
                    lot.update_calculated_fields(new_prices[lot.currency], current_date)
            st.session_state.last_price_refresh = datetime.now()
            initialize_comparison_books()
            save_state()
            st.success(f"Sample data created! ({len(new_prices)} currencies fetched)")
            st.rerun()
        
        st.divider()
        st.markdown("### 💼 Tax Parameters")

        params = st.session_state.parameters

        # CF Short-Term Loss - only reset rem_cfstl if user changes the base value
        new_cfstl = st.number_input("CF Short-Term Loss ($)", value=float(abs(params.cfstl)),
                                    min_value=0.0, step=100.0, format="%.2f", key="cfstl_input")
        new_cfstl = -abs(new_cfstl)
        if new_cfstl != params.cfstl:
            params.cfstl = new_cfstl
            params.rem_cfstl = new_cfstl  # Reset remaining only when base changes

        # CF Long-Term Loss - only reset rem_cfltl if user changes the base value
        new_cfltl = st.number_input("CF Long-Term Loss ($)", value=float(abs(params.cfltl)),
                                    min_value=0.0, step=100.0, format="%.2f", key="cfltl_input")
        new_cfltl = -abs(new_cfltl)
        if new_cfltl != params.cfltl:
            params.cfltl = new_cfltl
            params.rem_cfltl = new_cfltl  # Reset remaining only when base changes

        st.markdown("#### Tax Rates")
        fed_oi_rate = st.number_input("Marginal Federal OI Rate (%)", min_value=0.0, max_value=50.0,
                                      value=float(params.fed_oi_marginal_tax_rate * 100),
                                      step=0.5, format="%.1f", key="fed_oi_rate")
        params.fed_oi_marginal_tax_rate = fed_oi_rate / 100

        fed_cg_rate = st.number_input("Federal CG Rate (%)", min_value=0.0, max_value=30.0,
                                      value=float(params.fed_cg_marginal_tax_rate * 100),
                                      step=0.5, format="%.1f", key="fed_cg_rate")
        params.fed_cg_marginal_tax_rate = fed_cg_rate / 100

        state_rate = st.number_input("State Income Rate (%)", min_value=0.0, max_value=15.0,
                                     value=float(params.state_income_marginal_tax_rate * 100),
                                     step=0.5, format="%.1f", key="state_rate")
        params.state_income_marginal_tax_rate = state_rate / 100

        # OID Limit - only reset rem_oid if user changes the base value
        new_oid_limit = -abs(st.selectbox("OID Limit ($)", options=[3000, 6000],
                                          index=0 if abs(params.oid_limit) == 3000 else 1,
                                          key="oid_limit_select"))
        if new_oid_limit != params.oid_limit:
            params.oid_limit = new_oid_limit
            params.rem_oid = new_oid_limit  # Reset remaining only when base changes
        
        st.divider()
        st.markdown("### 🎯 Lot Selection")
        
        params.lot_order_index = st.selectbox("Sort By", options=["pnl", "value"],
                                              index=0 if params.lot_order_index == "pnl" else 1,
                                              key="lot_order")
        
        params.gain_lot_ordering = st.selectbox("Gain Lot Ordering", options=["high-to-low", "low-to-high"],
                                                index=0 if params.gain_lot_ordering == "high-to-low" else 1,
                                                key="gain_order")
        
        params.loss_lot_ordering = st.selectbox("Loss Lot Ordering", options=["high-to-low", "low-to-high"],
                                                index=0 if params.loss_lot_ordering == "high-to-low" else 1,
                                                key="loss_order")
        
        params.min_lot_value = st.number_input("Min Trade Value ($)", value=float(params.min_lot_value),
                                               min_value=0.0, step=10.0, format="%.2f", key="min_value")
        
        st.session_state.parameters = params
        sync_parameters_to_comparison_books()


def render_debit_card_purchase_tab():
    """Render the debit card purchase tab"""
    st.markdown("### 💳 Debit Card Purchase")
    st.markdown("Enter a purchase amount. The system will sell crypto lots using the Tax Waterfall methodology.")

    # Available balance tile (constrained width)
    col_avail, col_spacer = st.columns([1, 3])
    with col_avail:
        if st.session_state.lots:
            dps = get_data_processing_service()
            summary = dps.get_portfolio_summary(st.session_state.lots)
            st.metric("Available", f"${summary['total_value']:,.2f}")
        else:
            st.metric("Available", "$0.00")

    col1, col2, col_spacer = st.columns([1, 1, 2])
    with col1:
        dcpa = st.number_input("Purchase Amount ($)", min_value=0.01, value=100.0,
                               step=10.0, format="%.2f", key="dcpa_input")
    with col2:
        category = st.selectbox("Category", options=PURCHASE_CATEGORIES, key="category_select")

    # OID Strategy Warning
    params = st.session_state.parameters
    if params.rem_oid >= 0 and st.session_state.lots:
        # OID is fully consumed - check if next step would be pure gains (TWS 11+)
        lse = LotSelectionEngine()
        dps = get_data_processing_service()
        active_lots = [lot for lot in st.session_state.lots if lot.remaining_quantity > 0]
        dps.enrich_lots(active_lots, use_cache=True)
        current_selection = lse.select_lots(active_lots, params, float('inf'))

        if current_selection and current_selection.tw_step >= 11:
            st.warning(
                "**Tax Strategy Advisory:** Your OID limit ($3,000) is fully consumed. "
                "The next purchase will realize gains (TWS 11+) that will **erode your OID benefit** "
                "through IRS third netting. Consider waiting until next tax year to preserve your "
                f"ordinary income deduction. (Next step: TWS {current_selection.tw_step})"
            )
        elif current_selection and current_selection.tw_step >= 7:
            st.info(
                "**Tax Strategy Note:** Your OID limit is fully consumed. "
                "Current purchases are in 2-way allocation (TWS 7-10), which pairs gains with losses "
                "and is roughly tax-neutral. Your OID benefit is preserved for now."
            )

    process_btn = st.button("🚀 Process Purchase", type="primary")
    
    if process_btn:
        if not st.session_state.lots:
            st.error("❌ No portfolio loaded. Please upload lots first.")
            return

        # Check if purchase amount exceeds portfolio value
        dps = get_data_processing_service()
        portfolio_summary = dps.get_portfolio_summary(st.session_state.lots)
        portfolio_value = portfolio_summary['total_value']
        if dcpa > portfolio_value:
            st.error(f"❌ Purchase amount (${dcpa:,.2f}) exceeds available portfolio value (${portfolio_value:,.2f}).")
            return

        with st.spinner("Processing purchase..."):
            trade_engine = TradeEngine()
            purchase, new_sales, tax_result, hit_limit = trade_engine.process_purchase(
                lots=st.session_state.lots,
                parameters=st.session_state.parameters,
                dcpa=dcpa,
                description=category,
                category=category,
                existing_sales=st.session_state.sales
            )

            st.session_state.purchases.append(purchase)
            st.session_state.sales.extend(new_sales)
            st.session_state.tax_result = tax_result

            # Update tax result for display purposes
            tce = TaxCalculationEngine()
            tce.update_parameters_from_result(tax_result, st.session_state.parameters)

            # CRITICAL: Override rem_* with RAW values from TWS 1-6 sales
            # (TCE uses netted values, but TWS activation needs raw consumption)
            params = st.session_state.parameters

            # Override rem_cfstl from TWS 1 and 4 sales (gains that consumed CF-STL)
            raw_cfstl_used = sum(s.realized_cgl for s in st.session_state.sales if s.tw_step in [1, 4])
            params.rem_cfstl = params.cfstl + raw_cfstl_used
            if params.rem_cfstl > 0:
                params.rem_cfstl = 0

            # Override rem_cfltl from TWS 2 and 3 sales (gains that consumed CF-LTL)
            raw_cfltl_used = sum(s.realized_cgl for s in st.session_state.sales if s.tw_step in [2, 3])
            params.rem_cfltl = params.cfltl + raw_cfltl_used
            if params.rem_cfltl > 0:
                params.rem_cfltl = 0

            # Override rem_oid from TWS 5 and 6 sales (losses that consumed OID)
            raw_oid_used = sum(abs(s.realized_cgl) for s in st.session_state.sales if s.tw_step in [5, 6])
            params.rem_oid = params.oid_limit + raw_oid_used
            if params.rem_oid > 0:
                params.rem_oid = 0

            # CRITICAL FIX: Update lot remaining_quantity from sale records
            # The trade engine may modify different object references, so we must
            # explicitly sync the session_state lots with the sale's quantity_remaining
            for sale in new_sales:
                for lot in st.session_state.lots:
                    if lot.lot_id == sale.lot_id:
                        lot.remaining_quantity = sale.quantity_remaining
                        break

            # Force refresh lot calculated fields after sales
            dps = get_data_processing_service()
            mds = get_market_data_service()
            currencies = list(set(lot.currency for lot in st.session_state.lots if lot.remaining_quantity > 0))
            prices = {c: mds.get_price(c, use_cache=True) for c in currencies}
            for lot in st.session_state.lots:
                if lot.remaining_quantity > 0 and lot.currency in prices and prices[lot.currency]:
                    lot.update_calculated_fields(prices[lot.currency])

            save_state()

            # Process the same purchase on all comparison books
            if not st.session_state.get('pending_continuation'):
                process_comparison_purchase(dcpa, category)

            # Store state for potential continuation
            if hit_limit:
                st.session_state.pending_continuation = {
                    'purchase': purchase,
                    'category': category,
                    'new_sales_count': len(new_sales)
                }

        if purchase.status == PurchaseStatus.COMPLETED:
            st.session_state.pending_continuation = None
            st.success(f"✅ Purchase completed! {len(new_sales)} sale(s) for ${purchase.total_settlement_amount:,.2f}")
        elif hit_limit:
            st.warning(
                f"⏸️ **Paused at 100 sales.** Processed ${purchase.total_settlement_amount:,.2f} of ${dcpa:,.2f} "
                f"({len(new_sales)} sales). Remaining: ${purchase.rdcpa:,.2f}"
            )
        elif purchase.status == PurchaseStatus.INCOMPLETE:
            st.session_state.pending_continuation = None
            st.warning(f"⚠️ Incomplete. Only ${purchase.total_settlement_amount:,.2f} of ${dcpa:,.2f} covered.")
        else:
            st.session_state.pending_continuation = None
            st.error(f"❌ Failed: {purchase.status.value}")

        if not hit_limit:
            st.rerun()

    # Show continuation dialog if we have a pending purchase
    if st.session_state.get('pending_continuation'):
        pending = st.session_state.pending_continuation
        purchase = pending['purchase']

        st.markdown("---")
        st.markdown(f"### ⏸️ Continue Processing?")
        st.markdown(f"**Remaining amount:** ${purchase.rdcpa:,.2f}")

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("▶️ Continue", type="primary", use_container_width=True):
                with st.spinner("Continuing purchase processing..."):
                    trade_engine = TradeEngine()
                    continued_purchase, new_sales, tax_result, hit_limit = trade_engine.process_purchase(
                        lots=st.session_state.lots,
                        parameters=st.session_state.parameters,
                        dcpa=purchase.rdcpa,  # Continue with remaining amount
                        description=pending['category'],
                        category=pending['category'],
                        existing_sales=st.session_state.sales
                    )

                    # Update the original purchase record
                    purchase.rdcpa = continued_purchase.rdcpa
                    purchase.total_settlement_amount += continued_purchase.total_settlement_amount
                    purchase.num_sales += continued_purchase.num_sales
                    purchase.total_stl += continued_purchase.total_stl
                    purchase.total_ltl += continued_purchase.total_ltl
                    purchase.total_stg += continued_purchase.total_stg
                    purchase.total_ltg += continued_purchase.total_ltg
                    if continued_purchase.status == PurchaseStatus.COMPLETED:
                        purchase.status = PurchaseStatus.COMPLETED

                    st.session_state.sales.extend(new_sales)
                    st.session_state.tax_result = tax_result

                    # Update parameters
                    tce = TaxCalculationEngine()
                    tce.update_parameters_from_result(tax_result, st.session_state.parameters)

                    # CRITICAL: Override rem_* with RAW values from TWS 1-6 sales
                    params = st.session_state.parameters

                    # Override rem_cfstl from TWS 1 and 4 sales
                    raw_cfstl_used = sum(s.realized_cgl for s in st.session_state.sales if s.tw_step in [1, 4])
                    params.rem_cfstl = params.cfstl + raw_cfstl_used
                    if params.rem_cfstl > 0:
                        params.rem_cfstl = 0

                    # Override rem_cfltl from TWS 2 and 3 sales
                    raw_cfltl_used = sum(s.realized_cgl for s in st.session_state.sales if s.tw_step in [2, 3])
                    params.rem_cfltl = params.cfltl + raw_cfltl_used
                    if params.rem_cfltl > 0:
                        params.rem_cfltl = 0

                    # Override rem_oid from TWS 5 and 6 sales
                    raw_oid_used = sum(abs(s.realized_cgl) for s in st.session_state.sales if s.tw_step in [5, 6])
                    params.rem_oid = params.oid_limit + raw_oid_used
                    if params.rem_oid > 0:
                        params.rem_oid = 0

                    # Update lot quantities
                    for sale in new_sales:
                        for lot in st.session_state.lots:
                            if lot.lot_id == sale.lot_id:
                                lot.remaining_quantity = sale.quantity_remaining
                                break

                    save_state()

                    if hit_limit and purchase.rdcpa > 0.01:
                        pending['new_sales_count'] += len(new_sales)
                        st.rerun()
                    else:
                        st.session_state.pending_continuation = None
                        st.rerun()

        with col2:
            if st.button("⏹️ Stop", type="secondary", use_container_width=True):
                purchase.status = PurchaseStatus.INCOMPLETE
                st.session_state.pending_continuation = None
                save_state()
                st.rerun()

    st.divider()
    st.markdown("#### Recent Purchase Activity")
    if st.session_state.purchases:
        for p in reversed(st.session_state.purchases[-5:]):
            status_icon = "✅" if p.status == PurchaseStatus.COMPLETED else "⚠️" if p.status == PurchaseStatus.PROCESSING else "❌"
            st.write(f"{status_icon} **${p.dcpa:,.2f}** - {p.category} - {p.num_sales} sales - {p.timestamp.strftime('%m/%d %H:%M')}")
    else:
        st.info("No purchases yet.")


def get_lot_type_full(lot: Lot) -> str:
    """Get the full lot type string (STG, STL, LTG, LTL)"""
    lot_type = lot.get_lot_type()
    return lot_type.value if lot_type else "N/A"


def filter_and_sort_lots_by_tws(lots: List[Lot], tws_step: int, parameters: Parameters) -> List[Lot]:
    """Filter and sort lots according to a specific Tax Waterfall Step"""
    step_config = None
    for config in TAX_WATERFALL_CONFIG:
        if config.step == tws_step:
            step_config = config
            break
    
    if not step_config:
        return lots
    
    dps = get_data_processing_service()
    eligible_lots = dps.filter_eligible_lots(lots, min_value=parameters.min_lot_value,
                                             lot_types=step_config.return_types)
    return dps.sort_lots(eligible_lots, parameters)


def get_next_lots_for_tws(lots: List[Lot], tws_step: int, parameters: Parameters) -> List[Lot]:
    """Get the next lot(s) that would be selected for a given TWS"""
    step_config = None
    for config in TAX_WATERFALL_CONFIG:
        if config.step == tws_step:
            step_config = config
            break
    
    if not step_config:
        return []
    
    filtered = filter_and_sort_lots_by_tws(lots, tws_step, parameters)
    if not filtered:
        return []
    
    if step_config.is_two_way():
        result = []
        for lot_type in step_config.return_types:
            for lot in filtered:
                if get_lot_type_full(lot) == lot_type and lot not in result:
                    result.append(lot)
                    break
        return result
    else:
        return [filtered[0]] if filtered else []


def render_portfolio_section():
    """Render the portfolio overview section"""
    st.markdown("### 📈 Portfolio Overview")

    if not st.session_state.lots:
        st.info("No portfolio data. Please upload a CSV file or load sample data from the sidebar.")
        return

    dps = get_data_processing_service()
    summary = dps.get_portfolio_summary(st.session_state.lots)

    tab1, tab2, tab3 = st.tabs(["Summary", "Charts", "Detail"])

    with tab1:
        # Top metrics in tile graphics
        gains_count = summary['stg_count'] + summary['ltg_count']
        losses_count = summary['stl_count'] + summary['ltl_count']

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"""<div class="summary-tile">
                <div class="tile-label">Total Value</div>
                <div class="tile-value">${summary['total_value']:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col2:
            st.markdown(f"""<div class="summary-tile">
                <div class="tile-label">Unrealized P&L</div>
                <div class="tile-value">${summary['total_ur_pnl']:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"""<div class="summary-tile">
                <div class="tile-label">Active Lots</div>
                <div class="tile-value">{summary['total_lots']}</div>
            </div>""", unsafe_allow_html=True)
        with col4:
            st.markdown(f"""<div class="summary-tile">
                <div class="tile-label">Gains / Losses</div>
                <div class="tile-value">{gains_count} / {losses_count}</div>
            </div>""", unsafe_allow_html=True)

        # Lot type breakdown tiles
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(f"""<div class="lot-type-tile">
                <div class="lot-title">Short Term Gains</div>
                {summary['stg_count']} lots<br>
                Value: ${summary['stg_value']:,.2f}<br>
                P&L: ${summary['stg_pnl']:,.2f}
            </div>""", unsafe_allow_html=True)
        with col2:
            st.markdown(f"""<div class="lot-type-tile">
                <div class="lot-title">Long Term Gains</div>
                {summary['ltg_count']} lots<br>
                Value: ${summary['ltg_value']:,.2f}<br>
                P&L: ${summary['ltg_pnl']:,.2f}
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"""<div class="lot-type-tile">
                <div class="lot-title">Short Term Losses</div>
                {summary['stl_count']} lots<br>
                Value: ${summary['stl_value']:,.2f}<br>
                P&L: ${summary['stl_pnl']:,.2f}
            </div>""", unsafe_allow_html=True)
        with col4:
            st.markdown(f"""<div class="lot-type-tile">
                <div class="lot-title">Long Term Losses</div>
                {summary['ltl_count']} lots<br>
                Value: ${summary['ltl_value']:,.2f}<br>
                P&L: ${summary['ltl_pnl']:,.2f}
            </div>""", unsafe_allow_html=True)

    with tab2:
        # Charts - stacked vertically
        if summary['by_currency']:
            currency_data = pd.DataFrame([
                {"Currency": k, "Value": v['value']}
                for k, v in summary['by_currency'].items() if v['value'] > 0
            ])
            if not currency_data.empty:
                fig = px.pie(currency_data, values='Value', names='Currency', title='Portfolio by Currency')
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)

        pnl_data = pd.DataFrame([
            {"Type": "STG", "P&L": summary['stg_pnl']},
            {"Type": "LTG", "P&L": summary['ltg_pnl']},
            {"Type": "STL", "P&L": summary['stl_pnl']},
            {"Type": "LTL", "P&L": summary['ltl_pnl']},
        ])
        colors = ['#28a745' if x >= 0 else '#dc3545' for x in pnl_data['P&L']]
        fig = go.Figure(data=[go.Bar(x=pnl_data['Type'], y=pnl_data['P&L'], marker_color=colors)])
        fig.update_layout(title='Unrealized P&L by Type', height=400, yaxis_title='P&L ($)')
        st.plotly_chart(fig, use_container_width=True)

        if summary['by_currency']:
            cur_pnl_data = pd.DataFrame([
                {"Currency": k, "P&L": v['pnl']}
                for k, v in summary['by_currency'].items()
            ])
            if not cur_pnl_data.empty:
                cur_pnl_data = cur_pnl_data.sort_values('P&L', ascending=False)
                colors = ['#28a745' if x >= 0 else '#dc3545' for x in cur_pnl_data['P&L']]
                fig = go.Figure(data=[go.Bar(x=cur_pnl_data['Currency'], y=cur_pnl_data['P&L'], marker_color=colors)])
                fig.update_layout(title='Unrealized P&L by Currency', height=400, yaxis_title='P&L ($)')
                st.plotly_chart(fig, use_container_width=True)

    with tab3:
        # Lots table with TWS filter
        st.markdown("#### 📋 Lots Detail")

        tws_options = ["None"] + [f"Step {i}: {TAX_WATERFALL_CONFIG[i-1].title}" for i in range(1, 15)]
        col1, col2 = st.columns([2, 4])
        with col1:
            selected_tws = st.selectbox("Filter by Tax Waterfall Step", options=tws_options,
                                        key="portfolio_tws_filter_select")

        active_lots = [lot for lot in st.session_state.lots if lot.remaining_quantity > 0]

        # Enrich lots with current prices
        lse = LotSelectionEngine()
        dps = get_data_processing_service()
        dps.enrich_lots(active_lots, use_cache=True)

        # Get the current parameters (already updated during initialization or after purchases)
        params = st.session_state.parameters

        if selected_tws == "None":
            # Default: Show next lot(s) for the first active TWS step
            current_selection = lse.select_lots(active_lots, params, float('inf'))

            if current_selection:
                active_step_num = current_selection.tw_step
                active_step_title = TAX_WATERFALL_CONFIG[active_step_num - 1].title
                st.markdown(f"##### 🎯 Next Lot(s) to be Selected (Step {active_step_num}: {active_step_title})")
                next_data = [{"ID": lot.lot_id, "Currency": lot.currency,
                             "Quantity": f"{lot.remaining_quantity:.6f}",
                             "Current Value": f"${lot.current_value:,.2f}",
                             "P&L": f"${lot.ur_pnl:,.2f}",
                             "PTV": f"${ptv:,.2f}",
                             "Type": get_lot_type_full(lot)} for lot, ptv in current_selection.lots]
                st.dataframe(pd.DataFrame(next_data), use_container_width=True, hide_index=True)
            else:
                st.info("No active Tax Waterfall step - no eligible lots available.")

            display_lots = active_lots
        else:
            # Specific TWS selected: Check if step is active and show what would be selected
            tws_step = int(selected_tws.split(":")[0].replace("Step ", ""))
            step_config = TAX_WATERFALL_CONFIG[tws_step - 1]

            # Check if this step is currently active
            waterfall_status = lse.get_waterfall_status(active_lots, params)
            step_is_active = waterfall_status[tws_step - 1]['active'] if tws_step <= len(waterfall_status) else False

            if not step_is_active:
                st.warning(f"Step {tws_step}: {step_config.title} is currently **inactive**")
                # Show why it's inactive
                if tws_step in [1, 3] and params.rem_cfstl >= 0:
                    st.caption("Reason: No remaining CF-STL")
                elif tws_step in [2, 4] and params.rem_cfltl >= 0:
                    st.caption("Reason: No remaining CF-LTL")
                elif tws_step in [5, 6] and params.rem_oid >= 0:
                    st.caption("Reason: No remaining OID")
            else:
                # Get lots that would be selected for this specific step
                next_lots = get_next_lots_for_tws(active_lots, tws_step, params)
                if next_lots:
                    # Calculate PTVs using correct formulas for each step type
                    ptvs = {}
                    if step_config.is_two_way() and len(next_lots) == 2:
                        # For 2-way steps (7-10), calculate PTVs using the LSE formula
                        gain_lot = next_lots[0] if next_lots[0].ur_pnl >= 0 else next_lots[1]
                        loss_lot = next_lots[1] if next_lots[0].ur_pnl >= 0 else next_lots[0]
                        pnl_to_value_gain = abs(gain_lot.pnl_to_value) if gain_lot.pnl_to_value != 0 else 0.001
                        pnl_to_value_loss = abs(loss_lot.pnl_to_value) if loss_lot.pnl_to_value != 0 else 0.001
                        target_pnl = min(abs(gain_lot.ur_pnl), abs(loss_lot.ur_pnl))
                        ptv_gain = min(target_pnl / pnl_to_value_gain, gain_lot.current_value)
                        ptv_loss = min(target_pnl / pnl_to_value_loss, loss_lot.current_value)
                        ptvs = {gain_lot.lot_id: ptv_gain, loss_lot.lot_id: ptv_loss}
                    elif tws_step in [1, 2, 3, 4]:
                        # Steps 1-4: PTV = min(remaining_cf / pnl_to_value, current_value)
                        for lot in next_lots:
                            pnl_to_value = lot.pnl_to_value if lot.pnl_to_value > 0 else 0.001
                            if tws_step in [1, 4]:
                                remaining_cf = abs(params.rem_cfstl)
                            else:
                                remaining_cf = abs(params.rem_cfltl)
                            cf_based_value = remaining_cf / pnl_to_value
                            ptvs[lot.lot_id] = min(cf_based_value, lot.current_value)
                    elif tws_step in [5, 6]:
                        # Steps 5-6: PTV = min(remaining_oid / pnl_to_value, current_value)
                        for lot in next_lots:
                            pnl_to_value = abs(lot.pnl_to_value) if lot.pnl_to_value != 0 else 0.001
                            remaining_oid = abs(params.rem_oid)
                            oid_based_value = remaining_oid / pnl_to_value
                            ptvs[lot.lot_id] = min(oid_based_value, lot.current_value)
                    else:
                        # Steps 11-14: PTV = current_value
                        ptvs = {lot.lot_id: lot.current_value for lot in next_lots}

                    st.markdown(f"##### 🎯 Next Lot(s) for Step {tws_step}: {step_config.title}")
                    next_data = [{"ID": lot.lot_id, "Currency": lot.currency,
                                 "Quantity": f"{lot.remaining_quantity:.6f}",
                                 "Current Value": f"${lot.current_value:,.2f}",
                                 "P&L": f"${lot.ur_pnl:,.2f}",
                                 "PTV": f"${ptvs.get(lot.lot_id, lot.current_value):,.2f}",
                                 "Type": get_lot_type_full(lot)} for lot in next_lots]
                    st.dataframe(pd.DataFrame(next_data), use_container_width=True, hide_index=True)
                else:
                    st.info(f"No eligible lots for Step {tws_step}: {step_config.title}")

            filtered_lots = filter_and_sort_lots_by_tws(active_lots, tws_step, params)
            display_lots = filtered_lots

        lots_data = [{
            "Lot ID": lot.lot_id,
            "Currency": lot.currency,
            "Orig Qty": f"{lot.quantity:.6f}",
            "Cost Basis": f"${lot.cost_basis:,.2f}",
            "Curr Qty": f"{lot.remaining_quantity:.6f}",
            "Curr Price": f"${lot.current_mkt_price:,.2f}",
            "Curr Value": f"${lot.current_value:,.2f}",
            "P&L": f"${lot.ur_pnl:,.2f}",
            "P&L/Value": f"{lot.pnl_to_value*100:.4f}%",
            "Type": get_lot_type_full(lot),
            "Age (days)": (datetime.now() - lot.timestamp).days
        } for lot in display_lots]

        if lots_data:
            st.dataframe(pd.DataFrame(lots_data), use_container_width=True, hide_index=True)
        else:
            st.info("No lots match the selected filter criteria.")


def render_transaction_history():
    """Render the transaction history section"""
    st.markdown("### 📜 Transaction History")
    
    tab1, tab2 = st.tabs(["Purchases", "Sales"])
    
    with tab1:
        if not st.session_state.purchases:
            st.info("No purchases yet.")
        else:
            purchases_data = [{
                "Purchase ID": p.purchase_id,
                "Status": f"{'✅' if p.status == PurchaseStatus.COMPLETED else '⚠️' if p.status == PurchaseStatus.PROCESSING else '❌'} {p.status.value}",
                "Amount": f"${p.dcpa:,.2f}",
                "Settled": f"${p.total_settlement_amount:,.2f}",
                "# Sales": p.num_sales,
                "STG": f"${p.total_stg:,.2f}",
                "LTG": f"${p.total_ltg:,.2f}",
                "STL": f"${p.total_stl:,.2f}",
                "LTL": f"${p.total_ltl:,.2f}",
                "Category": p.category,
                "Time": p.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            } for p in reversed(st.session_state.purchases)]
            st.dataframe(pd.DataFrame(purchases_data), use_container_width=True, hide_index=True)
    
    with tab2:
        if not st.session_state.sales:
            st.info("No sales yet.")
        else:
            sales_data = []
            for s in reversed(st.session_state.sales):
                cgl_icon = "📈" if s.realized_cgl >= 0 else "📉"
                # Full lot type (STG, STL, LTG, LTL) instead of just ST/LT
                lot_type = ("STG" if s.realized_cgl >= 0 else "STL") if s.stlt == "ST" else ("LTG" if s.realized_cgl >= 0 else "LTL")
                sales_data.append({
                    "Timestamp": s.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "Sale ID": s.sales_id,
                    "Purchase ID": s.purchase_id,
                    "Lot ID": s.lot_id,
                    "Currency": s.currency,
                    "Qty Sold": f"{s.quantity_sold:.6f}",
                    "Price": f"${s.price:,.2f}",
                    "Settlement": f"${s.settlement_amount:,.2f}",
                    "CGL": f"{cgl_icon} ${s.realized_cgl:,.2f}",
                    "Type": lot_type,
                    "TW Step": s.tw_step
                })
            st.dataframe(pd.DataFrame(sales_data), use_container_width=True, hide_index=True)


def render_tax_waterfall_status():
    """Render the Tax Waterfall status section"""
    st.markdown("### 🌊 Tax Waterfall Status")
    
    if not st.session_state.lots:
        st.info("Load portfolio data to see Tax Waterfall status.")
        return
    
    lse = LotSelectionEngine()
    dps = get_data_processing_service()
    dps.enrich_lots(st.session_state.lots, use_cache=True)
    
    # Get the current parameters (already updated during initialization or after purchases)
    params = st.session_state.parameters
    
    status = lse.get_waterfall_status(st.session_state.lots, params)
    
    active_steps = [s for s in status if s['active']]
    if active_steps:
        first_active = active_steps[0]
        st.success(f"**Active Step: {first_active['step']} - {first_active['title']}** (TWSMV: ${first_active['twsmv']:,.2f})")
    else:
        st.warning("No active Tax Waterfall steps available.")
    
    status_data = [{
        "Step": step["step"],
        "Active": "✅" if step["active"] else "⬜",
        "Title": step["title"],
        "Lot Types": ", ".join(step["return_types"]),
        "Mode": step["allocation_type"],
        "TWSMV": f"${step['twsmv']:,.2f}" if step["active"] else "-"
    } for step in status]
    
    st.dataframe(pd.DataFrame(status_data), use_container_width=True, hide_index=True)
    
    if active_steps:
        st.markdown("#### Active Step Description")
        st.info(active_steps[0]['description'])


def _fmt_gl(value: float) -> str:
    """Format a gain/loss value: gains as $X.XX, losses as -$X.XX, zero as $0.00"""
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def _make_netting_table(stg: float, stl: float, ltg: float, ltl: float) -> pd.DataFrame:
    """Create a 2x2 DataFrame with Gains/Losses rows and ST/LT columns"""
    return pd.DataFrame(
        {"Short-Term": [_fmt_gl(stg), _fmt_gl(stl)],
         "Long-Term": [_fmt_gl(ltg), _fmt_gl(ltl)]},
        index=["Gains", "Losses"],
    )


def _build_tax_narrative(result, params) -> str:
    """Build a dynamic prose description of the tax calculation based on actual results."""
    f = lambda v: f"${abs(v):,.2f}"  # format as positive dollar amount
    lines = []

    # --- Realized Gains & Losses ---
    parts = []
    if result.total_stg > 0:
        parts.append(f"**{f(result.total_stg)}** in short-term gains")
    if result.total_stl < 0:
        parts.append(f"**{f(result.total_stl)}** in short-term losses")
    if result.total_ltg > 0:
        parts.append(f"**{f(result.total_ltg)}** in long-term gains")
    if result.total_ltl < 0:
        parts.append(f"**{f(result.total_ltl)}** in long-term losses")
    if parts:
        lines.append(
            "<b>Realized Gains &amp; Losses:</b> "
            "The lots sold to fund your debit card purchases produced "
            + ", ".join(parts) + "."
        )
    else:
        lines.append(
            "<b>Realized Gains &amp; Losses:</b> "
            "No realized gains or losses from the current sales."
        )

    # --- 1st Netting ---
    net_st = result.total_stg + result.total_stl
    net_lt = result.total_ltg + result.total_ltl
    st_word = "gain" if net_st >= 0 else "loss"
    lt_word = "gain" if net_lt >= 0 else "loss"
    netting1 = (
        f"<b>1st Netting (Same-Term):</b> "
        f"Short-term gains and losses net to a short-term {st_word} of <b>{f(net_st)}</b>. "
        f"Long-term gains and losses net to a long-term {lt_word} of <b>{f(net_lt)}</b>."
    )
    lines.append(netting1)

    # --- 2nd Netting ---
    has_cf = params.cfstl < 0 or params.cfltl < 0
    if has_cf:
        cf_parts = []
        if params.cfstl < 0:
            cf_parts.append(f"a carry-forward short-term loss of <b>{f(params.cfstl)}</b>")
        if params.cfltl < 0:
            cf_parts.append(f"a carry-forward long-term loss of <b>{f(params.cfltl)}</b>")
        net_st_after = result.second_net_stg + result.second_net_stl
        net_lt_after = result.second_net_ltg + result.second_net_ltl
        st_word2 = "gain" if net_st_after >= 0 else "loss"
        lt_word2 = "gain" if net_lt_after >= 0 else "loss"
        netting2 = (
            f"<b>2nd Netting (Carry-Forwards):</b> "
            f"You entered the year with {' and '.join(cf_parts)}. "
            f"After applying carry-forwards, the net short-term position is a {st_word2} of "
            f"<b>{f(net_st_after)}</b> and the net long-term position is a {lt_word2} of "
            f"<b>{f(net_lt_after)}</b>."
        )
    else:
        netting2 = (
            "<b>2nd Netting (Carry-Forwards):</b> "
            "No carry-forward losses from prior years, so positions are unchanged."
        )
    lines.append(netting2)

    # --- 3rd Netting ---
    pre_st = result.second_net_stg + result.second_net_stl
    pre_lt = result.second_net_ltg + result.second_net_ltl
    final_net_st = result.final_stg + result.final_stl
    final_net_lt = result.final_ltg + result.final_ltl
    cross_netted = (pre_st > 0 and pre_lt < 0) or (pre_st < 0 and pre_lt > 0)
    if cross_netted:
        final_st_word = "gain" if final_net_st >= 0 else "loss"
        final_lt_word = "gain" if final_net_lt >= 0 else "loss"
        netting3 = (
            f"<b>3rd Netting (Cross-Term):</b> "
            f"Because one term shows a gain and the other a loss, they are netted across "
            f"term boundaries. The final short-term position is a {final_st_word} of "
            f"<b>{f(final_net_st)}</b> and the final long-term position is a {final_lt_word} of "
            f"<b>{f(final_net_lt)}</b>."
        )
    else:
        netting3 = (
            "<b>3rd Netting (Cross-Term):</b> "
            "Both terms are the same direction (both gains or both losses), "
            "so no cross-term netting is required. Positions are unchanged."
        )
    lines.append(netting3)

    # --- OID ---
    if result.oid_applied < 0:
        oid_text = (
            f"<b>Ordinary Income Deduction (OID):</b> "
            f"After netting, <b>{f(result.oid_applied)}</b> in remaining losses "
            f"are applied as an ordinary income deduction (annual limit: "
            f"{f(params.oid_limit)}). This reduces your taxable ordinary income, "
            f"producing a tax credit of <b>{f(abs(result.oid_applied) * params.fed_oi_marginal_tax_rate)}</b> "
            f"at your {params.fed_oi_marginal_tax_rate:.0%} federal ordinary income rate."
        )
    else:
        oid_text = (
            "<b>Ordinary Income Deduction (OID):</b> "
            "No net losses remain after netting, so no ordinary income deduction is applied."
        )
    lines.append(oid_text)

    # --- Carry-Forwards to Next Year ---
    has_next_cf = result.next_year_cfstl < 0 or result.next_year_cfltl < 0
    if has_next_cf:
        cf_next_parts = []
        if result.next_year_cfstl < 0:
            cf_next_parts.append(f"<b>{f(result.next_year_cfstl)}</b> in short-term losses")
        if result.next_year_cfltl < 0:
            cf_next_parts.append(f"<b>{f(result.next_year_cfltl)}</b> in long-term losses")
        cf_text = (
            f"<b>Carry-Forwards to Next Year:</b> "
            f"After netting and OID, {' and '.join(cf_next_parts)} "
            f"will carry forward to the next tax year."
        )
    else:
        cf_text = (
            "<b>Carry-Forwards to Next Year:</b> "
            "All losses were fully consumed by gains and OID. Nothing carries forward."
        )
    lines.append(cf_text)

    # --- Tax Obligation ---
    tax_parts = []
    if result.final_stg > 0:
        stg_after_oid = max(result.final_stg + result.oid_applied, 0)
        if result.oid_applied < 0:
            tax_parts.append(
                f"The net short-term gain of {f(result.final_stg)}, reduced by the "
                f"{f(result.oid_applied)} OID credit to {f(stg_after_oid)}, "
                f"is taxed at your {params.fed_oi_marginal_tax_rate:.0%} federal ordinary income rate "
                f"for <b>{f(result.fed_oi_tax)}</b> in federal ordinary income tax"
            )
        else:
            tax_parts.append(
                f"The net short-term gain of {f(result.final_stg)} is taxed at your "
                f"{params.fed_oi_marginal_tax_rate:.0%} federal ordinary income rate "
                f"for <b>{f(result.fed_oi_tax)}</b> in federal ordinary income tax"
            )
    if result.final_ltg > 0:
        tax_parts.append(
            f"The net long-term gain of {f(result.final_ltg)} is taxed at your "
            f"{params.fed_cg_marginal_tax_rate:.0%} federal capital gains rate "
            f"for <b>{f(result.fed_cg_tax)}</b> in federal capital gains tax"
        )
    if result.state_tax > 0:
        total_gains = result.final_stg + result.final_ltg
        tax_parts.append(
            f"Total gains of {f(total_gains)} are taxed at your "
            f"{params.state_income_marginal_tax_rate:.0%} state income rate "
            f"for <b>{f(result.state_tax)}</b> in state tax"
        )
    if tax_parts:
        tax_text = (
            "<b>Tax Obligation:</b> " + ". ".join(tax_parts)
            + f". Your total tax obligation is <b>{f(result.total_tax)}</b>."
        )
    else:
        tax_text = (
            "<b>Tax Obligation:</b> "
            f"No taxable gains remain after netting. Your total tax obligation is <b>$0.00</b>."
        )
    lines.append(tax_text)

    return "<br><br>".join(lines)


def render_tax_calculation_detail():
    """Render detailed tax calculation breakdown"""
    st.markdown("### 🧮 Tax Calculation")

    if st.session_state.tax_result is None:
        st.info("Process a purchase to see tax calculations.")
        return

    result = st.session_state.tax_result
    params = st.session_state.parameters

    sub1, sub2 = st.tabs(["Detail", "Description"])

    with sub1:
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("#### Realized Gains & Losses")
            st.caption("From sales of purchase lots to fund debit card purchases")
            st.table(_make_netting_table(
                result.total_stg, result.total_stl,
                result.total_ltg, result.total_ltl,
            ))

        with col2:
            st.markdown("#### 1st Netting")
            st.caption("ST gains net ST losses; LT gains net LT losses")
            st.table(_make_netting_table(
                result.first_net_stg, result.first_net_stl,
                result.first_net_ltg, result.first_net_ltl,
            ))

            st.markdown("#### 2nd Netting")
            st.caption("Carry-forward losses netted vs. gains or added to losses")
            st.table(_make_netting_table(
                result.second_net_stg, result.second_net_stl,
                result.second_net_ltg, result.second_net_ltl,
            ))

            st.markdown("#### 3rd Netting")
            st.caption("Cross ST/LT netting — final taxable amounts")
            st.table(_make_netting_table(
                result.final_stg, result.final_stl,
                result.final_ltg, result.final_ltl,
            ))

        with col3:
            st.markdown("#### Ordinary Income Deduction")
            oid_consumed = abs(result.oid_applied)
            oid_remaining = abs(params.oid_limit) - oid_consumed
            st.write(f"**Consumed OID:** ${oid_consumed:,.2f}")
            st.write(f"**Remaining OID:** ${oid_remaining:,.2f}")

            st.markdown("#### Carry Forwards")
            cfstl_next = abs(result.next_year_cfstl)
            cfltl_next = abs(result.next_year_cfltl)
            cfstl_consumed = abs(params.cfstl) - cfstl_next
            cfltl_consumed = abs(params.cfltl) - cfltl_next
            st.write(f"**Consumed CF-STL:** ${cfstl_consumed:,.2f}")
            st.write(f"**Next Year CF-STL:** ${cfstl_next:,.2f}")
            st.write(f"**Consumed CF-LTL:** ${cfltl_consumed:,.2f}")
            st.write(f"**Next Year CF-LTL:** ${cfltl_next:,.2f}")

    with sub2:
        narrative = _build_tax_narrative(result, params)
        st.markdown(
            f'<div style="background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 8px; '
            f'padding: 1.25rem 1.5rem; margin-top: 0.5rem; font-size: 0.9rem; line-height: 1.7; '
            f'color: #333;">{narrative}</div>',
            unsafe_allow_html=True,
        )


def main():
    """Main application entry point"""
    initialize_session_state()
    render_sidebar()

    # Header with title/tabs on left, panels on right (narrow right column)
    header_col1, header_col2 = st.columns([5, 1])
    with header_col1:
        _logo_path = Path(__file__).parent.parent / "assets" / "logo.jpg"
        _logo_b64 = base64.b64encode(_logo_path.read_bytes()).decode()
        st.markdown(
            f'<h1 style="display:flex;align-items:center;gap:12px;">'
            f'<img src="data:image/jpeg;base64,{_logo_b64}" style="height:48px;border-radius:6px;">'
            f'Crypto Tax Optimizer</h1>',
            unsafe_allow_html=True,
        )
        st.markdown("*Demonstrating intelligent tax-optimized cryptocurrency lot selection*")
        # Add spacing before tabs
        st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "💳 Purchase", "📈 Portfolio", "📜 History", "🌊 Tax Waterfall", "🧮 Tax Calculation", "⚖️ Comparison"
        ])
    with header_col2:
        st.markdown("<div style='margin-top: 3.5rem;'></div>", unsafe_allow_html=True)
        render_market_prices_panel()
        render_tax_status_panel()
        render_cash_yield_panel()

    # Tab content (CSS adds visual separator below tab bar)
    with tab1:
        render_debit_card_purchase_tab()
    with tab2:
        render_portfolio_section()
    with tab3:
        render_transaction_history()
    with tab4:
        render_tax_waterfall_status()
    with tab5:
        render_tax_calculation_detail()
    with tab6:
        render_comparison_tab()

    st.divider()
    st.caption("3F Payments - Crypto Tax Optimization Demonstration System v2.5.0")


if __name__ == "__main__":
    main()
