# pushraker-kiln: pushraker's Discord messages as status cards, the
# FlashForgeUI-style cards notify-plus-kiln sent for kiln-notify (ported
# from FLSUN_pushraker's component/flsun_pushraker.py).
#
# pushraker posts each notification to Discord as one embed: its title, its
# text and a colour. With this component loaded ([pushraker_cards] in the
# plugin's moonraker.conf), the embed also gets the card layout:
#
#   Status | Extruder Temp | Bed Temp
#   Progress ██████░░░░ 60%                      (during a print)
#   Print Time | ETA | Layer
#   File
#   footer: the printer's name, and the time it was sent
#
# coloured by the printer's state (green printing or complete, orange
# paused, blue ready), and red for pushraker's failure notifications. The
# snapshot stays inside the embed, below the fields.
#
# It changes no pushraker file: at startup it wraps pushraker.discord's
# _payload(), which both Discord senders (channel webhook and direct
# message) call for every message, and the pushraker component's
# _attempts(), to learn which notification a message is (pushraker sends
# "complete" and "cancelled" from the print-end hooks, while Klipper still
# says printing). If a pushraker release changes either, the card falls
# back to Klipper's state, or is skipped and pushraker's own embed goes out
# unchanged. [pushraker_cards] discord_cards: False turns it off.
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations

import asyncio
import datetime
import functools
import inspect
import logging
import threading
from typing import Any, Dict, List, Optional

LOG = "[pushraker_cards]"
# Discord's limits
FIELD_VALUE_MAX = 1024
FIELDS_MAX = 25
# How long a send may wait for the printer's state
QUERY_TIMEOUT = 3.

# FlashForgeUI-Electron's labels and colours (as notify-plus-kiln's cards)
STATUS = {
    "printing": ("🖨️ Printing", 0x00ff00),
    "paused": ("⏸️ Paused", 0xf39c12),
    "complete": ("✅ Completed", 0x00ff00),
    "cancelled": ("🚫 Cancelled", 0x95a5a6),
    "error": ("❌ Error", 0xb02626),
    "standby": ("✅ Ready", 0x3498db),
}
FAILURE_COLOUR = 0xb02626
# pushraker's notifications that mean a state Klipper may not show yet
ROW_STATE = {"complete": "complete", "cancelled": "cancelled",
             "error": "error", "shutdown": "error", "paused": "paused",
             "file_pause": "paused"}
QUERY = {
    "print_stats": None,
    "display_status": ["progress"],
    "virtual_sdcard": ["progress"],
    "extruder": ["temperature", "target"],
    "heater_bed": ["temperature", "target"],
    "gcode_move": ["gcode_position"],
}


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    return "%dh %dm" % (seconds // 3600, seconds % 3600 // 60)


def _escape(text: str) -> str:
    for c in "\\*_~`|>[]#":
        text = text.replace(c, "\\" + c)
    return text


class PushrakerCards:
    def __init__(self, config: Any) -> None:
        self.server = config.get_server()
        self.cards = config.getboolean("discord_cards", True)
        self.loop = self.server.get_event_loop().aioloop
        self.loop_thread = threading.get_ident()
        self._original = None
        self._discord = None
        # Title of a message being sent -> pushraker's notification id
        self._rows: Dict[str, str] = {}
        if self.cards:
            self._wrap()

    async def component_init(self) -> None:
        # Every component is loaded by now, pushraker's too
        if self._original is not None:
            self._wrap_attempts()

    def _wrap_attempts(self) -> None:
        try:
            push = self.server.lookup_component("pushraker")
        except Exception:
            logging.info(f"{LOG} pushraker component not loaded")
            return
        original = getattr(push, "_attempts", None)
        if original is None or getattr(original, "_kiln_card", False):
            return
        params = list(inspect.signature(original).parameters)
        if params[:5] != ["rid", "dest", "t", "title", "body"]:
            logging.info(f"{LOG} pushraker's _attempts changed ({params}); "
                         "cards follow Klipper's state only")
            return
        rows = self._rows

        @functools.wraps(original)
        async def attempts(rid: str, dest: Any, t: Any, title: str,
                           *args: Any, **kwargs: Any) -> Any:
            rows[title] = rid
            try:
                return await original(rid, dest, t, title, *args, **kwargs)
            finally:
                if rows.get(title) == rid:
                    rows.pop(title, None)

        attempts._kiln_card = True  # type: ignore[attr-defined]
        push._attempts = attempts
        logging.info(f"{LOG} cards know which notification they are")

    # ---- the wrapper -------------------------------------------------------

    def _wrap(self) -> None:
        try:
            from pushraker import discord  # type: ignore
        except Exception as e:
            logging.warning(f"{LOG} pushraker not found ({e}); Discord "
                            "cards are off")
            return
        original = getattr(discord, "_payload", None)
        if original is None or getattr(original, "_kiln_card", False):
            if original is None:
                logging.warning(f"{LOG} this pushraker has no "
                                "discord._payload; Discord cards are off")
            return
        params = list(inspect.signature(original).parameters)
        if params[:4] != ["body", "title", "notify_type", "qsd"]:
            logging.warning(f"{LOG} pushraker's discord._payload changed "
                            f"({params}); Discord cards are off")
            return

        @functools.wraps(original)
        def payload(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            result = original(*args, **kwargs)
            try:
                notify_type = (args[2] if len(args) > 2
                               else kwargs.get("notify_type"))
                title = args[1] if len(args) > 1 else kwargs.get("title")
                embeds = result.get("embeds") or []
                if embeds:
                    self._card(embeds[0], str(notify_type),
                               self._row(str(title or "")))
            except Exception:
                logging.exception(f"{LOG} Discord card failed; sending "
                                  "pushraker's own embed")
            return result

        payload._kiln_card = True  # type: ignore[attr-defined]
        discord._payload = payload
        self._original = original
        self._discord = discord
        logging.info(f"{LOG} Discord messages use the status cards")

    def _row(self, title: str) -> Optional[str]:
        """The notification a title belongs to; Apprise may have shortened
        the title on the way."""
        if not title:
            return None
        rows = dict(self._rows)
        if title in rows:
            return rows[title]
        for full, rid in rows.items():
            if full.startswith(title) or title.startswith(full):
                return rid
        return None

    def close(self) -> None:
        if self._discord is not None and self._original is not None:
            self._discord._payload = self._original

    # ---- the card ----------------------------------------------------------

    def _state(self) -> Dict[str, Any]:
        """The printer's state and the file's metadata, read on Moonraker's
        event loop. Apprise sends from a worker thread; on the loop itself
        (never expected) waiting would deadlock, so nothing is read."""
        if threading.get_ident() == self.loop_thread:
            return {}
        future = asyncio.run_coroutine_threadsafe(self._query(), self.loop)
        try:
            return future.result(QUERY_TIMEOUT)
        except Exception:
            future.cancel()
            logging.info(f"{LOG} no printer state for the Discord card")
            return {}

    async def _query(self) -> Dict[str, Any]:
        kapis = self.server.lookup_component("klippy_apis")
        status = await kapis.query_objects(QUERY, default={})
        filename = (status.get("print_stats") or {}).get("filename") or ""
        meta: Dict[str, Any] = {}
        if filename:
            try:
                fm = self.server.lookup_component("file_manager")
                meta = dict(fm.get_file_metadata(filename) or {})
            except Exception:
                pass
        name = ""
        try:
            name = str(getattr(self.server.lookup_component("pushraker"),
                               "name", "") or "")
        except Exception:
            pass
        return {"status": status, "meta": meta, "name": name}

    def _card(self, embed: Dict[str, Any], notify_type: str,
              rid: Optional[str]) -> None:
        got = self._state()
        status = got.get("status") or {}
        meta = got.get("meta") or {}
        stats = status.get("print_stats") or {}
        state = ROW_STATE.get(rid or "") or str(stats.get("state") or "")
        label, colour = STATUS.get(state, ("", 0x95a5a6))

        fields: List[Dict[str, Any]] = []
        if label:
            fields.append({"name": "Status", "value": label, "inline": True})
        for key, title in (("extruder", "Extruder Temp"),
                           ("heater_bed", "Bed Temp")):
            heater = status.get(key)
            if heater:
                fields.append({
                    "name": title,
                    "value": "%.2f°C / %.2f°C" % (
                        float(heater.get("temperature") or 0.),
                        float(heater.get("target") or 0.)),
                    "inline": True,
                })
        filename = str(stats.get("filename") or "")
        if filename and state in ("printing", "paused"):
            fields += self._job_fields(stats, status, meta)
        elif filename and state in ("complete", "cancelled", "error"):
            total = float(stats.get("total_duration") or 0.)
            if total:
                fields.append({"name": "Total Time",
                               "value": _duration(total), "inline": True})
        if filename and state in STATUS and state != "standby":
            fields.append({"name": "File",
                           "value": _escape(filename)[:FIELD_VALUE_MAX],
                           "inline": False})
            # The text's own file-name line says the same as the field
            embed["description"] = self._drop_line(
                embed.get("description", ""), filename)

        if fields:
            embed["fields"] = fields[:FIELDS_MAX]
        embed["color"] = (FAILURE_COLOUR if notify_type == "failure"
                          else colour if label else embed.get("color"))
        name = got.get("name") or ""
        if name:
            embed["footer"] = {"text": name}
        embed["timestamp"] = datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if not embed.get("description"):
            embed.pop("description", None)

    @staticmethod
    def _drop_line(text: str, filename: str) -> str:
        names = {filename, _escape(filename),
                 filename.rsplit("/", 1)[-1],
                 _escape(filename.rsplit("/", 1)[-1])}
        lines = [ln for ln in str(text or "").split("\n")
                 if ln.strip() not in names]
        return "\n".join(lines).strip("\n")

    def _job_fields(self, stats: Dict[str, Any], status: Dict[str, Any],
                    meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        # M73 progress from the slicer is time based; the file position is
        # the fallback.
        progress = float(
            (status.get("display_status") or {}).get("progress") or
            (status.get("virtual_sdcard") or {}).get("progress") or 0.)
        progress = min(max(progress, 0.), 1.)
        filled = int(progress * 100 // 10)
        fields = [{
            "name": "Progress",
            "value": "%s %d%%" % ("█" * filled + "░" * (10 - filled),
                                  round(progress * 100)),
            "inline": False,
        }]
        elapsed = float(stats.get("print_duration") or 0.)
        fields.append({"name": "Print Time", "value": _duration(elapsed),
                       "inline": True})
        estimate = float(meta.get("estimated_time") or 0.)
        remaining: Optional[float] = None
        if estimate > 0:
            remaining = estimate * (1. - progress)
        elif progress > .01:
            remaining = elapsed / progress - elapsed
        if remaining is not None:
            # Discord shows <t:...> in each reader's own time zone
            eta = int(datetime.datetime.now(datetime.timezone.utc)
                      .timestamp() + remaining)
            fields.append({"name": "ETA", "value": f"<t:{eta}:t>",
                           "inline": True})
        layer = self._layer(stats, status, meta)
        if layer is not None:
            fields.append({"name": "Layer", "value": "%d / %d" % layer,
                           "inline": True})
        return fields

    @staticmethod
    def _layer(stats: Dict[str, Any], status: Dict[str, Any],
               meta: Dict[str, Any]) -> Optional[tuple]:
        info = stats.get("info") or {}
        if info.get("current_layer") and info.get("total_layer"):
            return int(info["current_layer"]), int(info["total_layer"])
        total = int(meta.get("layer_count") or 0)
        height = float(meta.get("layer_height") or 0.)
        first = float(meta.get("first_layer_height") or height)
        pos = (status.get("gcode_move") or {}).get("gcode_position") or []
        if total <= 0 or height <= 0. or len(pos) < 3:
            return None
        layer = int(round((float(pos[2]) - first) / height)) + 1
        return min(max(layer, 1), total), total


def load_component(config: Any) -> PushrakerCards:
    return PushrakerCards(config)
