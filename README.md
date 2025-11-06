## mugen run clean batch（简称mrcb）

mrcb是一个批量运行指定mugen测试并完成结果总结的工具。  
为基于openEuler开源操作系统的rpm包测试设计，旨在充分利用现代处理器多核特点、快捷完成数量较大的测试脚本运行，并且每一个mugen测试都将运行在全新的openEuler上（创建一个干净的虚拟环境），避免多项测试之间互相影响。同时，由于mugen能够测试的rpm软件包较多，mrcb的批处理特性能够避免人力的过多投入。

mrcb将深入研究[mugen项目](https://gitee.com/openeuler/mugen)的构造，利用其运行机制与测试携带信息创造合适的硬件与软件条件，最终完成所有mugen测试、总结数据并生成excel结果。mrcb支持多架构。

<br>  
mrcb应运行在x86_64 openEuler上，请勿引入Fedora的repo源。必须以root身份运行，运行前建议先关闭selinux（运行时也会自动关闭）。

## 如何使用？

### 获取mrcb

```shell
git clone https://gitee.com/April_Zhao/mugen_run_clean_batch
cd mugen_run_clean_batch
```

### 安装运行环境

运行前请确保安装Python3解释器，并执行以下命令：

```shell
# 安装Python3解释器
dnf install -y python3

# 该脚本会自动安装项目运行所需的所有工具并初始化运行环境
./before_mrcb_run.py
```

### 编写配置文件

在运行主脚本前，请编写正确的配置文件。以下是一个示例：

```toml
arch = 'RISC-V'
platform = 'UBOOT'
drive_url = 'https://repo.tarsier-infra.isrc.ac.cn/openEuler-RISC-V/devel/20250914/v0.1/QEMU/openEuler-25.09-V1-base-qemu-devel.qcow2.zst'
drive_type = 'qcow2'
compress_format = 'zstd'
UBOOT_BIN_FILE = 'https://repo.tarsier-infra.isrc.ac.cn/openEuler-RISC-V/devel/20250914/v0.1/QEMU/fw_payload_oe_uboot_2304.bin'
input_excel = '/root/第一轮测试组筛选.xlsx'
from_to = [2, 641]
```

### 运行主脚本

```shell
./main.py
```

## 功能特性

- 支持多架构测试（如x86、RISC-V等）
- 自动创建干净的虚拟环境运行每个测试
- 支持从Excel文件中批量读取测试用例
- 自动生成测试结果并导出为Excel文件
- 多线程并行执行测试，充分利用多核性能

## 依赖组件

- Python3
- PostgreSQL
- QEMU
- Mugen测试框架（自动从Gitee仓库克隆）

## 注意事项

- 请确保运行环境为openEuler x86_64系统
- 必须以root权限运行脚本
- 运行前建议关闭SELinux（脚本会自动处理）
- 确保网络连接正常，以便下载依赖包和镜像文件

## 许可证

本项目遵循开源许可证，请参阅[LICENSE](LICENSE)文件获取详细信息。