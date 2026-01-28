# -*- coding: utf-8 -*-
"""
StorageService - Client S3 pour le stockage des documents.

Gère le stockage et la récupération des documents originaux sur S3 Cloud Temple.
"""

import os
import hashlib
import sys
from typing import Optional, BinaryIO
from datetime import datetime, timedelta
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError

from ..config import get_settings


class StorageService:
    """
    Service de stockage S3 pour les documents.
    
    Responsabilités:
    - Upload de documents vers S3
    - Download de documents depuis S3
    - Génération d'URLs signées
    - Vérification d'existence
    - Suppression de documents
    """
    
    def __init__(self):
        """Initialise les clients S3 avec signatures adaptées."""
        settings = get_settings()
        
        # Désactiver le calcul du checksum par le SDK
        os.environ["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
        
        # Région Dell ECS Cloud Temple
        region = settings.s3_region_name if settings.s3_region_name else "fr1"
        
        # Client SigV2 pour PUT/GET/DELETE (opérations sur objets)
        # Tests validés: PUT ✅, GET ✅, DELETE ✅
        config_v2 = Config(
            region_name=region,
            signature_version='s3',  # SigV2 legacy
            s3={'addressing_style': 'path'},
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        
        self._client_v2 = boto3.client(
            's3',
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=region,
            config=config_v2
        )
        
        # Client SigV4 pour HEAD/LIST (opérations métadonnées)
        # Utilisé en fallback si SigV2 échoue sur ces opérations
        config_v4 = Config(
            region_name=region,
            signature_version='s3v4',
            s3={'addressing_style': 'path', 'payload_signing_enabled': False},
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        
        self._client_v4 = boto3.client(
            's3',
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=region,
            config=config_v4
        )
        
        # Client par défaut (SigV2 pour compatibilité maximale)
        self._client = self._client_v2
        
        self._bucket = settings.s3_bucket_name
        self._endpoint_url = settings.s3_endpoint_url
    
    def _get_key(self, memory_id: str, filename: str, doc_hash: Optional[str] = None) -> str:
        """
        Construit la clé S3 pour un document.
        
        Format: {memory_id}/documents/{hash}_{filename}
        ou si pas de hash: {memory_id}/documents/{filename}
        """
        if doc_hash:
            # Utilise les 8 premiers caractères du hash pour unicité
            return f"{memory_id}/documents/{doc_hash[:8]}_{filename}"
        return f"{memory_id}/documents/{filename}"
    
    @staticmethod
    def compute_hash(content: bytes) -> str:
        """Calcule le hash SHA256 d'un contenu."""
        return hashlib.sha256(content).hexdigest()
    
    async def upload_document(
        self,
        memory_id: str,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> dict:
        """
        Upload un document vers S3.
        
        Args:
            memory_id: ID de la mémoire
            filename: Nom du fichier
            content: Contenu binaire du document
            content_type: Type MIME (optionnel, détecté sinon)
            metadata: Métadonnées additionnelles
            
        Returns:
            dict avec uri, hash, size_bytes
        """
        doc_hash = self.compute_hash(content)
        key = self._get_key(memory_id, filename, doc_hash)
        
        # Détection du content-type si non fourni
        if not content_type:
            content_type = self._guess_content_type(filename)
        
        # Métadonnées S3
        s3_metadata = {
            'memory_id': memory_id,
            'original_filename': filename,
            'doc_hash': doc_hash,
            'uploaded_at': datetime.utcnow().isoformat()
        }
        if metadata:
            # Les metadata S3 doivent être des strings
            for k, v in metadata.items():
                s3_metadata[k] = str(v)
        
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                Metadata=s3_metadata
            )
            
            uri = f"s3://{self._bucket}/{key}"
            
            print(f"📤 [S3] Document uploadé: {uri}", file=sys.stderr)
            
            return {
                "uri": uri,
                "key": key,
                "hash": doc_hash,
                "size_bytes": len(content),
                "content_type": content_type
            }
            
        except ClientError as e:
            print(f"❌ [S3] Erreur upload: {e}", file=sys.stderr)
            raise
    
    async def download_document(self, memory_id: str, key_or_uri: str) -> bytes:
        """
        Télécharge un document depuis S3.
        
        Args:
            memory_id: ID de la mémoire (pour vérification)
            key_or_uri: Clé S3 ou URI complète (s3://bucket/key)
            
        Returns:
            Contenu binaire du document
        """
        key = self._parse_key(key_or_uri)
        
        # Vérification que le document appartient à la mémoire
        if not key.startswith(f"{memory_id}/"):
            raise PermissionError(f"Document n'appartient pas à la mémoire {memory_id}")
        
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            content = response['Body'].read()
            
            print(f"📥 [S3] Document téléchargé: {key} ({len(content)} bytes)", file=sys.stderr)
            return content
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise FileNotFoundError(f"Document non trouvé: {key}")
            raise
    
    async def delete_document(self, memory_id: str, key_or_uri: str) -> bool:
        """
        Supprime un document de S3.
        
        Args:
            memory_id: ID de la mémoire (pour vérification)
            key_or_uri: Clé S3 ou URI complète
            
        Returns:
            True si supprimé, False si n'existait pas
        """
        key = self._parse_key(key_or_uri)
        
        # Vérification que le document appartient à la mémoire
        if not key.startswith(f"{memory_id}/"):
            raise PermissionError(f"Document n'appartient pas à la mémoire {memory_id}")
        
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            print(f"🗑️ [S3] Document supprimé: {key}", file=sys.stderr)
            return True
            
        except ClientError as e:
            print(f"❌ [S3] Erreur suppression: {e}", file=sys.stderr)
            return False
    
    async def document_exists(self, key_or_uri: str) -> bool:
        """Vérifie si un document existe dans S3."""
        key = self._parse_key(key_or_uri)
        
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False
    
    async def get_signed_url(
        self,
        key_or_uri: str,
        expires_in_seconds: int = 3600
    ) -> str:
        """
        Génère une URL signée pour accéder au document.
        
        Args:
            key_or_uri: Clé S3 ou URI
            expires_in_seconds: Durée de validité (défaut: 1 heure)
            
        Returns:
            URL signée
        """
        key = self._parse_key(key_or_uri)
        
        url = self._client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self._bucket, 'Key': key},
            ExpiresIn=expires_in_seconds
        )
        
        return url
    
    async def list_documents(self, memory_id: str, prefix: str = "") -> list:
        """
        Liste les documents d'une mémoire.
        
        Args:
            memory_id: ID de la mémoire
            prefix: Préfixe additionnel (optionnel)
            
        Returns:
            Liste des objets S3
        """
        full_prefix = f"{memory_id}/documents/{prefix}"
        
        try:
            response = self._client.list_objects_v2(
                Bucket=self._bucket,
                Prefix=full_prefix
            )
            
            objects = []
            for obj in response.get('Contents', []):
                objects.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat()
                })
            
            return objects
            
        except ClientError as e:
            print(f"❌ [S3] Erreur listing: {e}", file=sys.stderr)
            return []
    
    async def test_connection(self) -> dict:
        """
        Teste la connexion S3 en utilisant PUT/GET (compatible SigV2).
        
        Returns:
            dict avec status, bucket, message
        """
        test_key = "_health_check/test.txt"
        test_content = b"health check"
        
        try:
            # Test avec PUT/GET qui fonctionnent avec SigV2
            self._client_v2.put_object(
                Bucket=self._bucket,
                Key=test_key,
                Body=test_content
            )
            
            # Vérifier qu'on peut lire
            response = self._client_v2.get_object(Bucket=self._bucket, Key=test_key)
            content = response['Body'].read()
            
            # Nettoyer
            self._client_v2.delete_object(Bucket=self._bucket, Key=test_key)
            
            if content == test_content:
                return {
                    "status": "ok",
                    "bucket": self._bucket,
                    "endpoint": self._endpoint_url,
                    "message": "Connexion S3 réussie (PUT/GET/DELETE validés)"
                }
            else:
                return {
                    "status": "warning",
                    "bucket": self._bucket,
                    "endpoint": self._endpoint_url,
                    "message": "Connexion OK mais contenu incohérent"
                }
            
        except NoCredentialsError:
            return {
                "status": "error",
                "bucket": self._bucket,
                "endpoint": self._endpoint_url,
                "message": "Credentials S3 invalides ou manquants"
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            return {
                "status": "error",
                "bucket": self._bucket,
                "endpoint": self._endpoint_url,
                "message": f"Erreur S3 [{error_code}]: {error_msg}"
            }
    
    def _parse_key(self, key_or_uri: str) -> str:
        """Extrait la clé S3 d'une URI ou retourne la clé directement."""
        if key_or_uri.startswith("s3://"):
            # Format: s3://bucket/key
            parts = key_or_uri[5:].split("/", 1)
            if len(parts) == 2:
                return parts[1]
            raise ValueError(f"URI S3 invalide: {key_or_uri}")
        return key_or_uri
    
    @staticmethod
    def _guess_content_type(filename: str) -> str:
        """Devine le content-type à partir de l'extension."""
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        
        content_types = {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'doc': 'application/msword',
            'txt': 'text/plain',
            'md': 'text/markdown',
            'json': 'application/json',
            'xml': 'application/xml',
            'html': 'text/html',
            'csv': 'text/csv',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'xls': 'application/vnd.ms-excel',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
        }
        
        return content_types.get(ext, 'application/octet-stream')


# Singleton pour usage global
_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """Retourne l'instance singleton du StorageService."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
