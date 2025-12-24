import os
import sys
import json
import time
import pathlib
from ftplib import FTP, error_perm
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def load_ftp_config(project_root):
    """
    Load FTP configuration from <project_root>/.vscode/sftp.json
    (host, username, password, remotePath).
    """
    config_path = os.path.join(project_root, ".vscode", "sftp.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"sftp.json not found at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    required_keys = ["host", "username", "password", "remotePath"]
    for key in required_keys:
        if key not in cfg:
            raise KeyError(f"Missing '{key}' in sftp.json")

    return cfg


def create_ftp_client(host, username, password, port=21, timeout=30):
    """
    Create and return an FTP client. [web:50][web:54]
    """
    ftp = FTP()
    ftp.connect(host=host, port=port, timeout=timeout)
    ftp.login(user=username, passwd=password)
    ftp.encoding = "utf-8"
    return ftp


def ensure_remote_dirs(ftp, remote_dir):
    """
    Ensure all directories in remote_dir exist, creating them as needed. [web:55][web:64]
    remote_dir is a POSIX-style path (no trailing slash).
    """
    if not remote_dir or remote_dir == "/":
        return

    # Normalize, remove leading/trailing slashes
    parts = [p for p in remote_dir.strip("/").split("/") if p]

    # Start from root or current directory depending on server setup
    for part in parts:
        try:
            ftp.cwd(part)
        except error_perm:
            # Directory does not exist, create and then change into it
            ftp.mkd(part)
            ftp.cwd(part)

    # Go back to original working directory after creating path
    # (simple approach: cd back to root and then to base remotePath on each upload)
    # This function will be called after cwd(remote_root) in upload_file,
    # so no extra cleanup is strictly necessary.


def upload_file(project_root, rel_file_path, cfg):
    """
    Upload file so its remote path mirrors its local relative path
    under cfg['remotePath'], using plain FTP. [web:52][web:57]
    """
    local_path = os.path.join(project_root, rel_file_path)
    if not os.path.exists(local_path):
        print(f"[WARN] Local file does not exist: {local_path}")
        return

    project_root = os.path.abspath(project_root)
    local_path = os.path.abspath(local_path)
    rel_path = os.path.relpath(local_path, project_root)
    rel_path_posix = rel_path.replace("\\", "/")

    # remotePath is the base directory on the server
    remote_root = cfg["remotePath"].rstrip("/")
    # Full remote path (dir + filename)
    if remote_root:
        remote_dir = "/".join([remote_root, os.path.dirname(rel_path_posix)]).rstrip("/")
    else:
        remote_dir = os.path.dirname(rel_path_posix).rstrip("/")

    filename = os.path.basename(rel_path_posix)

    print(f"[INFO] Uploading {local_path} -> {remote_dir}/{filename}")

    ftp = create_ftp_client(
        host=cfg["host"],
        username=cfg["username"],
        password=cfg["password"],
        port=cfg.get("port", 21),
    )

    try:
        # Change to base remote root, creating if needed
        if remote_root:
            # walk & create remote_root
            # example: remote_root="public_html/project"
            root_parts = [p for p in remote_root.strip("/").split("/") if p]
            ftp.cwd("/")  # start from root, adjust if your server requires otherwise
            for part in root_parts:
                try:
                    ftp.cwd(part)
                except error_perm:
                    ftp.mkd(part)
                    ftp.cwd(part)

        # Now ensure subdirectories for the file exist under remote_root
        sub_dir = os.path.dirname(rel_path_posix).strip("/")
        if sub_dir:
            ensure_remote_dirs(ftp, sub_dir)

        # Finally upload the file into the current directory
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {filename}", f)  # upload file. [web:52][web:57]
        print("[INFO] Upload complete.")
    finally:
        ftp.quit()


class SingleFileHandler(FileSystemEventHandler):
    def __init__(self, project_root, target_path, cfg):
        super().__init__()
        self.project_root = os.path.abspath(project_root)
        self.target_path = os.path.abspath(target_path)
        self.cfg = cfg

    def _maybe_upload(self, event_path):
        changed = os.path.abspath(event_path)
        if changed == self.target_path:
            print(f"[INFO] Detected change: {changed}")
            rel = os.path.relpath(self.target_path, self.project_root)
            # Small delay to avoid uploading while file is still being written
            time.sleep(0.2)
            upload_file(self.project_root, rel, self.cfg)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._maybe_upload(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        self._maybe_upload(event.src_path)


def main():
    if len(sys.argv) != 3:
        print("Usage: python auto_ftp.py <project_root_folder> <relative_file_path>")
        print("Example: python auto_ftp.py /path/to/project src/styles/main.scss")
        sys.exit(1)

    project_root = sys.argv[1]
    rel_file_path = sys.argv[2]
    target_file = os.path.join(project_root, rel_file_path)

    if not os.path.exists(project_root) or not os.path.isdir(project_root):
        print(f"[ERROR] Project root is not a directory: {project_root}")
        sys.exit(1)

    cfg = load_ftp_config(project_root)

    event_handler = SingleFileHandler(project_root, target_file, cfg)
    observer = Observer()
    watch_dir = os.path.dirname(target_file)
    observer.schedule(event_handler, watch_dir, recursive=False)

    print(f"[INFO] Watching {target_file} for changes...")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[INFO] Stopping observer...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
