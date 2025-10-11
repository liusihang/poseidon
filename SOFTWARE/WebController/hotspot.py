import logging
import shutil
import subprocess
import threading
from typing import Optional

logger = logging.getLogger("poseidon.hotspot")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.debug("Command failed (%s): %s", result.returncode, " ".join(cmd))
        if result.stdout:
            logger.debug("stdout: %s", result.stdout.strip())
        if result.stderr:
            logger.debug("stderr: %s", result.stderr.strip())
    else:
        logger.debug("Command ok: %s", " ".join(cmd))
    return result


def _probe_wifi_iface() -> Optional[str]:
    nmcli = shutil.which("nmcli")
    if not nmcli:
        logger.warning("nmcli not available; skip hotspot setup")
        return None
    result = _run([nmcli, "-t", "-f", "DEVICE,TYPE", "device", "status"])
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.strip().split(":")
        if len(parts) != 2:
            continue
        device, dev_type = parts
        if dev_type == "wifi":
            return device
    logger.warning("No Wi-Fi interface found via nmcli")
    return None


def _ensure_nmcli_hotspot(iface: str, ssid: str) -> None:
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return

    connection_name = f"{ssid}_AP"

    # Check whether the hotspot connection already exists.
    result = _run([nmcli, "-t", "-f", "NAME", "connection", "show"])
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.strip() == connection_name:
                logger.info("Hotspot connection %s already present", connection_name)
                break
        else:
            # create connection
            logger.info("Creating nmcli hotspot connection %s", connection_name)
            create_cmd = [
                nmcli,
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                iface,
                "con-name",
                connection_name,
                "autoconnect",
                "yes",
                "ssid",
                ssid,
            ]
            result = _run(create_cmd)
            if result.returncode != 0:
                logger.error("Failed to create hotspot connection via nmcli")
                return

    # Configure AP settings (open network, shared IPv4, AP mode).
    modify_cmd = [
        nmcli,
        "connection",
        "modify",
        connection_name,
        "802-11-wireless.mode",
        "ap",
        "802-11-wireless.band",
        "bg",
        "ipv4.method",
        "shared",
        "ipv6.method",
        "ignore",
        "wifi-sec.key-mgmt",
        "none",
    ]
    _run(modify_cmd)

    logger.info("Activating hotspot %s on %s", ssid, iface)
    up_cmd = [nmcli, "connection", "up", connection_name, "ifname", iface]
    result = _run(up_cmd)
    if result.returncode == 0:
        logger.info("Hotspot %s started on interface %s", ssid, iface)
    else:
        logger.error("Unable to bring up hotspot; check permissions and Wi-Fi drivers")


def ensure_hotspot(ssid: str, password: str = "") -> None:
    """
    Ensure a Wi-Fi hotspot is active using NetworkManager (nmcli).
    Password is ignored (open network) by design for this project.
    """
    if password:
        logger.warning("Password parameter ignored; hotspot is configured as open")

    iface = _probe_wifi_iface()
    if not iface:
        return
    _ensure_nmcli_hotspot(iface, ssid)


def ensure_hotspot_async(ssid: str, password: str = "") -> None:
    def worker():
        try:
            ensure_hotspot(ssid, password)
        except Exception:  # pragma: no cover
            logger.exception("Unexpected error while setting up hotspot")

    t = threading.Thread(target=worker, name="poseidon-hotspot", daemon=True)
    t.start()

