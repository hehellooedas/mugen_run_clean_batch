from paramiko import SSHClient



class TestCase():
    def __init__(self,arch,suite,case,id=0,machine_number=0,disk_number=0,network_interface=0,vcpu=1):
        self.id = id
        self.arch = arch
        self.suite:str =suite
        self.case:str = case
        self.machine_number:int = machine_number
        self.disk_number:int = disk_number
        self.network_interface:int = network_interface
        self.vcpu:int = vcpu
        self.ssh_port:int = 20000 + id
        self.run:str = ''


    def pre_test(self):
        if self.arch == 'riscv64':
            self.run = f'qemu-system-riscv64 \
             -nographic -machine virt -smp {self.vcpu} -m 2G \
             pflash0=pflash0,pflash1=pflash1,,acpi=off \
             -blockdev node-name=pflash0,driver=file,read-only=on,filename="$fw1" \
             -blockdev node-name=pflash1,driver=file,filename="$fw2" \
             -drive file="$drive",format=qcow2,id=hd0,if=none \
             -object rng-random,filename=/dev/urandom,id=rng0 \
             -device virtio-vga -device virtio-rng-device,rng=rng0 \
             -device virtio-blk-device,drive=hd0 -device qemu-xhci \
             -usb -device usb-kbd -device usb-tablet'