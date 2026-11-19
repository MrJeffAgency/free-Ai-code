# MrJeffAgency AI Chat for VS Code

Chat with any model configured in your local MJA server, directly inside VS Code.

## Requirements

- A running MJA server at `http://127.0.0.1:8082` with at least one provider key configured.
- VS Code 1.90 or newer.

## Install

Build/install locally with `vsce`:

```bash
cd plugins/vscode-mja-chat
npx @vscode/vsce package
code --install-extension mja-chat-1.0.0.vsix
```

Or install the packed `.vsix` via VS Code: **Extensions → ⋯ → Install from VSIX…**

## Usage

Open the command palette (Ctrl+Shift+P) and run **MJA Chat: Open**. Type a message and press Enter (or click Send). Replies stream in as they arrive. Click **Insert** to place the last reply (or a lone code block) at your cursor in the active editor.

Commands:
- **MJA Chat: Open** – open the chat panel
- **MJA Chat: Set server URL** – change the MJA server address
- **MJA Chat: Set model** – choose a model id (blank = server default)
- **MJA Chat: Set token** – bearer token if MJA Proxy Authentication is enabled

Settings are stored in VS Code user settings (`mjaChat.*`).
