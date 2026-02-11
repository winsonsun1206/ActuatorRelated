import os
import can
import time

os.system('sudo ip link set can1 type can bitrate 100000')
os.system('sudo ifconfig can1 up')

can1 = can.interface.Bus(channel='can1', bustype='socketcan')  # socketcan_native

def send_data(data):
    # 构造要发送的消息
    arbitration_id = 0x03
    msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=False)

    # 发送消息
    try:
        can1.send(msg)
        print("Message sent on can1:", msg)
    except can.CanError:
        print("Failed to send message")

# 发送可变数据
try:
    while True:
        # 获取当前时间戳并转换为字节序列
        timestamp = int(time.time()).to_bytes(4, byteorder='big')
        # 构造要发送的数据，这里假设要发送时间戳
        data = "3F73C6FA85000000"
        # 调用发送函数
        send_data(data)
        time.sleep(0.5)
except KeyboardInterrupt:
    pass

can1.shutdown()
os.system('sudo ifconfig can1 down')
