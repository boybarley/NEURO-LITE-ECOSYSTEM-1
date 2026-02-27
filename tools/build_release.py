#!/usr/bin/env python3
import os
import sys
import json
import shutil
import tarfile
import hashlib
import logging
import argparse
import tempfile
import subprocess
from typing import List, Dict, Any, Optional, Set
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("build_release.log")]
)
logger = logging.getLogger("release_builder")

class ReleaseBuilder:
    """Creates a release bundle for the Neuro-Lite system."""
    
    # Required files for a valid release
    REQUIRED_FILES = {
        "install.sh",
        "modules/01_os_tuning.sh",
        "modules/02_install_deps.sh", 
        "modules/03_download_model.sh",
        "modules/04_setup_service.sh",
        "core/main_server.py",
        "core/context_manager.py",
        "core/post_processor.py", 
        "core/rag_engine.py",
        "core/emotional_state.py",
        "core/llama_cpp_adapter.py",
        "webui/index.html",
        "config.env"
    }
    
    # Files that should be executable in the release
    EXECUTABLE_FILES = {
        "install.sh",
        "modules/01_os_tuning.sh",
        "modules/02_install_deps.sh", 
        "modules/03_download_model.sh",
        "modules/04_setup_service.sh"
    }
    
    def __init__(self, source_dir: str, build_dir: str, version: str):
        """Initialize the release builder.
        
        Args:
            source_dir: Source code directory
            build_dir: Build output directory
            version: Version string for the release
        """
        self.source_dir = os.path.abspath(source_dir)
        self.build_dir = os.path.abspath(build_dir)
        self.version = version
        self.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        self.release_name = f"neuro-lite-{version}-{self.timestamp}"
        self.missing_files: Set[str] = set()
        self.db_path: Optional[str] = None
        self.model_path: Optional[str] = None
        
    def validate_source(self) -> bool:
        """Validate that all required files exist in source directory.
        
        Returns:
            True if all required files exist, False otherwise
        """
        logger.info("Validating source files...")
        self.missing_files = set()
        
        for required_file in self.REQUIRED_FILES:
            file_path = os.path.join(self.source_dir, required_file)
            if not os.path.exists(file_path):
                self.missing_files.add(required_file)
                logger.warning(f"Missing required file: {required_file}")
        
        if self.missing_files:
            logger.error(f"Validation failed: {len(self.missing_files)} required files are missing")
            return False
        
        logger.info("Source validation successful")
        return True
    
    def validate_python_files(self) -> bool:
        """Validate Python files for syntax errors.
        
        Returns:
            True if all Python files pass validation, False otherwise
        """
        logger.info("Validating Python files...")
        python_files = []
        
        # Find all Python files
        for root, _, files in os.walk(self.source_dir):
            for file in files:
                if file.endswith('.py'):
                    python_files.append(os.path.join(root, file))
        
        # Validate each Python file
        invalid_files = []
        for py_file in python_files:
            try:
                result = subprocess.run(
                    ["python3", "-m", "py_compile", py_file],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode != 0:
                    invalid_files.append(py_file)
                    logger.warning(f"Invalid Python file: {py_file}")
                    logger.warning(f"Error: {result.stderr}")
            except Exception as e:
                invalid_files.append(py_file)
                logger.warning(f"Error validating {py_file}: {str(e)}")
        
        if invalid_files:
            logger.error(f"Python validation failed: {len(invalid_files)} files have syntax errors")
            return False
        
        logger.info(f"All {len(python_files)} Python files passed validation")
        return True
    
    def validate_shell_scripts(self) -> bool:
        """Validate shell scripts for syntax errors.
        
        Returns:
            True if all shell scripts pass validation, False otherwise
        """
        logger.info("Validating shell scripts...")
        shell_scripts = []
        
        # Find all shell scripts
        for root, _, files in os.walk(self.source_dir):
            for file in files:
                if file.endswith('.sh'):
                    shell_scripts.append(os.path.join(root, file))
        
        # Validate each shell script
        invalid_scripts = []
        for script in shell_scripts:
            try:
                result = subprocess.run(
                    ["bash", "-n", script],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode != 0:
                    invalid_scripts.append(script)
                    logger.warning(f"Invalid shell script: {script}")
                    logger.warning(f"Error: {result.stderr}")
            except Exception as e:
                invalid_scripts.append(script)
                logger.warning(f"Error validating {script}: {str(e)}")
        
        if invalid_scripts:
            logger.error(f"Shell script validation failed: {len(invalid_scripts)} files have syntax errors")
            return False
        
        logger.info(f"All {len(shell_scripts)} shell scripts passed validation")
        return True
    
    def copy_source_files(self, target_dir: str) -> None:
        """Copy source files to target directory.
        
        Args:
            target_dir: Target directory for source files
        """
        logger.info(f"Copying source files to {target_dir}...")
        
        # Create necessary directories
        os.makedirs(target_dir, exist_ok=True)
        
        # Copy files and directories
        for item in os.listdir(self.source_dir):
            source_item = os.path.join(self.source_dir, item)
            target_item = os.path.join(target_dir, item)
            
            if os.path.isdir(source_item):
                if item not in ['.git', '__pycache__', 'tools', 'build']:
                    shutil.copytree(source_item, target_item, dirs_exist_ok=True)
            else:
                shutil.copy2(source_item, target_item)
        
        logger.info("Source files copied successfully")
    
    def set_file_permissions(self, target_dir: str) -> None:
        """Set appropriate file permissions for executable files.
        
        Args:
            target_dir: Target directory with copied files
        """
        logger.info("Setting file permissions...")
        
        for executable in self.EXECUTABLE_FILES:
            file_path = os.path.join(target_dir, executable)
            if os.path.exists(file_path):
                try:
                    # Set executable permission (chmod +x)
                    current_mode = os.stat(file_path).st_mode
                    os.chmod(file_path, current_mode | 0o111)  # Add execute permission for all
                    logger.info(f"Set executable permission for {executable}")
                except Exception as e:
                    logger.warning(f"Failed to set permission for {executable}: {str(e)}")
            else:
                logger.warning(f"Executable file not found: {executable}")
    
    def include_database(self, db_path: str, target_dir: str) -> None:
        """Include knowledge database in the release.
        
        Args:
            db_path: Path to knowledge database
            target_dir: Target directory for the release
        """
        if not os.path.exists(db_path):
            logger.warning(f"Database file not found: {db_path}")
            return
        
        logger.info(f"Including database: {db_path}")
        self.db_path = os.path.basename(db_path)
        target_db = os.path.join(target_dir, self.db_path)
        
        try:
            shutil.copy2(db_path, target_db)
            logger.info(f"Database copied to {target_db}")
        except Exception as e:
            logger.error(f"Failed to copy database: {str(e)}")
            self.db_path = None
    
    def include_model(self, model_path: str, target_dir: str) -> None:
        """Include model file in the release if it's not too large.
        
        Args:
            model_path: Path to model file
            target_dir: Target directory for the release
        """
        if not os.path.exists(model_path):
            logger.warning(f"Model file not found: {model_path}")
            return
        
        # Check model file size
        model_size = os.path.getsize(model_path) / (1024 * 1024)  # Size in MB
        logger.info(f"Model file size: {model_size:.2f} MB")
        
        # If model is larger than 100MB, create a dummy file
        if model_size > 100:
            logger.info("Model file too large for release bundle, creating placeholder")
            self.model_path = os.path.basename(model_path)
            target_model = os.path.join(target_dir, f"{self.model_path}.download_info")
            
            try:
                model_info = {
                    "filename": self.model_path,
                    "size_bytes": os.path.getsize(model_path),
                    "size_mb": model_size,
                    "md5": self._compute_file_hash(model_path),
                    "download_url": "auto"  # Will be filled by download script
                }
                
                with open(target_model, 'w') as f:
                    json.dump(model_info, f, indent=2)
                logger.info(f"Created model placeholder: {target_model}")
            except Exception as e:
                logger.error(f"Failed to create model placeholder: {str(e)}")
                self.model_path = None
        else:
            # Include small model files directly
            logger.info(f"Including model: {model_path}")
            self.model_path = os.path.basename(model_path)
            target_model = os.path.join(target_dir, self.model_path)
            
            try:
                shutil.copy2(model_path, target_model)
                logger.info(f"Model copied to {target_model}")
            except Exception as e:
                logger.error(f"Failed to copy model: {str(e)}")
                self.model_path = None
    
    def _compute_file_hash(self, file_path: str) -> str:
        """Compute MD5 hash of a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            MD5 hash of the file
        """
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            # Read in 4MB chunks to handle large files
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    
    def generate_manifest(self, target_dir: str) -> None:
        """Generate a manifest file for the release.
        
        Args:
            target_dir: Target directory for the release
        """
        logger.info("Generating release manifest...")
        manifest_path = os.path.join(target_dir, "MANIFEST.json")
        
        manifest = {
            "name": "Neuro-Lite",
            "version": self.version,
            "build_timestamp": self.timestamp,
            "build_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "included_files": [],
            "database": self.db_path,
            "model": self.model_path
        }
        
        # List all files in the release
        for root, _, files in os.walk(target_dir):
            rel_path = os.path.relpath(root, target_dir)
            for file in files:
                if file != "MANIFEST.json":
                    file_path = os.path.join(root, file)
                    rel_file_path = os.path.join(rel_path, file) if rel_path != "." else file
                    
                    file_info = {
                        "path": rel_file_path,
                        "size_bytes": os.path.getsize(file_path),
                        "executable": os.access(file_path, os.X_OK)
                    }
                    manifest["included_files"].append(file_info)
        
        try:
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            logger.info(f"Manifest generated: {manifest_path}")
        except Exception as e:
            logger.error(f"Failed to generate manifest: {str(e)}")
    
    def create_tarball(self, source_dir: str) -> str:
        """Create a tarball of the release.
        
        Args:
            source_dir: Directory containing release files
            
        Returns:
            Path to the created tarball
        """
        logger.info("Creating release tarball...")
        
        # Ensure build directory exists
        os.makedirs(self.build_dir, exist_ok=True)
        
        # Create tarball filename
        tarball_path = os.path.join(self.build_dir, f"{self.release_name}.tar.gz")
        
        try:
            with tarfile.open(tarball_path, "w:gz") as tar:
                # Add each file to the tarball with the release name as the base directory
                for root, _, files in os.walk(source_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.join(
                            self.release_name, 
                            os.path.relpath(file_path, source_dir)
                        )
                        tar.add(file_path, arcname=arcname)
            
            logger.info(f"Tarball created: {tarball_path}")
            return tarball_path
            
        except Exception as e:
            logger.error(f"Failed to create tarball: {str(e)}")
            raise
    
    def build(self, include_db: Optional[str] = None, include_model: Optional[str] = None) -> str:
        """Build the release.
        
        Args:
            include_db: Optional path to database to include
            include_model: Optional path to model to include
            
        Returns:
            Path to the created release tarball
        """
        # Validate source files
        if not self.validate_source():
            raise ValueError(f"Source validation failed. Missing: {self.missing_files}")
        
        # Validate Python files
        if not self.validate_python_files():
            raise ValueError("Python validation failed")
        
        # Validate shell scripts
        if not self.validate_shell_scripts():
            raise ValueError("Shell script validation failed")
        
        # Create temporary directory for the release
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"Using temporary directory: {temp_dir}")
            
            # Copy source files
            self.copy_source_files(temp_dir)
            
            # Set file permissions
            self.set_file_permissions(temp_dir)
            
            # Include database if provided
            if include_db:
                self.include_database(include_db, temp_dir)
            
            # Include model if provided
            if include_model:
                self.include_model(include_model, temp_dir)
            
            # Generate manifest
            self.generate_manifest(temp_dir)
            
            # Create tarball
            tarball_path = self.create_tarball(temp_dir)
        
        logger.info(f"Release built successfully: {tarball_path}")
        return tarball_path

def main():
    parser = argparse.ArgumentParser(description="Build a release package for Neuro-Lite")
    parser.add_argument("--source", default=".", help="Source directory")
    parser.add_argument("--build-dir", default="build", help="Build output directory")
    parser.add_argument("--version", default="1.0.0", help="Release version")
    parser.add_argument("--include-db", help="Include knowledge database")
    parser.add_argument("--include-model", help="Include model file")
    args = parser.parse_args()
    
    try:
        builder = ReleaseBuilder(
            source_dir=args.source,
            build_dir=args.build_dir,
            version=args.version
        )
        
        tarball_path = builder.build(
            include_db=args.include_db,
            include_model=args.include_model
        )
        
        print(f"\nRelease built successfully: {tarball_path}")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Release build failed: {str(e)}")
        print(f"\nError: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
