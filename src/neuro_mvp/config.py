"""Centralized configuration management for the Neuro MVP system."""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from dotenv import load_dotenv


class ConfigManager:
    """Centralized configuration management with environment variable overrides."""
    
    def __init__(self, config_path: str = "config.yaml"):
        load_dotenv()
        self.config_path = Path(config_path)
        self._config: Optional[Dict[str, Any]] = None
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from YAML file with environment variable overrides."""
        if self._config is not None:
            return self._config
            
        config: Dict[str, Any] = {}
        if self.config_path.exists():
            config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        
        # Apply environment variable overrides
        config = self._apply_env_overrides(config)
        
        # Set defaults
        config.setdefault("tts", {})
        config.setdefault("memory", {})
        config.setdefault("conversation", {})
        config.setdefault("models", {})
        
        self._config = config
        return config
    
    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment variable overrides to configuration."""
        # Memory provider override
        if memory_cfg := config.get("memory"):
            memory_cfg["provider"] = os.getenv("MEMORY_PROVIDER", memory_cfg.get("provider", "qdrant"))
        
        # TTS configuration overrides
        if tts_cfg := config.get("tts", {}).get("kokoro", {}):
            tts_cfg["voice"] = os.getenv("KOKORO_VOICE", tts_cfg.get("voice", "af_heart"))
            tts_cfg["lang"] = os.getenv("KOKORO_LANG", tts_cfg.get("lang", "a"))
        
        # LLM configuration overrides
        if models_cfg := config.get("models", {}).get("llm", {}):
            models_cfg["base_url"] = os.getenv("OPENAI_BASE_URL", models_cfg.get("base_url", "http://localhost:1234/v1"))
            models_cfg["api_key"] = os.getenv("OPENAI_API_KEY", models_cfg.get("api_key"))
        
        # Web server configuration overrides
        if conversation_cfg := config.get("conversation"):
            conversation_cfg["autodrive_input_timeout_sec"] = float(os.getenv("WEB_AUTODRIVE_TIMEOUT", "15"))
            conversation_cfg["autodrive_assistant_timeout_sec"] = float(os.getenv("WEB_AUTODRIVE_ASSISTANT_TIMEOUT", "5"))
        
        return config
    
    def get_memory_config(self) -> Dict[str, Any]:
        """Get memory-specific configuration."""
        config = self.load()
        mem_cfg = config.get("memory", {})
        
        # Set defaults
        mem_cfg.setdefault("provider", "qdrant")
        mem_cfg.setdefault("qdrant", {})
        
        # Set persona and user label defaults
        qdrant_cfg = mem_cfg["qdrant"]
        qdrant_cfg.setdefault("persona", "Nova is friendly and loves learning about the user and herself. Rule 1: Be friendly. Rule 2: Be helpful.")
        qdrant_cfg.setdefault("user_label", "User is Noah.")
        
        return mem_cfg
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM-specific configuration."""
        config = self.load()
        models_cfg = config.get("models", {})
        
        # Set defaults
        models_cfg.setdefault("device", "auto")
        models_cfg.setdefault("cpu_safe", True)
        models_cfg.setdefault("llm", {})
        
        llm_cfg = models_cfg["llm"]
        llm_cfg.setdefault("provider", "openai_compat")
        llm_cfg.setdefault("base_url", "http://localhost:1234/v1")
        llm_cfg.setdefault("id", "qwen2.5-3b-instruct")
        llm_cfg.setdefault("max_new_tokens", 128)
        llm_cfg.setdefault("temperature", 0.7)
        llm_cfg.setdefault("thinking", False)
        
        return llm_cfg
    
    def get_tts_config(self) -> Dict[str, Any]:
        """Get TTS-specific configuration."""
        config = self.load()
        tts_cfg = config.get("tts", {})
        
        # Set defaults
        tts_cfg.setdefault("enable", True)
        tts_cfg.setdefault("auto_play", True)
        tts_cfg.setdefault("play_async", False)
        tts_cfg.setdefault("kokoro", {})
        
        kokoro_cfg = tts_cfg["kokoro"]
        kokoro_cfg.setdefault("voice", "af_heart")
        kokoro_cfg.setdefault("lang", "a")
        kokoro_cfg.setdefault("out_path", "response.wav")
        
        return tts_cfg


# Global configuration instance
config_manager = ConfigManager()


def load_config() -> Dict[str, Any]:
    """Load the global configuration."""
    return config_manager.load()


def get_memory_config() -> Dict[str, Any]:
    """Get memory configuration."""
    return config_manager.get_memory_config()


def get_llm_config() -> Dict[str, Any]:
    """Get LLM configuration."""
    return config_manager.get_llm_config()


def get_tts_config() -> Dict[str, Any]:
    """Get TTS configuration."""
    return config_manager.get_tts_config()
