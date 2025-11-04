from pathlib import Path,PurePosixPath
from tabnanny import check

from psycopg2.pool import ThreadedConnectionPool
import subprocess
import psutil,shutil
import gzip,bz2,lzma,zstandard



class RISC_V_UEFI:

    def __init__(self, **kwargs):
        self.id:int = int(kwargs.get('id'))
        self.pool:ThreadedConnectionPool = kwargs.get('pool')
        self.arch = 'RISC-V'
        self.suite:str =kwargs.get('suite')
        self.case:str = kwargs.get('case')

        self.json_desc = kwargs.get('json_desc')
        self.machine_number:int = 0
        self.disk_number:int = 0
        self.network_interface:int = 0


        self.vcpu:int = kwargs.get('vcpu')
        self.ssh_port:int = 20000 + id
        self.run:str = ''


    @staticmethod
    def make_openEuler_image(**kwargs):
        default_workdir:Path = kwargs.get('default_workdir')
        VIRT_VARS_FILE:Path = kwargs.get('VIRT_VARS_FILE')
        VIRT_CODE_FILE:Path = kwargs.get('VIRT_CODE_FILE')
        DRIVE_NAME:Path = Path(kwargs.get('DRIVE_FILE'))
        DRIVE_TYPE:Path = kwargs.get('DRIVE_TYPE')
        compress_format:str = kwargs.get('compress_format')
        print(compress_format)
        print(DRIVE_NAME)
        print(default_workdir)

        if compress_format == 'gzip':
            with gzip.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        elif compress_format == 'bzip2':
            with bz2.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        elif compress_format == 'xz':
            with lzma.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        elif compress_format == 'zstd':
            with zstandard.open(default_workdir / DRIVE_NAME,'rb') as fin,open(default_workdir / Path(DRIVE_NAME).with_suffix(''),'wb') as fout:
                shutil.copyfileobj(fin, fout,length=1024*1024*32)
        else:
            print("未检测到压缩格式，按照无压缩处理...")

        # 转变为绝对路径
        VIRT_VARS_FILE.resolve()
        VIRT_CODE_FILE.resolve()

        # 对两个固件进行软链接
        Path(default_workdir / PurePosixPath(VIRT_VARS_FILE).name).symlink_to(VIRT_VARS_FILE)
        Path(default_workdir / PurePosixPath(VIRT_CODE_FILE).name).symlink_to(VIRT_CODE_FILE)

        try:
            """
            QEMU模拟器UEFI RISC-V启动脚本模板
            qemu-system-riscv64 \
              -nographic -machine virt,pflash0=pflash0,pflash1=pflash1,acpi=off \
              -smp 8 -m 4G \
              -object memory-backend-ram,size=2G,id=ram1 \
              -numa node,memdev=ram1 \
              -object memory-backend-ram,size=2G,id=ram2 \
              -numa node,memdev=ram2 \
              -blockdev node-name=pflash0,driver=file,read-only=on,filename="RISCV_VIRT_CODE.fd" \
              -blockdev node-name=pflash1,driver=file,filename="RISCV_VIRT_VARS.fd" \
              -drive file="openEuler-24.03-qemu-uefi.qcow2",format=qcow2,id=hd0,if=none \
              -object rng-random,filename=/dev/urandom,id=rng0 \
              -device virtio-vga \
              -device virtio-rng-device,rng=rng0 \
              -device virtio-blk-device,drive=hd0 \
              -device virtio-net-device,netdev=usernet \
              -netdev user,id=usernet,hostfwd=tcp::"10000"-:22 \
              -device qemu-xhci -usb -device usb-kbd -device usb-tablet
            """

            QEMU = subprocess.Popen(args=f"""
                qemu-system-riscv64 \
                  -nographic -machine virt,pflash0=pflash0,pflash1=pflash1,acpi=off \
                  -smp 8 -m 4G \
                  -object memory-backend-ram,size=2G,id=ram1 \
                  -numa node,memdev=ram1 \
                  -object memory-backend-ram,size=2G,id=ram2 \
                  -numa node,memdev=ram2 \
                  -blockdev node-name=pflash0,driver=file,read-only=on,filename="{VIRT_CODE_FILE}" \
                  -blockdev node-name=pflash1,driver=file,filename="{VIRT_VARS_FILE}" \
                  -drive file="{default_workdir / DRIVE_NAME.with_suffix('')}",format={DRIVE_TYPE},id=hd0,if=none \
                  -object rng-random,filename=/dev/urandom,id=rng0 \
                  -device virtio-vga \
                  -device virtio-rng-device,rng=rng0 \
                  -device virtio-blk-device,drive=hd0 \
                  -device virtio-net-device,netdev=usernet \
                  -netdev user,id=usernet,hostfwd=tcp::"20000"-:22 \
                  -device qemu-xhci -usb -device usb-kbd -device usb-tablet
            """,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,start_new_session=True
            )
            print(f"QEMU's pid = {QEMU.pid}")
        except subprocess.CalledProcessError as e:
            print(e)
        finally:
            print('Hello finally!')
            QEMU.kill()
        print('Hello World!')