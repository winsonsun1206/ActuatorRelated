import os


def write_tmp_file(file_path = "/tmp/actuatortest.txt", content = ""):
    """
    将内容写入临时文件
    :param content: 要写入文件的内容，可以是字符串或字节数据
    """
    try:
        with open(file_path, 'w') as f:
            f.write(content)
            f.flush()  # 确保内容立即写入文件
            os.fsync(f.fileno())  # 确保文件系统将数据写入磁盘
        print(f"Content written to {file_path} successfully.")
    except Exception as e:
        print(f"Error writing to {file_path}: {e}") 


    if __name__ == "__main__":
        write_tmp_file(file_path="/home/winsonsun/tmp/actuatortest.txt", content="test ongoing.")

