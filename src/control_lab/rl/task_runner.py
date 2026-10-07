"""Detached train process. Its durable registry remains usable after the GUI exits."""
import argparse
import json
import os
from pathlib import Path
import traceback

from .artifacts import atomic_json
from .tasks import now, process_identity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    folder = args.request.resolve().parent
    request = json.loads(args.request.read_text(encoding="utf-8"))
    task_id = request["task_id"]
    if folder.name != task_id or request.get("schema_version") != 1 or request.get("kind") != "train":
        raise ValueError("Invalid training task request")
    with (folder/"runner.claim").open("x", encoding="utf-8") as stream:
        json.dump({"process": process_identity(os.getpid()), "at": now()}, stream)
    state = {"schema_version": 1, "task_id": task_id, "status": "running",
             "created_at": request["created_at"], "updated_at": now(), "process": process_identity(os.getpid())}
    atomic_json(folder/"state.json", state)

    def progress(message):
        value = {**message, "task_id": task_id}
        with (folder/"events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+"\n")
            stream.flush()
        state.update(updated_at=now(), last_event=value)
        if message.get("type") in {"completed", "stopped"}:
            state.update(status=message["type"], result=value)
        elif message.get("type") == "error":
            state.update(status="failed", error=message["message"])
        atomic_json(folder/"state.json", state)

    try:
        from .train import TrainConfig, train
        config = dict(request["config"])
        config["stop_file"] = folder/"STOP"
        train(TrainConfig(**config), progress_callback=progress)
        return 0
    except BaseException as exc:
        message = {"type": "error", "operation": "train", "error_type": type(exc).__name__,
                   "message": str(exc) or type(exc).__name__, "traceback": traceback.format_exc(limit=15)}
        progress(message)
        print(json.dumps(message, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
