"""Export six-panel image prompts from a story table; never generates images."""
import argparse
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comic_prompt_batch import read_story_table, export_story_prompts
from comic_prompt_planner import planning_request


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="xlsx/xlsm/csv/tsv表格")
    parser.add_argument("--column", default="优化稿")
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-config", help="仅真实编排时读取其中的文本API配置")
    parser.add_argument("--grid", type=int, choices=(4, 6), default=6)
    parser.add_argument("--limit", type=int, help="仅处理前N条，适合首次试跑")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只导出文本模型请求，不调用任何接口")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit必须大于0")
    records = read_story_table(args.input, args.column)
    if args.limit:
        records = records[:args.limit]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        rows = [{**r, "status": "待文本模型编排", "request": planning_request(r["body"], args.grid)} for r in records]
        (output / "待编排请求.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) + "\n", encoding="utf-8")
        print(json.dumps({"requests_prepared": len(rows), "model_calls": 0, "image_calls": 0}, ensure_ascii=False))
        return 0
    if not args.api_config:
        parser.error("真实编排需要--api-config；只预览请求可使用--dry-run")
    import httpx
    from picfactory_gui import PicFactoryGUI
    app = PicFactoryGUI.__new__(PicFactoryGUI)
    app.account_generation_stop_requested = False
    app.account_generation_active_clients = set()
    app.account_generation_active_clients_lock = threading.Lock()
    app.account_generation_log = lambda message, **kwargs: print(message)
    api = app.load_storyboard_api_config(args.api_config)
    event = threading.Event()
    def plan_one(body, count):
        try:
            return app.plan_project13_semantically(httpx, api, body, count, 0, event)
        except Exception as exc:
            message = str(exc)
            for key in api["keys"]:
                message = message.replace(key, "[redacted]")
            raise RuntimeError(message) from None
    report = export_story_prompts(records, output, plan_one, count=args.grid, overwrite=args.overwrite,
                                  stopped=event.is_set, progress=print)
    print(json.dumps({k: report[k] for k in ("total", "success", "skipped", "failed", "stopped")}, ensure_ascii=False))
    return 1 if report["failed"] or report["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
