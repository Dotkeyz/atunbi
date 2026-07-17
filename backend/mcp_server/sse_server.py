"""
MCP Server (SSE transport) — mounted on FastAPI for remote access.
Connect any MCP client remotely: http://8.211.196.226/mcp/sse
"""
from fastapi import APIRouter, Request
from mcp.server.sse import SseServerTransport
from mcp_server.atunbi_server import server as atunbi_server

router = APIRouter(tags=["MCP"])

MCP_MESSAGE_PATH = "/mcp/messages"


@router.get("/mcp/sse")
async def mcp_sse(request: Request):
    """SSE endpoint for remote MCP clients to connect."""
    transport = SseServerTransport(MCP_MESSAGE_PATH)

    async with transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await atunbi_server.run(
            read_stream, write_stream,
            atunbi_server.create_initialization_options(),
        )


@router.post("/mcp/messages")
async def mcp_messages(request: Request):
    """POST endpoint for MCP client messages."""
    transport = SseServerTransport(MCP_MESSAGE_PATH)
    await transport.handle_post_message(
        request.scope, request.receive, request._send
    )
