"""Provision public, pinned model artifacts for the synthetic benchmark."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from urllib.request import urlopen


MODELS = {
    "bekko": ("hotchpotch/bekko-embedding-v1-a8m", "openvino/openvino_model.xml",
              ("openvino/openvino_model.bin",), 384),
    "e5": ("Xenova/multilingual-e5-small", "onnx/model_quantized.onnx", (), 384),
    "static": ("univo-models/static-similarity-mrl-multilingual-int8-128",
               "model.safetensors", (), 128),
}


def download(root, kind, revision):
    repo, model, dependencies, dimension = MODELS[kind]
    if revision == "main":
        with urlopen(f"https://huggingface.co/api/models/{repo}", timeout=30) as response:
            revision = json.load(response)["sha"]
    folder = root / kind
    files = {}
    for filename in (model, "tokenizer.json", *dependencies):
        target = folder / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
        with urlopen(url, timeout=90) as source, temporary.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        temporary.replace(target)
        with target.open("rb") as stream:
            files[filename] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = dict(id=f"{repo}@{revision}", kind=kind, qualified=False, model=model,
                    tokenizer="tokenizer.json", dimension=dimension, max_tokens=128, files=files)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest["id"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("kind", choices=MODELS)
    parser.add_argument("--revision", default="main")
    args = parser.parse_args()
    download(args.root, args.kind, args.revision)
