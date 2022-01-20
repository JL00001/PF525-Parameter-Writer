# PF525-Parameter-Writer
Code base to interact with AB PowerFlex 525 drives

# WHAT
This is my personal code base for a project I work on in the slow times during work. Rapid deployment of PowerFlex 525 parameters. This will load in a Excel file and write out the parameter values to their respected parameter at their respected drive IP

# WHY
Because Rockwell didn't have a way to deploy parameters on mass or a way to audit parameters accross the network; and my employer's way of setting parameters was by hand. This lead to only the very necessary parameters being set and thoese not absolutly required for drive operation being passed over.

This may seem like a trival issue; but when you are installing 400 PowerFlex 525 on one area of a site, then you will understand why I created this

# FEATURES
Loading and writing parameter from a excel file and deploying them to drives

Parameter dumping all parameters from all drives on the network (all thoses that respond to a CIP discovery request) 

Writing a single parameter to all drives on the network

Reading a single parameter from all drives on the network

Searching for parameters who's value are not a given value

Placing all PF 525 drives on the network in to a autotune state (very handy indeed)

# WARINING
Writing to drives under operation can be dangerous! 
Please, for the love of what ever god you pray to, use this with caution! I studied Electical Enginering with a intrest in programing, I am not a safety expert or do i clame to be. Should you cause a accident, and you try to sue me; this paragraph will server as defence evidence 1. Should anyone know more about safely writing to drives, and would be willing to help make my program safer, I am all ears
  
  
# PLANS
GUI at some point; cleaning up code base
