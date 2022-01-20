import pycomm3
import json
import pandas as pd
import multiprocessing
import os
import ipaddress
import logging
import time
import keyboard
import ctypes

class DriveObject():
    def __init__(self, plc_ip, plc_processer_slot, drive_ip,log):
        self.log = log
        self.drive_ip = ipaddress.ip_address(str(drive_ip))
        self.Drive_Path = plc_ip + '/bp/' + \
            str(plc_processer_slot) + '/enet/' + str(drive_ip)

    def read_pf525_parameter(self, Instance):
        return(self.__read_pf525_data(b'\x93', int(Instance), b'\x09', 'INT'))

    def read_pf525_logic_command(self):
        return(self.__read_pf525_data(pycomm3.ClassCode.register, b'\x14', b'\x04', 'INT'))

    def __read_pf525_data(self, Class_Code, instance, Attribute, DataType):
        try:
            with pycomm3.CIPDriver(self.Drive_Path) as drive:
                result = drive.generic_message(
                    service=pycomm3.Services.get_attribute_single,
                    class_code=Class_Code,
                    instance=instance,
                    attribute=Attribute,
                    connected=False,
                    unconnected_send=True,
                    route_path=True,
                    data_type=pycomm3.INT
                )
                if result.error == "Device state conflict":
                    raise DeviceStateConflict(self.log)
        except pycomm3.CommError:
            self.log.critical("Connection to Drive Could Not Be Made")
            return None
        self.log.info("Read : {0:3} From Class Code: {1:3} Instance: {2:7} At Drive: {3:20}".format(str(result.value), str(Class_Code), str(instance), str(self.drive_ip)))
        return(result.value)

    def read_all_pf525_data(self,dic = None,lock = None):
        y = self.__read_pf525_data(b'\x93', 0, b'\x00', 'INT')
        if y is None:
            return None
        list_of_parameters_to_read = []
        for x in range(1,y+1):
            list_of_parameters_to_read.append(x)
        return_data = self.scattered_read(list_of_parameters_to_read)
        self.log.info("All Data Read From Drive At: " + self.Drive_Path)
        if dic == None or lock == None:
            return return_data
        else:
            lock.acquire()
            dic[str(self.drive_ip)] = return_data
            lock.release()
            return

    def detailed_read_all_pf525_data(self,dic = None,lock = None):
        y = self.__read_pf525_data(b'\x93', 0, b'\x00', 'INT')
        if y is None:
            return None
        return_data = []
        self.log.critical("Time One")
        for x in range(1,y+1):
            #return_data.append(Parameter(self.Drive_Path,x,self.log).return_All_Data())
            Parameter(self.Drive_Path,x,self.log)
        self.log.critical("Time Two")
        if dic == None or lock == None:
            return return_data
        else:
            lock.acquire()
            dic[str(self.drive_ip)] = return_data
            lock.release()
            return

    def write_pf525_parameter(self, Parameter, Value, Check=True):
        self.__write_pf525_data(b'\x93', Parameter, Value, b'\x09', Check)

    def write_pf525_logic_command(self, Value):
        self.__write_pf525_data(pycomm3.ClassCode.register, b'\x14', Value, b'\x04', False)

    def write_pf525_logic_timeout(self, timeout):
        self.__write_pf525_data(
            pycomm3.ClassCode.register, b'\x00', timeout, b'\x64', False)

    def __write_pf525_data(self, Class_Code, instance, request_data, Attribute, Check):
        try:
            with pycomm3.CIPDriver(self.Drive_Path) as drive:
                result = drive.generic_message(
                    service=pycomm3.Services.set_attribute_single,
                    class_code=Class_Code,
                    instance=instance,  # Parameter
                    attribute=Attribute,
                    request_data=pycomm3.INT.encode(request_data),  # value
                    connected=False,
                    unconnected_send=True,
                    route_path=True
                    )
                if result.error == "Device state conflict":
                    raise DeviceStateConflict(self.log)
        except pycomm3.CommError:
            self.log.critical("Connection to Drive Could Not Be Made")
            return
        self.log.info("Wrote: {0:3} to Class Code  : {1:3} Instance: {2:7} At Drive: {3:20}".format(str(request_data), str(Class_Code), str(instance), str(self.drive_ip)))
        if Check:
            if self.read_pf525_parameter(instance) != request_data:
                self.log.critical("Parameter {0:3} Data Write To Drive {1:15} Has Failed".format(str(instance),str(self.drive_ip)))
            else:
                self.log.warning("Parameter {0:3} Data Write To Drive {1:15} Was Successful".format(str(instance),str(self.drive_ip)))

    def drive_autotune(self):
        timeout = 45
        # Saves the current value of parameter 46 to memory
        Value46 = self.read_pf525_parameter(46)
        # Saves the current value of parameter 47 to memory
        Value47 = self.read_pf525_parameter(47)
        # Set the CIP Command Timeout. This will cause a fatal fault if the drive doesnt hear back from the control or program after a set amount of time
        self.write_pf525_logic_timeout(timeout)
        try:
            self.write_pf525_parameter(46, 5)  # Sets 46 to value 5
            self.write_pf525_parameter(47, 15)  # Sets 47 to value 15
            if self.read_pf525_logic_command() != 1:
                self.write_pf525_logic_command(8)
            # Sends a stop command to the drive
            self.write_pf525_logic_command(0)
            # Set Parameter 40 to 1, telling the drive to static tune
            self.write_pf525_parameter(40, 1)
            # Clear Motor Rr parameter (498). Polling parameter 498; The resistance of the motor, will give us a idea if the process is done
            self.write_pf525_parameter(498, 0)
            # Sent a start command to the drive; just like pushing the start button
            self.write_pf525_logic_command(2)
            x = 0
            while(x < timeout):
                time.sleep(1)
                x = x + 1
                if self.read_pf525_parameter(498) != 0:
                    break
                #print("\rSleeping: {0} Seconds Have Passed".format(x), end="\r")
            #print("")
            #print("Done")
            # Telling the drive to stop "running"
            self.write_pf525_logic_command(1)
        except DeviceStateConflict:
            return
        finally:
            # Setting the CIP Command Timeout back to 0 disabling it
            self.write_pf525_logic_timeout(0)
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
            with pycomm3.CIPDriver(self.Drive_Path) as pf525:
                result = pf525.generic_message(
                    service=0x32,
                    class_code=0x93,
                    instance=0,
                    connected=False,
                    unconnected_send=True,
                    route_path=True,
                    request_data=ParamItem[len(read_params)].encode(read_params),
                    data_type=ParamItem[len(read_params)],
                )
                if result.error == "Device state conflict":
                    raise DeviceStateConflict(self.log)
        except pycomm3.CommError:
            self.log.critical("Connection to Drive Could Not Be Made")
            return None
        self.log.debug("Read: {0:3} From Class Code: {1:3} Instance: {2:3} At Drive: {3:20}".format(str(result.value), str(b'0x93'), str(0), str(self.drive_ip)))
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
        with pycomm3.CIPDriver(self.Drive_Path) as pf525:
            result = pf525.generic_message(
                service=0x34,
                class_code=0x93,
                instance=0,
                connected=False,
                unconnected_send=True,
                route_path=True,
                request_data=ParamItem[len(write_params)].encode(write_params),
                data_type=ParamItem[len(write_params)],
            )
        self.log.info("Wrote: {0:3} to Class Code  : {1:3} Instance: {2:7} At Drive: {3:20}".format(str(write_params), str(0x93), str(0), str(self.drive_ip)))

class NetworkObject():
    def __init__(self,loggingLevel=30,LoggingFile=None):
        self.__loggerSetup(loggingLevel, LoggingFile, "PowerFlex 525 Data Logger")
        self.__discover_network_devices()

    def __discover_network_devices(self):
        manager =  multiprocessing.Manager()
        self.list_of_drive_objects = manager.dict()
        self.list_of_plcs_objects = manager.dict()
        self.discovery_process = multiprocessing.Process(target=discover_network_devices, args=(self.list_of_drive_objects, self.list_of_plcs_objects, self.log))
        self.discovery_process.start()
        self.Scanner = True
        keyboard.add_hotkey('esc', self.__esc)
        self.log.critical("Starting Scanner Process. Wait Until All Drives Have Been Found And Then Press 'ESC'")
        try:
            while self.Scanner:
                time.sleep(1)
                print("The Scanner Process Has Found: {0:3} Drives and {1:1} Processer".format(len(self.list_of_drive_objects.keys()),len(self.list_of_plcs_objects.keys())),end = "\r")
        except:
            self.discovery_process.terminate()

    def __esc(self):
        self.discovery_process.terminate()
        self.Scanner = False
        keyboard.remove_hotkey("esc")

    def __del__(self):
        try:
            self.discovery_process.terminate()
        except:
            pass

    def __autoTune_list_of_drives(self,list):
        list_of_autotuneing_drives = []
        for x in list:
            if x in self.list_of_drive_objects.keys():
                New_Process = multiprocessing.Process(target=self.list_of_drive_objects[x].drive_autotune)
                New_Process.start()
                self.log.info("Created New Process: {0:5} For Autotuneing PowerFlex At {1:15}".format(New_Process.pid,str(self.list_of_drive_objects[x].drive_ip)))
                list_of_autotuneing_drives.append(New_Process)
            else:
                self.log.debug("A Command Was Given To Autotune A Drive, But That Drive Is Not In The List Of Drive Objects. Passing")
        for x in list_of_autotuneing_drives:
            self.log.info("Joining Drive Process: {0:5}".format(x.pid))
            x.join()

    def all_network_drive_autoTune(self):
        self.__autoTune_list_of_drives(self.list_of_drive_objects.keys())

    def network_masked_drive_autoTune(self, ip_address, mask):
        try:
            network = ipaddress.IPv4Network(str(ip_address) + "/" + str(mask))
        except ValueError:
            self.log.critical("IP Address And / Or Mask Is Not Correct")
            return
        list_of_drives_to_autotune = []
        for x in network.hosts():
            list_of_drives_to_autotune.append(str(x))
        self.__autoTune_list_of_drives(list_of_drives_to_autotune)

    def single_read_parameter(self, ip, parameter):
        if self.__return_list_number_for_ip(ip) != None:
            return(self.list_of_drive_objects[self.__return_list_number_for_ip(ip)].read_pf525_parameter(parameter))
        else:
            self.log.critical("Drive Could Not Be Found")
            return("Drive Could Not Be Found")

    def single_write_parameter(self, ip, parameter, value):
        ip = str(ip)
        if ip in self.list_of_drive_objects.keys():
            self.list_of_drive_objects[ip].write_pf525_parameter(parameter, value)
        else:
            self.log.critical("Drive Could Not Be Found")
            return

    def network_drive_health(self, Write=False, **kwargs):
        drive_health_data = json.load(open('DriveHealthConfig.json',))
        self.log.warning("Starting Drive Health Scanner")
        list_of_parameters_to_read = [6,29,41,42,44,46,47,62,63,64,65,66,67,68,76,126,128,437,498,544,545,573]
        for x in self.list_of_drive_objects.keys():
            return_data = self.list_of_drive_objects[x].scattered_read(list_of_parameters_to_read)
            data = {
                "6":return_data[0],
                "29":return_data[1],
                "41":return_data[2],
                "42":return_data[3],
                "44":return_data[4],
                "46":return_data[5],
                "47":return_data[6],
                "62":return_data[7],
                "63":return_data[8],
                "64":return_data[9],
                "65":return_data[10],
                "66":return_data[11],
                "67":return_data[12],
                "68":return_data[13],
                "76":return_data[14],
                "126":return_data[15],
                "128":return_data[16],
                "437":return_data[17],
                "498":return_data[18],
                "544":return_data[19],
                "545":return_data[20],
                "573":return_data[21]
            }
            drive_ip_local = str(self.list_of_drive_objects[x].drive_ip)
            if ((data["6"] & 0x0001) == 0):
                drive_is_writeable = True and Write
            else:
                drive_is_writeable = False and Write

            if(data["544"] != 1):
                self.log.warning(drive_ip_local + " Hasn't Had Reverse Disabled")

            if(data["498"] == 0):
                self.log.warning(drive_ip_local + " Hasn't Been AutoTuned")

            if(data["545"] != 0):
                self.log.warning(drive_ip_local + " Hasn't Had Flying Start Disabled")
                if(drive_is_writeable):
                    self.self.list_of_drive_objects[x].write_pf525_parameter(545, 0)

            if(drive_health_data["EN_Data_Out_Parameters"]["enabled"]):
                if len(drive_health_data["EN_Data_Out_Parameters"]["parameters"]) == len(drive_health_data["EN_Data_Out_Parameters"]["correct values"]):
                    for y in range(len(drive_health_data["EN_Data_Out_Parameters"]["parameters"])):
                        if (self.list_of_drive_objects[x].read_pf525_parameter(drive_health_data["EN_Data_Out_Parameters"]["parameters"][y]) != drive_health_data["EN_Data_Out_Parameters"]["correct values"][y]):
                            self.log.warning(drive_ip_local + " Has Wrong EN Data Out_Parameters Set: {0}".format(drive_health_data["EN_Data_Out_Parameters"]["parameters"][y]))
                            if(drive_is_writeable):
                                self.list_of_drive_objects[x].write_pf525_parameter(drive_health_data["EN_Data_Out_Parameters"]["parameters"][y], drive_health_data["EN_Data_Out_Parameters"]["correct values"][y])
                else:
                    self.log.critical("Length Of 'EN_Data_Out_Parameters:parameters' Does Not Match The Length 'EN_Data_Out_Parameters:correct values' In DriveHealthConfig")

            if(data["44"] != drive_health_data["drive_max_speed"]):
                self.log.warning(drive_ip_local + " Has The Wrong MAX FREQ")
                if(drive_is_writeable):
                    self.self.list_of_drive_objects[x].write_pf525_parameter(44, drive_health_data["drive_max_speed"])

            if(data["29"] != drive_health_data["firmwear_verson"]):
                self.log.warning(drive_ip_local + " Has The Wrong FirmWear Version")

            if((data["46"] != 5) or (data["47"] != 15)):
                self.log.warning(drive_ip_local + " Drive Not Placed In Auto Mode")

            if(data["41"] == 1000) or (data["42"] == 1000):
                self.log.warning(drive_ip_local + " Drive Accel/Decel Parameters Are Default Values")

            if(data["41"] < 100 or data["42"] < 100):
                if(data["437"] == 0):
                    self.log.warning(drive_ip_local + " The Accel/Decel Is Too Fast For There Not To Be A Dynamic Break Attached")

            if(data["76"] == 0):
                self.log.warning(drive_ip_local + " Parameter 76 Is A Default Value. Change to 2 or 13")

            if(drive_health_data["db_and_brk_msg"]):
                if(data["76"] == 2):
                    self.log.warning(drive_ip_local + " Parameter 76 Implies That There Is A BRK Attached To This Drive")

                if(data["437"] != 0):
                    self.log.warning(drive_ip_local + " Parameter 437 Implies That There Is A Dynamic Braking Resistor Attached To This Drive")
            """
            if(self.list_of_drive_objects[x].read_pf525_parameter(133) == 0 and self.list_of_drive_objects[x].read_pf525_parameter(134) == 0 and self.list_of_drive_objects[x].read_pf525_parameter(135) == 0 and self.list_of_drive_objects[x].read_pf525_parameter(136) == 0):
                self.log.warning(
                    str(self.list_of_drive_objects[x].drive_ip) + " EN Subnet Not Set")

            if(self.list_of_drive_objects[x].read_pf525_parameter(137) == 0 and self.list_of_drive_objects[x].read_pf525_parameter(138) == 0 and self.list_of_drive_objects[x].read_pf525_parameter(139) == 0 and self.list_of_drive_objects[x].read_pf525_parameter(140) == 0):
                self.log.warning(
                    str(self.list_of_drive_objects[x].drive_ip) + " EN Gateway Not Set")

            if len(drive_health_data["en_subnet_parameters"]["value"]) == 4:
                list = [133, 134, 135, 136]
                for y in range(4):
                    if (self.list_of_drive_objects[x].read_pf525_parameter(list[y]) != drive_health_data["en_subnet_parameters"]["value"][y]):
                        self.log.warning(
                            str(self.list_of_drive_objects[x].drive_ip) + " Has Wrong Subnet Parameters Set")
                        break

            else:
                self.log.critical(
                    " Length Of 'en_subnet_parameters:value' In DriveHealthConfig.json Does Not Match The Length Of 4")

            if len(drive_health_data["en_gw_parameters"]["value"]) == 4:
                list = [137, 138, 139, 140]

                for y in range(4):

                    if (self.list_of_drive_objects[x].read_pf525_parameter(list[y]) != drive_health_data["en_gw_parameters"]["value"][y]):
                        self.log.warning(
                            str(self.list_of_drive_objects[x].drive_ip) + " Has Wrong Gateway Parameters Set")
                        if(drive_is_writeable):
                            self.list_of_drive_objects[x].write_pf525_parameter(
                                list[y], drive_health_data["en_gw_parameters"]["value"][y])

            else:
                self.log.critical(
                    " Length Of 'en_gw_parameters:value' In DriveHealthConfig.json Does Not Match The Length Of 4")
            """
            if(data["41"] < 100 or data["42"] < 100):
                if (data["573"] != 2):
                    self.log.warning(drive_ip_local + " Jerk Parameters Have Been Incorrectly Set. Needs To Be: 2")
                    if(drive_is_writeable):
                        self.list_of_drive_objects[x].write_pf525_parameter(573, 2)
            else:
                if (data["573"] != 3):
                    self.log.warning(drive_ip_local + " Jerk Parameters Have Been Incorrectly Set. Needs To Be: 3")
                    if(drive_is_writeable):
                        self.list_of_drive_objects[x].write_pf525_parameter(573, 3)

            if(data["126"] != drive_health_data["drive_comm_loss"]):
                self.log.warning(drive_ip_local + " COMM Lost Parameter Hasnt Been Set Properly")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(126, drive_health_data["drive_comm_loss"])

            if(data["128"] != 1):
                self.log.warning(drive_ip_local + " Drive Is Using BOOTP")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(128, 1)

            if(data["62"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 02 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(62, 0)

            if(data["63"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 03 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(63, 0)

            if(data["64"] != 0):
                self.log.warning(drive_ip_local + " 2-Wire Mode Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(64, 0)

            if(data["65"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 05 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(65, 0)

            if(data["66"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 06 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(66, 0)

            if(data["67"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 07 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(67, 0)

            if(data["68"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 08 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[x].write_pf525_parameter(68, 0)

        self.log.warning("Ending Drive Health Scanner")

    def network_parameter_search(self, parameter, value):
        return_data = []
        for x in self.list_of_drive_objects.keys():
            result = self.list_of_drive_objects[x].read_pf525_parameter(
                parameter)
            if (result != value):
                return_data.append(
                    [str(self.list_of_drive_objects[x].drive_ip), result])
        return return_data

    def network_drive_write(self, parameter, value):
        for x in self.list_of_drive_objects.keys():
            self.list_of_drive_objects[x].write_pf525_parameter(
                parameter, value)

    def network_drive_read(self, parameter):
        dic = {}
        for x in self.list_of_drive_objects.keys():
            dic[x] = self.list_of_drive_objects[x].read_pf525_parameter(parameter)
        return dic

    def network_parameter_dump(self, file):
        import Excel_Dump_Lables
        data = []
        list_of_reading_drive_process = []
        self.log.warning("Creating Drive Reading Treads")
        lock = multiprocessing.Lock()
        manager = multiprocessing.Manager()
        dic = manager.dict()
        for x in self.list_of_drive_objects.keys():
            New_Process = multiprocessing.Process(target=self.list_of_drive_objects[x].read_all_pf525_data,args=(dic,lock))
            New_Process.start()
            self.log.info("Created New Process: {0:5} For Reading All Parameter On Drive: {1:15}".format(New_Process.pid, str(self.list_of_drive_objects[x].drive_ip)))
            list_of_reading_drive_process.append(New_Process)
        self.log.warning("Joining Drive Reading Treads")
        for x in list_of_reading_drive_process:
            self.log.info("Joining Drive Process: {0:5}".format(x.pid))
            x.join()
        for x in dic.keys():
            data.append(dic[x])
        df1 = pd.DataFrame(data, index=dic.keys(), columns=range(1,732))
        df1 = df1.sort_index(ascending=True)
        df1 = df1.T
        df2 = pd.DataFrame(Excel_Dump_Lables.Lables, index=range(1,732), columns=["Name"])
        df = pd.concat([df2, df1], axis=1)
        df.to_excel(file + ".xlsx")
        self.log.warning("Excel File Saved")

    def load_Parameters_from_excel(self, Filename):
        try:
            open(Filename, 'r')
        except PermissionError:
            self.log.critical("The File Is Open In Another Process. Please Close That And Start Again")
            return
        DataFrame = pd.read_excel(Filename,index_col=0)
        self.log.debug(DataFrame)
        Parameters = DataFrame.copy()
        Parameters = Parameters.index.values
        self.log.debug(Parameters)
        ParameterValue = DataFrame.copy()
        ParameterValue = ParameterValue.iloc[1:, 1:]
        self.log.debug(ParameterValue)
        for row in ParameterValue.iteritems():
            ip = row[0]
            for parametervalue in row[1].items():
                parameter = parametervalue[0]
                value = parametervalue[1]
                try:
                    int(parameter)
                    int(value)
                    #print(f"Ip Address : {ip}, Parameter {parameter}, Value: {int(value)}")
                    self.single_write_parameter(ip, int(parameter), int(value))
                except ValueError:
                    pass

    def __loggerSetup(self, loggerLevel=10, loggerFile=None, loggerName=None):

        if loggerName is None:
            name = 'TestProgram'
        else:
            name = loggerName
        format = '%(asctime)s|%(name)-' + str(len(name)) + \
            's| %(levelname)-8s| %(message)s'
        datefmt = '%Y-%m-%d %H:%M:%S'
        cwd = os.getcwd()
        if loggerFile is None:
            logging.basicConfig(format=format, datefmt=datefmt)
        else:
            filename = cwd + "/" + loggerFile
            logging.basicConfig(filename=filename,
                                format=format, datefmt=datefmt)
        if loggerName is None:
            self.log = logging.getLogger('TestProgram')
        else:
            self.log = logging.getLogger(loggerName)
        self.log.setLevel(loggerLevel)
        self.log.debug("Logger Is Loaded")

class Controller():
    def __init__(self, ip, log):
        self.log = log
        self.ip = ip
        self.slot = self.__scan_for_processer_slot()

    def __scan_for_processer_slot(self):
        list_of_possible_processer_slots = []
        for x in range(4):
            result = self.__get_module_info(x)
            try:
                if (result['product_type'] == 'Programmable Logic Controller'):
                    list_of_possible_processer_slots.append(x)
            except TypeError:
                pass

        if (len(list_of_possible_processer_slots) == 1):
            return list_of_possible_processer_slots[0]
        else:
            self.log.critical(
                "More Than One Possible Slots For PLC Processer")
            self.log.critical(list_of_possible_processer_slots)
            list_of_possible_processer_slots_str = list_of_possible_processer_slots
            self.log.critical("Select Which Slot Is The Correct One")
            for x in range(len(list_of_possible_processer_slots)):
                list_of_possible_processer_slots[x] = str(
                    list_of_possible_processer_slots_str[x])
            x = True
            while(x):
                user_input = input("Enter your value: ")
                if user_input in list_of_possible_processer_slots:
                    x = False
                else:
                    self.log.critical("User Input Isnt In The Above List")
            return user_input

    def __get_module_info(self, slot):
        with pycomm3.CIPDriver(self.ip) as driver:
            logging.getLogger("pycomm3.cip_driver.CIPDriver").disabled = True
            try:
                data = driver.get_module_info(slot)
            except pycomm3.exceptions.ResponseError:
                data = None
            finally:
                logging.getLogger("pycomm3.cip_driver.CIPDriver").disabled = False
                return data

class DeviceStateConflict(Exception):
    def __init__(self, log):
        self.log = log
        self.log.critical("The Drive Is Not In The Correct State")
        self.log.critical("Inhibit The Drive In The I/O Tree Or Place The Whole Controller In Program Mode")

def discover_network_devices(list_of_drive_objects, list_of_plcs_objects,log):
    while True:
        list_of_nodes = pycomm3.CIPDriver.discover()
        for x in list_of_nodes:
            if "ip_address" in x:
                if(x["product_type"] == "Programmable Logic Controller"):
                    if(x["product_name"][0:4] == "1756"):
                        ipaddress = str(x['ip_address'])
                        list_of_plcs_objects[ipaddress] = Controller(ipaddress, log)
        if len(list_of_plcs_objects.keys()) != 0:
            for x in list_of_nodes:
                if "ip_address" in x:
                    if(x["product_name"][0:13] == "PowerFlex 525"):
                        if x['ip_address'] not in list_of_drive_objects.keys():
                            ipaddress = str(x['ip_address'])
                            plc_object = list_of_plcs_objects[list_of_plcs_objects.keys()[0]]
                            list_of_drive_objects[ipaddress] = DriveObject(plc_object.ip, plc_object.slot, ipaddress, log)

class Parameter():
    def __init__(self, drive_path, parameter, log):
        self.Drive_Path = drive_path
        self.Parameter = parameter
        self.log = log
        self.DPI_Online_Read_Full = {}
        self.DPI_Descriptor = {}
        self.get_DPI_Online_Read_Full()
        self.get_DPI_Descriptor()
        Real_Value = ((self.DPI_Online_Read_Full["Internal_Value"] + self.DPI_Online_Read_Full["Offset"]) * self.DPI_Online_Read_Full["Multiplier"] * self.DPI_Online_Read_Full['Base']) / (self.DPI_Online_Read_Full["Divisor"] * pow(10, self.DPI_Descriptor["Decimal_Point"]))
        self.DPI_Online_Read_Full.update({"Real_Value": Real_Value})

    def get_DPI_Online_Read_Full(self):
        DPI_Online_Read_Full = pycomm3.Struct( pycomm3.DINT("Descriptor"),
                                    pycomm3.DINT("Internal_Value"),
                                    pycomm3.DINT("Minimum_Value"),
                                    pycomm3.DINT("Maximum_Value"),
                                    pycomm3.DINT("Default_Value"),
                                    pycomm3.UINT("Next_Parameter"),
                                    pycomm3.UINT("Previous_Parameter"),
                                    pycomm3.n_bytes(4,"Units"),
                                    pycomm3.UINT("Multiplier"),
                                    pycomm3.UINT("Divisor"),
                                    pycomm3.UINT("Base"),
                                    pycomm3.INT("Offset"),
                                    pycomm3.USINT(""),
                                    pycomm3.USINT(""),
                                    pycomm3.USINT(""),
                                    pycomm3.USINT(""),
                                    pycomm3.n_bytes(16,"Parameter_Name"))
        try:
            with pycomm3.CIPDriver(self.Drive_Path) as pf525:
                result = pf525.generic_message(
                    service=pycomm3.Services.get_attribute_single,
                    class_code=0x93,
                    connected=False,
                    unconnected_send=True,
                    route_path=True,
                    instance=self.Parameter,     # Parameter
                    attribute=7,            # Method
                    data_type=DPI_Online_Read_Full[1],
                )
        except pycomm3.CommError:
            log.critical("Connection to Drive Could Not Be Made")
            return None
        self.DPI_Online_Read_Full.update(result.value[0])

    def get_DPI_Descriptor(self):
        class Map(ctypes.Structure):
            _fields_ = [("Data_Type", ctypes.c_uint8, 3),                           #PG 144 for what these mean
                        ("Sign_Type", ctypes.c_uint8, 1),
                        ("Hidden", ctypes.c_uint8, 1),
                        ("Not_a_Link_Sink", ctypes.c_uint8, 1),
                        ("Not_Recallable", ctypes.c_uint8, 1),
                        ("ENUM", ctypes.c_uint8, 1),
                        ("Writable", ctypes.c_uint8, 1),                            # Is a 0 When Parameter Is Read Only, 1 When Writeable
                        ("Not_Writable_When_Enabled", ctypes.c_uint8, 1),           # Is a 1 When Parameter Cannot Be Writen When Dive Is On
                        ("Instance", ctypes.c_uint8, 1),
                        ("Uses_Bit_ENUM_Mask", ctypes.c_uint8, 1),
                        ("Decimal_Point", ctypes.c_uint8, 4),
                        ("Extended_Data_Type", ctypes.c_uint8, 3),
                        ("Parameter_Exists", ctypes.c_uint8, 1),
                        ("Not_Used", ctypes.c_uint8, 1),
                        ("Formula_Links", ctypes.c_uint8, 1),
                        ("Access_Level", ctypes.c_uint8, 3),
                        ("Writable_ENUM", ctypes.c_uint8, 1),
                        ("Not_a_Link_Source", ctypes.c_uint8, 1),
                        ("Enhanced_Bit_ENUM", ctypes.c_uint8, 1),
                        ("Enhanced_ENUM", ctypes.c_uint8, 1),
                        ("Uses_DSI_Limits_Object", ctypes.c_uint8, 1),
                        ("Extended_Descriptor", ctypes.c_uint8, 1),
                        ("Always_Upload_Download", ctypes.c_uint8, 1)]
            def return_dic(self):
                dic = {}
                for field in self._fields_:
                    dic[field[0]] = getattr(self, field[0])
                return(dic)
        class Int(ctypes.Structure):
            _fields_ = [("Value", ctypes.c_uint32)]
        class union(ctypes.Union):
            _fields_ = [("Descriptor", Int),("Map",Map)]
        Results = union(Int(self.DPI_Online_Read_Full['Descriptor']))
        self.DPI_Descriptor.update(Results.Map.return_dic())

    def return_All_Data(self):
        All_Data = {}
        All_Data.update(self.DPI_Online_Read_Full)
        All_Data.update(self.DPI_Descriptor)
        return All_Data
