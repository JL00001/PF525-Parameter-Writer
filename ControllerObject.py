class ControllerObject():
    def __init__(self, ip, log=None):
        if log==None:
            import logging
            self.log = logging.getLogger("Drive " + ip)
        else:
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
            self.log.critical("More Than One Possible Slots For PLC Processer")
            self.log.critical(list_of_possible_processer_slots)
            list_of_possible_processer_slots_str = list_of_possible_processer_slots
            self.log.critical("Select Which Slot Is The Correct One")
            for x in range(len(list_of_possible_processer_slots)):
                list_of_possible_processer_slots[x] = str(list_of_possible_processer_slots_str[x])
            x = True
            while(x):
                user_input = input("Enter your value: ")
                if user_input in list_of_possible_processer_slots:
                    x = False
                else:
                    self.log.critical("User Input Isnt In The Above List")
            return user_input

    def __get_module_info(self, slot):
        import pycomm3
        with pycomm3.CIPDriver(self.ip) as driver:
            logging.getLogger("pycomm3.cip_driver.CIPDriver").disabled = True
            try:
                data = driver.get_module_info(slot)
            except pycomm3.exceptions.ResponseError:
                data = None
            finally:
                logging.getLogger("pycomm3.cip_driver.CIPDriver").disabled = False
                return data
