"""An import that failed for the wrong reason must not read as absence.

`try: import x ... except Exception: pass` collapses two different
events into one. The tolerated one is a genuinely optional dependency
not being installed. The other is a module that exists and will not
import - a syntax error, a missing transitive dependency, a half-written
file - and swallowing that produces a **quieter program rather than a
louder one**, which is the failure shape this project has now recorded
seven times.

It cost `ports.py` first (`4e6a58b`): pyserial missing reported an empty
bench, and a board-free result read as "no board attached".

Three things are asserted here, and the third is the one that catches the
next instance rather than these four.
"""

import ast
import builtins
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOST = os.path.join(REPO, "host")
if HOST not in sys.path:
    sys.path.insert(0, HOST)

import provenance                                          # noqa: E402
import scope                                               # noqa: E402


def _import_raising(exc, only):
    """A `__import__` that fails for `only`, with `exc`, and nothing else."""
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name == only or name.split(".")[0] == only:
            raise exc
        return real(name, *a, **kw)
    return fake


# --- the sharpest site: a row that cannot say which instrument read it ---

def test_provenance_records_an_absent_measure_rather_than_dropping_the_key(
        monkeypatch):
    """An absent field and a field nobody could compute are different facts.

    #51's conclusion is that a stored figure which does not name its
    instrument is unanswerable afterwards. A row that silently omits
    `instrument` is indistinguishable from a session that honestly took
    no counter reads, so the reason is written down instead.
    """
    monkeypatch.setattr(builtins, "__import__",
                        _import_raising(ImportError("no module"), "measure"))
    p = provenance.collect()
    assert "instrument" not in p
    assert "not importable" in p.get("instrument_error", ""), p


def test_provenance_keeps_a_broken_measure_apart_from_an_absent_one(
        monkeypatch):
    """The whole point: the two reasons must not read the same.

    `collect` promises never to raise, so this one is recorded rather
    than propagated - but it must not be recorded as absence, or a
    module that will not import is reported as a bench that does not
    have it.
    """
    monkeypatch.setattr(builtins, "__import__",
                        _import_raising(RuntimeError("planted"), "measure"))
    p = provenance.collect()
    err = p.get("instrument_error", "")
    assert "RuntimeError" in err and "planted" in err, p
    assert "not importable" not in err, (
        "a module that failed for another reason was reported as absent")


# --- best-effort teardown, which is allowed to be quiet about two things ---

def test_scope_close_tolerates_pyusb_absent_and_a_device_already_gone(
        monkeypatch):
    class Dev:
        pass

    class S:
        dev = Dev()

    monkeypatch.setattr(builtins, "__import__",
                        _import_raising(ImportError("no pyusb"), "usb"))
    scope.UsbTmc.close(S())          # must not raise

    monkeypatch.undo()
    usb_core = pytest.importorskip("usb.core")
    usb_util = pytest.importorskip("usb.util")
    monkeypatch.setattr(usb_util, "dispose_resources",
                        lambda d: (_ for _ in ()).throw(
                            usb_core.USBError("gone")))
    scope.UsbTmc.close(S())          # must not raise either


def test_scope_close_does_not_hide_a_fault_that_is_neither(monkeypatch):
    """A `close` that swallows everything is how a session ends silently."""
    usb_util = pytest.importorskip("usb.util")

    class S:
        dev = object()

    monkeypatch.setattr(usb_util, "dispose_resources",
                        lambda d: (_ for _ in ()).throw(
                            RuntimeError("planted")))
    with pytest.raises(RuntimeError):
        scope.UsbTmc.close(S())


# --- and the guard that catches the NEXT one -------------------------------

def _swallowed_imports(path):
    """(line, module) for each `try: import x` caught by a blanket handler.

    The shape, not the file: a `try` whose body contains an import,
    caught by a handler that names `Exception` or nothing at all, with
    NO `ImportError` arm anywhere on the same `try`.

    The defect is conflation, not the blanket arm itself. A `try` that
    handles `ImportError` first and records the rest separately has told
    the two events apart, which is the whole requirement - `collect` in
    `provenance.py` does exactly that, because it promises never to
    raise and therefore writes the reason down instead of propagating
    it.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        imported = [n for n in node.body
                    if isinstance(n, (ast.Import, ast.ImportFrom))]
        if not imported:
            continue
        blanket, named_absence = [], False
        for handler in node.handlers:
            names = []
            if handler.type is None:
                names = ["<bare>"]
            else:
                for t in (handler.type.elts
                          if isinstance(handler.type, ast.Tuple)
                          else [handler.type]):
                    names.append(getattr(t, "id", getattr(t, "attr", "?")))
            blanket.extend(
                [handler] if ("<bare>" in names or "Exception" in names
                              or "BaseException" in names) else [])
            named_absence = named_absence or "ImportError" in names
        if blanket and not named_absence:
            first = imported[0]
            mod = (first.names[0].name if isinstance(first, ast.Import)
                   else (first.module or "?"))
            out.append((blanket[0].lineno, mod))
    return out


def _host_sources():
    for root, _dirs, names in os.walk(HOST):
        for n in sorted(names):
            if n.endswith(".py"):
                yield os.path.join(root, n)


def test_no_import_in_host_is_guarded_by_a_blanket_handler():
    """The class, not the four instances.

    `except Exception` around an import cannot tell absence from a
    module that will not load, so it is the spelling itself that is
    refused here. Where a blanket catch is genuinely wanted, the import
    goes outside the `try` - which is also what makes the intent
    readable.
    """
    found = []
    for path in _host_sources():
        for line, mod in _swallowed_imports(path):
            found.append("%s:%d imports %s"
                         % (os.path.relpath(path, REPO), line, mod))
    assert not found, (
        "an import guarded by a blanket handler cannot tell an absent "
        "optional dependency from a broken one:\n  " + "\n  ".join(found))
