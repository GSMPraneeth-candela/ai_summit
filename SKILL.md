---
name: lanforge-youtube
description: Prepare LANforge lab laptops for a requested LANforge-script YouTube test and monitor and troubleshoot their bundled Playwright client over SSH.
---

## Connect LANforge MCP

Reuse the existing `octagon-last-yoga` LANforge MCP connection if it matches the endpoint below and exposes the LANforge tools. If the registration is missing, run:

```bash
codex mcp add octagon-last-yoga --url 'https://octagon-last-yoga.ngrok-free.dev/TzkT2lJGo5nvDHJMfec3mpK0g7KF89UDNjJHFQO609Y/mcp'
```

If an existing registration points elsewhere, report the mismatch before replacing it. Check that the current session exposes the tools before continuing. If it does not, have the user start a fresh session and resume setup. Pass the user's LANforge manager IP separately as `unit` on relevant calls.

## Set up the laptops

Use this workflow when the user explicitly asks for skill setup or requests a LANforge-script YouTube test. LANforge MCP owns test selection, planning, approval, launch and results. Before it launches a requested test, verify that the selected laptops have the bundled client and its dependencies. Report any unready laptop before launch.

1. Use `real_devices` on the requested manager for the LANforge inventory. For initial setup, enumerate all real Linux, macOS and Windows laptops. For test preparation, use only the laptops selected for that run. Match EIDs to the returned OS and management IP. Skip offline and busy clients and report them. Use the management network for SSH.
2. Verify SSH host keys against the lab's trusted inventory. Use an existing approved SSH key or agent when configured. Otherwise use the following defaults for standard LANforge lab laptops returned by the requested manager. If the operator provided different credentials, use those instead.

   | OS | SSH username | SSH password |
   |---|---|---|
   | Linux | `lanforge` | `lanforge` |
   | macOS | `lanforge` | `lanforge` |
   | Windows | `Administrator` | `lanforge` |

   Supply the password through SSH authentication rather than in a command argument. Stop on authentication failure and report the affected EID. Keep credentials out of run reports and logs.
3. Confirm the launcher path and account over SSH before installing. These are the standard paths. The venv goes under the deployment root, beside the `youtube` directory.

   | OS | Deployment root | Venv interpreter relative to root |
   |---|---|---|
   | Linux | `/home/lanforge/local/real_application_test` | `ratvenv/bin/python` |
   | macOS | `/Users/lanforge/local/real_application_test` | `ratvenv/bin/python` |
   | Windows | `C:\Program Files (x86)\LANforge-Server\local\real_application_test` | `ratvenv\Scripts\python.exe` |

4. Compare the deployed script with the bundled [youtube.py](youtube.py). If missing or different, stage the bundled copy via SFTP or SCP, verify its checksum, and place it at `youtube/youtube.py` under the deployment root. Keep a recoverable copy of any replaced script. Reuse a valid `ratvenv` or create it with `python3 -m venv ratvenv` on Linux/macOS or `py -m venv ratvenv` on Windows, from the deployment root. Verify `requests`, `playwright` and `playwright-healer==1.0.7` in that environment and install only what is missing or incompatible. Use the lab's tested package pins if supplied. If Chromium is missing, run `-m playwright install chromium` with that interpreter as the launcher user. Follow the lab's existing dependency download route, including its Linux Wi-Fi VRF where configured.
5. Verify imports, the deployed script checksum and Chromium availability under the launcher account. Report readiness per EID. The lab needs the existing LANforge YouTube launcher, the AdGuard directory at the path expected by the script, and the HTTP controller on port 5002 for stop signals and results.

## Monitor and recover

- Once MCP starts the test, follow that run through completion using its name or ID and the status MCP provides. Allow a reasonable startup and reporting grace period. If a client stalls or fails, inspect its current run log over SSH. Check the launcher's actual interpreter, imports and Chromium installation. For selector failures, read the Playwright Healer report.
- Diagnose as soon as the failure is visible. Apply authorized, targeted fixes such as restoring a missing dependency or Chromium after the affected client process stops. Verify the fix under the same launcher account. Leave active tests on healthy laptops running. Route any rerun through MCP's normal workflow.
- Report each affected EID, the failure, verified repairs and any remaining blocker. Preserve the original run logs.
