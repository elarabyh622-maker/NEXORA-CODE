"""Create the NoCloud seed and start the project-owned Ubuntu VM on Windows."""

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time

PHASE = Path(__file__).resolve().parent.parent
PRIVATE = PHASE / ".local"
TOOLS = PRIVATE / "qemu-tools"
VM = PRIVATE / "runner-vm"
PROVISIONED = VM / "provisioned"
GUEST_PORT = 2227
OPERATOR_KEY = "vm-operator"
UBUNTU_IMAGE_SHA256 = "406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0"
HOST_KEY = re.compile(rb"NEXORA_VM_SSH_HOST_KEY (ssh-ed25519 [A-Za-z0-9+/]+={0,2})")


def checked(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def seed():
    sys.path.insert(0, str(TOOLS / "python"))
    from pycdlib import PyCdlib

    identity = VM / OPERATOR_KEY
    if not identity.exists():
        checked(["ssh-keygen.exe", "-q", "-t", "ed25519", "-N", "", "-C", "nexora-code-vm",
                 "-f", OPERATOR_KEY], cwd=VM)
        sid = checked(["whoami.exe", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
        owner = re.search(r"S-1-5-[0-9-]+", sid).group()
        checked(["icacls.exe", OPERATOR_KEY, "/inheritance:r", "/grant:r", f"*{owner}:(F)"],
                cwd=VM, stdout=subprocess.DEVNULL)
    public_key = identity.with_suffix(".pub").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+ nexora-code-vm", public_key):
        raise SystemExit("Unexpected VM operator public key.")
    data = f"""#cloud-config
hostname: nexora-code-runner
manage_etc_hosts: true
disable_root: true
ssh_pwauth: false
ssh_deletekeys: true
ssh_genkeytypes: [ed25519]
users:
  - name: nexora-operator
    lock_passwd: true
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - {public_key}
runcmd:
  - [sh, -c, 'echo NEXORA_VM_SSH_HOST_KEY "$(cut -d" " -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)" > /dev/ttyS0']
"""
    metadata = "instance-id: nexora-code-runner-v1\nlocal-hostname: nexora-code-runner\n"
    iso = PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="CIDATA")
    try:
        for name, value in [("user-data", data), ("meta-data", metadata)]:
            contents = value.encode("utf-8")
            iso.add_fp(io.BytesIO(contents), len(contents), iso_path="/" + name.upper().replace("-", "_") + ";1",
                       rr_name=name, joliet_path="/" + name)
        iso.write(str(VM / "seed.iso"))
    finally:
        iso.close()


def port_open():
    with socket.socket() as client:
        client.settimeout(0.3)
        return client.connect_ex(("127.0.0.1", GUEST_PORT)) == 0


def ssh_command():
    return ["ssh.exe", "-F", "NUL", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
            "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=known_hosts",
            "-o", "GlobalKnownHostsFile=NUL", "-o", "IdentitiesOnly=yes",
            "-p", str(GUEST_PORT), "-i", OPERATOR_KEY, "nexora-operator@127.0.0.1"]


def guest_ready():
    if not (VM / "known_hosts").is_file():
        return False
    command = ssh_command() + ["true"]
    try:
        return subprocess.run(command, cwd=VM, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=8).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def owns_pending_vm(executable):
    try:
        state = json.loads((VM / "process.json").read_text(encoding="ascii"))
        pid = int(state["vmPid"])
    except (ValueError, KeyError, OSError):
        return False
    if state.get("sshPort") != GUEST_PORT:
        return False
    check = """
        $link = @(Get-NetTCPConnection -State Listen -LocalAddress '127.0.0.1' -LocalPort 2227 -ErrorAction Stop)
        if ($link.Count -ne 1 -or $link[0].OwningProcess -ne [int]$env:NEXORA_VM_EXPECTED_PID) { exit 1 }
        $vmProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $link[0].OwningProcess)
        if ($vmProcess.ExecutablePath -ne $env:NEXORA_VM_EXPECTED_EXE -or
            $vmProcess.CommandLine -notlike '*-name NEXORA-CODE-Runner*') { exit 1 }
    """
    environment = os.environ | {"NEXORA_VM_EXPECTED_PID": str(pid),
                                "NEXORA_VM_EXPECTED_EXE": str(executable)}
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", check], env=environment,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0


def wait_for_guest(process=None):
    deadline = time.monotonic() + 180
    known_hosts = VM / "known_hosts"
    serial = VM / "serial.log"
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise SystemExit("QEMU exited before SSH was ready. See qemu.log.")
        if not known_hosts.exists() and serial.exists():
            match = HOST_KEY.search(serial.read_bytes())
            if match:
                key = match.group(1)
                base64.b64decode(key.split()[1], validate=True)
                known_hosts.write_bytes(b"[127.0.0.1]:" + str(GUEST_PORT).encode() + b" " + key + b"\n")
        if guest_ready():
            print("Ubuntu VM ready. Host key pinned from the VM serial console.")
            return
        time.sleep(2)
    raise SystemExit("SSH did not become ready. Check serial.log and qemu.log before retrying.")


def shutdown_guest():
    if not guest_ready():
        raise SystemExit("SSH must verify the project VM before requesting shutdown.")
    subprocess.run(ssh_command() + ["sudo -n systemctl --no-block poweroff"], cwd=VM,
                   stdin=subprocess.DEVNULL, timeout=12, check=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if not port_open():
            return
        time.sleep(1)
    raise SystemExit("The project VM has not finished shutting down.")


def install_guest():
    if not guest_ready():
        raise SystemExit("Start the verified VM before provisioning it.")
    archive = io.BytesIO()
    files = [("host", "provision-linux.sh"), ("runner", "broker.py"), ("runner", "sandbox.py"),
             ("runner", "smoke.py"), ("runner", "nexora-code-runner.service")]
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        for folder, name in files:
            data = (PHASE / folder / name).read_bytes().replace(b"\r\n", b"\n")
            member = tarfile.TarInfo(f"{folder}/{name}")
            member.size = len(data)
            member.mode = 0o600
            bundle.addfile(member, io.BytesIO(data))
    command = "umask 077 && mkdir -p nexora-runner-src && tar -xf - -C nexora-runner-src"
    checked(ssh_command() + [command], cwd=VM, input=archive.getvalue())
    checked(ssh_command() + ["sudo -n bash nexora-runner-src/host/provision-linux.sh --dedicated-nexora-runner"],
            cwd=VM, stdin=subprocess.DEVNULL)


def provision():
    if PROVISIONED.exists():
        shutdown_guest()
        start(maintenance=True)
    try:
        install_guest()
        PROVISIONED.write_text("gVisor preflight and broker smoke passed.\n", encoding="ascii")
    finally:
        if PROVISIONED.exists():
            shutdown_guest()
            start()


def start(maintenance=False):
    vm_disk = VM / "ubuntu.qcow2"
    firmware = next(TOOLS.glob("msys64/ucrt64/share/qemu/edk2-x86_64-code.fd"), None)
    binaries = TOOLS / "msys64" / "ucrt64" / "bin"
    base = PRIVATE / "host-image" / "ubuntu-24.04-minimal-cloudimg-amd64.img"
    if not firmware or not base.is_file():
        raise SystemExit("Verified Ubuntu image and QEMU UEFI firmware are required.")
    variables_template = firmware.with_name("edk2-i386-vars.fd")
    if not variables_template.is_file():
        raise SystemExit("The QEMU UEFI variables template is missing.")
    with base.open("rb") as image:
        if hashlib.file_digest(image, "sha256").hexdigest() != UBUNTU_IMAGE_SHA256:
            raise SystemExit("Ubuntu image hash differs from the Canonical signed manifest.")
    if port_open():
        if guest_ready():
            print("The project Ubuntu VM is already running.")
            return
        if owns_pending_vm(binaries / "qemu-system-x86_64.exe"):
            wait_for_guest()
            return
        raise SystemExit(f"Loopback port {GUEST_PORT} is already in use. Verify its owner before reusing it.")
    VM.mkdir(parents=True, exist_ok=True)
    variables = VM / "uefi-vars.fd"
    if not variables.exists():
        shutil.copyfile(variables_template, variables)
    first_boot = not vm_disk.exists()
    if first_boot:
        seed()
        checked([binaries / "qemu-img.exe", "create", "-f", "qcow2", "-F", "qcow2",
                 "-b", str(base), vm_disk.name, "20G"], cwd=VM)
    restrict = "on" if PROVISIONED.exists() and not maintenance else "off"
    with (VM / "qemu.log").open("ab") as output:
        process = subprocess.Popen([
            binaries / "qemu-system-x86_64.exe",
            "-name", "NEXORA-CODE-Runner", "-machine", "q35", "-accel", "whpx",
            "-L", os.path.relpath(firmware.parent, VM),
            "-smp", "2", "-m", "2560",
            "-drive", f"if=pflash,unit=0,format=raw,readonly=on,file={os.path.relpath(firmware, VM)}",
            "-drive", f"if=pflash,unit=1,format=raw,file={variables.name}",
            "-display", "none", "-monitor", "none",
            "-chardev", "file,id=nexora_serial,path=serial.log,append=on", "-serial", "chardev:nexora_serial",
            "-drive", f"file={vm_disk.name},format=qcow2,if=virtio",
            "-drive", "file=seed.iso,format=raw,readonly=on,if=virtio",
            "-nic", f"user,model=virtio-net-pci,restrict={restrict},hostfwd=tcp:127.0.0.1:{GUEST_PORT}-:22",
        ], cwd=VM, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    (VM / "process.json").write_text(json.dumps({"vmPid": process.pid, "sshPort": GUEST_PORT}),
                                     encoding="ascii")
    print(f"VM started with PID {process.pid}", flush=True)
    wait_for_guest(process)


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This launcher uses Windows Hypervisor Platform.")
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--seed-only", action="store_true")
    actions.add_argument("--provision", action="store_true")
    actions.add_argument("--shutdown", action="store_true")
    args = parser.parse_args()
    if args.seed_only:
        VM.mkdir(parents=True, exist_ok=True)
        seed()
    elif args.provision:
        provision()
    elif args.shutdown:
        shutdown_guest()
    else:
        start()
