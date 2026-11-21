"""Server behaviour that depends on which read backend is active."""
import pytest
from unittest.mock import patch

from tests._helpers import tool_text
from things_mcp import server, url_scheme


async def test_headings_report_unavailable_on_applescript_backend():
    with patch.object(server, "SUPPORTS_STRUCTURE", False):
        result = await server.get_headings()
    text = tool_text(result)
    assert "not available" in text and "THINGS_MCP_BACKEND=sqlite" in text


async def test_search_advanced_heading_type_reports_unavailable():
    with patch.object(server, "SUPPORTS_STRUCTURE", False):
        result = await server.search_advanced(type="heading")
    assert "not available" in tool_text(result)


def test_update_without_token_raises_actionable_error():
    with patch.object(url_scheme.things, "token", return_value=None):
        with pytest.raises(url_scheme.MissingAuthToken, match="THINGS_AUTH_TOKEN"):
            url_scheme.construct_url("update", {"id": "abc"})


def test_add_without_token_still_works():
    with patch.object(url_scheme.things, "token", return_value=None):
        assert url_scheme.construct_url("add", {"title": "x"}).startswith("things:///add?")
