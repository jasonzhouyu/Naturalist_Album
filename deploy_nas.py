"""Deploy nature-album to NAS via SSH — uses stdin pipe for file transfer."""
import os
import re
import tarfile
import io
import paramiko

NAS_IP = "192.168.31.233"
NAS_USER = "pcwork"
NAS_PASS = "Shanghai2025/"
APP_DIR = "/home/pcwork/nature-album"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_ENV = r"Y:\Openclaw\workspace\.env"
DASHSCOPE_KEY = "sk-a2da2273a94f4f47b76c5c739f2efa1a"
SUDO = f"echo '{NAS_PASS}' | sudo -S"

EXCLUDE = {"__pycache__", "uploads", "deploy_nas.py", ".git", "migrate.py",
          "llm_cache.json", "batch_sessions.json", "shares.json", ".env",
          "keys", ".inat_state", "batch_sessions"}


def read_local_env() -> dict:
    """从 Y: .env 读取需要分发到 NAS 的 key。本地缺失就返回空。"""
    if not os.path.exists(LOCAL_ENV):
        return {}
    out = {}
    with open(LOCAL_ENV, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


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

    local = read_local_env()
    plantnet_key = local.get("PLANTNET_API_KEY", "")
    inat_user = local.get("INATURALIST_USERNAME", "")
    inat_pass = local.get("INATURALIST_PASSWORD", "")

    nas_env_lines = [f"DASHSCOPE_API_KEY={DASHSCOPE_KEY}"]
    if plantnet_key:
        nas_env_lines.append(f"PLANTNET_API_KEY={plantnet_key}")
    nas_env = "\\n".join(nas_env_lines)

    creds_setup = ""
    if inat_user and inat_pass:
        creds_setup = (
            f"mkdir -p keys && "
            f"printf 'INATURALIST_USERNAME=%s\\nINATURALIST_PASSWORD=%s\\n' "
            f"'{inat_user}' '{inat_pass}' > keys/inat_creds.env && "
            f"chmod 600 keys/inat_creds.env && "
        )
        print("       [+] iNat creds: pushing to keys/inat_creds.env")
    else:
        creds_setup = (
            "mkdir -p keys && "
            "[ -f keys/inat_creds.env ] || "
            "printf 'INATURALIST_USERNAME=\\nINATURALIST_PASSWORD=\\n' > keys/inat_creds.env && "
            "chmod 600 keys/inat_creds.env && "
        )
        print("       [!] iNat creds missing locally — placeholder created on NAS, "
              "sidecar will fail until you fill keys/inat_creds.env")

    if plantnet_key:
        print(f"       [+] PLANTNET_API_KEY: synced ({len(plantnet_key)} chars)")
    else:
        print("       [!] PLANTNET_API_KEY: not in local .env, skipping")

    print("[3/4] Building Docker...")
    cmd = (
        f"cd {APP_DIR} && "
        f"tar -xzf nature-album.tar.gz && "
        f"mkdir -p album/relic album/animal album/plant "
        f"thumbs/relic thumbs/animal thumbs/plant uploads && "
        f"printf '{nas_env}\\n' > .env && "
        f"{creds_setup}"
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
