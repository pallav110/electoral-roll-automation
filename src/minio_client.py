"""
MinIO Client for ECI Electoral Roll Downloader
Handles upload of downloaded PDFs and ZIPs to MinIO object storage.
"""

import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from minio import Minio
from minio.error import S3Error
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class MinIOClient:
    """MinIO client for uploading electoral roll files."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None,
        secure: bool = False
    ):
        """
        Initialize MinIO client.

        Args:
            endpoint: MinIO endpoint (e.g., 'localhost:9000' or 'minio.example.com')
            access_key: MinIO access key
            secret_key: MinIO secret key
            bucket: Default bucket name
            secure: Use HTTPS (True) or HTTP (False)
        """
        self.endpoint = endpoint or os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = access_key or os.environ.get("MINIO_ACCESS_KEY")
        self.secret_key = secret_key or os.environ.get("MINIO_SECRET_KEY")
        self.bucket = bucket or os.environ.get("MINIO_BUCKET", "electoral-rolls")
        self.secure = secure

        self.client: Optional[Minio] = None

        if self.access_key and self.secret_key:
            self._initialize_client()
        else:
            print("[!] MinIO credentials not provided. Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY environment variables.")

    def _initialize_client(self):
        """Initialize the MinIO client."""
        try:
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure
            )

            # Create bucket if it doesn't exist
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                print(f"[+] Created bucket: {self.bucket}")
            else:
                print(f"[+] Using existing bucket: {self.bucket}")

        except S3Error as e:
            print(f"[!] MinIO initialization error: {e}")
            self.client = None

    def is_configured(self) -> bool:
        """Check if MinIO client is properly configured."""
        return self.client is not None

    def upload_file(
        self,
        file_path: Path,
        object_name: Optional[str] = None,
        bucket: Optional[str] = None
    ) -> bool:
        """
        Upload a single file to MinIO.

        Args:
            file_path: Local path to file
            object_name: Object name in MinIO (defaults to relative path)
            bucket: Bucket name (defaults to instance bucket)

        Returns:
            True if successful, False otherwise
        """
        if not self.is_configured():
            print("[!] MinIO client not configured")
            return False

        if not file_path.exists():
            print(f"[!] File not found: {file_path}")
            return False

        bucket = bucket or self.bucket
        object_name = object_name or str(file_path)

        try:
            self.client.fput_object(
                bucket,
                object_name,
                str(file_path),
                content_type=self._get_content_type(file_path)
            )
            print(f"[+] Uploaded: {object_name} -> s3://{bucket}/{object_name}")
            return True
        except S3Error as e:
            print(f"[!] Upload failed for {file_path}: {e}")
            return False

    def upload_directory(
        self,
        directory: Path,
        prefix: str = "",
        bucket: Optional[str] = None,
        extensions: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """
        Upload all files in a directory to MinIO.

        Args:
            directory: Local directory to upload
            prefix: Prefix for object names (e.g., 'downloads/')
            bucket: Bucket name
            extensions: File extensions to upload (e.g., ['.pdf', '.zip'])

        Returns:
            Dictionary with 'uploaded' and 'failed' counts
        """
        if not self.is_configured():
            print("[!] MinIO client not configured")
            return {"uploaded": 0, "failed": 0}

        if not directory.exists():
            print(f"[!] Directory not found: {directory}")
            return {"uploaded": 0, "failed": 0}

        bucket = bucket or self.bucket
        uploaded = 0
        failed = 0

        for file_path in directory.rglob("*"):
            if file_path.is_file():
                if extensions and file_path.suffix.lower() not in extensions:
                    continue

                # Create object name with prefix
                relative_path = file_path.relative_to(directory)
                object_name = f"{prefix}{relative_path}".replace("\\", "/")

                if self.upload_file(file_path, object_name, bucket):
                    uploaded += 1
                else:
                    failed += 1

        print(f"[+] Directory upload complete: {uploaded} uploaded, {failed} failed")
        return {"uploaded": uploaded, "failed": failed}

    def upload_download_log(self, log_path: Path, bucket: Optional[str] = None) -> bool:
        """Upload download_log.json to MinIO."""
        bucket = bucket or self.bucket
        return self.upload_file(log_path, "download_log.json", bucket)

    def upload_all_organized(
        self,
        output_folder: Path = Path("downloaded_pdfs"),
        zip_files: Optional[List[Path]] = None,
        bucket: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload everything in an organized manner.

        Args:
            output_folder: Folder containing downloaded PDFs
            zip_files: List of ZIP files to upload
            bucket: Bucket name

        Returns:
            Summary of upload results
        """
        bucket = bucket or self.bucket
        results = {
            "pdfs": {"uploaded": 0, "failed": 0},
            "zips": {"uploaded": 0, "failed": 0},
            "log": False
        }

        # Upload PDFs organized by state
        if output_folder.exists():
            print(f"[*] Uploading PDFs from {output_folder}...")
            pdf_result = self.upload_directory(
                output_folder,
                prefix="pdfs/",
                bucket=bucket,
                extensions=[".pdf"]
            )
            results["pdfs"] = pdf_result

        # Upload ZIP files
        if zip_files:
            print("[*] Uploading ZIP files...")
            for zip_path in zip_files:
                if zip_path.exists():
                    object_name = f"archives/{zip_path.name}"
                    if self.upload_file(zip_path, object_name, bucket):
                        results["zips"]["uploaded"] += 1
                    else:
                        results["zips"]["failed"] += 1

        # Upload download log
        log_path = Path("download_log.json")
        if log_path.exists():
            results["log"] = self.upload_download_log(log_path, bucket)

        return results

    def list_objects(self, prefix: str = "", bucket: Optional[str] = None) -> List[Dict[str, Any]]:
        """List objects in bucket with given prefix."""
        if not self.is_configured():
            return []

        bucket = bucket or self.bucket
        objects = []

        try:
            for obj in self.client.list_objects(bucket, prefix=prefix, recursive=True):
                objects.append({
                    "name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                    "etag": obj.etag
                })
        except S3Error as e:
            print(f"[!] List objects failed: {e}")

        return objects

    def download_object(
        self,
        object_name: str,
        file_path: Path,
        bucket: Optional[str] = None
    ) -> bool:
        """Download an object from MinIO."""
        if not self.is_configured():
            return False

        bucket = bucket or self.bucket

        try:
            self.client.fget_object(bucket, object_name, str(file_path))
            print(f"[+] Downloaded: s3://{bucket}/{object_name} -> {file_path}")
            return True
        except S3Error as e:
            print(f"[!] Download failed: {e}")
            return False

    def _get_content_type(self, file_path: Path) -> str:
        """Determine content type based on file extension."""
        ext = file_path.suffix.lower()
        content_types = {
            ".pdf": "application/pdf",
            ".zip": "application/zip",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".txt": "text/plain",
        }
        return content_types.get(ext, "application/octet-stream")


def create_minio_client_from_env() -> MinIOClient:
    """Create MinIO client from environment variables."""
    return MinIOClient()


if __name__ == "__main__":
    # Test MinIO connection
    client = create_minio_client_from_env()

    if client.is_configured():
        print("[+] MinIO client configured successfully")

        # List objects
        objects = client.list_objects()
        print(f"[*] Objects in bucket: {len(objects)}")
        for obj in objects[:10]:  # Show first 10
            print(f"  - {obj['name']} ({obj['size']} bytes)")
    else:
        print("[!] MinIO not configured. Set environment variables:")
        print("    MINIO_ENDPOINT=localhost:9000")
        print("    MINIO_ACCESS_KEY=your_access_key")
        print("    MINIO_SECRET_KEY=your_secret_key")
        print("    MINIO_BUCKET=electoral-rolls")