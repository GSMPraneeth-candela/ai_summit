# LANforge YouTube interop demo

Paste this into Codex on a machine that can reach your LANforge lab. Replace `<MANAGER_IP>` with your LANforge manager’s IP.

> Install the lanforge-youtube skill from https://github.com/GSMPraneeth-candela/ai_summit into ~/.agents/skills/lanforge-youtube. Read its SKILL.md and follow the setup instructions for LANforge manager <MANAGER_IP>.

If Codex needs a fresh session to load the MCP connection, ask it to resume setup for the same manager using `$lanforge-youtube`.

## Run the demo

Choose an EID from the setup report and paste this into Codex:

> Use $lanforge-youtube to plan a one-minute YouTube test for client <CLIENT_EID> on manager <MANAGER_IP>. After I approve the plan, run it and monitor it through completion. If the client fails, diagnose it over SSH. I authorize repairs for confirmed missing test-venv dependencies or Chromium after the client stops. Show me any rerun plan for approval, then report playback and collected stats.

The setup details in [SKILL.md](SKILL.md) are for the private lab repo.
