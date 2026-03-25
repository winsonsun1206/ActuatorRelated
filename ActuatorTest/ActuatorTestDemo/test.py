import os
import can

os.system('sudo ip link set can0 type can bitrate 1000000')
os.system('sudo ip link set can1 type can bitrate 1000000')
os.system('sudo ifconfig can0 up')
os.system('sudo ifconfig can1 up')

# 初始化CAN总线
can0 = can.interface.Bus(channel='can0', interface='socketcan')  # 使用socketcan接口
can1 = can.interface.Bus(channel='can1', interface='socketcan')  # 使用socketcan接口

try:
    # 构造CAN消息
    # msg = can.Message(arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7], is_extended_id=False)

    # # 发送消息到can0
    # can1.send(msg)
    # print("Sent:", msg)

    # 接收can0的消息
    received_msg = can0.recv(0.1)
    print("Received:", received_msg)
    print("message_id", received_msg.arbitration_id-256)

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


# def connect_rabbitmq(queue_name='test_queue'):
#     credentials = pika.PlainCredentials('admin', 'ni50509800')
#     connection = pika.BlockingConnection(pika.ConnectionParameters('192.168.2.47', 5672,'/', credentials))
#     channel = connection.channel()
#     channel.queue_declare(queue=queue_name, durable=True)
#     return connection

# def test_callback(ch, method, properties, body):
#     task= json.loads(body)
#     operation = task.get('operation')
#     if operation == 'runin_test':
#         actuator_pn = task.get('actuator_pn')
#         actuator_sn = task.get('actuator_sn')
#         can_msg_address = task.get('can_msg_address')
#         seq_file = task.get('seq_file')
#         print(f"Received task: {task}")
#         #runin_test(actuator_pn, actuator_sn, can_msg_address, seq_file)
#     ch.basic_ack(delivery_tag=method.delivery_tag)