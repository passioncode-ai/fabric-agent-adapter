"""FAA-38 (contract CT-18, service.md *One copy*): does the Task Scheduler restart a task whose action exits 75?

Run on a Windows machine (the `windows-restart-receipt` workflow), never on the operator's own: it installs a throwaway
task `\\PassionCode\\faa38-receipt-<hex>` exactly as the kit writes one (`task_xml`, `task_install`: a logon trigger,
`InteractiveToken`, `RestartOnFailure` every minute), whose action appends one line per start to a log and exits 75,
waits, counts the starts and reads the task's last result, then deletes the task. It prints one JSON receipt and
writes it to the path given as its only argument. Standard library only."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

KIT = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(KIT))
_spec = importlib.util.spec_from_file_location("fabric_service", KIT / "fabric_service.py")
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

WAIT_SECONDS = 260  # the first start, then three restarts one minute apart, and slack


def query(task: str) -> str:
    return subprocess.run(["schtasks", "/Query", "/TN", task, "/V", "/FO", "LIST"], capture_output=True, text=True).stdout


def main(out: Path) -> int:
    if sys.platform != "win32":
        print("this receipt runs on Windows only", file=sys.stderr)
        return 2
    work = Path(os.environ.get("RUNNER_TEMP") or os.environ["TEMP"]) / ("faa38-" + secrets.token_hex(4))
    work.mkdir(parents=True)
    log = work / "starts.log"
    probe = work / "probe.py"
    probe.write_text("import sys, time\nopen(%r, 'a').write('%%.0f %%s\\n' %% (time.time(), ' '.join(sys.argv[1:])))\n"
                     "sys.exit(75)\n" % str(log))
    task = "\\PassionCode\\faa38-receipt-" + secrets.token_hex(4)
    xml = fs.task_xml(task, [sys.executable, str(probe), "serve"], working_directory=str(work),
                      description="FAA-38 receipt: does RestartOnFailure restart an exit 75?")
    receipt = {"task": task, "python": sys.executable, "waitSeconds": WAIT_SECONDS,
               "settings": {"RestartOnFailure": "PT1M x 999", "MultipleInstancesPolicy": "IgnoreNew",
                            "LogonType": "InteractiveToken"}}
    started = time.time()
    try:
        fs.task_install(task, xml)
        receipt["installed"] = True
        time.sleep(WAIT_SECONDS)
        lines = log.read_text().splitlines() if log.exists() else []
        receipt["starts"] = len(lines)
        receipt["startOffsetsSeconds"] = [round(float(l.split()[0]) - started) for l in lines]
        receipt["argv"] = sorted({" ".join(l.split()[1:]) for l in lines})
        info = query(task)
        receipt["lastResult"] = next((l.split(":", 1)[1].strip() for l in info.splitlines() if l.strip().startswith("Last Result")), None)
        receipt["status"] = next((l.split(":", 1)[1].strip() for l in info.splitlines() if l.strip().startswith("Status")), None)
    except Exception as exc:  # the receipt records what happened, including a task that could not be created or run
        receipt["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            fs.task_uninstall(task)
            receipt["removed"] = True
        except Exception as exc:
            receipt["removed"] = "failed: %s" % exc
    starts = receipt.get("starts", 0)
    receipt["answer"] = ("restarts" if starts >= 2 else "does-not-restart" if starts == 1 else "never-ran")
    text = json.dumps(receipt, indent=2)
    print(text)
    out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "windows-restart-receipt.json")))
