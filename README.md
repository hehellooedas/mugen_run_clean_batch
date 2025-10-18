## "mugen run clean batch" is abbreviated as mrcb

mrcb是一个批量运行指定mugen测试并完成结果总结的工具。
为基于openEuler开源操作系统的rpm包测试设计，旨在充分利用现代处理器多核特点、快捷完成数量较大的测试脚本运行，并且每一个mugen测试都将运行在全新的openEuler上（创建一个干净的虚拟环境），避免多项测试之间互相影响。同时，由于mugen能够测试的rpm软件包较多，mrcb的批处理特性能够避免人力的过多投入。

mrcb将深入研究[mugen项目](https://gitee.com/openeuler/mugen)的构造，利用其运行机制与测试携带信息创造合适的硬件与软件条件，最终完成所有mugen测试、总结数据并生成excel结果。mrcb支持多架构。



<br>
mrcb应运行在x86_64 openEuler上,请勿引入Fedora的repo源.


## 如何使用？

* 获取mrcb

```shell
git clone https://gitee.com/April_Zhao/mugen_run_clean_batch
cd ugen_run_clean_batch
```



* 运行前安装环境

```
# 安装Python3解释器
dnf install -y python3

chmod +x main.py before_mrcb_run.py
./before_mrcb_run.py
```

* 编写正确的配置文件
