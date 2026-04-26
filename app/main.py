"""Backward-compatible entrypoint shim for MacroPulser.

The MacroPulser runtime implementation now lives in
`app.macro_pulser.main` to keep folder-level separation from the
AI Work System entrypoint (`app.ai_work_system.main`).
"""

from app.macro_pulser import main as _macro_main

# Preserve `uvicorn app.main:app` compatibility.
app = _macro_main.app
main = _macro_main.main


def __getattr__(name: str):
    return getattr(_macro_main, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_macro_main)))


if __name__ == "__main__":
    main()
