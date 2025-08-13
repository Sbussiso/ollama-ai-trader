import json
import logging
from coinbase.rest import RESTClient
from typing import Dict, Any, Optional, List

# Configure logging
logger = logging.getLogger(__name__)

CONFIG = {}
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {}
_cb = CONFIG.get("coinbase", {}) if isinstance(CONFIG.get("coinbase", {}), dict) else {}
api_key = str(_cb.get("coinbase_api_key", CONFIG.get("coinbase_api_key", "")))
api_secret = str(_cb.get("coinbase_api_secret", CONFIG.get("coinbase_api_secret", "")))
if not api_key or not api_secret:
    logger.warning("Coinbase API credentials are not set in config.json (coinbase.coinbase_api_key/coinbase.coinbase_api_secret)")
client = RESTClient(api_key=api_key, api_secret=api_secret)


def get_product_info(client, product_id: str = "BTC-USD") -> Dict[str, Any]:
    """
    Get essential product information from Coinbase Advanced Trade API
    
    Args:
        client: RESTClient instance
        product_id: Trading pair (e.g., "BTC-USD", "ETH-USD", "SOL-USD")
    
    Returns:
        dict: JSON-formatted product information with essential data only
    """
    try:
        # Get product data from API
        product_response = client.get_product(product_id)
        
        # Extract only essential information
        current_price = float(getattr(product_response, 'price', 0)) if getattr(product_response, 'price', None) else None
        price_change_24h_percent = float(getattr(product_response, 'price_percentage_change_24h', 0)) if getattr(product_response, 'price_percentage_change_24h', None) else None
        volume_24h = float(getattr(product_response, 'volume_24h', 0)) if getattr(product_response, 'volume_24h', None) else None
        
        # Calculate price change in absolute terms
        price_change_24h_absolute = None
        if current_price and price_change_24h_percent is not None:
            price_change_24h_absolute = round((current_price * price_change_24h_percent) / 100, 2)
        
        return {
            "success": True,
            "product_id": product_id,
            "price": current_price,
            "price_change_24h": price_change_24h_absolute,
            "price_change_24h_percent": price_change_24h_percent,
            "volume_24h": volume_24h,
            "base_currency": getattr(product_response, 'base_display_symbol', None),
            "quote_currency": getattr(product_response, 'quote_display_symbol', None),
            "trading_disabled": getattr(product_response, 'trading_disabled', False)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "product_id": product_id
        }


# Test the function
if __name__ == "__main__":
    # Get single product information
    product_info = get_product_info(client, "BTC-USD")
    logger.info(json.dumps(product_info, indent=2))