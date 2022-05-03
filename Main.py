def main():
    import NetworkObject
    network = NetworkObject.NetworkObject()
    #network.network_drive_health()
    network.network_parameter_dump()

if __name__ == "__main__":
    main()


"""
network.Dev_Add_Drive("192.168.1.1")
network.list_of_drive_objects["192.168.1.1"] 
network.load_parameters_from_excel("Full Drive Parameter Template.xlsx")
network.network_autoTune_drive()
network.network_drive_health()
network.network_masked_autoTune_drive(Network, mask)
network.network_parameter_dump()
network.network_parameter_search(41, 100)
network.network_read_parameter(41)
network.network_write_parameter(41,100)
network.single_read_parameter("192.168.1.1",41)
network.single_write_parameter("192.168.1.1",41,100)
"""




"""
network.list_of_drive_objects["192.168.1.1"].detailed_read_all_pf525_data()
network.list_of_drive_objects["192.168.1.1"].drive_autotune()
network.list_of_drive_objects["192.168.1.1"].read_all_pf525_data()
network.list_of_drive_objects["192.168.1.1"].read_pf525_logic_command()
network.list_of_drive_objects["192.168.1.1"].read_pf525_parameter(41)
network.list_of_drive_objects["192.168.1.1"].scattered_read([496,498,500])

write_params = [
            (496, 0),
            (498, 0),
            (500, 0)]
     
network.list_of_drive_objects["192.168.1.1"].scattered_write(write_params)
network.list_of_drive_objects["192.168.1.1"].write_pf525_parameter(41,100)
"""
