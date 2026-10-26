"""python -m capabilities_gateway"""

from __future__ import annotations

import uvicorn

from capabilities_gateway.settings import port


def main() -> None:
    uvicorn.run(
        "capabilities_gateway.app:app",
        host="0.0.0.0",
        port=port(),
        factory=False,
    )


if __name__ == "__main__":
    main()
