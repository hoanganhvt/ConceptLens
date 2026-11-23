"""Exercise the actual Windows encoder child with public weights and synthetic text."""

import argparse
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.embedding_process import EncoderProcess


def wait_for_encoder(encoder):
    until = monotonic() + 35
    while monotonic() < until:
        encoder.start()
        if encoder.status != "building":
            return encoder.status
        sleep(0.05)
    raise TimeoutError("Encoder did not become ready or fail")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.runtime.resolve()))
    with TemporaryDirectory(prefix="conceptlens-encoder-smoke-") as folder:
        destination = Path(folder)
        manifest = json.loads((args.model / "manifest.json").read_text(encoding="utf-8"))
        for name in manifest["files"]:
            target = destination / name
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(args.model / name, target)
        # This fixture authorizes the isolated smoke only. The original artifact stays unqualified.
        manifest.update(qualified=True, threshold=0.5)
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        encoder = EncoderProcess(str(destination))
        try:
            status = wait_for_encoder(encoder)
            assert status == "ready", status
            vectors = encoder.encode(["I prefer a worked example.", "Mình thích ví dụ có lời giải."],
                                     query=True, deadline=monotonic() + 0.2)
            assert len(vectors) == 2 and all(len(vector) == manifest["dimension"] for vector in vectors)
            assert all(abs(sum(value * value for value in row) - 1) < 0.0001 for row in vectors)
            child = encoder.process
            encoder_id = encoder.metadata["id"]
        finally:
            encoder.close()
        assert encoder.process is None and child._closed

        model = manifest["model"]
        manifest["files"][model] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            checksum_status = wait_for_encoder(encoder)
            assert checksum_status == "error", checksum_status
        finally:
            encoder.close()
    print(json.dumps({"encoder": encoder_id, "dimension": manifest["dimension"], "ready": status,
                      "normalized_en_vi_outputs": True, "child_closed": True,
                      "incorrect_checksum_status": checksum_status, "hardware_qualified": False}, indent=2))


if __name__ == "__main__":
    main()
