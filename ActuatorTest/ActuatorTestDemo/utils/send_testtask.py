import pika
import json
import requests
import click
import argparse
from dataclasses import dataclass, asdict
import pickle

@dataclass
class TestSlot:
    part_number: str
    serial_number: str
    can_msg_id: int
    can_bus_id: int



def get_unacked_count(queue_name, host, port, username, password):
    url = f'http://{host}:{port}/api/queues/%2F/{queue_name}'
    response = requests.get(url, auth=(username, password), timeout=15)
    if response.status_code == 200:
        data = response.json()
        return data.get('messages_unacknowledged', 1), data.get('messages_ready', 1)
    else:
        print(f"Failed to get queue info: {response.status_code} - {response.text}")
        return 1,1

def send_test_task(test_slot, queue_name, host, port, operation="runin_test"):
    credentials = pika.PlainCredentials('admin', 'ni50509800')
    connection = pika.BlockingConnection(pika.ConnectionParameters(host, port, '/', credentials))  
    channel = connection.channel()
      
#
    
    task_data = {
        "task_id": "12345",
        "task_name": "RunIntest_Task",
        "operation": operation,
        "parameters": test_slot  # Serialize the test condition string
    }
    message = pickle.dumps(task_data)  # Convert dataclass to dict before dumping to JSON
    # print(message)
    # print("-"*40)
    # print(pickle.loads(message)["parameters"])
    # print(pickle.loads(message)["parameters"][0].part_number)
    remaining_count, ready_count = get_unacked_count(queue_name, host, 15672, 'admin', 'ni50509800')
    if remaining_count > 0:
        print(f"⚠️ Warning: There are already messages in the '{queue_name}' queue. number is {remaining_count}. Consider processing them before adding new tasks.")
    else:
        channel.basic_publish(exchange='', routing_key=queue_name, body=message)
        print(f" [x] Sent message to {queue_name}")
    connection.close()
        

# parser = argparse.ArgumentParser(description= "runintest_command")
# parser.add_argument("-t", "--testcondition", help="string of test condition")
# args = parser.parse_args()



if __name__ == "__main__":
    test_slots = []
    while True:
        test_condition = input("Enter test condition (or 'exit' to quit): ")
        if test_condition.lower() == 'exit':
            break
        # Here you can parse the test_condition string into a TestSlot object
        # For simplicity, let's assume the input is in the format: "PN123,SN456,3,1"
        try:
            part_number, serial_number, can_msg_id, can_bus_id, operation, queue_name = test_condition.split(',')
            test_slot = TestSlot(part_number=part_number.strip(), serial_number=serial_number.strip(), can_msg_id=int(can_msg_id.strip()), can_bus_id=int(can_bus_id.strip()))
            test_slots.append(test_slot)
        except ValueError:
            print("Invalid input format. Please enter in the format: 'PN123','SN456',3,1,'runin_test','runintest_queue'")
    if test_slots:
        send_test_task(test_slots, queue_name=queue_name.strip(), host='192.168.2.47', port=5672, operation=operation.strip())