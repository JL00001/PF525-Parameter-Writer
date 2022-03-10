Due to the fact that json files are not able to be commented, this file will server as the the README for using DriveHealthScanner

Firmwear Verson:
	5.001 == 5001 or 5.002 == 5002
	"firmwear_verson":5002,

Max Drive Speed:
	In certain drives, the 60Hz limit may not be enough to reach the target speed. In general, no more than 10% variation from this limit should be alowed.
	60Hz == 6000 or 70Hz == 7000
	"drive_max_speed":6000,

Drive Comm Loss:
	1 Sec == 10
	"drive_comm_loss":10,

Dynamic Brake and Brake Messages:
	Will suppress dynamic brake and brake messages.
	When "true" will print off drives that have parameters that should have dynamic brakes or regular brakes.
	The engineer should cross reference this output with the drawings 
	"db_and_brk_msg":false,
	
Ethernet Subnet Parameters:
	255.255.0.0 == [255,255,0,0]
	"en_subnet_parameters":
	{
	"value":[255,255,0,0]
	},
	
Ethernet Data Out Parameters
	The data that corresponds to parameters [157,158,159,160]
	This is the data being able to be pulled from the ethernet interface.
	See PowerFlex Parameter Manual 
	"en_data_out_parameters":
	{
	"value":[0,0,0,0]
	}
	
Backup of drive configs

{
  "firmwear_verson":5002,
  "drive_max_speed":6000,
  "drive_comm_loss":10,
  "db_and_brk_msg":false,
  "en_subnet_parameters":
  {
    "value":[255,255,0,0]
  },
  "en_data_out_parameters":
  {
    "value":[0,0,0,0]
  }
}