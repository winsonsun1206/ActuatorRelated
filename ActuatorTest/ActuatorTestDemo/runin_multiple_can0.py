import os
import click
import sys
from utils.sequence_parse import parse_test_cases
from utils.send_data import send_can_data
import can
import time, datetime
import struct
from utils.generate_tmp import write_tmp_file
import pika
import json
import threading
import queue
import pickle
from dataclasses import dataclass, asdict
import socket
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler



@dataclass
class TestSlot:
    part_number: str
    serial_number: str
    can_msg_id: int

HOST = '127.0.0.1'
UDP_PORT = 15006
BUFFER_SIZE = 2048
can_bus = "can0"

def heartbeat_calibration(can_msg_address: list[int], timeout):
    # send heart beat command every 0.05 second.
    heartbeat_command = b'\x3F\x73\xC6\xFA\x85\x00\x00\x00'  # 示例心跳命令数据
    #request data streaming
    streaming = b'\x0F\x00\x00\x00\x00\x00\x00\x00'  # 示例请求数据流命令数据
    start_time = time.time()
    while time.time() - start_time < timeout:
        send_can_data(can_bus, can_msg_address, heartbeat_command)
        wait_time = 0.05
        send_can_data(can_bus, can_msg_address, streaming)

        time.sleep(wait_time)




def check_calibration_status(redis_handler, redis_key:list, expected_value:list, timeout):
    start_time = time.time()
    while time.time() - start_time < timeout:
        for key, expected in zip(redis_key, expected_value):
            value = redis_handler.get_value(key)
            print(f"Checking calibration status for {key}: current value={value}, expected value={expected}")
            #### check the bits of return value and expected value, if the same, return true, if not, continue to wait until timeout
            if value & expected != expected:
                continue
            else:
                break  # 如果当前值等于预期值，跳出循环继续等待
        else:  # 如果内层循环没有被break打断，说明所有值都达到了预期，返回True
            return True
        time.sleep(1)  # 等待1秒后再次检查
        # 如果超时了还没有达到预期值，返回False
    return False


def calibrate_motor_parameter(actuator_pn:list[str], actuator_sn:list[str], can_msg_address: list[int]):
    print(f"Calibrating actuator with PN: {','.join(actuator_pn)}, SN: {','.join(actuator_sn)}, CAN Address: {','.join(hex(addr) for addr in can_msg_address)}")
    # 发送校准命令的CAN消息，假设校准命令为0x01，数据为0x01
    #cansend can1 003#0601000000000000
    motor_param_calibration_command = b'\x06\x01\x00\x00\x00\x00\x00\x00'  # 示例校准命令数据
    send_can_data(can_bus, can_msg_address, motor_param_calibration_command)
  

def calibrate_encoder_parameter(actuator_pn:list[str], actuator_sn:list[str], can_msg_address: list[int]):
    print(f"Calibrating actuator with PN: {','.join(actuator_pn)}, SN: {','.join(actuator_sn)}, CAN Address: {','.join(hex(addr) for addr in can_msg_address)}")
    # 发送校准命令的CAN消息，假设校准命令为0x01，数据为0x01
    #cansend can1 003#0601000000000000
    encoder_calibration_command = b'\x08\x01\x00\x00\x00\x00\x00\x00'  # 示例校准命令数据   
    send_can_data(can_bus, can_msg_address, encoder_calibration_command)


def calibrate_electrical_parameter(actuator_pn:list[str], actuator_sn:list[str], can_msg_address: list[int]):
    print(f"Calibrating actuator with PN: {','.join(actuator_pn)}, SN: {','.join(actuator_sn)}, CAN Address: {','.join(hex(addr) for addr in can_msg_address)}")
    # 发送校准命令的CAN消息，假设校准命令为0x01，数据为0x01
    #cansend can1 003#0601000000000000
    electrical_param_calibration_command = b'\x07\x01\x00\x00\x00\x00\x00\x00'  # 示例校准命令数据
    send_can_data(can_bus, can_msg_address, electrical_param_calibration_command)


def save_parameters_to_flash(actuator_pn:list[str], actuator_sn:list[str], can_msg_address: list[int]):
    print(f"Saving parameters to flash for actuator with PN: {','.join(actuator_pn)}, SN: {','.join(actuator_sn)}, CAN Address: {','.join(hex(addr) for addr in can_msg_address)}")
    # 发送保存参数到flash的CAN消息，假设命令为0x0C，数据为0x87A4429F
    save_to_flash_command = b'\x0C\x9F\x42\xA4\x87\x00\x00\x00'  # 示例保存到flash命令数据
    send_can_data(can_bus, can_msg_address, save_to_flash_command)
    time.sleep(6)  # 等待保存操作完成
    #load parameters from flash
    load_from_flash_command = b'\x0D\x01\x00\x00\x00\x00\x00\x00'  # 示例从flash加载命令数据
    send_can_data(can_bus, can_msg_address, load_from_flash_command)
    # time.sleep(3)  # 等待加载操作完成

def runin_test(actuator_pn:list[str], actuator_sn:list[str], can_msg_address: list[int],  seq_file:str):

    test_cases, dut_info = parse_test_cases(seq_file)
    max_speed = dut_info.get("max_speed", 219)  # 从DUT信息中获取最大速度，默认为120
    loop_nums = dut_info.get("loop_nums", 61)  # 从DUT信息中获取循环次数，默认为60

    if test_cases is None or len(test_cases) == 0:
        return 0
    print(f"Running test sequence for Actuator PN: {",".join(actuator_pn)}, SN: {",".join(actuator_sn)}, CAN Address: {",".join(hex(addr) for addr in can_msg_address)}")
    
    print("=" * 50)
    send_can_data(can_bus, can_msg_address, b'\x01\x89\xfd\x86\x13\x00\x00\x00')  # 发送速度为0的消息以停止执行
    send_can_data(can_bus, can_msg_address, b'\x00\x01\x00\x00\x00\x00\x00\x00')  # 发送加速度为0的消息
    send_can_data(can_bus, can_msg_address, b'\x03\x03\x00\x00\x00\x00\x00\x00')  # 发送减速度为0的消息
    test_case_index =0
    for loop in range(loop_nums):
        print(f"Starting loop {loop+1}/{loop_nums}...")
        for test_case in test_cases:
            test_id = test_case.get("id")
            test_name = test_case.get("name")
            description = test_case.get("description")
            parameters = test_case.get("parameters", {})
            
            print(f"Test Case {test_id}: {test_name}. Description: {description}")
            speed_target = parameters.get("speed_target", 0) * max_speed
            acceleration = parameters.get("acceleration", 0)
            deceleration = parameters.get("deceleration", 0)
            duration = parameters.get("duration", 0)
            print(f"      Executing test case {test_id} with parameters: speed_target={speed_target}, acceleration={acceleration}, deceleration={deceleration}, duration={duration}, quiescent_time={parameters.get('quiescent_time', 0)}")
            print("-" * 40)
            # 构造要发送的数据，这里假设要发送速度目标
            #convert the acceleration to little-endian byte format
            acceleration_data = struct.pack('<f', acceleration)  # 将加速度转换为4字节小端格式
            #the first byte of payload is can id, followed by 
            # can id is hex of can_msg_address, for example, if can_msg_address is 0x03, the first byte of payload should be 0x03
            # add one byte of 0x12 as the sub address for acceleration, anb make it ahead of acceleration data
            acceleration_data = b'\x1E' + acceleration_data + b'\x02\x00\x00'  # 补齐到8字节
            send_can_data(can_bus, can_msg_address, acceleration_data)
            print(f"      Acceleration data to send: {acceleration_data.hex()}")
            #--------------------
            deceleration_data = struct.pack('<f', deceleration)  # 将减速度转换
            deceleration_data = b'\x1F' + deceleration_data + b'\x02\x00\x00'  # 补齐到8字节
            print(f"      Deceleration data to send: {deceleration_data.hex()}")
            send_can_data(can_bus, can_msg_address, deceleration_data)
            #--------------------    
            speed = struct.pack('<f', speed_target)  # 将速度目标转换为4字节小端格式
            speed_data = b'\x12' + speed + b'\x02\x00\x00'  # 补齐到8字节
            print(f"      Speed target data to send: {speed_data.hex()}")
            send_can_data(can_bus, can_msg_address, speed_data)
            #----------------------------
            ## counting down the sleep time for better visualization of the test process
            for remaining in range(duration, 0, -1):
                sys.stdout.write(f"\r      Time remaining: {remaining} seconds")
                sys.stdout.flush()
                time.sleep(1)
            print("\n      Test case execution completed. Entering quiescent time.")
            quiescent_time = parameters.get("quiescent_time", 0)
            send_can_data(can_bus, can_msg_address, b'\x12\x00\x00\x00\x00\x02\x00\x00')  # 发送速度为0的消息以停止执行
            for remaining in range(quiescent_time, 0, -1):
                sys.stdout.write(f"\r      Quiescent time remaining: {remaining} seconds")
                sys.stdout.flush()
                time.sleep(1)
            print("\n      Quiescent time completed.")
            print("=" * 50)

class RabbitmqCusumer:
    def __init__(self, queue_name='test_queue', server_ip='192.168.2.47', port=5672, redis_db=0):
        self.queue_name = queue_name
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout= 7201))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=queue_name)
        self.test_queue = queue.Queue()
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True   # 设置为守护线程，这样在主线程退出时它会自动结束
        self.test_consumer_thread.start()
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=redis_db)

    def callback(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        try:
            task = pickle.loads(body)
            self.test_queue.put_nowait(task)
        except Exception as e:
            print(f"Failed to process message: {e}")



    #####put blew task in another thread to avoid blocking the callback function, which will block the RabbitMQ from sending ACK to server, and cause the message to be re-delivered and processed repeatedly##### 
    def process_tasks(self):
        while True:
            try:
                task = self.test_queue.get_nowait()  # 等待新任务，超时设置为1秒以便定期检查线程是否应该退出
                if task is None:  # 如果收到None，表示应该退出线程
                    continue
                elif task.get('operation') == 'runin_test':
                    test_slots = task.get('parameters', {})
                    task_id = task.get('task_id', f'can0_unknown_runin_task_id_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}').strip()
                    if not test_slots or len(test_slots) == 0:
                        print("No test slots provided in the task parameters.")
                        continue

                    part_numbers = [slot.part_number for slot in test_slots]
                    serial_numbers = [slot.serial_number for slot in test_slots]
                    can_msg_addresses = [slot.can_msg_id for slot in test_slots]
                    seq_file_20 = '~/ActuatorTest/ActuatorTestDemo/resource/sequences/test_sequence_20.json'
                    seq_file_70 = '~/ActuatorTest/ActuatorTestDemo/resource/sequences/test_sequence_70.json'
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
                        self.redis_handler.set_value(task_id, 0.0)
                        client_socket.settimeout(2.0)  # 设置超时时间为5秒
                        try:
                            client_socket.sendto(json.dumps({
                                "message": f"runin_test for Part Numbers: {','.join(part_numbers)}, Serial Numbers: {','.join(serial_numbers)}, CAN Addresses: {','.join(hex(addr) for addr in can_msg_addresses)}"
                            }).encode('utf-8'), (HOST, UDP_PORT))
                            print(f"Sent test start message to UDP server at {HOST}:{UDP_PORT}")
                            
                            runin_test(part_numbers, serial_numbers, can_msg_addresses, seq_file_20)
                            self.redis_handler.set_value(task_id, 0.5)
                            runin_test(part_numbers, serial_numbers, can_msg_addresses, seq_file_70)
                            #time.sleep(5.0)
                            client_socket.sendto(json.dumps({"message": "task finished"}).encode('utf-8'), (HOST, UDP_PORT))
                            print(f"Sent test completion message to UDP server at {HOST}:{UDP_PORT}")
                        except socket.timeout:
                            print(f"Failed to send message to UDP server at {HOST}:{UDP_PORT} due to timeout.")
                        finally:
                            self.redis_handler.set_value(task_id, 1.0) # 设置一个redis键值对来标识通信超时
                elif task.get('operation') == 'calibration':
                    test_slots = task.get('parameters', {})
                    task_id = task.get('task_id', f'can0_unknown_calibration_task_id_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}')
                    if not test_slots or len(test_slots) == 0:
                        print("No test slots provided in the task parameters.")
                        continue
                    part_numbers = [slot.part_number for slot in test_slots]
                    serial_numbers = [slot.serial_number for slot in test_slots]
                    can_msg_addresses = [slot.can_msg_id for slot in test_slots]
                    calibration_active = True
                   
                    
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
                        client_socket.settimeout(1.0)
                        client_socket.sendto(json.dumps({
                                "message": f"calibration for Part Numbers: {','.join(part_numbers)}, Serial Numbers: {','.join(serial_numbers)}, CAN Addresses: {','.join(hex(addr) for addr in can_msg_addresses)}"
                            }).encode('utf-8'), (HOST, UDP_PORT))
                        start_time = datetime.datetime.now()
                        #reset parameters:
                        # calibrate_motor_parameter(part_numbers, serial_numbers, can_msg_addresses)
                        # heartbeat_calibration(can_msg_addresses, timeout=300)
                        # time.sleep(5)
                        # #"f{station_name}_can0_bus_{can_bus_id}_{serial_number}_status".strip()"
                        # key_list = [f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_calibration".strip() for can_bus_id, serial_number in zip(can_msg_addresses, serial_numbers)] + [f"{station_name}_can0_bus_{can_bus_id}_{serial_number}_status".strip() for can_bus_id, serial_number in zip(can_msg_addresses, serial_numbers)]
                        # value_list = [0x01]*len(can_msg_addresses)+ [0x00]*len(can_msg_addresses)  # calibration status should be 1, and running status should be 0x3 for calibration completed
                                                
                        # if check_calibration_status(self.redis_handler, key_list, value_list, timeout=300):
                        #     print("Calibration status check passed. Proceeding with encoder and electrical parameter calibration.")
                        # else:
                        #     print("Calibration status check failed and timeout. Please check the device and try again.")
                        #     continue  # 跳过后续的校准步骤
                        #self.redis_handler.set_value(f"{station_name}_can0_bus_{can_msg_addresses[0]}_{serial_numbers[0]}_status".strip(), 0)  # 重置状态为0，等待校准完成的反馈
                        # time.sleep(500)
                        self.redis_handler.set_value(task_id, 0.0)
                        calibrate_encoder_parameter(part_numbers, serial_numbers, can_msg_addresses)
                        heartbeat_calibration(can_msg_addresses, timeout=230)
                        self.redis_handler.set_value(task_id, 0.5)
                        calibrate_electrical_parameter(part_numbers, serial_numbers, can_msg_addresses)
                        heartbeat_calibration(can_msg_addresses, timeout=230)
                        save_parameters_to_flash(part_numbers, serial_numbers, can_msg_addresses)
                        client_socket.sendto(json.dumps({"message": "task finished"}).encode('utf-8'), (HOST, UDP_PORT))
                        print("Calibration process completed.")
                        self.redis_handler.set_value(task_id, 1.0)
                        #client_socket.sendto(json.dumps({"message":"motor parameter calibration"}).encode('utf-8'), (HOST, UDP_PORT))
                        # while calibration_active and datetime.datetime.now()- start_time < 600.0:
                        #     try:
                        #         data, udp_ip = client_socket.recvfrom(BUFFER_SIZE)
                        #         message = json.loads(data.decode('utf-8'))
                        #         print(f"Received message from {udp_ip}: {message}")
                        #         message_content = message.get("message", "")
                        #         if "motor calibration completed" in message_content:
                        #             print("motor calibration finished")
                        #             break
                        #     except socket.timeout:
                        #         continue
                        #     except Exception as e:
                        #         print(f"An error occurred: {e}")
                        #         break
                        # calibrate_encoder_parameter(part_numbers, serial_numbers, can_msg_addresses)
                        # time.sleep(1)
                        # client_socket.sendto(json.dumps({"message":"encoder parameter calibration"}).encode('utf-8'), (HOST, UDP_PORT))
                        # while calibration_active and datetime.now()- start_time < 600.0:
                        #     try:
                        #         data, udp_ip = client_socket.recvfrom(BUFFER_SIZE)
                        #         message = json.loads(data.decode('utf-8'))
                        #         print(f"Received message from {udp_ip}: {message}")
                        #         message_content = message.get("message", "")
                        #         if "encoder calibration completed" in message_content:
                        #             print("encoder calibration finished")
                        #             break
                        #     except socket.timeout:
                        #         continue
                        #     except Exception as e:
                        #         print(f"An error occurred: {e}")
                        #         break       
            except queue.Empty:
                continue  # 如果没有任务，继续等待


        

    def start_consuming(self):
        self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print('Waiting for messages. To exit press CTRL+C')
        self.channel.start_consuming()

if __name__ == "__main__":
    station_conf = read_station_conf()
    station_name = station_conf.get("station_name", "unknown_station").strip()
    consumer = RabbitmqCusumer(queue_name=f'runintest_queue_{station_name}_can0', server_ip='192.168.2.47', port=5672)
    consumer.start_consuming()
    