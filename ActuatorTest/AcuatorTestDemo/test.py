import os
import can

os.system('sudo ip link set can0 type can bitrate 100000')
os.system('sudo ip link set can1 type can bitrate 100000')
os.system('sudo ifconfig can0 up')
os.system('sudo ifconfig can1 up')

# 初始化CAN总线
can0 = can.interface.Bus(channel='can0', bustype='socketcan')  # 使用socketcan接口
can1 = can.interface.Bus(channel='can1', bustype='socketcan')  # 使用socketcan接口

try:
    # 构造CAN消息
    msg = can.Message(arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7], is_extended_id=False)

    # 发送消息到can0
    can1.send(msg)
    print("Sent:", msg)

    # 接收can0的消息
    received_msg = can0.recv(0.1)
    print("Received:", received_msg)

    # 如果接收到的消息为None，即超时，则输出相应信息
    if received_msg is None:
        print('Timeout occurred, no message.')

finally:
    # 关闭CAN总线
    can0.shutdown()
    can1.shutdown()

    # 关闭CAN通道
    os.system('sudo ifconfig can0 down')
    os.system('sudo ifconfig can1 down')
