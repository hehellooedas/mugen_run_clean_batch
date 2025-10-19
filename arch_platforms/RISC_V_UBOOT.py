


class RISC_V_UBOOT:
    def __init__(self):
        self.arch = 'RISC-V'        # 当前测试类负责的指令集架构
        self.platform = 'UBOOT'     # 当前测试类负责的系统启动引导平台
        self.suite = ''             # 当前测试类待测试的mugen测试套名称
        self.case = ''              # 当前测试类待测试的mugen测试名称


    @staticmethod
    def pretest():
        pass