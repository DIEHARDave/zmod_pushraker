#!/usr/bin/env python3
"""Offline checks for zmod_pushraker: python test_zmod_pushraker.py

Needs what Zmod's Moonraker environment has:
pip install apprise requests jinja2 pillow

- zmod_pushraker.cfg includes the vendored macro file; _NOTIFY TYPE=end
  runs the print-end hook; _PUSHRAKER_CANCEL fires once per cancel
  (rendered with Jinja2, as Klipper does)
- klipper/pushraker_hooks.py wraps CANCEL_PRINT (stand-in Klipper)
- moonraker/pushraker.py finds the package; the Discord cards on
  pushraker's real discord._payload
- the settings page fix from tools/vendor.py is in place
- web.sh adds the page; install.sh / uninstall.sh are executable in git
  and handle the same parts
"""

import configparser
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "python")
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def macros(path):
    with open(path, encoding="utf-8") as f:
        return re.findall(r"^\[gcode_macro (\S+)\]", f.read(), re.M)


cfg_path = os.path.join(HERE, "zmod_pushraker.cfg")
with open(cfg_path, encoding="utf-8") as f:
    cfg_text = f.read()
inc = re.findall(r"^\[include (\S+)\]", cfg_text, re.M)
check(len(inc) == 1, "zmod_pushraker.cfg includes one file")
inc_path = os.path.join(HERE, inc[0])
check(os.path.isfile(inc_path), f"included {inc[0]} exists")
hooks = macros(inc_path)
for h in ("_PRINT_END_NTFY", "_CANCEL_PRINT_NTFY", "_NTFY_HOOKS"):
    check(h in hooks, f"vendored macros define {h}")
check(not re.search(r"^\[gcode_macro (END_PRINT|CANCEL_PRINT)\]", cfg_text,
                    re.M), "doesn't redefine Zmod's END_PRINT/CANCEL_PRINT")

cp = configparser.RawConfigParser(strict=False)
cp.read_string(cfg_text.replace("[include ", "[x_include "))
check(cp.has_section("pushraker_hooks"), "has [pushraker_hooks]")

# The macros, rendered the way Klipper does (Jinja2)
import jinja2  # noqa: E402

env = jinja2.Environment("{%", "%}", "{", "}")


def render(name, params=None, printer=None):
    src = cp.get(f"gcode_macro {name}", "gcode")
    out = env.from_string(src).render(params=params or {},
                                      printer=printer or {})
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


check(render("_NOTIFY", {"TYPE": "end", "MSG": "x"}) == ["_PRINT_END_NTFY"],
      "_NOTIFY TYPE=end runs the print-end hook")
check(render("_NOTIFY", {"TYPE": "filament"}) == [] and render("_NOTIFY") == [],
      "other _NOTIFY types do nothing")


class P(dict):
    """printer: Klipper's lookup object (in, [], attribute access)."""
    def __getattr__(self, k):
        return self[k]


def printer(state, cancel_send=None):
    p = P(print_stats=P(state=state))
    if cancel_send is not None:
        p["gcode_macro _CANCEL_PRINT"] = P(cancel_send=cancel_send)
    return p


check(render("_PUSHRAKER_CANCEL", printer=printer("printing", 0))
      == ["_CANCEL_PRINT_NTFY"], "cancel hook on the first CANCEL_PRINT")
check(render("_PUSHRAKER_CANCEL", printer=printer("printing", 1)) == [],
      "no cancel hook on the native screen's second CANCEL_PRINT")
check(render("_PUSHRAKER_CANCEL", printer=printer("paused", 0))
      == ["_CANCEL_PRINT_NTFY"], "cancel hook when paused")
check(render("_PUSHRAKER_CANCEL", printer=printer("standby", 0)) == [],
      "no cancel hook without a print")
check(render("_PUSHRAKER_CANCEL", printer=printer("printing"))
      == ["_CANCEL_PRINT_NTFY"], "cancel hook without Zmod's _CANCEL_PRINT")


# klipper/pushraker_hooks.py against a stand-in Klipper
sys.path.insert(0, os.path.join(HERE, "klipper"))
import pushraker_hooks  # noqa: E402


class FakeConfigError(Exception):
    pass


class FakeGCmd:
    def __init__(self, line):
        self.line = line
        self.info = []

    def respond_info(self, msg):
        self.info.append(msg)


class FakeGCode:
    def __init__(self, log, fail=()):
        self.log, self.fail = log, fail
        self.handlers = {}
        self.gcode_help = {}

    def register_command(self, cmd, func, when_not_ready=False, desc=None):
        if func is None:
            return self.handlers.pop(cmd, None)
        assert cmd not in self.handlers, cmd
        self.handlers[cmd] = func
        if desc is not None:
            self.gcode_help[cmd] = desc

    def run_script_from_command(self, script):
        self.log.append(script)
        if script in self.fail:
            raise RuntimeError("boom")


class FakePrinter:
    def __init__(self, gcode, macros):
        self.gcode, self.macros, self.events = gcode, macros, {}

    def register_event_handler(self, ev, cb):
        self.events[ev] = cb

    def lookup_object(self, name, default=Exception):
        if name == "gcode":
            return self.gcode
        if name.startswith("gcode_macro ") and name[12:] in self.macros:
            return object()
        if default is Exception:
            raise KeyError(name)
        return default


class FakeConfig:
    error = FakeConfigError

    def __init__(self, printer, wrap):
        self.printer, self.wrap = printer, wrap

    def get_printer(self):
        return self.printer

    def get(self, key, default=None):
        return self.wrap if key == "wrap" and self.wrap else default


def setup(fail=(), macros=("_PUSHRAKER_CANCEL",)):
    log = []
    gc = FakeGCode(log, fail)
    for cmd in ("PRINT_END", "CANCEL_PRINT"):
        gc.register_command(cmd, lambda g, c=cmd: log.append(c),
                            desc=cmd.lower())
    pr = FakePrinter(gc, macros)
    obj = pushraker_hooks.load_config(
        FakeConfig(pr, cp.get("pushraker_hooks", "wrap")))
    pr.events["klippy:ready"]()
    return obj, gc, log


obj, gc, log = setup()
check(obj.get_status(0)["wrapped"] == ["CANCEL_PRINT"],
      "wraps CANCEL_PRINT only")
gc.handlers["PRINT_END"](FakeGCmd("PRINT_END"))
gc.handlers["CANCEL_PRINT"](FakeGCmd("CANCEL_PRINT"))
check(log == ["PRINT_END", "_PUSHRAKER_CANCEL", "CANCEL_PRINT"],
      "cancel hook runs before CANCEL_PRINT; other commands untouched")
check(gc.gcode_help.get("CANCEL_PRINT") == "cancel_print", "help text kept")

obj, gc, log = setup(fail=("_PUSHRAKER_CANCEL",))
g = FakeGCmd("CANCEL_PRINT")
gc.handlers["CANCEL_PRINT"](g)
check(log == ["_PUSHRAKER_CANCEL", "CANCEL_PRINT"] and g.info,
      "a failing hook still runs the original, with a console note")

obj, gc, log = setup(macros=())
check(obj.get_status(0)["wrapped"] == [], "no hook macros: nothing wrapped")
gc.handlers["CANCEL_PRINT"](FakeGCmd("CANCEL_PRINT"))
check(log == ["CANCEL_PRINT"], "unwrapped command still works")

try:
    pushraker_hooks.load_config(FakeConfig(FakePrinter(None, ()), "BAD"))
    check(False, "bad wrap option rejected")
except FakeConfigError:
    check(True, "bad wrap option rejected")

# moonraker/pushraker_cards.py on pushraker's real
# discord._payload, with a stand-in Moonraker and printer state
import importlib.util  # noqa: E402

sys.path.insert(0, PY)
# By file: moonraker/pushraker.py (the shim) would shadow the package if
# the folder were on sys.path
_spec = importlib.util.spec_from_file_location(
    "pushraker_cards", os.path.join(HERE, "moonraker", "pushraker_cards.py"))
pushraker_cards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pushraker_cards)
from pushraker import discord as pr_discord  # noqa: E402

real_payload = pr_discord._payload


class FakeLoop:
    aioloop = None


class FakeServer:
    def __init__(self, push):
        self.push = push

    def get_event_loop(self):
        return FakeLoop()

    def lookup_component(self, name):
        if name == "pushraker" and self.push is not None:
            return self.push
        raise KeyError(name)


class FakeMRConfig:
    def __init__(self, server):
        self.server = server

    def get_server(self):
        return self.server

    def getboolean(self, key, default):
        return default


class FakePush:
    name = "AD5X-2"

    async def _attempts(self, rid, dest, t, title, body, headers, path,
                        result=None):
        return pr_discord._payload(body, title, "info", {})


import asyncio  # noqa: E402

push = FakePush()
cards = pushraker_cards.load_component(FakeMRConfig(FakeServer(push)))
check(pr_discord._payload is not real_payload, "cards wrap discord._payload")
asyncio.run(cards.component_init())
check(getattr(push._attempts, "_kiln_card", False),
      "cards wrap pushraker's _attempts")

printing = {"status": {
    "print_stats": {"state": "printing", "filename": "cube.gcode",
                    "print_duration": 600, "info": {"current_layer": 12,
                                                    "total_layer": 50}},
    "display_status": {"progress": 0.4},
    "extruder": {"temperature": 220.0, "target": 220.0},
    "heater_bed": {"temperature": 60.0, "target": 60.0}},
    "meta": {"estimated_time": 1500}, "name": "AD5X-2"}
cards._state = lambda: printing
p = pr_discord._payload("40% done\ncube.gcode", "Progress", "info", {})
e = p["embeds"][0]
names = [f["name"] for f in e.get("fields", [])]
check(names == ["Status", "Extruder Temp", "Bed Temp", "Progress",
                "Print Time", "ETA", "Layer", "File"],
      f"printing card fields ({names})")
check(e.get("color") == 0x00ff00, "printing card is green")
check(e.get("footer", {}).get("text") == "AD5X-2", "printer name in footer")
check("cube.gcode" not in e.get("description", ""),
      "file line moved from the text to the File field")
check(dict((f["name"], f["value"]) for f in e["fields"])["Layer"]
      == "12 / 50", "layer from print_stats.info")

# "complete" comes from the print-end hook while Klipper still says printing
title = "Print complete"
p = asyncio.run(push._attempts("complete", None, None, title, "done",
                               {}, None))
e = p["embeds"][0]
fields = dict((f["name"], f["value"]) for f in e.get("fields", []))
check(fields.get("Status") == "✅ Completed",
      "complete card from the notification id, not Klipper's state")
check("Progress" not in fields and fields.get("File") == "cube.gcode",
      "complete card: no progress bar, file kept")

p = pr_discord._payload("boom", "Error", "failure", {})
check(p["embeds"][0]["color"] == 0xb02626, "failure card is red")

cards._state = lambda: (_ for _ in ()).throw(RuntimeError("no state"))
p = pr_discord._payload("plain", "Plain", "info", {})
check(p["embeds"][0]["title"] == "Plain" and "fields" not in p["embeds"][0],
      "a card error sends pushraker's own embed")
cards.close()
check(pr_discord._payload is real_payload, "close() puts _payload back")

# Moonraker loads the cards before the pushraker component, which is what
# puts the package on sys.path: the cards wrap at component_init then
import pushraker as _pkg  # noqa: E402

_saved = sys.modules.get("pushraker.discord")
# import fails, as before the shim ran
sys.modules["pushraker.discord"] = None
delattr(_pkg, "discord")
push = FakePush()
late = pushraker_cards.load_component(FakeMRConfig(FakeServer(push)))
sys.modules["pushraker.discord"] = _saved
_pkg.discord = _saved
check(pr_discord._payload is real_payload,
      "pushraker not importable yet: nothing wrapped at load")
asyncio.run(late.component_init())
check(getattr(pr_discord._payload, "_kiln_card", False)
      and getattr(push._attempts, "_kiln_card", False),
      "wrapped at component_init once pushraker is importable")
late.close()

# moonraker/pushraker.py (the shim) finds the package in python/
# (pushraker's component imports Moonraker itself, which only the printer
# has: getting that far means the shim found the package)
code = "\n".join([
    "import importlib.util, sys",
    "s = importlib.util.spec_from_file_location('shim', sys.argv[1])",
    "m = importlib.util.module_from_spec(s)",
    "try:",
    "    s.loader.exec_module(m); print(callable(m.load_component))",
    "except ModuleNotFoundError as e:",
    "    print(e.name == 'moonraker' and 'pushraker' in sys.modules)",
])
r = subprocess.run([sys.executable, "-I", "-c", code,
                    os.path.join(HERE, "moonraker", "pushraker.py")],
                   capture_output=True, text=True)
check(r.stdout.strip() == "True",
      "the shim loads pushraker from python/"
      + ("" if r.stdout.strip() == "True" else "\n" + r.stderr[-600:]))

with open(os.path.join(PY, "pushraker", "web", "index.html"),
          encoding="utf-8") as f:
    page = f.read()
check("el('nt-fc-loaded') ?" in page, "settings page filament-change fix")

with open(os.path.join(HERE, "web.sh"), encoding="utf-8") as f:
    web = f.read()
check("location /notifications/ { alias $WEB/;" in web,
      "web.sh adds /notifications/ with the page")
check("BIN=$DIR/zpushraker" in web,
      "own nginx binary name (survives Zmod's killall nginx)")

modes = subprocess.run(["git", "ls-files", "-s", "install.sh",
                        "uninstall.sh", "web.sh"], cwd=HERE,
                       capture_output=True, text=True).stdout
check(modes.count("100755") == 3,
      "install.sh, uninstall.sh, web.sh executable in git")
with open(os.path.join(HERE, "install.sh"), encoding="utf-8") as f:
    inst = f.read()
with open(os.path.join(HERE, "uninstall.sh"), encoding="utf-8") as f:
    uninst = f.read()
for s in ("pushraker_hooks.py", "for COMP in pushraker pushraker_cards",
          "moonraker", "web.sh"):
    check(s in inst and s in uninst, f"install/uninstall both handle {s}")

print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'all passed'}")
sys.exit(1 if failures else 0)
