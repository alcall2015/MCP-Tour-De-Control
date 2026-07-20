import importlib
import os
import pytest

# Must set before importing app modules that read settings at module level
os.environ["ENCRYPTION_KEY"] = "nHlluIaJjW5FGjaUt0P9bfOgUPKYD5UiDjRZdze4mzI="  # valid Fernet key

# Reload settings so it picks up the env var set above
import app.config
importlib.reload(app.config)

from app.utils.crypto import encrypt_value, decrypt_value, generate_key


def test_encrypt_decrypt_roundtrip():
    original = "sk-test-api-key-12345"
    encrypted = encrypt_value(original)
    assert encrypted != original
    decrypted = decrypt_value(encrypted)
    assert decrypted == original


def test_encrypt_produces_different_ciphertexts():
    value = "same-value"
    a = encrypt_value(value)
    b = encrypt_value(value)
    assert a != b  # Fernet uses random IV


def test_generate_key_returns_valid_key():
    key = generate_key()
    assert isinstance(key, str)
    assert len(key) > 20
