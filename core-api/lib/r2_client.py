"""
Cloudflare R2 storage client using S3-compatible API via boto3
"""
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import BinaryIO, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid
import os
import logging

from api.config import settings
from lib.filename_utils import sanitize_filename

logger = logging.getLogger(__name__)


class R2ConfigurationError(RuntimeError):
    """Raised when R2 storage is not configured enough to perform uploads."""


def _require_setting(value: str, name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise R2ConfigurationError("Storage upload is not configured")
    if name == "R2_S3_API" and not value.startswith(("http://", "https://")):
        raise R2ConfigurationError("Storage upload is not configured")
    return value


class R2Client:
    """Cloudflare R2 storage client using S3-compatible API"""

    def __init__(self):
        self.bucket_name = _require_setting(settings.r2_bucket_name, "R2_BUCKET_NAME")
        self.presigned_url_expiry = settings.r2_presigned_url_expiry
        self.max_file_size = settings.r2_max_file_size
        endpoint_url = _require_setting(settings.r2_s3_api, "R2_S3_API")
        access_key_id = _require_setting(settings.r2_access_key_id, "R2_ACCESS_KEY_ID")
        secret_access_key = _require_setting(settings.r2_secret_access_key, "R2_SECRET_ACCESS_KEY")

        # Initialize S3 client for R2
        self.s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version='s3v4'),
            region_name='auto'  # R2 uses 'auto' for region
        )
        logger.info(f"✅ R2 client initialized for bucket: {self.bucket_name}")

    def _generate_key(self, user_id: str, filename: str) -> str:
        """
        Generate a unique R2 object key.
        Format: files/{user_id}/{YYYYMMDD}/{uuid}.{ext}
        """
        filename = sanitize_filename(filename)
        # Extract file extension
        ext = os.path.splitext(filename)[1].lower() if '.' in filename else ''

        # Generate unique key
        timestamp = datetime.utcnow().strftime('%Y%m%d')
        unique_id = str(uuid.uuid4())

        return f"files/{user_id}/{timestamp}/{unique_id}{ext}"

    def upload_file(
        self,
        file_data: BinaryIO,
        filename: str,
        content_type: str,
        user_id: str,
        file_size: int,
    ) -> dict:
        """
        Upload a file to R2 using streaming (memory efficient).

        Args:
            file_data: Binary file data (file-like object)
            filename: Original filename
            content_type: MIME type
            user_id: User ID for namespacing
            file_size: Pre-calculated file size in bytes

        Returns:
            dict with r2_key and metadata
        """
        # Generate unique key
        r2_key = self._generate_key(user_id, filename)

        try:
            # Stream upload to R2 using upload_fileobj (doesn't load into memory)
            self.s3_client.upload_fileobj(
                file_data,
                self.bucket_name,
                r2_key,
                ExtraArgs={
                    'ContentType': content_type,
                    'Metadata': {
                        'user_id': user_id,
                        'original_filename': filename,
                        'uploaded_at': datetime.utcnow().isoformat()
                    }
                }
            )

            logger.info(f"📤 Uploaded file to R2: {r2_key} ({file_size} bytes)")

            return {
                'r2_key': r2_key,
                'filename': filename,
                'file_type': content_type,
                'file_size': file_size,
            }

        except ClientError as e:
            logger.error(f"❌ Failed to upload to R2: {e}")
            raise

    def get_presigned_url(
        self,
        r2_key: str,
        expiration: Optional[int] = None
    ) -> str:
        """
        Generate a presigned URL for downloading a file.

        Args:
            r2_key: The R2 object key
            expiration: URL expiration in seconds (default: from settings)

        Returns:
            Presigned URL string
        """
        if expiration is None:
            expiration = self.presigned_url_expiry

        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': r2_key
                },
                ExpiresIn=expiration
            )
            logger.info(f"🔗 Generated presigned URL for: {r2_key} (expires in {expiration}s)")
            return url

        except ClientError as e:
            logger.error(f"❌ Failed to generate presigned URL: {e}")
            raise

    def delete_file(self, r2_key: str, bucket: Optional[str] = None) -> bool:
        """
        Delete a file from R2.

        Args:
            r2_key: The R2 object key to delete
            bucket: Override bucket name (default: from settings)

        Returns:
            True if successful
        """
        target_bucket = _require_setting(bucket or self.bucket_name, "R2_BUCKET_NAME")
        try:
            self.s3_client.delete_object(
                Bucket=target_bucket,
                Key=r2_key
            )
            logger.info(f"🗑️ Deleted file from R2: {r2_key}")
            return True

        except ClientError as e:
            logger.error(f"❌ Failed to delete from R2: {e}")
            raise

    def file_exists(self, r2_key: str, bucket: Optional[str] = None) -> bool:
        """
        Check if a file exists in R2.

        Args:
            r2_key: The R2 object key
            bucket: Override bucket name (default: from settings)

        Returns:
            True if file exists
        """
        target_bucket = _require_setting(bucket or self.bucket_name, "R2_BUCKET_NAME")
        try:
            self.s3_client.head_object(
                Bucket=target_bucket,
                Key=r2_key
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise

    def get_object_metadata(self, r2_key: str) -> Optional[Dict[str, Any]]:
        """
        Get file metadata from R2.

        Args:
            r2_key: The R2 object key

        Returns:
            dict with content_length, content_type, last_modified, or None if not found
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=r2_key
            )
            return {
                'content_length': response.get('ContentLength'),
                'content_type': response.get('ContentType'),
                'last_modified': response.get('LastModified'),
            }
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            raise

    def generate_presigned_put_url(
        self,
        r2_key: str,
        content_type: str,
        expiration: Optional[int] = None,
        bucket: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate presigned PUT URL for direct client upload.

        Args:
            r2_key: The full R2 object key
            content_type: MIME type for the upload
            expiration: URL validity in seconds (default: from settings)
            bucket: Override bucket name (default: from settings)

        Returns:
            dict with url, expires_at
        """
        if expiration is None:
            expiration = settings.r2_upload_url_expiry

        target_bucket = _require_setting(bucket or self.bucket_name, "R2_BUCKET_NAME")

        try:
            url = self.s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': target_bucket,
                    'Key': r2_key,
                    'ContentType': content_type,
                },
                ExpiresIn=expiration,
                HttpMethod='PUT'
            )

            expires_at = datetime.utcnow() + timedelta(seconds=expiration)

            logger.info(f"🔗 Generated presigned PUT URL for: {r2_key} (expires in {expiration}s)")

            return {
                'url': url,
                'expires_at': expires_at.isoformat() + 'Z',
            }

        except ClientError as e:
            logger.error(f"❌ Failed to generate presigned PUT URL: {e}")
            raise

    def generate_key_for_context(
        self,
        user_id: str,
        filename: str,
        context: str = "files",
    ) -> str:
        """
        Generate R2 key with context-based prefix.

        Keys: {context}/{user_id}/{YYYYMMDD}/{uuid}.{ext}

        Args:
            user_id: User ID for namespacing
            filename: Original filename (used for extension)
            context: Upload context (files, notes, chat, email)

        Returns:
            The generated R2 object key
        """
        filename = sanitize_filename(filename)
        # Extract file extension
        ext = os.path.splitext(filename)[1].lower() if '.' in filename else ''

        # Generate unique key
        timestamp = datetime.utcnow().strftime('%Y%m%d')
        unique_id = str(uuid.uuid4())

        return f"{context}/{user_id}/{timestamp}/{unique_id}{ext}"

    def list_files(
        self,
        prefix: str = '',
        max_keys: int = 1000
    ) -> list:
        """
        List files in R2 with optional prefix filter.

        Args:
            prefix: Filter by key prefix (e.g., 'files/{user_id}/')
            max_keys: Maximum number of keys to return

        Returns:
            List of file metadata dicts
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )

            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                })

            logger.info(f"📋 Listed {len(files)} files with prefix: {prefix}")
            return files

        except ClientError as e:
            logger.error(f"❌ Failed to list files: {e}")
            raise


# Singleton instance
_r2_client: Optional[R2Client] = None


def get_r2_client() -> R2Client:
    """Get or create the R2 client singleton."""
    global _r2_client
    if _r2_client is None:
        _r2_client = R2Client()
    return _r2_client
