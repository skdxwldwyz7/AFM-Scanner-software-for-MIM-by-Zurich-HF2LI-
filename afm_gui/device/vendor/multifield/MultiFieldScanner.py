import serial
import time
import re
import logging
import qcodes as qc
from qcodes.instrument import Instrument
import qcodes.validators as vals

log = logging.getLogger(__name__)

class MultiFieldScanner(Instrument):
    """
    QCoDeS driver for the custom open-loop MultiFieldScanner.
    Rewritten directly from scratch to independently handle serial communication,
    just like the NewtonLT06 driver.
    """
    def __init__(self, name: str, port: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        
        self.port = port
        # 1. 建立独占串口物理连接
        self.ser = serial.Serial(self.port, baudrate=115200, timeout=0.5)
        log.info(f"Initialized MultiFieldScanner on {self.port}")
        
        # 2. 统一注册三个通道的开环电压参数
        for ch in [1, 2, 3]:
            self.add_parameter(
                name=f'ch{ch}_v',
                label=f'Channel {ch} Voltage',
                unit='V',
                set_cmd=self._make_set_voltage(ch),
                get_cmd=self._make_get_voltage(ch),
                vals=vals.Numbers(-150.0, 150.0) # 严格的安全硬限幅
            )
        self.write_raw(f"[nch:{123}]")
        self.connect_message()

    def write_raw(self, cmd: str) -> None:
        """底层写入字符串并自动编码"""
        self.ser.write(cmd.encode('utf-8'))
        
    def ask_raw(self, cmd: str) -> str:
        """底层写入并读取"""
        self.write_raw(cmd)
        return self.ser.read_until().decode('utf-8').strip()

    def _make_set_voltage(self, ch: int):
        """生成对应通道的设置闭包函数"""
        def set_v(val: float):
            # 激活并选择通道
            time.sleep(0.02)
            # 设置电压缓冲
            self.write_raw(f"[target:ch{ch}:{val:.6f}]")
            time.sleep(0.02)
            # 硬件强制触发输出生效
            self.write_raw("[start]")
            time.sleep(0.02)
            log.debug(f"Pushed {val}V to ch{ch} and triggered start.")
        return set_v

    def _make_get_voltage(self, ch: int):
        """生成对应通道的读取解析闭包函数"""
        def get_v() -> float:
            # 清理历史可能残留的缓存
            if hasattr(self, 'ser') and self.ser.is_open:
                self.ser.read_all()
                
            self.write_raw("[echo:on]")
            # 给硬件一点时间响应回传 (拉长到0.1s确保能收到起码一两行完整数据)
            time.sleep(0.1)
            
            # 手册要求用完关闭 echo, 先发停止命令防止后续产生无限乱码风暴
            self.write_raw("[echo:off]")
            time.sleep(0.05)
            
            # 核心修复点：将之前所有的响应数据(跨多行)全部作为 byte 读出，不再被 \r\n 局限
            resp_bytes = self.ser.read_all()
            log.debug(f"Raw bytes response: {resp_bytes}")
            
            # 在二进制字节流中倒序寻找最后一次出现的通道头部（保证读取最新鲜的一条）
            header = f"[ch{ch}:".encode('ascii')
            start_idx = resp_bytes.rfind(header)
            
            if start_idx != -1:
                # 数据从 header 之后开始，共3个字节
                data_start = start_idx + len(header)
                if data_start + 3 <= len(resp_bytes) and resp_bytes[data_start+3] == ord(b']'):
                    xyz_bytes = resp_bytes[data_start:data_start+3]
                    # x, y, z 分别为高八位、中八位、低八位，拼接为 24 位整数
                    xyz_int = (xyz_bytes[0] << 16) + (xyz_bytes[1] << 8) + xyz_bytes[2]
                    
                    # 使用手册公式精确还原电压
                    voltage = -300.0 * (xyz_int / ((1 << 24) - 1)) + 150.0
                    return round(voltage, 6)
                else:
                    log.warning(f"Incomplete binary data packet for channel {ch}.")
            else:
                log.warning(f"Could not find channel {ch} header in response.")
                
            return float('nan')
        return get_v

    def start_output(self):
        """手动全开"""
        self.write_raw("[start]")
        
    def stop_output(self):
        """手动全停"""
        self.write_raw("[stop]")
        
    def clear_output(self):
        """清空电压映射寄存器"""
        self.write_raw("[clear]")

    def get_idn(self) -> dict:
        """QCoDeS 标准设备信息获取"""
        return {'vendor': 'Custom', 'model': 'MultiFieldScanner', 'serial': self.port, 'firmware': ''}

    def close(self):
        """安全释放串口，并在断开前自动关闭高压"""
        if hasattr(self, 'ser') and self.ser.is_open:
            try:
                self.write_raw("[echo:off]")
                self.stop_output()
                self.clear_output()
            except Exception:
                pass
            self.ser.close()
        super().close()
