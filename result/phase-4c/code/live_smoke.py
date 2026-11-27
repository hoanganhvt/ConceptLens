"""Exercise the installed CLI catalogs and the Phase 4C route functions."""

import argparse
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Literal
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import BaseModel


class Proof(BaseModel):
    value: Literal["ready"]


def version(command):
    path = shutil.which(command)
    if not path:
        return "not installed"
    try:
        result = subprocess.run([path, "--version"], text=True, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else "unavailable"


def catalog(app, provider, preferred):
    started = monotonic()
    try:
        models = app.model_catalog(provider)
    except HTTPException as exc:
        print(f"{provider} catalog blocked: HTTP {exc.status_code} after {monotonic() - started:.2f}s. {exc.detail}")
        return None
    selected = preferred or (models[0]["id"] if models else None)
    if selected is None or selected not in {model["id"] for model in models}:
        print(f"{provider} catalog blocked: requested model is unavailable.")
        return None
    print(f"{provider} catalog: {len(models)} models in {monotonic() - started:.2f}s. Selected {selected}.")
    return selected


def codex_probe(providers, model):
    started = monotonic()

    def remaining():
        return max(0.01, 25 - (monotonic() - started))

    try:
        result = providers.codex_result(Proof, "Return the object with value set to ready.", {},
                                        model=model, remaining=remaining, kind="phase-4c-smoke")
    except HTTPException as exc:
        print(f"Codex inference blocked: HTTP {exc.status_code} after {monotonic() - started:.2f}s. {exc.detail}")
        return False
    passed = result == {"value": "ready"}
    print(f"Codex inference: {'pass' if passed else 'fail'} in {monotonic() - started:.2f}s.")
    return passed


def run(args, scratch):
    os.environ["STUDY_DATA"] = str(Path(scratch) / "study")
    if args.disposable_codex_state:
        state = Path(scratch) / "codex-state"
        state.mkdir()
        os.environ["CODEX_SQLITE_HOME"] = str(state)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from backend import main, providers
    from backend.demo import ROAD
    from backend.models import Roadmap

    main.language.set("en")
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    print(f"Installed CLIs: {version('codex')}, agy {version('agy')}.")
    print(f"Disposable Codex SQLite state: {args.disposable_codex_state}.")
    if args.codex_proof_only:
        print(f"Codex structured inference probe for catalog model {args.codex_model}.")
        return 0 if codex_probe(providers, args.codex_model) else 2
    if args.codex_catalog_only:
        isolated_home = Path(scratch) / "codex-catalog"
        isolated_home.mkdir()
        with patch.dict(os.environ, {"CODEX_HOME": str(isolated_home)}):
            print("Protocol-only Codex catalog probe with an empty CLI home.")
            return 0 if catalog(main, "codex", args.codex_model) else 2
    codex = catalog(main, "codex", args.codex_model)
    agy = catalog(main, "agy", args.agy_model)
    codex_ready = bool(codex and codex_probe(providers, codex))
    if not (codex_ready and agy):
        print("V7 blocked before mixed-provider lesson generation.")
        return 2

    main.save_settings(providers.SettingsUpdate(provider="codex", codex_model=codex,
                                               visual_provider="agy", agy_visual_model=agy))
    roadmap = main.commit(Roadmap.model_validate(ROAD))
    rid, tid = roadmap["id"], roadmap["chapters"][0]["topics"][0]["id"]
    try:
        lesson = main.generate(rid, tid)
        if not lesson["illustration_status"] or any(scene["state"] != "ready" for scene in lesson["illustration_status"]):
            print("V7 blocked: at least one selected-model illustration did not generate.")
            return 2
        main.repair(rid, tid, 0, main.Repair(error="Synthetic smoke: give the control a clear label.", manual=True))
    except HTTPException as exc:
        print(f"V7 blocked: mixed-provider generation or repair returned HTTP {exc.status_code}. {exc.detail}")
        return 2
    print("V7 generated and repaired a synthetic lesson. Review the CLI capability evidence before closing V7.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-model")
    parser.add_argument("--agy-model")
    parser.add_argument("--disposable-codex-state", action="store_true")
    probe = parser.add_mutually_exclusive_group()
    probe.add_argument("--codex-catalog-only", action="store_true")
    probe.add_argument("--codex-proof-only", action="store_true")
    args = parser.parse_args()
    if args.codex_proof_only and not args.codex_model:
        parser.error("--codex-proof-only requires --codex-model")
    with TemporaryDirectory(prefix="study-phase-4c-live-") as scratch:
        code = run(args, scratch)
    raise SystemExit(code)
