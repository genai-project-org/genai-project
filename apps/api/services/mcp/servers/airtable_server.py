"""In-house MCP server over the Airtable REST API (personal access token in AIRTABLE_ACCESS_TOKEN)."""
import json
import os
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from services.mcp.servers._common import request

API = "https://api.airtable.com/v0"
mcp = FastMCP("airtable")


def _h() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('AIRTABLE_ACCESS_TOKEN', '')}"}


@mcp.tool()
async def list_bases() -> str:
    """List Airtable bases the token can access."""
    d = await request("GET", f"{API}/meta/bases", service="Airtable", headers=_h())
    return "\n".join(f"- {b['name']} id={b['id']}" for b in d.get("bases", [])) or "No bases."


@mcp.tool()
async def list_tables(base_id: str) -> str:
    """List tables (and field names) in a base."""
    d = await request("GET", f"{API}/meta/bases/{base_id}/tables", service="Airtable", headers=_h())
    return "\n".join(f"- {t['name']} id={t['id']} fields=[{', '.join(f['name'] for f in t['fields'])}]"
                     for t in d.get("tables", [])) or "No tables."


@mcp.tool()
async def list_records(base_id: str, table: str, max_records: int = 20) -> str:
    """List records in a table (table name or id)."""
    d = await request("GET", f"{API}/{base_id}/{quote(table)}", service="Airtable", headers=_h(),
                      params={"maxRecords": max(1, min(max_records, 100))})
    return "\n".join(f"- {r['id']}: {json.dumps(r['fields'])[:300]}" for r in d.get("records", [])) or "No records."


@mcp.tool()
async def create_record(base_id: str, table: str, fields_json: str) -> str:
    """Create a record. fields_json is a JSON object of field name -> value."""
    try:
        fields = json.loads(fields_json)
    except ValueError:
        raise RuntimeError("fields_json must be a valid JSON object")
    d = await request("POST", f"{API}/{base_id}/{quote(table)}", service="Airtable", headers=_h(),
                      json={"fields": fields})
    return f"Created record {d['id']}."


if __name__ == "__main__":
    mcp.run()
