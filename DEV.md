# fastclaude development plan

## Status

This document records the design agreed before implementation. The initial package is intentionally small: it provides a completions-style Python interface backed by the installed Claude Code executable and its configured authentication, including OAuth and subscriptions, rather than integrating with the Anthropic API directly.

**Progress (2026-08-22):** the transcript codec move (see "Native transcript codec" and "Migration plan" below) is done: `fastclaude.session` now owns the layout, record-construction, writing, reading, and tool-qualification primitives, plus the captured ant fixtures as package data, with llmsurgery, fastllm-claude-code, and llmdojo importing from it. Deviations from the plan as written: `cur_sess` and `sess_file` moved wholesale (llmsurgery keeps only naming/resolution); the rec-to-Msg converters (`recs2chat` etc.) stayed in llmsurgery, since the lossless returned trace comes from fastllm's `norm_parts` instead; `tool_reply` stays until the protocol module exists; `uniq_path` moved from `llmsurgery.utils`.

**Progress (2026-08-22, later):** `fastclaude.protocol` (NDJSON framing, the MCP-shaped bridge on `fastcore.funccall`, `ClaudeProto` control routing with per-request cancellable handlers) and `fastclaude.core` (`astream`/`ClaudeRun`: compile, spawn, trace accumulation from full events, native interrupt, shielded close/drain/escalate/remove cleanup) are implemented, with offline scripted-peer lessons plus live-validated runs: plain completion, in-process tool loop, interrupt mid-tool (Claude sends `control_cancel_request`, terminal_reason `aborted_tools`), and stateless continuation with signatures replayed. The default cwd is an XDG cache work dir (`xdg_cache_home()/'fastclaude'`), replacing `~/.fastllm-claude-agent`. `fastllm-claude-code` is ported: history and chat-ns callables pass to `astream` (via `ClaudeCodeCallback` injecting `ns`), all tool calls stream server-marked with real results merged in, each turn's history is reshaped to the external-loop message shape, and the Agent SDK and llmsurgery dependencies are gone. A host closing the stream interrupts the run and cancels the in-flight callable, verified live. `tool_reply` was not moved: the bridge grew its own `tool_content` (callable returns, not Anthropic tool_result blocks); llmsurgery's deferred machinery is now uncalled outside llmsurgery and can be deleted when convenient. Not yet done: ipyai/solveit adoption (step 5), a fixture refresh carrying visible thinking, and the deferred-tools future option remains unimplemented by design.

The important decisions are:

- Each request is independent. `fastclaude` never owns conversation state across calls.
- Callers pass complete history as `aidialog.msg_parts.Msg` objects, so they can edit, hide, rewind, or replace any earlier message.
- History is compiled into a real Claude Code JSONL transcript and resumed. It is not rendered into XML or flattened into a prompt.
- The last input message must be a genuine user prompt. A history ending only in `ToolResult` is not supported initially.
- Claude owns the live agent/tool loop. Python only supplies tool definitions and executes callbacks when Claude requests them.
- Public tools are ordinary Python callables. MCP is only a small private wire-protocol implementation required by Claude Code; `fastclaude` will not depend on the `mcp` package or expose MCP concepts in its API.
- The low-level Claude transcript codec currently in `llmsurgery.ant` moves into `fastclaude`. `llmsurgery` then depends on `fastclaude`, not the reverse.
- Interrupts use Claude Code's native control request before falling back to process termination.

## Purpose

Claude Code already implements the expensive and difficult parts of a Claude agent:

- OAuth and subscription authentication
- model requests and prompt caching
- thinking and signed thinking-block handling
- the iterative model/tool loop
- built-in tools and permissions
- compaction and context management
- streaming output
- session transcripts

`fastclaude` should reuse those capabilities without adopting the full Claude Agent SDK abstraction. Its job is the narrow adapter around the installed `claude` executable:

```text
complete message history
        |
        v
native temporary Claude transcript ----+
                                        |
final real user prompt -----------------+--> claude process
Python callable tools <--- control/MCP --->      |
                                                v
                                  streamed events + complete Msg trace
```

The main users are:

- `fastllm-claude-code`, which should become a thin FastLLM provider adapter
- `ipyai`, whose usual tools are a live-kernel `python(code: str)` callable and a `bash(code: str)` callable
- future applications that want the same subscription-backed runner with additional Python callables

## Non-goals

The initial version will not provide:

- a persistent conversational client
- a server-side session object used across requests
- an Anthropic API fallback
- an official MCP client or server abstraction
- external stdio, SSE, or HTTP MCP servers
- hooks, agents, permissions callbacks, session mirrors, plugins, or the Agent SDK's complete option surface
- continuation from a history whose final content is only a historical `ToolResult`
- compatibility shims for old versions of `fastllm-claude-code`

Options should be added only when a concrete caller needs them.

## Why not use the Agent SDK directly?

The Python Agent SDK is mostly a substantial wrapper around the Claude Code subprocess. The checked-out repository contains approximately:

| Area | Lines |
|---|---:|
| Production Python | 6,561 |
| Unit tests | 18,279 |
| End-to-end tests | 1,526 |
| Examples | 2,420 |
| Scripts | 952 |
| Total | 29,738 |

The production code covers a much wider public API than these projects require: dozens of options and message dataclasses, multiple transport and session-store modes, hooks, permissions, agents, skills, plugins, file checkpointing, external MCP variants, cross-platform executable discovery, detailed lifecycle events, and compatibility across Claude Code versions.

The essential contract needed here is much smaller:

1. Start `claude` with streaming JSON input/output.
2. Send the initialization control request.
3. Send one user turn.
4. Route in-process tool requests to Python callables.
5. Stream output until the terminal result.
6. Support interruption and bounded cleanup.

The initial runtime implementation should plausibly remain below about 1,000 lines, excluding tests and the transcript codec moved from `llmsurgery`. This is an expectation, not a line-count target.

## Dependency direction

The intended graph is:

```text
fastcore -> aidialog -> fastllm -> fastclaude -> llmsurgery
                                 ^
                                 |
                       fastllm-claude-code
```

`fastclaude` depends on `fastllm`, which provides:

- the canonical `aidialog.msg_parts` message model transitively
- `fastllm.anthropic.denorm_msgs` for converting `Msg` objects to Anthropic-style message dictionaries
- existing Anthropic event normalization used by the FastLLM adapter

`fastclaude` owns the low-level Claude-specific transcript format because that format is required to implement one completion. `llmsurgery` remains the higher-level package for finding, inspecting, branching, editing, compacting, and exporting sessions.

There must be one implementation of the undocumented transcript format. The codec should be moved, not copied.

## Public request contract

The working API shape is:

```python
run = astream(
    msgs,
    model='sonnet',
    system=None,
    tools=[python, bash],
    cwd=None,
)

async for event in run:
    ...

generated = run.messages
result = run.result
```

`astream` is a regular factory returning a `ClaudeRun`. `ClaudeRun` implements the async-iterator protocol and also provides:

```python
await run.interrupt()
await run.aclose()
```

A `ClaudeRun` is request-scoped. It owns exactly one temporary transcript and one subprocess, then becomes terminal. This does not create persistent conversation state.

### Inputs

- `msgs` is a sequence of `aidialog.msg_parts.Msg`.
- The sequence must end with a user message containing a real prompt block, normally `Text`. Media should be allowed when the existing Anthropic conversion supports it.
- A final message containing only `ToolResult` is rejected clearly.
- Earlier history may contain text, signed thinking, media, tool uses, and tool results.
- Tool-use names belonging to Python callables are qualified to Claude's private `mcp__fastclaude__<name>` representation when the transcript is written, then unqualified in returned data.
- The complete history is supplied on every call. Nothing from an earlier `ClaudeRun` is consulted.

### Outputs

The first implementation should favor losslessness over a large new type hierarchy:

- Async iteration yields raw decoded Claude stream-json dictionaries.
- `run.result` stores the terminal result dictionary.
- `run.messages` accumulates the generated assistant messages and tool-result user messages as canonical `Msg` objects, including signed thinking blocks.
- The FastLLM adapter converts `stream_event.event` dictionaries with its existing `norm_sse_event` machinery.

Keeping the generated tool trace matters. A later stateless request must be able to receive the tool uses and results from the previous run, not merely its final text.

The API can be narrowed after the first adapter ports show which raw events callers actually require. It should not start with a parallel set of Agent SDK dataclasses.

## Request lifecycle

For each invocation:

1. Validate the message sequence and isolate the final user prompt.
2. Convert the earlier `Msg` objects with `fastllm.anthropic.denorm_msgs`.
3. Qualify historical Python tool names with `mcp__fastclaude__`.
4. Create a fresh random session ID and write the earlier messages as a native Claude JSONL transcript under the session directory corresponding to `cwd`.
5. Start the installed `claude` executable in `cwd`, resuming that session.
6. Send the control-protocol `initialize` request and await its response.
7. Send the final user message as the one live stream-json input message.
8. Read NDJSON stdout continuously, routing control messages internally and yielding ordinary output events.
9. When Claude requests a Python tool, execute the callable, return the result, and keep the same process alive so Claude continues the loop.
10. Stop after the terminal run result and all in-flight control/tool work is finished.
11. Close stdin, reap the subprocess, and remove the exact temporary session file on success, error, cancellation, or interruption.

A fresh random session ID avoids collisions when identical histories run concurrently. Prompt caching depends on request content, not on reusing a session ID.

## Claude command and environment

The executable is the user's installed `claude`, resolved with `shutil.which` unless an explicit path is supplied.

The core command is based on the Agent SDK's current command builder:

```text
claude
  --output-format stream-json
  --verbose
  --input-format stream-json
  --include-partial-messages
  --resume=<session-id>
  --model <model>
  --system-prompt <system>
  --mcp-config <private-sdk-server-config>
  --strict-mcp-config
  --allowedTools <qualified-callable-tools>
  --tools ""
```

Important details:

- Do not use `--bare`: current Claude help says bare mode never reads OAuth or the keychain.
- Do not isolate `CLAUDE_CONFIG_DIR` by default. Testing showed that doing so also isolates the login, defeating the purpose of subscription access.
- Set `ANTHROPIC_API_KEY` to an empty value by default so an inherited API key does not silently incur API charges.
- Remove inherited `CLAUDECODE`; otherwise the child may believe it is nested inside another Claude Code process.
- Use the user's real Claude config and OAuth, but `--strict-mcp-config` prevents unrelated configured MCP servers from joining this request.
- Built-in Claude tools are disabled initially. A later explicit `native_tools` option can enable a named subset when required.
- `--resume=<id>` must use the equals form so a dash-leading value cannot become an injected option.
- Piped stdin/stdout make Claude headless, so the Agent SDK currently omits `--print`. This behavior needs an integration test against the supported CLI version range.
- Do not use `--no-session-persistence`: the invocation must resume the transcript we just wrote.

The default interaction with user/project settings should initially match `fastllm-claude-code`. Whether to suppress more Claude customizations is a later explicit policy decision; authentication must continue to use the real config.

## Native transcript codec

Move the completion-critical portion of `llmsurgery.ant` into `fastclaude.session`:

- session directory and file calculation
- canonical serialization and stable UUID helpers
- native user/assistant record construction
- parent-UUID chaining
- transcript reading and writing
- `msgs2recs`-equivalent conversion
- tool-name qualification needed by callable tools
- record/message conversion needed to accumulate a lossless returned trace

The initial runner should use a random session ID even if individual record construction remains deterministic for testability.

Keep these higher-level operations in `llmsurgery`:

- locating and resolving the user's existing sessions
- searching and displaying sessions
- active-thread and compaction analysis
- dialog conversion and export
- branching, naming, editing, and compacting sessions
- prompt-history analysis

After the move, `llmsurgery.ant` imports its transcript primitives from `fastclaude.session`. Existing exported names can be changed directly as part of the coordinated port; no compatibility layer is required unless separately requested.

## Callable tools

The public tool definition is simply an annotated Python callable with a docstring:

```python
async def search(query: str, limit: int = 10) -> str:
    "Search the local index."
    ...
```

No alias registry is needed. The callable's `__name__` is the tool name.

Schema and dispatch use `fastcore.funccall`:

```python
ns = mk_ns(tools)
schemas = [get_schema(f, pname='inputSchema') for f in tools]
result = await call_func_async(name, arguments, ns)
```

`get_schema` already derives the name, description, and JSON schema from `__name__`, `__doc__`, annotations, and defaults.

Tool return conversion should initially be small:

- strings become MCP text content
- JSON-compatible values become a readable JSON text result
- `None` becomes an empty successful result
- exceptions become an error tool result that Claude can read

Images, resources, annotations, aliases, and custom result classes are out of initial scope.

### Sync and async callables

`fastcore.funccall.call_func_async` awaits async results but calls synchronous functions inline. Running a slow synchronous tool inline would block streaming, control responses, and interruption. Therefore:

- async callables run in their own tracked task
- synchronous callables run in a worker thread
- cancelling an async callable cancels its task
- cancellation of a worker-thread callable is best-effort: the wait can be abandoned, but Python cannot forcibly stop the thread

Important tools such as `ipyai`'s Python and Bash adapters should be async and implement real cancellation themselves. A Bash adapter should terminate its process group; a live-kernel Python adapter should request a kernel interrupt.

## Private MCP-shaped bridge

Claude Code currently exposes in-process SDK tools using MCP-shaped JSON-RPC nested inside its control protocol. We need that wire contract, but not the official `mcp` package.

The CLI receives a private server entry equivalent to:

```json
{"type": "sdk", "name": "fastclaude"}
```

It then sends stdout messages shaped like:

```json
{
  "type": "control_request",
  "request_id": "...",
  "request": {
    "subtype": "mcp_message",
    "server_name": "fastclaude",
    "message": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
  }
}
```

The private dispatcher only needs the methods Claude uses for callable tools:

- `initialize`
- `notifications/initialized`
- `ping`, if observed
- `tools/list`
- `tools/call`

Notifications still require acknowledgement of the outer Claude control request even when the inner JSON-RPC notification has no response.

The dispatcher returns an outer `control_response` containing `mcp_response`. Unknown JSON-RPC methods return method-not-found; exceptions in a tool become tool errors rather than protocol errors.

This module is deliberately not a general MCP implementation.

## Streaming and tool-loop ownership

Claude, not FastLLM or `ipyai`, owns each live tool loop:

```text
assistant thinking
assistant tool_use
Python callable execution
user tool_result
assistant thinking
assistant final response
```

All of that occurs within one Claude process. This preserves Claude's normal iteration behavior, signed thinking blocks, and prompt/cache behavior.

The host executes the callable because it owns the Python object, but it does not decide whether to continue, formulate a synthetic continuation prompt, or start another completion. It returns the tool result through the control channel and Claude continues.

This differs intentionally from current `fastllm-claude-code`, which defers each new tool call to FastLLM's external tool loop.

## Interrupts and cleanup

`ClaudeRun.interrupt()` sends Claude's native control request:

```json
{
  "type": "control_request",
  "request_id": "interrupt_1",
  "request": {"subtype": "interrupt"}
}
```

The stdout reader must continue running concurrently so it can match the corresponding `control_response` and drain the terminal events.

Observed Claude Code 2.1.238 behavior during a real in-flight interruption:

- the control response acknowledged success
- the partial assistant message carried `"aborted": true`
- Claude emitted a native user record containing `[Request interrupted by user]`
- the terminal result had `is_error: true`, `subtype: "error_during_execution"`, and `terminal_reason: "aborted_streaming"`

An interruption explicitly initiated by the caller is not reported as an ordinary provider failure. The raw terminal result remains available, while adapters can represent the partial response using their normal interrupted marker.

When the consuming task is cancelled or the iterator is closed:

1. shield a short cleanup section from cancellation
2. send the native interrupt if the process is active
3. wait briefly for its acknowledgement and terminal result
4. close stdin
5. terminate the process if graceful interruption fails
6. kill and reap it if termination also times out
7. remove the exact temporary transcript

The bridge must also handle CLI-originated:

```json
{"type": "control_cancel_request", "request_id": "..."}
```

Each in-flight tool/control callback is tracked by request ID. On cancellation, cancel that task and do not write a response for a request Claude has abandoned.

## Planned files

Keep the package small and cohesive:

```text
fastclaude/
    __init__.py       public exports and version
    core.py           ClaudeRun and request lifecycle
    protocol.py       subprocess NDJSON, control routing, callable bridge, interrupts
    session.py        native Claude transcript codec moved from llmsurgery
tests/
    test_session.py
    test_protocol.py
    test_tools.py
    test_integration.py
```

Do not split additional modules until actual code size or dependency boundaries justify them.

## Migration plan

### `llmsurgery`

1. Move the low-level transcript codec to `fastclaude.session` with its tests.
2. Add `fastclaude` as an `llmsurgery` dependency.
3. Import those primitives into `llmsurgery.ant`.
4. Leave analysis, editing, dialog, and compaction behavior in `llmsurgery`.

### `fastllm-claude-code`

Replace its Agent SDK payload construction with a thin adapter:

- pass canonical `Msg` history and callable tools to `fastclaude`
- normalize streamed Anthropic events with existing FastLLM functions
- mark the callable-driven tool events as internally/server executed so FastLLM does not start a second external tool loop
- retain the complete generated `Msg` trace for the next stateless request
- remove the Agent SDK dependency and the current session/deferred-tool orchestration

### `ipyai`

Wrap existing host tools as ordinary annotated async functions. For example:

```python
def python_tool(tools):
    async def python(code: str) -> str:
        "Execute code in the user's live IPython session."
        return await tools.call_text('py', {'code': code})
    return python
```

The existing kernel-side Python implementation can remain responsible for output capture, final-expression display, and traceback formatting. The host wrapper only adapts it to the callable contract.

## Test plan

### Unit tests

- `Msg` history round-trips through native records, including signed thinking and tool blocks.
- Session paths, IDs, UUID chains, and cleanup are correct.
- Commands use argv lists, safe equals-form identifiers, and the intended environment.
- NDJSON handles chunked lines, multiple lines per chunk, malformed JSON, large messages, stderr, and non-zero exits.
- Initialization requests and responses are matched by request ID.
- Minimal JSON-RPC tool initialization, listing, calls, notifications, errors, and cancellation work.
- Callable names and schemas come from `fastcore.funccall`.
- Sync and async callable execution behave correctly.
- Tool prefixes are added only on the Claude side and removed from returned data.
- Iterator close and task cancellation cannot leak subprocesses or transcript files.
- Explicit interrupt is distinguished from provider failure.

### Integration tests

Integration tests require an installed, authenticated Claude Code and must be explicitly selected. They should cover:

- a simple subscription-backed completion
- editable multi-turn history
- signed thinking round-trip
- one Python callable call followed by Claude's final answer in the same process
- multiple tool iterations
- tool exception handling
- interruption during model generation
- interruption during an async tool
- cleanup after success, error, and cancellation
- the supported Claude Code version range

Tests must use uniquely named sessions and remove only the exact files they create.

## Source map: Claude Agent SDK contract

Paths below refer to the 2026-08-22 checkout at `~/git/claude-agent-sdk-python`; line numbers will drift.

### Process command and transport

- `src/claude_agent_sdk/_internal/transport/subprocess_cli.py:562-785` builds the Claude command.
- `.../subprocess_cli.py:566` establishes `stream-json` output plus `--verbose`.
- `.../subprocess_cli.py:637-645` uses equals-form resume/session identifiers to prevent option injection.
- `.../subprocess_cli.py:657-682` converts SDK MCP server configuration into `--mcp-config`.
- `.../subprocess_cli.py:684-691` adds partial messages and strict MCP configuration.
- `.../subprocess_cli.py:781-783` always selects stream-json input.
- `.../subprocess_cli.py:787-815` resolves/spawns the executable, removes `CLAUDECODE`, and builds the child environment.
- `.../subprocess_cli.py:942-1038` performs shielded terminate/kill/reap cleanup.
- `.../subprocess_cli.py:1043-1075` serializes stdin writes and closes input.
- `.../subprocess_cli.py:1081-1142` frames and parses NDJSON stdout and converts non-zero process exits to errors.
- `.../subprocess_cli.py:1144-1170` checks the installed Claude version.

### Control protocol and tools

- `src/claude_agent_sdk/_internal/query.py:231-283` sends and records the initialization control request.
- `.../query.py:297-346` tracks incoming control-request tasks and cancels them on `control_cancel_request`.
- `.../query.py:308-467` is the central stdout reader/router.
- `.../query.py:469-596` handles CLI-originated control requests and builds success/error responses.
- `.../query.py:548-566` unwraps the `mcp_message` subtype and returns `mcp_response`.
- `.../query.py:598-643` sends Python-originated control requests and matches responses by request ID.
- `.../query.py:645-674` routes raw inner JSON-RPC messages to the SDK MCP bridge.
- `.../query.py:684-686` implements native interruption.
- `.../query.py:819-892` explains why stdin must remain open while tools/control callbacks may still occur.
- `.../query.py:908-950` begins cancellation-shielded query cleanup.

### Official SDK MCP machinery that we intentionally replace

- `src/claude_agent_sdk/__init__.py:491-619` turns SDK tool definitions into an official `mcp.server.Server`, validates arguments, and returns `{type: "sdk", name, instance}`.
- `src/claude_agent_sdk/_internal/sdk_mcp_bridge.py:1-21` describes the nested JSON-RPC/control-channel contract.
- `.../sdk_mcp_bridge.py:343-384` routes raw JSON-RPC through the official MCP server.
- `src/claude_agent_sdk/types.py:631-646` defines the SDK MCP config shape.

`fastclaude` replaces that general machinery with the callable-only dispatcher described above.

## Source map: current downstream implementations

### `fastllm-claude-code`

`~/aai-ws/fastllm-claude-code/fastllm_claude_code/core.py` is only about 80 runtime lines:

- `23-28` defines the MCP prefix, built-in server tools, continuation prompt, and work directory.
- `36-62` converts messages, constructs callable schemas, handles a trailing tool result, creates Agent SDK options, and writes/resumes a native session.
- `47-55` is the deferred-result branch not included in the initial `fastclaude` design.
- `65-75` converts Agent SDK stream events into FastLLM deltas.

The small adapter is obscured by dependencies on the Agent SDK and `llmsurgery` session helpers. After the port it should mostly contain FastLLM normalization and provider registration.

### `llmsurgery.ant`

`~/aai-ws/llmsurgery/llmsurgery/ant.py` currently contains both low-level session transport and high-level surgery:

- `55-79` computes session directories/files.
- `125-168` constructs native message records.
- `170-192` chains and saves records.
- `209-235` converts Anthropic messages into resumable sessions.
- `456-484` converts whole dialogs to messages/sessions.
- `696-750` implements held results, tool deferral, deferred attachments, and empty-input continuation.
- `721-732` qualifies custom tool names.
- `776-794` adapts Agent SDK query events.

The completion-critical primitives move to `fastclaude`; the user-facing session analysis and editing operations remain in `llmsurgery`.

## Protocol experiments already completed

### Direct history injection

Claude stream-json input accepts only SDK user messages. Sending an outer `type: "user"` whose inner `message.role` was `assistant`, even with `shouldQuery: false`, failed with:

```text
Expected message role 'user', got 'assistant'
```

Therefore arbitrary history cannot be supplied directly through stdin. A real native session transcript is required.

### Historical tool-result continuation

Tests used the real authenticated Claude Code 2.1.238 installation and a fabricated native session.

1. With a transcript ending in `assistant/tool_use`, sending the matching `tool_result` as the live stream-json user message did not resume that tool use.
2. Repeating with the built-in Bash tool and the actual session ID caused Claude to issue a new Bash call with a new tool-use ID.
3. Writing the ordinary `tool_result` into the transcript and resuming with an empty input stream produced no model turn.

Thus normal transcript records do not recreate Claude's pending internal tool state or trigger an assistant continuation.

### Interrupt

A live native interrupt was acknowledged and produced the aborted partial message plus `terminal_reason: "aborted_streaming"` described above. This validates the request-scoped interrupt design.

## Possible future option: deferred historical tool results

The initial contract deliberately rejects a request ending only in `ToolResult`. This is normally unnecessary when Claude owns the live tool loop: one `ClaudeRun` includes the tool call, callable result, and final assistant continuation.

A concrete reason to add support would be history editing at a mid-agent boundary. For example, a caller could delete only the final assistant answer while retaining:

```text
user prompt
assistant thinking + tool use
user tool result
```

and ask `fastclaude` to regenerate the missing assistant continuation. Another possible caller might deliberately run an external tool loop and submit its result as the final request message.

Claude Code cannot currently continue that history directly. The working approach in `llmsurgery.ant` is:

1. write the native history only through the preceding `tool_use`
2. append a `hook_deferred_tool` attachment for that tool use
3. queue the already-known result by qualified tool name and arguments
4. resume with an empty input stream
5. allow Claude to re-invoke the pending tool
6. return the queued result without executing the tool again
7. let Claude produce the continuation

Relevant current code:

- `llmsurgery/llmsurgery/ant.py:696-718`: `hold_result` and `defer_tools`
- `.../ant.py:735-750`: `mk_deferred` and `no_prompt`
- `fastllm_claude_code/core.py:47-55`: detection and construction of this continuation

This is valid but depends on an undocumented `hook_deferred_tool` transcript attachment and PreToolUse hook behavior. It should be added only after a real `ipyai` or FastLLM workflow demonstrates that regeneration from exactly this boundary is required.
