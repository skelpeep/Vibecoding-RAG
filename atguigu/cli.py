import argparse
import uvicorn
from atguigu.config.config import RuntimeConfig

def main():
    parser = argparse.ArgumentParser(description="Run knowledge platform services")
    parser.add_argument("service", choices=["platform", "import", "query", "worker", "settlement-worker"])
    parser.add_argument("--port", type=int)
    parser.add_argument("--once", action="store_true", help="worker exits when no currently due tasks remain")
    args = parser.parse_args()
    if args.service == "settlement-worker":
        from atguigu.business.settlement_worker import run_worker
        run_worker(once=args.once)
        return
    if args.service == "worker":
        from atguigu.business.import_worker import run_worker
        run_worker(once=args.once)
        return
    port = args.port or {"platform": RuntimeConfig.platform_port, "import": RuntimeConfig.import_port, "query": RuntimeConfig.query_port}[args.service]
    uvicorn.run(f"atguigu.web.api.{args.service}_service:app", host=RuntimeConfig.host, port=port, workers=1)

if __name__ == "__main__":
    main()
