# pushraker-kiln: call pushraker's print hooks from Kiln's own macros
#
# pushraker takes its print-end and cancel snapshots when _PRINT_END_NTFY
# and _CANCEL_PRINT_NTFY run, which must happen before the printer parks.
# Kiln OS defines PRINT_END and CANCEL_PRINT in its read-only ad5x.cfg, and
# a [gcode_macro PRINT_END] in a plugin would be merged into Kiln's section
# (same name) rather than wrap it. So this module wraps the commands
# instead: once Klipper is ready, each command named in `wrap` first runs
# its hook macro, then the original command. A hook never stops the
# original from running (print end switches the heaters off).
#
# [pushraker_hooks]
# wrap: PRINT_END=_PRINT_END_NTFY, CANCEL_PRINT=_CANCEL_PRINT_NTFY
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging

DEFAULT_WRAP = "PRINT_END=_PRINT_END_NTFY, CANCEL_PRINT=_CANCEL_PRINT_NTFY"


class PushrakerHooks:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.wrap = []
        for item in config.get("wrap", DEFAULT_WRAP).split(","):
            item = item.strip()
            if not item:
                continue
            cmd, sep, hook = item.partition("=")
            if not sep or not cmd.strip() or not hook.strip():
                raise config.error(
                    "[pushraker_hooks] wrap: expected COMMAND=HOOK, got '%s'"
                    % (item,))
            self.wrap.append((cmd.strip().upper(), hook.strip().upper()))
        self.wrapped = []
        self.printer.register_event_handler("klippy:ready", self._ready)

    def _ready(self):
        gcode = self.printer.lookup_object("gcode")
        for cmd, hook in self.wrap:
            if self.printer.lookup_object("gcode_macro " + hook, None) is None:
                logging.warning("pushraker_hooks: no %s macro; %s left as is",
                                hook, cmd)
                continue
            desc = gcode.gcode_help.get(cmd)
            old = gcode.register_command(cmd, None)
            if old is None:
                logging.warning("pushraker_hooks: no %s command to wrap", cmd)
                continue
            gcode.register_command(cmd, self._make(gcode, cmd, hook, old),
                                   desc=desc)
            self.wrapped.append(cmd)
        logging.info("pushraker_hooks: wrapped %s",
                     ", ".join(self.wrapped) or "nothing")

    def _make(self, gcode, cmd, hook, old):
        def handler(gcmd):
            try:
                gcode.run_script_from_command(hook)
            except Exception as e:
                # "never fails": the print end must still run
                logging.exception("pushraker_hooks: %s before %s", hook, cmd)
                gcmd.respond_info("pushraker: %s failed (%s); %s continues"
                                  % (hook, e, cmd))
            old(gcmd)
        return handler

    def get_status(self, eventtime):
        return {"wrapped": list(self.wrapped)}


def load_config(config):
    return PushrakerHooks(config)
