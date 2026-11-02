"""Read story tables and export model-planned prompts without image/DB writes."""
import csv
import hashlib
import json
import re
from pathlib import Path

from comic_prompt_planner import SEMANTIC_VERSION, render_semantic_prompt, validate_semantic_plan


def read_story_table(input_path, column="优化稿"):
    path = Path(input_path)
    records = []
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook:
                rows = sheet.iter_rows(values_only=True)
                headers = [str(value or "").strip() for value in next(rows, ())]
                if column not in headers:
                    continue
                index = headers.index(column)
                for number, row in enumerate(rows, 2):
                    body = str(row[index] or "").strip() if len(row) > index else ""
                    if body:
                        records.append({"source_id": row[0], "sheet": sheet.title, "row": number, "body": body})
        finally:
            workbook.close()
    elif path.suffix.lower() in {".csv", ".tsv"}:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
            if column not in (reader.fieldnames or []):
                raise ValueError(f"表格缺少“{column}”列。")
            first = reader.fieldnames[0]
            for number, row in enumerate(reader, 2):
                body = str(row.get(column) or "").strip()
                if body:
                    records.append({"source_id": row.get(first), "sheet": "", "row": number, "body": body})
    else:
        raise ValueError("仅支持xlsx、xlsm、csv、tsv表格。")
    if not records:
        raise ValueError(f"没有找到非空的“{column}”数据。")
    return records


def _save_json(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def export_story_prompts(records, output_dir, plan_one, count=6, overwrite=False,
                         stopped=lambda: False, progress=lambda message: None):
    """One planner call per missing story; never invokes an image endpoint."""
    if count not in (4, 6):
        raise ValueError("宫格数只能是4或6。")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"version": SEMANTIC_VERSION, "panel_count": count, "total": len(records),
                "success": 0, "skipped": 0, "failed": 0, "stopped": False, "records": []}
    for index, record in enumerate(records, 1):
        if stopped():
            manifest["stopped"] = True
            break
        body = record["body"].replace("\r\n", "\n").replace("\r", "\n").strip()
        identifier = re.sub(r"[^\w\u4e00-\u9fff-]", "_", str(record.get("source_id") or index))[:28]
        stem = f"{index:03d}_{identifier}"
        plan_path = output / f"{stem}_分镜执行单.json"
        prompt_path = output / f"{stem}_生图Prompt.txt"
        entry = {**record, "index": index, "plan_file": plan_path.name, "prompt_file": prompt_path.name}
        try:
            source_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            cached = False
            if plan_path.exists() and not overwrite:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                if (plan.get("version") != SEMANTIC_VERSION or plan.get("source_sha256") != source_hash
                        or plan.get("source_body") != body
                        or len(plan.get("panels", [])) != count):
                    raise ValueError("已有执行单与本次正文、版本或格数不同，请换输出目录或显式允许覆盖。")
                validate_semantic_plan(plan, body, count)
                cached = True
            else:
                if prompt_path.exists() and not overwrite:
                    raise ValueError("已有同名TXT而无匹配执行单，请换输出目录或显式允许覆盖。")
                progress(f"第{index}/{len(records)}条：开始语义编排。")
                plan = plan_one(body, count)
                validate_semantic_plan(plan, body, count)
                if plan.get("source_sha256") != source_hash or plan.get("source_body") != body:
                    raise ValueError("编排结果与本条原文不匹配。")
            prompt = render_semantic_prompt(plan)
            if cached and prompt_path.exists() and prompt_path.read_text(encoding="utf-8") != prompt:
                raise ValueError("已有TXT与执行单不一致，请换输出目录或显式允许覆盖。")
            if not cached:
                _save_json(plan_path, plan)
            if not cached or not prompt_path.exists():
                prompt_path.write_text(prompt, encoding="utf-8")
            entry.update({"status": "已有结果" if cached else "完成", "title": plan["title"], "note": plan["note"]})
            manifest["skipped" if cached else "success"] += 1
            progress(f"第{index}/{len(records)}条：{entry['status']}。")
        except Exception as exc:
            if stopped():
                manifest["stopped"] = True
                break
            entry.update({"status": "失败", "error": str(exc)[:1200]})
            manifest["failed"] += 1
            progress(f"第{index}/{len(records)}条：失败，{entry['error']}")
        manifest["records"].append(entry)
        _save_json(output / "Prompt导出清单.json", manifest)
    _save_json(output / "Prompt导出清单.json", manifest)
    return manifest
