# cc-switch-tool

[English README](README.md)

`cc-switch-tool` 是一个轻量级的 Python 配置切换工具，用于管理 Claude Code、
Codex CLI、Gemini CLI 的中转 / 代理配置。

它适合在一些原生 `cc-switch` 二进制无法运行的 Linux 机器上使用，例如遇到：

```text
cc-switch: error while loading shared libraries: libssl.so.3:
cannot open shared object file: No such file or directory
```

这类问题通常和系统 OpenSSL 版本或共享库不匹配有关。`cc-switch-tool` 使用
Python 实现，可以避免原生二进制对 `libssl.so.3` 的直接依赖。

## 适用场景

适合以下情况：

- 你需要为 Claude Code、Codex CLI、Gemini CLI 保存多套中转 / 代理配置
- 你经常在 Linux 服务器、远程机器或多台开发机之间切换 endpoint
- 你所在的环境不方便处理原生二进制兼容问题
- 你想通过自己的 WebDAV 服务在多台机器之间同步配置

## 功能

- 管理 Claude Code、Codex CLI、Gemini CLI 配置。
- 支持切换 `base_url`、`api_key`、可选 `model`，以及 Codex `provider`。
- 直接运行 `cc-switch` 或 `ccs` 可进入交互式 TUI。
- 支持中文 / 英文界面，可通过 `--lang`、`CCS_LANG` 或 TUI 菜单切换。
- 支持 WebDAV 云备份和恢复，方便多机器同步配置。
- 支持从 GUI 版 `cc-switch` 的 WebDAV 备份中导入配置。
- TUI 中可一键安装/更新 Codex CLI、Claude Code、Gemini CLI。
- 引导安装脚本可自动安装 Node.js 和内置 AI CLI 工具。
- 本地密钥文件尽量使用严格权限写入。
- `list` 和 `show` 默认隐藏 API Key。

## 环境要求

- Python 3.9+
- 目标 CLI 的配置文件所在环境
- 安装/更新 Codex CLI、Claude Code、Gemini CLI 时需要 Node.js 20+ 和 npm
- 推荐使用 `pipx` 进行隔离安装

## 安装

带 Python 3.9+ 检查的引导安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/jtmyd-top/cc-switch-tool/main/scripts/bootstrap_install.py | python3
```

默认情况下，引导安装脚本也会检查 Node.js 20+，并安装/更新：

- `@openai/codex`
- `@anthropic-ai/claude-code`
- `@google/gemini-cli`

如果只想安装 `cc-switch-tool`，可以加 `--skip-clis`：

```bash
curl -fsSL https://raw.githubusercontent.com/jtmyd-top/cc-switch-tool/main/scripts/bootstrap_install.py | python3 - --skip-clis
```

推荐使用 `pipx`：

```bash
pipx install git+https://github.com/jtmyd-top/cc-switch-tool.git
```

如果没有 `pipx`：

```bash
python3 -m pip install --user git+https://github.com/jtmyd-top/cc-switch-tool.git
```

Termux 上可以先安装 `pipx`，也可以直接使用 `pip --user`：

```bash
pkg install python-pipx
pipx ensurepath
pipx install git+https://github.com/jtmyd-top/cc-switch-tool.git
```

从本地源码目录安装：

```bash
git clone https://github.com/jtmyd-top/cc-switch-tool.git
cd cc-switch-tool
pipx install .
```

云同步加密功能使用可选依赖：

```bash
pipx inject cc-switch-tool cryptography
```

开发模式，不安装直接运行：

```bash
PYTHONPATH=src python3 -m cc_switch_tool.cli --help
```

安装后的命令：

```bash
cc-switch
ccs
```

已安装设备升级：

```bash
cc-switch upgrade
```

查看当前已安装版本：

```bash
cc-switch --version
```

也可以直接运行不带参数的 `cc-switch`，然后在主菜单里选择“升级程序”。

## 快速开始

1. 添加配置：

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

2. 启用配置：

```bash
cc-switch use claude kimi
cc-switch use codex openrouter
cc-switch use gemini proxy1
```

3. 查看配置：

```bash
cc-switch list
cc-switch current
cc-switch show claude kimi
```

4. 编辑配置：

```bash
cc-switch edit claude kimi --api-key sk-new
cc-switch edit claude kimi --model claude-sonnet-4
cc-switch edit codex openrouter --base-url https://new.example.com --model gpt-4.1
cc-switch edit codex openrouter --clear-model
```

如果编辑的是当前正在使用的配置，工具会立即重写对应 CLI 的配置文件。

5. 删除配置：

```bash
cc-switch remove claude kimi
```

6. 导出当前启用配置的环境变量：

```bash
eval "$(cc-switch env codex)"
```

也可以不切换当前配置，直接导出某个已保存的配置：

```bash
cc-switch env codex openrouter
```

## 命令概览

常用命令：

- `cc-switch add <tool> <name> --base-url ... --api-key ...`
- `cc-switch use <tool> <name>`
- `cc-switch edit <tool> <name> ...`
- `cc-switch remove <tool> <name>`
- `cc-switch list [tool]`
- `cc-switch current [tool]`
- `cc-switch show <tool> <name>`
- `cc-switch env <tool> [name]`
- `cc-switch menu`

支持的 `tool`：

- `claude`
- `codex`
- `gemini`

## 交互式菜单

直接运行：

```bash
cc-switch
```

或：

```bash
ccs
```

会进入 TUI 菜单。菜单中可以添加、编辑、删除、切换配置，也可以进行 WebDAV
云同步、从 GUI 备份导入配置、切换语言，以及一键安装/更新 Codex CLI、
Claude Code、Gemini CLI。如果 Node.js/npm 不存在或版本过低，TUI 会尝试先通过
系统包管理器安装 Node.js。

## 语言

单次命令指定语言：

```bash
cc-switch --lang zh list
cc-switch --lang en list
```

或使用环境变量：

```bash
export CCS_LANG=zh
```

TUI 菜单里也可以切换语言。保存后的语言配置位于：

```text
~/.cc-switch-tool/settings.json
```

## 写入的文件

工具自己的配置保存在：

```text
~/.cc-switch-tool/profiles.json
```

这个文件保存：

- 所有已保存的配置
- 每个工具当前启用的配置名

`cc-switch use claude <name>` 会更新：

```text
~/.claude/settings.json
~/.cc-switch-tool/active.env
~/.bashrc
```

写入类似内容：

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "...",
    "ANTHROPIC_BASE_URL": "...",
    "ANTHROPIC_MODEL": "..."
  }
}
```

只有配置里设置了 `model` 时，才会写入 `ANTHROPIC_MODEL`。

`cc-switch use codex <name>` 会更新：

```text
~/.codex/config.toml
~/.cc-switch-tool/codex.env
~/.cc-switch-tool/active.env
~/.bashrc
```

Codex 配置使用 `env_key = "OPENAI_API_KEY"`。当前启用的 key 也会写入
`~/.cc-switch-tool/active.env`，并且 `cc-switch use` 会在 `~/.bashrc` 中安装
自动加载片段（如果存在 `~/.zshrc` 也会写入）。启动 Codex 前请新开一个 shell，
或者运行 `source ~/.bashrc`。

`cc-switch use gemini <name>` 会更新：

```text
~/.gemini/settings.json
~/.gemini/.env
~/.cc-switch-tool/active.env
~/.bashrc
```

其中 `.env` 会写入 `GEMINI_API_KEY` 和 `GOOGLE_GEMINI_BASE_URL`。

云恢复和从 GUI 备份导入配置后，会自动重新应用 active 配置，所以目标 CLI 配置文件
和当前 shell 环境文件会在同一步更新。

如果删除的是当前启用配置，本地 active 记录也会一并清除。

## WebDAV 云同步

`cc-switch cloud ...` 可以把 `~/.cc-switch-tool/profiles.json` 备份到你自己的
WebDAV 服务，并在新机器上恢复。

`cc-switch sync ...` 是 `cc-switch cloud ...` 的别名。

常见 WebDAV 服务包括 Nextcloud、坚果云、Cloudreve、自建 WebDAV 服务等。

### 初始化配置

```bash
cc-switch cloud setup
```

也可以直接传入常用参数：

```bash
cc-switch cloud setup \
  --url https://dav.example.com/dav/ \
  --user alice
```

如果没有传 `--password`，会交互式询问密码。

WebDAV 凭据保存在：

```text
~/.cc-switch-tool/webdav.enc
```

该文件使用机器绑定密钥加密，密钥来源优先使用 `/etc/machine-id`，如果不可用则
使用 `~/.cc-switch-tool/.keyring` 中的本机盐值。一个机器上加密的 WebDAV 配置
不设计为迁移到另一台机器解密；新机器上请重新运行 `cc-switch cloud setup`。

如果是自签名证书的 WebDAV 服务：

```bash
cc-switch cloud setup --insecure
```

### 备份和恢复

```bash
cc-switch cloud test
cc-switch cloud backup
cc-switch cloud restore
cc-switch cloud status
cc-switch cloud forget
```

`restore` 会在覆盖前保留旧的本地 `profiles.json` 时间戳备份。如果本地有远端
不存在的配置，默认会拒绝覆盖；确认要覆盖时使用 `--force`。

### 可选：加密上传

如果 WebDAV 服务是共享服务，或者你不完全信任服务端，可以给上传内容额外加密：

```bash
cc-switch cloud backup --encrypt
cc-switch cloud restore
```

这个额外口令不会保存在本地，请自行记住。

### 典型导入流程

从 GUI 版 `cc-switch` 备份导入时，通常是：

1. 先用 `cc-switch cloud setup` 配好 WebDAV 连接
2. 通过 `--pull-dir` 指定 GUI 备份所在目录
3. 运行 `cc-switch cloud pull`

### 从 GUI 版 cc-switch 备份导入

如果 GUI 版 `cc-switch` 会把 `db.sql` 备份到 WebDAV，可以在 setup 时配置其远端目录：

```bash
cc-switch cloud setup --pull-dir /path/on/webdav/
```

然后导入：

```bash
cc-switch cloud pull
```

其他用法：

```bash
cc-switch cloud pull --pull-dir /path/on/webdav/
cc-switch cloud pull https://dav.example.com/path/db.sql
cc-switch cloud pull --overwrite
```

## 常见问题

### 原版 cc-switch 报 `libssl.so.3`

如果看到：

```text
cc-switch: error while loading shared libraries: libssl.so.3:
cannot open shared object file: No such file or directory
```

可以安装这个 Python 实现：

```bash
pipx install git+https://github.com/jtmyd-top/cc-switch-tool.git
```

这样通常不需要为了一个工具去改旧 Linux 机器上的系统 OpenSSL 包。

### 缺少 `tomlkit` 或 `questionary`

请通过 `pipx install git+...` 或 `pipx install .` 安装，项目依赖会自动安装。

即使你只打算使用非交互式 CLI，`questionary` 也仍然属于项目依赖，因为 TUI 和
CLI 在同一个包里发布。

### `pip install --user` 后找不到命令

确认用户脚本目录在 `PATH` 中，通常是：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 安全说明

API Key 会保存在本地 `~/.cc-switch-tool/profiles.json`，并写入对应工具的配置文件。
相关文件会尽量以 `0600` 权限写入。

默认情况下，`list` 和 `show` 的终端输出会隐藏 API Key。

WebDAV 凭据的机器绑定加密可以防止 `webdav.enc` 被误拷贝到其他机器后直接使用。
但它不能防御已经能以同一个 Linux 用户读取本地文件的攻击者。

如果需要更强的云备份保护，请使用：

```bash
cc-switch cloud backup --encrypt
```
