"""Backward-compatible entrypoint.

Historically this project ran from a single app.py.
The refactor keeps app.py as a thin wrapper so existing deployments keep working.

Run:
    python app.py
"""

from tdl_bot.main import main


if __name__ == "__main__":
    main()
