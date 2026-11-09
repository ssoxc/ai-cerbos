"""A small, local MCP server for the demo: the "Knowledge base" from the asset registry.

LiteLLM's MCP gateway proxies it (infra/litellm.yaml). Before every tool call LiteLLM
asks Cerbos (infra/cerbos_guard.py, cerbos/policies/mcp_tool.yaml) whether the calling
API key may use that tool. The tools carry standard MCP annotations describing their
risk; nothing here touches real data.
"""

import os
from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

server = MCPServer(
    name="knowledge",
    title="Knowledge base",
    description="Search and maintain the team's shared documentation (demo data).",
)

DOCUMENTS = [
    {"title": "Agent onboarding checklist", "team": "agents"},
    {"title": "Incident response runbook", "team": "platform"},
    {"title": "Benefits overview 2026", "team": "people-ops"},
    {"title": "Cerbos policy style guide", "team": "platform"},
]
NOTES: list[dict] = []


@server.tool(
    title="Search documents",
    description="Search the knowledge base by keyword.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
)
def search_docs(query: str) -> dict:
    words = query.lower().split()
    matches = [d for d in DOCUMENTS if any(w in d["title"].lower() for w in words)] or DOCUMENTS[:2]
    return {"query": query, "results": [d["title"] for d in matches]}


@server.tool(
    title="Add a note",
    description="Add a note to the knowledge base.",
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
)
def add_note(title: str, body: str = "") -> dict:
    NOTES.append({"title": title, "body": body, "at": datetime.now(UTC).isoformat()})
    return {"saved": title, "notes": len(NOTES)}


@server.tool(
    title="Delete a collection",
    description="Permanently delete a document collection. (Demo: deletes nothing.)",
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True),
)
def delete_collection(name: str) -> dict:
    return {"deleted": name, "note": "Demo server: nothing was actually deleted."}


if __name__ == "__main__":
    import anyio

    port = int(os.environ.get("MCP_PORT", "8082"))
    # Reachable only inside the Compose network, by LiteLLM; not published on the host.
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    anyio.run(
        lambda: server.run_streamable_http_async(
            host="0.0.0.0", port=port, stateless_http=True, transport_security=security
        )
    )
