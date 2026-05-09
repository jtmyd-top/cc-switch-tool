# cc-switch-tool

[中文文档](README.zh-CN.md)

`cc-switch-tool` is a lightweight Python profile switcher for Claude Code,
Codex CLI, and Gemini CLI relay/proxy endpoints.

It is useful on Linux machines where a native `cc-switch` binary cannot start
because of system library mismatches, for example:

```text
cc-switch: error while loading shared libraries: libssl.so.3:
cannot open shared object file: No such file or directory
```

Because this project is implemented in Python, it avoids that OpenSSL shared
library dependency from native binaries.

## Why Use It

Use `cc-switch-tool` when you need to:

- keep multiple relay/proxy profiles for Claude Code, Codex CLI, or Gemini CLI
- switch endpoints quickly on Linux servers, remote boxes, or shared workstations
- avoid native binary compatibility issues on older systems
- sync your profile store across machines through your own WebDAV server

## Features

- Manage profiles for Claude Code, Codex CLI, and Gemini CLI.
- Switch `base_url`, `api_key`, optional `model`, and Codex `provider`.
- Interactive TUI when running `cc-switch` or `ccs` without arguments.
- Chinese / English UI via `--lang`, `CCS_LANG`, or the TUI language menu.
- WebDAV backup and restore for profile sync across machines.
- Optional import from GUI `cc-switch` WebDAV backups.
- One-click install/update for Codex CLI, Claude Code, and Gemini CLI from the TUI.
- Bootstrap installer can install Node.js and the bundled AI CLI tools automatically.
- Local secret files are written with restrictive permissions where supported.
- API keys are redacted in `list` and `show` output by default.

## Requirements

- Python 3.9+
- Linux or another environment where the target CLI config files are available
- Node.js 20+ and npm for installing/updating Codex CLI, Claude Code, and Gemini CLI
- `pipx` recommended for isolated installation

## Installation

Bootstrap installer with a Python 3.9+ check:

```bash
curl -fsSL https://raw.githubusercontent.com/jtmyd-top/cc-switch-tool/main/scripts/bootstrap_install.py | python3
```

By default, the bootstrap installer also checks Node.js 20+ and installs/updates:

- `@openai/codex`
- `@anthropic-ai/claude-code`
- `@google/gemini-cli`

Use `--skip-clis` to install only `cc-switch-tool`:

```bash
curl -fsSL https://raw.githubusercontent.com/jtmyd-top/cc-switch-tool/main/scripts/bootstrap_install.py | python3 - --skip-clis
```

Recommended with `pipx`:

```bash
pipx install git+https://github.com/jtmyd-top/cc-switch-tool.git
```

If `pipx` is unavailable:

```bash
python3 -m pip install --user git+https://github.com/jtmyd-top/cc-switch-tool.git
```

On Termux, install `pipx` first or use `pip --user` directly:

```bash
pkg install python-pipx
pipx ensurepath
pipx install git+https://github.com/jtmyd-top/cc-switch-tool.git
```

From a local checkout:

```bash
git clone https://github.com/jtmyd-top/cc-switch-tool.git
cd cc-switch-tool
pipx install .
```

Cloud sync encryption uses an optional dependency:

```bash
pipx inject cc-switch-tool cryptography
```

Development without installing:

```bash
PYTHONPATH=src python3 -m cc_switch_tool.cli --help
```

The installed commands are:

```bash
cc-switch
ccs
```

Upgrade an existing installation:

```bash
cc-switch upgrade
```

Check the installed version:

```bash
cc-switch --version
```

You can also open `cc-switch` with no arguments and choose `upgrade program`
from the main menu.

## Quick Start

1. Add one or more profiles:

```bash
cc-switch add claude kimi \
  --base-url https://proxy.example.com \
  --api-key sk-xxx \
  --model claude-sonnet-4

cc-switch add codex openrouter \
  --base-url https://openrouter.ai/api/v1 \
  --api-key sk-xxx \
  --provider openrouter \
  --model gpt-4.1

cc-switch add gemini proxy1 \
  --base-url https://proxy.example.com \
  --api-key xxx
```

2. Activate a profile:

```bash
cc-switch use claude kimi
cc-switch use codex openrouter
cc-switch use gemini proxy1
```

3. Inspect saved profiles:

```bash
cc-switch list
cc-switch current
cc-switch show claude kimi
```

4. Update a profile:

```bash
cc-switch edit claude kimi --api-key sk-new
cc-switch edit claude kimi --model claude-sonnet-4
cc-switch edit codex openrouter --base-url https://new.example.com --model gpt-4.1
cc-switch edit codex openrouter --clear-model
```

If the edited profile is currently active, `cc-switch-tool` rewrites the target
tool config immediately.

5. Remove a profile:

```bash
cc-switch remove claude kimi
```

6. Export environment variables for the active profile:

```bash
eval "$(cc-switch env codex)"
```

You can also export a specific saved profile without activating it first:

```bash
cc-switch env codex openrouter
```

## Command Overview

Core commands:

- `cc-switch add <tool> <name> --base-url ... --api-key ...`
- `cc-switch use <tool> <name>`
- `cc-switch edit <tool> <name> ...`
- `cc-switch remove <tool> <name>`
- `cc-switch list [tool]`
- `cc-switch current [tool]`
- `cc-switch show <tool> <name>`
- `cc-switch env <tool> [name]`
- `cc-switch menu`

Supported tools:

- `claude`
- `codex`
- `gemini`

## Interactive TUI

Run without arguments:

```bash
cc-switch
```

or:

```bash
ccs
```

The TUI supports profile add/edit/remove/switch workflows, WebDAV cloud sync,
GUI backup pull, language switching, and one-click install/update for Codex CLI,
Claude Code, and Gemini CLI. If Node.js/npm is missing or too old, the TUI can
try to install Node.js first using the system package manager.

## Language

Set language for one command:

```bash
cc-switch --lang en list
cc-switch --lang zh list
```

Or set an environment variable:

```bash
export CCS_LANG=zh
```

The TUI also has a language menu. The saved language is stored in:

```text
~/.cc-switch-tool/settings.json
```

## Files Written

Profiles are stored in:

```text
~/.cc-switch-tool/profiles.json
```

This file stores:

- all saved profiles
- the active profile name for each tool

`cc-switch use claude <name>` updates:

```text
~/.claude/settings.json
~/.cc-switch-tool/active.env
~/.bashrc
```

with:

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "...",
    "ANTHROPIC_BASE_URL": "...",
    "ANTHROPIC_MODEL": "..."
  }
}
```

`ANTHROPIC_MODEL` is only written when the selected profile has a model.

`cc-switch use codex <name>` updates:

```text
~/.codex/config.toml
~/.cc-switch-tool/codex.env
~/.cc-switch-tool/active.env
~/.bashrc
```

Codex uses `env_key = "OPENAI_API_KEY"`. The active key is also written to
`~/.cc-switch-tool/active.env`, and `cc-switch use` installs a shell startup
loader in `~/.bashrc` (and `~/.zshrc` when it exists). Open a new shell, or
run `source ~/.bashrc`, before starting Codex from that shell.

`cc-switch use gemini <name>` updates:

```text
~/.gemini/settings.json
~/.gemini/.env
~/.cc-switch-tool/active.env
~/.bashrc
```

with `GEMINI_API_KEY` and `GOOGLE_GEMINI_BASE_URL`.

Cloud restore and GUI backup import re-apply active profiles after profiles are
restored, so the target CLI config files and active shell env file are updated
in the same step.

Removing an active profile clears it from the local active-profile record.

## Cloud Sync (WebDAV)

`cc-switch cloud ...` backs up `~/.cc-switch-tool/profiles.json` to a WebDAV
server you control and restores it on another machine.

`cc-switch sync ...` is an alias for `cc-switch cloud ...`.

Supported WebDAV providers include Nextcloud, JianGuoYun, Cloudreve, and
self-hosted WebDAV servers.

### Setup

```bash
cc-switch cloud setup
```

Or pass common fields directly:

```bash
cc-switch cloud setup \
  --url https://dav.example.com/dav/ \
  --user alice
```

You will be prompted for the password if `--password` is omitted.

Credentials are stored in:

```text
~/.cc-switch-tool/webdav.enc
```

The file is encrypted with a machine-bound key derived from `/etc/machine-id`,
or a fallback salt in `~/.cc-switch-tool/.keyring` when `machine-id` is not
available. A config encrypted on one machine is not meant to be decrypted on
another machine; run `cc-switch cloud setup` again on each host.

For self-signed WebDAV servers:

```bash
cc-switch cloud setup --insecure
```

### Backup and Restore

```bash
cc-switch cloud test
cc-switch cloud backup
cc-switch cloud restore
cc-switch cloud status
cc-switch cloud forget
```

`restore` keeps a timestamped backup of the previous local `profiles.json`.
It refuses to overwrite by default if local profiles are missing on the remote;
use `--force` when you intentionally want to overwrite.

### Optional Encrypted Uploads

Use an extra passphrase when your WebDAV server is shared or not fully trusted:

```bash
cc-switch cloud backup --encrypt
cc-switch cloud restore
```

The passphrase is not stored. You must remember it.

### Pull Workflow

Typical GUI-backup import flow:

1. Configure WebDAV credentials with `cc-switch cloud setup`
2. Set `--pull-dir` to the directory that contains GUI `cc-switch` backups
3. Run `cc-switch cloud pull`

### Pull from GUI cc-switch Backup

If the GUI `cc-switch` app backs up a `db.sql` file to WebDAV, configure its
remote directory during setup:

```bash
cc-switch cloud setup --pull-dir /path/on/webdav/
```

Then import from it:

```bash
cc-switch cloud pull
```

Other options:

```bash
cc-switch cloud pull --pull-dir /path/on/webdav/
cc-switch cloud pull https://dav.example.com/path/db.sql
cc-switch cloud pull --overwrite
```

## Troubleshooting

### Native cc-switch fails with `libssl.so.3`

If you see:

```text
cc-switch: error while loading shared libraries: libssl.so.3:
cannot open shared object file: No such file or directory
```

install this Python implementation instead:

```bash
pipx install git+https://github.com/jtmyd-top/cc-switch-tool.git
```

This avoids changing system OpenSSL packages on older Linux hosts.

### `tomlkit` or `questionary` is missing

Install through `pipx install git+...` or `pipx install .` so project
dependencies are installed automatically.

If you only want the non-interactive CLI, `questionary` is still part of the
project dependencies because the TUI ships in the same package.

### Command not found after `pip install --user`

Make sure your user script directory is in `PATH`, usually:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Security Notes

API keys are stored locally in `~/.cc-switch-tool/profiles.json` and written to
the target tool config files. The files are written with `0600` permissions
where supported.

By default, `list` and `show` redact API keys in terminal output.

Machine-bound WebDAV credential encryption protects against accidental copying
of `~/.cc-switch-tool/webdav.enc` to another machine. It does not protect
against an attacker who can already read files as the same Linux user.

For stronger protection of cloud backups, use:

```bash
cc-switch cloud backup --encrypt
```
