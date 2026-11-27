"""Temporary directories whose cleanup can never raise.

Windows refuses to delete a file another process (or this one,
through a media backend or a database handle) still holds open:
``PermissionError [WinError 32]``. Linux permits deleting an open
file, so a cleanup that raises on Windows is invisible on Linux
until it kills a build gate there -- CI run 45991918059 died
exactly that way, twice over (a SQLite project store and the
narration players' audio folders, the latter raising out of
``tempfile``'s weakref finaliser at interpreter exit).

The discipline here:

* :func:`remove_tree` retries briefly -- a backend told to stop
  may release its handle a moment later -- then degrades to a
  best-effort removal. It NEVER raises; a folder that survives is
  plain temp litter the OS reaps later, not a crash.
* :class:`TempDir` is the ``tempfile.TemporaryDirectory`` shape
  (``.name``, ``.cleanup()``) without a finaliser that can raise:
  its exit-time sweep is :func:`remove_tree` itself.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import weakref
from pathlib import Path


def remove_tree(path: str | Path, *, attempts: int = 8,
                delay_s: float = 0.05) -> bool:
    """Recursively delete ``path``; return True when it is gone.

    Retries briefly (a just-stopped media backend or a closing
    database handle releases the file a moment after the request),
    then removes what it can and reports honestly. Never raises.
    """
    target = Path(path)
    if not target.exists():
        return True
    for attempt in range(max(1, attempts)):
        try:
            shutil.rmtree(target)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt + 1 < attempts:
                time.sleep(delay_s)
    try:
        shutil.rmtree(target, ignore_errors=True)
    except Exception:  # noqa: BLE001 -- cleanup must never raise
        pass
    return not target.exists()


class TempDir:
    """A temporary directory with a cleanup that cannot raise.

    Drop-in for the two narration players' use of
    ``tempfile.TemporaryDirectory``: same ``.name`` / ``.cleanup()``
    surface, but creation is ``mkdtemp`` and the exit-time sweep is
    a ``weakref.finalize`` running :func:`remove_tree` -- so a file
    still locked at interpreter shutdown degrades to temp litter
    instead of a traceback out of ``weakref._exitfunc``.
    """

    def __init__(self, prefix: str = "mimforge-") -> None:
        self.name = tempfile.mkdtemp(prefix=prefix)
        self._finalizer = weakref.finalize(self, remove_tree, self.name)

    def cleanup(self) -> None:
        """Remove the tree now (never raises) and disarm the
        exit-time sweep."""
        self._finalizer.detach()
        remove_tree(self.name)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, *exc) -> None:
        self.cleanup()
