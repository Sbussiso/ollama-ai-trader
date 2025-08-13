import json
import logging
from coinbase.rest import RESTClient
from typing import Dict, Any, Optional, List

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
    logging.getLogger(__name__).warning("Coinbase API credentials are not set in config.json (coinbase.coinbase_api_key/coinbase.coinbase_api_secret)")
client = RESTClient(api_key=api_key, api_secret=api_secret)

logger = logging.getLogger(__name__)


def create_portfolio(client, name: str) -> Dict[str, Any]:
    """
    Create a new portfolio in Coinbase Advanced Trade
    
    Args:
        client: RESTClient instance
        name: Name for the new portfolio (must be unique)
    
    Returns:
        dict: JSON-formatted response with portfolio creation details
    """
    try:
        # Create portfolio using the Advanced Trade API
        response = client.create_portfolio(name=name)
        
        # Extract portfolio information from response
        portfolio_data = {
            "success": True,
            "portfolio_name": name,
            "created": True,
            "message": f"Portfolio '{name}' created successfully"
        }
        
        # Add portfolio details if available
        if hasattr(response, 'portfolio'):
            portfolio_info = getattr(response, 'portfolio', None)
            if portfolio_info:
                if hasattr(portfolio_info, 'name'):
                    portfolio_data["confirmed_name"] = getattr(portfolio_info, 'name', None)
                if hasattr(portfolio_info, 'uuid'):
                    portfolio_data["portfolio_uuid"] = getattr(portfolio_info, 'uuid', None)
                if hasattr(portfolio_info, 'type'):
                    portfolio_data["portfolio_type"] = getattr(portfolio_info, 'type', None)
        
        return portfolio_data
        
    except Exception as e:
        error_message = str(e)
        
        # Handle common error cases
        if "already exists" in error_message.lower():
            return {
                "success": False,
                "error": f"Portfolio '{name}' already exists. Please choose a different name.",
                "portfolio_name": name,
                "created": False
            }
        elif "invalid" in error_message.lower():
            return {
                "success": False,
                "error": f"Invalid portfolio name '{name}'. Please use a valid name.",
                "portfolio_name": name,
                "created": False
            }
        else:
            return {
                "success": False,
                "error": error_message,
                "portfolio_name": name,
                "created": False
            }


# Test the function
if __name__ == "__main__":
    # Create a new portfolio
    portfolio_result = create_portfolio(client, "AI_Trading_Bot_Portfolio")
    logging.basicConfig(level=logging.INFO)
    logger.info(json.dumps(portfolio_result, indent=2))
