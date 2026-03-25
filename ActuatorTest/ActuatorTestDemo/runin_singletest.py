import os
import click
import sys
from utils.sequence_parse import parse_test_cases
from utils.send_data import send_can_data
import can
import time
import struct
from utils.generate_tmp import write_tmp_file


@click.command()
@click.argument('actuator_pn', type=str)
@click.argument('actuator_sn', type=str)
@click.argument('can_msg_address', type=int)

@click.option('--seq_file', default='/home/winsonsun/Documents/ActuatorTest/AcuatorTestDemo/resource/sequences/test_sequence.json', help='Path to the test sequence JSON file.')

def runin_singlesocket(actuator_pn:str, actuator_sn:str, can_msg_address: int,  seq_file:str):

    test_cases, dut_info, test_plan = parse_test_cases(seq_file)
    max_speed = dut_info.get("max_speed", 219)  # 从DUT信息中获取最大速度，默认为120
    loop_nums = dut_info.get("loop_nums", 61)  # 从DUT信息中获取循环次数，默认为60

    if test_cases is None or len(test_cases) == 0:
        return 0
    print(f"Running test sequence for Actuator PN: {actuator_pn}, SN: {actuator_sn}, CAN Address: {hex(can_msg_address)}")
    
    print("=" * 50)
    send_can_data(can_msg_address, b'\x01\x89\xfd\x86\x13\x00\x00\x00')  # 发送速度为0的消息以停止执行
    send_can_data(can_msg_address, b'\x00\x01\x00\x00\x00\x00\x00\x00')  # 发送加速度为0的消息
    send_can_data(can_msg_address, b'\x03\x03\x00\x00\x00\x00\x00\x00')  # 发送减速度为0的消息
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
            send_can_data(can_msg_address, acceleration_data)
            print(f"      Acceleration data to send: {acceleration_data.hex()}")
            #--------------------
            deceleration_data = struct.pack('<f', deceleration)  # 将减速度转换
            deceleration_data = b'\x1F' + deceleration_data + b'\x02\x00\x00'  # 补齐到8字节
            print(f"      Deceleration data to send: {deceleration_data.hex()}")
            send_can_data(can_msg_address, deceleration_data)
            #--------------------    
            speed = struct.pack('<f', speed_target)  # 将速度目标转换为4字节小端格式
            speed_data = b'\x12' + speed + b'\x02\x00\x00'  # 补齐到8字节
            print(f"      Speed target data to send: {speed_data.hex()}")
            send_can_data(can_msg_address,speed_data)
            #----------------------------
            ## counting down the sleep time for better visualization of the test process
            for remaining in range(duration, 0, -1):
                sys.stdout.write(f"\r      Time remaining: {remaining} seconds")
                sys.stdout.flush()
                time.sleep(1)
            print("\n      Test case execution completed. Entering quiescent time.")
            quiescent_time = parameters.get("quiescent_time", 0)
            send_can_data(can_msg_address, b'\x12\x00\x00\x00\x00\x02\x00\x00')  # 发送速度为0的消息以停止执行
            for remaining in range(quiescent_time, 0, -1):
                sys.stdout.write(f"\r      Quiescent time remaining: {remaining} seconds")
                sys.stdout.flush()
                time.sleep(1)
            print("\n      Quiescent time completed.")
            print("=" * 50)


if __name__ == "__main__":
    runin_singlesocket()
    