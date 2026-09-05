#!/usr/bin/env python3
"""
Builds one self-contained, ready-to-send zip per participant:
    dist/participant-01.zip, dist/participant-02.zip, ...

Each zip contains ONLY that participant's own kubeconfig plus the generic
connect.sh / connect.ps1 / README.txt -- safe to hand out individually,
since it grants access to nothing but their own namespace.

Run from the terraform/ directory, after `terraform apply` has generated
kubeconfigs/*.yaml:
    python scripts/package_participant_kits.py
"""
import shutil
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
KUBECONFIG_DIR = ROOT_DIR / "kubeconfigs"
KIT_DIR = ROOT_DIR / "participant-kit"
DIST_DIR = ROOT_DIR / "dist"

KIT_FILES = ["connect.sh", "connect.ps1", "README.txt"]


def main() -> int:
    kubeconfigs = sorted(KUBECONFIG_DIR.glob("participant-*.yaml"))
    if not kubeconfigs:
        print(f"No kubeconfigs found in {KUBECONFIG_DIR} -- run terraform apply first.")
        return 1

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    for kcfg in kubeconfigs:
        name = kcfg.stem  # e.g. participant-07
        zip_path = DIST_DIR / f"{name}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(kcfg, arcname=f"{name}/{kcfg.name}")
            for fname in KIT_FILES:
                zf.write(KIT_DIR / fname, arcname=f"{name}/{fname}")

    print(f"Built {len(kubeconfigs)} participant kits in {DIST_DIR}/")
    print("Hand out participant-XX.zip to participant XX only -- each one only")
    print("grants access to that participant's own namespace.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
