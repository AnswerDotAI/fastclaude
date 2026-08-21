# fastclaude

`fastclaude` is a small, completions-style Python interface backed by the installed
Claude Code executable. It inherits Claude CLI authentication, including OAuth and
subscriptions, without requiring direct Anthropic API integration.

The project is currently at the design/scaffolding stage. The planned interface:

- accepts complete, editable histories as `aidialog.msg_parts.Msg` objects
- compiles them into real Claude Code sessions rather than flattening them into a prompt
- lets Claude own the live agent loop
- exposes ordinary annotated Python callables as tools
- streams Claude output and supports native interruption
- remains stateless across requests

See [DEV.md](DEV.md) for the complete design, protocol findings, source references,
and implementation plan.

## Development

```bash
pip install -e .[dev]
```

The project normally lives in the `~/aai-ws` uv workspace. After its GitHub repository
exists, add it with:

```bash
ws-add fastclaude
```

## License

Apache License 2.0.
