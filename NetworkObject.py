#logging.getLogger("pycomm3.cip_driver.CIPDriver").setLevel(level=logging.DEBUG)
class NetworkObject():
    def __init__(self,loggingLevel=30,LoggingFile=None):
        self.__loggerSetup(loggingLevel, LoggingFile, "PowerFlex 525 Data Logger")
        self.__discover_network_devices()

    def __discover_network_devices(self):
        import multiprocessing
        import keyboard
        manager =  multiprocessing.Manager()
        self.list_of_drive_objects = manager.dict()
        self.discovery_process = multiprocessing.Process(target=discover_network_devices, args=(self.list_of_drive_objects, self.log))
        self.discovery_process.start()
        self.Scanner = True
        keyboard.add_hotkey('esc', self.__esc)
        self.log.critical("Starting Scanner Process. Wait Until All Drives Have Been Found And Then Press 'ESC'")
        try:
            import time
            while self.Scanner:
                time.sleep(1)
                print("The Scanner Process Has Found: {0:3} Drives".format(len(self.list_of_drive_objects.keys())),end = "\r")
        except:
            self.discovery_process.terminate()

    def __esc(self):
        import keyboard
        self.discovery_process.terminate()
        self.Scanner = False
        keyboard.remove_hotkey("esc")

    def __del__(self):
        try:
            self.discovery_process.terminate()
        except:
            pass

    def __autoTune_list_of_drives(self,list):
        import multiprocessing
        list_of_autotuneing_drives = []
        for x in list:
            if x in self.list_of_drive_objects.keys():
                New_Process = multiprocessing.Process(target=self.list_of_drive_objects[x].drive_autotune)
                New_Process.start()
                self.log.info("Created New Process: {0:5} For Autotuneing PowerFlex At {1:15}".format(New_Process.pid,self.list_of_drive_objects[x].ip))
                list_of_autotuneing_drives.append(New_Process)
            else:
                self.log.debug("A Command Was Given To Autotune A Drive, But That Drive Is Not In The List Of Drive Objects. Passing")
        for x in list_of_autotuneing_drives:
            self.log.info("Joining Drive Process: {0:5}".format(x.pid))
            x.join()

    def network_autoTune_drive(self):
        self.__autoTune_list_of_drives(self.list_of_drive_objects.keys())

    def network_masked_autoTune_drive(self, ip, mask):
        try:
            network = ipaddress.IPv4Network(ip + "/" + str(mask))
        except ValueError:
            self.log.critical("IP Address And / Or Mask Is Not Correct")
            return
        list_of_drives_to_autotune = []
        for x in network.hosts():
            list_of_drives_to_autotune.append(str(x))
        self.__autoTune_list_of_drives(list_of_drives_to_autotune)

    def single_read_parameter(self, ip, parameter):
        if ip in self.list_of_drive_objects.keys():
            return(self.list_of_drive_objects[ip].read_pf525_parameter(parameter))
        else:
            self.log.critical("Drive Could Not Be Found")
            return("Drive Could Not Be Found")

    def single_write_parameter(self, ip, parameter, value):
        if ip in self.list_of_drive_objects.keys():
            self.list_of_drive_objects[ip].write_pf525_parameter(parameter, value)
        else:
            self.log.critical("Drive Could Not Be Found")
            return

    def network_drive_health(self, Write=False):
        import json
        drive_health_data = json.load(open('DriveHealthConfig.json',))
        self.log.warning("Starting Drive Health Scanner")
        list_of_parameters_to_read = [6,29,41,42,44,46,47,62,63,64,65,66,67,68,76,81,105,126,128,437,498,544,545,573]
        for drive_ip_local in sorted(self.list_of_drive_objects.keys()):
            return_data = self.list_of_drive_objects[drive_ip_local].scattered_read(list_of_parameters_to_read)
            data = {
                "6":return_data[0],         #Current Status Of The Drive (If Running)
                "29":return_data[1],        #Firmware Version
                "41":return_data[2],        #Accel Time
                "42":return_data[3],        #Decel Time
                "44":return_data[4],        #Max Hz
                "46":return_data[5],        #Start Source 1
                "47":return_data[6],        #Speed Source 1
                "62":return_data[7],        #DigIn TermBlk 02
                "63":return_data[8],        #DigIn TermBlk 03
                "64":return_data[9],        #2-Wire Mode
                "65":return_data[10],       #DigIn TermBlk 05
                "66":return_data[11],       #DigIn TermBlk 06
                "67":return_data[12],       #DigIn TermBlk 07
                "68":return_data[13],       #DigIn TermBlk 08       
                "76":return_data[14],       #Relay Out1 Sel
                "81":return_data[15],       #Relay Out2 Sel
                "105":return_data[16],      #Safety Open En         (Suppresses Motor Fault On Safety Open (E-Stop Pulled))
                "126":return_data[17],      #Comm Loss Time
                "128":return_data[18],      #EN Addr Sel            (BOOTP vs Static IP)
                "437":return_data[19],      #DB Resistor Sel        (Setting For Dynamic Break Value)
                "498":return_data[20],      #Motor Rr               (Motor Resistance)
                "544":return_data[21],      #Reverse Disable
                "545":return_data[22],      #Flying Start En
                "573":return_data[23]       #Mtr Options Cfg        (Jerk Config)
            }
            if ((data["6"] & 0x0001) == 0):
                drive_is_writeable = True and Write
            else:
                drive_is_writeable = False and Write
 
            if len(drive_health_data["en_data_out_parameters"]["value"]) == 4:
                if (self.list_of_drive_objects[drive_ip_local].scattered_read([157,158,159,160]) != drive_health_data["en_data_out_parameters"]["value"]):
                    self.log.warning(drive_ip_local + " Has Wrong EN Data Out_Parameters Set: {0}".format(drive_health_data["EN_Data_Out_Parameters"]["parameters"][y]))
                    if(drive_is_writeable):
                        write_params = [
                        (157, drive_health_data["en_data_out_parameters"]["value"][0]),
                        (158, drive_health_data["en_data_out_parameters"]["value"][1]),
                        (159, drive_health_data["en_data_out_parameters"]["value"][2]),
                        (160, drive_health_data["en_data_out_parameters"]["value"][3])]
                        network.list_of_drive_objects[drive_ip_local].scattered_write(write_params)
            else:
                self.log.critical("Length Of 'EN_Data_Out_Parameters:parameters' Does Not Match The Length 'EN_Data_Out_Parameters:correct values' In DriveHealthConfig")
                
            if len(drive_health_data["en_subnet_parameters"]["value"]) == 4:
                if (self.list_of_drive_objects[drive_ip_local].scattered_read([133, 134, 135, 136]) != drive_health_data["en_subnet_parameters"]["value"]):
                    self.log.warning(drive_ip_local + " Has Wrong Subnet Parameters Set")
                    if(drive_is_writeable):
                        write_params = [
                        (133, drive_health_data["en_subnet_parameters"]["value"][0]),
                        (134, drive_health_data["en_subnet_parameters"]["value"][1]),
                        (135, drive_health_data["en_subnet_parameters"]["value"][2]),
                        (136, drive_health_data["en_subnet_parameters"]["value"][3])]
                        self.list_of_drive_objects[drive_ip_local].scattered_write(write_params)

            else:
                self.log.critical("Length Of 'en_subnet_parameters' In DriveHealthConfig.json Does Not Match The Length Of 4")
            
            if(self.list_of_drive_objects[drive_ip_local].scattered_read([133, 134, 135, 136]) == [0,0,0,0]):
                self.log.warning(drive_ip_local + " EN Gateway Not Set")
                
            if(data["544"] != 1):
                self.log.warning(drive_ip_local + " Hasn't Had Reverse Disabled")

            if(data["498"] == 0):
                self.log.warning(drive_ip_local + " Hasn't Been AutoTuned")
                
            if(data["41"] == 1000) or (data["42"] == 1000):
                self.log.warning(drive_ip_local + " Drive Accel/Decel Parameters Are Default Values")
                
            if(data["29"] != drive_health_data["firmwear_verson"]):
                self.log.warning(drive_ip_local + " Has The Wrong FirmWear Version")
                
            if(data["46"] != 5 or data["47"] != 15):
                self.log.warning(drive_ip_local + " Drive Not Placed In Auto Mode")

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

            if(data["545"] != 0):
                self.log.warning(drive_ip_local + " Hasn't Had Flying Start Disabled")
                if(drive_is_writeable):
                    self.self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(545, 0)

            if(data["44"] != drive_health_data["drive_max_speed"]):
                self.log.warning(drive_ip_local + " Has The Wrong MAX FREQ")
                if(drive_is_writeable):
                    self.self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(44, drive_health_data["drive_max_speed"])
                
            if(data["41"] < 100 or data["42"] < 100):
                if (data["573"] != 2):
                    self.log.warning(drive_ip_local + " Jerk Parameters Have Been Incorrectly Set. Needs To Be: 2")
                    if(drive_is_writeable):
                        self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(573, 2)
            else:
                if (data["573"] != 3):
                    self.log.warning(drive_ip_local + " Jerk Parameters Have Been Incorrectly Set. Needs To Be: 3")
                    if(drive_is_writeable):
                        self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(573, 3)

            if(data["126"] != drive_health_data["drive_comm_loss"]):
                self.log.warning(drive_ip_local + " COMM Lost Parameter Hasnt Been Set Properly")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(126, drive_health_data["drive_comm_loss"])

            if(data["128"] != 1):
                self.log.warning(drive_ip_local + " Drive Is Using BOOTP")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(128, 1)

            if(data["62"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 02 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(62, 0)

            if(data["63"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 03 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(63, 0)

            if(data["64"] != 0):
                self.log.warning(drive_ip_local + " 2-Wire Mode Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(64, 0)

            if(data["65"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 05 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(65, 0)

            if(data["66"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 06 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(66, 0)

            if(data["67"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 07 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(67, 0)

            if(data["68"] != 0):
                self.log.warning(drive_ip_local + " DigIn TermBlk 08 Has Not Been Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(68, 0)
                    
            if(data["81"] == 0):
                self.log.warning(drive_ip_local + " Parameter 81 Is A Default Value. Change to 0")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(81, 0)
                    
            if(data["105"] != 0):
                self.log.warning(drive_ip_local + " Has Not Had Safety Open Fault Disabled")
                if(drive_is_writeable):
                    self.list_of_drive_objects[drive_ip_local].write_pf525_parameter(105, 0)

        self.log.warning("Ending Drive Health Scanner")

    def network_parameter_search(self, parameter, value):
        return_data = []
        for x in self.list_of_drive_objects.keys():
            result = self.list_of_drive_objects[x].read_pf525_parameter(
                parameter)
            if (result != value):
                return_data.append([self.list_of_drive_objects[x].ip, result])
        return return_data

    def network_write_parameter(self, parameter, value):
        for x in self.list_of_drive_objects.keys():
            self.list_of_drive_objects[x].write_pf525_parameter(parameter, value)

    def network_read_parameter(self, parameter):
        dic = {}
        for x in self.list_of_drive_objects.keys():
            dic[x] = self.list_of_drive_objects[x].read_pf525_parameter(parameter)
        return dic

    def network_parameter_dump(self, file="Drive Parameter Dump"):
        import Excel_Dump_Lables
        import multiprocessing
        import pandas as pd
        self.log.warning("Creating Drive Reading Treads")
        pool = multiprocessing.Pool(32)
        dic = {}
        list = []
        for y in pool.map(read_all_pf525_data_process, self.list_of_drive_objects.keys()):
            dic[y["drive"]] = y["data"]
        data = []
        for x in dic.keys():
            data.append(dic[x])
        df1 = pd.DataFrame(data, index=dic.keys(), columns=range(1,732))
        df1 = df1.sort_index(ascending=True)
        df1 = df1.T
        df2 = pd.DataFrame(Excel_Dump_Lables.Lables, index=range(1,732), columns=["Name"])
        df = pd.concat([df2, df1], axis=1)
        self.log.warning("Writing To Excel")
        try:
            df.to_excel(file + ".xlsx")
        except PermissionError:
            self.log.critical("Close Out The Excel File As I Am Trying To Write To It")
            self.log.critical("Press Any Key When Ready")
            input()
            self.log.warning("Writing To Excel")
            df.to_excel(file + ".xlsx")
        self.log.warning("Excel File Saved")

    def load_parameters_from_excel(self, Filename):
        import pandas as pd
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

    def Dev_Add_Drive(self,ip):
        import DriveObject
        self.list_of_drive_objects[ip] = DriveObject.DriveObject(ip, self.log)
     
    def __loggerSetup(self, loggerLevel=10, loggerFile=None, loggerName=None):
        import os
        import logging
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

def discover_network_devices(list_of_drive_objects,log):
    import pycomm3
    import DriveObject
    while True:
        list_of_nodes = pycomm3.CIPDriver.discover()
        for x in list_of_nodes:
            if "ip_address" in x:
                if(x["product_name"][0:13] == "PowerFlex 525"):
                    if x['ip_address'] not in list_of_drive_objects.keys():
                        ipaddress = x['ip_address']
                        list_of_drive_objects[ipaddress] = DriveObject.DriveObject(ipaddress, log)

def read_all_pf525_data_process(ip):
    import DriveObject
    return DriveObject.DriveObject(ip).read_all_pf525_data()

