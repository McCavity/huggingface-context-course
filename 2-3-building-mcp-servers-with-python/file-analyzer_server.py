from mcp.server.fastmcp import FastMCP
import os

mcp = FastMCP("file-analyzer")

@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file.
    
    Args:
        path: The absolute file path to read
    
    Returns:
        The file contents as a string
    """
    try:
        with open(path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File not found at {path}"
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def count_lines(path: str) -> int:
    """Count the number of lines in a file.
    
    Args:
        path: The absolute file path
    
    Returns:
        The number of lines in the file
    """
    try:
        with open(path, 'r') as f:
            return len(f.readlines())
    except Exception as e:
        return -1

@mcp.tool()
def list_directory(path: str) -> list[str]:
    """List files in a directory.
    
    Args:
        path: The directory path
    
    Returns:
        A list of file names in the directory
    """
    try:
        return os.listdir(path)
    except Exception as e:
        return []

if __name__ == "__main__":
    mcp.run()
