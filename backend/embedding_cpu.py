"""Optional CPU inference using local weights and tokenizers."""

from pathlib import Path
from os import environ


class Encoder:
    def __init__(self, directory, manifest):
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            environ[name] = "2"
        environ["TOKENIZERS_PARALLELISM"] = "false"
        import numpy as np
        from tokenizers import Tokenizer

        self.np = np
        directory = Path(directory)
        model = directory / manifest["model"]
        self.kind = manifest["kind"]
        self.dimension = manifest["dimension"]
        self.tokens = Tokenizer.from_file(str(directory / manifest["tokenizer"]))
        self.tokens.enable_truncation(max_length=manifest.get("max_tokens", 128))
        pad = next((value for value in ("[PAD]", "<pad>") if self.tokens.token_to_id(value) is not None), None)
        if pad is not None:
            self.tokens.enable_padding(pad_id=self.tokens.token_to_id(pad), pad_token=pad)
        if self.kind == "static":
            from safetensors.numpy import load_file

            self.weights = load_file(str(model))["embeddings"]
            self.unknown = self.tokens.token_to_id("[UNK]")
            if self.weights.ndim != 2 or self.weights.shape[1] != self.dimension:
                raise ValueError("Invalid static embedding dimensions")
        elif self.kind == "e5":
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            self.runtime = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
            self.input_names = [port.name for port in self.runtime.get_inputs()]
        elif self.kind == "bekko":
            from openvino import Core

            self.runtime = Core().compile_model(str(model), "CPU", {"INFERENCE_NUM_THREADS": 2,
                                                                    "NUM_STREAMS": 1})
            self.input_names = [port.get_any_name() for port in self.runtime.inputs]
        else:
            raise ValueError("Unsupported CPU embedding model")

    def encode(self, text, *, query):
        return self.encode_many([text], query=query)[0]

    def encode_many(self, texts, *, query):
        if not texts:
            return []
        if self.kind == "e5":
            prefix = "query: " if query else "passage: "
            texts = [prefix + text for text in texts]
        batch = self.tokens.encode_batch(texts, add_special_tokens=self.kind != "static")
        np = self.np
        if self.kind == "static":
            rows = []
            for item in batch:
                ids = [token for token, visible in zip(item.ids, item.attention_mask)
                       if visible and token != self.unknown]
                rows.append(self.weights[ids].mean(axis=0, dtype=np.float32)
                            if ids else np.zeros(self.dimension, dtype=np.float32))
            pooled = np.asarray(rows)
        else:
            inputs = dict(input_ids=np.asarray([item.ids for item in batch], dtype=np.int64),
                          attention_mask=np.asarray([item.attention_mask for item in batch], dtype=np.int64),
                          token_type_ids=np.asarray([item.type_ids for item in batch], dtype=np.int64))
            selected = {name: inputs[name] for name in self.input_names}
            hidden = (self.runtime.run(None, selected)[0] if self.kind == "e5"
                      else self.runtime(selected)[self.runtime.output(0)])
            mask = inputs["attention_mask"][:, :, None].astype(np.float32)
            pooled = (hidden * mask).sum(axis=1, dtype=np.float32) / np.maximum(mask.sum(axis=1), 1)
        if pooled.shape != (len(texts), self.dimension) or not np.isfinite(pooled).all():
            raise ValueError("Invalid embedding output")
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.maximum(norms, np.finfo(np.float32).tiny)).tolist()
