import Objects
import pycomm3
import ipaddress



def main():

    network = Objects.NetworkObject()
    #network.network_parameter_dump("Test")
    #network.network_drive_health()
    #print(network.list_of_drive_objects["172.16.11.11"].detailed_read_all_pf525_data())


    write_params = [
        (573, 3),
        (41, 100),
        (42, 100)]
    network.list_of_drive_objects["172.16.21.14"].scattered_write(write_params)









if __name__ == "__main__":
    main()



#network.network_AutoTuned()
#network.network_drive_health()
#network.single_drive_amazon("11.200.3.21")
#network.single_drive_auto("11.200.3.21")
#network.network_drive_write(157,3)
#network.single_drive_read("172.16.18.12",42)
#network.network_parameter_search(41, 1)
#network.network_parameter_search(42, 1)
#network.single_write_parameter("172.16.18.12",40,1)
#network.single_drive_auto("172.16.18.12")
#network.single_drive_manual("172.16.18.12")
#network.single_drive_autotune("172.16.18.12")

#network.all_network_drive_autoTune()
#network.network_masked_drive_autoTune("172.16.41.16","255.255.255.252")
#network.network_parameter_dump("Test")
#print(network.list_of_drive_objects["172.16.41.17"].read_all_pf525_data())
#network.list_of_drive_objects["172.16.41.17"].read_all_pf525_data()
#network.load_Parameters_from_excel("Parameter.xlsx")
