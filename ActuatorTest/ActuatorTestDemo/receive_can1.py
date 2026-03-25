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
from utils.redis_handler import RedisHandler
from utils.parsing_mapping_id_sn import parse_mapping_id_sn, get_sn_pn_by_id
# os.system('sudo ip link set can1 type can bitrate 1000000')
# os.system('sudo ifconfig can1 txqueuelen 65536')
# os.system('sudo ifconfig can1 up')


#can1 = can.interface.Bus(channel='can1', bustype='socketcan')  # socketcan_native
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


class TimeScaleDBHandler_can1:
    def __init__(self, host, port, database, user, password, table, flush_batch_size=1500, redis_bank=0,station_name="unknown_station"):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.BUFFER_SIZE = flush_batch_size
        self.bus1_feedback = {"can_bus":1}
        self.bus1_buffer= list()
        self.redis_handler = RedisHandler(host=host, port=6379, db=redis_bank)   
        self.station_name = station_name


    def read_canbus(self, task_queue, can_bus, stop_event):
        # can_bus = can.interface.Bus(channel= canbus, interface='socketcan')
        feedback_list = [hex(x) for x in range(0x41, 0x4d+1)]
        monitoring = False
        monitor_task = "False"
        mapping_dict = {}
        while not stop_event.is_set():
            
            msg = can_bus.recv(BUFFER_SIZE)  # 调整超时以检查消息
            try:
                monitor_task = task_queue.get_nowait()
            except queue.Empty:
                pass

            if monitor_task == "False":
                mapping_dict = {}
                monitoring = False
                continue
            elif monitor_task!="False" or monitoring== True:
                if  monitor_task != "False" and monitoring == False:
                    mapping_dict = parse_mapping_id_sn(monitor_task)
                    print(f"Parsed mapping dictionary: {mapping_dict}")
                
                monitoring = True
                address = hex(msg.data[0])
                if msg.arbitration_id not in range(256, 512) or address not in feedback_list:
                    continue
                can_bus_id = msg.arbitration_id-256
                part_number, serial_number = get_sn_pn_by_id(mapping_dict, can_bus_id)
                match address:
                    case '0x46':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "POSITION_MOTOR_Rad", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"rad", 
                                        "timestamp": datetime.now().isoformat()} 
                        #print(f"MCL_POSITION_MOTOR_Rad_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x47':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "POSITION_OUTPUT_Rad", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"rad", 
                                        "timestamp": datetime.now().isoformat()} 
                        #print(f"MCL_POSITION_OUTPUT_Rad_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x48':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "VELOCITY_Radps", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"rad/s", 
                                        "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_VELOCITY_Radps_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x49':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "CURRENT_IQ_A", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"A", 
                                        "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_CURRENT_IQ_A_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x4a':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "CURRENT_ID_A", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"A", 
                                        "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_CURRENT_ID_A_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x4c':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "BOARD_TEMP__degC", "data": struct.unpack('<f', msg.data[1:5])[0]/10, "unit":"°C", 
                                            "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_TEMP_BOARD_ddegC_FB:{struct.unpack('<i', msg.data[1:5])[0]/10}" + u"\u2103"+".")
                    case '0x4d':
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "MOTOR_TEMP_degC", "data": struct.unpack('<f', msg.data[1:5])[0]/10, "unit":"°C", 
                                            "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_TEMP_MOTOR_ddegC_FB:{struct.unpack('<i', msg.data[1:5])[0]/10}"+u"\u2103"+".")
                    case '0x41':  #status
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "STATUS", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        status = struct.unpack('<i', msg.data[1:5])[0]
                        self.redis_handler.set_value(f"{station_name}_can1_bus_{can_bus_id}_{serial_number}_status".strip(), status)  
                        #print(f"receive running status: {status}")
                    case '0x42':  #Calibration
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "CALIBRATION", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        self.redis_handler.set_value(f"{station_name}_can1_bus_{can_bus_id}_{serial_number}_calibration".strip(), struct.unpack('<i', msg.data[1:5])[0])    
                        #print(f"redis::{station_name}_can1_bus_{can_bus_id}_{serial_number}_calibration", struct.unpack('<i', msg.data[1:5])[0])
                        #calibrated_fb = struct.unpack('<i', msg.data[1:5])[0]
                        #print(f"receive calibration status: {calibrated_fb}")
                    case '0x43':  #error??
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id,"serial_number": serial_number, "part_number": part_number, "variable_name": "ERROR", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        #self.redis_handler.set_value(f"{station_name}_can1_bus_{can_bus_id}_{serial_number}_error", struct.unpack('<i', msg.data[1:5])[0])    
                        self.redis_handler.set_value(f"{station_name}_can1_bus_{can_bus_id}_{serial_number}_error".strip(), struct.unpack('<i', msg.data[1:5])[0])    

                        # print("receive error status")
                    case '0x44': #warning???
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "WARNING", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        self.redis_handler.set_value(f"{station_name}_can1_bus_{can_bus_id}_{serial_number}_warning".strip(), struct.unpack('<i', msg.data[1:5])[0])
                        
                        # warning_fb = struct.unpack('<i', msg.data[1:5])[0]
                        # print("receive warning status")
                    case '0x45': #control mode
                        self.bus1_feedback = {"can_bus":1, "can_bus_id": can_bus_id,"serial_number": serial_number, "part_number": part_number,  "variable_name": "CONTROL_MODE", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        # control_mode = struct.unpack('<i', msg.data[1:5])[0] 
                        # print("receive control mode")
           
                self.bus1_buffer.append(self.bus1_feedback)
                if len(self.bus1_buffer) > self.BUFFER_SIZE:
                    ####temparily just print the feedback, later will save to database
                    ###clear the buffer
                    print(f"{datetime.now().isoformat()} :Flushing CAN bus 0 feedback buffer with {len(self.bus1_buffer )} entries.")
                    self.bus1_buffer.clear()
        
                




def runinTest_monitor(canbus:str, db_handler: TimeScaleDBHandler_can1):
    can_bus = can.interface.Bus(channel= canbus, interface='socketcan')
    #feedback_list = [hex(x) for x in range(0x41, 0x4d+1)]
    timeout = 0.5  # 接收消息的超时时间（秒）
    #start_time = time.time()
    monitor_task = queue.Queue()
    stop_signal = threading.Event()
    thread = threading.Thread(target =db_handler.read_canbus, args=(monitor_task, can_bus, stop_signal,) )
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
                        monitor_task.put_nowait(message_content)
                        # thread = threading.Thread(target =read_canbus, args=(can_bus, stop_signal,) )
                        # thread.start()
                        monitor= True
                        if "calibration" is message_content:
                            current_task = "calibration"
                        else:
                            current_task = "runin_test"
                    # if current_task == "calibration":
                    #     if calibrated_fb & 0x01 ==1 and status & 0x1C == 0:
                    #             server_socket.sendto(json.dumps({"message":"motor calibration completed"}).encode('utf-8'), (HOST, UDP_PORT))
                    #             continue
                    #     if calibrated_fb & 0x02 ==1 and status & 0x1C == 0:
                    #             server_socket.sendto(json.dumps({"message":"encoder calibration completed"}).encode('utf-8'), (HOST, UDP_PORT))
                    #             continue
                    #     if calibrated_fb & 0x04 ==1 and status & 0x1C == 0:
                    #             server_socket.sendto(json.dumps({"message":"electrical calibration completed"}).encode('utf-8'), (HOST, UDP_PORT))
                    #             continue

     
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
    can1_db_handler = TimeScaleDBHandler_can1(host='192.168.2.47', port=5432, database='actuator_test', user='admin', password='ni50509800', 
                                              table='can1_feedback', flush_batch_size=1500, redis_bank=0, station_name=station_name)
    runinTest_monitor("can1", can1_db_handler)
