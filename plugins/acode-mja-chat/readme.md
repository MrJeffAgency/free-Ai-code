# MrJeffAgency AI Chat for Acode

Chat with any model configured in your local MJA server, directly inside Acode.

## Requirements

- A running MJA server at `http://127.0.0.1:8082` (run `mja-server` first), with at least one provider key configured.
- Recent Acode with the Command palette.

## Usage

Command palette (Ctrl+Shift+P):
- **MJA Chat: Open** – open the chat panel
- **MJA Chat: Set server URL** – change the MJA server address (default `http://127.0.0.1:8082`)
- **MJA Chat: Set model** – choose a model id (leave blank to use the server default)

Type a message and press Enter (or click Send). The reply streams in as it arrives. Click **Insert into editor** to place the last reply (or a lone code block) at your cursor.

The server URL and model are saved in localStorage. If Proxy Authentication is enabled in MJA, set the bearer token with **MJA Chat: Set token**.
