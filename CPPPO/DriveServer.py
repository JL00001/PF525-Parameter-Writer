import sys, logging
from Excel_Dump_Lables import Lables
from cpppo.server import enip
from cpppo.server.enip.main import main as enip_main

class DPI_Parameters( enip.Object ):
    class_id			= 0x93
    def __init__( self, name=None, **kwds ):
        super( DPI_Parameters, self ).__init__( name=name, **kwds )
        if self.instance_id == 0:
            pass
        else:
            self.attribute['9']= enip.Attribute( Lables[self.instance_id],	enip.INT, default=self.instance_id )
            
class scattered_read( enip.Object ):
    class_id			= 0x93
    def __init__( self, name=None, **kwds ):
        super( scattered_read, self ).__init__( name=name, **kwds )
        self.attribute['50']= enip.Attribute( Lables[self.instance_id],	enip.INT, default=self.instance_id )
            

def main( **kwds ):
    enip.config_files 	       += [ __file__.replace( '.py', '.cfg' ) ]
    for x in range(1,731):
        DPI_Parameters( name="DPI_Parameters", instance_id=x )
    return enip_main( argv=sys.argv[1:])

sys.exit( main( attribute_class=main))






