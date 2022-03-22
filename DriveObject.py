import pycomm3

class DriveObject():
    def __init__(self,ip,log=None):
        import ipaddress
        if log==None:
            import logging
            self.log = logging.getLogger("Drive " + ip)
        else:
            self.log = log
        self.ip_object = ipaddress.ip_address(ip)
        self.ip = str(self.ip_object)

    def __str__(self):
        return self.read_all_pf525_data()
    
    def read_pf525_parameter(self, Instance):
        return(self.__read_pf525_data(b'\x93', int(Instance), b'\x09'))

    def read_pf525_logic_command(self):
        return(self.__read_pf525_data(pycomm3.ClassCode.register, b'\x14', b'\x04'))

    def __read_pf525_data(self, class_code, instance, attribute, dataType=pycomm3.INT):
        try:
            with pycomm3.CIPDriver(self.ip) as drive:
                result = drive.generic_message(
                    service=pycomm3.Services.get_attribute_single,
                    class_code=class_code,
                    instance=instance,
                    attribute=attribute,
                    data_type=dataType,
                    connected=False,
                    route_path=False,
                )
                if result.error == "Device state conflict":
                    raise DeviceStateConflict(self.log)
        except pycomm3.CommError:
            raise CommError(self.log)
        self.log.info("Read : {0:3} From Class Code: {1:3} Instance: {2:7} At Drive: {3:20}".format(str(result.value), str(class_code), str(instance), self.ip))
        return(result.value)

    def read_all_pf525_data(self):
        y = self.__read_pf525_data(b'\x93', 0, b'\x00')
        if y is None:
            return None
        list_of_parameters_to_read = []
        for x in range(1,y+1):
            list_of_parameters_to_read.append(x)
        return_data = self.scattered_read(list_of_parameters_to_read)
        self.log.info("All Data Read From Drive At: " + self.ip)
        data = {}
        data["drive"] = self.ip
        data["data"] = return_data
        return data

    def detailed_read_all_pf525_data(self):
        import ParameterObject
        y = self.__read_pf525_data(b'\x93', 0, b'\x00')
        if y is None:
            return None
        return_data = []
        for x in range(1,y+1):
            return_data.append(ParameterObject.Parameter(self.ip,x,self.log).return_All_Data())
        return return_data

    def write_pf525_parameter(self, Parameter, Value, Check=True):
        self.__write_pf525_data(b'\x93', Parameter, Value, b'\x09', Check)

    def __write_pf525_logic_command(self, Value):
        self.__write_pf525_data(pycomm3.ClassCode.register, b'\x14', Value, b'\x04', False)

    def __write_pf525_logic_timeout(self, timeout):
        self.__write_pf525_data(
            pycomm3.ClassCode.register, b'\x00', timeout, b'\x64', False)

    def __write_pf525_data(self, class_code, instance, request_data, attribute, check):
        try:
            with pycomm3.CIPDriver(self.ip) as drive:
                result = drive.generic_message(
                    service=pycomm3.Services.set_attribute_single,
                    class_code=class_code,
                    instance=instance,  # Parameter
                    attribute=attribute,
                    connected=False,
                    route_path=False,
                    request_data=pycomm3.INT.encode(request_data),  # value
                    )
                if result.error == "Device state conflict":
                    raise DeviceStateConflict(self.log)
        except pycomm3.CommError:
            raise CommError(self.log)
        self.log.info("Wrote: {0:3} to Class Code  : {1:3} Instance: {2:7} At Drive: {3:20}".format(str(request_data), str(class_code), str(instance), self.ip))
        if check:
            if self.read_pf525_parameter(instance) != request_data:
                self.log.critical("Parameter {0:3} Data Write To Drive {1:15} Has Failed".format(str(instance),self.ip))
            else:
                self.log.warning("Parameter {0:3} Data Write To Drive {1:15} Was Successful".format(str(instance),self.ip))

    def drive_autotune(self):
        import time
        timeout = 60
        # Saves the current value of parameter 46 to memory
        Value46 = self.read_pf525_parameter(46)
        # Saves the current value of parameter 47 to memory
        Value47 = self.read_pf525_parameter(47)
        # Set the CIP Command Timeout. This will cause a fatal fault if the drive doesnt hear back from the control or program after a set amount of time
        self.__write_pf525_logic_timeout(timeout)
        try:
            self.write_pf525_parameter(46, 5)  # Sets 46 to value 5
            self.write_pf525_parameter(47, 15)  # Sets 47 to value 15
            if self.read_pf525_logic_command() != 1:
                self.__write_pf525_logic_command(8)
            # Sends a stop command to the drive
            self.__write_pf525_logic_command(0)
            # Set Parameter 40 to 1, telling the drive to static tune
            self.write_pf525_parameter(40, 1)
            # Clear Motor Rr parameter (498). Polling parameter 498; The resistance of the motor, will give us a idea if the process is done
            self.write_pf525_parameter(498, 0)
            # Sent a start command to the drive; just like pushing the start button
            self.__write_pf525_logic_command(2)
            x = 0
            while(x < timeout):
                time.sleep(1)
                x = x + 1
                if self.read_pf525_parameter(498) != 0:
                    break
            # Telling the drive to stop "running"
            self.__write_pf525_logic_command(1)
        except DeviceStateConflict:
            return
        finally:
            # Setting the CIP Command Timeout back to 0 disabling it
            self.__write_pf525_logic_timeout(0)
            # Loads the saved value of parameter 46 back to the drive
            self.write_pf525_parameter(46, Value46)
            # Loads the saved value of parameter 47 back to the drive
            self.write_pf525_parameter(47, Value47)

    def __scattered_read(self,read_list):
        """
        read_params = [
            (496, 0),
            (498, 0),
            (500, 0)]
        """
        read_params = []
        for x in read_list:
            read_params.append(tuple([x,0]))
        ParamItem = pycomm3.Struct(pycomm3.UINT("parameter"), pycomm3.UINT('value'))
        try:
            with pycomm3.CIPDriver(str(self.ip)) as pf525:
                result = pf525.generic_message(
                    service=0x32,
                    class_code=0x93,
                    instance=0,
                    connected=False,
                    route_path=False,
                    request_data=ParamItem[len(read_params)].encode(read_params),
                    data_type=ParamItem[len(read_params)],
                )
                if result.error == "Device state conflict":
                    raise DeviceStateConflict(self.log)
        except pycomm3.CommError:
            raise CommError(self.log)
        self.log.debug("Read: {0:3} From Class Code: {1:3} Instance: {2:3} At Drive: {3:20}".format(str(result.value), str(b'0x93'), str(0), self.ip))
        return_data = []
        for x in result.value:
            return_data.append(x['value'])
        return return_data

    def scattered_read(self,read_list):
        return_data = []
        for x in range(0, len(read_list), 64):
            return_data = return_data + self.__scattered_read(read_list[x : x + 64])
        return return_data

    def scattered_write(self,write_params):
        ParamItem = pycomm3.Struct(pycomm3.UINT("parameter"), pycomm3.UINT('value'))
        with pycomm3.CIPDriver(self.ip) as pf525:
            result = pf525.generic_message(
                service=0x34,
                class_code=0x93,
                instance=0,
                connected=False,
                route_path=False,
                request_data=ParamItem[len(write_params)].encode(write_params),
                data_type=ParamItem[len(write_params)],
            )
        self.log.info("Wrote: {0:3} to Class Code  : {1:3} Instance: {2:7} At Drive: {3:20}".format(str(write_params), str(0x93), str(0), self.ip))
        
class DeviceStateConflict(Exception):
    def __init__(self, log):
        self.log = log
        self.log.critical("The Drive Is Not In The Correct State")
        self.log.critical("Inhibit The Drive In The I/O Tree Or Place The Whole Controller In Program Mode")
        
class CommError(Exception):
    def __init__(self, log):
        self.log = log
        self.log.critical("The Drive Could Not Be Reached")
