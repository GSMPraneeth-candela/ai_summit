#!/usr/bin/python3
import asyncio
import os
import argparse
from datetime import datetime, timedelta
import requests
import re
import platform
import logging
import shutil
import sys
from pathlib import Path

from playwright.async_api import TimeoutError as TimeoutException
from playwright.async_api import async_playwright
from playwright_healer import HealerConfig, HealingPage, auto_config

# Windows legacy consoles are cp1252; the healer prints unicode (e.g. a check
# mark) and would crash the run, so force UTF-8 output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _use_script_owner_browser_cache():
    """When run as another user (e.g. root), reuse the script owner's
    Playwright browser cache instead of an empty one."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or platform.system() == "Windows":
        return
    try:
        import pwd

        home = pwd.getpwuid(os.stat(os.path.abspath(__file__)).st_uid).pw_dir
    except Exception:
        return
    rel = (
        "Library/Caches/ms-playwright"
        if platform.system() == "Darwin"
        else ".cache/ms-playwright"
    )
    cache = os.path.join(home, rel)
    if os.path.isdir(cache) and cache != os.path.join(os.path.expanduser("~"), rel):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cache


_use_script_owner_browser_cache()

LOG_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "youtube_test.log"
)
ARTIFACT_DIR = Path(__file__).resolve().parent / "playwright_artifacts"
AUTOMATION_RETRIES = 3
AUTOMATION_RETRY_DELAY_SECONDS = 2

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False

_log_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)
logger.addHandler(_console_handler)

_file_handler = logging.FileHandler(
    LOG_FILE_PATH,
    mode="w",
)
_file_handler.setFormatter(_log_fmt)
logger.addHandler(_file_handler)


def demo_flag(name):
    """Demo hooks are switched by flag files next to this script."""
    flag = Path(__file__).resolve().parent / name
    return flag if flag.exists() else None


def demo_selector(real, stale):
    """demo_dom_break.flag: use a deliberately stale selector so the healer
    has something to fix."""
    return stale if demo_flag("demo_dom_break.flag") else real


def demo_dir():
    """demo_record.flag: record browser video (and healer reports) under
    demo_videos/<label>, where <label> is the flag file's text."""
    flag = demo_flag("demo_record.flag")
    if not flag:
        return None
    path = flag.parent / "demo_videos" / (flag.read_text().strip() or "run")
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_healer_config():
    """Use configured AI providers, or local heuristic/DOM healing by default."""
    try:
        config = auto_config()
        providers = ", ".join(provider.provider.value for provider in config.providers)
        logger.info("Playwright healer AI providers enabled: %s.", providers)
    except ValueError:
        config = HealerConfig()
        logger.info(
            "No Playwright healer AI provider configured; using local heuristic "
            "and DOM-fuzzy healing."
        )

    config.report_dir = str(ARTIFACT_DIR / "healer_reports")
    config.cache.file_path = str(ARTIFACT_DIR / "healer_cache.json")
    if demo_flag("demo_healer_off.flag"):
        config.enable_heuristic = False
        config.enable_dom_fuzzy = False
        logger.info("Demo: Playwright healer disabled (standard approach).")
    if demo_dir():
        config.report_dir = str(demo_dir() / "healer_reports")
    return config


def record_debug_error(context):
    """Record technical error details in the main client test log."""
    active_exception = sys.exc_info()[1]
    if active_exception is None:
        logger.error(context)
    elif isinstance(active_exception, TimeoutException):
        return
    else:
        logger.exception(
            "%s: %s: %s",
            context,
            type(active_exception).__name__,
            active_exception,
        )


def upload_test_log(host, device_name):
    """Upload this client's log to the active YouTube test results directory."""
    logger.info("Uploading client log.")
    try:
        _file_handler.flush()
        with open(LOG_FILE_PATH, "rb") as log_file:
            response = requests.post(
                f"http://{host}:5002/upload_youtube_log",
                data={"device_name": device_name, "device_type": "client"},
                files={"log_file": ("youtube_test.log", log_file, "text/plain")},
                timeout=30,
            )
        if response.status_code != 200:
            logger.error(
                "Failed to upload YouTube test log to "
                "http://%s:5002/upload_youtube_log. Status code: %s",
                host,
                response.status_code,
            )
        else:
            logger.info("Client log uploaded successfully.")
    except Exception:
        logger.error(
            "Unable to upload the client log. " "The log remains available locally."
        )
        record_debug_error("Client log upload failed")


class YouTube(object):

    def __init__(self, url, resolution, host, port, duration, device_name, page):
        self.url = url
        self.resolution = resolution
        self.device_name = device_name
        self.host = host
        self.port = port
        self.page = page
        self.healing_page = HealingPage(
            page, build_healer_config(), test_name=f"youtube-{device_name}"
        )
        self.healer_stopped = False
        self.duration = duration
        self.dataset = []
        self.stop_signal = False
        self.current_stage = "initializing the test"
        self.stats_upload_failures = 0
        self.server_connection_failed = False
        self.stop_check_failed = False
        self.last_progress_log = None

    async def retry_automation_step(
        self, description, action, final_failure_is_error=False
    ):
        """Run a transient browser action a few times before giving up.

        Setup actions such as opening a YouTube context menu occasionally
        fail while the player is still rendering.  Callers decide whether a
        final failure is fatal; this helper only provides consistent retry
        behavior and logging.
        """
        for attempt in range(1, AUTOMATION_RETRIES + 1):
            try:
                await action()
                if attempt > 1:
                    logger.info(
                        "%s succeeded on attempt %s/%s.",
                        description,
                        attempt,
                        AUTOMATION_RETRIES,
                    )
                return True
            except Exception as error:
                log = logger.warning
                if attempt == AUTOMATION_RETRIES and final_failure_is_error:
                    log = logger.error
                log(
                    "%s failed on attempt %s/%s: %s",
                    description,
                    attempt,
                    AUTOMATION_RETRIES,
                    error,
                )
                if attempt < AUTOMATION_RETRIES:
                    await self.dismiss_player_menu(log_success=False)
                    await asyncio.sleep(AUTOMATION_RETRY_DELAY_SECONDS)
        return False

    def get_video_id(self):
        return self.url.split("=")[1]

    async def focus_video_tab(self):
        """Close any extra tab and leave the YouTube tab in the foreground.

        The adguard extension opens a welcome tab as it loads, and that tab
        takes the foreground. Chrome then throttles the backgrounded YouTube
        tab, so the player never fetches media and every sample reads back
        0x0 with no frames.

        The welcome tab only shows up several seconds after the page load
        returns, so wait for it rather than sampling the tab list once.
        """
        context = self.page.context
        context.on("page", lambda page: asyncio.create_task(page.close()))
        for page in context.pages:
            if page != self.page:
                await page.close()
        await self.page.bring_to_front()

    async def load_video(self):
        logger.info("Loading YouTube video: %s", self.url)

        async def load():
            await self.focus_video_tab()
            await self.healing_page.goto(
                self.url, wait_until="domcontentloaded", timeout=60_000
            )
            await self.healing_page.locator(
                "#movie_player", "YouTube video player"
            ).wait_for(timeout=30_000)

        loaded = await self.retry_automation_step(
            "Loading the YouTube page", load, final_failure_is_error=True
        )
        if loaded:
            logger.info("YouTube page DOM and player loaded successfully.")
        return loaded

    def check_stop_signal(self):
        """Check the stop signal from the Flask server."""
        try:
            endpoint_url = f"http://{self.host}:5002/check_stop"

            response = requests.get(endpoint_url, timeout=5)
            if response.status_code == 200:
                if self.stop_check_failed:
                    logger.info("Connection to the test server recovered.")
                    self.stop_check_failed = False

                stop_signal_from_server = response.json().get("stop", False)

                # Only update if the server's stop signal is True
                if stop_signal_from_server:
                    self.stop_signal = True
                    logger.info("Stop signal received from server. Stopping playback.")
            else:
                logger.warning(
                    "Stop-signal endpoint returned HTTP %s.",
                    response.status_code,
                )
            return self.stop_signal
        except Exception:
            if not self.stop_check_failed:
                logger.warning(
                    "Unable to check for a stop request because "
                    "the test server is unavailable."
                )
                self.stop_check_failed = True
                record_debug_error("Stop-signal request failed")
            return self.stop_signal

    async def select_resolution(self):
        # Don't bother selecting resolution for Auto
        if self.resolution == "Auto":
            logger.info("Resolution set to Auto.")
            return True

        logger.info(f"Selecting resolution: {self.resolution}")

        async def select():
            await self.healing_page.click(
                ".ytp-button.ytp-settings-button", "YouTube settings button"
            )
            await self.page.locator(
                ".ytp-menuitem-label:visible", has_text="Quality"
            ).click()
            options = self.page.locator(".ytp-menuitem-label:visible")
            await options.filter(has_text="Auto").first.wait_for(timeout=20_000)
            requested = options.filter(has_text=self.resolution)
            if await requested.count():
                await requested.first.click()
                logger.info(f"Resolution set to {self.resolution}.")
            else:
                await options.filter(has_text="Auto").first.click()
                logger.warning(
                    f"Resolution '{self.resolution}' not available. "
                    "Falling back to Auto."
                )

        if not await self.retry_automation_step(
            f"Selecting resolution '{self.resolution}'", select
        ):
            logger.warning(
                "Unable to select resolution '%s'. "
                "Continuing with YouTube's automatic quality.",
                self.resolution,
            )
            await self.dismiss_player_menu()
        return True

    async def dismiss_player_menu(self, log_success=True):
        """Best-effort cleanup before continuing with automatic quality."""
        try:
            await self.page.keyboard.press("Escape")
            if log_success:
                logger.info("Dismissed the YouTube player menu.")
        except Exception:
            logger.warning(
                "Could not dismiss the YouTube settings menu; "
                "playback will still be attempted.",
                exc_info=True,
            )

    async def enable_stats(self):
        async def enable():
            await self.healing_page.click(
                "#movie_player:visible",
                "visible YouTube video player",
                button="right", timeout=20_000
            )
            await self.page.locator(".ytp-menuitem:visible").filter(
                has_text="Stats for nerds"
            ).click(timeout=10_000)
            await self.healing_page.locator(
                demo_selector(
                    ".html5-video-info-panel-content.ytp-sfn-content",
                    ".html5-video-info-panel-content.ytp-sfn-content-old",
                ),
                "Stats for Nerds panel",
            ).wait_for(timeout=10_000)

        if await self.retry_automation_step("Enabling Stats for Nerds", enable):
            logger.info("Stats for nerds panel enabled.")
            return True
        logger.warning(
            "Stats for Nerds could not be enabled after retries. "
            "Playback will continue, and statistics collection will be "
            "retried during playback."
        )
        return False

    async def get_stats(self):
        elem = self.healing_page.locator(
            demo_selector(
                ".html5-video-info-panel-content.ytp-sfn-content",
                ".html5-video-info-panel-content.ytp-sfn-content-old",
            ),
            "Stats for Nerds panel",
        )
        # Selenium's WebElement.text returns the rendered, visible text.  Use
        # inner_text() here rather than text_content() so hidden/raw DOM text
        # cannot be parsed and reported as a Stats for Nerds sample.
        await elem.wait_for(state="visible", timeout=20_000)
        stats_data = await elem.inner_text(timeout=20_000)
        stats_data = stats_data.replace(" ", "")
        viewport_match = re.search(
            r"Viewport/Frames([\d+x]+)(?:\*[\d.]+)?/([\d]+)droppedof([\d]+)",
            stats_data,
        )
        current_optimal_res_match = re.search(
            r"Current/OptimalRes([\d@x]+)/([\d@x]+)", stats_data
        )
        # Initialize an empty dictionary to store extracted values
        data = {}
        # Check and assign the extracted values if matches were found
        if viewport_match:
            data["Viewport"] = viewport_match.group(1)  # e.g., '1280x720'
            data["DroppedFrames"] = viewport_match.group(2)  # e.g., '0'
            data["TotalFrames"] = viewport_match.group(3)  # e.g., '3930'

        if current_optimal_res_match:
            data["CurrentRes"] = current_optimal_res_match.group(
                1
            )  # e.g., '1920x1080@60'
            data["OptimalRes"] = current_optimal_res_match.group(
                2
            )  # e.g., '1920x1080@60'

        buffer_health_match = re.search(r"BufferHealth([\d.]+)s", stats_data)
        if buffer_health_match:
            data["BufferHealth"] = buffer_health_match.group(1)

        missing_fields = sorted(
            {"Viewport", "DroppedFrames", "TotalFrames", "CurrentRes"} - data.keys()
        )
        if missing_fields:
            logger.warning(
                "Stats for Nerds sample is missing fields: %s. " "Raw panel text: %r",
                ", ".join(missing_fields),
                stats_data[:1000],
            )

        current_time = datetime.now().strftime("%H:%M:%S")
        data["Timestamp"] = current_time

        return data

    async def get_video_duration(self):
        elem = self.healing_page.locator(
            ".ytp-time-duration", "YouTube video duration"
        )
        return await elem.text_content(timeout=10_000)

    async def enable_loop(self):
        async def enable():
            await self.healing_page.click(
                "#movie_player:visible",
                "visible YouTube video player",
                button="right",
            )
            loop_item = (
                self.page.locator(".ytp-menuitem:visible").filter(has_text="Loop").first
            )
            await loop_item.click(timeout=10_000)

        if await self.retry_automation_step("Enabling video loop", enable):
            logger.info("Video loop playback enabled.")
            return True
        logger.warning(
            "Video looping could not be enabled after retries. "
            "Continuing with the remaining automation steps."
        )
        return False

    async def full_screen(self):
        async def enter_full_screen():
            await self.healing_page.click(
                demo_selector(
                    ".ytp-fullscreen-button.ytp-button",
                    ".ytp-fullscreen-button-old.ytp-button",
                ),
                "YouTube full-screen button",
                timeout=5_000,
            )

        if not await self.retry_automation_step(
            "Entering full-screen mode", enter_full_screen
        ):
            logger.warning(
                "Failed to enter full-screen mode after retries. "
                "Continuing playback in the current window."
            )

    async def play(self):
        self.current_stage = "loading the YouTube video"
        logger.info("Stage: %s.", self.current_stage)
        if not await self.load_video():
            await self.stop()
            return False

        self.current_stage = "enabling Stats for Nerds"
        logger.info("Stage: %s.", self.current_stage)
        if not await self.enable_stats():
            logger.warning("Continuing without confirmed Stats for Nerds setup.")
        if self.duration:
            self.current_stage = "enabling video loop"
            logger.info("Stage: %s.", self.current_stage)
            if not await self.enable_loop():
                logger.warning("Continuing playback without confirmed looping.")

        self.current_stage = "selecting the video resolution"
        logger.info("Stage: %s.", self.current_stage)
        if not await self.select_resolution():
            logger.error(
                "Resolution selection failed for requested value '%s'.",
                self.resolution,
            )
            await self.stop()
            return False

        try:
            self.video_duration = await self.get_video_duration()
            logger.info("YouTube reported video duration: %s", self.video_duration)
        except Exception as error:
            self.video_duration = None
            logger.warning(
                "Unable to read the video duration: %s. Continuing playback.",
                error,
            )
        await asyncio.sleep(1)
        self.current_stage = "playing the YouTube video"
        logger.info("Stage: %s.", self.current_stage)
        logger.info(
            "Playback started: duration=%s minute(s), resolution=%s.",
            self.duration,
            self.resolution,
        )
        if not await self.start():
            logger.warning(
                "Could not confirm playback start after retries. "
                "Continuing statistics collection."
            )
        await self.full_screen()
        if self.duration:
            end_time = datetime.now() + timedelta(minutes=self.duration)
            while datetime.now() <= end_time:
                if self.check_stop_signal():
                    break
                stats = await self.get_stats()
                self.dataset.append(stats)
                self.send_stats_to_api(stats, self.device_name)
                await asyncio.sleep(1)
            stats = await self.get_stats()
            self.dataset.append(stats)
            self.send_stats_to_api(stats, self.device_name, stop=True)
        else:
            if not self.video_duration:
                logger.error(
                    "The video duration is required when --duration is not "
                    "specified; playback length cannot be determined."
                )
                return False
            time_array = self.video_duration.split(":")
            time_array = list(map(int, time_array))
            if len(time_array) == 3:
                delta = timedelta(
                    hours=time_array[0],
                    minutes=time_array[1],
                    seconds=time_array[2],
                )
            else:
                delta = timedelta(minutes=time_array[0], seconds=time_array[1])
            end_time = datetime.now() + timedelta(seconds=delta.total_seconds())
            while datetime.now() < end_time:
                if self.check_stop_signal():
                    break
                stats = await self.get_stats()
                self.dataset.append(stats)
                self.send_stats_to_api(stats, self.device_name)
                await asyncio.sleep(1)
            stats = await self.get_stats()
            self.dataset.append(stats)
            self.send_stats_to_api(stats, self.device_name, stop=True)

        logger.info("Playback finished.")
        await self.stop()
        return True

    async def start(self):
        async def start_playback():
            elem = self.healing_page.locator(
                ".ytp-play-button.ytp-button", "YouTube play button"
            )
            if (
                await elem.get_attribute("data-title-no-tooltip", timeout=10_000)
                != "Pause"
            ):
                await elem.click(timeout=10_000)

        started = await self.retry_automation_step(
            "Starting YouTube playback", start_playback
        )
        if started:
            logger.info("Playback start step completed.")
        return started

    async def stop(self):
        logger.info("Closing Chrome and browser driver.")
        if not self.healer_stopped:
            try:
                await self.healing_page.shutdown()
                self.healer_stopped = True
            except Exception:
                logger.warning("Unable to save the Playwright healer report.")
                record_debug_error("Playwright healer shutdown failed")
        logger.info("Saving Playwright trace to: %s", ARTIFACT_DIR / "trace.zip")
        try:
            await self.page.context.tracing.stop(path=str(ARTIFACT_DIR / "trace.zip"))
        except Exception:
            logger.warning(
                "Unable to save the Playwright trace; browser cleanup will " "continue."
            )
            record_debug_error("Playwright trace save failed")
        try:
            if not self.page.is_closed():
                await self.page.close()
            logger.info("Chrome and browser driver closed successfully.")
        except Exception:
            logger.warning("Unable to close the browser page cleanly.")
            record_debug_error("Browser page cleanup failed")

    def send_stats_to_api(self, stats, device_name, stop=False):
        try:
            url = f"http://{self.host}:5002/youtube_stats"
            headers = {
                "Content-Type": "application/json",
            }
            data = {
                device_name: stats,  # Device name as key, stats as value
                "stop": stop,  # Stop remains as a separate key
            }

            response = requests.post(url, json=data, headers=headers, timeout=5)
            if response.status_code == 200:
                if self.server_connection_failed:
                    logger.info("Connection to the test server recovered.")
                    self.server_connection_failed = False
            else:
                self._record_stats_upload_failure(
                    f"test server returned HTTP {response.status_code}"
                )
        except Exception:
            self._record_stats_upload_failure("test server request failed")

    def _record_stats_upload_failure(self, debug_context):
        self.stats_upload_failures += 1
        if not self.server_connection_failed:
            logger.warning(
                "Unable to send statistics to the test server. "
                "Playback will continue. Endpoint: "
                "http://%s:5002/youtube_stats. Failure: %s",
                self.host,
                debug_context,
            )
            self.server_connection_failed = True
            record_debug_error(debug_context)


async def async_main():

    parser = argparse.ArgumentParser(
        prog="youtube.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
        Youtube streaming automation
         """,
        description="""\
NAME: youtube.py
PURPOSE: This script will open youtube over browser and play it for mentioned
duration or single loop and get the reporting stats

Example:
    # for running a single loop of any url with Auto video resolution

        python3 youtube.py --url <video url>

    # for running a single loop of any url with required video quality

        python3 youtube.py --url <video url> --res <resoultion>

    # for running a video for certain amount of time

        python3 youtube.py --url <video url> --duration <duration in minuites>
    PS: If we mentioned the duration the loop option of video will be enabled
    automatically

    --res <resolution>
         144p
         240p
         360p
         480p
         720p
         1080p
    if resoultion is not there in options then video will play with Auto
    quality

    --duration <duration in minitues>
         If we mentioned the duration the loop option of video will be enabled
         automatically
         and if not then video will play only once

    --env <enviornment variable>=<enviornment value>
        If required to assign multiple envirnment variable just use
        --env key=value again for other values
        example python3 youtube.py --env python=python3 --env DISPLAY=:0
          """,
    )

    parser.add_argument(
        "--url",
        type=str,
        default="https://www.youtube.com/watch?v=4GnVDPD01as",
    )
    parser.add_argument("--res", type=str, default="Auto")
    parser.add_argument("--duration", default=0, type=int)
    parser.add_argument("--env", action="extend", nargs="+", default=[])

    parser.add_argument("--host", type=str, required=True)
    parser.add_argument("--port", type=str, default=8000)
    parser.add_argument("--device_name", type=str, required=True)

    args = parser.parse_args()

    logger.info(
        "Test started: device=%s, URL=%s, requested_resolution=%s, "
        "duration_minutes=%s, server=%s:5002.",
        args.device_name,
        args.url,
        args.res,
        args.duration,
        args.host,
    )
    logger.info("Operating system: %s.", platform.system())

    for argument in args.env:
        if "=" not in argument:
            parser.error(
                f"Invalid --env value '{argument}'. Expected format: KEY=VALUE"
            )
        key, value = argument.split("=", 1)
        if not key:
            parser.error(
                f"Invalid --env value '{argument}'. "
                "Environment variable name cannot be empty."
            )
        os.environ[key] = value

    if platform.system() == "Windows":
        adguard_path = os.path.join(
            "C:\\",
            "Program Files (x86)",
            "LANforge-Server",
            "local",
            "real_application_test",
            "youtube",
            "adguard",
        )
    elif platform.system() == "Linux":
        adguard_path = "/home/lanforge/local/real_application_test/youtube/adguard"
    elif platform.system() == "Darwin":
        adguard_path = "/Users/lanforge/local/real_application_test/youtube/adguard"
    else:
        logger.error("Unsupported operating system: %s", platform.system())
        raise Exception("Unsupported OS")

    logger.info("Using browser extension directory: %s", adguard_path)

    yt = None
    playwright = None
    context = None
    result = "FAILED"
    failed_stage = "starting Chrome"
    try:
        logger.info("Starting Playwright runtime.")
        playwright = await async_playwright().start()
        logger.info("Preparing Playwright artifact directory: %s", ARTIFACT_DIR)
        shutil.rmtree(ARTIFACT_DIR, ignore_errors=True)
        ARTIFACT_DIR.mkdir()
        logger.info("Starting Chrome.")
        context = await playwright.chromium.launch_persistent_context(
            "",
            headless=platform.system() == "Linux"
            and not Path(
                "/tmp/.X11-unix/X"
                + os.environ.get("DISPLAY", "").lstrip(":").split(".")[0]
            ).exists(),
            channel="chromium" if platform.system() == "Linux" else None,
            viewport=None,
            record_video_dir=str(demo_dir()) if demo_dir() else None,
            args=[
                f"--disable-extensions-except={adguard_path}",
                f"--load-extension={adguard_path}",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        logger.info("Chrome persistent context started successfully.")
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        logger.info("Playwright tracing started.")
        page = context.pages[0] if context.pages else await context.new_page()
        logger.info("Browser page is ready.")

        yt = YouTube(
            args.url,
            args.res,
            args.host,
            args.port,
            args.duration,
            args.device_name,
            page,
        )
        if args.duration != 0:
            yt.duration = args.duration
        if await yt.play():
            result = "STOPPED BY USER" if yt.stop_signal else "COMPLETED"
        else:
            failed_stage = yt.current_stage
    except TimeoutException as error:
        if yt is not None:
            failed_stage = yt.current_stage
        logger.error("YouTube test timed out while %s: %s", failed_stage, error)
    except Exception:
        if yt is not None:
            failed_stage = yt.current_stage
        logger.error("YouTube test failed while %s.", failed_stage)
        record_debug_error(f"YouTube test failed while {failed_stage}")
    finally:
        if result == "FAILED" and yt is not None:
            logger.info("Stopping YouTube playback and closing Chrome.")
            try:
                if not yt.page.is_closed():
                    await yt.stop()
            except Exception:
                record_debug_error("YouTube page cleanup failed")
        if context is not None:
            try:
                await context.close()
                logger.info("Chrome closed successfully.")
            except Exception:
                record_debug_error("Playwright context cleanup failed")
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                logger.warning(
                    "Chrome could not be closed completely. "
                    "Manual cleanup may be required."
                )
                record_debug_error("Chrome cleanup failed")
        logger.info("TEST RESULT: %s", result)
        if yt is not None:
            logger.info(
                "Test summary: samples=%s, statistics upload failures=%s.",
                len(yt.dataset),
                yt.stats_upload_failures,
            )
        upload_test_log(
            args.host,
            args.device_name,
        )

    return 0 if result != "FAILED" else 1


def main():
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
