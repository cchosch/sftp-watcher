import os
import sys
import json
import time
import pathlib
from ftplib import FTP, error_perm
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import paramiko


def load_ftp_config(project_root):
    """
    Load FTP/SFTP configuration from <project_root>/.vscode/sftp.json
    (host, username, password, remotePath, protocol).
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

    # Default protocol to ftp if not specified
    if "protocol" not in cfg:
        cfg["protocol"] = "ftp"

    return cfg


# ---------------- FTP helpers ----------------

def create_ftp_client(host, username, password, port=21, timeout=30):
    """
    Create and return an FTP client.
    """
    ftp = FTP()
    ftp.connect(host=host, port=port, timeout=timeout)
    ftp.login(user=username, passwd=password)
    ftp.encoding = "utf-8"
    return ftp


def ensure_remote_dirs_ftp(ftp, remote_dir):
    """
    Ensure all directories in remote_dir exist, creating them as needed (FTP).
    remote_dir is a POSIX-style path (no trailing slash).
    """
    if not remote_dir or remote_dir == "/":
        return

    parts = [p for p in remote_dir.strip("/").split("/") if p]

    for part in parts:
        try:
            ftp.cwd(part)
        except error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def upload_file_ftp(project_root, rel_file_path, cfg):
    """
    Upload file via plain FTP, mirroring local relative path.
    """
    local_path = os.path.join(project_root, rel_file_path)
    if not os.path.exists(local_path):
        print(f"[WARN] Local file does not exist: {local_path}")
        return

    project_root = os.path.abspath(project_root)
    local_path = os.path.abspath(local_path)
    rel_path = os.path.relpath(local_path, project_root)
    rel_path_posix = rel_path.replace("\\", "/")

    remote_root = cfg["remotePath"].rstrip("/")
    if remote_root:
        remote_dir = "/".join([remote_root, os.path.dirname(rel_path_posix)]).rstrip("/")
    else:
        remote_dir = os.path.dirname(rel_path_posix).rstrip("/")

    filename = os.path.basename(rel_path_posix)

    print(f"[INFO] (FTP) Uploading {local_path} -> {remote_dir}/{filename}")

    ftp = create_ftp_client(
        host=cfg["host"],
        username=cfg["username"],
        password=cfg["password"],
        port=cfg.get("port", 21),
    )

    try:
        if remote_root:
            root_parts = [p for p in remote_root.strip("/").split("/") if p]
            ftp.cwd("/")
            for part in root_parts:
                try:
                    ftp.cwd(part)
                except error_perm:
                    ftp.mkd(part)
                    ftp.cwd(part)

        sub_dir = os.path.dirname(rel_path_posix).strip("/")
        if sub_dir:
            ensure_remote_dirs_ftp(ftp, sub_dir)

        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {filename}", f)
        print("[INFO] (FTP) Upload complete.")
    finally:
        ftp.quit()


# ---------------- SFTP helpers ----------------

def create_sftp_client(host, username, password, port=22, timeout=30):
    """
    Create and return an SFTP client (paramiko.SFTPClient) and its SSH client.
    Caller must close both.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=timeout,
        look_for_keys=False,
        allow_agent=False
    )
    sftp = ssh.open_sftp()
    return ssh, sftp


def ensure_remote_dirs_sftp(sftp, remote_dir):
    """
    Ensure all directories in remote_dir exist, creating them as needed (SFTP).
    remote_dir is a POSIX-style path (no trailing slash).
    """
    if not remote_dir or remote_dir == "/":
        return

    parts = [p for p in remote_dir.strip("/").split("/") if p]

    path = ""
    for part in parts:
        path = f"{path}/{part}" if path else f"/{part}"
        try:
            sftp.stat(path)
        except IOError:
            sftp.mkdir(path)


def upload_file_sftp(project_root, rel_file_path, cfg):
    """
    Upload file via SFTP, mirroring local relative path.
    """
    local_path = os.path.join(project_root, rel_file_path)
    if not os.path.exists(local_path):
        print(f"[WARN] Local file does not exist: {local_path}")
        return

    project_root = os.path.abspath(project_root)
    local_path = os.path.abspath(local_path)
    rel_path = os.path.relpath(local_path, project_root)
    rel_path_posix = rel_path.replace("\\", "/")

    remote_root = cfg["remotePath"].rstrip("/")
    if remote_root:
        remote_dir = "/".join([remote_root, os.path.dirname(rel_path_posix)]).rstrip("/")
    else:
        remote_dir = os.path.dirname(rel_path_posix).rstrip("/")

    filename = os.path.basename(rel_path_posix)

    print(f"[INFO] (SFTP) Uploading {local_path} -> {remote_dir}/{filename}")

    ssh, sftp = create_sftp_client(
        host=cfg["host"],
        username=cfg["username"],
        password=cfg["password"],
        port=cfg.get("port", 22),
    )

    try:
        if remote_root:
            ensure_remote_dirs_sftp(sftp, remote_root)

        sub_dir = os.path.dirname(rel_path_posix).strip("/")
        if sub_dir:
            full_sub_dir = f"{remote_root}/{sub_dir}".strip("/")
            full_sub_dir = "/" + full_sub_dir if not full_sub_dir.startswith("/") else full_sub_dir
            ensure_remote_dirs_sftp(sftp, full_sub_dir)

        # Build full remote file path
        if remote_dir:
            remote_file_path = f"{remote_dir}/{filename}"
        else:
            remote_file_path = f"/{filename}"

        sftp.put(local_path, remote_file_path)
        print("[INFO] (SFTP) Upload complete.")
    finally:
        sftp.close()
        ssh.close()


# ---------------- Protocol-agnostic upload ----------------

def upload_file(project_root, rel_file_path, cfg):
    """
    Dispatch upload to FTP or SFTP based on cfg['protocol'].
    """
    protocol = cfg.get("protocol", "ftp").lower()
    if protocol == "sftp":
        upload_file_sftp(project_root, rel_file_path, cfg)
    else:
        upload_file_ftp(project_root, rel_file_path, cfg)


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

    print(f"[INFO] Watching {target_file} for changes using protocol '{cfg.get('protocol', 'ftp')}'...")
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
