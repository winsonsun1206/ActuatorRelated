import os
import can
import time
import signal
from datetime import datetime, timedelta
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


#can0 = can.interface.Bus(channel='can1', bustype='socketcan')  # socketcan_native
HOST = '127.0.0.1'
UDP_PORT = 15006
BUFFER_SIZE = 2048    

status = 0
calibrated_fb=0
error_fb=0
warning_fb=0
control_mode =0
current_task =""
monitor = False


class TimeScaleDBHandler_can0:
    def __init__(self, host, port, database, user, password, table, flush_batch_size=1500, redis_bank=0,station_name="unknown_station"):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.BUFFER_SIZE = flush_batch_size
        self.bus0_feedback = {"can_bus":0}
        self.bus0_buffer= list()
        self.redis_handler = RedisHandler(host=host, port=6379, db=redis_bank)   
        self.station_name = station_name
        self.max_temp = dict()
        self.hw_version = dict()
        self.sw_version = dict()
        self.calibration = dict()
        self.error_code = dict()
        self.start_current = dict()
        self.end_current = dict()
        self.current = dict()
        self.voltage = dict()
        self.current_drift = dict()


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
                    ### in this condition, it means the monitoring just starts, we need to parse the mapping info sent from the UDP server, and then start monitoring the CAN bus
                    mapping_dict = parse_mapping_id_sn(monitor_task)
                    self.max_temp = dict()  # reset max temp when new monitoring starts 
                    self.calibration = dict()  # reset calibration status when new monitoring starts
                    self.error_code = dict()  # reset error code when new monitoring starts 
                    self.start_current = dict()  # reset start current when new monitoring starts
                    self.end_current = dict()  # reset end current when new monitoring starts
                    self.current = dict()  # reset current when new monitoring starts
                    self.voltage = dict()  # reset voltage when new monitoring starts
                    self.current_drift = dict()  # reset current drift when new monitoring starts
                    self.high_speed_start_time = dict()  # reset high speed start time when new monitoring starts
                    print(f"Parsed mapping dictionary: {mapping_dict}")
                
                monitoring = True
                address = hex(msg.data[0])
                if msg.arbitration_id not in range(256, 512) or address not in feedback_list:
                    continue
                can_bus_id = msg.arbitration_id-256
                part_number, serial_number = get_sn_pn_by_id(mapping_dict, can_bus_id)
                match address:
                    case '0x46':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "POSITION_MOTOR_Rad", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"rad", 
                                        "timestamp": datetime.now().isoformat()} 
                        #print(f"MCL_POSITION_MOTOR_Rad_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x47':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "POSITION_OUTPUT_Rad", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"rad", 
                                        "timestamp": datetime.now().isoformat()} 
                        #print(f"MCL_POSITION_OUTPUT_Rad_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x48':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "VELOCITY_Radps", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"rad/s", 
                                        "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_VELOCITY_Radps_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                        velocity = struct.unpack('<f', msg.data[1:5])[0]
                        if abs(velocity) > 152 and self.high_speed_start_time.get(can_bus_id) is None:  # assuming 152 rad/s as the threshold for high speed, this value can be adjusted based on actual requirement
                            self.high_speed_start_time[can_bus_id] = datetime.now()
                        if abs(velocity) > 152 and self.high_speed_start_time.get(can_bus_id) is not None and self.start_current[can_bus_id] is None:
                            if datetime.now() - self.high_speed_start_time[can_bus_id] > timedelta(seconds=3):  # if high speed lasts for more than 3 seconds, we consider it as a valid high speed state, this duration can also be adjusted
                                # if high speed lasts for more than 5 seconds, we consider it as a valid high speed state, this duration can also be adjusted
                                self.start_current[can_bus_id] = self.current.get(can_bus_id, 0.0)
                                
                        if abs(velocity) > 152 and self.high_speed_start_time.get(can_bus_id) is not None and datetime.now() - self.high_speed_start_time[can_bus_id] > timedelta(seconds=50) and self.end_current.get(can_bus_id) is None:
                                self.end_current[can_bus_id] = self.current.get(can_bus_id, 0.0)
                                self.current_drift[can_bus_id] = (self.end_current[can_bus_id] - self.start_current[can_bus_id])/ self.start_current[can_bus_id]
                                # if high speed lasts for more than 3 seconds, we consider it as a valid high speed state, this duration can also be adjusted
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "high_speed_current", "data": self.current[can_bus_id], "unit":"A", 
                                        "timestamp": datetime.now().isoformat()}
                            
                    case '0x49':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "CURRENT_IQ_A", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"A", 
                                        "timestamp": datetime.now().isoformat()}
                        self.current[can_bus_id] = struct.unpack('<f', msg.data[1:5])[0]
                        #print(f"MCL_CURRENT_IQ_A_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x4a':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "CURRENT_ID_A", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"A", 
                                        "timestamp": datetime.now().isoformat()}
                        
                        #print(f"MCL_CURRENT_ID_A_FB:{struct.unpack('<f', msg.data[1:5])[0]}.")
                    case '0x4b':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "IC_Voltage", "data": struct.unpack('<f', msg.data[1:5])[0], "unit":"V", 
                                            "timestamp": datetime.now().isoformat()}
                        self.voltage[can_bus_id] = struct.unpack('<f', msg.data[1:5])[0]
                        
                        
                    case '0x4c':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "BOARD_TEMP__degC", "data": struct.unpack('<i', msg.data[1:5])[0]/10, "unit":"°C", 
                                            "timestamp": datetime.now().isoformat()}
                        #print(f"MCL_TEMP_BOARD_ddegC_FB:{struct.unpack('<i', msg.data[1:5])[0]/10}" + u"\u2103"+".")
                    case '0x4d':
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "MOTOR_TEMP_degC", "data": struct.unpack('<i', msg.data[1:5])[0]/10, "unit":"°C", 
                                            "timestamp": datetime.now().isoformat()}
                        temperature = struct.unpack('<i', msg.data[1:5])[0]/10
                        self.max_temp[can_bus_id] = temperature if temperature > self.max_temp.get(can_bus_id, float('-inf')) else self.max_temp.get(can_bus_id, float('-inf'))
                        #print(f"MCL_TEMP_MOTOR_ddegC_FB:{struct.unpack('<i', msg.data[1:5])[0]/10}"+u"\u2103"+".")
                    case '0x41':  #status
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "STATUS", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        status = struct.unpack('<i', msg.data[1:5])[0]
                        #self.redis_handler.set_value(f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_status".strip(), status)  
                        #print(f"receive running status: {status}")
                    case '0x42':  #Calibration
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "CALIBRATION", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        self.calibration[can_bus_id] = struct.unpack('<i', msg.data[1:5])[0]
                        #self.redis_handler.set_value(f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_calibration".strip(), struct.unpack('<i', msg.data[1:5])[0])    
                        #print(f"redis::{station_name}_can0_bus_{can_bus_id}_{serial_number}_calibration", struct.unpack('<i', msg.data[1:5])[0])
                        #calibrated_fb = struct.unpack('<i', msg.data[1:5])[0]
                        #print(f"receive calibration status: {calibrated_fb}")
                    case '0x43':  #error??
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id,"serial_number": serial_number, "part_number": part_number, "variable_name": "ERROR", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        self.error_code[can_bus_id] = struct.unpack('<i', msg.data[1:5])[0] if struct.unpack('<i', msg.data[1:5])[0] !=0 else self.error_code.get(can_bus_id, 0)
                        #self.redis_handler.set_value(f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_error", struct.unpack('<i', msg.data[1:5])[0])    
                        #self.redis_handler.set_value(f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_error".strip(), struct.unpack('<i', msg.data[1:5])[0])    

                        # print("receive error status")
                    case '0x44': #warning???
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id, "serial_number": serial_number, "part_number": part_number, "variable_name": "WARNING", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        #self.redis_handler.set_value(f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_warning".strip(), struct.unpack('<i', msg.data[1:5])[0])
                        
                        # warning_fb = struct.unpack('<i', msg.data[1:5])[0]
                        # print("receive warning status")
                    case '0x45': #control mode
                        self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id,"serial_number": serial_number, "part_number": part_number,  "variable_name": "CONTROL_MODE", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                                        "timestamp": datetime.now().isoformat()}
                        
                    # case '0x5d': # firmware_version
                    #     self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id,"serial_number": serial_number, "part_number": part_number,  "variable_name": "FIRMWARE_VERSION", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                    #                     "timestamp": datetime.now().isoformat()}
                    #     self.sw_version[can_bus_id] = struct.unpack('<i', msg.data[1:5])[0]
                    # case '0x5e': # hardware_version
                    #     self.bus0_feedback = {"can_bus":0, "can_bus_id": can_bus_id,"serial_number": serial_number, "part_number": part_number,  "variable_name": "HARDWARE_VERSION", "data": struct.unpack('<i', msg.data[1:5])[0], "unit":"", 
                    #                     "timestamp": datetime.now().isoformat()}
                    #     self.hw_version[can_bus_id] = struct.unpack('<i', msg.data[1:5])[0]
                        
                        # control_mode = struct.unpack('<i', msg.data[1:5])[0] 
                        # print("receive control mode")
           
                self.bus0_buffer.append(self.bus0_feedback)
                if len(self.bus0_buffer) > self.BUFFER_SIZE:
                    ####temparily just print the feedback, later will save to database
                    ###clear the buffer
                    #print(f"{datetime.now().isoformat()} :Flushing CAN bus 0 feedback buffer with {len(self.bus0_buffer )} entries.")
                    #replace a print task with real postgresql insertion task:
                    
                    self.bus0_buffer.clear()
        
                




def runinTest_monitor(canbus:str, db_handler: TimeScaleDBHandler_can0):
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
                    print(f"Received message from {udp_ip[0]}:{udp_ip[1]}: {message}")
                    message_content = message.get("message", "")
                    if "task finished" in message_content:
                        #  stop_signal.set()
                        #  thread.join()
                         monitor = False
                         monitor_task.put_nowait("False")
                         #sendback the test result through udp, starting from max temperature
                         test_result= {"max_temperature": db_handler.max_temp, "calibration": db_handler.calibration, "error_code": db_handler.error_code,
                                       "start_current": db_handler.start_current, "current_drift": db_handler.current_drift, "r_voltage": db_handler.voltage}
                         server_socket.sendto(json.dumps({"message": "test result", "data": test_result}).encode('utf-8'), (udp_ip[0], udp_ip[1]))
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
    can0_db_handler = TimeScaleDBHandler_can0(host='192.168.2.47', port=5432, database='actuator_test', user='admin', password='ni50509800', 
                                              table='can0_feedback', flush_batch_size=1500, redis_bank=0, station_name=station_name)
    runinTest_monitor("can0", can0_db_handler)
