# GitHub Copilot CLI — Feature Set & Command Reference

> Source: [GitHub Copilot CLI Command Reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)

---

## Command-Line Commands

| Command | Description |
|---------|-------------|
| `copilot` | Launch the interactive user interface. |
| `copilot help [topic]` | Display help information. Topics: config, commands, environment, logging, permissions. |
| `copilot init` | Initialize Copilot custom instructions for this repository. |
| `copilot update` | Download and install the latest version. |
| `copilot version` | Display version information and check for updates. |
| `copilot login` | Authenticate with Copilot via OAuth device flow. Accepts `--host HOST` to specify GitHub host URL (default: `https://github.com`). |
| `copilot logout` | Sign out of GitHub and remove stored credentials. |
| `copilot plugin` | Manage plugins and plugin marketplaces. |

---

## Interactive Interface Shortcuts

### Global Shortcuts

| Shortcut | Description |
|----------|-------------|
| `@ FILENAME` | Include file contents in the context. |
| `Ctrl+X` then `/` | Run a slash command after you've started typing a prompt. |
| `Esc` | Cancel the current operation. |
| `! COMMAND` | Execute a command in your local shell, bypassing Copilot. |
| `Ctrl+C` | Cancel operation / clear input. Press twice to exit. |
| `Ctrl+D` | Shutdown. |
| `Ctrl+L` | Clear the screen. |
| `Shift+Tab` | Cycle between standard, plan, and autopilot mode. |

### Timeline Shortcuts

| Shortcut | Description |
|----------|-------------|
| `Ctrl+O` | Expand recent items in Copilot's response timeline (when prompt input is empty). |
| `Ctrl+E` | Expand all items in Copilot's response timeline (when prompt input is empty). |
| `Ctrl+T` | Expand/collapse display of reasoning in responses. |

### Navigation Shortcuts

| Shortcut | Description |
|----------|-------------|
| `Ctrl+A` | Move to beginning of the line. |
| `Ctrl+B` | Move to the previous character. |
| `Ctrl+E` | Move to end of the line. |
| `Ctrl+F` | Move to the next character. |
| `Ctrl+G` | Edit the prompt in an external editor. |
| `Ctrl+H` | Delete the previous character. |
| `Ctrl+K` | Delete from cursor to end of line. If at end, delete the line break. |
| `Ctrl+U` | Delete from cursor to beginning of the line. |
| `Ctrl+W` | Delete the previous word. |
| `Home` | Move to the start of the current line. |
| `End` | Move to the end of the current line. |
| `Ctrl+Home` | Move to the start of the text. |
| `Ctrl+End` | Move to the end of the text. |
| `Meta+←/→` | Move the cursor by a word. |
| `↑/↓` | Navigate the command history. |

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/add-dir PATH` | Add a directory to the allowed list for file access. |
| `/agent` | Browse and select from available agents. |
| `/allow-all`, `/yolo` | Enable all permissions (tools, paths, and URLs). |
| `/clear`, `/new` | Clear the conversation history. |
| `/compact` | Summarize the conversation history to reduce context window usage. |
| `/context` | Show the context window token usage and visualization. |
| `/cwd`, `/cd [PATH]` | Change the working directory or display the current directory. |
| `/delegate [PROMPT]` | Delegate changes to a remote repository with an AI-generated pull request. |
| `/diff` | Review the changes made in the current directory. |
| `/exit`, `/quit` | Exit the CLI. |
| `/experimental [on\|off]` | Toggle or turn on/off experimental features. |
| `/feedback` | Provide feedback about the CLI. |
| `/fleet [PROMPT]` | Enable parallel subagent execution of parts of a task. |
| `/help` | Show the help for interactive commands. |
| `/ide` | Connect to an IDE workspace. |
| `/init` | Initialize Copilot custom instructions and agentic features for this repository. |
| `/list-dirs` | Display all directories for which file access has been allowed. |
| `/login` | Log in to Copilot. |
| `/logout` | Log out of Copilot. |
| `/lsp [show\|test\|reload\|help] [SERVER-NAME]` | Manage the language server configuration. |
| `/mcp [show\|add\|edit\|delete\|disable\|enable] [SERVER-NAME]` | Manage the MCP server configuration. |
| `/model`, `/models [MODEL]` | Select the AI model you want to use. |
| `/plan [PROMPT]` | Create an implementation plan before coding. |
| `/plugin [marketplace\|install\|uninstall\|update\|list] [ARGS...]` | Manage plugins and plugin marketplaces. |
| `/rename NAME` | Rename the current session (alias for `/session rename`). |
| `/reset-allowed-tools` | Reset the list of allowed tools. |
| `/resume [SESSION-ID]` | Switch to a different session (optionally specify a session ID). |
| `/review [PROMPT]` | Run the code review agent to analyze changes. |
| `/session [checkpoints [n]\|files\|plan\|rename NAME]` | Show session information and workspace summary. |
| `/share [file\|gist] [PATH]` | Share the session to a Markdown file or GitHub gist. |
| `/skills [list\|info\|add\|remove\|reload] [ARGS...]` | Manage skills for enhanced capabilities. |
| `/terminal-setup` | Configure the terminal for multiline input support (`Shift+Enter` and `Ctrl+Enter`). |
| `/theme [show\|set\|list] [auto\|THEME-ID]` | View or configure the terminal theme. |
| `/usage` | Display session usage metrics and statistics. |
| `/user [show\|list\|switch]` | Manage the current GitHub user. |

---

## Command-Line Options

| Option | Description |
|--------|-------------|
| `--acp` | Start the Agent Client Protocol server. |
| `--add-dir=PATH` | Add a directory to the allowed list for file access (can be used multiple times). |
| `--add-github-mcp-tool=TOOL` | Add a tool to enable for the GitHub MCP server (can be used multiple times). Use `*` for all tools. |
| `--add-github-mcp-toolset=TOOLSET` | Add a toolset to enable for the GitHub MCP server (can be used multiple times). Use `all` for all toolsets. |
| `--additional-mcp-config=JSON` | Add an MCP server for this session only. Accepts JSON string or file path (prefix with `@`). |
| `--agent=AGENT` | Specify a custom agent to use. |
| `--allow-all` | Enable all permissions (equivalent to `--allow-all-tools --allow-all-paths --allow-all-urls`). |
| `--allow-all-paths` | Disable file path verification and allow access to any path. |
| `--allow-all-tools` | Allow all tools to run automatically without confirmation. Required for programmatic use (env: `COPILOT_ALLOW_ALL`). |
| `--allow-all-urls` | Allow access to all URLs without confirmation. |
| `--allow-tool=TOOL ...` | Tools the CLI has permission to use. For multiple tools, use a quoted, comma-separated list. |
| `--allow-url=URL ...` | Allow access to specific URLs or domains. For multiple URLs, use a quoted, comma-separated list. |
| `--alt-screen=VALUE` | Use the terminal alternate screen buffer (`on` or `off`). |
| `--autopilot` | Enable autopilot continuation in prompt mode. |
| `--available-tools=TOOL ...` | Only these tools will be available to the model. |
| `--banner` | Show the startup banner. |
| `--bash-env` | Enable BASH_ENV support for bash shells. |
| `--config-dir=PATH` | Set the configuration directory (default: `~/.copilot`). |
| `--continue` | Resume the most recent session. |
| `--deny-tool=TOOL ...` | Tools the CLI does not have permission to use. |
| `--deny-url=URL ...` | Deny access to specific URLs or domains (takes precedence over `--allow-url`). |
| `--disable-builtin-mcps` | Disable all built-in MCP servers. |
| `--disable-mcp-server=SERVER-NAME` | Disable a specific MCP server (can be used multiple times). |
| `--disable-parallel-tools-execution` | Disable parallel execution of tools (tools execute sequentially). |
| `--disallow-temp-dir` | Prevent automatic access to the system temporary directory. |
| `--enable-all-github-mcp-tools` | Enable all GitHub MCP server tools. Overrides `--add-github-mcp-toolset` and `--add-github-mcp-tool`. |
| `--excluded-tools=TOOL ...` | These tools will not be available to the model. |
| `--experimental` | Enable experimental features (use `--no-experimental` to disable). |
| `-h`, `--help` | Display help. |
| `-i PROMPT`, `--interactive=PROMPT` | Start an interactive session and automatically execute this prompt. |
| `--log-dir=DIRECTORY` | Set the log file directory (default: `~/.copilot/logs/`). |
| `--log-level=LEVEL` | Set the log level (choices: none, error, warning, info, debug, all, default). |
| `--max-autopilot-continues=COUNT` | Maximum number of continuation messages in autopilot mode (default: unlimited). |
| `--model=MODEL` | Set the AI model you want to use. |
| `--no-alt-screen` | Disable the terminal alternate screen buffer. |
| `--no-ask-user` | Disable the `ask_user` tool (agent works autonomously without asking questions). |
| `--no-auto-update` | Disable downloading CLI updates automatically. |
| `--no-bash-env` | Disable BASH_ENV support for bash shells. |
| `--no-color` | Disable all color output. |
| `--no-custom-instructions` | Disable loading of custom instructions from AGENTS.md and related files. |
| `--no-experimental` | Disable experimental features. |
| `--output-format=FORMAT` | `text` (default) or `json` (outputs JSONL: one JSON object per line). |
| `-p PROMPT`, `--prompt=PROMPT` | Execute a prompt programmatically (exits after completion). |
| `--plain-diff` | Disable rich diff rendering. |
| `--resume=SESSION-ID` | Resume a previous interactive session (optionally specify a session ID). |
| `-s`, `--silent` | Output only the agent response (without usage statistics), useful for scripting with `-p`. |
| `--screen-reader` | Enable screen reader optimizations. |
| `--secret-env-vars=VAR ...` | Environment variable whose value you want redacted in output. `GITHUB_TOKEN` and `COPILOT_GITHUB_TOKEN` are redacted by default. |
| `--share=PATH` | Share a session to a Markdown file after completion (default: `./copilot-session-<ID>.md`). |
| `--share-gist` | Share a session to a secret GitHub gist after completion. |
| `--stream=MODE` | Enable or disable streaming mode (`on` or `off`). |
| `-v`, `--version` | Show version information. |
| `--yolo` | Enable all permissions (equivalent to `--allow-all`). |

---

## Tool Permission Patterns

The `--allow-tool` and `--deny-tool` options accept permission patterns in the format `Kind(argument)`. The argument is optional—omitting it matches all tools of that kind.

| Pattern | Matches | Examples |
|---------|---------|----------|
| `shell` | Shell command execution | `shell(git push)`, `shell(git:*)`, `shell` |
| `write` | File creation or modification | `write`, `write(src/*.ts)` |
| `read` | File or directory reads | `read`, `read(.env)` |
| `SERVER-NAME` | MCP server tool invocation | `My MCP(create_issue)`, `MyMCP` |
| `url` | URL access via web-fetch or shell | `url(github.com)`, `url(https://*.api.com)` |
| `memory` | Storing facts to agent memory | `memory` |

For `shell` rules, the `:*` suffix matches the command stem followed by a space, preventing partial matches. For example, `shell(git:*)` matches `git push` and `git pull` but not `gitea`.

Deny rules always take precedence over allow rules, even when `--allow-all` is set.

```bash
# Allow all git commands except git push
copilot --allow-tool='shell(git:*)' --deny-tool='shell(git push)'

# Allow a specific MCP server tool
copilot --allow-tool='MyMCP(create_issue)'

# Allow all tools from a server
copilot --allow-tool='MyMCP'
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `COPILOT_MODEL` | Set the AI model. |
| `COPILOT_ALLOW_ALL` | Set to `true` to allow all permissions automatically (equivalent to `--allow-all`). |
| `COPILOT_AUTO_UPDATE` | Set to `false` to disable automatic updates. |
| `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` | Comma-separated list of additional directories for custom instructions. |
| `COPILOT_SKILLS_DIRS` | Comma-separated list of additional directories for skills. |
| `COPILOT_EDITOR` | Editor command for interactive editing (checked after `$VISUAL` and `$EDITOR`). Defaults to `vi` if none are set. |
| `COPILOT_GITHUB_TOKEN` | Authentication token. Takes precedence over `GH_TOKEN` and `GITHUB_TOKEN`. |
| `COPILOT_HOME` | Override the configuration and state directory. Default: `$HOME/.copilot`. |
| `GH_TOKEN` | Authentication token. Takes precedence over `GITHUB_TOKEN`. |
| `GITHUB_TOKEN` | Authentication token. |
| `USE_BUILTIN_RIPGREP` | Set to `false` to use the system ripgrep instead of the bundled version. |
| `PLAIN_DIFF` | Set to `true` to disable rich diff rendering. |
| `COLORFGBG` | Fallback for dark/light terminal background detection. |
| `COPILOT_CLI_ENABLED_FEATURE_FLAGS` | Comma-separated list of feature flags to enable. |

---

## Configuration File Settings

Settings cascade from user → repository → local, with more specific scopes overriding general ones. Command-line flags and environment variables always take the highest precedence.

| Scope | Location | Purpose |
|-------|----------|---------|
| User | `~/.copilot/config.json` | Global defaults for all repositories. Use `COPILOT_HOME` env var for alternative path. |
| Repository | `.github/copilot/settings.json` | Shared repository configuration (committed). |
| Local | `.github/copilot/settings.local.json` | Personal overrides (add to `.gitignore`). |

### User Settings (`~/.copilot/config.json`)

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `allowed_urls` | string[] | `[]` | URLs or domains allowed without prompting. |
| `alt_screen` | boolean | `false` | Use the terminal alternate screen buffer. |
| `auto_update` | boolean | `true` | Automatically download CLI updates. |
| `banner` | `"always"` \| `"once"` \| `"never"` | `"once"` | Animated banner display frequency. |
| `bash_env` | boolean | `false` | Enable BASH_ENV support for bash shells. |
| `beep` | boolean | `true` | Play an audible beep when attention is required. |
| `compact_paste` | boolean | `true` | Collapse large pastes into compact tokens. |
| `custom_agents.default_local_only` | boolean | `false` | Only use local custom agents. |
| `denied_urls` | string[] | `[]` | URLs or domains blocked (takes precedence over `allowed_urls`). |
| `experimental` | boolean | `false` | Enable experimental features. |
| `include_coauthor` | boolean | `true` | Add a Co-authored-by trailer to git commits made by the agent. |
| `companyAnnouncements` | string[] | `[]` | Custom messages shown randomly on startup. |
| `log_level` | `"none"` \| `"error"` \| `"warning"` \| `"info"` \| `"debug"` \| `"all"` \| `"default"` | `"default"` | Logging verbosity. |
| `model` | string | varies | AI model to use (see the `/model` command). |
| `powershell_flags` | string[] | `["-NoProfile", "-NoLogo"]` | Flags passed to PowerShell (pwsh) on startup. Windows only. |
| `reasoning_effort` | `"low"` \| `"medium"` \| `"high"` \| `"xhigh"` | `"medium"` | Reasoning effort level for extended thinking. |
| `render_markdown` | boolean | `true` | Render Markdown in terminal output. |
| `screen_reader` | boolean | `false` | Enable screen reader optimizations. |
| `stream` | boolean | `true` | Enable streaming responses. |
| `store_token_plaintext` | boolean | `false` | Store authentication tokens in plaintext when no system keychain is available. |
| `streamer_mode` | boolean | `false` | Hide preview model names and quota details (useful when recording). |
| `theme` | `"auto"` \| `"dark"` \| `"light"` | `"auto"` | Terminal color theme. |
| `trusted_folders` | string[] | `[]` | Folders with pre-granted file access. |
| `update_terminal_title` | boolean | `true` | Show the current intent in the terminal title. |

### Repository Settings (`.github/copilot/settings.json`)

| Setting | Type | Merge Behavior | Description |
|---------|------|----------------|-------------|
| `companyAnnouncements` | string[] | Replaced—repository takes precedence | Messages shown randomly on startup. |
| `enabledPlugins` | Record<string, boolean> | Merged—repository overrides user for same key | Declarative plugin auto-install. |
| `extraKnownMarketplaces` | Record<string, {...}> | Merged—repository overrides user for same key | Plugin marketplaces available in this repository. |
| `marketplaces` | Record<string, {...}> | Merged—repository overrides user for same key | Plugin marketplaces (deprecated—use `extraKnownMarketplaces`). |

### Local Settings (`.github/copilot/settings.local.json`)

Personal overrides that should not be committed. Add this file to `.gitignore`. Uses the same schema as the repository configuration file and takes precedence over it.

---

## Hooks Reference

Hooks are external commands that execute at specific lifecycle points during a session, enabling custom automation, security controls, and integrations. Hook configuration files are loaded automatically from `.github/hooks/*.json` in your repository.

### Hook Events

| Event | Description | Can Control? |
|-------|-------------|--------------|
| `sessionStart` | A new or resumed session begins. | No |
| `sessionEnd` | The session terminates. | No |
| `userPromptSubmitted` | The user submits a prompt. | No |
| `preToolUse` | Before each tool executes. | Yes — can allow, deny, or modify. |
| `postToolUse` | After each tool completes. | No |
| `agentStop` | The main agent finishes a turn. | Yes — can block and force continuation. |
| `subagentStop` | A subagent completes. | Yes — can block and force continuation. |
| `errorOccurred` | An error occurs during execution. | No |

### Hook Configuration Format

Hook configuration files use JSON format with version `1`.

#### Command Hooks

Command hooks run shell scripts and are supported on all hook types.

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "bash": "your-bash-command",
        "powershell": "your-powershell-command",
        "cwd": "optional/working/directory",
        "env": { "VAR": "value" },
        "timeoutSec": 30
      }
    ]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"command"` | Yes | Must be `"command"`. |
| `bash` | string | One of bash/powershell | Shell command for Unix. |
| `powershell` | string | One of bash/powershell | Shell command for Windows. |
| `cwd` | string | No | Working directory (relative to repo root or absolute). |
| `env` | object | No | Environment variables (supports variable expansion). |
| `timeoutSec` | number | No | Timeout in seconds. Default: 30. |

#### Prompt Hooks

Prompt hooks auto-submit text as if the user typed it. Only supported on `sessionStart` and run before any initial prompt passed via `--prompt`.

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "type": "prompt",
        "prompt": "Your prompt text or /slash-command"
      }
    ]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"prompt"` | Yes | Must be `"prompt"`. |
| `prompt` | string | Yes | Text to submit—can be a natural language message or a slash command. |

### preToolUse Decision Control

The `preToolUse` hook can control tool execution by writing a JSON object to stdout.

| Field | Values | Description |
|-------|--------|-------------|
| `permissionDecision` | `"allow"`, `"deny"`, `"ask"` | Whether the tool executes. Empty output uses default behavior. |
| `permissionDecisionReason` | string | Reason shown to the agent. Required when decision is `"deny"`. |
| `modifiedArgs` | object | Substitute tool arguments to use instead of the originals. |

### agentStop / subagentStop Decision Control

| Field | Values | Description |
|-------|--------|-------------|
| `decision` | `"block"`, `"allow"` | `"block"` forces another agent turn using reason as the prompt. |
| `reason` | string | Prompt for the next turn when decision is `"block"`. |

### Tool Names for Hook Matching

| Tool Name | Description |
|-----------|-------------|
| `bash` | Execute shell commands (Unix). |
| `powershell` | Execute shell commands (Windows). |
| `view` | Read file contents. |
| `edit` | Modify file contents. |
| `create` | Create new files. |
| `glob` | Find files by pattern. |
| `grep` | Search file contents. |
| `web_fetch` | Fetch web pages. |
| `task` | Run subagent tasks. |

If multiple hooks of the same type are configured, they execute in order. For `preToolUse`, if any hook returns `"deny"`, the tool is blocked. Hook failures (non-zero exit codes or timeouts) are logged and skipped—they never block agent execution.

---

## MCP Server Configuration

MCP servers provide additional tools to the CLI agent. Configure persistent servers in `~/.copilot/mcp-config.json`. Use `--additional-mcp-config` to add servers for a single session.

### Transport Types

| Type | Description | Key Fields |
|------|-------------|------------|
| `local` / `stdio` | Local process communicating via stdin/stdout. | `command`, `args` |
| `http` | Remote server using streamable HTTP transport. | `url` |
| `sse` | Remote server using Server-Sent Events transport. | `url` |

### Local Server Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `command` | Yes | Command to start the server. |
| `args` | Yes | Command arguments (array). |
| `tools` | Yes | Tools to enable: `["*"]` for all, or a list of specific tool names. |
| `env` | No | Environment variables. Supports `$VAR`, `${VAR}`, and `${VAR:-default}` expansion. |
| `cwd` | No | Working directory for the server. |
| `timeout` | No | Tool call timeout in milliseconds. |
| `type` | No | `"local"` or `"stdio"`. Default: `"local"`. |

### Remote Server Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `"http"` or `"sse"`. |
| `url` | Yes | Server URL. |
| `tools` | Yes | Tools to enable. |
| `headers` | No | HTTP headers. Supports variable expansion. |
| `oauthClientId` | No | Static OAuth client ID (skips dynamic registration). |
| `oauthPublicClient` | No | Whether the OAuth client is public. Default: `true`. |
| `timeout` | No | Tool call timeout in milliseconds. |

### Filter Mapping

Control how MCP tool output is processed using the `filterMapping` field.

| Value | Description |
|-------|-------------|
| `none` | No filtering. |
| `markdown` | Format output as Markdown. |
| `hidden_characters` | Remove hidden or control characters. Default. |

### Built-in MCP Servers

| Server | Description |
|--------|-------------|
| `github-mcp-server` | GitHub API integration: issues, pull requests, commits, code search, and GitHub Actions. |
| `playwright` | Browser automation: navigate, click, type, screenshot, and form handling. |
| `fetch` | HTTP requests via the fetch tool. |
| `time` | Time utilities: `get_current_time` and `convert_time`. |

Use `--disable-builtin-mcps` to disable all built-in servers, or `--disable-mcp-server SERVER-NAME` to disable a specific one.

### MCP Server Trust Levels

| Source | Trust Level | Review Recommended |
|--------|-------------|-------------------|
| Built-in | High | No |
| Repository (`.github/mcp.json`) | Medium | Recommended |
| Workspace (`.mcp.json`, `.vscode/mcp.json`) | Medium | Recommended |
| Dev Container (`.devcontainer/devcontainer.json`) | Medium | Recommended |
| User config (`~/.copilot/mcp-config.json`) | User-defined | User responsibility |
| Remote servers | Low | Always |

All MCP tool invocations require explicit permission, even for read-only operations on external services.

---

## Skills Reference

Skills are Markdown files that extend what the CLI can do. Each skill lives in its own directory containing a `SKILL.md` file. When invoked (via `/SKILL-NAME` or automatically by the agent), the skill's content is injected into the conversation.

### Skill Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier. Letters, numbers, and hyphens only. Max 64 characters. |
| `description` | string | Yes | What the skill does and when to use it. Max 1024 characters. |
| `allowed-tools` | string or string[] | No | Comma-separated list or YAML array of tools that are automatically allowed when the skill is active. Use `"*"` for all tools. |
| `user-invocable` | boolean | No | Whether users can invoke the skill with `/SKILL-NAME`. Default: `true`. |
| `disable-model-invocation` | boolean | No | Prevent the agent from automatically invoking this skill. Default: `false`. |

### Skill Locations

Skills are loaded from these locations in priority order (first found wins for duplicate names).

| Location | Scope | Description |
|----------|-------|-------------|
| `.github/skills/` | Project | Project-specific skills. |
| `.agents/skills/` | Project | Alternative project location. |
| `.claude/skills/` | Project | Claude-compatible location. |
| Parent `.github/skills/` | Inherited | Monorepo parent directory support. |
| `~/.copilot/skills/` | Personal | Personal skills for all projects. |
| `~/.claude/skills/` | Personal | Claude-compatible personal location. |
| Plugin directories | Plugin | Skills from installed plugins. |
| `COPILOT_SKILLS_DIRS` | Custom | Additional directories (comma-separated). |

### Commands (Alternative Skill Format)

Commands are an alternative to skills stored as individual `.md` files in `.claude/commands/`. The command name is derived from the filename. Command files use a simplified format (no `name` field required) and support `description`, `allowed-tools`, and `disable-model-invocation`. Commands have lower priority than skills with the same name.

---

## Custom Agents Reference

Custom agents are specialized AI agents defined in Markdown files. The filename (minus extension) becomes the agent ID. Use `.agent.md` or `.md` as the file extension.

### Built-in Agents

| Agent | Model | Description |
|-------|-------|-------------|
| `code-review` | claude-sonnet-4.5 | High signal-to-noise code review. Analyzes diffs for bugs, security issues, and logic errors. |
| `explore` | claude-haiku-4.5 | Fast codebase exploration. Searches files, reads code, and answers questions. Returns focused answers under 300 words. Safe to run in parallel. |
| `general-purpose` | claude-sonnet-4.5 | Full-capability agent for complex multi-step tasks. Runs in a separate context window. |
| `research` | claude-sonnet-4.6 | Deep research agent. Generates a report based on information in your codebase, relevant repositories, and on the web. |
| `task` | claude-haiku-4.5 | Command execution (tests, builds, lints). Returns brief summary on success, full output on failure. |

### Custom Agent Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | Yes | Description shown in the agent list and task tool. |
| `infer` | boolean | No | Allow auto-delegation by the main agent. Default: `true`. |
| `mcp-servers` | object | No | MCP servers to connect. Uses the same schema as `~/.copilot/mcp-config.json`. |
| `model` | string | No | AI model for this agent. When unset, inherits the outer agent's model. |
| `name` | string | No | Display name. Defaults to the filename. |
| `tools` | string[] | No | Tools available to the agent. Default: `["*"]` (all tools). |

### Custom Agent Locations

| Scope | Paths |
|-------|-------|
| Project | `.github/agents/` or `.claude/agents/` |
| User | `~/.copilot/agents/` or `~/.claude/agents/` |
| Plugin | `<plugin>/agents/` |

Project-level agents take precedence over user-level agents. Plugin agents have the lowest priority.

---

## Permission Approval Responses

When the CLI prompts for permission to execute an operation, you can respond with:

| Key | Action |
|-----|--------|
| `y` | Allow this specific request once. |
| `n` | Deny this specific request once. |
| `!` | Allow all similar requests for the rest of the session. |
| `#` | Deny all similar requests for the rest of the session. |
| `?` | Show detailed information about the request. |

Session approvals reset when you run `/clear` or start a new session.

### Feature Flags

| Feature | Status | Description |
|---------|--------|-------------|
| `AUTOPILOT_MODE` | experimental | Autonomous operation mode. |
| `BACKGROUND_AGENTS` | staff | Run agents in the background. |
| `QUEUED_COMMANDS` | staff | Queue commands while the agent is running. |
| `LSP_TOOLS` | on | Language Server Protocol tools. |
| `PLAN_COMMAND` | on | Interactive planning mode. |
| `AGENTIC_MEMORY` | on | Persistent memory across sessions. |
| `CUSTOM_AGENTS` | on | Custom agent definitions. |

---

## OpenTelemetry Monitoring

Copilot CLI can export traces and metrics via [OpenTelemetry](https://opentelemetry.io/) (OTel), giving visibility into agent interactions, LLM calls, tool executions, and token usage. All signal names and attributes follow the [OTel GenAI Semantic Conventions](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/gen-ai/).

OTel is off by default with zero overhead. It activates when any of the following conditions are met:
- `COPILOT_OTEL_ENABLED=true`
- `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- `COPILOT_OTEL_FILE_EXPORTER_PATH` is set

### OTel Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COPILOT_OTEL_ENABLED` | `false` | Explicitly enable OTel. Not required if `OTEL_EXPORTER_OTLP_ENDPOINT` is set. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP endpoint URL. Setting this automatically enables OTel. |
| `COPILOT_OTEL_EXPORTER_TYPE` | `otlp-http` | Exporter type: `otlp-http` or `file`. |
| `OTEL_SERVICE_NAME` | `github-copilot` | Service name in resource attributes. |
| `OTEL_RESOURCE_ATTRIBUTES` | — | Extra resource attributes as comma-separated key=value pairs. |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `false` | Capture full prompt and response content. |
| `OTEL_LOG_LEVEL` | — | OTel diagnostic log level: NONE, ERROR, WARN, INFO, DEBUG, VERBOSE, ALL. |
| `COPILOT_OTEL_FILE_EXPORTER_PATH` | — | Write all signals to this file as JSON-lines. Setting this automatically enables OTel. |
| `COPILOT_OTEL_SOURCE_NAME` | `github.copilot` | Instrumentation scope name for tracer and meter. |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Auth headers for the OTLP exporter (e.g., `Authorization=Bearer token`). |

### Traces

The runtime emits a hierarchical span tree for each agent interaction. Each tree contains an `invoke_agent` root span, with `chat` and `execute_tool` child spans.

#### `invoke_agent` Span Attributes

Wraps the entire agent invocation. Span kind: `CLIENT`.

| Attribute | Description |
|-----------|-------------|
| `gen_ai.operation.name` | `invoke_agent` |
| `gen_ai.provider.name` | Provider (e.g., github, anthropic) |
| `gen_ai.agent.id` | Session identifier |
| `gen_ai.agent.name` | Agent name (subagents only) |
| `gen_ai.agent.description` | Agent description (subagents only) |
| `gen_ai.agent.version` | Runtime version |
| `gen_ai.conversation.id` | Session identifier |
| `gen_ai.request.model` | Requested model |
| `gen_ai.response.model` | Resolved model |
| `gen_ai.response.id` | Last response ID |
| `gen_ai.response.finish_reasons` | `["stop"]` or `["error"]` |
| `gen_ai.usage.input_tokens` | Total input tokens (all turns) |
| `gen_ai.usage.output_tokens` | Total output tokens (all turns) |
| `gen_ai.usage.cache_read.input_tokens` | Cached input tokens read |
| `gen_ai.usage.cache_creation.input_tokens` | Cached input tokens created |
| `github.copilot.turn_count` | Number of LLM round-trips |
| `github.copilot.cost` | Monetary cost |
| `github.copilot.aiu` | AI units consumed |
| `server.address` | Server hostname |
| `server.port` | Server port |
| `error.type` | Error class name (on error) |

#### `chat` Span Attributes

One span per LLM request. Span kind: `CLIENT`.

| Attribute | Description |
|-----------|-------------|
| `gen_ai.operation.name` | `chat` |
| `gen_ai.provider.name` | Provider name |
| `gen_ai.request.model` | Requested model |
| `gen_ai.conversation.id` | Session identifier |
| `gen_ai.response.id` | Response ID |
| `gen_ai.response.model` | Resolved model |
| `gen_ai.response.finish_reasons` | Stop reasons |
| `gen_ai.usage.input_tokens` | Input tokens this turn |
| `gen_ai.usage.output_tokens` | Output tokens this turn |
| `gen_ai.usage.cache_read.input_tokens` | Cached tokens read |
| `gen_ai.usage.cache_creation.input_tokens` | Cached tokens created |
| `github.copilot.cost` | Turn cost |
| `github.copilot.aiu` | AI units consumed this turn |
| `github.copilot.server_duration` | Server-side duration |
| `github.copilot.initiator` | Request initiator |
| `github.copilot.turn_id` | Turn identifier |
| `github.copilot.interaction_id` | Interaction identifier |
| `server.address` | Server hostname |
| `server.port` | Server port |
| `error.type` | Error class name (on error) |

#### `execute_tool` Span Attributes

One span per tool call. Span kind: `INTERNAL`.

| Attribute | Description |
|-----------|-------------|
| `gen_ai.operation.name` | `execute_tool` |
| `gen_ai.provider.name` | Provider name (when available) |
| `gen_ai.tool.name` | Tool name (e.g., `readFile`) |
| `gen_ai.tool.type` | `function` |
| `gen_ai.tool.call.id` | Tool call identifier |
| `gen_ai.tool.description` | Tool description |
| `error.type` | Error class name (on error) |

### Metrics

#### GenAI Convention Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.operation.duration` | Histogram | s | LLM API call and agent invocation duration |
| `gen_ai.client.token.usage` | Histogram | tokens | Token counts by type (input/output) |
| `gen_ai.client.operation.time_to_first_chunk` | Histogram | s | Time to receive first streaming chunk |
| `gen_ai.client.operation.time_per_output_chunk` | Histogram | s | Inter-chunk latency after first chunk |

#### Vendor-Specific Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `github.copilot.tool.call.count` | Counter | calls | Tool invocations by `gen_ai.tool.name` and success |
| `github.copilot.tool.call.duration` | Histogram | s | Tool execution latency by `gen_ai.tool.name` |
| `github.copilot.agent.turn.count` | Histogram | turns | LLM round-trips per agent invocation |

### Span Events

| Event | Description | Attributes |
|-------|-------------|------------|
| `github.copilot.session.truncation` | Conversation history was truncated | `token_limit`, `pre_tokens`, `post_tokens`, `tokens_removed`, `messages_removed` |
| `github.copilot.session.compaction_start` | History compaction began | None |
| `github.copilot.session.compaction_complete` | History compaction completed | `success`, `pre_tokens`, `post_tokens`, `tokens_removed`, `messages_removed` |
| `github.copilot.skill.invoked` | A skill was invoked | `skill.name`, `skill.path`, `skill.plugin_name`, `skill.plugin_version` |
| `github.copilot.session.shutdown` | Session is shutting down | `shutdown_type`, `total_premium_requests`, `lines_added`, `lines_removed`, `files_modified_count` |
| `github.copilot.session.abort` | User cancelled the current operation | `abort_reason` |
| `exception` | Session error | `error_type`, `error_status_code`, `error_provider_call_id` |

### Resource Attributes

All signals carry these resource attributes.

| Attribute | Value |
|-----------|-------|
| `service.name` | `github-copilot` (configurable via `OTEL_SERVICE_NAME`) |
| `service.version` | Runtime version |

### Content Capture

By default, no prompt content, responses, or tool arguments are captured—only metadata. To capture full content, set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`.

> **Warning:** Content capture may include sensitive information such as code, file contents, and user prompts. Only enable this in trusted environments.

When content capture is enabled, the following attributes are populated:

| Attribute | Description |
|-----------|-------------|
| `gen_ai.input.messages` | Full prompt messages (JSON) |
| `gen_ai.output.messages` | Full response messages (JSON) |
| `gen_ai.system_instructions` | System prompt content (JSON) |
| `gen_ai.tool.definitions` | Tool schemas (JSON) |
| `gen_ai.tool.call.arguments` | Tool input arguments |
| `gen_ai.tool.call.result` | Tool output |

---

## Further Reading

- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli)
- [GitHub Copilot CLI Plugin Reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [GitHub Copilot CLI Programmatic Reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference)
