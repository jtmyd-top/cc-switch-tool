# cc-switch-tool

`cc-switch` manages relay/proxy endpoint profiles for Claude Code, Codex CLI, and Gemini CLI.

## Install

From this directory:

```bash
pipx install .
```

For local development without installing:

```bash
PYTHONPATH=src python -m cc_switch_tool.cli --help
```

## Usage

Add profiles:

```bash
cc-switch add claude kimi --base-url https://proxy.example.com --api-key sk-xxx
cc-switch add codex openrouter --base-url https://openrouter.ai/api/v1 --api-key sk-xxx --provider openrouter --model gpt-4.1
cc-switch add gemini proxy1 --base-url https://proxy.example.com --api-key xxx
```

Switch profiles:

```bash
cc-switch use claude kimi
cc-switch use codex openrouter
cc-switch use gemini proxy1
```

Edit an existing profile (any subset of fields; if it's the active one, the tool config is rewritten):

```bash
cc-switch edit claude kimi --api-key sk-new
cc-switch edit codex openrouter --base-url https://new.example.com --model gpt-4.1
cc-switch edit codex openrouter --clear-model
```

Inspect profiles:

```bash
cc-switch list
cc-switch current
cc-switch show claude kimi
```

Remove a profile:

```bash
cc-switch remove claude kimi
```

Export environment variables for the active profile:

```bash
eval "$(cc-switch env codex)"
```

## Files written

Profiles are stored in:

```text
~/.cc-switch-tool/profiles.json
```

`cc-switch use claude <name>` updates:

```text
~/.claude/settings.json
```

with:

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "...",
    "ANTHROPIC_BASE_URL": "..."
  }
}
```

`cc-switch use codex <name>` updates:

```text
~/.codex/config.toml
~/.cc-switch-tool/codex.env
```

Codex config uses `env_key = "OPENAI_API_KEY"`, so run this if your shell has not already exported the key:

```bash
eval "$(cc-switch env codex)"
```

`cc-switch use gemini <name>` updates:

```text
~/.gemini/settings.json
~/.gemini/.env
```

with `GEMINI_API_KEY` and `GOOGLE_GEMINI_BASE_URL` in the `.env` file.

API keys are stored locally and written with `0600` permissions where supported. `list` and `show` redact keys by default.

## Cloud sync (WebDAV)

`cc-switch cloud …` (alias: `cc-switch sync …`) backs up `~/.cc-switch-tool/profiles.json` to a WebDAV server you control (Nextcloud, 坚果云 / JianGuoYun, Cloudreve, self-hosted nginx-dav, etc.) and restores it on a new machine.

### Configure (one-time)

```bash
cc-switch cloud setup
# or pass everything on the command line:
cc-switch cloud setup --url https://dav.example.com/dav/ --user alice
```

You'll be prompted for the password. The credentials are written to `~/.cc-switch-tool/webdav.enc` encrypted with **Fernet (AES-128-CBC + HMAC-SHA256)** using a key derived from this machine's `/etc/machine-id` (or, if missing, a random salt at `~/.cc-switch-tool/.keyring`, mode `0600`). The file cannot be decrypted on a different machine — that is by design; on a new host run `cc-switch cloud setup` again.

For self-signed staging WebDAV servers, pass `--insecure` to skip TLS verification.

### Backup / restore

```bash
cc-switch cloud test           # PROPFIND the remote dir to verify auth
cc-switch cloud backup         # PUT profiles.json to the remote
cc-switch cloud restore        # GET remote → write local (timestamped backup of old kept)
cc-switch cloud status         # show URL, username, last sync time, etag
cc-switch cloud forget         # delete webdav.enc and sync.json
```

`restore` refuses by default if the local store has profiles missing on the remote (so you don't silently drop data); pass `--force` to overwrite anyway. Before overwriting, the old `profiles.json` is copied to `profiles.json.bak.<timestamp>` next to it.

### Encrypted uploads (optional)

If your WebDAV provider is shared / not fully trusted, encrypt the upload with an extra passphrase so the server only sees ciphertext:

```bash
cc-switch cloud backup --encrypt           # prompts for a passphrase
cc-switch cloud restore                    # auto-detects ciphertext, prompts for passphrase
```

The passphrase is **not** stored anywhere — you must remember it, and it must be the same on every machine that restores.

### Files

| Path | Contents |
| --- | --- |
| `~/.cc-switch-tool/profiles.json` | Local profile store (mode `0600`). |
| `~/.cc-switch-tool/webdav.enc`    | Fernet ciphertext of the WebDAV URL/username/password (mode `0600`). |
| `~/.cc-switch-tool/sync.json`     | Plain JSON: last backup/restore timestamps, last upload size, etag. |
| `~/.cc-switch-tool/.keyring`      | Fallback machine-bound salt when `/etc/machine-id` is missing (mode `0600`). |

### Threat model

Machine-bound encryption protects the WebDAV credentials against accidental disclosure (e.g., copying `~/.cc-switch-tool` to a USB stick or a different machine). It does **not** protect against an attacker with read access to the same Linux account — same trust boundary as `~/.ssh/id_rsa`. For stronger guarantees, use `cloud backup --encrypt` with a passphrase you keep in your head.

### TUI

Running `cc-switch` (or `ccs`) without arguments opens the TUI. The main menu now has a `☁ cloud sync (WebDAV)` entry that exposes setup/backup/restore/test/forget with the same prompts.

