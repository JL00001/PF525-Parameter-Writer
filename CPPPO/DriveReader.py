from cpppo.server.enip.get_attribute import proxy_simple

class powerflex( proxy_simple ):
    pass
    
class powerflex_750_series( powerflex ):
    """Specific parameters and their addresses, for the PowerFlex 750 Series AC drives."""
    PARAMETERS				= dict( powerflex.PARAMETERS,
	output_frequency		= powerflex.parameter( '@0x93/  1/9',	'INT',		'Hz' ),
	output_freq 			= powerflex.parameter( '@0x93/  1/9',	'INT',		'Hz' ),
	mtr_vel_fdbk 			= powerflex.parameter( '@0x93/  3/9',	'INT',		'Hz/RPM' ), # See = Speed Units
	motor_velocity 		    = powerflex.parameter( '@0x93/  3/9',	'INT',		'Hz/RPM' ), # See = Speed Units
	output_current			= powerflex.parameter( '@0x93/  7/9',	'INT',		'Amps' ),
	output_voltage		    = powerflex.parameter( '@0x93/  8/9',	'INT',		'VAC' ),
	output_power			= powerflex.parameter( '@0x93/  9/9',	'INT',		'kW' ),
	dc_bus_volts			= powerflex.parameter( '@0x93/ 11/9',	'INT',		'VDC' ),
	elapsed_mwh			    = powerflex.parameter( '@0x93/ 13/9',	'INT',		'MWh' ),
	elapsed_kwh			    = powerflex.parameter( '@0x93/ 14/9',	'INT',		'kWh' ),
	elapsed_run_time		= powerflex.parameter( '@0x93/ 15/9',	'INT',		'Hrs' ),
	rated_volts			    = powerflex.parameter( '@0x93/ 20/9',	'INT',		'VAC' ),
	rated_amps			    = powerflex.parameter( '@0x93/ 21/9',	'INT',		'Amps' ),
	rated_kw			    = powerflex.parameter( '@0x93/ 22/9',	'INT',		'kW' ),
	speed_units			    = powerflex.parameter( '@0x93/300/9',	'INT',		'Hz/RPM' ), # 0-->Hz, 1-->RPM
    )
    
    def Read(self, attribute, types):
    	return_data, = self.read([(attribute,types)])
    	return return_data


    def read_all(self):
        return_data = {}
        for x in self.PARAMETERS.keys():
            attribute = self.PARAMETERS[str(x)].attribute
            types = self.PARAMETERS[str(x)].types
            return_data[str(attribute)] = self.Read(attribute,types)
        return return_data
    
    
Object =  powerflex_750_series(host="192.168.1.143")

print(Object.read_all())
