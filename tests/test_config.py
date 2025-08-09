"""
Test suite for monitor.config module.

Tests configuration loading, model mapping functionality, and related utilities
after the recent refactoring from model_mapping to MODEL_MAPPING.
"""

import pytest
import os
import tempfile
import json
from unittest.mock import patch, MagicMock
import logging

# Import the config module
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from monitor import config


class TestModelMapping:
    """Test model mapping functionality."""
    
    def setup_method(self):
        """Reset config state before each test."""
        config._MODEL_CONFIG_CACHE = None
        config.MODEL_MAPPING = None
    
    def test_model_mapping_initialization(self):
        """Test that MODEL_MAPPING is properly initialized."""
        # Mock a simple model config
        mock_config = {
            "model_mapping": {
                "gpt4": "gpt-4-turbo-preview",
                "claude": "claude-3-sonnet-20240229"
            },
            "conversation_history_mapping": {},
            "context_window_mapping": {},
            "output_window_mapping": {},
            "model_max_tpm": {},
            "openai_model_tpm_tier": {},
            "anthropic_model_tpm_tier": {},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config):
            config.load_model_config()
            
        assert config.MODEL_MAPPING is not None
        assert config.MODEL_MAPPING["gpt4"] == "gpt-4-turbo-preview"
        assert config.MODEL_MAPPING["claude"] == "claude-3-sonnet-20240229"
    
    def test_get_model_reverse_mapping_basic(self):
        """Test basic reverse mapping functionality."""
        config.MODEL_MAPPING = {
            "gpt4": "gpt-4-turbo-preview",
            "claude": "claude-3-sonnet-20240229",
            "gpt35": "gpt-3.5-turbo"
        }
        
        reverse_mapping = config.get_model_reverse_mapping()
        
        assert reverse_mapping["gpt-4-turbo-preview"] == "gpt4"
        assert reverse_mapping["claude-3-sonnet-20240229"] == "claude"
        assert reverse_mapping["gpt-3.5-turbo"] == "gpt35"
    
    def test_get_model_reverse_mapping_duplicates(self):
        """Test reverse mapping with duplicate values (should log warnings)."""
        config.MODEL_MAPPING = {
            "gpt4": "gpt-4-turbo-preview",
            "gpt4-alias": "gpt-4-turbo-preview",  # Duplicate value
            "claude": "claude-3-sonnet-20240229"
        }
        
        with patch('monitor.config.logger') as mock_logger:
            reverse_mapping = config.get_model_reverse_mapping()
            
            # Should log warning about duplicates
            mock_logger.warning.assert_called()
            
            # Should keep the last alias in the mapping
            assert reverse_mapping["gpt-4-turbo-preview"] == "gpt4-alias"
            assert reverse_mapping["claude-3-sonnet-20240229"] == "claude"
    
    def test_set_model_with_valid_key(self):
        """Test set_model with a valid model key."""
        # Mock a complete model config with keys matching hardcoded model_tpm_mapping
        mock_config = {
            "model_mapping": {
                "gpt4o": "gpt-4o-2024-08-06",  # Updated to current OpenAI snapshot
                "sonnet35": "claude-3-5-sonnet-20241022"  # Updated to current Anthropic
            },
            "conversation_history_mapping": {"gpt4o": 50, "sonnet35": 40},
            "context_window_mapping": {"gpt4o": 128000, "sonnet35": 200000},
            "output_window_mapping": {"gpt4o": 4096, "sonnet35": 4096},
            "model_max_tpm": {"gpt4o": 10000, "sonnet35": 20000},  # Model → tier level
            "openai_model_tpm_tier": {10000: 30000},  # Tier → TPM (numeric key)
            "anthropic_model_tpm_tier": {20000: 40000},  # Tier → TPM
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config):
            # First call load_model_config as required
            config.load_model_config()
            
            # Test with shorthand key
            config.set_model("gpt4o")
            assert config.MODEL == "gpt-4o-2024-08-06"
    
    def test_set_model_with_full_model_name(self):
        """Test set_model with a full model name."""
        # Use same updated mock_config as above
        mock_config = {
            "model_mapping": {
                "gpt4o": "gpt-4o-2024-08-06",
                "sonnet35": "claude-3-5-sonnet-20241022"
            },
            "conversation_history_mapping": {"gpt4o": 50, "sonnet35": 40},
            "context_window_mapping": {"gpt4o": 128000, "sonnet35": 200000},
            "output_window_mapping": {"gpt4o": 4096, "sonnet35": 4096},
            "model_max_tpm": {"gpt4o": 10000, "sonnet35": 20000},
            "openai_model_tpm_tier": {10000: 30000},
            "anthropic_model_tpm_tier": {20000: 40000},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config):
            # First call load_model_config as required
            config.load_model_config()
            
            # Test with full model name
            config.set_model("gpt-4o-2024-08-06")
            assert config.MODEL == "gpt-4o-2024-08-06"
    
    def test_set_model_with_unknown_model(self):
        """Test set_model with an unknown model."""
        # Mock a complete model config (updated keys)
        mock_config = {
            "model_mapping": {"gpt4o": "gpt-4o-2024-08-06"},
            "conversation_history_mapping": {"gpt4o": 50},
            "context_window_mapping": {"gpt4o": 128000},
            "output_window_mapping": {"gpt4o": 4096},
            "model_max_tpm": {"gpt4o": 10000},
            "openai_model_tpm_tier": {10000: 30000},
            "anthropic_model_tpm_tier": {},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config):
            # First call load_model_config as required
            config.load_model_config()
            
            # First set a valid model to establish baseline
            config.set_model("gpt4o")
            assert config.MODEL == "gpt-4o-2024-08-06"
            baseline_model = config.MODEL

            # Unknown model should be a no-op and return False
            ok = config.set_model("unknown-model")
            assert ok is False
            assert config.MODEL == baseline_model
    
    def test_set_model_with_none_model_mapping(self):
        """Test set_model when MODEL_MAPPING is None."""
        config.MODEL_MAPPING = None
        
        # Should return False and keep existing state
        old_model = getattr(config, "MODEL", None)
        ok = config.set_model("gpt4")
        assert ok is False
        assert getattr(config, "MODEL", None) == old_model


class TestConfigLoading:
    """Test configuration loading functionality."""
    
    def setup_method(self):
        """Reset config state before each test."""
        config._MODEL_CONFIG_CACHE = None
        config.MODEL_MAPPING = None
    
    def test_load_model_config_success(self):
        """Test successful model config loading."""
        mock_config = {
            "model_mapping": {"gpt4o": "gpt-4o-2024-08-06"},
            "conversation_history_mapping": {"gpt4o": 8000},
            "context_window_mapping": {"gpt4o": 128000},
            "output_window_mapping": {"gpt4o": 4096},
            "model_max_tpm": {"gpt4o": 10000},
            "openai_model_tpm_tier": {10000: 30000},
            "anthropic_model_tpm_tier": {},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config):
            config.load_model_config()
            
        assert config._MODEL_CONFIG_CACHE == mock_config
        assert config.MODEL_MAPPING == {"gpt4o": "gpt-4o-2024-08-06"}
        assert config.conversation_history_mapping == {"gpt4o": 8000}
        assert config.context_window_mapping == {"gpt4o": 128000}
    
    def test_load_model_config_exception_handling(self):
        """Test config loading with exception handling."""
        with patch('monitor.config._load_and_validate_model_config', side_effect=Exception("Config error")):
            # Should raise an exception rather than setting defaults
            with pytest.raises(Exception):
                config.load_model_config()
    
    def test_config_caching(self):
        """Test that config is properly cached."""
        mock_config = {
            "model_mapping": {"gpt4": "gpt-4-turbo-preview"},
            "conversation_history_mapping": {},
            "context_window_mapping": {},
            "output_window_mapping": {},
            "model_max_tpm": {},
            "openai_model_tpm_tier": {},
            "anthropic_model_tpm_tier": {},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config) as mock_load:
            # First call should load config
            config.load_model_config()
            assert mock_load.call_count == 1
            
            # Cache should be populated
            assert config._MODEL_CONFIG_CACHE is not None


class TestModelValidation:
    """Test model validation and related utilities."""
    
    def setup_method(self):
        """Setup test data."""
        config.MODEL_MAPPING = {
            "gpt4": "gpt-4-turbo-preview",
            "gpt35": "gpt-3.5-turbo",
            "claude": "claude-3-sonnet-20240229"
        }
    
    def test_model_key_validation(self):
        """Test validation of model keys."""
        # Valid keys
        assert "gpt4" in config.MODEL_MAPPING
        assert "claude" in config.MODEL_MAPPING
        
        # Invalid keys
        assert "invalid-key" not in config.MODEL_MAPPING
    
    def test_model_value_validation(self):
        """Test validation of model values."""
        model_values = list(config.MODEL_MAPPING.values())
        
        # Valid values
        assert "gpt-4-turbo-preview" in model_values
        assert "claude-3-sonnet-20240229" in model_values
        
        # Invalid values
        assert "invalid-model" not in model_values


class TestTPMMapping:
    """Test TPM (Tokens Per Minute) mapping functionality."""
    
    def test_model_tpm_mapping_structure(self):
        """Test that model_tpm_mapping has expected structure."""
        # Mock config loading
        mock_config = {
            "model_mapping": {"gpt4o": "gpt-4o-2024-08-06"},
            "conversation_history_mapping": {},
            "context_window_mapping": {},
            "output_window_mapping": {},
            "model_max_tpm": {"gpt4o": 10000},
            "openai_model_tpm_tier": {10000: "tier-1"},
            "anthropic_model_tpm_tier": {},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=mock_config):
            config.load_model_config()
            
        # Check that model_tpm_mapping is created with expected model keys
        assert hasattr(config, 'model_tpm_mapping')
        assert config.model_tpm_mapping is not None
        
        # Should contain model key mappings to tier mappings
        expected_model_keys = [
        "sonnet4", 
        "sonnet35", 
        "sonnet37", 
        "4o-mini", 
        "gpt4o", 
        "o3-mini", 
        "gpt41", 
        "o3", 
        "grok3", 
        "grok4", 
        "gemini20",
        "gpt5"
        ]
        for model_key in expected_model_keys:
            assert model_key in config.model_tpm_mapping


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_empty_model_mapping(self):
        """Test behavior with empty MODEL_MAPPING."""
        config.MODEL_MAPPING = {}
        
        reverse_mapping = config.get_model_reverse_mapping()
        assert reverse_mapping == {}
    
    def test_none_model_mapping_for_reverse_mapping(self):
        """Test behavior when MODEL_MAPPING is None for reverse mapping."""
        config.MODEL_MAPPING = None
        
        # Should raise AttributeError when trying to call .items() on None
        with pytest.raises(AttributeError):
            config.get_model_reverse_mapping()
    
    def test_malformed_model_mapping(self):
        """Test behavior with malformed model mapping data."""
        # This would be caught during config validation, but test defensive coding
        config.MODEL_MAPPING = "not-a-dict"
        
        with pytest.raises(AttributeError):
            list(config.MODEL_MAPPING.keys())


class TestSetModelBehavior:
    """Test detailed set_model behavior after config loading."""
    
    def setup_method(self):
        """Reset config state and load test config before each test."""
        config._MODEL_CONFIG_CACHE = None
        config.MODEL_MAPPING = None
        
        # Load a standard test config
        self.mock_config = {
            "model_mapping": {
                "gpt4o": "gpt-4o-2024-08-06",
                "sonnet35": "claude-3-5-sonnet-20241022"
            },
            "conversation_history_mapping": {"gpt4o": 100, "sonnet35": 80},
            "context_window_mapping": {"gpt4o": 128000, "sonnet35": 200000},
            "output_window_mapping": {"gpt4o": 4096, "sonnet35": 8192},
            "model_max_tpm": {"gpt4o": 10000, "sonnet35": 20000},
            "openai_model_tpm_tier": {10000: 30000},
            "anthropic_model_tpm_tier": {20000: 40000},
            "xai_model_tpm_tier": {},
            "google_model_tpm_tier": {}
        }
        
        with patch('monitor.config._load_and_validate_model_config', return_value=self.mock_config):
            config.load_model_config()
    
    def test_set_model_updates_all_globals(self):
        """Test that set_model updates all related global variables."""
        # Set a model and verify all globals are updated
        config.set_model("gpt4o")
        
        assert config.MODEL == "gpt-4o-2024-08-06"
        assert config.MODEL_CONTEXT_WINDOW == 128000
        assert config.MODEL_OUTPUT_WINDOW == 4096
        assert config.CONVERSATION_MAX_SIZE == 100
        assert config.MAX_TOKEN_COUNT == 128000
        assert config.TOTAL_TOKEN_COUNT == 0
        assert config.CONVERSATION_HISTORY == []
    
    def test_set_model_noop_for_unknown_model(self):
        """Test that unknown models are a no-op and do not change state."""
        # First set a valid model to establish baseline
        config.set_model("gpt4o")
        baseline_model = config.MODEL
        baseline_history_len = len(config.CONVERSATION_HISTORY)
        
        # Now attempt to set an unknown model; should return False and not change state
        ok = config.set_model("some-unknown-model")
        assert ok is False
        assert config.MODEL == baseline_model
        assert len(config.CONVERSATION_HISTORY) == baseline_history_len


if __name__ == "__main__":
    pytest.main([__file__])
