from mcp.server.fastmcp import FastMCP

mcp = FastMCP("safe-operations")

@mcp.tool()
def divide(numerator: float, denominator: float) -> str:
    """Divide two numbers.
    
    Args:
        numerator: The dividend
        denominator: The divisor
    
    Returns:
        The quotient or an error message
    """
    try:
        if denominator == 0:
            return "Error: Cannot divide by zero"
        result = numerator / denominator
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def parse_json(data: str) -> str:
    """Parse a JSON string.
    
    Args:
        data: JSON string to parse
    
    Returns:
        Parsed JSON or error message
    """
    import json
    try:
        parsed = json.loads(data)
        return f"Valid JSON: {parsed}"
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {str(e)}"

if __name__ == "__main__":
    mcp.run()
