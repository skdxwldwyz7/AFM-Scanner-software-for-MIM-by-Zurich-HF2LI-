import serial
import time
import logging
import qcodes as qc
from qcodes.instrument import Instrument
import qcodes.validators as vals

log = logging.getLogger(__name__)

class NewtonLT06(Instrument):
    """
    QCoDeS driver for MC-NewtonLT06 positioner.
    Handles automatic channel switching for multi-axis support on a single serial link.
    """
    # Channel mappings according to original instrument_control get_all_position
    CH_MAP = {'z': 1, 'x': 2, 'y': 3}

    def __init__(self, name: str, port: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.port = port
        
        # Setup serial connection
        self.lt06 = serial.Serial(self.port, 115200, timeout=0.5)
        time.sleep(3) # Wait for device initialization
        
        self._active_channel = None
        
        # Default parameters
        self.capacitance = 30
        self.voltage = 30
        self.frequency = 500
        
        self._init_device()
        
        # Create QCoDeS parameters for each axis directly!
        for axis, ch in self.CH_MAP.items():
            self.add_parameter(
                axis,
                label=f'{axis.upper()} Position',
                unit='mm',
                get_cmd=lambda c=ch: self._get_position(c),
                set_cmd=lambda val, c=ch: self._set_position(c, val),
                get_parser=float,
                vals=vals.Numbers(-100, 100) # Safe working limit bounds
            )
            
        self.connect_message()

    def _init_device(self):
        self.set_parameter(self.voltage, self.frequency, self.capacitance)
        self.set_mode(1) # Config step mode
        log.info(f"Initialized NewtonLT06 on {self.port}")

    def write_raw(self, cmd: str):
        self.lt06.write(cmd.encode('utf-8'))

    def ask_raw(self, cmd: str) -> str:
        self.write_raw(cmd)
        resp = self.lt06.read_until().decode('utf-8').strip()
        return resp

    def switch_channel(self, ch: int):
        """Intelligently switch channel only if necessary."""
        if self._active_channel == ch:
            return
        
        # Disable current channel if needed
        if self._active_channel is not None:
            self.write_raw(f"[ch{self._active_channel}:0]")
            time.sleep(0.05)
            
        self.write_raw(f"[ch{ch}:1]")
        time.sleep(0.1) # Wait for channel relays to physically actuate
        self._active_channel = ch
        log.debug(f"Switched NewtonLT06 to channel {ch}")

    def _get_position(self, ch: int) -> float:
        self.switch_channel(ch)
        resp = self.ask_raw("[check:pos?]")
        try:
            if resp.startswith('[pos:') and resp.endswith(']'):
                val = float(resp[5:-1])
                return val
            else:
                log.warning(f"Unable to parse position from NewtonLT06: {resp}")
                return float('nan')
        except Exception as e:
            log.warning(f"Error parsing position: {e}")
            return float('nan')

    def _set_position(self, ch: int, target: float):
        self.switch_channel(ch)
        self.write_raw(f"[movetarget:{target:.3f}]")
        # Minimal sleep to prevent bus collisions if called sequentially rapidly
        time.sleep(0.1)

    def set_parameter(self, voltage: int, frequency: int, capacitance: int):
        self.capacitance = capacitance
        self.voltage = voltage
        self.frequency = frequency
        self.write_raw(f"[cap:{self.capacitance:03d}nF]")
        time.sleep(0.2)
        self.write_raw(f"[volt:+{self.voltage:03d}V]")
        time.sleep(0.2)
        self.write_raw(f"[freq:{self.frequency:05d}Hz]")
        time.sleep(0.2)

    def set_mode(self, mode: int):
        if mode == 1:
            self.write_raw("[-step-]")
        elif mode == 2:
            self.write_raw("[-slid-]")
        else:
            raise ValueError("Mode must be 1 (step) or 2 (slide)")

    def get_idn(self):
        resp = self.ask_raw("[*IDN?]")
        return {'vendor': 'Newton', 'model': 'LT06', 'serial': None, 'firmware': resp}

    def close(self):
        if hasattr(self, 'lt06') and self.lt06.is_open:
            if self._active_channel is not None:
                self.write_raw(f"[ch{self._active_channel}:0]")
                time.sleep(0.1)
            self.lt06.close()
        super().close()
