#!/usr/bin/env python
"""
List all orders from the AI Trading Bot Portfolio directly from Coinbase API

This script demonstrates retrieving orders directly from the Coinbase API
without using a local database.
"""

import json
import logging
import time
import base64
import hmac
import hashlib
import http.client
from urllib.parse import urlencode
import pandas as pd
from datetime import datetime
from coinbase.rest import RESTClient
import uuid

# Configure logging
logger = logging.getLogger(__name__)

# Coinbase API setup via config.json
import json
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

# Initialize RESTClient for account-related operations
client = RESTClient(api_key=api_key, api_secret=api_secret)


def get_ai_portfolio_id():
    """Get the UUID of the AI Trading Bot Portfolio"""
    try:
        portfolios_response = client.get_portfolios()
        
        if hasattr(portfolios_response, 'portfolios'):
            portfolios = getattr(portfolios_response, 'portfolios', [])
            for portfolio in portfolios:
                if hasattr(portfolio, 'name') and getattr(portfolio, 'name', '') == "AI_Trading_Bot_Portfolio":
                    portfolio_uuid = getattr(portfolio, 'uuid', None)
                    logger.info(f"Found AI Trading Bot Portfolio: {portfolio_uuid}")
                    return portfolio_uuid
        
        logger.error("AI Trading Bot Portfolio not found")
        return None
        
    except Exception as e:
        logger.error(f"Error getting portfolio ID: {str(e)}")
        return None


def get_agent_orders(filter_status="ALL"):
    """
    Get orders from the AI Trading Bot Portfolio with optional status filtering.
    
    Args:
        filter_status (str): Filter orders by status. Must be one of:
            - 'ALL': All orders (default)
            - 'OPEN': Only open orders
            - 'FILLED': Only filled orders
            - 'CANCELED': Only canceled orders
            
    Returns:
        pd.DataFrame: DataFrame containing the filtered orders
    """
    # Map filter values to status values expected by the API
    status_map = {
        'ALL': None,  # No status filter
        'OPEN': 'OPEN',
        'FILLED': 'FILLED',
        'CANCELED': 'CANCELLED'  # Note: API uses 'CANCELLED' with two Ls
    }
    
    if filter_status not in status_map:
        raise ValueError(f"Invalid filter value. Must be one of: {list(status_map.keys())}")

    
    portfolio_id = get_ai_portfolio_id()
    all_orders = []
    cursor = None

    while True:
        # Prepare request parameters
        params = {
            'limit': 100,
            'cursor': cursor,
            'retail_portfolio_id': portfolio_id,  # optional if your key is portfolio-scoped
            'order_status': status_map[filter_status] if filter_status != 'ALL' else None
        }
        
        # Remove None values from params
        params = {k: v for k, v in params.items() if v is not None}
        
        # Make the API request
        resp = client.list_orders(**params)
        all_orders.extend(resp.orders)

        if not getattr(resp, "has_next", False):
            break
        cursor = resp.cursor
    
    # Convert to pandas DataFrame
    if not all_orders:
        return pd.DataFrame()
    
    # Extract useful fields from each order
    orders_data = []
    for order in all_orders:
        order_dict = {
            "order_id": getattr(order, "order_id", "Unknown"),
            "product_id": getattr(order, "product_id", "Unknown"),
            "side": getattr(order, "side", "Unknown"),
            "status": getattr(order, "status", "Unknown"),
            "created_time": getattr(order, "created_time", None),
            "filled_size": getattr(order, "filled_size", "0"),
            "average_filled_price": getattr(order, "average_filled_price", "0")
        }
        orders_data.append(order_dict)
    
    # Create DataFrame
    return pd.DataFrame(orders_data)


def list_agent_orders(filter_status: str = "ALL") -> str:
    """
    List orders from the AI Trading Bot Portfolio.
    This is the main tool function for the agent - returns a formatted string summary.
    
    Args:
        filter_status: Filter orders by status. Must be one of:
            - 'ALL': All orders (default)
            - 'OPEN': Only open orders
            - 'FILLED': Only filled orders
            - 'CANCELED': Only canceled orders
    
    Returns:
        str: Formatted string summary of orders or error message
    """
    try:
        orders_df = get_agent_orders(filter_status=filter_status)
        
        if orders_df.empty:
            return f"No {filter_status.lower()} orders found in AI Trading Bot Portfolio."
        
        # Create a summary string
        summary = f"\n📊 AI Trading Bot Portfolio Orders ({filter_status}):\n"
        summary += f"Total orders: {len(orders_df)}\n\n"
        
        # Add details for each order
        for _, order in orders_df.iterrows():
            summary += f"Order ID: {order['order_id']}\n"
            summary += f"  Product: {order['product_id']}\n"
            summary += f"  Side: {order['side']}\n"
            summary += f"  Status: {order['status']}\n"
            summary += f"  Created: {order['created_time']}\n"
            summary += f"  Filled Size: {order['filled_size']}\n"
            summary += f"  Avg Price: ${order['average_filled_price']}\n\n"
        
        return summary
        
    except Exception as e:
        logger.error(f"Error listing agent orders: {str(e)}")
        return f"❌ Error listing agent orders: {str(e)}"


def get_list_orders_tool():
    """
    Get list orders tool for the agent.
    This is a wrapper function that returns the main tool function.
    
    Returns:
        function: The list_agent_orders function
    """
    return list_agent_orders


if __name__ == "__main__":
    logger.info("Getting agent orders...")
    orders_summary = list_agent_orders(filter_status='CANCELED')
    logger.info(orders_summary)
    logger.info("Done.")