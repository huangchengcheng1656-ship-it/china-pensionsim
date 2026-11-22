"""Validate supplied data interfaces and replay the standard synthetic demonstration."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from data_validation import DEFAULT_FILES, validate_paths
from interruption import run as interruption_run

ROOT = Path(__file__).resolve().parent


def run(destination, region=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new output directory")
    errors = validate_paths(DEFAULT_FILES)
    if errors:
        raise ValueError("Data validation failed: " + "; ".join(errors))
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", str(ROOT / "model.py"), "--out", str(destination)]
    if region is not None:
        command += ["--region", region]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    interruption = {
        "mode": "synthetic_fixture",
        "parameter_basis": ("固定的职业中断回归样例，使用样例自带的全国占位参数；"
                            "不随 --region 改变 / fixed career-interruption regression fixture with its own "
                            "national placeholder parameters; not affected by --region"),
        "region_requested": region,
        "results": interruption_run(),
    }
    (destination / "interruption.synthetic.json").write_text(
        json.dumps(interruption, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (destination / "data_validation.json").write_text(
        json.dumps({"files_checked": len(DEFAULT_FILES), "errors": errors}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("synthetic_output"), help="new output directory")
    parser.add_argument("--region", help="registered public regional scenario, currently 浙江省")
    args = parser.parse_args(argv)
    try:
        destination = run(args.out, region=args.region)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")
    print(f"Validated {len(DEFAULT_FILES)} data files and saved synthetic results in {destination}")


if __name__ == "__main__":
    main()
