from __future__ import annotations

import argparse

import uvicorn

from app.api.main import create_app

app = create_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-work-system")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    uvicorn.run("app.ai_work_system.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
