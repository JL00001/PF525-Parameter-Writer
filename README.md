# PF525-Parameter-Writer
Code base to interact with AB Power Flex 525 drives

# WHAT
This is my personal code base for a project I work on in the slow times during work. Rapid deployment of Power Flex 525 parameters. This will load-in an Excel file and write out the parameter values to their respected parameter at their respected drive IP

# WHY
Because Rockwell didn't have a way to deploy parameters on mass or a way to audit parameters across the network; and my employer's way is to set parameters by hand. This lead to only the very necessary parameters being set and those not absolutely required for drive operation being forgotten.

This may seem like a trivial issue; but when you are installing 400 Power Flex 525 on one area of a site, then you will understand why I created this

# FEATURES
Loading and writing parameter from a excel file and deploying them to drives

Parameter dumping of all parameters from all drives on the network (all those that respond to a CIP discovery request) 

Writing a single parameter to all drives on the network

Reading a single parameter from all drives on the network

Searching for parameters whose value are not a given value

Placing all PF 525 drives on the network in to an autotune state (very handy indeed) and recovery from state after the autotune test has concluded

Drive Health Scanner (Just runs through all drives on the network, and checking their Parameters based on MY EMPLOYER'S standards. Your results may vary)

# WARNING 
Writing to drives under operation can be dangerous! 
Please use this with caution! I studied Electrical Engineering with an interest in programing, I am not a safety expert or do I claimed to be. Use at your own risk
  
# PLANS
GUI at some point; cleaning up code base (Delayed Indef) I have been hearing that the PF525 might be end of life. The code base might be reused in some form

# CREDITS
ottowayi's wounderful pycomm3. https://github.com/ottowayi/pycomm3 Of which this codebase would not be possible. My codebase is just a object wrapper of sorts on his library. His library does the low level CIP network packet creation and he has helped many times during development of this codebase.

pjkundert's CPPPO. https://github.com/pjkundert/cpppo While still under constrution, I plan on using CPPPO to create a "dummy" drive to read/write CIP packets too. As of now; it can read/write data from/to the dummy drive. Why? Because PowerFlex 525 Drives are expensive, and if anyone has one and wants to send me it, ill be open to it. 

Currently, Network Parameter Dump, does not work with the dummy drive. This is due to the use of the custom CIP method "scattered read". This custom CIP method allowes the Parameter Dump to pull 63 parameter in one call; Speeding up downloading.


