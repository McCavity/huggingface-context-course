from mcp.server.fastmcp import FastMCP

mcp = FastMCP("prompts-server")

@mcp.prompt()
def code_review_prompt(language: str = "python") -> str:
    """Template for reviewing code in a specific language."""
    return f"""You are an expert {language} code reviewer. 
Analyze the provided code and provide feedback on:
1. Correctness and logic
2. Performance and efficiency
3. Code style and readability
4. Security implications
5. Testing coverage

Be constructive and suggest improvements."""

@mcp.prompt()
def security_audit_prompt() -> str:
    """Template for security audits."""
    return """Conduct a security audit of the provided code or system. Check for:
1. Authentication vulnerabilities
2. Authorization issues
3. Data validation gaps
4. SQL injection or injection attacks
5. Insecure dependencies
6. Sensitive information exposure

Rate each finding by severity (critical, high, medium, low)."""

@mcp.tool()
def get_available_prompts() -> list[str]:
    """List available prompt templates."""
    return ["code_review_prompt", "security_audit_prompt"]

if __name__ == "__main__":
    mcp.run()
