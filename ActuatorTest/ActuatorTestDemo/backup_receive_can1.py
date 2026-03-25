import os
import can
import time
import signal
from datetime import datetime
import struct
from utils.convertion import hex_to_float
import threading
import socket
import json
import queue
from utils.station_conf import read_station_conf
# os.system('sudo ip link set can1 type can bitrate 1000000')
# os.system('sudo ifconfig can1 txqueuelen 65536')
# os.system('sudo ifconfig can1 up')


#can0 = can.interface.Bus(channel='can1', bustype='socketcan')  # socketcan_native
HOST = '127.0.0.1'
UDP_PORT = 15005
BUFFER_SIZE = 2048    

status = 0
calibrated_fb=0
error_fb=0
warning_fb=0
control_mode =0
current_task =""
monitor = False
def read_canbus(task_queue, can_bus, stop_event):
    # can_bus = can.interface.Bus(channel= canbus, interface='socketcan')
    feedback_list = [hex(x) for x in range(0x41, 0x4d+1)]
    monitoring = False
    monitor_task = "False"
    while not stop_event.is_set():
         
        msg = can_bus.recv(BUFFER_SIZE)  # 调整超时以检查消息
        try:
            monitor_task = task_queue.get_nowait()
        except queue.Empty:
            pass

        if monitor_task == "False":
            monitoring = False
            continue
        elif monitor_task=="True" or monitoring== True:
             monitoring = True
             address = hex(msg.data[0])
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
                case '0x41':  #status
                    status = struct.unpack('<i', msg.data[1:5])[0]
                    print(f"receive running status: {status}")
                case '0x42':  #Calibration
                    calibrated_fb = struct.unpack('<i', msg.data[1:5])[0]
                    print(f"receive calibration status: {calibrated_fb}")
                case '0x43':  #error??
                    error_fb = struct.unpack('<i', msg.data[1:5])[0]
                    print("receive error status")
                case '0x44': #warning???
                    warning_fb = struct.unpack('<i', msg.data[1:5])[0]
                    print("receive warning status")
                case '0x45': #control mode
                    control_mode = struct.unpack('<i', msg.data[1:5])[0] 
                    print("receive control mode")




def runinTest_monitor(canbus:str):
    can_bus = can.interface.Bus(channel= canbus, interface='socketcan')
    #feedback_list = [hex(x) for x in range(0x41, 0x4d+1)]
    timeout = 0.5  # 接收消息的超时时间（秒）
    #start_time = time.time()
    monitor_task = queue.Queue()
    stop_signal = threading.Event()
    thread = threading.Thread(target =read_canbus, args=(monitor_task, can_bus, stop_signal,) )
    thread.start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((HOST, UDP_PORT))
        print(f"UDP server listening on {HOST}:{UDP_PORT}")
        server_socket.settimeout(timeout)  # 设置接收消息的超时时间
        # start_time = datetime.now()
        while True:
            try:        
                data, udp_ip = server_socket.recvfrom(BUFFER_SIZE)
                if data is not None:
                    message = json.loads(data.decode('utf-8'))
                    print(f"Received message from {udp_ip}: {message}")
                    message_content = message.get("message", "")
                    if "task finished" in message_content:
                        #  stop_signal.set()
                        #  thread.join()
                         monitor = False
                         monitor_task.put_nowait("False")
                         continue
                    else:
                        print("starting monitoring thread")
                        monitor_task.put_nowait("True")
                        # thread = threading.Thread(target =read_canbus, args=(can_bus, stop_signal,) )
                        # thread.start()
                        monitor= True
                        if "calibration" is message_content:
                            current_task = "calibration"
                        else:
                            current_task = "runin_test"
                    if current_task == "calibration":
                        if calibrated_fb & 0x01 ==1 and status & 0x1C == 0:
                                server_socket.sendto(json.dumps({"message":"motor calibration completed"}).encode('utf-8'), (HOST, UDP_PORT))
                                continue
                        if calibrated_fb & 0x02 ==1 and status & 0x1C == 0:
                                server_socket.sendto(json.dumps({"message":"encoder calibration completed"}).encode('utf-8'), (HOST, UDP_PORT))
                                continue
                        if calibrated_fb & 0x04 ==1 and status & 0x1C == 0:
                                server_socket.sendto(json.dumps({"message":"electrical calibration completed"}).encode('utf-8'), (HOST, UDP_PORT))
                                continue

     
            except KeyboardInterrupt:
                print("\nProgramm interruptted by user.")
                stop_signal.set()
                thread.join()
                can_bus.shutdown()
                break
            except socket.timeout:
                continue
            except Exception as e:
                print(f"An error occurred: {e}")
                can_bus.shutdown()
                break

if __name__ == "__main__":
    station_name = read_station_conf().get("station_name", "unknown_station")
    runinTest_monitor("can1")
