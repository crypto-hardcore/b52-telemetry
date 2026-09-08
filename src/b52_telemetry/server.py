from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "b52_telemetry.main:app",
        host="127.0.0.1",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
