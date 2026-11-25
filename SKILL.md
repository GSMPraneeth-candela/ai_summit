---
name: lanforge-youtube
description: Prepare LANforge lab laptops for a requested LANforge-script YouTube test and monitor and troubleshoot their bundled Playwright client over SSH.
---

## Connect LANforge MCP

The user can say “Connect the LANforge MCP server for this skill.” Register the endpoint below as a remote HTTP MCP server in the AI host running the skill. The URL is ready to register.

Reuse the existing `octagon-last-yoga` LANforge MCP connection if it matches the endpoint below and exposes the LANforge tools. If the registration is missing, run:

```bash
codex mcp add octagon-last-yoga --url 'https://octagon-last-yoga.ngrok-free.dev/TzkT2lJGo5nvDHJMfec3mpK0g7KF89UDNjJHFQO609Y/mcp'
```

In Claude Code, use `claude mcp add --transport http octagon-last-yoga <URL-above>` instead. For a host without shell-based registration, use its MCP settings.

If an existing registration points elsewhere, report the mismatch before replacing it. Confirm the current session exposes LANforge tools and that `real_devices` succeeds for the requested manager. If the tools are missing after registration, start a fresh session or ask the user to reopen the host if required, then resume setup. Pass the user's LANforge manager IP separately as `unit` on relevant calls. The MCP URL is the tool server address and the manager IP identifies the testbed.

## How the skill works with LANforge MCP

- **LANforge MCP** supplies the client inventory and owns the test plan, approval, launch, run status, and results. This skill applies to an explicitly requested LANforge-script YouTube test. That workflow uses the installed YouTube launcher on each selected laptop and picks up the script deployed by this skill. The QCM YouTube workflow uses a different runner.
- **This skill** prepares the selected laptops and handles client-side recovery. Use MCP inventory to map each EID to its OS and management IP, then use SSH/SFTP over the management network. The deployment and repair steps apply to the existing YouTube client and its venv.
- **The bundled `youtube.py`** drives playback with Playwright and handles supported selector changes with Playwright Healer. The LANforge controller receives the resulting logs and stats. A missing Python package or browser runtime is an SSH diagnosis and repair case. A stale locator with successful playback is a browser recovery case, confirmed in the healer report.

For a requested run, wait until MCP has identified the target laptops, then complete the preparation below before launch. If the target list changes, verify readiness for the new list before launch. Keep MCP's approval flow and report any unready clients so the user can decide whether to proceed with a smaller set. After launch, monitor the same run and use SSH only on the affected client when evidence points to a laptop-side failure. Let MCP handle reruns and results.

## Set up the laptops

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
