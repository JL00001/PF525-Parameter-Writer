class ParameterObject():
    def __init__(self, ip, parameter, log==None):
        self.ip = ip
        self.Parameter = parameter
        if log==None:
            import logging
            self.log = logging.getLogger("ParameterObject")
        else:
            self.log = log
        self.DPI_Online_Read_Full = {}
        self.DPI_Descriptor = {}
        self.get_DPI_Online_Read_Full()
        self.get_DPI_Descriptor()
        Real_Value = ((self.DPI_Online_Read_Full["Internal_Value"] + self.DPI_Online_Read_Full["Offset"]) * self.DPI_Online_Read_Full["Multiplier"] * self.DPI_Online_Read_Full['Base']) / (self.DPI_Online_Read_Full["Divisor"] * pow(10, self.DPI_Descriptor["Decimal_Point"]))
        self.DPI_Online_Read_Full.update({"Real_Value": Real_Value})

    def get_DPI_Online_Read_Full(self):
        import pycomm3
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
            with pycomm3.CIPDriver(self.ip) as drive:
                result = drive.generic_message(
                    service=pycomm3.Services.get_attribute_single,
                    class_code=0x93,
                    instance=self.Parameter,     # Parameter
                    attribute=7,            # Method
                    connected=False,
                    route_path=False,
                    data_type=DPI_Online_Read_Full[1],
                )
        except pycomm3.CommError:
            log.critical("Connection to Drive Could Not Be Made")
            return None
        self.DPI_Online_Read_Full.update(result.value[0])

    def get_DPI_Descriptor(self):
        import ctypes
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