# Things MCP Server

This [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) server lets you use ChatGPT, Codex, Claude Desktop, and other MCP clients to interact with your task management data in [Things 3](https://culturedcode.com/things) from Cultured Code. You can ask your assistant to create tasks, analyze projects, help manage priorities, and more.

This server leverages the [Things.py](https://github.com/thingsapi/things.py) library and the [Things URL Scheme](https://culturedcode.com/things/help/url-scheme/). 

## Experimental: AppleScript read backend

> **This is an experiment on a fork.** It is not the upstream project's behavior. The upstream server ([hald/things-mcp](https://github.com/hald/things-mcp)) reads your Things database directly. This branch (`applescript-read-backend`) asks the running Things app instead. It exists to see whether the server can work on macOS 27 without any file-access setup, and to find out what that costs. Treat it as a prototype: it was tested by hand on one machine (see [What was and wasn't verified](#what-was-and-wasnt-verified)).

### Why

On macOS 27, Claude Desktop starts MCP servers through a helper that stops them inheriting its file access. Things' database lives in a protected folder (`~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/`), so every read fails with `unable to open database file` while writes (which use the Things URL scheme) keep working ([#62](https://github.com/hald/things-mcp/issues/62)). The known workarounds are running the server over HTTP from a context that has file access, or granting access to the specific `uv`/Python binaries, which breaks when they update. Even a normal Terminal can fail the same way on a fresh macOS 27 setup.

### How it differs from upstream

| | Upstream (`hald/things-mcp`) | This branch (default) |
|---|---|---|
| How reads work | Opens the Things SQLite database with [things.py](https://github.com/thingsapi/things.py) | Asks the Things app over Apple Events (JavaScript for Automation, bulk property reads); no file access |
| Permission needed | File access to Things' Group Container | macOS Automation permission to control Things |
| macOS 27 from Claude Desktop | Reads fail unless you set up access or run the HTTP workaround | Works (tested) |
| Headings, checklist items, reminder times, repeating-item details | Yes | **No** (Things' scripting interface doesn't expose them) |
| Auth token for updates | Read from the database automatically | **You set `THINGS_AUTH_TOKEN`** |
| Speed | Milliseconds | About 0.4s of overhead per query; lists take roughly 0.5-1s, Today a few seconds, the full Logbook 7-9s on a library of ~2,300 logged items |
| Things must be running | No | Yes (a read launches it if it isn't) |
| Writes (add/update/bulk/show/search) | URL scheme | Unchanged, same URL scheme |

SQLite stays available: set `THINGS_MCP_BACKEND=sqlite` to get upstream's read behavior and the fields above, if your setup can read the database.

### Tool status

Tested through a live MCP server launched the way Claude Desktop launches it, against a real Things library (about 340 open to-dos, 32 projects, 7 areas, 2,300 logged items). Write tests used clearly named throwaway items.

| Tool | Status | Notes |
|---|---|---|
| `get_inbox`, `get_anytime` | Works | |
| `get_today` | Works | Count matched Things' own Today (15). Items in Someday projects are hidden, as upstream does |
| `get_someday` | Works | Includes Someday projects and the open to-dos inside them |
| `get_upcoming` | Works, differs | Includes repeating-item templates, shown with a `4001-01-01` deadline and no start date. Not compared with upstream |
| `get_logbook` | Works | Period, limit and `project_uuid` filters tested |
| `get_trash` | Works | 3,907 trashed items read in about 2.5s |
| `get_todos` | Works, differs | `include_items` has no effect: checklists are unavailable |
| `get_projects`, `get_areas`, `get_tags` | Works | |
| `get_tagged_items` | Works | Open items only, as designed |
| `get_tag_usage` | Works | Counts come from the same reads; not cross-checked against upstream |
| `get_headings` | **Unavailable** | Returns an explanatory message instead of an empty list |
| `search_todos`, `search_items` | Works | `search_items` opens Things' Search screen (confirmed by reading Things' current list); the query text itself isn't exposed to check |
| `search_advanced` | Works | Tested: `status`, `tag`, `area`, `project`, `type` (to-do/project), `last`, `deadline`, `start_date` (exact and `>=`), `stop_date` with operators. `type="heading"` is unavailable |
| `get_recent` | Works | |
| `add_todo` | Works | Title, notes, tags, `when`, deadline tested. Checklist items are sent but can't be read back here |
| `add_project` | Works | With initial to-dos and `when: someday` |
| `add_area`, `update_area` | Works | Rename and tags tested. Areas can't be deleted through this server (by design), so a test run leaves one behind |
| `update_todo` | Works | Title, notes, `add_tags`, `tags`, deadline, moving into a project, append/clear checklist, completed, canceled. Needs `THINGS_AUTH_TOKEN` |
| `update_project` | Works | Title, notes, deadline, canceled. Needs `THINGS_AUTH_TOKEN` |
| `bulk_update_todos` | Works | Tested: `add_tags`, `tags`, deadline, `when` (a date, `today`, `tomorrow`, `evening`, `someday`, `anytime`), `list`, `list_id`, completed, canceled. `heading`: works (the to-do landed under the right heading, confirmed by eye in Things, since this backend can't read headings back). `evening` shows up as a Today item; Things doesn't expose the evening flag, so that one can't be told apart from `today` by reads. Needs `THINGS_AUTH_TOKEN` |
| `show_item` | Works | Confirmed by reading which list Things reports as current: a built-in list (`logbook`) and a project by ID both navigated correctly |

### Known limitations

- **Unavailable fields.** Headings, checklist items, reminder times and repeating-item details can't be read. Reading a project's to-dos works, but you lose which heading each one sits under. Only the SQLite backend has them.
- **Write confirmations are optimistic.** "Updated todo" means Things accepted the URL. Things applies it a moment later, so a read issued at the same instant (for example, in parallel with the write) can still show the old data; a read a second later is correct. The server clears its read caches after each write.
- **Auth token.** Updating existing items needs the token from Things → Settings → General → Things URLs → Manage, set as `THINGS_AUTH_TOKEN`. Without it, update tools fail with instructions. Adding items doesn't need it.
- **Approximate `start` values.** Items from the Upcoming list are labeled `Someday` (how things.py represents scheduled items), since Things doesn't expose the start list.
- **Speed.** Each Apple Event query costs a process start. There's a short cache and bulk reads, but big views are slower than upstream.

### What was and wasn't verified

- **Verified:** every tool above through a real MCP server run the way Claude Desktop runs it, with the SQLite backend failing and this backend succeeding in the same setup. 222 unit tests pass (the AppleScript backend's are mocked).
- **Not verified:** a side-by-side comparison with upstream's results. On the test machine the upstream backend can't read the database at all, even from Terminal, so parity rests on matching Things' own counts and spot checks. Also untested: a clean machine's first-run Automation prompt, other macOS versions, other Things versions, and the `.mcpb` extension build. Every tool and every documented parameter was exercised at least once, apart from those listed here.

### Try it

From a checkout of this branch, add a server to Claude Desktop's config (`~/Library/Application Support/Claude/claude_desktop_config.json`). Use the absolute path to `uv`, because the helper doesn't use your shell `PATH`:

```json
"things-dev": {
  "command": "/opt/homebrew/bin/uv",
  "args": ["--directory", "/path/to/things-mcp", "run", "things-mcp"],
  "env": { "THINGS_AUTH_TOKEN": "<token from Things>" }
}
```

Quit and reopen Claude Desktop, and disable any other Things MCP extension so the tool names don't clash. To go back to upstream's behavior, remove the server or set `THINGS_MCP_BACKEND=sqlite`.

## Support the Project

If you find this project helpful, consider supporting its development:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/haldick)

## Features

- Access to all major Things lists (Inbox, Today, Upcoming, etc.)
- Project and area management
- Tag operations
- Advanced search capabilities
- Recent items
- Detailed item information including checklists (SQLite backend only; see [Experimental: AppleScript read backend](#experimental-applescript-read-backend))
- Support for nested data (projects within areas, todos within projects)
- Someday project filtering: tasks in Someday projects are automatically excluded from Today, Upcoming, and Anytime views, matching Things UI behavior


## Installation

### Prerequisites
- macOS (Things 3 is Mac-only)
- Things 3 app with "Enable Things URLs" turned on (Settings → General)
- An MCP client, such as the ChatGPT desktop app, Codex, Claude Desktop, or Claude Code
- [uv](https://docs.astral.sh/uv/) Python package manager: `brew install uv`

### Install via uvx (Any MCP Client)

Things MCP is published on PyPI and can be run directly with `uvx`:

```bash
uvx things-mcp
```

Configure your MCP client to use `uvx` with `things-mcp` as the argument.

### Claude Desktop

#### Option 1: One-Click Install (Recommended)

1. Download the latest file from the [releases page](https://github.com/hald/things-mcp/releases)
2. Double-click the `.mcpb` file
3. Done!

#### Option 2: Manual Config

1. Go to **Claude → Settings → Developer → Edit Config**
2. Add the Things server:

```json
{
  "mcpServers": {
    "things": {
      "command": "uvx",
      "args": ["things-mcp"]
    }
  }
}
```

3. Save and restart Claude Desktop

### Claude Code

```bash
claude mcp add-json things '{"command":"uvx","args":["things-mcp"]}'
```

To make it available globally (across all projects), add `-s user`:
```bash
claude mcp add-json -s user things '{"command":"uvx","args":["things-mcp"]}'
```

### ChatGPT Desktop and Codex

The ChatGPT desktop app, Codex CLI, and Codex IDE extension share the same local MCP configuration. The quickest way to add Things MCP is with the Codex CLI:

```bash
codex mcp add things -- uvx things-mcp
```

Confirm that the server is configured:

```bash
codex mcp list
```

You can also configure it in the ChatGPT desktop app:

1. Open **Settings → MCP servers**
2. Select **Add server**
3. Enter `things` as the name, choose **STDIO**, and enter the result of `which uvx` as the command to launch (should look similar to /opt/homebrew/bin/uvx)
4. Enter `things-mcp` under arguments
5. Save the server and select **Restart**

> [!IMPORTANT]
> When using the ChatGPT desktop client, you must use **Work** mode to access Things MCP. Select **ChatGPT** from the top-left menu, then choose **Work** from the toggle at the top of the page. Regular **Chat** mode does not use locally configured MCP tools. You can also select the separate **Codex** view, which shares the same MCP configuration.

In ChatGPT Work or Codex, type `/mcp` to check that the Things server is connected, then try asking, "What's in my Things inbox?"

This local setup does not work in ChatGPT on the web because the web client does not read local Codex MCP configuration. See [OpenAI's MCP documentation](https://developers.openai.com/codex/mcp/) and [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex) for current availability and interface details.

### Verify it's working

After installation:
- If using Claude Desktop, you should see "Things MCP" in the "Search and tools" list
- If using ChatGPT Work or Codex, type `/mcp` and confirm that the Things server is connected
- Try asking: "What's in my Things inbox?"

### Sample Usage with Claude Desktop
* "What's on my todo list today?"
* "Create a todo to pack for my beach vacation next week, include a packing checklist."
* "Evaluate my current todos using the Eisenhower matrix."
* "Help me conduct a GTD-style weekly review using Things."
* "Show me tasks that haven't been modified in over a month."

#### Tips
* Create a project in Claude with custom instructions that explains how you use Things and organize areas, projects, tags, etc. Tell Claude what information you want included when it creates a new task (eg asking it to include relevant details in the task description might be helpful).
* Try adding another MCP server that gives Claude access to your calendar. This will let you ask Claude to block time on your calendar for specific tasks, create todos from upcoming calendar events (eg prep for a meeting), etc.
* Use task ages to identify stale items: "Which tasks in my Anytime list are older than 2 weeks?"


## Available Tools

### List Views
- `get-inbox` - Get todos from Inbox
- `get-today` - Get todos due today
- `get-upcoming` - Get upcoming todos
- `get-anytime` - Get todos from Anytime list
- `get-someday` - Get todos from Someday list, including tasks in Someday projects
- `get-logbook` - Get completed and canceled todos, optionally for one project
- `get-trash` - Get trashed todos

### Basic Operations
- `get-todos` - Get todos, optionally filtered by project
- `get-projects` - Get all projects
- `get-areas` - Get all areas

### Tag Operations
- `get-tags` - Get all tags
- `get-tagged-items` - Get items with a specific tag
- `get-tag-usage` - Report how many items use each tag, sorted by usage; flag unused tags for cleanup

### Search Operations
- `search-todos` - Simple search by title/notes
- `search-advanced` - Advanced search with multiple filters

### Time-based Operations
- `get-recent` - Get open items created within a rolling time window

### Things URL Scheme Operations
- `add-todo` - Create a new todo
- `add-project` - Create a new project
- `add-area` - Create a new Area (via AppleScript; Things URL scheme has no add-area command)
- `update-area` - Update an existing Area: rename or set tags (via AppleScript)
- `update-todo` - Update an existing todo
- `bulk-update-todos` - Apply the same update to many todos in a single operation
- `update-project` - Update an existing project
- `show-item` - Show a specific item or list in Things
- `search-items` - Search for items in Things

## Tool Parameters

### Pagination (most read tools)
The list/search read tools (`get-inbox`, `get-today`, `get-upcoming`, `get-anytime`, `get-someday`, `get-logbook`, `get-trash`, `get-todos`, `get-projects`, `get-areas`, `get-tags`, `get-tagged-items`, `get-headings`, `search-todos`, `search-advanced`, `get-recent`) accept optional pagination:
- `limit` - Maximum number of items to return (default: all; `get-logbook` defaults to 50)
- `offset` - Number of items to skip from the start (default: 0)

When neither is set, output is unchanged. When set, a `Showing X-Y of Z items` header is prepended so you know how much more there is. An `offset` past the end is reported distinctly from an empty result.

These same read tools also return **structured content** alongside the human-readable text: MCP clients receive the raw item dicts plus `count`/`total`/`offset`/`limit` under `structured_content`, so data can be consumed programmatically without parsing the formatted text.

### get-todos
- `project_uuid` (optional) - Filter todos by project
- `include_items` (optional, default: true) - Include checklist items

### get-projects / get-areas / get-tags
- `include_items` (optional, default: false) - Include contained items

### search-advanced
- `status` - Filter by status (incomplete/completed/canceled)
- `start_date` - Filter by start date (YYYY-MM-DD)
- `deadline` - Filter by deadline (YYYY-MM-DD)
- `tag` - Filter by tag
- `area` - Filter by area UUID
- `stop_date` - Filter by completion/cancellation date (YYYY-MM-DD, optionally with an operator such as '>=2024-01-01', or 'past'/'future')
- `project` - Filter by project UUID (includes items under the project's headings)
- `type` - Filter by item type (to-do/project/heading)
- `last` - Filter by creation date (e.g., '3d' for last 3 days, '1w' for last week)

### get-recent
- `period` (required) - Rolling window back from now (e.g., '1d' = the last 24 hours, '1w', '2m', '1y'); months ≈ 30 days, years ≈ 365 days. Returns open (incomplete) items only, newest first

### get-logbook
- `period` (optional, default: '7d') - Look-back window by completion date. Accepts `d`/`w`/`m`/`y` (e.g., '3d', '1w', '2m', '1y'); months ≈ 30 days, years ≈ 365 days
- `limit` (optional, default: 50) - Maximum number of items to return
- `project_uuid` (optional) - Only return items from this project, including items under its headings

Returns both completed and canceled items; each item's `status` tells them apart.

### get-tag-usage
- `only_unused` (optional, default: false) - Return only tags that no item references (cleanup candidates)

### update-todo (checklist & tags)
- `tags` - Replace all tags on the todo
- `add_tags` - Append tags without removing existing ones
- `checklist_items` - Replace the entire checklist with this list; pass an empty list (`[]`) to clear it. Omit it to leave the checklist unchanged
- `prepend_checklist_items` - Add these items to the top of the checklist
- `append_checklist_items` - Add these items to the bottom of the checklist

### bulk-update-todos
Applies the same change to every todo in `ids` in a single operation. Requires the Things auth token to be enabled (Things → Settings → General → Enable Things URLs → Manage); the server reads it automatically.
- `ids` (required) - List of todo UUIDs to update
- `list` / `list_id` - Move all into a project/area (by title or UUID)
- `tags` / `add_tags` - Replace or append tags on all
- `when` - Reschedule all (keyword or YYYY-MM-DD)
- `deadline` - Set deadline on all (YYYY-MM-DD)
- `heading` / `heading_id` - Move all under a heading (by title or UUID)
- `completed` / `canceled` - Mark all completed or canceled

### Scheduling with Reminders (add-todo, add-project, update-todo, update-project)
- `when` - Accepts multiple formats:
  - Keywords: `today`, `tomorrow`, `evening`, `anytime`, `someday`
  - Date: `YYYY-MM-DD` (e.g., `2024-01-15`)
  - DateTime with reminder: `YYYY-MM-DD@HH:MM` (e.g., `2024-01-15@14:30`)

## Troubleshooting

If it's not working:

1. **Make sure Things 3 is installed and has been opened at least once**
   - The first read may show a macOS prompt asking to let the server control Things; allow it
   - `unable to open database file` means you're on the `sqlite` backend without database access; remove `THINGS_MCP_BACKEND` to use the default

2. **Check that "Enable Things URLs" is turned on**
   - Open Things → Settings → General → Enable Things URLs

3. **Claude Desktop can't find `uvx`**
   - Install uv globally with Homebrew (`brew install uv`) 
   - **Alternative**: Use the full path to `uvx` in your config. Find it with `which uvx` (typically `/Users/USERNAME/.local/bin/uvx`)

## Development

### Running Tests

The project includes a comprehensive unit test suite for the URL scheme and formatter modules.

```bash
# Install test dependencies
uv sync --extra test

# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_url_scheme.py

# Run tests matching a pattern
uv run pytest -k "test_add_todo"
```

### MCP Integration Test

The project includes an integration test plan that can be executed by Claude (via Claude Cowork or Claude Code) to verify all MCP tools work correctly against a live Things database.

See [`docs/mcp_integration_test_plan.md`](docs/mcp_integration_test_plan.md) for the full test plan.

### Project Structure

```
things-mcp/
├── src/things_mcp/      # Main package
│   ├── __init__.py      # Package exports
│   ├── __main__.py      # Entry point for python -m
│   ├── server.py        # MCP server implementation
│   ├── url_scheme.py    # Things URL scheme implementation
│   └── formatters.py    # Data formatting utilities
├── tests/               # Unit tests
│   ├── conftest.py      # Test fixtures and configuration
│   ├── test_url_scheme.py
│   ├── test_formatters.py
│   ├── test_someday_filtering.py
│   └── test_mcp_server_filtering.py
├── docs/                # Documentation
│   └── mcp_integration_test_plan.md  # Claude-executable integration test
├── manifest.json        # MCPB package manifest
├── build_mcpb.sh        # MCPB package build script
├── pyproject.toml       # Project dependencies, build config, and pytest config
├── .env.example         # Sample environment configuration
└── run.sh               # Convenience runner script
```

### HTTP Transport

By default, the server uses stdio transport for communication with MCP clients. For remote access scenarios, you can run the server with HTTP transport.

#### Configuration

Set these environment variables to enable HTTP transport:

| Variable | Default | Description |
|----------|---------|-------------|
| `THINGS_MCP_TRANSPORT` | `stdio` | Transport type: `stdio` or `http` |
| `THINGS_MCP_HOST` | `127.0.0.1` | HTTP server bind address |
| `THINGS_MCP_PORT` | `8000` | HTTP server port |
| `THINGS_MCP_BACKEND` | `applescript` | Read backend: `applescript` or `sqlite` (see [Experimental: AppleScript read backend](#experimental-applescript-read-backend)) |
| `THINGS_AUTH_TOKEN` | unset | Things auth token, needed to update existing items on the `applescript` backend |

#### Example

```bash
# Using uvx
THINGS_MCP_TRANSPORT=http THINGS_MCP_HOST=0.0.0.0 THINGS_MCP_PORT=8000 uvx things-mcp

# Or from source
THINGS_MCP_TRANSPORT=http THINGS_MCP_HOST=0.0.0.0 THINGS_MCP_PORT=8000 uv run things-mcp
```

See `.env.example` for a sample configuration file.
