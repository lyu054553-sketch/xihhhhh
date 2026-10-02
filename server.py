"""本地启动：python3 server.py；冲突时可用 PORT=8765。"""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run("backend.api:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), reload=False)
