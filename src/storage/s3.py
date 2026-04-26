"""
S3 storage helpers for all 3 buckets.

All S3 access in the system MUST go through these helpers.
Never instantiate boto3 clients directly in agent or tool code.

Buckets (resolved from env vars):
  - golden-dataset  → S3_BUCKET_GOLDEN_DATASET
  - eval-results    → S3_BUCKET_EVAL_RESULTS
  - artifacts       → S3_BUCKET_ARTIFACTS
"""

import os
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Mock store (used when MOCK_STORAGE=true)
# ---------------------------------------------------------------------------

# Module-level mock store — persists across calls within a process.
# Structure: { bucket_name: { object_key: bytes } }
_MOCK_STORE: Dict[str, Dict[str, bytes]] = {
    "golden-dataset": {},
    "eval-results": {},
    "artifacts": {},
}


def _is_mock() -> bool:
    return os.getenv("MOCK_STORAGE", "").lower() == "true"


# ---------------------------------------------------------------------------
# boto3 client (lazy-initialised, only when not mocking)
# ---------------------------------------------------------------------------

_s3_client = None


def _get_client():
    global _s3_client
    if _s3_client is None:
        import boto3

        region = os.getenv("AWS_REGION", "us-east-1")
        _s3_client = boto3.client("s3", region_name=region)
    return _s3_client


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_object(bucket_name: str, key: str) -> bytes:
    """
    Return the body of the object at *key* in *bucket_name*.

    Raises ``KeyError`` in mock mode when the object does not exist.
    Raises ``botocore.exceptions.ClientError`` in live mode when the object
    does not exist.
    """
    if _is_mock():
        bucket = _MOCK_STORE.get(bucket_name, {})
        if key not in bucket:
            raise KeyError(f"Object not found in mock store: bucket={bucket_name!r}, key={key!r}")
        return bucket[key]

    response = _get_client().get_object(Bucket=bucket_name, Key=key)
    return response["Body"].read()


def put_object(
    bucket_name: str,
    key: str,
    body: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    """Write *body* to *key* in *bucket_name*."""
    if _is_mock():
        _MOCK_STORE.setdefault(bucket_name, {})[key] = body
        return

    _get_client().put_object(
        Bucket=bucket_name,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def list_objects(bucket_name: str, prefix: str = "") -> List[Dict[str, Any]]:
    """
    List objects in *bucket_name* under *prefix*.

    Returns a list of dicts with keys: ``key``, ``size``, ``last_modified``.
    """
    if _is_mock():
        bucket = _MOCK_STORE.get(bucket_name, {})
        return [
            {"key": k, "size": len(v), "last_modified": None}
            for k, v in bucket.items()
            if k.startswith(prefix)
        ]

    paginator = _get_client().get_paginator("list_objects_v2")
    results: List[Dict[str, Any]] = []
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            results.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                }
            )
    return results
