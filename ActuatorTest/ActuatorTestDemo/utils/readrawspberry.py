def rawspberry_temp(path = "/sys/class/thermal/thermal_zone0/temp"):
        temperature =0.0
        try:
            with open(path,"r") as f:
                  content = f.read()
                  temperature = float(content)/1000
                  print(temperature)
        except Exception as error:
              print(error)
        finally:
            return temperature
        

if __name__ == "__main__":
    rawspberry_temp()