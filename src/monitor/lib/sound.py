"""Simple cross-platform sound/notification helpers.

This module provides a tiny utility to play an OS-level sound to notify the user
that a task has completed.

The helper uses platform-native mechanisms (winsound on Windows; afplay/osascript
on macOS; canberra-gtk-play/paplay/aplay on Linux).
"""

from __future__ import annotations

import logging
import sys
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def _play_windows_sound() -> bool:
    """Attempt to play an audible sound on Windows using OS sound aliases.

    Tries winsound.PlaySound with SND_ALIAS for common system aliases, and
    falls back to a simple winsound.Beep if PlaySound fails or aliases are
    unavailable.
    """
    try:
        import winsound  # type: ignore

        aliases = (
            "SystemNotification",
            "SystemAsterisk",
            "SystemExclamation",
            "SystemHand",
        )
        for alias in aliases:
            try:
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
                logger.debug("_play_windows_sound: played alias %s", alias)
                return True
            except Exception as exc:
                logger.debug("_play_windows_sound: alias %s failed: %s", alias, exc)

        try:
            winsound.Beep(800, 200)
            logger.debug("_play_windows_sound: used winsound.Beep as fallback")
            return True
        except Exception as exc:
            logger.debug("_play_windows_sound: winsound.Beep failed: %s", exc)
            return False
    except Exception as exc:
        logger.debug("_play_windows_sound: winsound import or use failed: %s", exc)
        return False


def _play_macos_sound() -> bool:
    """Attempt to play an audible sound on macOS.

    Prefers afplay with a short duration on a system sound file. Falls back to
    AppleScript 'beep' via osascript if afplay is unavailable.
    """
    # Candidate system sounds commonly present on macOS
    candidates = [
        "/System/Library/Sounds/Ping.aiff",
        "/System/Library/Sounds/Glass.aiff",
        "/System/Library/Sounds/Pop.aiff",
        "/System/Library/Sounds/Blow.aiff",
    ]

    afplay = shutil.which("afplay")
    if afplay:
        for sound in candidates:
            if os.path.exists(sound):
                try:
                    # Limit playback time to keep it snappy
                    result = subprocess.run(
                        [afplay, "-t", "0.5", sound],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=3,
                    )
                    if result.returncode == 0:
                        logger.debug("_play_macos_sound: played %s via afplay", sound)
                        return True
                    else:
                        logger.debug(
                            "_play_macos_sound: afplay returned %s for %s",
                            result.returncode,
                            sound,
                        )
                except Exception as exc:
                    logger.debug("_play_macos_sound: afplay failed for %s: %s", sound, exc)

    # Fallback to osascript beep
    osascript = shutil.which("osascript")
    if osascript:
        try:
            result = subprocess.run(
                [osascript, "-e", "beep 1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
            )
            if result.returncode == 0:
                logger.debug("_play_macos_sound: used osascript beep")
                return True
            logger.debug("_play_macos_sound: osascript returned %s", result.returncode)
        except Exception as exc:
            logger.debug("_play_macos_sound: osascript beep failed: %s", exc)

    return False


def _play_linux_sound() -> bool:
    """Attempt to play an audible sound on Linux/Unix-like systems.

    Tries canberra-gtk-play first. Falls back to paplay/aplay with common
    system sound files.
    """
    # 1) canberra-gtk-play with a commonly available icon
    canberra = shutil.which("canberra-gtk-play")
    if canberra:
        icons = ("dialog-information", "bell", "complete", "system-ready", "message-new-instant")
        for icon in icons:
            try:
                result = subprocess.run(
                    [canberra, "-q", "-i", icon],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=3,
                )
                if result.returncode == 0:
                    logger.debug("_play_linux_sound: played icon '%s' via canberra-gtk-play", icon)
                    return True
                logger.debug(
                    "_play_linux_sound: canberra-gtk-play returned %s for icon '%s'",
                    result.returncode,
                    icon,
                )
            except Exception as exc:
                logger.debug(
                    "_play_linux_sound: canberra-gtk-play failed for icon '%s': %s",
                    icon,
                    exc,
                )

    # 2) paplay with common sound files
    paplay = shutil.which("paplay")
    if paplay:
        candidate_files = [
            "/usr/share/sounds/freedesktop/stereo/complete.oga",
            "/usr/share/sounds/freedesktop/stereo/bell.oga",
            "/usr/share/sounds/freedesktop/stereo/message.oga",
            "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
            "/usr/share/sounds/ubuntu/stereo/bell.ogg",
        ]
        for sound in candidate_files:
            if os.path.exists(sound):
                try:
                    result = subprocess.run(
                        [paplay, sound],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=3,
                    )
                    if result.returncode == 0:
                        logger.debug("_play_linux_sound: played %s via paplay", sound)
                        return True
                    logger.debug(
                        "_play_linux_sound: paplay returned %s for %s",
                        result.returncode,
                        sound,
                    )
                except Exception as exc:
                    logger.debug("_play_linux_sound: paplay failed for %s: %s", sound, exc)

    # 3) aplay with common sound files (ALSA)
    aplay = shutil.which("aplay")
    if aplay:
        candidate_files = [
            "/usr/share/sounds/alsa/Front_Center.wav",
            "/usr/share/sounds/alsa/Noise.wav",
        ]
        for sound in candidate_files:
            if os.path.exists(sound):
                try:
                    result = subprocess.run(
                        [aplay, "-q", sound],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=3,
                    )
                    if result.returncode == 0:
                        logger.debug("_play_linux_sound: played %s via aplay", sound)
                        return True
                    logger.debug(
                        "_play_linux_sound: aplay returned %s for %s",
                        result.returncode,
                        sound,
                    )
                except Exception as exc:
                    logger.debug("_play_linux_sound: aplay failed for %s: %s", sound, exc)

    return False


def _play_audible_fallback() -> bool:
    """Dispatch to an OS-specific audible playback helper, with ASCII BEL fallback."""
    try:
        if sys.platform.startswith("win"):
            ok = _play_windows_sound()
        elif sys.platform == "darwin":
            ok = _play_macos_sound()
        else:
            ok = _play_linux_sound()
        if ok:
            logger.debug("_play_audible_fallback: OS-specific sound played successfully")
            return True
        else:
            logger.debug("_play_audible_fallback: OS-specific sound unavailable or failed, using ASCII BEL fallback")
            print('\a', end='', flush=True)
            return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("_play_audible_fallback: unexpected error: %s, using ASCII BEL fallback", exc)
        try:
            print('\a', end='', flush=True)
        except Exception:
            pass
        return True


def ring_bell(enabled: bool = True) -> bool:
    """Play an OS-level sound to notify the user.

    This simplified helper selects an OS-specific mechanism and attempts to
    play an audible system sound. It does not use prompt_toolkit and does not
    print the ASCII BEL directly, except as a final fallback.

    Args:
        enabled (bool): When False, do nothing and return False.

    Returns:
        bool: True if an OS-specific playback method or ASCII BEL fallback
            succeeded; False if disabled.
    """
    if not enabled:
        logger.debug("ring_bell: disabled -> no-op")
        return False

    try:
        ok = _play_audible_fallback()
        if ok:
            logger.debug("ring_bell: OS-specific sound or ASCII BEL fallback succeeded")
        else:
            logger.debug("ring_bell: All playback methods failed")
        return ok
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("ring_bell: error while attempting playback: %s", exc)
        return False
