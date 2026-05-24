"""Deploy nature-album to NAS via SSH — uses stdin pipe for file transfer."""
import os
import tarfile
import io
import paramiko

NAS_IP = "192.168.31.233"
NAS_USER = "pcwork"
NAS_PASS = "Shanghai2025/"
APP_DIR = "/home/pcwork/nature-album"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
DASHSCOPE_KEY = "sk-a2da2273a94f4f47b76c5c739f2efa1a"
SUDO = f"echo '{NAS_PASS}' | sudo -S"

EXCLUDE = {"__pycache__", "uploads", "deploy_nas.py", ".git", "migrate.py",
          "llm_cache.json", "batch_sessions.json", "shares.json", ".env"}


def create_tarball():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, dirs, files in os.walk(LOCAL_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE]
            rel = os.path.relpath(root, LOCAL_DIR).replace("\\", "/")
            parts = rel.split("/")
            if parts[0] in ("album", "thumbs") and len(parts) > 1:
                continue
            for f in files:
                if f.endswith((".pyc", ".cr2", ".cr3", ".nef", ".arw")):
                    continue
                path = os.path.join(root, f)
                arcname = rel + "/" + f if rel != "." else f
                tar.add(path, arcname=arcname)
        # empty dirs
        for d in ["album/relic", "album/animal", "album/plant",
                   "thumbs/relic", "thumbs/animal", "thumbs/plant", "uploads"]:
            info = tarfile.TarInfo(d + "/")
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
    buf.seek(0)
    return buf.read()


def run_ssh(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n"):
            print(f"       {line}")
    if err:
        for line in err.split("\n"):
            line = line.strip()
            if line:
                print(f"       [>] {line}")
    return out, err


def main():
    print("[1/4] Packaging...")
    tarball_data = create_tarball()
    print(f"       {len(tarball_data) / 1024:.0f} KB")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(NAS_IP, username=NAS_USER, password=NAS_PASS)

    print("[2/4] Uploading to NAS via SCP...")
    # Use scp via stdin pipe to avoid SFTP issues
    scp_cmd = f"cat > {APP_DIR}/nature-album.tar.gz"
    transport = ssh.get_transport()
    channel = transport.open_session()
    channel.exec_command(scp_cmd)
    channel.sendall(tarball_data)
    channel.shutdown_write()
    # Wait for completion
    exit_code = channel.recv_exit_status()
    if exit_code != 0:
        err = channel.recv_stderr(1024).decode()
        print(f"       SCP failed: {err}")
        # Try creating dir first
        run_ssh(ssh, f"mkdir -p {APP_DIR}")
        channel = transport.open_session()
        channel.exec_command(f"cat > {APP_DIR}/nature-album.tar.gz")
        channel.sendall(tarball_data)
        channel.shutdown_write()
        exit_code = channel.recv_exit_status()
    print(f"       Uploaded (exit {exit_code})")

    print("[3/4] Building Docker...")
    cmd = (
        f"cd {APP_DIR} && "
        f"tar -xzf nature-album.tar.gz && "
        f"mkdir -p album/relic album/animal album/plant "
        f"thumbs/relic thumbs/animal thumbs/plant uploads && "
        f"echo 'DASHSCOPE_API_KEY={DASHSCOPE_KEY}' > .env && "
        f"{SUDO} docker compose build --no-cache 2>&1 && "
        f"{SUDO} docker compose down 2>/dev/null; "
        f"{SUDO} docker compose up -d && "
        f"sleep 3 && {SUDO} docker compose ps"
    )
    run_ssh(ssh, cmd)

    ssh.close()
    print(f"\n[4/4] Done! http://{NAS_IP}:8000")


if __name__ == "__main__":
    main()
