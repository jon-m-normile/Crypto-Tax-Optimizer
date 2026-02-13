"""
State Manager

Handles persistence of application state between sessions.
Uses JSON files for simple, portable storage.
"""

import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import asdict
from pathlib import Path

try:
    from ..models import Lot, Sale, Purchase, Parameters, PurchaseStatus
except ImportError:
    from models import Lot, Sale, Purchase, Parameters, PurchaseStatus


class StateManager:
    """
    Manages application state persistence.
    
    State includes:
    - Portfolio lots
    - User parameters
    - Purchase history
    - Sales history
    """
    
    DEFAULT_STATE_DIR = Path.home() / ".tax_optimizer"
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize the state manager.
        
        Args:
            state_dir: Directory to store state files
        """
        self.state_dir = state_dir or self.DEFAULT_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.lots_file = self.state_dir / "lots.json"
        self.parameters_file = self.state_dir / "parameters.json"
        self.purchases_file = self.state_dir / "purchases.json"
        self.sales_file = self.state_dir / "sales.json"
    
    def save_lots(self, lots: List[Lot]) -> None:
        """Save lots to file"""
        data = []
        for lot in lots:
            lot_dict = {
                "lot_id": lot.lot_id,
                "timestamp": lot.timestamp.isoformat(),
                "currency": lot.currency,
                "quantity": lot.quantity,
                "cost_basis": lot.cost_basis,
                "remaining_quantity": lot.remaining_quantity,
                "eligible_currency": lot.eligible_currency,
            }
            data.append(lot_dict)
        
        with open(self.lots_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_lots(self) -> List[Lot]:
        """Load lots from file"""
        if not self.lots_file.exists():
            return []
        
        try:
            with open(self.lots_file, 'r') as f:
                data = json.load(f)
            
            lots = []
            for item in data:
                lot = Lot(
                    lot_id=item["lot_id"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    currency=item["currency"],
                    quantity=item["quantity"],
                    cost_basis=item["cost_basis"],
                    remaining_quantity=item.get("remaining_quantity", item["quantity"]),
                    eligible_currency=item.get("eligible_currency", True),
                )
                lots.append(lot)
            
            return lots
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error loading lots: {e}")
            return []
    
    def save_parameters(self, parameters: Parameters) -> None:
        """Save parameters to file"""
        data = {
            "lot_order_index": parameters.lot_order_index,
            "gain_lot_ordering": parameters.gain_lot_ordering,
            "loss_lot_ordering": parameters.loss_lot_ordering,
            "min_lot_value": parameters.min_lot_value,
            "cfstl": parameters.cfstl,
            "cfltl": parameters.cfltl,
            "rem_cfstl": parameters.rem_cfstl,
            "rem_cfltl": parameters.rem_cfltl,
            "oid_limit": parameters.oid_limit,
            "rem_oid": parameters.rem_oid,
            "fed_oi_marginal_tax_rate": parameters.fed_oi_marginal_tax_rate,
            "fed_cg_marginal_tax_rate": parameters.fed_cg_marginal_tax_rate,
            "state_income_marginal_tax_rate": parameters.state_income_marginal_tax_rate,
        }
        
        with open(self.parameters_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_parameters(self) -> Optional[Parameters]:
        """Load parameters from file"""
        if not self.parameters_file.exists():
            return None
        
        try:
            with open(self.parameters_file, 'r') as f:
                data = json.load(f)
            
            return Parameters(
                lot_order_index=data.get("lot_order_index", "pnl"),
                gain_lot_ordering=data.get("gain_lot_ordering", "high-to-low"),
                loss_lot_ordering=data.get("loss_lot_ordering", "high-to-low"),
                min_lot_value=data.get("min_lot_value", 10.0),
                cfstl=data.get("cfstl", 0.0),
                cfltl=data.get("cfltl", 0.0),
                rem_cfstl=data.get("rem_cfstl"),
                rem_cfltl=data.get("rem_cfltl"),
                oid_limit=data.get("oid_limit", -3000.0),
                rem_oid=data.get("rem_oid"),
                fed_oi_marginal_tax_rate=data.get("fed_oi_marginal_tax_rate", 0.24),
                fed_cg_marginal_tax_rate=data.get("fed_cg_marginal_tax_rate", 0.15),
                state_income_marginal_tax_rate=data.get("state_income_marginal_tax_rate", 0.05),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error loading parameters: {e}")
            return None
    
    def save_purchases(self, purchases: List[Purchase]) -> None:
        """Save purchases to file"""
        data = []
        for purchase in purchases:
            purchase_dict = {
                "purchase_id": purchase.purchase_id,
                "dcpa": purchase.dcpa,
                "status": purchase.status.value,
                "rdcpa": purchase.rdcpa,
                "total_settlement_amount": purchase.total_settlement_amount,
                "num_sales": purchase.num_sales,
                "total_stl": purchase.total_stl,
                "total_ltl": purchase.total_ltl,
                "total_stg": purchase.total_stg,
                "total_ltg": purchase.total_ltg,
                "description": purchase.description,
                "category": purchase.category,
                "timestamp": purchase.timestamp.isoformat(),
            }
            data.append(purchase_dict)
        
        with open(self.purchases_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_purchases(self) -> List[Purchase]:
        """Load purchases from file"""
        if not self.purchases_file.exists():
            return []
        
        try:
            with open(self.purchases_file, 'r') as f:
                data = json.load(f)
            
            purchases = []
            for item in data:
                purchase = Purchase(
                    purchase_id=item["purchase_id"],
                    dcpa=item["dcpa"],
                    status=PurchaseStatus(item.get("status", "New")),
                    rdcpa=item.get("rdcpa", item["dcpa"]),
                    total_settlement_amount=item.get("total_settlement_amount", 0),
                    num_sales=item.get("num_sales", 0),
                    total_stl=item.get("total_stl", 0),
                    total_ltl=item.get("total_ltl", 0),
                    total_stg=item.get("total_stg", 0),
                    total_ltg=item.get("total_ltg", 0),
                    description=item.get("description", ""),
                    category=item.get("category", ""),
                    timestamp=datetime.fromisoformat(item["timestamp"]) if "timestamp" in item else datetime.now(),
                )
                purchases.append(purchase)
            
            return purchases
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error loading purchases: {e}")
            return []
    
    def save_sales(self, sales: List[Sale]) -> None:
        """Save sales to file"""
        data = []
        for sale in sales:
            sale_dict = {
                "sales_id": sale.sales_id,
                "purchase_id": sale.purchase_id,
                "lot_id": sale.lot_id,
                "tw_step": sale.tw_step,
                "quantity_sold": sale.quantity_sold,
                "quantity_remaining": sale.quantity_remaining,
                "currency": sale.currency,
                "price": sale.price,
                "settlement_amount": sale.settlement_amount,
                "realized_cgl": sale.realized_cgl,
                "stlt": sale.stlt,
                "timestamp": sale.timestamp.isoformat(),
            }
            data.append(sale_dict)
        
        with open(self.sales_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_sales(self) -> List[Sale]:
        """Load sales from file"""
        if not self.sales_file.exists():
            return []
        
        try:
            with open(self.sales_file, 'r') as f:
                data = json.load(f)
            
            sales = []
            for item in data:
                sale = Sale(
                    sales_id=item["sales_id"],
                    purchase_id=item["purchase_id"],
                    lot_id=item["lot_id"],
                    tw_step=item["tw_step"],
                    quantity_sold=item["quantity_sold"],
                    quantity_remaining=item["quantity_remaining"],
                    currency=item["currency"],
                    price=item["price"],
                    settlement_amount=item["settlement_amount"],
                    realized_cgl=item["realized_cgl"],
                    stlt=item["stlt"],
                    timestamp=datetime.fromisoformat(item["timestamp"]) if "timestamp" in item else datetime.now(),
                )
                sales.append(sale)
            
            return sales
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error loading sales: {e}")
            return []
    
    def save_all(self, lots: List[Lot], parameters: Parameters,
                purchases: List[Purchase], sales: List[Sale]) -> None:
        """Save all state"""
        self.save_lots(lots)
        self.save_parameters(parameters)
        self.save_purchases(purchases)
        self.save_sales(sales)
    
    def load_all(self) -> Dict[str, Any]:
        """Load all state"""
        return {
            "lots": self.load_lots(),
            "parameters": self.load_parameters(),
            "purchases": self.load_purchases(),
            "sales": self.load_sales(),
        }
    
    def clear_all(self) -> None:
        """Clear all saved state"""
        for file in [self.lots_file, self.parameters_file, 
                     self.purchases_file, self.sales_file]:
            if file.exists():
                file.unlink()
    
    def has_saved_state(self) -> bool:
        """Check if there is saved state"""
        return self.lots_file.exists() or self.parameters_file.exists()
    
    def export_to_json(self) -> str:
        """Export all state to a single JSON string"""
        state = self.load_all()
        
        # Convert to serializable format
        export_data = {
            "lots": [],
            "parameters": None,
            "purchases": [],
            "sales": [],
            "exported_at": datetime.now().isoformat()
        }
        
        if state["lots"]:
            for lot in state["lots"]:
                export_data["lots"].append({
                    "lot_id": lot.lot_id,
                    "timestamp": lot.timestamp.isoformat(),
                    "currency": lot.currency,
                    "quantity": lot.quantity,
                    "cost_basis": lot.cost_basis,
                    "remaining_quantity": lot.remaining_quantity,
                })
        
        if state["parameters"]:
            p = state["parameters"]
            export_data["parameters"] = {
                "lot_order_index": p.lot_order_index,
                "gain_lot_ordering": p.gain_lot_ordering,
                "loss_lot_ordering": p.loss_lot_ordering,
                "min_lot_value": p.min_lot_value,
                "cfstl": p.cfstl,
                "cfltl": p.cfltl,
                "oid_limit": p.oid_limit,
                "fed_oi_marginal_tax_rate": p.fed_oi_marginal_tax_rate,
                "fed_cg_marginal_tax_rate": p.fed_cg_marginal_tax_rate,
                "state_income_marginal_tax_rate": p.state_income_marginal_tax_rate,
            }
        
        for purchase in state["purchases"]:
            export_data["purchases"].append({
                "purchase_id": purchase.purchase_id,
                "dcpa": purchase.dcpa,
                "status": purchase.status.value,
                "timestamp": purchase.timestamp.isoformat(),
                "description": purchase.description,
            })
        
        for sale in state["sales"]:
            export_data["sales"].append({
                "sales_id": sale.sales_id,
                "lot_id": sale.lot_id,
                "tw_step": sale.tw_step,
                "quantity_sold": sale.quantity_sold,
                "currency": sale.currency,
                "settlement_amount": sale.settlement_amount,
                "realized_cgl": sale.realized_cgl,
                "stlt": sale.stlt,
            })
        
        return json.dumps(export_data, indent=2)


# Singleton instance
_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Get the singleton StateManager instance"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager
