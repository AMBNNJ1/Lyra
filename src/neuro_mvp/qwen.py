from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

# Optional torch import; degrade gracefully if missing/broken
try:
    import torch  # type: ignore
    _TORCH_OK = True
except Exception:
    torch = None  # type: ignore
    _TORCH_OK = False


def pick_device(cfg_device: str = "auto") -> str:
    if cfg_device == "cuda":
        return "cuda" if (_TORCH_OK and torch.cuda.is_available()) else "cpu"  # type: ignore[union-attr]
    if cfg_device == "cpu":
        return "cpu"
    # auto
    return "cuda" if (_TORCH_OK and torch.cuda.is_available()) else "cpu"  # type: ignore[union-attr]


@dataclass
class LLMConfig:
    model_id: str
    max_new_tokens: int = 128
    temperature: float = 0.7
    thinking: bool = False
    device: str = "auto"
    cpu_safe: bool = True
    local_files_only: bool = False
    revision: Optional[str] = None


class QwenLLM:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.device = pick_device(cfg.device)
        self.enabled = True
        if (not _TORCH_OK) or (self.device == "cpu" and cfg.cpu_safe):
            print("[llm] Torch unavailable or CPU-safe active — skipping local LLM load.")
            self.enabled = False
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            cfg.model_id,
            local_files_only=cfg.local_files_only,
            revision=cfg.revision,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            cfg.model_id,
            torch_dtype="auto",
            device_map="auto" if self.device == "cuda" else None,
            local_files_only=cfg.local_files_only,
            revision=cfg.revision,
        )

    def generate(self, system: str, user_text: str) -> str:
        if not self.enabled:
            return f"(stub) {user_text}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        return self.generate_from_messages(messages)

    def generate_from_messages(self, messages: List[Dict[str, Any]]) -> str:
        if not self.enabled:
            # Return last user message with stub prefix
            last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = str(m.get("content", ""))
                    break
            return f"(stub) {last_user}"
        # Some Qwen tokenizers don't accept enable_thinking; guard it.
        if self.cfg.thinking:
            try:
                text = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True, enable_thinking=True
                )
            except TypeError:
                text = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
        else:
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=self.cfg.max_new_tokens)
        new_tokens = out[0][len(inputs.input_ids[0]):]
        resp = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        return resp


@dataclass
class VLMConfig:
    model_id: str
    max_new_tokens: int = 128
    device: str = "auto"
    cpu_safe: bool = True
    local_files_only: bool = False
    revision: Optional[str] = None


class QwenVLM:
    def __init__(self, cfg: VLMConfig):
        self.cfg = cfg
        self.device = pick_device(cfg.device)
        self.enabled = True
        if (not _TORCH_OK) or (self.device == "cpu" and cfg.cpu_safe):
            print("[vlm] Torch unavailable or CPU-safe active — skipping local VLM load.")
            self.enabled = False
            return
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            cfg.model_id,
            torch_dtype="auto",
            device_map="auto",
            local_files_only=cfg.local_files_only,
            revision=cfg.revision,
        )
        self.processor = AutoProcessor.from_pretrained(
            cfg.model_id,
            local_files_only=cfg.local_files_only,
            revision=cfg.revision,
        )

    def describe(self, image_url: str, prompt: str) -> str:
        if not self.enabled:
            return f"(stub) image:{image_url} {prompt}"
        from qwen_vl_utils import process_vision_info
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": image_url},
                {"type": "text", "text": prompt},
            ]
        }]
        text_input = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[text_input], images=image_inputs, videos=video_inputs,
            padding=True, return_tensors="pt"
        ).to(self.model.device)
        with torch.inference_mode():  # type: ignore[union-attr]
            output_ids = self.model.generate(**inputs, max_new_tokens=self.cfg.max_new_tokens)
        trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)]
        reply = self.processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        return reply
