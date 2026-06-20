from mcp.server.fastmcp import FastMCP

mcp = FastMCP("documentation")

# Define resources
@mcp.resource("doc://api/overview")
def api_overview() -> str:
    """API overview and getting started guide."""
    return """# API Overview

This API provides tools for user management, data querying, and report generation.

## Getting Started
1. Authenticate with your API token
2. Call endpoints with appropriate parameters
3. Handle responses and errors gracefully

## Rate Limits
- 100 requests per minute per API key
- Burst limit: 10 requests per second
"""

@mcp.resource("doc://api/endpoints")
def api_endpoints() -> str:
    """Complete list of API endpoints."""
    return """# API Endpoints

## Users
- GET /users - List all users
- POST /users - Create a user
- GET /users/{id} - Get a specific user
- PUT /users/{id} - Update a user

## Data
- POST /query - Execute a database query
- GET /data/{id} - Retrieve data

## Reports
- GET /reports - List reports
- POST /reports - Generate a report
"""

@mcp.tool()
def get_api_status() -> dict:
    """Check the current API status."""
    return {
        "status": "operational",
        "uptime_percent": 99.99,
        "response_time_ms": 45
    }

if __name__ == "__main__":
    mcp.run()
