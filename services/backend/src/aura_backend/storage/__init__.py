"""
Storage abstraction for object storage (local filesystem, S3, etc.).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from ..config import get_settings

# Private prefixes that require signed URLs
PRIVATE_PREFIXES = ("captures/", "generated/")
# Max key length to prevent abuse
MAX_KEY_LENGTH = 512
# Allowed key pattern: alphanumeric, /, ., -, _
KEY_PATTERN = re.compile(r"^[a-zA-Z0-9._\-/]+$")


def sanitize_key(key: str) -> str:
    """Validate and sanitize storage key to prevent path traversal."""
    if not key or len(key) > MAX_KEY_LENGTH:
        raise ValueError("Invalid key length")
    # Reject absolute paths, traversal, null bytes, leading slash
    if key.startswith("/") or ".." in key or "\x00" in key or "//" in key:
        raise ValueError("Invalid key: path traversal detected")
    if not KEY_PATTERN.match(key):
        raise ValueError("Invalid key: illegal characters")
    # Normalize but reject if normalized differs and contains traversal
    normalized = os.path.normpath(key).replace("\\", "/")
    if normalized != key:
        # Allow only if normalization doesn't change traversal semantics
        if ".." in normalized or normalized.startswith("/"):
            raise ValueError("Invalid key: path traversal after normalization")
    return key


def create_signed_url(key: str, ttl_sec: int | None = None) -> str:
    """Create a short-lived signed URL for private objects."""
    s = get_settings()
    ttl = ttl_sec or s.storage_signed_url_ttl_sec
    sanitized = sanitize_key(key)
    expires = int(time.time()) + ttl
    payload = f"{sanitized}:{expires}".encode()
    sig = hmac.new(s.storage_signing_secret.encode(), payload, hashlib.sha256).hexdigest()
    # Use base64url for key to keep URL safe, but keep key readable for routing
    return f"/api/v1/storage/{sanitized}?expires={expires}&signature={sig}"


def verify_signed_url(key: str, expires: str, signature: str) -> bool:
    """Verify a signed URL."""
    try:
        sanitized = sanitize_key(key)
        exp = int(expires)
        if exp < int(time.time()):
            return False
        s = get_settings()
        payload = f"{sanitized}:{exp}".encode()
        expected = hmac.new(s.storage_signing_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def is_private_key(key: str) -> bool:
    """Check if key requires signed URL."""
    return any(key.startswith(prefix) for prefix in PRIVATE_PREFIXES)


class StorageBackend(ABC):
    """Abstract storage backend."""
    
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store data and return the key."""
        ...
    
    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve data by key."""
        ...
    
    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete data by key."""
        ...
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        ...
    
    @abstractmethod
    def get_url(self, key: str) -> str:
        """Get public URL for key."""
        ...


class LocalStorage(StorageBackend):
    """Local filesystem storage backend."""
    
    def __init__(self, base_path: str = "./data/storage"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        sanitized = sanitize_key(key)
        path = self.base_path / sanitized
        # Ensure the resolved path stays within base_path (prevent traversal)
        try:
            path.resolve().relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError("Path traversal detected")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return sanitized
    
    def get(self, key: str) -> bytes:
        sanitized = sanitize_key(key)
        path = self.base_path / sanitized
        try:
            path.resolve().relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError("Path traversal detected")
        if not path.exists():
            raise FileNotFoundError(f"Key not found: {sanitized}")
        return path.read_bytes()
    
    def delete(self, key: str) -> None:
        sanitized = sanitize_key(key)
        path = self.base_path / sanitized
        try:
            path.resolve().relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError("Path traversal detected")
        if path.exists():
            path.unlink()
    
    def exists(self, key: str) -> bool:
        try:
            sanitized = sanitize_key(key)
            path = self.base_path / sanitized
            path.resolve().relative_to(self.base_path.resolve())
            return path.exists()
        except Exception:
            return False
    
    def get_url(self, key: str) -> str:
        sanitized = sanitize_key(key)
        # Private objects get short-lived signed URLs
        if is_private_key(sanitized):
            return create_signed_url(sanitized)
        # Public assets (thumbnails, etc.) can be served directly via storage endpoint
        # but still require validation on the server side
        return f"/api/v1/storage/{sanitized}"


class S3Storage(StorageBackend):
    """S3-compatible storage backend (MinIO, AWS S3, etc.)."""
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        bucket: str = "aura",
    ):
        import boto3
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        # Ensure bucket exists
        try:
            self.client.head_bucket(Bucket=bucket)
        except Exception:
            self.client.create_bucket(Bucket=bucket)
    
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key
    
    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()
    
    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
    
    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False
    
    def get_url(self, key: str) -> str:
        from ..config import get_settings
        s = get_settings()
        return f"{s.s3_public_base_url.rstrip('/')}/{key}"


_storage: "StorageBackend | None" = None


def get_storage() -> "StorageBackend":
    """Get the configured storage backend."""
    global _storage
    if _storage is None:
        s = get_settings()
        if s.s3_endpoint and s.s3_endpoint != "http://localhost:9000":
            # Use S3-compatible storage
            _storage = S3Storage(
                endpoint=s.s3_endpoint,
                access_key=s.s3_access_key,
                secret_key=s.s3_secret_key,
                region=s.s3_region,
                bucket=s.s3_bucket_captures,
            )
        else:
            # Use local filesystem rooted at the backend data_dir so CWD at
            # launch (repo root vs services/backend) resolves to the same dir.
            _storage = LocalStorage(str(s.data_dir / "storage"))
    return _storage


def set_storage(backend: "StorageBackend") -> None:
    """Override the storage backend (for testing)."""
    global _storage
    _storage = backend