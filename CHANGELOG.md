# Release notes

<!-- do not remove -->

## 0.0.4

### New Features

- Continue a tool round by deferral rather than a paused process ([#6](https://github.com/AnswerDotAI/fastclaude/pull/6)), thanks to [@jph00](https://github.com/jph00)


## 0.0.3

### New Features

- Replace deferred-tool hack with paused MCP tool calls: runs now pause at a complete tool batch and resume in the same Claude process ([#4](https://github.com/AnswerDotAI/fastclaude/issues/4))


## 0.0.2

### New Features

- Return control of the tool loop to the caller: advertise tool schemas, defer tool calls via PreToolUse hook, and continue from tool results ([#3](https://github.com/AnswerDotAI/fastclaude/issues/3))


## 0.0.1

### New Features

- Preserve str subclass types across tool results using `wrap_typed`/`unwrap_typed` from fastllm.types ([#2](https://github.com/AnswerDotAI/fastclaude/issues/2))
- Add session transcript codec, stream-json protocol layer, and astream/ClaudeRun stateless completions via Claude Code CLI ([#1](https://github.com/AnswerDotAI/fastclaude/issues/1))
