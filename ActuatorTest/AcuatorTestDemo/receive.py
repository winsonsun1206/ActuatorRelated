import os
import can
import time
import signal
from datetime import datetime
import struct
from utils.convertion import hex_to_float
# os.system('sudo ip link set can1 type can bitrate 1000000')
# os.system('sudo ifconfig can1 txqueuelen 65536')
# os.system('sudo ifconfig can1 up')

#can0 = can.interface.Bus(channel='can1', bustype='socketcan')  # socketcan_native
can0 = can.interface.Bus(channel= 'can1', interface='socketcan')
feedback_list = [hex(x) for x in range(0x41, 0x4d+1)]
timeout = 999.0  # 接收消息的超时时间（秒）
start_time = time.time()
try:
    while time.time() - start_time < timeout:
        
            msg = can0.recv(0.1)  # 调整超时以检查消息
            if msg is not None:
                address = hex(msg.data[0])
                if address in feedback_list:
                    print(datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'), end= " ")
                match address:
                    case '0x46':
                        print(f"MCL_POSITION_MOTOR_Rad_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x47':
                        print(f"MCL_POSITION_OUTPUT_Rad_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x48':
                        print(f"MCL_VELOCITY_Radps_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x49':
                        print(f"MCL_CURRENT_IQ_A_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x4a':
                        print(f"MCL_CURRENT_ID_A_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x4c':
                        print(f"MCL_TEMP_BOARD_ddegC_FB:{struct.unpack('<i', msg.data[1:5])[0]/10}" + u"\u2103"+".")
                    case '0x4d':
                        print(f"MCL_TEMP_MOTOR_ddegC_FB:{struct.unpack('<i', msg.data[1:5])[0]/10}"+u"\u2103"+".")
                    case '0x41':  #status\
                        print("receive running status")
                    case '0x42':  #Calibration
                        print("receive calibration status")
                    case '0x43':  #error??
                        print("receive error status")
                    case '0x44': #warning???
                        print("receive warning status")
                    case '0x45': #control mode 
                        print("receive control mode")      
except KeyboardInterrupt:
    print("\nProgramm interruptted by user.")
except Exception as error:
    print(f"\nAn error occured: {error}")

finally:
    can0.shutdown()
# #os.system('sudo ifconfig can1 down')
    print("CAN Channel Shutdown")
