"""Small completions-style Python interface backed by the Claude CLI

Modules:

- `fastclaude.core`: `astream` and `ClaudeRun`: stateless user turns with in-place caller-owned tool continuation through Claude Code
- `fastclaude.protocol`: Claude Code's stream-json wire protocol: NDJSON transport, control routing, and paused MCP tool calls
- `fastclaude.session`: Read, write, and build native Claude Code session transcripts"""

__version__ = "0.0.3"
