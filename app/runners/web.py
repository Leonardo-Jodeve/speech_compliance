"""python -m app.runners.web [--port 8000]，仅在本机开放。"""
import argparse

import uvicorn

from app.web.api import create_app


def main():
    parser = argparse.ArgumentParser(description="启动外呼话术评判工作台")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="使用隔离的虚构数据与模拟 ASR/LLM，不连接公司服务")
    args = parser.parse_args()
    runtime = None
    if args.demo:
        from app.web.demo import DemoRuntime
        runtime = DemoRuntime()
    uvicorn.run(create_app(runtime), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
