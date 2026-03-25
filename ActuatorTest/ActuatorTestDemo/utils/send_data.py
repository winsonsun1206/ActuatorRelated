import os
import can
import time

def send_can_data(canbus:str,arbitration_id, data):
    # 构造要发送的消息
    if canbus == 'can1':
        with can.interface.Bus(channel='can1', interface='socketcan') as can1:
            if type(arbitration_id) != list:
                msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=False)
                # 发送消息
                try:
                    can1.send(msg)
                    #print("Message sent on can1:", msg)
                except can.CanError:
                    print("Failed to send message")
            elif type(arbitration_id) == list and len(arbitration_id) > 0:
                for i in range(len(arbitration_id)):
                    msg = can.Message(arbitration_id=arbitration_id[i], data=data, is_extended_id=False)
                    try:
                        can1.send(msg)
                        #print(f"Message sent on can1: {msg}")
                    except can.CanError:
                        print("Failed to send message")
    elif canbus == 'can0':
        with can.interface.Bus(channel='can0', interface='socketcan') as can0:
            if type(arbitration_id) != list:
                msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=False)
                # 发送消息
                try:
                    can0.send(msg)
                    #print("Message sent on can0:", msg)
                except can.CanError:
                    print("Failed to send message")
            elif type(arbitration_id) == list and len(arbitration_id) > 0:
                for i in range(len(arbitration_id)):
                    msg = can.Message(arbitration_id=arbitration_id[i], data=data, is_extended_id=False)
                    try:
                        can0.send(msg)
                        #print(f"Message sent on can0: {msg}")
                    except can.CanError:
                        print("Failed to send message")



if __name__ == "__main__":
    ###print python-can version---
    print("python-can version:", can.__version__)
    ###send can data---
    send_can_data('can0', [0x01], b'\x01\x89\xfd\x86\x13\x00\x00\x00')
    
