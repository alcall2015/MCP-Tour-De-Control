import structlog
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from app.models import McpServer
from app.schemas import McpTestResult, McpToolInfo

log = structlog.get_logger()


class McpService:
    @staticmethod
    async def test_connection(server: McpServer) -> McpTestResult:
        try:
            if server.transport == "stdio":
                if not server.command:
                    return McpTestResult(success=False, error="stdio transport requires a command")
                transport = StdioTransport(
                    command=server.command,
                    args=server.args or [],
                    env=server.env or None,
                )
                async with Client(transport) as client:
                    tools = await client.list_tools()
                    return McpTestResult(
                        success=True,
                        tools=[
                            McpToolInfo(
                                name=t.name,
                                description=t.description,
                                input_schema=t.inputSchema if hasattr(t, "inputSchema") else None,
                            )
                            for t in tools
                        ],
                    )
            elif server.transport == "http":
                if not server.url:
                    return McpTestResult(success=False, error="http transport requires a url")
                async with Client(server.url) as client:
                    tools = await client.list_tools()
                    return McpTestResult(
                        success=True,
                        tools=[
                            McpToolInfo(
                                name=t.name,
                                description=t.description,
                                input_schema=t.inputSchema if hasattr(t, "inputSchema") else None,
                            )
                            for t in tools
                        ],
                    )
            else:
                return McpTestResult(success=False, error=f"Unknown transport: {server.transport}")
        except Exception as e:
            log.error("MCP connection test failed", server=server.name, error=str(e))
            return McpTestResult(success=False, error=str(e))

    @staticmethod
    async def get_server_tools(server: McpServer) -> list[dict]:
        result = await McpService.test_connection(server)
        if result.success:
            return [t.model_dump() for t in result.tools]
        return []
