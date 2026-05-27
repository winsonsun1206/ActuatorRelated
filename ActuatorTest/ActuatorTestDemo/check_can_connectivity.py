import can
import time
from datetime import datetime, timedelta
from utils.send_data import send_can_data, send_heartbeat
BUFFER_SIZE = 2048 

if __name__ == "__main__":
    print("Starting CAN connectivity check...")
    can_bus = input("Enter CAN bus to test (e.g., 'can0' or 'can1'): ")
    can_bus_interface = can.interface.Bus(channel=can_bus.strip(), interface='socketcan')
    arbitration_id_list = [int(x, 16) for x in input("Enter arbitration ID to test (e.g., 0x01) use comma to seperate each id: and press Enter: ").split(',')]
    found_device = dict()
    start_time = datetime.now(timezone.utc)
    while datetime.now(timezone.utc) - start_time < timedelta(seconds=5):  # 设置一个超时时间，例如30秒
        msg = can_bus_interface.recv(BUFFER_SIZE)  # 等待接收消息，设置适当的超时
        address = hex(msg.data[0])
        if msg.arbitration_id not in range(256, 512):
                    continue
        can_bus_id = msg.arbitration_id-256
        found_device[can_bus_id] = True
        #### if all of can_bus_id can be found, break the loop,the range is from 1 to 4
        if all(id in found_device for id in arbitration_id_list):
            print("All devices found on CAN bus.")
            break
        
    print(f"Finished CAN connectivity check. Found devices: {list(found_device.keys())}")
    print("send heartbeat message...")
    while True:
        send_heartbeat(can_bus, arbitration_id_list)
        #print(f"Sent heartbeat message on {can_bus} for arbitration ID: {arbitration_id_list}")
        time.sleep(1)
        
        