"""
Data Input Service

Handles reading and parsing of CSV input files:
- Purchase_Lots.csv: Client's portfolio of purchase lots
- User_Parameters.csv: Configuration settings
"""

import csv
import io
from datetime import datetime
from typing import List, Tuple, Optional
try:
    from ..models import Lot, Parameters
except ImportError:
    from models import Lot, Parameters


class DataInputService:
    """
    Service for reading and parsing client input files.
    
    Supports reading from:
    - File paths
    - File-like objects (for Streamlit uploads)
    - String content
    """
    
    @staticmethod
    def parse_purchase_lots_csv(content: str) -> Tuple[List[Lot], List[str]]:
        """
        Parse Purchase_Lots.csv content into Lot objects.
        
        Expected CSV format:
        lot_id,timestamp,currency,quantity,cost_basis
        
        Args:
            content: CSV file content as string
            
        Returns:
            Tuple of (list of Lot objects, list of error messages)
        """
        lots = []
        errors = []
        
        try:
            reader = csv.DictReader(io.StringIO(content))
            
            # Normalize column names (handle different casing/spacing)
            fieldnames = reader.fieldnames
            if not fieldnames:
                errors.append("CSV file appears to be empty or has no headers")
                return lots, errors
            
            # Create a mapping for flexible column matching
            column_map = {}
            for field in fieldnames:
                normalized = field.lower().strip().replace(' ', '_').replace('-', '_')
                column_map[normalized] = field
            
            # Required columns
            required = ['lot_id', 'timestamp', 'currency', 'quantity', 'cost_basis']
            missing = [col for col in required if col not in column_map]
            if missing:
                errors.append(f"Missing required columns: {', '.join(missing)}")
                return lots, errors
            
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                try:
                    # Extract values using the column map
                    lot_id = str(row[column_map['lot_id']]).strip()
                    timestamp_str = str(row[column_map['timestamp']]).strip()
                    currency = str(row[column_map['currency']]).strip().upper()
                    quantity_str = str(row[column_map['quantity']]).strip()
                    cost_basis_str = str(row[column_map['cost_basis']]).strip()
                    
                    # Parse timestamp - try multiple formats
                    timestamp = DataInputService._parse_timestamp(timestamp_str)
                    if timestamp is None:
                        errors.append(f"Row {row_num}: Invalid timestamp format '{timestamp_str}'")
                        continue
                    
                    # Parse numeric values
                    try:
                        quantity = float(quantity_str.replace(',', ''))
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid quantity '{quantity_str}'")
                        continue
                    
                    try:
                        cost_basis = float(cost_basis_str.replace(',', '').replace('$', ''))
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid cost_basis '{cost_basis_str}'")
                        continue
                    
                    # Validate values
                    if quantity <= 0:
                        errors.append(f"Row {row_num}: Quantity must be positive")
                        continue
                    
                    if cost_basis < 0:
                        errors.append(f"Row {row_num}: Cost basis cannot be negative")
                        continue
                    
                    # Create Lot object
                    lot = Lot(
                        lot_id=lot_id,
                        timestamp=timestamp,
                        currency=currency,
                        quantity=quantity,
                        cost_basis=cost_basis
                    )
                    lots.append(lot)
                    
                except KeyError as e:
                    errors.append(f"Row {row_num}: Missing column {e}")
                except Exception as e:
                    errors.append(f"Row {row_num}: Error parsing - {str(e)}")
            
        except csv.Error as e:
            errors.append(f"CSV parsing error: {str(e)}")
        except Exception as e:
            errors.append(f"Unexpected error: {str(e)}")
        
        return lots, errors
    
    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> Optional[datetime]:
        """Try to parse a timestamp string using multiple formats"""
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue
        
        return None
    
    @staticmethod
    def parse_user_parameters_csv(content: str) -> Tuple[Parameters, List[str]]:
        """
        Parse User_Parameters.csv content into a Parameters object.
        
        Expected CSV format (parameter,value):
        lot_order_index,pnl
        gain_lot_ordering,high-to-low
        ...
        
        Or (name,value format):
        name,value
        lot_order_index,pnl
        ...
        
        Args:
            content: CSV file content as string
            
        Returns:
            Tuple of (Parameters object, list of error messages)
        """
        errors = []
        param_dict = {}
        
        try:
            reader = csv.DictReader(io.StringIO(content))
            fieldnames = reader.fieldnames
            
            if not fieldnames:
                errors.append("CSV file appears to be empty or has no headers")
                return Parameters(), errors
            
            # Normalize column names
            normalized_fields = [f.lower().strip() for f in fieldnames]
            
            # Determine CSV format
            if len(normalized_fields) >= 2:
                # Could be (name, value) or (parameter_name, value) format
                name_col = None
                value_col = None
                
                for i, field in enumerate(normalized_fields):
                    if field in ['name', 'parameter', 'param', 'parameter_name', 'title']:
                        name_col = fieldnames[i]
                    elif field in ['value', 'setting', 'val']:
                        value_col = fieldnames[i]
                
                if name_col and value_col:
                    # Parse as name/value pairs
                    for row in reader:
                        param_name = row[name_col].lower().strip().replace(' ', '_').replace('-', '_')
                        param_value = row[value_col].strip()
                        param_dict[param_name] = param_value
                else:
                    # Try first column as name, second as value
                    for row in reader:
                        values = list(row.values())
                        if len(values) >= 2:
                            param_name = str(values[0]).lower().strip().replace(' ', '_').replace('-', '_')
                            param_value = str(values[1]).strip()
                            param_dict[param_name] = param_value
            
        except csv.Error as e:
            errors.append(f"CSV parsing error: {str(e)}")
        except Exception as e:
            errors.append(f"Unexpected error: {str(e)}")
        
        # Create Parameters object with parsed values
        params = Parameters()
        
        # Map parsed values to Parameters fields
        param_mapping = {
            'lot_order_index': ('lot_order_index', str),
            'gain_lot_ordering': ('gain_lot_ordering', str),
            'loss_lot_ordering': ('loss_lot_ordering', str),
            'min_lot_value': ('min_lot_value', float),
            'carry_forward_stl': ('cfstl', lambda x: -abs(float(x))),
            'cfstl': ('cfstl', lambda x: -abs(float(x))),
            'carry_forward_ltl': ('cfltl', lambda x: -abs(float(x))),
            'cfltl': ('cfltl', lambda x: -abs(float(x))),
            'oid_limit': ('oid_limit', lambda x: -abs(float(x))),
            'fed_oi_marginal_tax_rate': ('fed_oi_marginal_tax_rate', float),
            'fed_cg_marginal_tax_rate': ('fed_cg_marginal_tax_rate', float),
            'state_income_marginal_tax_rate': ('state_income_marginal_tax_rate', float),
        }
        
        for csv_name, (attr_name, converter) in param_mapping.items():
            if csv_name in param_dict:
                try:
                    value = param_dict[csv_name]
                    # Handle percentage formats
                    if 'rate' in csv_name and '%' in str(value):
                        value = value.replace('%', '')
                        converted = float(value) / 100
                    else:
                        converted = converter(value)
                    setattr(params, attr_name, converted)
                except (ValueError, TypeError) as e:
                    errors.append(f"Error parsing {csv_name}: {str(e)}")
        
        # Re-run __post_init__ to set remaining values
        params.__post_init__()
        
        return params, errors
    
    @staticmethod
    def read_file(file_path: str) -> str:
        """Read a file and return its content as string"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    @staticmethod
    def read_uploaded_file(uploaded_file) -> str:
        """Read a Streamlit UploadedFile and return content as string"""
        content = uploaded_file.getvalue()
        if isinstance(content, bytes):
            return content.decode('utf-8')
        return content


def load_sample_lots() -> List[Lot]:
    """
    Generate sample lot data for testing/demo purposes.
    Returns a diverse portfolio of cryptocurrency lots.
    """
    from datetime import datetime, timedelta
    import random
    
    base_date = datetime.now()
    lots = []
    
    # Sample data with mix of ST/LT and gains/losses
    sample_data = [
        # BTC lots - mix of old and new
        ("BTC-001", base_date - timedelta(days=400), "BTC", 0.5, 20000),   # LT gain
        ("BTC-002", base_date - timedelta(days=200), "BTC", 0.3, 45000),   # ST loss
        ("BTC-003", base_date - timedelta(days=100), "BTC", 0.2, 35000),   # ST gain
        
        # ETH lots
        ("ETH-001", base_date - timedelta(days=500), "ETH", 2.0, 1500),    # LT gain
        ("ETH-002", base_date - timedelta(days=180), "ETH", 1.5, 4000),    # ST loss
        ("ETH-003", base_date - timedelta(days=30), "ETH", 1.0, 2800),     # ST gain
        
        # SOL lots
        ("SOL-001", base_date - timedelta(days=450), "SOL", 50, 25),       # LT gain
        ("SOL-002", base_date - timedelta(days=90), "SOL", 30, 250),       # ST loss
        ("SOL-003", base_date - timedelta(days=60), "SOL", 20, 150),       # ST gain
        
        # ADA lots
        ("ADA-001", base_date - timedelta(days=380), "ADA", 5000, 1.50),   # LT loss
        ("ADA-002", base_date - timedelta(days=150), "ADA", 3000, 0.40),   # ST gain
        
        # LINK lots
        ("LINK-001", base_date - timedelta(days=400), "LINK", 100, 8),     # LT gain
        ("LINK-002", base_date - timedelta(days=50), "LINK", 50, 25),      # ST loss
    ]
    
    for lot_id, timestamp, currency, quantity, price in sample_data:
        lots.append(Lot(
            lot_id=lot_id,
            timestamp=timestamp,
            currency=currency,
            quantity=quantity,
            cost_basis=quantity * price
        ))
    
    return lots


def load_sample_parameters() -> Parameters:
    """Generate sample parameters for testing/demo purposes"""
    return Parameters(
        lot_order_index="pnl",
        gain_lot_ordering="high-to-low",
        loss_lot_ordering="high-to-low",
        min_lot_value=50.0,
        cfstl=-2000.0,
        cfltl=-1500.0,
        oid_limit=-3000.0,
        fed_oi_marginal_tax_rate=0.24,
        fed_cg_marginal_tax_rate=0.15,
        state_income_marginal_tax_rate=0.05
    )
