"""
Allow running the MCP Memory server as a module:

    python -m mcp_memory
    python -m mcp_memory --port 8002
"""

from mcp_memory.server import main

if __name__ == "__main__":
    main()
