"""Live per-beat heart rate capture over Bluetooth LE.

WHOOP's public Developer API (see `thaalam.whoop_client`) never exposes
raw/second-wise heart rate or HRV -- every endpoint returns aggregates
(once per cycle/recovery/workout). There is, however, an official way to
get real beat-by-beat data: WHOOP's "HR Broadcast" feature turns the
strap into a standard Bluetooth GATT Heart Rate Service (0x180D)
peripheral, the same profile any chest strap uses. This module connects
to that broadcast directly -- no WHOOP account, OAuth token, or cloud
round-trip involved -- and logs each notification (instantaneous BPM
plus any RR-intervals) to DuckDB.

Enable the broadcast first: WHOOP app -> Settings -> Strap Settings ->
HR Broadcast. This only streams live data while broadcasting is on and
the strap is in Bluetooth range; it cannot backfill history, so it's a
separate capture step from `thaalam.sync`'s historical API sync.

RR-intervals are the raw beat-to-beat timings HRV (rmssd) is computed
from, but WHOOP's own recovery HRV score is a separate proprietary
calculation -- this module does not attempt to reproduce it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from thaalam import db

logger = logging.getLogger(__name__)

HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# Flush buffered samples to DuckDB this often, so an interrupt/crash loses at
# most a few seconds of data instead of the whole session.
FLUSH_INTERVAL_SECONDS = 5.0


def _parse_hr_measurement(data: bytes) -> dict[str, Any]:
    """Decode a Bluetooth SIG Heart Rate Measurement characteristic payload.

    Format (org.bluetooth.characteristic.heart_rate_measurement): a flags
    byte, then the HR value (uint8 or uint16, per a flag bit), then an
    optional energy-expended uint16, then zero or more RR-interval uint16
    values (each in units of 1/1024 second).
    """
    flags = data[0]
    offset = 1

    hr_format_uint16 = bool(flags & 0x01)
    sensor_contact_bits = (flags >> 1) & 0x03
    energy_expended_present = bool(flags & 0x08)
    rr_present = bool(flags & 0x10)

    if hr_format_uint16:
        heart_rate = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2
    else:
        heart_rate = data[offset]
        offset += 1

    # Sensor contact bits: 00/01 = feature not supported by this sensor,
    # 10 = supported but not currently detected, 11 = supported and detected.
    sensor_contact = sensor_contact_bits == 0b11 if sensor_contact_bits in (0b10, 0b11) else None

    energy_expended = None
    if energy_expended_present:
        energy_expended = int.from_bytes(data[offset : offset + 2], "little")
        offset += 2

    rr_intervals_ms: list[float] = []
    if rr_present:
        while offset + 2 <= len(data):
            raw_rr = int.from_bytes(data[offset : offset + 2], "little")
            rr_intervals_ms.append(round(raw_rr / 1024 * 1000, 2))
            offset += 2

    return {
        "heart_rate": heart_rate,
        "sensor_contact": sensor_contact,
        "energy_expended": energy_expended,
        "rr_intervals_ms": rr_intervals_ms,
    }


async def _find_device(name_filter: str | None, scan_timeout: float) -> BLEDevice:
    """Scan for a nearby BLE device advertising the standard Heart Rate Service."""
    logger.info("Scanning for a Bluetooth Heart Rate Service broadcaster (%.0fs)...", scan_timeout)

    def _matches(device: BLEDevice, advertisement_data: Any) -> bool:
        service_uuids = [u.lower() for u in (advertisement_data.service_uuids or [])]
        if HEART_RATE_SERVICE_UUID not in service_uuids:
            return False
        if name_filter and (not device.name or name_filter.lower() not in device.name.lower()):
            return False
        return True

    device = await BleakScanner.find_device_by_filter(_matches, timeout=scan_timeout)
    if device is None:
        raise RuntimeError(
            "No Bluetooth device advertising the Heart Rate Service was found. "
            "Make sure HR Broadcast is turned on in the WHOOP app (Settings -> "
            "Strap Settings -> HR Broadcast), the strap is nearby, and this "
            "computer's Bluetooth is on."
        )
    logger.info("Found broadcasting device: %s (%s)", device.name or "unknown", device.address)
    return device


async def run_live_capture(
    *,
    name_filter: str | None = None,
    address: str | None = None,
    scan_timeout: float = 10.0,
    duration: float | None = None,
    db_path: str | Path | None = None,
    on_sample: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Connect to a broadcasting WHOOP strap and log live samples to DuckDB.

    Requires HR Broadcast to already be turned on in the WHOOP app. Runs
    until `duration` seconds elapse, or indefinitely (until Ctrl+C) if
    `duration` is None. `on_sample`, if given, is called with each parsed
    sample dict as it arrives (e.g. for a live printout).

    Returns the session_id used to group this run's rows in
    `hr_broadcast_samples`.
    """
    con = db.get_connection(db_path) if db_path is not None else db.get_connection()
    session_id = uuid.uuid4().hex
    buffer: list[dict[str, Any]] = []
    sample_count = 0
    last_flush = time.monotonic()

    def _flush() -> None:
        nonlocal buffer, last_flush
        if buffer:
            db.insert_hr_broadcast_samples(con, buffer)
            buffer = []
        last_flush = time.monotonic()

    def _on_notify(_characteristic: Any, data: bytearray) -> None:
        nonlocal sample_count
        parsed = _parse_hr_measurement(bytes(data))
        sample = {
            "session_id": session_id,
            "recorded_at": datetime.now(timezone.utc),
            "heart_rate": parsed["heart_rate"],
            "rr_intervals_ms": parsed["rr_intervals_ms"],
            "sensor_contact": parsed["sensor_contact"],
            "energy_expended": parsed["energy_expended"],
        }
        buffer.append(sample)
        sample_count += 1
        if on_sample is not None:
            on_sample(sample)
        if time.monotonic() - last_flush >= FLUSH_INTERVAL_SECONDS:
            _flush()

    try:
        target = address if address else await _find_device(name_filter, scan_timeout)

        async with BleakClient(target) as client:
            logger.info("Connected; subscribing to live heart rate notifications...")
            await client.start_notify(HEART_RATE_MEASUREMENT_CHAR_UUID, _on_notify)
            logger.info("Capturing live heart rate -- press Ctrl+C to stop.")

            started_at = time.monotonic()
            try:
                while True:
                    await asyncio.sleep(1.0)
                    if duration is not None and time.monotonic() - started_at >= duration:
                        break
            except KeyboardInterrupt:
                logger.info("Stopping capture (Ctrl+C)...")
            finally:
                await client.stop_notify(HEART_RATE_MEASUREMENT_CHAR_UUID)
    finally:
        _flush()
        logger.info("Session %s complete -- %d sample(s) captured.", session_id, sample_count)
        con.close()

    return session_id
