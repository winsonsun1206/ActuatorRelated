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

@dataclass
class TestSlot:
    part_number: str
    serial_number: str
    can_msg_id: int
    can_bus_id: int

HOST = '127.0.0.1'
UDP_PORT = 15005
BUFFER_SIZE = 2048
can_bus = "can1"

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
    save_to_flash_command = b'\x0C\x87\xA4\x42\x9F\x00\x00\x00'  # 示例保存到flash命令数据
    send_can_data(can_bus, can_msg_address, save_to_flash_command)
    time.sleep(6)  # 等待保存操作完成
    #load parameters from flash
    load_from_flash_command = b'\x0D\x01\x00\x00\x00\x00\x00\x00'  # 示例从flash加载命令数据
    send_can_data(can_bus, can_msg_address, load_from_flash_command)
    time.sleep(3)  # 等待加载操作完成

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
    def __init__(self, queue_name='test_queue', server_ip='192.168.2.47', port=5672):
        self.queue_name = queue_name
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout= 7201))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=queue_name)
        self.test_queue = queue.Queue()

    def callback(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        task = pickle.loads(body)
        if task.get('operation') == 'runin_test':
            test_slots = task.get('parameters', {})
            if not test_slots or len(test_slots) == 0:
                print("No test slots provided in the task parameters.")
                #ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            part_numbers = [slot.part_number for slot in test_slots]
            serial_numbers = [slot.serial_number for slot in test_slots]
            can_msg_addresses = [slot.can_msg_id for slot in test_slots]
            seq_file_20 = './resource/sequences/test_sequence_20.json'
            seq_file_70 = './resource/sequences/test_sequence_70.json'
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
                client_socket.settimeout(2.0)  # 设置超时时间为5秒
                try:
                    client_socket.sendto(json.dumps({
                        "message": f"Testing for Part Numbers: {','.join(part_numbers)}, Serial Numbers: {','.join(serial_numbers)}, CAN Addresses: {','.join(hex(addr) for addr in can_msg_addresses)}."
                    }).encode('utf-8'), (HOST, UDP_PORT))
                    print(f"Sent test start message to UDP server at {HOST}:{UDP_PORT}")
                    runin_test(part_numbers, serial_numbers, can_msg_addresses, seq_file_20)
                    runin_test(part_numbers, serial_numbers, can_msg_addresses, seq_file_70)
                    #time.sleep(5.0)
                    client_socket.sendto(json.dumps({"message": "task finished"}).encode('utf-8'), (HOST, UDP_PORT))
                    print(f"Sent test completion message to UDP server at {HOST}:{UDP_PORT}")
                    #ch.basic_ack(delivery_tag=method.delivery_tag)
                except socket.timeout:
                    print(f"Failed to send message to UDP server at {HOST}:{UDP_PORT} due to timeout.")
        elif task.get('operation') == 'calibration':
            test_slots = task.get('parameters', {})
            if not test_slots or len(test_slots) == 0:
                print("No test slots provided in the task parameters.")
                #ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            part_numbers = [slot.part_number for slot in test_slots]
            serial_numbers = [slot.serial_number for slot in test_slots]
            can_msg_addresses = [slot.can_msg_id for slot in test_slots]
            calibration_active = True
            
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
                client_socket.settimeout(1.0)
                start_time = datetime.now()
                calibrate_motor_parameter(part_numbers, serial_numbers, can_msg_addresses)
                time.sleep(1)
                client_socket.sendto(json.dumps({"message":"motor parameter calibration"}).encode('utf-8'), (HOST, UDP_PORT))
                while calibration_active and datetime.now()- start_time < 600.0:
                    try:
                        data, udp_ip = client_socket.recvfrom(BUFFER_SIZE)
                        message = json.loads(data.decode('utf-8'))
                        print(f"Received message from {udp_ip}: {message}")
                        message_content = message.get("message", "")
                        if "motor calibration completed" in message_content:
                            print("motor calibration finished")
                            break
                    except socket.timeout:
                        continue
                    except Exception as e:
                        print(f"An error occurred: {e}")
                        break
                calibrate_encoder_parameter(part_numbers, serial_numbers, can_msg_addresses)
                time.sleep(1)
                client_socket.sendto(json.dumps({"message":"encoder parameter calibration"}).encode('utf-8'), (HOST, UDP_PORT))
                while calibration_active and datetime.now()- start_time < 600.0:
                    try:
                        data, udp_ip = client_socket.recvfrom(BUFFER_SIZE)
                        message = json.loads(data.decode('utf-8'))
                        print(f"Received message from {udp_ip}: {message}")
                        message_content = message.get("message", "")
                        if "encoder calibration completed" in message_content:
                            print("encoder calibration finished")
                            break
                    except socket.timeout:
                        continue
                    except Exception as e:
                        print(f"An error occurred: {e}")
                        break

                calibrate_electrical_parameter(part_numbers, serial_numbers, can_msg_addresses)
                time.sleep(1)
                client_socket.sendto(json.dumps({"message":"electrical parameter calibration"}).encode('utf-8'), (HOST, UDP_PORT))
                while calibration_active and datetime.now()- start_time < 600.0:
                    try:
                        data, udp_ip = client_socket.recvfrom(BUFFER_SIZE)
                        message = json.loads(data.decode('utf-8'))
                        print(f"Received message from {udp_ip}: {message}")
                        message_content = message.get("message", "")
                        if "electrical calibration completed" in message_content:
                            print("electrical parameter calibration finished")
                            break
                    except socket.timeout:
                        continue
                    except Exception as e:
                        print(f"An error occurred: {e}")
                        break
                save_parameters_to_flash(part_numbers, serial_numbers, can_msg_addresses)
                client_socket.sendto(json.dumps({"message": "task finished"}).encode('utf-8'), (HOST, UDP_PORT))
            #ch.basic_ack(delivery_tag=method.delivery_tag)
        else:
            ch.basic_ack(delivery_tag=method.delivery_tag)
        # 在这里可以添加处理消息的逻辑

    def start_consuming(self):
        self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print('Waiting for messages. To exit press CTRL+C')
        self.channel.start_consuming()

if __name__ == "__main__":
    station_conf = read_station_conf()
    station_name = station_conf.get("station_name", "unknown_station").strip()
    consumer = RabbitmqCusumer(queue_name=f'runintest_queue_{station_name}_can1', server_ip='192.168.2.47', port=5672)
    consumer.start_consuming()
    