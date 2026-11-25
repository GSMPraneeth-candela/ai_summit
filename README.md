# LANforge YouTube interop demo

Use Codex to run LANforge YouTube tests with Playwright and Playwright Healer. LANforge MCP supplies the client inventory and controls the run. SSH/SFTP handles laptop setup and troubleshooting.

## 1. Install the skill

Run this in Bash on the machine where Codex runs. That machine needs access to the MCP endpoint and to the laptops' management network. You'll also need the LANforge manager IP, approved SSH access, and a lab with the existing YouTube launcher, AdGuard assets, and YouTube controller on port 5002.

```bash
mkdir -p "$HOME/.agents/skills" &&
  git clone https://github.com/GSMPraneeth-candela/ai_summit.git "$HOME/.agents/skills/lanforge-youtube"
```

If you already installed the skill from this repository, update it with:

```bash
git -C "$HOME/.agents/skills/lanforge-youtube" pull --ff-only
```

## 2. Connect LANforge MCP

Get the full private demo URL on `octagon-last-yoga.ngrok-free.dev` from the lab operator. Paste it when prompted. This command reuses an existing registration named `octagon-last-yoga`. If yours points to a different service or is disabled, correct that local registration before continuing.

```bash
if ! codex mcp get octagon-last-yoga >/dev/null 2>&1; then
  if read -r -s -p 'Paste the full LANforge MCP URL: ' lanforge_demo_url; then
    printf '\n'
    if [[ -n "$lanforge_demo_url" ]]; then
      codex mcp add octagon-last-yoga --url "$lanforge_demo_url"
    fi
  fi
  unset lanforge_demo_url
fi
```

Start a new Codex chat to load the skill and MCP tools. The skill can also register the server during setup when `LANFORGE_MCP_URL` is available in the Codex shell. [Codex MCP setup example](https://developers.openai.com/learn/docs-mcp)

## 3. Set up the laptops

Paste this into Codex and replace `<MANAGER_IP>` with your LANforge manager's IP.

> Use $lanforge-youtube to set up all available, idle real laptops on LANforge manager <MANAGER_IP>. Get their EIDs, OS types and management IPs from LANforge MCP. Use the lab's approved SSH credentials to deploy the bundled youtube.py, create or update the test venv, install the packages and Chromium, and report which laptops are ready.

For standard lab images the documented usernames are `lanforge` on Linux and macOS, and `Administrator` on Windows. If your lab still uses the factory password, obtain it privately from the operator or the lab's original deployment README. Prefer an SSH key or agent when available. The setup verifies SSH host identity and uses the existing LANforge launcher paths.

## 4. Run the demo

Replace `<MANAGER_IP>` and `<CLIENT_EID>` with the manager IP and a ready laptop's EID.

> Use $lanforge-youtube to run a one-minute YouTube streaming test on LANforge manager <MANAGER_IP> for client <CLIENT_EID>. Show me the test plan before starting. Monitor the run until it finishes. If a laptop fails, diagnose it over SSH. I authorize repair of confirmed missing test-venv dependencies or Chromium after the affected client stops. Show me any rerun plan for approval and report playback, collected stats, and what was repaired.

To demonstrate selector recovery, ask for the skill's stale-selector smoke test on a dedicated demo client. The skill checks the healer report and removes the demo flag afterward.
